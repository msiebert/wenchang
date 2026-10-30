# Spec Review: AIE-1296 — on_call observer for bind_tools

## What & why

Adopters who call the engine through `bind_tools` (not MCP) get no hook for logs and metrics. Give `bind_tools` (and `MemoryTools`) the same `on_call` observer MCP has, delivering the same `ToolCallRecord` once per tool call, and move the record and its delivery into a new `mcp`-free module, `wenchang.observer`, that both entry points share.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | `bind_tools(..., on_call=obs)` | a tool succeeds | one record: bare tool name, all args (defaults filled), `render_result` payload, `is_error=False`, `request_id=None`, `duration_s>=0`; same return value |
| 2 | same | a tool raises (contract or off-contract) | one record with `render_error` payload, `is_error=True`; the original exception propagates |
| 3 | same | each of 7 tools, via attribute or `tools()` | exactly one record per call, in order; arity `TypeError` gives no record |
| 4 | an observer that raises | any tool call | tool outcome unchanged; `ERROR` logged on `wenchang.tools` |
| 5 | `on_call` not callable / async | `bind_tools` or `MemoryTools` | `TypeError` (MCP's messages); `bind_tools` fails before resolving |
| 6 | `on_call=None` | tools called | no change; existing tool tests pass unmodified |
| 7 | no `mcp` installed | import `wenchang.observer`, `wenchang.tools` | works, records delivered |
| 8 | `wenchang.mcp` | import `ToolCallRecord`; run existing MCP tests | same class as `wenchang.observer`'s; `__all__` unchanged; `test_mcp_server.py` passes unmodified; one record per MCP call |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| New `wenchang.observer` module holds `ToolCallRecord`, `ToolCallObserver`, `check_observer`, `notify_observer`; `wenchang.mcp` re-exports the record | Keep record in `mcp` (requires the extra); put it in `tools.py` (MCP would import private helpers across modules) | Importable without `mcp`; one place for record building and safe delivery |
| `request_id: str \| None`, `None` for `bind_tools` | Separate record type; synthesize a UUID | Same observer works for both; a fake id implies correlation that doesn't exist; observer runs on the caller's thread, so callers can correlate via contextvars |
| `result` is the rendered JSON-safe payload | Raw return value / exception object on the record | Same shape as MCP; the caller already has the raw value or exception |
| MCP keeps its own boundary and calls `notify_observer`; does not pass `on_call` into `bind_tools` | MCP observes via `bind_tools` | Would lose credential/resolver-failure records and `request_id`, and change MCP behavior |
| `on_call` on both `MemoryTools` and `bind_tools` | Only `bind_tools` | `bind_tools` is a thin resolver+constructor; adopters constructing `MemoryTools` directly get the same hook |
| Wrapper via `functools.wraps` decorator on the 7 methods | Proxy object / subclass returned by `bind_tools` | Return type stays `MemoryTools`; docstrings and signatures unchanged |

## Files/modules to be touched

- `src/wenchang/observer.py` (new), `src/wenchang/tools.py`, `src/wenchang/mcp.py`
- `tests/test_observer.py`, `tests/test_tools_observer.py`, `tests/test_mcp_observer_shared.py` (new; existing tests untouched)
- `ARCHITECTURE.md`, `docs/adr/0043-shared-tool-call-observer.md` (new), `docs/adr/0027-mcp-host-adapter.md` (pointer)

## Open questions / assumptions

- Widening `request_id` to `str | None` is a typing-level change to a public MCP type (runtime values unchanged). Assumed acceptable pre-1.0.
- `check_observer` / `notify_observer` are public in `wenchang.observer` so `wenchang.mcp` (and custom host adapters) can use them without private imports.

## Risks

- `ToolCallRecord.__module__` changes to `wenchang.observer` (affects pickled records only).
- With an observer set, every call pays a deep copy and render; acceptable since it's opt-in and MCP already does this.
