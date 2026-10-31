# Identity and multi-tenant auth

wenchang does not authenticate anyone. You decide who the caller is. wenchang takes your answer and enforces it: the caller can only reach the scopes and entities you grant, and can only write the scopes your policy allows.

In the legend, Wenchang's two attendants are Tianlong, who cannot hear, and Diya, who cannot speak. That way no secret gets out. A resolver is the same arrangement in Python.

## How identity flows {#flow}

Every tool call goes through the same chain, on every integration path:

```
credentials          raw, untrusted data from the request
   |  credentials_from_context(ctx)    (MCP: runs on every tool call)
   |  or your code passes them         (direct: bind_tools(..., credentials, ...))
   v
resolver.resolve(credentials)          verifies them; returns Identity or ResolutionFailure
   v
Identity                               scope -> ScopeGrant(entity_id, role)
   v
path                                   {scope}/{entity_id}/{area}/{name}.md, from the grant
   v
ScopePolicy                            may this role write this scope?
```

The agent passes only `scope`, `area`, and `name`. The entity ID always comes from the caller's grant, so a caller cannot name another tenant's path. Reads need only a grant; writes also need a role the policy allows.

| Piece | What it owns | In an org, project, and user deployment |
| --- | --- | --- |
| Credentials | Whatever the request carries. Never trusted on their own. | A bearer token, plus an `X-Project-Id` header naming the open project. |
| `credentials_from_context` (MCP) or the caller (direct) | Getting credentials out of the request. No verification. | Reads the `Authorization` and `X-Project-Id` headers. |
| `IdentityResolver` | Verifying credentials and deciding the grants. Must not raise. | Verifies the token with your identity provider, then checks project membership in your database. |
| `Identity` | One `ScopeGrant(entity_id, role)` per scope the caller may use. | `user`: the user's ID, role `owner`. `project`: the project's ID, the user's role on it. `organization`: the org's ID, `member` or `admin`. |
| Path | Where a file lives, built from the grant. | `user/u-tianlong/...`, `project/p-ninth-examination/...`, `organization/o-hanlin-press/...`. |
| `ScopePolicy` | Which roles may write each scope. Unlisted scopes are open to any grant. | `organization` writable by `admin` and `owner` only. |

## What you provide {#contract}

Three pieces plug in.

1. **`credentials_from_context(ctx)`** reads the caller's raw credentials from the MCP request. It must be a plain function, not async. Over HTTP, `ctx.headers` holds the request headers. On stdio it is `None`, so a stdio server reads credentials from its own environment instead. Return the raw value and do not trust it here. Without MCP there is no such function: you pass the credentials to `bind_tools` yourself.
2. **A resolver** with one method, `resolve(credentials) -> Identity | ResolutionFailure`. It verifies the credentials and returns an `Identity`: a mapping from scope name to `ScopeGrant(entity_id, role)`. Roles are your own words (`owner`, `member`, `admin`).
3. **A `ScopePolicy`** mapping a scope to the set of roles allowed to write it. A scope not listed is open to every role that holds a grant. The `system/` area is read-only in every scope regardless.

Under MCP, every tool call runs all three. Without MCP, the resolver runs once per `bind_tools` call, which is why you [bind per request](integrate-without-mcp.md#per-request). The agent never sees credentials and never passes an entity ID. It passes `scope`, `area`, and `name`, and the tool layer fills in the entity ID from the caller's grant for that scope. A caller cannot name another user's path.

## A complete example {#example}

The example is a novelist's assistant served over HTTP to an author (Tianlong), an editor (Diya), and the press's editor-in-chief (Kuixing). Each request carries a bearer token and, optionally, a project header. The server has three scopes:

- `user`: the caller's own ID from the verified token.
- `project`: the manuscript named in `X-Project-Id`, if the caller is a member of it. Tianlong is its `author` and Diya its `editor`. A request with no project header gets no `project` scope, which is what Kuixing's requests look like.
- `organization`: the caller's publisher, Hanlin Press, writable only by admins and owners. Kuixing is an `admin`. Tianlong and Diya are `member`s and can read it but not write it.

<!--include python auth_http.py-->

Points to notice:

- **The user ID comes from the token, never from a header.** The project does come from a header, so the resolver checks membership before granting it. Treat every header as a request, not a fact.
- **`verify_token` and `project_role` are yours.** They stand for your identity provider or session store and your membership database. The stubs only make the file run.
- **The resolver does not raise.** A bad credential is a `ResolutionFailure`. The detail is shown to the agent, so never put a token or secret in it. If the resolver raises anyway, or `credentials_from_context` raises, the call fails with a permanent "memory unavailable" error that names only the exception type.
- **Under MCP the resolver runs on every tool call.** Cache inside it if verification is expensive, and expire cache entries with the token.
- **Entity IDs are path segments.** They must be non-empty and must not contain `/`, a backslash, or control characters. Use stable IDs. If a user's ID changes, their old files are still under the old ID.

## Behavior to expect {#behavior}

| Situation | Result |
| --- | --- |
| Resolver returns `ResolutionFailure` | Permanent error carrying your detail. No memory for that call. |
| Agent names a scope the caller has no grant for | `InvalidArgumentError` listing the scopes that are available. |
| Tianlong (a `member`) writes `organization` | `RestrictedScopeError`, reason `role_required`, with the permitted roles. |
| Anyone writes `system/` | `RestrictedScopeError`, reason `system_read_only`. |

<!--html-->
<div class="callout callout-warn"><strong>Reads are not restricted by role.</strong> A caller can read every area, including <code>system/</code>, of every scope it holds a grant for. <code>ScopePolicy</code> gates writes only. If a scope should not be readable by some people, do not grant it to them.</div>
<!--/html-->
<!--md-->
> **Reads are not restricted by role.** A caller can read every area, including `system/`, of every scope it holds a grant for. `ScopePolicy` gates writes only. If a scope should not be readable by some people, do not grant it to them.
<!--/md-->

The prompt also has to match the policy. If only admins can write `organization`, say that in `scope_guidance`, or the agent will try and fail. See [Customizing the prompts](prompts.md#scope-guidance).

## Transports {#transports}

The example serves streamable HTTP, where each request carries its own credentials. On stdio, one process serves one session, so credentials come from the process environment. [Transports](integrate-new-server.md#transports) covers both. To add the tools to a server you already run, with your own auth in front, see [Integrate: an existing mcp 2.x server](integrate-existing-server.md).

## Test your resolver {#testing}

`pip install "wenchang[testing] @ git+https://github.com/msiebert/wenchang"` adds pytest mixins in `wenchang.testing`. Subclass `ResolverConformance` and supply fixtures for your resolver, a valid and an invalid credential, your policy, the scopes a valid credential should get, and the roles you use. It checks that valid credentials give an `Identity`, invalid ones give a `ResolutionFailure`, results are consistent, roles are known, and writes follow your policy. Details are in the [reference](reference.md#conformance).
