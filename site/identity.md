# Identity and multi-tenant auth

wenchang does not authenticate anyone. You decide who the caller is. wenchang takes your answer and enforces it: the caller can only reach the scopes and entities you grant, and can only write the scopes your policy allows.

In the legend, Wenchang's two attendants are Tianlong, who cannot hear, and Diya, who cannot speak. That way no secret gets out. A resolver is the same arrangement in Python.

## How identity flows

Every tool call is checked against the same chain, on every integration path. Over MCP the whole chain runs on every tool call. Without MCP, credentials are resolved once per `bind_tools` call, and the path and policy checks run on every tool call:

```
credentials          raw, untrusted data from the request
   |  credentials_from_context(ctx)    (MCP: runs on every tool call)
   |  or your code passes them         (direct: bind_tools(..., credentials, ...))
   v
resolver.resolve(credentials)          verifies them; returns Identity or ResolutionFailure
   |                                   (MCP: every tool call; direct: once per bind_tools call)
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

## What you provide

Three pieces plug in.

1. **`credentials_from_context(ctx)`** reads the caller's raw credentials from the MCP request. It must be a plain function, not async. Over HTTP, `ctx.headers` holds the request headers. On stdio it is `None`, so a stdio server reads credentials from its own environment instead. Return the raw value and do not trust it here. Without MCP there is no such function: you pass the credentials to `bind_tools` yourself.
2. **A resolver** with one method, `resolve(credentials) -> Identity | ResolutionFailure`. It verifies the credentials and returns an `Identity`: a mapping from scope name to `ScopeGrant(entity_id, role)`. Roles are your own words (`owner`, `member`, `admin`). `resolve` must be a plain synchronous method. wenchang never awaits it, so an `async def resolve` returns a coroutine, and every call fails with `ResolverFailureError` ("Resolver ... returned coroutine, not Identity or ResolutionFailure.") on every integration path.
3. **A `ScopePolicy`** mapping a scope to the set of roles allowed to write it. A scope not listed is open to every role that holds a grant. The `system/` area is read-only in every scope regardless.

Under MCP, every tool call runs all three. Without MCP, the resolver runs once per `bind_tools` call, which is why you [bind per request](integrate-without-mcp.md#per-request). The agent never sees credentials and never passes an entity ID. It passes `scope`, `area`, and `name`, and the tool layer fills in the entity ID from the caller's grant for that scope. A caller cannot name another user's path.

## A complete example

The example is a novelist's assistant served over HTTP to an author (Tianlong), an editor (Diya), and the press's editor-in-chief (Kuixing). Each request carries a bearer token and, optionally, a project header. The server has three scopes:

- `user`: the caller's own ID from the verified token.
- `project`: the manuscript named in `X-Project-Id`, if the caller is a member of it. Tianlong is its `author` and Diya its `editor`. A request with no project header gets no `project` scope, which is what Kuixing's requests look like.
- `organization`: the caller's publisher, Hanlin Press, writable only by admins and owners. Kuixing is an `admin`. Tianlong and Diya are `member`s and can read it but not write it.

```python
import os
from collections.abc import Callable
from dataclasses import dataclass

from google.cloud import storage
from mcp.server.mcpserver import Context

from wenchang.core import MemoryStore
from wenchang.identity import Identity, ResolutionFailure, ScopeGrant
from wenchang.mcp import build_server
from wenchang.prompts import PromptSlots
from wenchang.scope import ScopePolicy
from wenchang.storage.gcs import GcsStorage
from wenchang.transport import InProcessClient


@dataclass(frozen=True)
class Claims:
    """What your identity provider says about a verified token."""

    user_id: str
    org_id: str
    org_role: str  # "member" or "admin"


@dataclass(frozen=True)
class Credentials:
    """What the request carries. Both fields are untrusted until the resolver checks them."""

    token: str
    project_id: str | None


class MembershipResolver:
    """Turns a request's credentials into the caller's grants. Must not raise."""

    def __init__(
        self,
        verify_token: Callable[[str], Claims | None],
        project_role: Callable[[str, str], str | None],
    ) -> None:
        self._verify_token = verify_token  # your IdP or session store
        self._project_role = project_role  # your membership database

    def resolve(self, credentials: Credentials | None) -> Identity | ResolutionFailure:
        if credentials is None:
            return ResolutionFailure("Missing bearer token.")
        claims = self._verify_token(credentials.token)
        if claims is None:
            return ResolutionFailure("Invalid or expired token.")
        grants = {
            "user": ScopeGrant(claims.user_id, "owner"),
            "organization": ScopeGrant(claims.org_id, claims.org_role),
        }
        if credentials.project_id is not None:
            # The project comes from a header, so check the user belongs to it.
            role = self._project_role(claims.user_id, credentials.project_id)
            if role is None:
                return ResolutionFailure("Not a member of the requested project.")
            grants["project"] = ScopeGrant(credentials.project_id, role)
        return Identity(grants=grants)


def credentials_from_context(ctx: Context) -> Credentials | None:
    headers = ctx.headers or {}
    auth = headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        return None
    return Credentials(token=auth.removeprefix("Bearer "), project_id=headers.get("x-project-id"))


# Stand-ins so the file runs; replace both with calls to your own systems.
TOKENS = {
    "tok-tianlong": Claims("u-tianlong", "o-hanlin-press", "member"),  # author
    "tok-diya": Claims("u-diya", "o-hanlin-press", "member"),  # editor
    "tok-kuixing": Claims("u-kuixing", "o-hanlin-press", "admin"),  # editor-in-chief
}
PROJECT_ROLES = {
    ("u-tianlong", "p-ninth-examination"): "author",
    ("u-diya", "p-ninth-examination"): "editor",
}


def verify_token(token: str) -> Claims | None:
    return TOKENS.get(token)


def project_role(user_id: str, project_id: str) -> str | None:
    return PROJECT_ROLES.get((user_id, project_id))


# Only admins and owners may write the organization scope.
policy = ScopePolicy({"organization": frozenset({"admin", "owner"})})

bucket = storage.Client(project="my-gcp-project").bucket(os.environ["WENCHANG_BUCKET"])

server = build_server(
    slots=PromptSlots(
        purpose=(
            "You have persistent memory of your work helping an author write a novel: reference "
            "it and save to it with these tools whenever you work on a manuscript."
        ),
        scope_guidance=(
            "There are three scopes. `user` is private to the person you are talking with. "
            "`project` is the manuscript, shared by its author, co-author, and editor; any of "
            "them may write it. `organization` is Hanlin Press, shared by every author and editor "
            "there; only editors-in-chief may write it. Writes to `user` and `project` need no "
            "ask. If a new fact contradicts one stored in a shared scope, show the stored fact "
            "and ask which to keep. If no project is open, you have no `project` scope."
        ),
        seed_areas=(
            "- user: preferences, workflows\n"
            "- project: characters, plot, timeline, style\n"
            "- organization: conventions\n\n"
            "Every scope also has a `system/` area."
        ),
    ),
    client=InProcessClient(
        MemoryStore(GcsStorage(bucket), scope_priority=("user", "project", "organization"))
    ),
    resolver=MembershipResolver(verify_token, project_role),
    policy=policy,
    credentials_from_context=credentials_from_context,
    source="inkwell-web",
    product="Inkwell",
)

if __name__ == "__main__":
    server.run("streamable-http", host="0.0.0.0", port=8000)  # behind your TLS proxy
```

Points to notice:

- **The user ID comes from the token, never from a header.** The project does come from a header, so the resolver checks membership before granting it. Treat every header as a request, not a fact.
- **`verify_token` and `project_role` are yours.** They stand for your identity provider or session store and your membership database. The stubs only make the file run.
- **The resolver does not raise.** A bad credential is a `ResolutionFailure`. The detail is shown to the agent, so never put a token or secret in it. If the resolver raises anyway, the call fails with a permanent `ResolverFailureError` whose message names only the exception's type, such as "Resolver MembershipResolver raised KeyError."
- **`credentials_from_context` should not raise either.** If it does, the call fails with a permanent `ResolverFailureError` with a fixed message, "Credentials could not be read from the request.", and only the exception's type is logged, since its message may carry the credential.
- **Under MCP the resolver runs on every tool call.** Without MCP it runs once per `bind_tools` call. Cache inside it if verification is expensive, and expire cache entries with the token.
- **Entity IDs are path segments.** They must be non-empty and must not contain `/`, a backslash, or control characters. Use stable IDs. If a user's ID changes, their old files are still under the old ID.

### The same resolver without MCP

`MembershipResolver` and `Credentials` from this example work unchanged with `bind_tools`. Read the token and project header from your own request, build `Credentials` from them, and pass it as `credentials`. Bind once per request:

```python
tools = bind_tools(
    client,
    MembershipResolver(verify_token, project_role),
    Credentials(token=bearer_token, project_id=request.headers.get("x-project-id")),
    policy,
    source="inkwell-api",
    product="Inkwell",
)
```

`bearer_token` and `request` stand for your framework's request. A bad token makes `bind_tools` raise `ResolverFailureError` with your detail. See [Integrate without MCP](integrate-without-mcp.md#per-request).

## Behavior to expect

| Situation | Result |
| --- | --- |
| Resolver returns `ResolutionFailure` | Permanent error carrying your detail. No memory for that call. |
| Resolver raises, or `resolve` is `async` | `ResolverFailureError` naming the exception type, or saying it returned a coroutine. |
| `credentials_from_context` raises | `ResolverFailureError`: "Credentials could not be read from the request." |
| Agent names a scope the caller has no grant for | `InvalidArgumentError` listing the scopes that are available. |
| Tianlong (a `member`) writes `organization` | `RestrictedScopeError`, reason `role_required`, with the permitted roles. |
| Anyone writes `system/` | `RestrictedScopeError`, reason `system_read_only`. |

> **Reads are not restricted by role.** A caller can read every area, including `system/`, of every scope it holds a grant for. `ScopePolicy` gates writes only. If a scope should not be readable by some people, do not grant it to them.

The prompt also has to match the policy. If only admins can write `organization`, say that in `scope_guidance`, or the agent will try and fail. See [Customizing the prompts](prompts.md#scope-guidance).

## Transports

The example serves streamable HTTP, where each request carries its own credentials. On stdio, one process serves one session, so credentials come from the process environment. [Transports](integrate-new-server.md#transports) covers both. To add the tools to a server you already run, with your own auth in front, see [Integrate: an existing mcp 2.x server](integrate-existing-server.md).

## Test your resolver

`pip install "wenchang[testing] @ git+https://github.com/msiebert/wenchang"` adds pytest mixins in `wenchang.testing`. Subclass `ResolverConformance` and supply fixtures for your resolver, a valid and an invalid credential, your policy, the scopes a valid credential should get, and the roles you use. It checks that valid credentials give an `Identity`, invalid ones give a `ResolutionFailure`, results are consistent, roles are known, and writes follow your policy. Details are in the [reference](reference.md#conformance).

---

HTML version: <https://msiebert.github.io/wenchang/identity.html>
