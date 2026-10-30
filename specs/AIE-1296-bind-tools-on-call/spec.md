# Feature Specification: on_call observer for bind_tools

**Linear**: AIE-1296

**Feature Branch**: `AIE-1296-bind-tools-on-call`

**Created**: 2026-10-30

**Status**: Implemented

**Input**: `on_call` only exists in `wenchang.mcp`. Adopters that call the engine through `bind_tools` can't send logs and metrics without wrapping each tool themselves. Accept the same observer in `bind_tools`, with the same call shape (tool name, arguments, result or error, duration), and share one implementation between `bind_tools` and `wenchang.mcp`. Acceptance: the observer fires once per call for successes and errors; an exception raised by the observer doesn't break the tool call; MCP behavior is unchanged.

## Decisions already made (not reopened)

- The observer type and record are the MCP ones: `Callable[[ToolCallRecord], None]` and `ToolCallRecord(tool, arguments, result, is_error, request_id, duration_s)`, same field order.
- The shared implementation lives in a new module, `wenchang.observer`, importable without the `[mcp]` extra. `wenchang.mcp` re-exports `ToolCallRecord`; `wenchang.mcp.__all__` is unchanged.
- `request_id` becomes `str | None`. MCP records always carry the MCP request id (a non-empty `str`, as today); `bind_tools` records carry `None`. See ADR 0043.
- `result` is the JSON-safe payload, as in MCP: `render_result(value)` on success, `render_error(exc)` on failure. The caller still gets the raw value or the original exception.
- MCP keeps its own call boundary (credentials, identity resolution, and the tool) and does not pass `on_call` into `bind_tools`, so each MCP call still produces exactly one record and credential/resolver failures are still recorded.
- MCP record construction moves into `notify_observer`, so a deep-copy failure while building an MCP record is now logged and swallowed rather than propagating. This is an intended narrowing; it is unreachable in practice, since MCP arguments are pydantic-validated and payloads are JSON-safe dicts.
- The observer is never called inside an `except` block, so it cannot see the tool's exception through `sys.exc_info()`, and an observer failure's log never chains the tool's exception as `__context__`.
- A render failure is recorded as MCP records it: `render_error(<render exception>)` with `is_error=True`. The caller still gets the raw return value.
- Each entry point has its own duration boundary. MCP covers credentials, `bind_tools`, the tool, and rendering. `bind_tools` covers the tool method only.
- Out of scope: async observers, an exception object on the record, observing `bind_tools`' own identity resolution (it is not a tool call).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Observe direct tool calls (Priority: P1)

An adopter calls the engine through `bind_tools(..., on_call=observer)` and gets one `ToolCallRecord` per tool call, for logs and metrics.

**Why this priority**: The issue's purpose.

**Independent Test**: Bind tools over `InProcessClient` with a list-appending observer; call tools that succeed and fail.

**Acceptance Scenarios**:

1. **Given** tools bound with `on_call=records.append`, **When** `read_file(scope, area, name)` succeeds, **Then** exactly one record is appended with `tool == "read_file"`, `arguments == {"scope": scope, "area": area, "name": name}`, `result == render_result(<returned file>)`, `is_error is False`, `request_id is None`, and `duration_s` a `float >= 0`; and the call returns the same object the tool produced.
2. **Given** the same tools, **When** a tool raises a `WenchangError` (e.g. `read_file` of a missing file raises `NotFoundError`), **Then** exactly one record is appended with `is_error is True` and `result == render_error(<that exception>)`, and the caller receives the identical exception object.
3. **Given** a client whose method raises an off-contract exception (e.g. `RuntimeError("secret")`), **When** the tool is called, **Then** one record is appended whose `result` is the internal-category payload `render_error` produces (no `"secret"`), `is_error is True`, and the `RuntimeError` propagates unchanged.
4. **Given** tools bound with an observer, **When** each of the seven tools is called once, by attribute and again through `tools()[name]`, **Then** each call appends exactly one record whose `tool` is that tool's name (no prefix), in call order.
5. **Given** a tool called with optional arguments omitted (e.g. `list_prefix(scope)`), **When** the record arrives, **Then** `arguments` has every parameter of that tool by name with defaults filled in (`{"scope": scope, "area": None, "cursor": None}`), matching the MCP wrapper's argument mapping; positional and keyword calls give equal mappings.
6. **Given** a record, **When** the caller mutates a list it passed (e.g. `aliases`) after the call, or tries to assign into `record.arguments` or `record.result`, **Then** the record is unchanged (deep copies) and assignment raises `TypeError` (read-only mappings).
7. **Given** a call Python itself rejects before the tool runs (wrong arity or an unknown keyword), **When** it is made, **Then** `TypeError` propagates and no record is appended.
8. **Given** an observer, **When** a tool call completes, **Then** the observer has run on the calling thread before the call returns or raises.
9. **Given** an observer that captures `sys.exc_info()`, **When** a tool raises (contract or off-contract), **Then** the observer saw `(None, None, None)`.
10. **Given** a tool whose return value `render_result` cannot render (e.g. a client stub returning a non-conforming object, so `render_result` raises `TypeError`), **When** the tool is called, **Then** one record is delivered with `is_error is True` and `result == render_error(<that TypeError>)`, and the caller gets the raw return value.

---

### User Story 2 - A failing observer never breaks the call (Priority: P1)

**Why this priority**: Explicit acceptance criterion; observability must not change tool behavior.

**Independent Test**: An observer that raises; check the tool's outcome and the log.

**Acceptance Scenarios**:

1. **Given** an observer that raises `RuntimeError`, **When** a tool succeeds, **Then** the caller gets the normal return value, and one `ERROR` log record is emitted on logger `wenchang.tools` whose message names the tool, with `exc_info`.
2. **Given** an observer that raises, **When** a tool fails, **Then** the caller receives the tool's original exception object (not the observer's), and the observer failure is logged as in 2.1.
3. **Given** arguments that cannot be deep-copied (an `aliases` fixture that is a `list` subclass whose `__deepcopy__` raises), **When** the tool is called, **Then** the tool's outcome is unchanged, no record is delivered, and the failure is logged at `ERROR` on `wenchang.tools`.
4. **Given** a client whose method raises `RuntimeError("secret")` and an observer that raises, **When** the tool is called, **Then** no log record on `wenchang.tools` contains `"secret"`: not in its message, its formatted `exc_info` traceback, or any chained `__context__`/`__cause__`. The `RuntimeError` still reaches the caller.

---

### User Story 3 - Configuring the observer (Priority: P1)

**Acceptance Scenarios**:

1. **Given** `bind_tools` and `MemoryTools`, **When** their signatures are inspected, **Then** each has a keyword-only `on_call` defaulting to `None`, and `MemoryTools.on_call` returns the observer passed (or `None`).
2. **Given** `on_call=None` (the default), **When** tools are called, **Then** no observer runs and behavior is unchanged: every existing `tests/test_tools*.py` test passes unmodified.
3. **Given** `on_call="x"`, **When** `bind_tools` or `MemoryTools` is called, **Then** `TypeError("on_call must be callable or None")` is raised; given an `async def` observer, `TypeError("on_call must be a plain function, not async")`. `bind_tools` raises before calling the resolver.
4. **Given** an observer, **When** `descriptions()`, `tool_descriptions()`, and `inspect.signature` of each tool method are read, **Then** they are identical to those without an observer.

---

### User Story 4 - One implementation; MCP unchanged (Priority: P1)

**Acceptance Scenarios**:

1. **Given** an interpreter where `mcp` cannot be imported, **When** `wenchang.observer` and `wenchang.tools` are imported and `bind_tools(..., on_call=...)` is used, **Then** the imports succeed and records are delivered.
2. **Given** `wenchang.mcp`, **When** `ToolCallRecord` is imported from it, **Then** it is the same class as `wenchang.observer.ToolCallRecord`, and `wenchang.mcp.__all__` is unchanged.
3. **Given** `ToolCallRecord`, **When** its fields are inspected, **Then** they are, in order, `tool`, `arguments`, `result`, `is_error`, `request_id`, `duration_s`, and it is a frozen dataclass.
4. **Given** the existing `tests/test_mcp_server.py`, **When** the suite runs, **Then** every test passes unmodified: MCP records still carry the MCP request id, the registered (prefixed) name, credential and resolver failures, and observer failures are still logged on `wenchang.mcp`.
5. **Given** an MCP server with an observer, **When** one tool call is made, **Then** exactly one record is delivered (MCP does not also observe through `bind_tools`).
6. **Given** `wenchang.observer`, **When** `notify_observer` is called with an observer that raises, **Then** it logs at `ERROR` on the logger it was given and returns normally; `check_observer` raises the two `TypeError`s of 3.3 and accepts `None` or a plain callable.

### Edge Cases

- Off-contract exceptions are recorded with `render_error`'s internal payload; the observer never sees their message. The caller still gets the exception, so nothing is lost.
- `BaseException`s that are not `Exception`s (e.g. `KeyboardInterrupt`) from the tool or the observer are not caught and produce no record, as in MCP.
- `duration_s` covers the tool method only, not rendering, copying, or the observer.
- `MemoryTools` instances may be shared across threads; the observer then runs concurrently and must be thread-safe and fast, as in MCP.
- Identity-resolution failures in `bind_tools` raise before any tools exist; they produce no record (they are not tool calls). MCP still records them, because its boundary includes resolution.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: New module `wenchang.observer` MUST define `ToolCallRecord` (moved from `wenchang.mcp`, `request_id: str | None`), `ToolCallObserver`, `check_observer`, and `notify_observer`, with no import of `mcp`.
- **FR-002**: `MemoryTools.__init__` and `bind_tools` MUST accept keyword-only `on_call: ToolCallObserver | None = None`, validated by `check_observer`; `MemoryTools` MUST expose it as a read-only `on_call` property.
- **FR-003**: With an observer, each of the seven tool methods MUST deliver exactly one record per call that reaches the tool, through `notify_observer`, then return or re-raise the tool's own outcome.
- **FR-004**: `wenchang.mcp` MUST validate with `check_observer` and deliver through `notify_observer` (logger `wenchang.mcp`), with no record construction or observer error handling of its own, and MUST re-export `ToolCallRecord`.
- **FR-005**: ARCHITECTURE.md MUST describe `wenchang.observer` and the new parameters. ADR 0043 MUST record the decision, including:
  - `request_id: str | None`;
  - each entry point's duration boundary (MCP: credentials + `bind_tools` + tool + render; `bind_tools`: the tool method only);
  - the MCP deep-copy-failure narrowing;
  - that a subclass override of a tool method without the decorator is not observed.

  The `ToolCallRecord` docstring MUST define `tool`, `arguments`, `result`, `request_id`, and `duration_s` per entry point.
- **FR-007**: `evals/server.py` MUST narrow `record.request_id` to `str` with an explicit `if request_id is None: raise ...` before building `TraceCall`, because MCP records always carry an id.
- **FR-006**: `make check` MUST pass, with every existing test unmodified except the one approved line below.

## Success Criteria *(mandatory)*

- **SC-001**: An adopter using `bind_tools` gets one record per tool call without wrapping tools.
- **SC-002**: `tests/test_mcp_server.py`, `tests/test_evals_server.py`, and `tests/test_tools*.py` pass and type-check (`make typecheck`) unmodified. Deliberate exception, approved by the orchestrator: `tests/test_tools.py` adds `"wenchang.observer"` to `ALLOWED_WENCHANG_IMPORTS`. This one line records the new module boundary and does not weaken the test, which still forbids storage, google, and nested imports.

## Assumptions

- Changing `request_id` from `str` to `str | None` is acceptable: runtime MCP values are unchanged; strictly typed consumers that use it as `str` must narrow it.
- `bind_tools` callers correlate records without a request id: the observer runs synchronously on the calling thread, so a `contextvars` value or thread-local set by the caller is visible to it.
