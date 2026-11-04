# PR Review: AIE-1318 — Reject async resolve at registration

## What changed & why

An `async def resolve` used to be accepted at registration and only failed at call time, as a coroutine returned instead of an `Identity`. New `wenchang.identity.check_resolver` raises `TypeError("resolver.resolve must be a plain method, not async")` for detectably async `resolve` (async method, async staticmethod, async classmethod, partial of an async fn, async generator, object with async `__call__`, partial of an async-call object; `check_resolver` unwraps partials). It runs from `mcp._validate` (so `register_memory_tools` and `build_server`) and from `bind_tools`, before anything is registered or resolved. `resolve_identity` is unchanged.

## Acceptance criteria → tests

Spec references are User Story (US) scenarios in `spec.md`.

| Acceptance criterion (Given/When/Then) | Test(s) |
| --------------------------------------- | ------- |
| US1.1: async `resolve`, `register_memory_tools` raises the `TypeError`; nothing registered | `tests/test_mcp_server.py:1385` `test_register_rejects_async_resolve` |
| US1.2: async `resolve`, `build_server` raises the same `TypeError` | `tests/test_mcp_server.py:1400` `test_build_server_rejects_async_resolve` |
| US1.3: async `resolve`, `bind_tools` raises `TypeError`, no `ResolverFailureError`, no never-awaited warning | `tests/test_tools.py:646` `test_bind_tools_rejects_async_resolve` |
| US1.4: all seven variants through all three entry points | The three parametrized tests above |
| US2.1: sync resolver accepted by all three entry points | `tests/test_tools.py:676` `..._accepts_sync_resolver_after_resolver_check`; `tests/test_mcp_server.py:1410` `test_sync_resolver_is_accepted_by_both_entry_points` |
| US2.2: raising `resolve` read stays `ResolverFailureError` | `tests/test_tools.py:683` `..._raising_resolve_read_stays_resolver_failure` |
| US2.3: sync `resolve` returning a coroutine stays `ResolverFailureError` | `tests/test_tools.py:697` `..._sync_resolve_returning_coroutine_stays_resolver_failure` |
| US2.4: existing tests pass unmodified | Full suite via `make check` |
| US3.1: `check_resolver` returns `None` for sync, raises per variant, never calls `resolve` | `tests/test_identity.py:1044` `..._accepts_sync_resolver`; `:1056` `..._rejects_each_async_variant`; `:1066` `..._never_calls_resolve` |
| US3.2: missing or raising `resolve` read returns `None` | `tests/test_identity.py:1078` `..._returns_none_without_resolve_attribute`; `:1086` `..._returns_none_when_resolve_read_raises` |
| US3.3: async `on_call` plus async `resolve`, `on_call` `TypeError` first | `tests/test_tools.py:717` `..._async_on_call_error_precedes_resolver_check` |
| US3.4: non-`IdentityResolver`, `isinstance` `TypeError` first | `tests/test_mcp_server.py:1421` `test_non_resolver_error_precedes_async_resolve_check` |
| US3.5: async resolver plus async `credentials_from_context`, resolver `TypeError` first | `tests/test_mcp_server.py:1434` `test_async_resolve_error_precedes_async_credentials_error` |

The MCP per-call edge case (resolver swapped to async after registration) has no test, by decision in the spec.

## Architecture / ADR changes

- New [ADR 0044](../../docs/adr/0044-reject-async-resolver.md); amends ADR 0014 for the async case and extends the ADR 0027 startup checks.
- `ARCHITECTURE.md`: identity module (`check_resolver`), `bind_tools`, `register_memory_tools` startup checks and per-call binding, module-dependency note, identity invariant, error taxonomy.
- `site-src/` pages are updated separately.

## Deviations from spec

- None.

## Look closely at

- `bind_tools` now raises `TypeError` for an async `resolve` where it used to raise `ResolverFailureError`. No existing test asserted the old behavior.
- Detection is best effort: a sync `def` returning a coroutine is undetectable and still fails at call time as `ResolverFailureError`.
- The MCP per-call path calls `bind_tools` inside `except Exception`, so a resolver swapped to async after registration renders as an "internal" error with an `ERROR` log; `resolve` is read twice per call.
- Ordering: `isinstance` check, then `check_resolver`, then `credentials_from_context`/`on_call` checks in `_validate`; `check_observer` then `check_resolver` then `resolve_identity` in `bind_tools`.

## Follow-ups

- None identified.

## make check

ruff format/check clean; pyright 0 errors; 5877 passed, 18 skipped, 46 deselected.

## Reviewer notes

- Spec review failed first pass with 3 majors, all fixed: the never-awaited warning test was untestable (now `catch_warnings(record=True)` + `gc.collect()`); doc touch points were incomplete (`integrate-new-server.md`, more `ARCHITECTURE.md` lines, ADR cross-refs); source docstrings were missing from the plan. Re-review passed.
- Code review (spec fidelity) passed, nits only.
- Correctness review found no bugs. One false negative, `functools.partial` wrapping an async-`__call__` object, is fixed (`check_resolver` unwraps partials). A missing async-classmethod variant was added to all three test files. `BaseException` while reading `resolve` propagates, consistent with `resolve_identity`; left as is.
