from mcp.server.mcpserver import Context, MCPServer

from wenchang.core import MemoryStore
from wenchang.identity import Identity, SandboxResolver, ScopeGrant
from wenchang.mcp import memory_instructions, register_memory_tools
from wenchang.prompts import PromptSlots
from wenchang.scope import ScopePolicy
from wenchang.storage.memory import InMemoryStorage
from wenchang.transport import InProcessClient

slots = PromptSlots(
    purpose="You have persistent memory of your work helping an author write a novel.",
    scope_guidance="There is one scope, user, private to the author you are talking with.",
    seed_areas="- user: preferences, workflows\n\nEvery scope also has a `system/` area.",
)


def credentials_from_context(ctx: Context) -> None:
    return None  # SandboxResolver ignores credentials.


prompt = memory_instructions(slots) + (
    "\n## Tone\n\nWhen you save something, say so in one short sentence.\n"
)
server = MCPServer("inkwell-memory", instructions=prompt)
register_memory_tools(
    server,
    prompt=prompt,  # the same text as the instructions
    client=InProcessClient(MemoryStore(InMemoryStorage())),
    resolver=SandboxResolver(Identity(grants={"user": ScopeGrant("u-tianlong", "owner")})),
    policy=ScopePolicy({}),
    credentials_from_context=credentials_from_context,
    source="inkwell-web",
)
