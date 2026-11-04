# Tasks: Map RetryError to BackendUnavailableError (AIE-1317)

Tests first; implementation never edits `tests/`. Test docstrings cite AIE-1317.

- [ ] **T1 — Tests (test-writer).** In `tests/test_storage_gcs_errors.py`: extend `TIMEOUT_EXCEPTIONS` with `RetryError("m", ServiceUnavailable("x"))`, `RetryError("m", None)` and a 408 `GoogleAPICallError` (AC1, AC2); add `assert excinfo.value.__cause__ is exc` to the shared parametrized TIMEOUT tests (a strengthening, not a Constitution II weakening); add the real-`Retry` exhaustion tests (AC3) and the propagates-unchanged tests (AC4). Run them and confirm the new ones fail before starting T2 (Constitution I).
- [ ] **T2 — Implementation (implementer).** Add the two `TIMEOUT` cases to `_map_backend_error` in `src/wenchang/storage/gcs.py`; `make check` green (AC5).
- [ ] **T3 — Docs (doc-updater).** ARCHITECTURE.md storage-bullet clause; `review-pr.md` (states the no-ADR rationale). No glossary change.
