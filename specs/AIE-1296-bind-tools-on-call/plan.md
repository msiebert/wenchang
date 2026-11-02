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
    tool: str
    arguments: Mapping[str, object]
    result: Mapping[str, object]
    is_error: bool
    request_id: str | None
    duration_s: float


ToolCallObserver: TypeAlias = Callable[[ToolCallRecord], None]
```

The `ToolCallRecord` docstring defines each field per entry point:

| Field | MCP (`wenchang.mcp`) | Direct (`bind_tools` / `MemoryTools`) |
| ----- | -------------------- | ------------------------------------- |
| `tool` | registered name, prefix included | bare method name |
| `arguments` | what the wrapper received | every parameter by name, defaults filled |
| `result` | copy of the `structured_content` payload | `render_result(value)`, or `render_error(exc)` for a tool or render failure |
| `request_id` | the MCP request id (always a `str`) | `None` |
| `duration_s` | credentials + `bind_tools` + tool + render | the tool method only |

Both entry points use read-only deep copies of `arguments` and `result`. Records compare by value and are unhashable.

```python
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
2. `started = time.monotonic()`; run the tool inside `try: ... except Exception as exc:`. The `except` block only stores the exception; nothing else runs in it.
3. `duration_s = time.monotonic() - started`.
4. After leaving the `except` block:
   - On failure: `result = render_error(exc)`, `is_error = True`.
   - On success: `result = render_result(value)`, `is_error = False`. If `render_result` raises, the wrapper catches it the same way (store, leave the block) and uses `result = render_error(render_exc)`, `is_error = True`, matching MCP's `_run`. The caller still gets the raw value.
5. `notify_observer(on_call, _log, tool=<method name>, arguments=<bound mapping>, result=..., is_error=..., request_id=None, duration_s=...)`. This runs outside any `except` block, so `sys.exc_info()` is empty inside the observer, and an observer exception has no `__context__` linking it to the tool's exception.
6. Return the tool's value, or `raise exc` (the original object). A `finally` clears the stored exception locals so they don't form a reference cycle.

When `on_call` is `None`, the tool runs with no binding, timing, or rendering.

Mechanism: a private decorator on the seven methods using `functools.wraps`, so `__doc__` (read by `tool_descriptions`), `__name__`, and `inspect.signature` stay identical. No change to tool bodies.

- `inspect.signature` is computed once, at decoration time.
- For pyright strict, the decorator is annotated `(Callable[Concatenate[MemoryTools, _P], _R]) -> Callable[Concatenate[MemoryTools, _P], _R]`, and the wrapper is `cast` to that type, so bound-method calls keep their parameter types.
- `check_observer` runs after the existing checks in `MemoryTools.__init__`, so existing error precedence is unchanged.
- A subclass that overrides a tool method without the decorator is not observed. This is documented in ADR 0043.

### `wenchang.mcp`

- `from wenchang.observer import ToolCallRecord, check_observer, notify_observer`; `ToolCallRecord` stays in `__all__` (re-export; `wenchang.mcp.__all__` unchanged).
- `_validate` calls `check_observer(on_call)` in place of its two inline checks (same messages, same order relative to other checks).
- `call()` keeps its timing boundary (credentials + `bind_tools` + tool) and replaces the inline record construction and try/except with `notify_observer(on_call, _log, tool=tool, arguments=arguments, result=payload, is_error=is_error, request_id=ctx.request_id, duration_s=duration)`.
- `_run` keeps calling `bind_tools` **without** `on_call`.
- Annotations of `on_call` parameters become `ToolCallObserver | None` (same type).
- Behavior narrowing: record construction (deep copies) now happens inside `notify_observer`'s guard, so a deep-copy failure is logged and swallowed instead of propagating. This is intended and unreachable in practice.

### `evals/server.py`

`TraceCall.request_id` (`evals/graders.py`) stays `str`. At `evals/server.py:327`, narrow `r.record.request_id` with an explicit `if request_id is None: raise RuntimeError(...)` before building `TraceCall`, because MCP records always carry an id. Without this, pyright strict fails once `request_id` is `str | None`.

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
- ADR 0043 `docs/adr/0043-shared-tool-call-observer.md`; amend ADR 0027 decision 10 with a pointer to 0043 (record moved, `request_id` widened). ADR 0043 must record:
  - `request_id: str | None`;
  - each entry point's duration boundary;
  - the render-failure behavior;
  - the MCP deep-copy narrowing;
  - that the observer is not called inside `except`;
  - that undecorated subclass overrides are not observed.
