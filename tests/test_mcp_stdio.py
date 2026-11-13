"""The memory MCP server runs over stdio (AIE-1060, US8.1)."""

import sys
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import StdioServerParameters
from mcp.client import Client

from evals.reference_adopter import REFERENCE_SLOTS
from wenchang.prompts import build_memory_prompt
from wenchang.tools import TOOL_NAMES

pytestmark = pytest.mark.unit

SCRIPT = Path(__file__).resolve().parent / "mcp_stdio_server.py"


def test_stdio_server_serves_tools_instructions_and_calls() -> None:
    """A client launching the server over stdio sees the seven tools and the
    memory prompt, and a write then read round trip succeeds (AIE-1060, US8.1).
    Descriptions carry the guidance preambles within the length cap, and
    get_memory_index returns the memory prompt as a second content block
    (AIE-1382).
    """
    params = StdioServerParameters(command=sys.executable, args=[str(SCRIPT)])

    async def main() -> tuple[dict[str, str], str | None, Any, Any, Any]:
        with anyio.fail_after(30):
            async with Client(params) as client:
                descriptions = {
                    tool.name: tool.description or "" for tool in (await client.list_tools()).tools
                }
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
                index = await client.call_tool("get_memory_index", {})
                return descriptions, client.instructions, written, read, index

    descriptions, instructions, written, read, index = anyio.run(main)

    assert set(descriptions) == set(TOOL_NAMES)
    assert instructions == build_memory_prompt(REFERENCE_SLOTS)
    assert written.is_error is False
    assert read.is_error is False
    assert read.structured_content["content"] == "- [stated] Prefers tea\n"
    assert read.structured_content["version"] == written.structured_content["version"]

    index_description = " ".join(descriptions["get_memory_index"].split())
    assert " ".join(REFERENCE_SLOTS.purpose.split()) in index_description
    assert "call this first" in index_description
    for name in ("write_file", "append_line", "replace_fact"):
        text = " ".join(descriptions[name].split())
        assert "[system]" in text, name
        assert "never write a new `[system]` line" in text, name
    for name, text in descriptions.items():
        assert len(text) <= 2000, name

    assert index.is_error is False
    blocks = [block for block in index.content if block.type == "text"]
    assert len(index.content) == 2
    assert len(blocks) == 2
    assert blocks[1].text == build_memory_prompt(REFERENCE_SLOTS) == instructions
