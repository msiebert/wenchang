from mcp.server.mcpserver import Context

from wenchang.core import MemoryStore
from wenchang.identity import Identity, ResolutionFailure, ScopeGrant
from wenchang.mcp import build_server
from wenchang.prompts import PromptSlots
from wenchang.scope import ScopePolicy
from wenchang.storage.memory import InMemoryStorage
from wenchang.transport import InProcessClient


class BearerResolver:
    """Verifies a bearer token and returns the caller's grants. Must not raise."""

    def resolve(self, credentials: str | None) -> Identity | ResolutionFailure:
        if credentials != "Bearer secret-token":  # replace with real verification
            return ResolutionFailure("Missing or invalid bearer token.")
        return Identity(grants={"user": ScopeGrant("u-ada", "owner")})


def credentials_from_context(ctx: Context) -> str | None:
    # Headers are client-supplied: return the raw credential and let the resolver verify it.
    return (ctx.headers or {}).get("authorization")


server = build_server(
    slots=PromptSlots(
        purpose="You have persistent memory of your work with this user.",
        scope_guidance=(
            "There is one scope, user, and it is private to the person you are talking with."
        ),
        seed_areas="- user: preferences, workflows\n\nEvery scope also has a `system/` area.",
    ),
    client=InProcessClient(MemoryStore(InMemoryStorage())),
    resolver=BearerResolver(),
    policy=ScopePolicy({}),
    credentials_from_context=credentials_from_context,
    source="my-service",
)

if __name__ == "__main__":
    server.run("streamable-http")
