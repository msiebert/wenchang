# PR Review: AIE-1034 — replace_fact

## What changed & why

Adds `MemoryStore.replace_fact(path, old_string, new_string,
expected_version, *, source) -> MemoryFile` to `src/wenchang/core.py`, so a
caller can change one fact line without resending the rest of the file. The
anchor must match exactly once (overlaps counted); a stale
`expected_version` re-applies the edit against fresh content when the
anchor survives, and escalates to `VersionConflictError` only when it
doesn't. No storage or error-module changes — built entirely on
`Storage.get`/`put_if_version` and existing error types.

## Acceptance criteria → tests

| Acceptance criterion (Given/When/Then) | Test(s) |
| --------------------------------------- | ------- |
| Unique match replaced; new version; read_file agrees | `test_replace_fact_replaces_unique_match_and_read_file_agrees` |
| Match at start / end / across line break | `test_replace_fact_matches_at_start_end_or_across_line_break` |
| Empty `new_string` deletes the span | `test_replace_fact_with_empty_new_string_deletes_the_span` |
| Unicode / CRLF matched exactly, no normalization | `test_replace_fact_handles_unicode_and_crlf_without_normalization` |
| Zero matches → `ReplaceFactMatchError(count=0)`, unchanged | `test_replace_fact_zero_matches_raises_with_current_content_and_version` |
| k≥2 non-overlapping matches → `count=k`, unchanged | `test_replace_fact_multiple_non_overlapping_matches_raises_with_count` |
| Overlapping matches counted (`"aa"` in `"aaa"` → 2), rejected | `test_replace_fact_overlapping_matches_counted_and_rejected` |
| Empty `old_string` → `ValueError`, no storage call | `test_replace_fact_empty_old_string_raises_value_error_without_storage` |
| Metadata carried over; `sources` gains `source`; `last_updated` = clock | `test_replace_fact_stamps_sources_and_last_updated_preserving_rest` |
| `source` already in `sources` leaves it unchanged | `test_replace_fact_source_already_present_leaves_sources_unchanged` |
| Empty `source` → `ValueError`, no storage call | `test_replace_fact_empty_source_raises_value_error_without_storage` |
| Result over `max_file_bytes` → `OversizeWriteError`, nothing written | `test_replace_fact_over_byte_ceiling_raises_oversize_and_writes_nothing` |
| Result exactly at `max_file_bytes` succeeds | `test_replace_fact_at_exact_byte_ceiling_succeeds` |
| Malformed path → `NotFoundError(INVALID_PATH)`, no storage call | `test_replace_fact_malformed_path_raises_invalid_path_without_storage` |
| Absent file → `NotFoundError(FILE_ABSENT)` | `test_replace_fact_no_file_raises_file_absent` |
| Naive clock → `ValueError`, nothing written | `test_replace_fact_naive_clock_raises_value_error_and_writes_nothing` |
| `BackendUnavailableError` propagates from `get` / `put_if_version` | `test_replace_fact_propagates_backend_unavailable_from_get`, `test_replace_fact_propagates_backend_unavailable_from_put_if_version` |
| Corrupt metadata / non-UTF-8 bytes propagate unchanged | `test_replace_fact_corrupt_metadata_propagates`, `test_replace_fact_non_utf8_bytes_propagates` |
| `old == new` unique match is a normal write | `test_replace_fact_old_equals_new_is_a_normal_write` |
| SC-001: rejected calls leave file/version unchanged | `test_replace_fact_rejected_calls_leave_stored_file_and_version_unchanged` |
| Stale version, anchor survives another writer's unrelated change → succeeds, both changes present (SC-002) | `test_replace_fact_succeeds_when_another_writer_changed_a_different_line` |
| Stale version, other writer removed the anchor → `VersionConflictError` with their content/version | `test_replace_fact_raises_version_conflict_when_other_writer_removed_anchor` |
| Stale version, other writer added a second anchor occurrence → `VersionConflictError` | `test_replace_fact_raises_version_conflict_when_other_writer_added_second_match` |
| Race between `get` and `put_if_version`, anchor survives → re-applies once, succeeds | `test_replace_fact_reapplies_after_a_race_that_preserves_the_anchor` |
| Race removes the anchor → `VersionConflictError` with the racing write's state | `test_replace_fact_raises_version_conflict_when_a_race_removes_the_anchor` |
| Every put races → 3 attempts, then `VersionConflictError` with last-read state | `test_replace_fact_exhausts_three_attempts_when_every_put_races` |
| Retry of a call whose first response was lost sees its own prior write → `VersionConflictError` | `test_replace_fact_retry_with_the_same_version_sees_its_own_prior_write` |
| File deleted between a failed put and the retry's re-read → `NotFoundError(FILE_ABSENT)` | `test_replace_fact_raises_file_absent_when_file_deleted_mid_retry` |
| Unminted `expected_version` treated as stale, not a parse error (unique match succeeds; zero matches → `VersionConflictError`) | `test_replace_fact_treats_an_unminted_expected_version_as_stale_and_succeeds`, `test_replace_fact_unminted_expected_version_with_zero_matches_raises_version_conflict` |

## Architecture / ADR changes

- `ARCHITECTURE.md` — `core` module entry updated: `replace_fact` moved
  from *(planned)* to implemented, with its unique-anchor, stale-reapply,
  retry-budget, and metadata-stamping semantics described; the bird's-eye
  summary and ADR cross-references updated.
- `docs/adr/0009-replace-fact-semantics.md` (new) — records the "genuine
  overlap" test, the split between `ReplaceFactMatchError` (current
  version) and `VersionConflictError` (stale version), guarding the put on
  the version just read, overlapping match counting, empty-`old_string` /
  empty-`source` → `ValueError`, the 3-attempt budget, metadata carryover,
  and the required keyword-only `source` deviation from the Notion
  signature.

## Deviations from spec

- `replace_fact` takes a required keyword-only `source: str` beyond the
  Notion signature `(path, old_string, new_string, expected_version)`.
  Notion's spec has no way to record which calling surface wrote via
  `replace_fact` in `sources`, since the call has no metadata argument at
  all; without this parameter that guarantee would silently not hold for
  this write path. Raised and approved by the human at spec review; see
  ADR 0009. `write_file`'s own `sources`-stamping parity is tracked
  separately (AIE-1109); `append_line` (AIE-1036) is expected to follow the
  same pattern.

## Look closely at

- The overlap test (`_count_occurrences`, current content vs. current
  content only — never the caller's original base) and whether the
  `ReplaceFactMatchError` vs. `VersionConflictError` split matches
  intuition for a caller integrating against this.
- Retry non-idempotence when `new_string` contains `old_string` (accepted
  risk, documented in ADR 0009 and the spec's Assumptions) — confirm no
  caller in this codebase relies on retry safety in that shape yet.
- The put in the retry loop is guarded on the version just re-read, not
  the caller's original `expected_version` — confirm this matches the
  "re-apply against fresh content" reading of the spec, not a stricter one.

## Follow-ups

- AIE-1109: give `write_file` the same required-`source` stamping
  parameter `replace_fact` now has.
- AIE-1036 (`append_line`): follow the required keyword-only `source`
  pattern established here.
- AIE-1040 / AIE-1042: `system/` read-only and role-gated scope enforcement
  remain unenforced for `replace_fact`, as for `write_file`.
