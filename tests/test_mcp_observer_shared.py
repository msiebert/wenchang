"""Tests that wenchang.mcp shares the observer implementation in wenchang.observer.

Covers AIE-1296, US4.2 (re-exported record, unchanged __all__) and US4.5 (one
record per MCP call, delivered through notify_observer).
"""

import logging
from collections.abc import Mapping
from typing import Any, cast

import anyio
import pytest
from mcp.client import Client
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult

import wenchang.mcp as wmcp
import wenchang.observer
from evals.reference_adopter import REFERENCE_SLOTS
from wenchang.core import MemoryStore
from wenchang.identity import Identity, SandboxResolver, ScopeGrant
from wenchang.mcp import build_server
from wenchang.observer import ToolCallRecord
from wenchang.scope import ScopePolicy
from wenchang.storage.memory import InMemoryStorage
from wenchang.transport import InProcessClient

pytestmark = pytest.mark.unit

PREFIX = "mem"
FILE = {"scope": "user", "area": "notes", "name": "today"}
IDENTITY = Identity({"user": ScopeGrant("u-alice", "owner")})


def _server(on_call: object) -> MCPServer:
    return build_server(
        slots=REFERENCE_SLOTS,
        client=InProcessClient(MemoryStore(InMemoryStorage())),
        resolver=SandboxResolver(IDENTITY),
        policy=ScopePolicy({}),
        credentials_from_context=lambda ctx: None,
        source="mcp-observer-shared",
        tool_prefix=PREFIX,
        on_call=cast(Any, on_call),
    )


def _read_once(server: MCPServer) -> CallToolResult:
    async def main() -> CallToolResult:
        with anyio.fail_after(30):
            async with Client(server) as client:
                return await client.call_tool(f"{PREFIX}_read_file", dict(FILE))

    return anyio.run(main)


def test_mcp_reexports_the_shared_record() -> None:
    """wenchang.mcp.ToolCallRecord is wenchang.observer.ToolCallRecord
    (AIE-1296, US4.2).
    """
    assert wmcp.ToolCallRecord is wenchang.observer.ToolCallRecord


def test_mcp_all_is_unchanged() -> None:
    """wenchang.mcp.__all__ is unchanged (AIE-1296, US4.2)."""
    assert wmcp.__all__ == [
        "PROMPT_RESOURCE_URI",
        "ToolCallRecord",
        "build_server",
        "memory_instructions",
        "register_memory_tools",
    ]


def test_one_mcp_call_delivers_one_record() -> None:
    """One MCP tool call delivers exactly one record, under the registered name;
    MCP does not also observe through bind_tools (AIE-1296, US4.5).
    """
    records: list[ToolCallRecord] = []

    result = _read_once(_server(records.append))

    assert result.is_error is True
    assert [r.tool for r in records] == [f"{PREFIX}_read_file"]
    assert isinstance(records[0].request_id, str)
    assert records[0].request_id


def test_mcp_delivers_through_notify_observer(monkeypatch: pytest.MonkeyPatch) -> None:
    """MCP delivers records through notify_observer with its request id and the
    wenchang.mcp logger (AIE-1296, US4.5).
    """
    calls: list[tuple[logging.Logger, Mapping[str, object]]] = []
    real = wenchang.observer.notify_observer

    def spy(on_call: Any, logger: logging.Logger, **kwargs: Any) -> None:
        calls.append((logger, kwargs))
        real(on_call, logger, **kwargs)

    monkeypatch.setattr(wmcp, "notify_observer", spy)
    records: list[ToolCallRecord] = []

    _read_once(_server(records.append))

    assert len(calls) == 1
    logger, kwargs = calls[0]
    assert logger.name == "wenchang.mcp"
    assert kwargs["tool"] == f"{PREFIX}_read_file"
    request_id = kwargs["request_id"]
    assert isinstance(request_id, str)
    assert request_id
    assert kwargs["is_error"] is True
    assert len(records) == 1
