# Tasks: delete_file

**Linear issue**: AIE-1037 | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

Each task runs test-writer (failing tests), then implementer (make them
pass), then a green `make check`, in order.

## T1 — Storage.delete_if_version

Add `delete_if_version` to the `Storage` protocol, `InMemoryStorage`, and
`GcsStorage`, following plan.md.

Acceptance: spec US4.1–6. Conformance cases go in
`tests/storage_conformance.py`, and GCS-only cases in
`tests/integration/test_storage_gcs.py`. Covers FR-005. Also run
`make test-integration`.

## T2 — MemoryStore.delete_file

Add `delete_file` to `MemoryStore`, following the algorithm and error table
in plan.md.

Acceptance: spec US1.1–3, US2.1–4, US3.1–3. New file
`tests/test_core_delete_file.py`. Covers FR-001–FR-004 and FR-006.
