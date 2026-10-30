# Implementation Plan: AIE-1296 on_call observer for bind_tools

**Spec**: `spec.md` · **ADR**: 0043 · **Branch**: `AIE-1296-bind-tools-on-call`

## Summary

Move `ToolCallRecord` and the observer plumbing (validation, record construction, safe delivery) out of `wenchang.mcp` into a new dependency-free module `wenchang.observer`. `MemoryTools`/`bind_tools` take `on_call` and deliver one record per tool-method call; `wenchang.mcp` delivers through the same function at its own boundary.

## Public interface

### `wenchang.observer` (new; imports nothing from `mcp`)

```python
__all__ = ["ToolCallObserver", "ToolCallRecord", "check_observer", "notify_observer"]

@dataclass(frozen=True)
class ToolCallRecord:
    tool: str                       # registered tool name (MCP: prefix included; bind_tools: bare name)
    arguments: Mapping[str, object] # read-only deep copy, every parameter by name, defaults filled
    result: Mapping[str, object]    # read-only deep copy of render_result / render_error output
    is_error: bool
    request_id: str | None          # MCP request id; None for direct (bind_tools) calls
    duration_s: float               # monotonic wall time of the observed call

ToolCallObserver: TypeAlias = Callable[[ToolCallRecord], None]

def check_observer(on_call: object) -> None:
    """Raise TypeError unless on_call is None or a plain (non-async) callable."""
    # Messages, verbatim: "on_call must be callable or None"
    #                     "on_call must be a plain function, not async"

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
    at ERROR as "on_call observer failed for %s" (tool), with exc_info, and
    swallowed. Never raises an Exception.
    """
```

### `wenchang.tools`

```python
class MemoryTools:
    def __init__(
        self,
        client: TransportClient,
        identity: Identity,
        policy: ScopePolicy,
        *,
        source: str,
        product: str | None = None,
        on_call: ToolCallObserver | None = None,
    ) -> None: ...

    @property
    def on_call(self) -> ToolCallObserver | None: ...

def bind_tools(
    client: TransportClient,
    resolver: IdentityResolver[_C],
    credentials: _C,
    policy: ScopePolicy,
    *,
    source: str,
    product: str | None = None,
    on_call: ToolCallObserver | None = None,
) -> MemoryTools:
    """check_observer(on_call) first (before the resolver runs), then resolve and construct."""
```

`__all__` unchanged. Logger: `logging.getLogger("wenchang.tools")`.

Per-call behavior when `on_call` is set, for each of the seven tool methods:

1. Bind the call's arguments to the method signature (excluding `self`) with defaults applied. If binding fails, make the call as-is (Python raises `TypeError`) with no record.
2. `started = time.monotonic()`; run the tool.
3. `duration_s = time.monotonic() - started`.
4. Success: `result = render_result(value)`, `is_error = False`. `Exception`: `result = render_error(exc)`, `is_error = True`. Rendering is inside the guarded path (a rendering failure is logged and skipped like an observer failure).
5. `notify_observer(on_call, _log, tool=<method name>, arguments=<bound mapping>, result=..., is_error=..., request_id=None, duration_s=...)`.
6. Return the tool's value, or re-raise the original exception object (bare `raise` semantics; the observer's exception must not become its `__context__`).

When `on_call` is `None`, the tool runs with no binding, timing, or rendering.

Mechanism (implementer's choice, constrained): a private decorator on the seven methods using `functools.wraps`, so `__doc__` (read by `tool_descriptions`), `__name__`, and `inspect.signature` stay identical. No change to tool bodies.

### `wenchang.mcp`

- `from wenchang.observer import ToolCallRecord, check_observer, notify_observer`; `ToolCallRecord` stays in `__all__` (re-export; `wenchang.mcp.__all__` unchanged).
- `_validate` calls `check_observer(on_call)` in place of its two inline checks (same messages, same order relative to other checks).
- `call()` keeps its timing boundary (credentials + `bind_tools` + tool) and replaces the inline record construction and try/except with `notify_observer(on_call, _log, tool=tool, arguments=arguments, result=payload, is_error=is_error, request_id=ctx.request_id, duration_s=duration)`.
- `_run` keeps calling `bind_tools` **without** `on_call`.
- Annotations of `on_call` parameters become `ToolCallObserver | None` (same type).

## Module boundaries

`wenchang.observer` depends only on the stdlib. `wenchang.tools` and `wenchang.mcp` depend on it. No storage, transport, or scope semantics change.

## Testing approach

- New `tests/test_tools_observer.py`: US1-US3 against `InProcessClient` over the in-memory fake (follow existing `tests/test_tools.py` fixtures); off-contract errors via a client stub whose method raises.
- New `tests/test_observer.py`: US4.3, US4.6 (`check_observer`, `notify_observer` directly, with `caplog`).
- US4.1: subprocess with `mcp` blocked (e.g. `sys.modules["mcp"] = None` before importing), as `tests/test_mcp_server.py` already does with a subprocess.
- US4.2, US4.5: a small addition in a new test file (do not modify `tests/test_mcp_server.py`; it must pass unchanged).
- Test docstrings reference AIE-1296 and the scenario (e.g. "AIE-1296, US1.2").

## Docs

- ARCHITECTURE.md: module map entry for `wenchang.observer`; `MemoryTools`/`bind_tools` signatures; the MCP `on_call` section points at the shared record and notes `request_id` is `None` for direct calls.
- ADR 0043 `docs/adr/0043-shared-tool-call-observer.md`; amend ADR 0027 decision 10 with a pointer to 0043 (record moved, `request_id` widened).
