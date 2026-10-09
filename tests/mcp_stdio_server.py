"""A memory MCP server over stdio, for tests/test_mcp_stdio.py (AIE-1060).

Serves an in-memory store with the reference adopter's slots and a sandbox
resolver. Run as a script: python tests/mcp_stdio_server.py
"""

from prompts_reference_adopter import REFERENCE_SLOTS
from wenchang.core import MemoryStore
from wenchang.identity import Identity, SandboxResolver, ScopeGrant
from wenchang.mcp import build_server
from wenchang.scope import ScopePolicy
from wenchang.storage.memory import InMemoryStorage
from wenchang.transport import InProcessClient

server = build_server(
    slots=REFERENCE_SLOTS,
    client=InProcessClient(MemoryStore(InMemoryStorage())),
    resolver=SandboxResolver(Identity({"user": ScopeGrant("u-stdio", "owner")})),
    policy=ScopePolicy({}),
    credentials_from_context=lambda ctx: None,
    source="mcp-stdio",
)

if __name__ == "__main__":
    server.run("stdio")
