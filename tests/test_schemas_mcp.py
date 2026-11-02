"""Tests that wenchang.mcp registers input schemas matching wenchang.schemas.

Covers AIE-1295, US2.2: the MCP adapter's hand-written wrapper signatures
agree with the exported input schemas on property names, required sets, and
per-property kinds.
"""

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, TypeVar, cast

import anyio
import pytest
from mcp.client import Client
from mcp.server.mcpserver import Context, MCPServer

from evals.reference_adopter import REFERENCE_SLOTS
from schema_kinds import schema_kind
from wenchang.core import MemoryStore
from wenchang.identity import Identity, SandboxResolver, ScopeGrant
from wenchang.mcp import register_memory_tools
from wenchang.prompts import build_memory_prompt
from wenchang.schemas import tool_schemas
from wenchang.scope import ScopePolicy
from wenchang.storage.memory import InMemoryStorage
from wenchang.tools import TOOL_NAMES
from wenchang.transport import InProcessClient

pytestmark = pytest.mark.unit

_T = TypeVar("_T")


def _credentials(ctx: Context[Any, Any]) -> object:
    return "caller"


def _server() -> MCPServer:
    prompt = build_memory_prompt(REFERENCE_SLOTS)
    server = MCPServer("host", instructions=prompt)
    register_memory_tools(
        server,
        prompt=prompt,
        client=InProcessClient(MemoryStore(InMemoryStorage())),
        resolver=SandboxResolver(Identity({"user": ScopeGrant("u-1", "owner")})),
        policy=ScopePolicy({}),
        credentials_from_context=_credentials,
        source="mcp-schemas",
    )
    return server


def _with_client(server: MCPServer, body: Callable[[Client], Awaitable[_T]]) -> _T:
    async def main() -> _T:
        with anyio.fail_after(30):
            async with Client(server, mode="auto") as client:
                return await body(client)

    return anyio.run(main)


def _tools(server: MCPServer) -> dict[str, Any]:
    async def body(client: Client) -> dict[str, Any]:
        return {tool.name: tool for tool in (await client.list_tools()).tools}

    return _with_client(server, body)


def test_registered_input_schemas_match_export() -> None:
    """Each MCP-registered input schema has the exported schema's property
    names, required set, and per-property kinds (AIE-1295, US2.2).
    """
    listed = _tools(_server())
    exported = tool_schemas()

    assert set(listed) == set(TOOL_NAMES)
    for name in TOOL_NAMES:
        registered = cast(dict[str, Any], listed[name].input_schema)
        schema = exported[name].input
        ours = cast(dict[str, Mapping[str, Any]], schema["properties"])
        theirs = cast(dict[str, Mapping[str, Any]], registered.get("properties", {}))

        assert set(theirs) == set(ours), name
        assert set(registered.get("required", [])) == set(cast(list[str], schema["required"])), name
        for prop in ours:
            assert schema_kind(theirs[prop]) == schema_kind(ours[prop]), (name, prop)
