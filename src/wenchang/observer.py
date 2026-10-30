"""The tool-call observer shared by MemoryTools and the MCP adapter.

An observer is a plain callable that receives one ToolCallRecord after each
tool call. check_observer validates one; notify_observer builds the record
and delivers it, logging and swallowing any failure.
"""

import copy
import inspect
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TypeAlias

__all__ = ["ToolCallObserver", "ToolCallRecord", "check_observer", "notify_observer"]


@dataclass(frozen=True)
class ToolCallRecord:
    """One memory tool call, as an entry point handled it.

    The fields depend on the entry point, MCP (wenchang.mcp) or direct
    (bind_tools / MemoryTools):

    - tool: MCP, the registered name, prefix included; direct, the bare
      method name.
    - arguments: MCP, what the wrapper received; direct, every parameter by
      name, defaults filled.
    - result: MCP, a copy of the structured_content payload; direct,
      render_result of the return value, or render_error of the tool's or
      the render's failure.
    - is_error: whether result is an error payload.
    - request_id: MCP, the request's id, for correlating records that arrive
      in completion order; direct, None.
    - duration_s: wall time on a monotonic clock. MCP, credentials,
      bind_tools, the tool, and rendering; direct, the tool method only.

    arguments and result are read-only deep copies. Calls rejected during
    argument validation never produce a record. Records compare by value and
    are unhashable, because arguments and result are mappings.
    """

    tool: str
    arguments: Mapping[str, object]
    result: Mapping[str, object]
    is_error: bool
    request_id: str | None
    duration_s: float


ToolCallObserver: TypeAlias = Callable[[ToolCallRecord], None]


def check_observer(on_call: object) -> None:
    """Raise TypeError unless on_call is None or a plain (non-async) callable."""
    if on_call is not None and not callable(on_call):
        raise TypeError("on_call must be callable or None")
    # Observers are called synchronously; a coroutine would never run.
    if inspect.iscoroutinefunction(on_call):
        raise TypeError("on_call must be a plain function, not async")


def notify_observer(
    on_call: ToolCallObserver,
    logger: logging.Logger,
    *,
    tool: str,
    arguments: Mapping[str, object],
    result: Mapping[str, object],
    is_error: bool,
    request_id: str | None,
    duration_s: float,
) -> None:
    """Build the record (read-only deep copies of arguments and result) and call on_call.

    Any Exception from building the record or from on_call is logged on logger
    at ERROR, naming the tool, and swallowed.
    """
    try:
        record = ToolCallRecord(
            tool,
            MappingProxyType(copy.deepcopy(dict(arguments))),
            MappingProxyType(copy.deepcopy(dict(result))),
            is_error,
            request_id,
            duration_s,
        )
        on_call(record)
    except Exception:
        logger.error("on_call observer failed for %s", tool, exc_info=True)
