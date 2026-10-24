# Authorization

wenchang does not authenticate anyone. You decide who the caller is. wenchang takes your answer and enforces it: the caller can only reach the scopes and entities you grant, and can only write the scopes your policy allows.

In the legend, Wenchang's two attendants are Tianlong, who cannot hear, and Diya, who cannot speak. That way no secret gets out. A resolver is the same arrangement in Python.

## What you provide

Three pieces plug in.

1. **`credentials_from_context(ctx)`** reads the caller's raw credentials from the MCP request. It must be a plain function, not async. Over HTTP, `ctx.headers` holds the request headers. On stdio it is `None`, so a stdio server reads credentials from its own environment instead. Return the raw value and do not trust it here.
2. **A resolver** with one method, `resolve(credentials) -> Identity | ResolutionFailure`. It verifies the credentials and returns an `Identity`: a mapping from scope name to `ScopeGrant(entity_id, role)`. Roles are your own words (`owner`, `member`, `admin`).
3. **A `ScopePolicy`** mapping a scope to the set of roles allowed to write it. A scope not listed is open to every role that holds a grant. The `system/` area is read-only in every scope regardless.

Every tool call runs all three. The agent never sees credentials and never passes an entity ID. It passes `scope`, `area`, and `name`, and the tool layer fills in the entity ID from the caller's grant for that scope. A caller cannot name another user's path.

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
- **The resolver does not raise.** A bad credential is a `ResolutionFailure`. The detail is shown to the agent, so never put a token or secret in it. If the resolver raises anyway, or `credentials_from_context` raises, the call fails with a permanent "memory unavailable" error that names only the exception type.
- **The resolver runs on every tool call.** Cache inside it if verification is expensive, and expire cache entries with the token.
- **Entity IDs are path segments.** They must be non-empty and must not contain `/`, a backslash, or control characters. Use stable IDs. If a user's ID changes, their old files are still under the old ID.

## Behavior to expect

| Situation | Result |
| --- | --- |
| Resolver returns `ResolutionFailure` | Permanent error carrying your detail. No memory for that call. |
| Agent names a scope the caller has no grant for | `InvalidArgumentError` listing the scopes that are available. |
| Tianlong (a `member`) writes `organization` | `RestrictedScopeError`, reason `role_required`, with the permitted roles. |
| Anyone writes `system/` | `RestrictedScopeError`, reason `system_read_only`. |

> **Reads are not restricted by role.** A caller can read every area, including `system/`, of every scope it holds a grant for. `ScopePolicy` gates writes only. If a scope should not be readable by some people, do not grant it to them.

The prompt also has to match the policy. If only admins can write `organization`, say that in `scope_guidance`, or the agent will try and fail. See [Customizing the prompts](prompts.md#scope-guidance).

## Other transports

- **stdio.** The client starts one server process per session, so identity usually comes from the process environment: an environment variable holding a token, or the grants themselves for a single-developer setup as in [Setup](setup.md#server). Return it from `credentials_from_context` as `os.environ.get("MEMORY_TOKEN")` and let the resolver verify it.
- **HTTP.** `server.run("streamable-http", host=..., port=...)` serves the MCP endpoint at `/mcp` by default. Put TLS in front of it. The MCP SDK also has its own auth options on `MCPServer` (`auth`, `token_verifier`) if you want requests rejected before they reach wenchang. See the `mcp` documentation. The HTTP example here builds and its resolver was exercised directly, but it was not run against a live MCP client.
- **An existing MCP server.** Use `register_memory_tools` to add the tools to a server you already run, with your own auth in front. See [Reference](reference.md#embed).

## Test your resolver

`pip install "wenchang[testing]"` adds pytest mixins in `wenchang.testing`. Subclass `ResolverConformance` and supply fixtures for your resolver, a valid and an invalid credential, your policy, the scopes a valid credential should get, and the roles you use. It checks that valid credentials give an `Identity`, invalid ones give a `ResolutionFailure`, results are consistent, roles are known, and writes follow your policy. Details are in the [reference](reference.md#conformance).

---

HTML version: <https://msiebert.github.io/wenchang/authorization.html>
