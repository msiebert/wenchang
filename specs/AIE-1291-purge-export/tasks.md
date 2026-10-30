# Tasks: AIE-1291 Purge and export all memory for an entity

Tests first for each task; implementation never edits `tests/`. Rebase onto
the final `AIE-1293-index-cache` tip before T1.

- [ ] T1 — `export` and `ExportedObject`. Tests: US4, US6.2
  (`tests/test_core_export.py`). Implement the shared argument check,
  `ExportedObject`, and `MemoryStore.export` in `src/wenchang/core.py`.
- [ ] T2 — `purge` and `PurgeIncompleteError`. Tests: US1, US2
  (`tests/test_core_purge.py`). Implement `PURGE_MAX_PASSES`,
  `PurgeIncompleteError`, the pass loop, and `MemoryStore.purge`.
- [ ] T3 — Index cache interaction. Tests: US3 (same file). Implement the
  invalidate-after-deletes wrapper and its logging.
- [ ] T4 — Storage conformance. Tests: US5 in `tests/storage_conformance.py`;
  run on `InMemoryStorage` (`make test`) and `GcsStorage`
  (`make emulator-up`, `make test-integration`). Expected to pass on T1–T3.
- [ ] T5 — API surface. Tests: US6.1. Expected to pass with no change.
- [ ] T6 — Docs: ADR 0038, ARCHITECTURE.md, review-pr.md. `make check` and
  `make test-integration` green.
