"""MCP server adapter: the memory tools and prompt on an mcp MCPServer.

Requires the optional extra: pip install 'wenchang[mcp]'.
"""

from typing import Final

try:
    from mcp.server.mcpserver import MCPServer
except ImportError as exc:  # optional dependency
    raise ImportError(
        "wenchang.mcp requires the optional 'mcp' extra: pip install 'wenchang[mcp]'"
    ) from exc

__all__ = ["PROMPT_RESOURCE_URI", "MCPServer"]

PROMPT_RESOURCE_URI: Final[str] = "wenchang://memory-prompt"
