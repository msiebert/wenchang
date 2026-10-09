"""The memory MCP server runs over stdio (AIE-1060, US8.1)."""

import sys
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import StdioServerParameters
from mcp.client import Client

from prompts_reference_adopter import REFERENCE_SLOTS
from wenchang.prompts import build_memory_prompt
from wenchang.tools import TOOL_NAMES

pytestmark = pytest.mark.unit

SCRIPT = Path(__file__).resolve().parent / "mcp_stdio_server.py"


def test_stdio_server_serves_tools_instructions_and_calls() -> None:
    """A client launching the server over stdio sees the seven tools and the
    memory prompt, and a write then read round trip succeeds (AIE-1060, US8.1).
    """
    params = StdioServerParameters(command=sys.executable, args=[str(SCRIPT)])

    async def main() -> tuple[set[str], str | None, Any, Any]:
        with anyio.fail_after(30):
            async with Client(params) as client:
                names = {tool.name for tool in (await client.list_tools()).tools}
                written = await client.call_tool(
                    "write_file",
                    {
                        "scope": "user",
                        "area": "notes",
                        "name": "today",
                        "content": "- [stated] Prefers tea\n",
                        "description": "Drinks",
                        "aliases": [],
                        "expected_version": None,
                    },
                )
                read = await client.call_tool(
                    "read_file", {"scope": "user", "area": "notes", "name": "today"}
                )
                return names, client.instructions, written, read

    names, instructions, written, read = anyio.run(main)

    assert names == set(TOOL_NAMES)
    assert instructions == build_memory_prompt(REFERENCE_SLOTS)
    assert written.is_error is False
    assert read.is_error is False
    assert read.structured_content["content"] == "- [stated] Prefers tea\n"
    assert read.structured_content["version"] == written.structured_content["version"]
