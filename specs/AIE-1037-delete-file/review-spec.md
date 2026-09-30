# Spec Review: AIE-1037 — delete_file

## What & why

Add `MemoryStore.delete_file(path, expected_version)`, which removes a
memory file only if it is still at `expected_version`. This is the
"delete the whole file" half of forgetting (Notion 8.1). Storage has no
delete today, so the `Storage` protocol gains
`delete_if_version(key, expected)`, implemented by the in-memory fake and by
GCS (using `if_generation_match`).

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | file at `V` | `delete_file(path, V)` | returns `None`; `read_file` → `FILE_ABSENT`; gone from `list_prefix`; siblings untouched |
| 2 | deleted path | `write_file(path, …, None)` | recreated |
| 3 | caller holds stale `V1`, file at `V2` | delete | `VersionConflictError(current content, V2)`; file kept |
| 4 | delete at `V` succeeded | identical retry | `NotFoundError(FILE_ABSENT)` |
| 5 | another write lands between read and delete | delete | `VersionConflictError` with post-race content/version; file kept |
| 6 | file gone by the time the conditional delete runs | delete | `NotFoundError(FILE_ABSENT)` |
| 7 | malformed path | delete | `NotFoundError(INVALID_PATH)`, no storage call |
| 8 | no file at a valid path | delete | `NotFoundError(FILE_ABSENT)` |
| 9 | backend timeout/unavailable | delete | `BackendUnavailableError` propagates |
| 10 | storage: object at `T` / other token / absent | `delete_if_version(key, T)` | removed / `PreconditionFailedError` / `PreconditionFailedError` (both backends) |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| Protocol gets only `delete_if_version` | Also an unconditional `delete` | Every mutation is guarded, and nothing calls an unguarded delete. |
| Absent → `PreconditionFailedError` in storage | New storage-level not-found exception | Mirrors `put_if_version`. Core re-reads to tell the cases apart. |
| Already-absent → `FILE_ABSENT` (including a retry after a landed delete) | Idempotent success when absent | Consistent with every other call. The file is gone either way. Tool wording (AIE-1044) can say "already gone = done". |
| Returns `None`, no `source` | Return last content/version; stamp source | Nothing remains to version or stamp. |
| Metadata not parsed on delete | Validate metadata first | A corrupt file should still be deletable. |

## Files/modules to be touched

- `src/wenchang/storage/{__init__,memory,gcs}.py`, `src/wenchang/core.py`
- `tests/storage_conformance.py`, `tests/integration/test_storage_gcs.py`,
  `tests/test_core_delete_file.py` (new), plus any `Storage` test doubles
  that need the new method for pyright
- `ARCHITECTURE.md`, `docs/adr/0012-delete-file.md` (storage protocol change)

## Open questions / assumptions

- **Your call:** should deleting an already-absent file raise `FILE_ABSENT`
  (proposed), or return success so that deletes are idempotent?
- `system/` read-only enforcement is left to AIE-1040.

## Risks

- The GCS client retries conditional deletes on its own. A landed delete
  whose response was lost surfaces as `FILE_ABSENT`, not success. This is
  harmless only if the tool wording treats it as done.
