import logging

from mcp.server.mcpserver import Context, MCPServer

from wenchang.core import MemoryStore
from wenchang.identity import Identity, SandboxResolver, ScopeGrant
from wenchang.mcp import ToolCallRecord, memory_instructions, register_memory_tools
from wenchang.prompts import PromptSlots
from wenchang.scope import ScopePolicy
from wenchang.storage.memory import InMemoryStorage
from wenchang.transport import InProcessClient

log = logging.getLogger("inkwell.calls")

slots = PromptSlots(
    purpose="You have persistent memory of your work helping an author write a novel.",
    scope_guidance=(
        "There is one scope, user, and it is private to the author you are talking with."
    ),
    seed_areas="- user: preferences, workflows, research\n\nEvery scope also has a `system/` area.",
)
identity = Identity(grants={"user": ScopeGrant("u-tianlong", "owner")})


def credentials_from_context(ctx: Context) -> str | None:
    # Over HTTP, return the raw credential and let your resolver verify it.
    # ctx.headers is None on stdio.
    return (ctx.headers or {}).get("authorization")


def on_call(record: ToolCallRecord) -> None:
    # Runs on worker threads after every call; keep it fast and thread-safe.
    log.info("%s error=%s %.3fs", record.tool, record.is_error, record.duration_s)


prompt = memory_instructions(slots)

# Your existing server, with your own tools and middleware.
server = MCPServer("hanlin-tools", instructions=prompt)

register_memory_tools(
    server,
    prompt=prompt,
    client=InProcessClient(MemoryStore(InMemoryStorage())),
    resolver=SandboxResolver(identity),
    policy=ScopePolicy({}),
    credentials_from_context=credentials_from_context,
    source="hanlin-tools",
    product="Inkwell",
    tool_prefix="inkwell",  # tools are registered as inkwell_read_file, inkwell_write_file, ...
    on_call=on_call,
)
