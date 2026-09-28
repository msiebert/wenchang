# Tasks: write_file

**Linear issue**: AIE-1033 | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

Each task runs test-writer (failing tests) → implementer (make them pass) →
`make check` green, in order. No task runs in parallel with another.

## T1 — Conditional put in the protocol and the in-memory fake

Add `PreconditionFailedError` and `Storage.put_if_version` (plan.md,
`storage/__init__.py`) and implement it in `InMemoryStorage`.

Acceptance: spec US7 scenarios 1–6, as `StorageConformance` cases in
`tests/storage_conformance.py`, exercised by `tests/test_storage_memory.py`.
FR-001, FR-002.

## T2 — Conditional put in GcsStorage

Implement `GcsStorage.put_if_version` per plan.md.

Acceptance: stubbed cases in `tests/test_storage_gcs_errors.py` —
`if_generation_match=0` for `None` and `int(token)` otherwise;
non-canonical tokens (`""`, `"abc"`, `"0"`, `"-1"`, `"007"`) raise
`PreconditionFailedError` with no upload call; GCS `PreconditionFailed` →
`PreconditionFailedError(key)`; timeout → `BackendUnavailableError(TIMEOUT)`;
unavailable → `BackendUnavailableError(UNAVAILABLE)`. Spec US6.3. The T1
conformance cases pass against fake-gcs-server (`make test-integration`).
FR-002, FR-008.

## T3 — MemoryStore.write_file: create, replace, conflict, stamping

Add the `clock` constructor option and `write_file` (plan.md steps 1, 3–6;
size check is T4).

Acceptance: spec US1.1–2, US2.1–6, US3.1–3, US5.1–3, US6.1–2, and the edge
cases (deleted-before-conflict-fetch → `FILE_ABSENT`; corrupt object on
conflict fetch propagates). New file `tests/test_core_write_file.py`.
FR-003, FR-004, FR-005, FR-007.

## T4 — Byte ceiling

Add the `max_file_bytes` constructor option and plan.md step 2.

Acceptance: spec US4.1–6 and US3.2 for the oversize case, in
`tests/test_core_write_file.py`. FR-006.
