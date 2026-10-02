# Implementation Plan: Transport conformance test cases

**Linear issue**: AIE-1045 | **Branch**: `AIE-1045-transport-cases` | **Date**: 2026-10-02 | **Spec**: [spec.md](spec.md)

## Summary

Extend `src/wenchang/testing/transport_conformance.py` with the §10.2
case methods (43, incl. US10.5) and a few private case helpers. Update the
method-name test. Add self-tests per group, a message-drift test, and
the reference run inherits the new cases automatically. No change to
`core` or `transport`. Based on `AIE-1047-transport-harness`; PR targets
that branch until it merges.

## Technical Context

Same module and conventions as AIE-1047. New imports from `wenchang`:
`errors` gains `ReplaceFactMatchError`, `VersionConflictError`,
`RecoverableError`; `core` gains `ListCursor`; `version_token` gains
`VersionToken` (for `_ABSENT_TOKEN`). The token `ast` rule in
`tests/test_testing_package.py` (`find_version_misuse`) is unchanged: it
flags only Names/Attributes ending in `version` used as operands, so
`VersionToken("1")` and the name `_ABSENT_TOKEN` are not flagged, and
`client.<method>(...)` calls are exempt as callers of the token.

**Token rule for the cases**: a token reaches the client only as an
argument to a `client.<method>(...)` call written inside the lambda
passed to `_call` or `expect_error`. No private helper takes a token
parameter; helpers take a zero-arg callable instead.

## Constitution Check

| Principle | Status |
| --------- | ------ |
| I. Tests-first | T1–T5 each test-writer → implementer. The "tests" here are the reference run (which goes red as soon as the method-name test lists a missing case) and the per-group self-tests |
| II. Tests not negotiable | The AIE-1047 method-name test is updated, as its spec anticipated (allow-test-change: US5.3 of AIE-1047 says "AIE-1045 extends this list and updates the test") |
| IV. Strict typing | As AIE-1047 |
| V. Storage only through interface | No storage access |
| VI. Spec fidelity | §10.2 groups covered; corrupt-metadata parity excluded (ADR 0023); US7.3 follows the human's answer (a) |
| VII. Architecture documented | ARCHITECTURE.md `testing` entry; ADR 0023 |
| VIII. Traceability | Test docstrings cite AIE-1045; shipped module cites none |
| IX. Small PR | One module extended, test files extended |

**Decisions to record in ADR 0023:**

1. **One method per assertion, grouped by §10.2 bullet**, each
   self-contained (own writes, own paths), so a failure names one
   behavior. Rejected: a few large scenario methods, which hide which
   assertion failed.
2. **Argument-error parity pins core's exact message text** via module
   constants (one per method where core shares a message across causes:
   `MSG_WRITE_ARGS`, `MSG_REPLACE_ARGS`, `MSG_APPEND_ARGS`; format
   constants for cursors and `get_memory_index`), with a drift test in
   `tests/` triggering every (method, cause) pair on `MemoryStore`.
   Rejected: type-only checks (a remote could reshape the text the agent
   reads; ADR 0019 decision 7 requires the message).
3. **Corrupt-metadata parity (`MetadataFormatError`,
   `UnicodeDecodeError`) is out of the transport suite.** A conforming
   client cannot seed corrupt stored data, so the suite cannot provoke
   them. The storage suite and the tool layer cover them. Rejected: a
   `corrupt_storage` fixture, which only an in-process adopter could
   supply and would make the suite non-uniform.
4. **Index cap arithmetic replays core's rule over client-returned
   entries** (`index_entry_bytes` over entries from `list_prefix` or the
   index, never self-built `FileEntry`s), never hardcoded, so the cases
   hold for any fixture values; US8.3 asserts the exact longest fitting
   prefix and exact `capped`, and skips only when 20 probe files never
   make the replay omit an `INDEX_AREA` entry (not merely the sentinel).
5. **Tokens reach the client only inside `client.<method>(...)` calls in
   the lambda passed to `_call`/`expect_error`**; no helper takes a token
   parameter. `_ABSENT_TOKEN = VersionToken("1")` is a plain constant
   handed to calls on absent paths, where any token must yield
   `FILE_ABSENT`; the token scan needs no exemption.
6. **Recency assertions rely on the clock contract** (strictly
   increasing `last_updated` within a test) and compare only two reads
   from the same client with `<`.
7. **The transport accepts `system/` writes (human decision 2026-10-02,
   option (a) of ADR 0021's open question).** `test_system_area_write_is_
   accepted_at_transport` asserts it. Enforcement is the tool layer's and
   the resolver suite's. ADR 0019's "Update (2026-10-02)" amendment to
   decision 6 (a remote server must not enforce scope at the transport)
   and ADR 0021's record of decision (a) already exist; verify present,
   and ADR 0023 cites the existing amendment. Rejected: (b) running
   enforcement cases through the tool layer (makes this a tool-layer
   suite); (c) leaving it unspecified (weakens "indistinguishable").
8. **`get_memory_index` argument errors: `ValueError` text pinned,
   `TypeError` type only, duplicate scope excluded.** Invalid scope and
   invalid entity_id `ValueError`s carry core's exact text. The
   `TypeError` texts are not pinned: they embed Python type names of
   caller-side values, which a remote client may detect at
   serialization with its own wording, and a type check alone shows the
   call was rejected before any storage effect. Duplicate scope is
   excluded: it cannot be built with a real `Mapping`, and a remote
   serializing the map to JSON would legitimately collapse it. Recorded
   in ADR 0023.

## Public interface

Additions to `transport_conformance.py` (all methods on
`TransportConformance`, signatures take only the fixtures they use):

```python
_ABSENT_TOKEN: Final = VersionToken("1")
PROBE_STEM_3: Final = "conformance-probe-3"
INDEX_AREA: Final = "conformance-index"

# Exact core messages, pinned for parity (drift-tested in tests/).
MSG_WRITE_ARGS: Final = "source must be non-empty"
MSG_REPLACE_ARGS: Final = "old_string and source must be non-empty"
MSG_APPEND_ARGS: Final = "line must be a single fact line and source must be non-empty"
MSG_MALFORMED_CURSOR: Final = "Malformed list cursor: {cursor!r}"
MSG_FOREIGN_CURSOR: Final = "Cursor {cursor!r} was not issued for prefix {prefix!r}"
MSG_INVALID_SCOPE: Final = "invalid scope: {scope!r}"
MSG_INVALID_ENTITY: Final = "invalid entity_id: {entity_id!r}"


def _meta(
    description: str = "d", aliases: tuple[str, ...] = ("x", "y"), *, sources: frozenset[str]
) -> FileMetadata: ...
def _write(
    name: str, label: str, fn: Callable[[], object], /
) -> MemoryFile: ...  # _call + canonical_file
def _read(
    name: str, label: str, fn: Callable[[], object], /
) -> MemoryFile: ...  # _call + canonical_file
def _conflict(
    name: str, label: str, fn: Callable[[], object], path: str, content: str, /
) -> VersionConflictError: ...  # expect_error(VersionConflictError, RECOVERABLE, path=, content=)
```

`_seed` already exists in the module (AIE-1047) and is reused. The
callables passed to `_write`/`_read`/`_conflict` are lambdas containing
the `client.<method>(...)` call, so any token appears only there.

Per-method message use: US5.6 → `MSG_REPLACE_ARGS` (empty
`old_string`); US6.5 → `MSG_APPEND_ARGS` (non-fact and two-line lines);
US10.3 → `MSG_WRITE_ARGS` (`write_file`), `MSG_REPLACE_ARGS`
(`replace_fact`), `MSG_APPEND_ARGS` (`append_line`), all for empty
`source`; US9.4 → the cursor constants; US10.5 → `MSG_INVALID_SCOPE` / `MSG_INVALID_ENTITY` (its `TypeError`
cases are type only; decision 8).

Case method names (exact):

| Group | Methods |
| ----- | ------- |
| US1 | `test_round_trip_unicode_content_and_metadata`, `test_round_trip_markdown_resembling_fact_syntax`, `test_round_trip_content_without_trailing_newline`, `test_round_trip_empty_content`, `test_round_trip_empty_aliases_and_many_sources`, `test_write_replace_round_trips` |
| US2 | `test_failed_replace_leaves_content_and_metadata_together`, `test_delete_removes_content_and_metadata_together`, `test_append_updates_content_and_last_updated_together` |
| US3 | `test_tokens_from_every_operation_are_accepted`, `test_index_entry_tokens_are_accepted` |
| US4 | `test_stale_write_conflicts_with_current_content`, `test_create_on_existing_path_conflicts`, `test_write_with_token_on_absent_path_is_not_found`, `test_stale_delete_conflicts`, `test_delete_absent_is_not_found` |
| US5 | `test_replace_fact_unique_match_succeeds`, `test_replace_fact_zero_matches_rejected`, `test_replace_fact_multiple_matches_rejected`, `test_replace_fact_stale_token_unique_match_reapplies`, `test_replace_fact_stale_token_non_unique_conflicts`, `test_replace_fact_empty_old_string_is_value_error` |
| US6 | `test_concurrent_appends_one_lands_one_conflicts`, `test_retried_append_does_not_duplicate`, `test_append_inserts_separator_when_needed`, `test_append_to_absent_file_is_not_found_and_creates_nothing`, `test_append_non_fact_line_is_value_error` |
| US7 | `test_oversize_append_is_rejected`, `test_oversize_replace_fact_is_rejected`, `test_system_area_write_is_accepted_at_transport` |
| US8 | `test_index_fans_out_over_every_scope`, `test_index_orders_system_first_then_priority_then_recency`, `test_index_byte_cap_degrades_with_capped_prefixes`, `test_index_of_empty_scope_map_is_empty` |
| US9 | `test_list_prefix_paginates_with_stable_cursors`, `test_list_prefix_levels`, `test_list_prefix_invalid_prefix_is_not_found`, `test_list_prefix_malformed_cursor_is_value_error` |
| US10 | `test_invalid_path_is_not_found_for_every_operation`, `test_absent_file_is_not_found_for_every_mutating_read`, `test_empty_source_is_value_error`, `test_error_messages_carry_category_guidance`, `test_get_memory_index_argument_errors_match_core` |

Phrases reused from the harness: `round trip`, `wrong error type`,
`wrong payload`, `wrong message`, `did not raise`, `token not accepted`,
`unexpected error`, `bad field`, `wrong result type`. New phrases:

| Phrase | Where |
| ------ | ----- |
| `content changed` | a case that expected content to be unchanged after a rejected call |
| `wrong content` | read content differs from expected after a successful call |
| `wrong order` | index or page entries not in the expected sequence |
| `wrong capped` | capped prefixes or counts differ |
| `budget exceeded` | included entries' sizes sum over `index_max_bytes` |
| `not later` | `last_updated` did not increase between two reads |
| `duplicated line` / `missing line` | append cases |
| `missing guidance` | `str(exc)` does not end with the category's guidance |

Index-order expectation (US8.2): the case writes, in this order,
`first_scope/system/s1`, `second_scope/system/s2`, then for each scope
in `scope_priority` order followed by unlisted scopes sorted, one
`PROBE_AREA` file. Expected order after `without_sentinel`: `s2, s1`
(newest system first), then one entry per non-system scope in tier
order, where tiers are: listed scopes in `scope_priority` order, then
unlisted scopes as one tier sorted by recency (newest first). The case
computes this from the fixtures rather than hardcoding scope names.

US8.3 budget: write files with 200-byte descriptions under `INDEX_AREA`
in `second_scope` one at a time (at most 20). After each write, size the
`INDEX_AREA` entries (from `list_prefix`, all pages) with
`index_entry_bytes` and the sentinel with `sentinel_entry_bytes`, and
replay the cap; keep writing until the replay predicts that at least one
`INDEX_AREA` entry, not merely the sentinel, is omitted. Skip only if
that never happens within 20 files. Build the expected order from the listed entries and the sentinel entry
(from `list_prefix` of the sentinel area): system tier (empty), then
non-system tiers by `scope_priority` (listed in order, unlisted as one
trailing tier), the sentinel in its tier position and oldest, recency
from write order within tiers. Replay core's loop: include while the
cumulative size ≤ `index_max_bytes`, stop at the first overflow. Assert
the returned paths equal the included paths exactly (`wrong order`) and
their sizes total at most the budget (`budget exceeded`). Expected
`capped` comes from the replay over client-returned entries: omitted
entries grouped by area prefix with counts, sorted by prefix, including
the sentinel's area when the replay predicts it capped. It is compared
to the client's raw `capped` in the order returned, so unsorted or
sentinel-dropped output fails `wrong capped`. `index_max_bytes` is
floored at `MIN_INDEX_BYTES = 1024` to leave room for the probe entries.
Then two budget probes: write `conformance-probe-fit` (newest) sized to
fill the leftover budget exactly, recheck, then resize it to one byte
past and recheck. The exact fit catches a too-small budget; the +1
catches a too-large one. Sizing re-measures the listed entry and retries
up to `_FIT_ATTEMPTS` times, since the version string's length can
change between writes. If the entry cannot be sized exactly within
`_FIT_ATTEMPTS`, or the leftover budget is below a minimal entry, the
probes do not run and the first check stands.

### `tests/test_testing_package.py`

No change: `find_version_misuse` already passes the new cases, given
the token rule above.

### ARCHITECTURE.md

`testing` entry: `TransportConformance` now covers all nine §10.2
groups (43 case methods), the exact-message parity rule and its drift
test, the token rule (tokens only inside `client.<method>(...)` calls in
the lambda), and the corrupt-metadata exclusion.

## Test layout

- `tests/test_transport_conformance_reference.py`: the method-name set
  updated to the full list (allowed change per AIE-1047 US5.3).
- `tests/test_transport_conformance_cases_self.py` (new): one broken
  client per §10.2 group (US11.2), each matching phrase and label,
  each also run against the reference client.
- `tests/test_transport_conformance_messages.py` (new): drift test —
  trigger every (method, cause) pair on a real `MemoryStore` (empty
  `source` on `write_file`, `replace_fact`, `append_line`; empty
  `old_string`; non-fact and two-line `line`; malformed and foreign
  cursor; invalid scope and invalid entity_id on `get_memory_index`) and
  assert `str(exc) == MSG_*` (formatted where needed).

## Tasks mapping

T1 US1–US3; T2 US4–US6; T3 US7, US8, US9; T4 US10 (incl. US10.5) + messages drift test
+ method-name update; T5 docs (verify the ADR 0019 amendment and ADR
0021 decision (a) are present; ADR 0023 cites the existing amendment).

## Complexity Tracking

None.
