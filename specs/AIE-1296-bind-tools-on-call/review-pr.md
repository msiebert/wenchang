# PR Review: AIE-1296 — on_call observer for bind_tools

## What changed & why

`bind_tools` and `MemoryTools` take `on_call=None`, so adopters calling the engine directly get one `ToolCallRecord` per tool call without wrapping tools. `ToolCallRecord` and the delivery plumbing (`check_observer`, `notify_observer`) move into a new stdlib-only module, `wenchang.observer`. `wenchang.mcp` re-exports the record and delivers through it at its own boundary. `request_id` becomes `str | None` (`None` for direct calls), and `evals/server.py` narrows it.

## Acceptance criteria → tests

Files: `TO` = `tests/test_tools_observer.py`, `O` = `tests/test_observer.py`, `MS` = `tests/test_mcp_observer_shared.py`.

| Acceptance criterion | Test(s) |
| -------------------- | ------- |
| US1.1 success: one record, bare name, `request_id=None`, same return object | `TO::test_successful_call_produces_one_record` |
| US1.2 contract error: `render_error` record, same exception | `TO::test_contract_error_produces_one_error_record` |
| US1.3 off-contract error: internal payload, no `"secret"` | `TO::test_off_contract_error_is_recorded_as_internal` |
| US1.4 all 7 tools, by attribute and `tools()[name]` | `TO::test_each_tool_produces_one_record_by_attribute_and_by_name` |
| US1.5 defaults filled; positional == keyword | `TO::test_arguments_have_defaults_filled`, `TO::test_positional_and_keyword_calls_give_equal_arguments` |
| US1.6 read-only deep copies | `TO::test_record_is_a_read_only_deep_copy` |
| US1.7 arity / unknown keyword: no record | `TO::test_rejected_call_produces_no_record` |
| US1.8 observer runs on calling thread before return | `TO::test_observer_runs_on_calling_thread_before_return` |
| US1.9 empty `sys.exc_info()` in observer | `TO::test_observer_sees_no_active_exception` |
| US1.10 render failure recorded as `render_error`; raw value returned | `TO::test_render_failure_is_recorded_as_error` |
| US2.1 raising observer on success is logged | `TO::test_failing_observer_on_success_is_logged` |
| US2.2 raising observer on failure keeps the tool's exception | `TO::test_failing_observer_on_failure_keeps_tool_exception` |
| US2.3 uncopyable arguments: logged, no record | `TO::test_uncopyable_arguments_are_logged_not_delivered` |
| US2.4 no `"secret"` in logs, tracebacks, or chains | `TO::test_observer_failure_log_does_not_leak_tool_exception` |
| US3.1 keyword-only `on_call=None`; `on_call` property | `TO::test_on_call_is_keyword_only_defaulting_to_none`, `TO::test_on_call_property_returns_the_observer` |
| US3.2 default: behavior unchanged | `TO::test_no_observer_by_default`; existing `tests/test_tools*.py` (one approved allowlist line; see below) |
| US3.3 bad / async observer `TypeError`; `bind_tools` before resolver | `TO::test_memory_tools_rejects_bad_observer`, `TO::test_bind_tools_rejects_bad_observer_before_resolving` |
| US3.4 descriptions and signatures unchanged | `TO::test_descriptions_and_signatures_are_unchanged_by_observer` |
| US4.1 works without `mcp` | `TO::test_observer_works_without_mcp` |
| US4.2 `mcp` re-exports the record; `__all__` unchanged | `MS::test_mcp_reexports_the_shared_record`, `MS::test_mcp_all_is_unchanged` |
| US4.3 record shape | `O::test_record_is_a_frozen_dataclass_with_ordered_fields`, `O::test_record_request_id_accepts_none` |
| US4.4 MCP behavior unchanged | existing `tests/test_mcp_server.py`, passing unmodified |
| US4.5 one record per MCP call, via `notify_observer` | `MS::test_one_mcp_call_delivers_one_record`, `MS::test_mcp_delivers_through_notify_observer` |
| US4.6 `check_observer` / `notify_observer` | `O::test_check_observer_*` (3), `O::test_notify_*` (4) |
| Edges: `BaseException` passes through; duration excludes observer | `TO::test_base_exception_from_tool_propagates_without_record`, `TO::test_base_exception_from_observer_propagates`, `TO::test_duration_excludes_observer_time` |

## Architecture / ADR changes

- New [ADR 0043](../../docs/adr/0043-shared-tool-call-observer.md); [ADR 0027](../../docs/adr/0027-mcp-host-adapter.md) decision 10 has an amendment pointer.
- `ARCHITECTURE.md`: new **observer** module-map entry and bird's-eye mention; **tools** gains the `on_call` signatures and direct-call behavior; the **mcp** `on_call` bullet points at the shared record; diagram notes list `observer`.

## Deviations from spec

- **Approved exception to "existing tests unmodified":** `tests/test_tools.py` adds one line, `"wenchang.observer"`, to `ALLOWED_WENCHANG_IMPORTS` (used by `test_tools_module_imports_are_restricted`). This records the new module boundary. It does not weaken the test, which still forbids storage, google, and nested imports.
- Accepted narrowing (spec, ADR 0043): an MCP record deep-copy failure is now logged and swallowed, not propagated.

## Look closely at

- `_observed` in `src/wenchang/tools.py`: nothing runs inside `except` but the assignment; `raise error` re-raises the original object; `finally` clears locals.
- The `cast`-based `Concatenate["MemoryTools", _P]` typing keeps bound-method calls type-checked.
- `request_id: str | None` is a typing-level change to a public MCP type (accepted pre-1.0).

## Follow-ups

- None.
