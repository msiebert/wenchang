# Tasks: AIE-1296

Test-first: test-writer writes failing tests (`tests/**` only), then the implementer makes them pass (`src/**`). The `evals/server.py` change (T3c) is done by the lead or a general-purpose agent, since the implementer's hook scope excludes `evals/`. Spec refs are `spec.md` user stories. `tests/test_mcp_server.py`, `tests/test_evals_server.py`, and existing `tests/test_tools*.py` are not modified.

## T1 - Shared observer module (US4.3, US4.6)

- [ ] T1a test-writer: `tests/test_observer.py` — `ToolCallRecord` shape (frozen dataclass, field order, `request_id` accepts `None`), `check_observer` (accepts `None`/plain callable; both `TypeError` messages), `notify_observer` (delivers a record with read-only deep copies; an observer or copy failure logs `ERROR` on the given logger with the tool name and returns). Expected failing state: `wenchang.observer` does not exist.
- [ ] T1b implementer: add `src/wenchang/observer.py` per plan.md.

## T2 - Observer on MemoryTools / bind_tools (US1, US2, US3, US4.1)

- [ ] T2a test-writer: `tests/test_tools_observer.py`, covering:
  - US1.1-1.10, including empty `sys.exc_info()` inside the observer and a render failure recorded as `render_error`;
  - US1.9: make the tool call outside any `except` block;
  - US2.1-2.4, where the US2.3 aliases fixture is a `list` subclass with a raising `__deepcopy__`, and US2.4 checks for no `"secret"` in the `wenchang.tools` logs, tracebacks, or chained exceptions. Put `"secret"` only in the client stub's exception message, never on the observer's raise line;
  - US3.1-3.4;
  - US4.1 (subprocess with `mcp` blocked).

  Expected failing state: `on_call` is not a parameter.
- [ ] T2b implementer: `on_call` on `MemoryTools` and `bind_tools`, the per-call wrapper, and the `wenchang.tools` logger, per plan.md:
  - the signature is computed at decoration time;
  - the decorator has the `Concatenate[MemoryTools, _P]` annotation, and the wrapper is cast to it;
  - the observer is never called inside `except`; the `except` block stores `error = exc` (since `exc` is unbound when the block ends), the wrapper does `raise error`, and `finally` clears it;
  - the wrapper reads `self.on_call`, not `self._on_call`;
  - `"MemoryTools"` is quoted in the decorator annotations, because the decorator is defined before the class (3.11);
  - a render failure is recorded as `render_error`;
  - `check_observer` runs after the existing `__init__` checks.

## T3 - MCP uses the shared implementation (US4.2, US4.4, US4.5)

- [ ] T3a test-writer: `tests/test_mcp_observer_shared.py` — `wenchang.mcp.ToolCallRecord is wenchang.observer.ToolCallRecord`; one MCP call yields exactly one record; MCP delivery goes through `wenchang.observer.notify_observer` (monkeypatch it on `wenchang.mcp`'s import). Expected failing state: identity and delivery-path assertions fail.
- [ ] T3b implementer: refactor `src/wenchang/mcp.py` per plan.md; `tests/test_mcp_server.py` passes unmodified.
- [ ] T3c lead or general-purpose agent: in `evals/server.py`, narrow `r.record.request_id` with an explicit `if request_id is None: raise RuntimeError(...)` before building `TraceCall` (`TraceCall.request_id` stays `str`).

## T4 - Verify

- [x] T4 lead:
  - `make check` is green, including `make typecheck` with existing `tests/test_tools*.py` unmodified apart from the approved allowlist line (bound-method calls still type-check through the decorator).
  - `git diff --diff-filter=MDR origin/main -- 'tests/test_tools*.py' tests/test_mcp_server.py tests/test_evals_server.py` shows exactly one change: `+        "wenchang.observer",` in `ALLOWED_WENCHANG_IMPORTS` in `tests/test_tools.py` (an approved exception; see spec.md SC-002).

## T5 - Docs (doc-updater)

- [x] T5a ARCHITECTURE.md updates per plan.md.
- [x] T5b ADR `docs/adr/0043-shared-tool-call-observer.md`, covering the items listed in plan.md's Docs section; pointer in ADR 0027 decision 10.
- [x] T5c `specs/AIE-1296-bind-tools-on-call/review-pr.md` with the AC-to-test mapping.

## Order

T1 -> T2 -> T3 (each test-writer then implementer), then T4, then T5. No storage change, so `make test-integration` is not required.
