# Authorization

wenchang does not authenticate anyone. You decide who the caller is. wenchang takes your answer and enforces it: the caller can only reach the scopes and entities you grant, and can only write the scopes your policy allows.

In the legend, Wenchang's two attendants are Tianlong, who cannot hear, and Diya, who cannot speak. That way no secret gets out. A resolver is the same arrangement in Python.

## What you provide {#contract}

Three pieces plug in.

1. **`credentials_from_context(ctx)`** reads the caller's raw credentials from the MCP request. It must be a plain function, not async. Over HTTP, `ctx.headers` holds the request headers. On stdio it is `None`, so a stdio server reads credentials from its own environment instead. Return the raw value and do not trust it here.
2. **A resolver** with one method, `resolve(credentials) -> Identity | ResolutionFailure`. It verifies the credentials and returns an `Identity`: a mapping from scope name to `ScopeGrant(entity_id, role)`. Roles are your own words (`owner`, `member`, `admin`).
3. **A `ScopePolicy`** mapping a scope to the set of roles allowed to write it. A scope not listed is open to every role that holds a grant. The `system/` area is read-only in every scope regardless.

Every tool call runs all three. The agent never sees credentials and never passes an entity ID. It passes `scope`, `area`, and `name`, and the tool layer fills in the entity ID from the caller's grant for that scope. A caller cannot name another user's path.

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
- **The resolver runs on every tool call.** Cache inside it if verification is expensive, and expire cache entries with the token.
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

## Other transports {#transports}

- **stdio.** The client starts one server process per session, so identity usually comes from the process environment: an environment variable holding a token, or the grants themselves for a single-developer setup as in [Setup](setup.md#server). Return it from `credentials_from_context` as `os.environ.get("MEMORY_TOKEN")` and let the resolver verify it.
- **HTTP.** `server.run("streamable-http", host=..., port=...)` serves the MCP endpoint at `/mcp` by default. Put TLS in front of it. The MCP SDK also has its own auth options on `MCPServer` (`auth`, `token_verifier`) if you want requests rejected before they reach wenchang. See the `mcp` documentation. The HTTP example here builds and its resolver was exercised directly, but it was not run against a live MCP client.
- **An existing MCP server.** Use `register_memory_tools` to add the tools to a server you already run, with your own auth in front. See [Reference](reference.md#embed).

## Test your resolver {#testing}

`pip install "wenchang[testing]"` adds pytest mixins in `wenchang.testing`. Subclass `ResolverConformance` and supply fixtures for your resolver, a valid and an invalid credential, your policy, the scopes a valid credential should get, and the roles you use. It checks that valid credentials give an `Identity`, invalid ones give a `ResolutionFailure`, results are consistent, roles are known, and writes follow your policy. Details are in the [reference](reference.md#conformance).
