# PR Review: AIE-1109 — write_file required `source`, sources accumulate

## What changed & why

`MemoryStore.write_file` now requires a keyword-only, non-empty `source`,
matching `replace_fact` and `append_line`. Stored `sources` is now a union
that only ever grows — create stores `metadata.sources | {source}`; replace
reads the current object first and stores
`stored.sources | metadata.sources | {source}` — so a replacing caller can
no longer erase another surface's recorded writes by omitting them.
Replace's read-before-put also means corrupt stored metadata now propagates
`MetadataFormatError` instead of being silently overwritten, closing the
parity gap ADR 0009 deferred to this issue.

## Acceptance criteria → tests

| Acceptance criterion (Given/When/Then) | Test(s) |
| --------------------------------------- | ------- |
| US1.1: create with `sources=frozenset()`, `source="chat"` → `{"chat"}` | `test_write_file_create_stamps_source_into_empty_sources` |
| US1.2: create with `sources={"cli"}`, `source="chat"` → `{"cli", "chat"}` | `test_write_file_create_unions_caller_sources_with_source` |
| US1.3: create with `sources={"chat"}`, `source="chat"` → `{"chat"}`, no duplication | `test_write_file_create_source_already_in_metadata_sources_not_duplicated` |
| US2.1: replace, stored `{"cli"}`, caller `sources=frozenset()`, `source="chat"` → `{"cli", "chat"}` | `test_write_file_replace_carries_forward_stored_source_caller_did_not_supply` |
| US2.2: replace, stored `{"cli"}`, caller `sources={"api"}`, `source="chat"` → `{"cli", "api", "chat"}` | `test_write_file_replace_unions_stored_caller_and_source` |
| US2.3: replace, stored `{"cli", "api"}`, caller omits `"api"` → `{"cli", "api"}` (cannot remove) | `test_write_file_replace_cannot_remove_a_stored_source` |
| US2.4: replace carries `description`/`aliases`/content from caller, `last_updated` from clock, matches `read_file` | `test_write_file_replace_description_aliases_content_are_callers_last_updated_is_clock` |
| US3.1: empty `source` (create/replace) → `ValueError`, no storage call | `test_write_file_empty_source_on_create_raises_value_error_without_storage`, `test_write_file_empty_source_on_replace_raises_value_error_without_storage` |
| US3.2: `source` omitted or positional → `TypeError` | `test_write_file_missing_source_raises_type_error`, `test_write_file_positional_source_raises_type_error` |
| US3.3: malformed path checked before empty `source` | `test_write_file_malformed_path_checked_before_empty_source` |
| US3.4: stale `expected_version` → `VersionConflictError` with current content/version | `test_write_file_replace_with_stale_version_raises_conflict_with_current_version` |
| US3.5: replace, no object at path → `NotFoundError(FILE_ABSENT)`, nothing created | `test_write_file_replace_with_no_object_raises_file_absent_and_creates_nothing` |
| US3.6: race between read and conditional write → `VersionConflictError` with post-race content, other writer untouched | `test_write_file_race_before_put_raises_conflict_with_post_race_content` |
| US3.7: stored metadata corrupt at matching version → `MetadataFormatError` propagates, file unchanged | `test_write_file_replace_with_corrupt_stored_metadata_at_matching_version_propagates` |
| US3.8: existing behavior (oversize, create-conflict, backend-error propagation) unchanged apart from new argument | pre-existing oversize/conflict/backend-error tests (e.g. `test_write_file_over_default_byte_ceiling_raises_oversize_and_writes_nothing`, `test_write_file_with_none_expected_conflicts_when_file_exists`, `test_write_file_propagates_backend_unavailable_error_from_put_unchanged`), updated only to pass `source=` |

Four pre-existing tests had their `sources` assertions changed from the
caller-supplied set to the union (required by the issue):
`test_write_file_creates_file_and_read_file_agrees`,
`test_write_file_sequential_writes_never_mix_content_and_metadata`,
`test_write_file_round_trips_metadata_with_special_characters`, and
`test_write_file_stamps_last_updated_from_clock_overriding_caller_value` —
each now asserts `meta.sources | {"chat"}` (or the applicable union) rather
than `meta.sources` alone.

## Architecture / ADR changes

- `ARCHITECTURE.md`: `write_file` entry rewritten — signature, `source`
  validation order, create/replace union semantics, replace's
  read-before-put, and corrupt-metadata propagation.
- New [ADR 0013](../../docs/adr/0013-write-file-source.md): required
  `source`, union semantics (and why caller-supplied `sources` is unioned
  in rather than ignored or rejected), replace-reads-before-put, and
  corrupt-metadata propagation. [ADR 0009](../../docs/adr/0009-replace-fact-semantics.md)
  gets a one-line "Update (AIE-1109)" pointer closing the parity gap it
  deferred.

## Deviations from spec

- None from this issue's spec. This issue itself is the deviation ADR 0009
  flagged against the original Notion `write_file` signature (`sources`
  "stamped as-is"); ADR 0013 records the resolution.

## Look closely at

- The replace path's read-before-put in `core.py`: on a version mismatch
  at the read, stored metadata is still parsed (result discarded) before
  raising `VersionConflictError`, so corrupt metadata surfaces as
  `MetadataFormatError` whatever the version. This mirrors the existing
  precondition-failure path, which also parses before raising a conflict.
  The stale-version + corrupt-metadata combination has no dedicated test.
- No automatic re-apply on a race at the conditional put (unlike
  `replace_fact`); confirm that's intentional here (it is, per FR-005) and
  not an inconsistency worth flagging to callers.

## Follow-ups

- None identified. Agent-facing tool wording (AIE-1044) and transport
  conformance cases (AIE-1045) remain explicitly out of scope per spec.md.
