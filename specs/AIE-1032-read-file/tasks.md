# Tasks: read_file and the storage layer (AIE-1032)

**Input**: [spec.md](spec.md), [plan.md](plan.md)

Tasks run in order. Each is test-writer (tests) then implementer (`src/`).
`make check` green after each; T3 also runs `make test-integration`.

## T1 — Path validation

Build `wenchang.paths.is_valid_path` in `src/wenchang/paths.py`; tests in
`tests/test_paths.py`.

Acceptance: spec US2 scenarios 3–4 and FR-007; every row of plan.md's
`is_valid_path` table; never raises for any `str`.

## T2 — Storage protocol, in-memory fake, conformance suite

Build `Storage`, `StoredObject` in `src/wenchang/storage/__init__.py` and
`InMemoryStorage` in `src/wenchang/storage/memory.py`. Tests: the shared
`StorageConformance` class in `tests/storage_conformance.py`, run against
`InMemoryStorage` from `tests/test_storage_memory.py`.

Acceptance: spec US4 scenarios 1–6, FR-001, FR-003; tokens unique across
keys within one instance; the caller's metadata mapping is copied on `put`
(mutating it afterwards doesn't change stored state).

## T3 — GCS storage implementation

Build `GcsStorage` in `src/wenchang/storage/gcs.py`. Tests:
`tests/integration/test_storage_gcs.py` (subclass of `StorageConformance`
over a fresh emulator bucket, `@pytest.mark.integration`) and
`tests/test_storage_gcs_errors.py` (stubbed bucket/blob, unit).

Acceptance: spec US4 scenarios 1–6 against the emulator; US3 scenario 2 and
FR-004 (every exception in plan.md's mapping list → the stated reason;
other exceptions propagate); `get` retries when download fails with
412/404 after `get_blob`, up to 3 attempts, then
`BackendUnavailableError(UNAVAILABLE)`; FR-008 (no other `src/` module
imports `google.cloud`).

## T4 — read_file

Build `MemoryFile`, `MemoryStore` in `src/wenchang/core.py`; tests in
`tests/test_core_read_file.py` over `InMemoryStorage` and a raising stub
`Storage`.

Acceptance: spec US1 scenarios 1–6, US2 scenarios 1, 2, 5, US3 scenarios 1,
3, 4, FR-005, FR-006; `INVALID_PATH` cases never call storage (stub records
calls); returned `path` is the caller's string.

## T5 — Docs (doc-updater)

ARCHITECTURE.md: move `storage` and `core` from planned to implemented
(narrowing `core` to `read_file` implemented, the rest planned), add
`paths`. ADR for the six decisions in plan.md. Draft `review-pr.md`.
