# Tasks: list_prefix

**Linear issue**: AIE-1035 | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

Each task runs test-writer (failing tests) → implementer (make them pass) →
`make check` green, in order. No task runs in parallel with another.

## T1 — Storage.list_page (protocol + in-memory)

Add `ListedObject`, `Storage.list_page`, and `InMemoryStorage.list_page`.

Acceptance: spec US4.1–4, as new cases in `tests/storage_conformance.py`.
FR-005.

## T2 — GcsStorage.list_page

Implement for GCS; the conformance cases from T1 run against fake-gcs-server
(`make emulator-up`, `make test-integration`). Unit-test backend error
mapping with a stub bucket if the existing GCS unit tests do so for `get`.

Acceptance: spec US4.1–4 against GCS. FR-005.

## T3 — is_valid_prefix

Add `paths.is_valid_prefix`.

Acceptance: spec US3.1 prefix table (valid: `a/`, `a/e/`, `a/e/x/`).

## T4 — MemoryStore.list_prefix

Add `FileEntry`, `ListPage`, `ListCursor`, `list_page_size`, and
`list_prefix` per plan.md algorithm.

Acceptance: spec US1.1–6, US2.1–5, US3.1–4, edge case "short page with
cursor". New file `tests/test_core_list_prefix.py`. FR-001–FR-004.
