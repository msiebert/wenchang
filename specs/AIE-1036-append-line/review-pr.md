# PR Review: AIE-1036 — append_line

## What changed & why

Adds `MemoryStore.append_line(path, line, expected_version, *, source) ->
MemoryFile`, the fifth core API function: it appends one fact line to the
end of an existing file's content, only if the file is still at
`expected_version`. Every mutating call in `core` is now version-guarded.
The original Notion design was an unguarded append (appends "commute"); it
was changed at the spec checkpoint on 2026-09-29 so a retried append that
already landed fails its guard instead of duplicating the line, and Notion
and the Linear issue were updated to match (ADR 0011).

## Acceptance criteria → tests

| Acceptance criterion (Given/When/Then) | Test(s) |
| --------------------------------------- | ------- |
| US1.1 — append at `V` to content ending in `\n` produces concatenated content, new version, `read_file` agrees | `test_append_line_appends_to_trailing_newline_content_and_read_file_agrees` |
| US1.2 — content with no trailing newline gets a separator inserted | `test_append_line_inserts_separator_when_content_lacks_trailing_newline` |
| US1.3 — empty content becomes exactly `line + "\n"` | `test_append_line_on_empty_content_is_exactly_the_line` |
| US1.4 — headings/blank lines preserved byte for byte, new line follows | `test_append_line_preserves_non_fact_lines_and_blank_lines` |
| US1.5 — `sources` unioned, `last_updated` from clock, `description`/`aliases` unchanged | `test_append_line_stamps_sources_union_and_clock_leaving_rest_unchanged` |
| US1.6 — same line appended at `V` then `V2` appears twice (deliberate repeats allowed) | `test_append_line_same_line_appended_twice_appears_twice` |
| US1.7 — unicode / fact-like markdown round-trips byte for byte | `test_append_line_unicode_and_fact_like_markdown_round_trips_exactly` |
| US2.1 — stale token raises `VersionConflictError(current_content, current_version)`, file unchanged, no re-apply | `test_append_line_stale_token_raises_version_conflict_with_current_content` |
| US2.2 — identical retry with the now-stale version conflicts; content has the line exactly once | `test_append_line_identical_retry_at_stale_version_conflicts_line_appears_once` |
| US2.3 — two callers on the same version: first lands, second conflicts with first's line, retry with returned version lands, both lines once | `test_append_line_two_callers_same_version_second_conflicts_then_retry_succeeds` |
| US2.4 — a write landing between read and conditional write raises `VersionConflictError` with the post-race content/version, no second write attempted | `test_append_line_race_before_put_raises_conflict_and_does_not_retry_write` |
| US2.5 — own write lands, then `PreconditionFailedError` (backend-level retry of a 412): re-read finds it matches, returns success, no second append | `test_append_line_own_write_lands_then_precondition_fails_returns_success` |
| US2.5b (implementation detail, not in spec's numbered list) — precondition failure whose re-read finds the object deleted raises `NotFoundError(FILE_ABSENT)` | `test_append_line_deleted_mid_retry_raises_file_absent` |
| US3.1 — malformed path raises `NotFoundError(INVALID_PATH)`, no storage call | `test_append_line_malformed_path_raises_invalid_path_without_storage` (parametrized) |
| US3.2 — missing file raises `NotFoundError(FILE_ABSENT)`, nothing created | `test_append_line_no_file_raises_file_absent_and_creates_nothing` |
| US3.3 — `line` not exactly one fact line raises `ValueError`, no storage call | `test_append_line_malformed_line_raises_value_error_without_storage` (parametrized) |
| US3.4 — empty `source` raises `ValueError`, no storage call | `test_append_line_empty_source_raises_value_error_without_storage` |
| US3.5 — result over `max_file_bytes` raises `OversizeWriteError(size, limit)`, file unchanged; exactly at the limit succeeds | `test_append_line_over_byte_ceiling_raises_oversize_and_writes_nothing`, `test_append_line_at_exact_byte_ceiling_succeeds` |
| US3.6 — stale token and oversize line together raise `VersionConflictError` (version checked first) | `test_append_line_stale_token_and_oversize_line_raises_version_conflict_first` |
| US3.7 — `BackendUnavailableError` / `MetadataFormatError` propagate unchanged | `test_append_line_propagates_backend_unavailable_from_get`, `test_append_line_propagates_backend_unavailable_from_put_if_version`, `test_append_line_corrupt_metadata_propagates` |

## Architecture / ADR changes

- `ARCHITECTURE.md`: added `append_line` to the bird's-eye view's list of
  implemented `core` operations and to the `core` module-map bullet
  (algorithm, error ordering, metadata stamping); updated the "Optimistic
  concurrency via generation" invariant to state every mutating call is now
  guarded, and to contrast `replace_fact`'s re-apply with `append_line`'s
  no-re-apply; removed the now-obsolete "`append_line` carries no version
  guard" invariant bullet.
- `docs/adr/0011-append-line-version-guard.md` (new): records the deviation
  from Notion's original unguarded design, the no-re-apply decision, the
  landed-write check after a `PreconditionFailedError`, missing-file
  behavior, single-fact-line validation, and the rejected alternatives
  (unguarded, optional token, internal CAS retry loop).

## Deviations from spec

- The implemented `append_line` requires `expected_version` and does not
  re-apply on a stale token, deviating from the original Notion design
  (unguarded, commuting appends). This deviation is the subject of this PR
  and is justified in ADR 0011; Notion and the Linear issue were updated to
  match before implementation, so there is no remaining gap between spec
  and code.

## Look closely at

- The precondition-failure branch in `append_line`: confirm the "landed
  write" check compares both stored bytes and stored metadata to what was
  written (not just one), since a false positive there would silently skip
  a real conflict.
- Error-check ordering: version is checked before size (US3.6), and path/
  line/source validation happens before any storage call (US3.1, US3.3,
  US3.4) — worth confirming these orderings match `replace_fact`'s existing
  pattern for consistency.
- The `_DeletableStorage`/`_DeleteThenPreconditionFailsStorage` test doubles
  cover a case (delete landing mid-retry) not explicitly enumerated in the
  spec's numbered acceptance scenarios; confirm the behavior they assert
  (`NotFoundError(FILE_ABSENT)`) is the intended contract, not just
  incidental.

## Follow-ups

- AIE-1040: `system/` read-only enforcement (out of scope here; `core`
  itself doesn't yet restrict writes to any area).
- AIE-1044: tool-facing wording for `append_line`'s conflict must present a
  concurrent-append conflict as routine, not a failure.
- AIE-1045: transport conformance suite needs a "concurrent appends: one
  lands, the other conflicts and lands on retry" case, replacing the old
  "append commutativity" case.
