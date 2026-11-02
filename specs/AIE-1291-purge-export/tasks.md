# Tasks: AIE-1291 Purge and export all memory for an entity

Each task's tests are written by `test-writer` (edits `tests/**` only) and
seen failing before `implementer` (edits `src/wenchang/core.py` only)
starts the task. Docs belong to `doc-updater` (`ARCHITECTURE.md`,
`docs/**`, `specs/**`). Subagents are spawned without `name=`.

**Blocked on:** AIE-1293's implementation being committed and rebased in
(the orchestrator signals when). Nothing below starts before that.

- [ ] T1 — `export`, `ExportedObject`, and the public names.
  - test-writer: US4 and US6.2 (`tests/test_core_export.py`,
    `tests/test_core_api_surface.py`), plus the export cases of US5 (5.2's
    export side, 5.3's export, 5.4's export) in a new
    `EntityPurgeExportConformance` mixin in `tests/storage_conformance.py`,
    subclassed in `tests/test_storage_memory.py` and
    `tests/integration/test_storage_gcs.py`. All seen red.
  - implementer: the shared argument check, `ExportedObject`,
    `MemoryStore.export`, `PURGE_MAX_PASSES`, and `PurgeIncompleteError`
    (6.2 imports it). `make check` green.
- [ ] T2 — `purge`, including its index-cache wrapper.
  - test-writer: US1, US2, US3 (`tests/test_core_purge.py`), and the purge
    cases of US5 (5.1, 5.2's round trip, 5.3's purge, 5.4's purge) in
    `EntityPurgeExportConformance`. All seen red.
  - implementer: `max_passes` validation, `_purge_passes`, and `purge` with
    the invalidation wrapper and failure-path logging. `make check` green.
- [ ] T3 — API-surface guard.
  - test-writer: US6.1. It passes as soon as it's written: it guards
    against later drift and adds no behavior, so there is no red phase and
    no implementer step.
- [ ] T4 — Integration run (lead): `make emulator-up`, then
  `make test-integration`; the US5 mixin runs on `GcsStorage`.
- [ ] T5 — Docs.
  - doc-updater: ADR 0038; ARCHITECTURE.md (core entry, error-taxonomy
    section, storage conformance description, concurrency section);
    `review-pr.md`. `make check` green.
