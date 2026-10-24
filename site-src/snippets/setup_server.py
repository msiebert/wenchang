# pyright: basic
import os

from google.cloud import storage
from mcp.server.mcpserver import Context

from wenchang.core import MemoryStore
from wenchang.identity import Identity, SandboxResolver, ScopeGrant
from wenchang.mcp import build_server
from wenchang.prompts import PromptSlots
from wenchang.scope import ScopePolicy
from wenchang.storage.gcs import GcsStorage
from wenchang.transport import InProcessClient

slots = PromptSlots(
    purpose=(
        "You have persistent memory of your work helping an author write a novel: reference it "
        "and save to it with these tools whenever you work on a manuscript."
    ),
    scope_guidance=(
        "There are three scopes. `user` is private to the author you are talking with. "
        "`project` is the manuscript, shared by everyone working on it; any of them may write it. "
        "`organization` is Hanlin Press, shared by every author and editor there; only "
        "editors-in-chief may write it. Writes to `user` and `project` need no ask. If a new fact "
        "contradicts one stored in a shared scope, show the stored fact and ask which to keep."
    ),
    seed_areas=(
        "- user: preferences, workflows\n"
        "- project: characters, plot, timeline, style\n"
        "- organization: conventions\n\n"
        "Every scope also has a `system/` area."
    ),
)

# Each person sets their own WENCHANG_USER. Everyone on a manuscript shares WENCHANG_PROJECT.
identity = Identity(
    grants={
        "user": ScopeGrant(os.environ["WENCHANG_USER"], "owner"),
        "project": ScopeGrant(os.environ["WENCHANG_PROJECT"], "member"),
        "organization": ScopeGrant(os.environ["WENCHANG_ORG"], "member"),
    }
)

# Application Default Credentials; the bucket must already exist.
bucket = storage.Client(project="my-gcp-project").bucket(os.environ["WENCHANG_BUCKET"])
store = MemoryStore(GcsStorage(bucket), scope_priority=("user", "project", "organization"))


def credentials_from_context(ctx: Context) -> None:
    return None  # SandboxResolver ignores credentials.


server = build_server(
    slots=slots,
    client=InProcessClient(store),
    resolver=SandboxResolver(identity),
    # Only editors-in-chief (admins) write organization.
    policy=ScopePolicy({"organization": frozenset({"admin", "owner"})}),
    credentials_from_context=credentials_from_context,
    source="claude-code",
    product="Inkwell",
)

if __name__ == "__main__":
    server.run("stdio")
