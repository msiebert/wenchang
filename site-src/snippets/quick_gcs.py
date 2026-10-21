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
        "You have persistent memory of your work with this user: reference it and "
        "save to it with these tools."
    ),
    scope_guidance=(
        "There are two scopes. `user` is private to the person you are talking with. "
        "`project` is shared with everyone on the project. Writes to `user` need no ask; "
        "ask before saving a new fact to `project`, and name the scope."
    ),
    seed_areas=(
        "- user: preferences, workflows, people\n"
        "- project: conventions, glossary\n\n"
        "Every scope also has a `system/` area."
    ),
)

identity = Identity(
    grants={
        "user": ScopeGrant("u-me", "owner"),
        "project": ScopeGrant("p-demo", "member"),
    }
)

# Uses Application Default Credentials; the bucket must already exist.
bucket = storage.Client(project="my-gcp-project").bucket("my-wenchang-memory")
store = MemoryStore(GcsStorage(bucket), scope_priority=("user", "project"))


def credentials_from_context(ctx: Context) -> None:
    return None


server = build_server(
    slots=slots,
    client=InProcessClient(store),
    resolver=SandboxResolver(identity),
    policy=ScopePolicy({}),
    credentials_from_context=credentials_from_context,
    source="quickstart",
    product="Demo",
)

if __name__ == "__main__":
    server.run("stdio")
