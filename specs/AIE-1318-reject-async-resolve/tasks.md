# Tasks: AIE-1318

Test-first: test-writer writes failing tests (`tests/**` only), then the implementer makes them pass (`src/**`). Spec refs are `spec.md` user stories. Existing tests are not modified, except one that expects `ResolverFailureError` for an async `resolve` through `bind_tools` (spec SC-002).

## T1 - Tests (test-writer)

- [x] T1a `tests/test_identity.py`: `check_resolver` unit tests (US3.1, US3.2).
- [x] T1b `tests/test_tools.py`: `bind_tools` rejection over the five variants, no `ResolverFailureError`, no never-awaited `RuntimeWarning`; sync accepted; raising `resolve` access and sync-returns-coroutine stay `ResolverFailureError`; ordering with async `on_call` (US1.3-1.4, US2, US3.3). The no-warning check uses `warnings.catch_warnings(record=True)` + `simplefilter("always")` + `gc.collect()`, not `-W error`. Update any existing test that expects `ResolverFailureError` for an async `resolve`.
- [x] T1c `tests/test_mcp_server.py`: `register_memory_tools` and `build_server` rejection over the five variants with nothing registered; sync accepted; `isinstance` `TypeError` first; async resolver plus async `credentials_from_context` raises the resolver `TypeError` first (US1.1-1.2, 1.4, US2.1, US3.4-3.5). Reuse the existing tool/resource listing helpers; `build_server` cases assert only the `TypeError`. Variant fixtures are pyright-strict clean.
- [x] Every docstring references AIE-1318. Expected failing state: `check_resolver` does not exist and async `resolve` is not rejected.

## T2 - Implementation (implementer)

- [x] T2a `src/wenchang/identity.py`: add `check_resolver` per plan.md (no `__all__` exists; do not add one).
- [x] T2b `src/wenchang/mcp.py`: call `check_resolver(resolver)` in `_validate` right after the `isinstance` check.
- [x] T2c `src/wenchang/tools.py`: call `check_resolver(resolver)` in `bind_tools` after `check_observer(on_call)` and before `resolve_identity`.
- [x] T2d Docstrings: `bind_tools` (resolver check beside the `on_call` ordering line), `register_memory_tools`/`build_server`/`_validate` where they list what is validated, `IdentityResolver` and its `resolve` ("a plain, non-async method"). No ticket IDs in `src/`.

## T3 - Docs (doc-updater; `site-src/` via general-purpose, since doc-updater's scope excludes it)

- [x] T3a general-purpose: `site-src/reference.md` (incl. `bind_tools` and `register_memory_tools` parameter sections), `site-src/identity.md`, `site-src/integrate-without-mcp.md`, `site-src/integrate-new-server.md` per plan.md.
- [x] T3b doc-updater: ARCHITECTURE.md (identity, `bind_tools` incl. ordering, `register_memory_tools`, invariant and error-taxonomy mentions).
- [x] T3c doc-updater: ADR `docs/adr/0044-reject-async-resolver.md`, cross-referencing ADR 0027 and ADR 0014 (amends 0014 for the async case; 0014 not edited) and recording the MCP per-call edge case.
- [x] T3d doc-updater: `specs/AIE-1318-reject-async-resolve/review-pr.md` with the AC-to-test mapping.

## T4 - Verify (lead)

- [x] `make check` is green.
- [x] `git diff --diff-filter=MDR origin/main -- tests` shows only the approved `ResolverFailureError` -> `TypeError` change, if any such test existed.

## Order

T1 -> T2 -> T3 -> T4. No storage change, so `make test-integration` is not required.
