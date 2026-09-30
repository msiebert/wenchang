# PR Review: AIE-1037 — delete_file

## What changed & why

Adds `MemoryStore.delete_file(path, expected_version) -> None`, which
removes the file at `path` only if it is still at `expected_version` — the
"delete the whole file" half of forgetting (Notion Section 8.1). The
`Storage` protocol had no delete, so it gains
`delete_if_version(key, expected) -> None`, a guarded delete with no
unconditional counterpart, implemented by both `InMemoryStorage` (in
memory) and `GcsStorage` (`blob.delete(if_generation_match=...)`). An
absent object or a version mismatch both raise the existing storage-level
`PreconditionFailedError`; `core` re-reads on that failure to tell a
conflict from an absence, the same pattern used elsewhere.

## Acceptance criteria → tests

| Acceptance criterion (Given/When/Then) | Test(s) |
| --------------------------------------- | ------- |
| US1.1 — delete at current version returns `None`; `read_file` then raises `FILE_ABSENT`; gone from `list_prefix` | `test_delete_file_at_current_version_removes_file_from_read_and_list` |
| US1.2 — a sibling file under the same prefix is unchanged (content, metadata, version) | `test_delete_file_leaves_other_file_under_same_prefix_unchanged` |
| US1.3 — after delete, `write_file(path, ..., None)` recreates the file | `test_delete_file_then_write_file_with_none_recreates_it` |
| US2.1 — stale token raises `VersionConflictError(current_content, current_version)`, file unchanged | `test_delete_file_stale_token_raises_version_conflict_and_leaves_file` |
| US2.2 — identical retry after a successful delete raises `NotFoundError(FILE_ABSENT)` | `test_delete_file_identical_retry_after_success_raises_file_absent` |
| US2.3 — a write landing between the version check and the conditional delete raises `VersionConflictError` with the post-race content/version, file still present | `test_delete_file_race_before_delete_raises_conflict_with_content_after_race` |
| US2.4 — precondition failure whose re-read finds the object gone raises `NotFoundError(FILE_ABSENT)` | `test_delete_file_deleted_mid_delete_raises_file_absent` |
| US3.1 — malformed path raises `NotFoundError(INVALID_PATH)`, no storage call | `test_delete_file_malformed_path_raises_invalid_path_without_storage` (parametrized) |
| US3.2 — well-formed path with no object raises `NotFoundError(FILE_ABSENT)` | `test_delete_file_no_file_raises_file_absent` |
| US3.3 — `BackendUnavailableError` propagates from `get` and from `delete_if_version` | `test_delete_file_propagates_backend_unavailable_from_get`, `test_delete_file_propagates_backend_unavailable_from_delete_if_version` |
| (implementation detail, not in spec's numbered list) — corrupt metadata does not block delete | `test_delete_file_with_corrupt_metadata_still_deletes` |
| US4.1 — `delete_if_version(key, T)` at the current token removes the object, returns `None` | `test_delete_if_version_with_current_token_deletes_object` (`StorageConformance`, both backends) |
| US4.2 — a stale token raises `PreconditionFailedError`, object unchanged | `test_delete_if_version_with_stale_token_raises_and_leaves_object_unchanged` (`InMemoryStorage`; skipped for `GcsStorage`, see below) |
| US4.3 — no object at `key` raises `PreconditionFailedError` | `test_delete_if_version_on_missing_key_raises` (both backends) |
| US4.4 — `put_if_version(key, ..., None)` succeeds after a delete (create-if-absent works again) | `test_put_if_version_none_succeeds_after_delete` (both backends) |
| US4.5 — deleting one key leaves another's `get`/`list_page` results unchanged, and no longer lists the deleted one | `test_delete_if_version_leaves_other_keys_visible_in_get_and_list_page` (both backends) |
| US4.6 — GCS-only: non-canonical token raises `PreconditionFailedError` with no client call; `PreconditionFailed`/`NotFound` from `blob.delete()` map to `PreconditionFailedError`; timeout/unavailable map to `BackendUnavailableError`; an unmapped exception propagates | `test_delete_if_version_deletes_with_matching_generation`, `test_delete_if_version_with_non_canonical_token_raises_without_client_call`, `test_delete_if_version_precondition_failed_raises_precondition_failed_error`, `test_delete_if_version_not_found_raises_precondition_failed_error`, `test_delete_if_version_timeout_exceptions_map_to_backend_unavailable_timeout`, `test_delete_if_version_unavailable_exceptions_map_to_backend_unavailable_unavailable`, `test_delete_if_version_unmapped_exception_propagates_unchanged` (`tests/test_storage_gcs_errors.py`) |

## Architecture / ADR changes

- `ARCHITECTURE.md`: marked `delete_file` implemented in the bird's-eye
  view and the `core` module-map bullet (semantics, error ordering, no
  `source`/return value, no metadata parsing, no tombstone); added
  `delete_if_version` to the `Storage` protocol's method list and to the
  `storage` module-map bullet (guarded-only, precondition-failure mapping
  for both backends).
- `docs/adr/0012-delete-file.md` (new): guarded-delete-only protocol
  change; already-absent → `FILE_ABSENT` rather than idempotent success,
  and why; no `source`/no return value; metadata not parsed; the
  fake-gcs-server `ifGenerationMatch`-on-`DELETE` gap and the resulting
  skipped integration test.

## Deviations from spec

- None. The implementation matches `spec.md` and `plan.md` as written; the
  already-absent-file and idempotency question was resolved at the spec
  checkpoint (spec Assumptions, `review-spec.md` "Your call") before
  implementation, so there is no open gap between spec and code.

## Look closely at

- The precondition-failure re-read in `delete_file`: it distinguishes
  "conflict" from "absent" purely by whether the re-read finds an object,
  with no landed-write check like `append_line`'s (there is nothing to
  compare a delete's result against). Confirm that's the right call given
  delete has no payload to match.
- `TestGcsStorage.test_delete_if_version_with_stale_token_raises_and_leaves_object_unchanged`
  is skipped in `tests/integration/test_storage_gcs.py` because
  fake-gcs-server doesn't enforce `ifGenerationMatch` on `DELETE`; the same
  behavior against the real client is covered only by a stub
  (`tests/test_storage_gcs_errors.py`). Worth confirming that coverage is
  an acceptable substitute, not a gap to track separately.
- `GcsStorage.delete_if_version` maps both `PreconditionFailed` and
  `NotFound` to the same `PreconditionFailedError` — confirm that
  collapsing "wrong generation" and "already gone" into one signal at the
  storage layer (leaving `core` to re-read and tell them apart) is still
  the right boundary, consistent with `put_if_version`.

## Follow-ups

- AIE-1040: `system/` read-only enforcement (out of scope here; nothing in
  `core` yet restricts a delete to any area).
- AIE-1044: tool-facing wording for `delete_file` must present
  `FILE_ABSENT` on an already-deleted file as "already gone, done," not as
  an error surfaced to the agent.
- AIE-1045: transport conformance suite needs `delete_file` cases mirroring
  the spec's US1-US3 scenarios.
- If a future fake-gcs-server version starts enforcing `ifGenerationMatch`
  on `DELETE`, remove the skip in `TestGcsStorage` (ADR 0012 notes this).
