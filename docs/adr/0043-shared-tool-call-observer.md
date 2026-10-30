# 0043. Shared tool-call observer

Date: 2026-10-30

## Status

Accepted. Amends [ADR 0027](0027-mcp-host-adapter.md) decision 10.

## Context

The `on_call` observer existed only in `wenchang.mcp` (ADR 0027 decision
10). An adopter calling the engine through `bind_tools` had no hook for logs
and metrics short of wrapping each tool. The issue asks for the same
observer on `bind_tools`, with the same record shape, one implementation
shared with MCP, and MCP behavior unchanged.

## Decision

1. **New module `wenchang.observer`**, public names `ToolCallRecord`,
   `ToolCallObserver`, `check_observer`, and `notify_observer`. It imports
   only the stdlib, so `bind_tools` users get the observer without the
   `[mcp]` extra. `ToolCallRecord` moved here from `wenchang.mcp`, which
   re-exports it; `wenchang.mcp.__all__` is unchanged.
   - `check_observer(on_call)` raises `TypeError` unless `on_call` is `None`
     or a plain callable, with MCP's two messages.
   - `notify_observer(on_call, logger, *, tool, arguments, result, is_error,
     request_id, duration_s)` builds the record (read-only deep copies of
     `arguments` and `result`) and calls `on_call`. Any `Exception` from
     either step is logged at `ERROR` on `logger`, naming the tool, and
     swallowed.
2. **`MemoryTools(..., on_call=None)` and `bind_tools(..., on_call=None)`.**
   Keyword-only, checked by `check_observer`; `bind_tools` checks it before
   the resolver runs, `MemoryTools` after its existing checks.
   `MemoryTools.on_call` is a read-only property. Each of the seven tool
   methods is wrapped by a private decorator (`functools.wraps`, so
   docstrings, `descriptions()`, and `inspect.signature` are unchanged)
   that, when an observer is set, delivers one record per call on the
   calling thread before the call returns or raises.
3. **`request_id: str | None`.** MCP records carry the MCP request id, as
   before; direct records carry `None`. This is a typing-level change to a
   public MCP type with runtime values unchanged, accepted pre-1.0. Strictly
   typed consumers must narrow it; `evals/server.py` raises if an MCP record
   has none.
4. **`result` is the rendered payload.** Direct calls record
   `render_result(value)`, or `render_error(exc)` with `is_error=True` on
   failure. If `render_result` raises on a return value, the record carries
   `render_error(<render exception>)` with `is_error=True`, as MCP does, and
   the caller still gets the raw value. The caller always gets the raw value
   or the original exception object.
5. **Per-entry-point fields.** The `ToolCallRecord` docstring defines each:
   `tool` is the registered (prefixed) name under MCP and the bare method
   name directly; `arguments` is what the MCP wrapper received, or every
   parameter by name with defaults filled; `duration_s` covers credentials,
   `bind_tools`, the tool, and rendering under MCP, and the tool method only
   directly.
6. **MCP keeps its own boundary.** It validates with `check_observer`,
   delivers through `notify_observer` (logger `wenchang.mcp`), and does not
   pass `on_call` into `bind_tools`. Each MCP call still yields exactly one
   record, and credential and resolver failures are still recorded.
7. **The observer is never called inside an `except` block.** The wrapper
   only stores the exception there, then renders, notifies, and re-raises
   outside it. The observer sees an empty `sys.exc_info()`, and an observer
   failure's log never chains the tool's exception (which may carry
   secrets) as `__context__`.
8. **Edges.**
   - MCP record construction now happens inside `notify_observer`'s guard,
     so a deep-copy failure is logged and swallowed instead of propagating.
     This narrowing is intended and unreachable in practice: MCP arguments
     are pydantic-validated and payloads are JSON-safe.
   - A call Python rejects before the tool runs (wrong arity, unknown
     keyword) raises `TypeError` with no record.
   - `BaseException`s that are not `Exception`s, from the tool or the
     observer, pass through uncaught with no record.
   - A subclass that overrides a tool method without the decorator is not
     observed.
   - Identity-resolution failures in `bind_tools` produce no record; they
     are not tool calls.

## Consequences

- `bind_tools` adopters get one record per tool call with no wrapping, and
  one observer function serves both entry points.
- Direct records have no request id. The observer runs synchronously on the
  calling thread, so callers correlate through a `contextvars` value or
  thread-local they set.
- `ToolCallRecord.__module__` is now `wenchang.observer`, which affects only
  pickled records.
- With an observer set, every direct call pays a deep copy and a render; it
  is opt-in, and MCP already pays it.
- `wenchang.tools` imports `wenchang.observer`.

Rejected:

- **A separate record type for direct calls.** One observer could not serve
  both entry points.
- **A synthetic UUID request id.** It implies a correlation with a request
  that does not exist.
- **MCP observing through `bind_tools`.** It would lose credential and
  resolver-failure records and the MCP request id, and would change MCP's
  duration boundary.
- **Keeping the record in `wenchang.mcp`.** `bind_tools` users would need
  the `[mcp]` extra.
- **Putting it in `wenchang.tools`.** MCP would import private helpers
  across modules.
- **A proxy object or subclass returned by `bind_tools`.** The return type
  would no longer be `MemoryTools`, and docstrings, signatures, and
  bound-method typing would need forwarding.
