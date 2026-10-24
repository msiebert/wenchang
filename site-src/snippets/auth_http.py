# pyright: basic
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
