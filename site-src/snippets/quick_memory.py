from mcp.server.mcpserver import Context

from wenchang.core import MemoryStore
from wenchang.identity import Identity, SandboxResolver, ScopeGrant
from wenchang.mcp import build_server
from wenchang.prompts import PromptSlots
from wenchang.scope import ScopePolicy
from wenchang.storage.memory import InMemoryStorage
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

# One fixed identity for every caller: fine for a local sandbox.
identity = Identity(
    grants={
        "user": ScopeGrant("u-me", "owner"),
        "project": ScopeGrant("p-demo", "member"),
    }
)


def credentials_from_context(ctx: Context) -> None:
    return None  # SandboxResolver ignores credentials.


server = build_server(
    slots=slots,
    client=InProcessClient(MemoryStore(InMemoryStorage(), scope_priority=("user", "project"))),
    resolver=SandboxResolver(identity),
    policy=ScopePolicy({}),  # no role-gated scopes
    credentials_from_context=credentials_from_context,
    source="quickstart",
    product="Demo",
)

if __name__ == "__main__":
    server.run("stdio")
