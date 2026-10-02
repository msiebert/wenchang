# PR Review: AIE-1045 — Transport conformance test cases

## What changed & why

Notion §10.2 lists nine groups of assertions the shared transport suite
must make so the in-process and remote transports can't be told apart.
AIE-1047 built the harness and five baseline cases. This PR adds the full
set of §10.2 cases: 43 methods on `TransportConformance` in
`src/wenchang/testing/transport_conformance.py`, one per assertion and
grouped by §10.2 bullet. It also adds private case helpers, message
constants copied from core (`MSG_*`), and a new fixture floor
`MIN_INDEX_BYTES = 1024`. On the test side it adds broken-client
self-tests (`tests/test_transport_conformance_cases_self.py`, 88 tests)
and a drift test that keeps the pinned messages equal to core's
(`tests/test_transport_conformance_messages.py`). It also updates the
method-name test to the full list of 48 cases, and makes the pytester
fixture-error test compute its counts from the case signatures. Nothing
in `core`, `transport`, or the harness helpers changes. The branch is
based on `AIE-1047-transport-harness`, and the PR targets that branch
until it merges.

## Acceptance criteria → tests

The rows are the 11 acceptance criteria in `review-spec.md`. Line numbers
were checked with grep against the latest commit (`2704e05`). Key:

- `mod` = `src/wenchang/testing/transport_conformance.py` (where each case
  is defined)
- `cs` = `tests/test_transport_conformance_cases_self.py`
- `msg` = `tests/test_transport_conformance_messages.py`
- `ref` = `tests/test_transport_conformance_reference.py`
- `self` = `tests/test_transport_conformance_self.py`
- `pkg` = `tests/test_testing_package.py`

Every case also runs in two other places. The first is the reference run,
ref:111 `TestInProcessClient` (inherited). The second is a parametrized
check that runs it against both the reference client and the forwarding
wrapper: cs:222 `test_reference_client_passes_case` (US1–US3), cs:452
`..._conflict_replace_append_case` (US4–US6), cs:571
`..._enforcement_index_listing_case` (US7–US9), and cs:681
`..._error_parity_case` (US10). Each broken-client self-test first calls
`_reference_passes` (cs:198), which now also fails if the case skips
(`_run_unskipped`). It then calls `_case_fails` (cs:204), which matches
the phrase and the probe-path label.

| # | Acceptance criterion | Cases (mod) | Self-tests / drift tests |
| - | -------------------- | ----------- | ------------------------ |
| 1 | Round trip (US1): unicode, fact-like markdown, no trailing newline, empty content, many sources, replace survive byte-for-byte; sources accumulate | mod:1058 `test_round_trip_unicode_content_and_metadata`; mod:1078 `test_round_trip_markdown_resembling_fact_syntax`; mod:1091 `test_round_trip_content_without_trailing_newline`; mod:1104 `test_round_trip_empty_content`; mod:1115 `test_round_trip_empty_aliases_and_many_sources`; mod:1128 `test_write_replace_round_trips` | cs:245 `test_unicode_round_trip_dropped_alias_fails`; cs:222 |
| 2 | Atomicity (US2): rejected stale replace leaves content and metadata together; delete removes both; append moves content and `last_updated` together | mod:1163 `test_failed_replace_leaves_content_and_metadata_together`; mod:1204 `test_delete_removes_content_and_metadata_together`; mod:1241 `test_append_updates_content_and_last_updated_together` | cs:292 `test_failed_replace_new_content_old_description_fails`; cs:1078 `test_deleted_file_still_listed_fails`; cs:1015 `test_append_not_advancing_last_updated_fails`; cs:1044 `test_append_not_stamping_source_fails` |
| 3 | Token opacity (US3): tokens from every operation and from index entries are accepted when handed back | mod:1283 `test_tokens_from_every_operation_are_accepted`; mod:1344 `test_index_entry_tokens_are_accepted` | cs:397 `test_rejected_token_from_operation_fails[write_file, read_file, append_line, replace_fact, list_prefix]`; cs:412 `test_rejected_index_entry_token_fails` |
| 4 | Conflicts (US4): stale write/delete conflict carrying current content, and a retry with the carried token succeeds; create-on-existing conflicts; token on an absent path → `FILE_ABSENT` | mod:1390 `test_stale_write_conflicts_with_current_content`; mod:1426 `test_create_on_existing_path_conflicts`; mod:1448 `test_write_with_token_on_absent_path_is_not_found`; mod:1470 `test_stale_delete_conflicts`; mod:1498 `test_delete_absent_is_not_found` | cs:480 `test_stale_write_success_fails`; cs:753 `test_conflict_carrying_stale_content_fails`; cs:824 `test_stale_write_retry_without_effect_fails`; cs:783 `test_create_on_existing_succeeding_fails` |
| 5 | Replace-fact (US5): unique match succeeds; 0 and 2 matches carry count and content; stale unique re-applies; stale non-unique conflicts; empty anchor → exact `ValueError` | mod:1519 `test_replace_fact_unique_match_succeeds`; mod:1538 `test_replace_fact_zero_matches_rejected`; mod:1562 `test_replace_fact_multiple_matches_rejected`; mod:1586 `test_replace_fact_stale_token_unique_match_reapplies`; mod:1611 `test_replace_fact_stale_token_non_unique_conflicts`; mod:1638 `test_replace_fact_empty_old_string_is_value_error` | cs:512 `test_replace_fact_wrong_match_count_fails`; cs:856 `test_replace_fact_rejection_after_mutating_fails`; msg:48 `test_replace_fact_empty_old_string_message_matches`; msg:55 `test_replace_fact_empty_source_message_matches` |
| 6 | Append (US6): of two concurrent appends one lands and one conflicts, and the retry lands once, in order; a retried landed append conflicts; separator rule; absent → nothing created; non-fact or two-line → exact `MSG_APPEND_ARGS` | mod:1662 `test_concurrent_appends_one_lands_one_conflicts`; mod:1699 `test_retried_append_does_not_duplicate`; mod:1724 `test_append_inserts_separator_when_needed`; mod:1752 `test_append_to_absent_file_is_not_found_and_creates_nothing`; mod:1773 `test_append_non_fact_line_is_value_error` | cs:536 `test_concurrent_appends_both_landing_fails`; cs:955 `test_concurrent_appends_bad_retry_fails[duplicates, drops, misorders]`; cs:790 `test_retried_landed_append_succeeding_fails`; cs:984 `test_append_without_separator_fails`; msg:62, 69, 76 `test_append_line_*_message_matches` |
| 7 | Enforcement (US7): oversize append/replace rejected with the exact UTF-8 size (multi-byte); a `system/` write is **accepted** at the transport (decision (a)) | mod:1798 `test_oversize_append_is_rejected`; mod:1831 `test_oversize_replace_fact_is_rejected`; mod:1867 `test_system_area_write_is_accepted_at_transport` | cs:597 `test_oversize_mutation_accepted_fails[append, replace_fact]`; cs:881 `test_oversize_append_applied_before_rejection_fails`; cs:625 `test_system_area_write_rejected_fails`; cs:1100 `test_system_area_write_reading_back_different_fails` |
| 8 | Index (US8): fan-out; system first, then priority, then recency; cap replayed: exact returned entries, within budget, exact raw `capped`; empty map → `((), ())` | mod:1892 `test_index_fans_out_over_every_scope`; mod:1922 `test_index_orders_system_first_then_priority_then_recency`; mod:1976 `test_index_byte_cap_degrades_with_capped_prefixes` (`_replay_cap` mod:785, `_check_cap` mod:834); mod:2058 `test_index_of_empty_scope_map_is_empty` | cs:1191 `test_index_spuriously_capped_fails`; cs:1131 `test_index_system_entries_after_others_fails`; cs:640 `test_index_omitting_entries_without_capped_fails`; cs:1155 `test_index_over_budget_fails`; cs:1175 `test_index_dropping_fitting_entry_fails`; cs:1198 `test_skipped_case_counts_as_failure` |
| 9 | Listing (US9): pagination at `list_page_size` with stable cursors, strictly ascending, no duplicates across pages; entity/scope levels; invalid prefix → `INVALID_PATH`; malformed/foreign cursor → exact `ValueError` | mod:2071 `test_list_prefix_paginates_with_stable_cursors`; mod:2112 `test_list_prefix_levels`; mod:2138 `test_list_prefix_invalid_prefix_is_not_found`; mod:2157 `test_list_prefix_malformed_cursor_is_value_error` | cs:660 `test_full_first_page_without_cursor_fails`; cs:1286 `test_list_pagination_misbehavior_fails[descending, unstable cursor, cursor on last page, repeated boundary entry]`; msg:89 `test_list_prefix_malformed_cursor_message_matches`; msg:100 `test_list_prefix_foreign_cursor_message_matches` |
| 10 | Parity (US10): invalid path and absent file for every operation; empty source per method; full `str(exc)` matches core and ends with guidance; `get_memory_index` exact `ValueError`, `TypeError` by type | mod:2200 `test_invalid_path_is_not_found_for_every_operation`; mod:2246 `test_absent_file_is_not_found_for_every_mutating_read`; mod:2279 `test_empty_source_is_value_error`; mod:2313 `test_error_messages_carry_category_guidance`; mod:2421 `test_get_memory_index_argument_errors_match_core` | cs:1393 `test_invalid_path_write_stored_fails`; cs:701 `test_absent_read_raising_key_error_fails`; cs:1362 `test_absent_delete_raising_key_error_fails`; cs:1343 `test_empty_source_wrong_message_fails`; cs:1316 `test_reshaped_error_message_fails`; msg:115 `test_write_file_empty_source_message_matches`; msg:126 `test_get_memory_index_invalid_scope_message_matches`; msg:136 `test_get_memory_index_invalid_entity_message_matches` |
| 11 | Integrity (US11): method-name set complete; reference run has no skips; broken client per group; token scan passes unchanged; no Linear IDs; no marks | — | ref:164 `test_suite_public_methods_are_exactly_the_listed_cases`; ref:111 `TestInProcessClient`; cs:1204 `test_reference_subclass_runs_every_case_unskipped`; self:2240 `test_subclass_missing_fixture_reports_fixture_error` (counts derived from case signatures); pkg:444 `test_transport_conformance_never_operates_on_version_tokens`; pkg:439 `test_transport_conformance_cites_no_linear_ids`; pkg:432 `test_transport_conformance_applies_no_pytest_marks`; pkg:385 `test_transport_conformance_imports_only_allowed_modules` |

`make check` passes: 2179 passed, 6 skipped, 41 deselected. The 6 skips
are the existing resolver-conformance skips and were there before this
PR. The transport suite skips nothing (cs:1204).

## Architecture / ADR changes

- New [ADR 0023](../../docs/adr/0023-transport-conformance-cases.md):
  plan decisions 1–8 and the alternatives rejected for each:
  - one method per assertion;
  - exact message parity, with a drift test;
  - the corrupt-metadata exclusion;
  - replaying the index cap;
  - the token rule, with no scanner exemption;
  - recency via the clock contract;
  - the transport accepts `system/` writes (decision (a));
  - `get_memory_index` `TypeError`s checked by type only, and the
    duplicate-scope exclusion.

  It also records the adversarial spec review.
- The human's decision (a) of 2026-10-02 is that the transport accepts
  `system/` writes. `system/` read-only and role restriction are enforced
  only in the tool layer. It is already recorded in ADR 0021 ("Decision
  (human, 2026-10-02): option (a)") and in ADR 0019's "Update
  (2026-10-02)" amendment to decision 6. ADR 0023 cites both, and
  mod:1867 is the case that asserts it.
- `ARCHITECTURE.md`:
  - `testing` entry: the 43 cases across the nine §10.2 groups, the cap
    replay, the `MSG_*` constants and their drift test, `TypeError`s
    checked by type only, the duplicate-scope and corrupt-metadata
    exclusions, `_ABSENT_TOKEN` and the token rule, the acceptance case
    for `system/`, and how the repo checks the suite.
  - `transport` entry: the conformance suite is complete.
  - "transport mirrors core" invariant: the suite asserts the acceptance,
    with a link to ADR 0023.
- `docs/product/glossary.md`: "Transport conformance suite" lists the
  nine groups, the exact argument-error wording, and the `system/`
  acceptance rule.

## Deviations from spec

- **None from Notion beyond those already recorded.** The enforcement
  reading (option (a)) was decided by the human and is recorded in ADR
  0021 and ADR 0019. This PR adds the acceptance case.
- **Exclusions, recorded in ADR 0023:**
  - Corrupt-metadata parity (`MetadataFormatError`,
    `UnicodeDecodeError`) can't be reached through a conforming client.
    Core's `read_file`/`list_prefix` tests and the storage conformance
    suite cover it.
  - Duplicate scopes in `scope_map` can't be built with a real `Mapping`.
  - `get_memory_index`'s `TypeError` texts are not pinned.
- **Fixture contract change:** `index_max_bytes` must be at least
  `MIN_INDEX_BYTES` (1024), to leave room for the US8.3 probe entries.
  This is recorded in ADR 0023 decision 9, ARCHITECTURE.md, and an
  "Update (2026-10-02)" note in ADR 0021. US8.3 compares the client's raw
  `capped`, including the sentinel's area, with the replay, and adds the
  exact-fit / +1 budget probes. spec.md, plan.md, and ADR 0023 decision 4
  describe this.
- **Smaller differences between spec text and code:**
  - US11.2's US5 broken client reports `match_count=2` for zero matches,
    because a count of 1 is invalid for `ReplaceFactMatchError`.
  - US11.2's US4 client "returns success on a stale write" by re-applying
    the write at the current version.

## Review findings

**Adversarial spec review** (two rounds, before implementation):

- The append separator rule was corrected to match core.
- A misreading of the token scan was fixed: `_ABSENT_TOKEN` needs no
  exemption, and US10.4 builds its local errors with it.
- Message constants are now one per method (`MSG_WRITE_ARGS` /
  `MSG_REPLACE_ARGS` / `MSG_APPEND_ARGS`).
- The cap stop rule now waits until an `INDEX_AREA` entry, not just the
  sentinel, is predicted capped.

**Adversarial code review** (after implementation). Each finding below
was fixed in `src/wenchang/testing/transport_conformance.py`:

1. **US9.1 accepted duplicate entries across pages (bug).** A client
   that repeated an entry across pages passed. Pagination now requires
   strictly ascending paths. A repeat fails `wrong order: duplicate entry
   across pages` (mod:2106), and the strict check is at mod:2109. Killed
   by `test_list_pagination_misbehavior_fails[_RepeatsBoundaryEntry]`
   (cs:1286).
2. **US8.3 `capped` comparison and budget edges.** `_check_cap` (mod:834)
   compares the raw `capped` with the sorted expectation, including the
   sentinel's area. The case requires `index_max_bytes >=
   MIN_INDEX_BYTES = 1024` (mod:82, mod:1989). After the main check it
   writes `conformance-probe-fit` twice:
   - sized to fill the remaining budget exactly, which must be included;
   - then one byte larger, which must be capped.

   Each probe runs `_check_cap` again (mod:2019–2056). This catches a
   client whose budget comparison is off by a few bytes.
3. **US5.4 content stays under 64 bytes,** so the case passes at
   `MIN_FILE_BYTES`.
4. **US1 unsorted-alias cases are now actually unsorted** (for example
   `("日本", "ñ")` at mod:1074), so a client that sorts aliases fails.
5. **The whitespace round-trip now covers CRLF, trailing spaces, and a
   fenced block** (mod:1088).
6. **`wrong order` messages now end with "check the clock contract"**
   (mod:863), pointing adopters to the likely cause.
7. **The `index_max_bytes` fixture docstring** states the 1024-byte floor.

**Coverage (mutation) review:** 30 surviving mutants were reviewed. 26
were real gaps, and the self-tests added to `cs` in the latest commit
(cs:722–1400, including the cases from the code review above) now kill
all 26. The `cs` file has 88 tests, all passing. The other 4 were
equivalent or unreachable, so no test can kill them, and none was added. `_reference_passes`
now also fails a case that skips, so a fixture change can't hide a case
by making it skip.

## Look closely at

- **US8.3 replay and fit probe** (mod:1976, `_replay_cap` mod:785,
  `_check_cap` mod:834):
  - The expected order is rebuilt from scope tiers and write order, with
    the sentinel oldest in its tier. Check that `_tier` (mod:775) matches
    core's handling of unlisted scopes.
  - `fit_to` re-measures the entry each time, because the version
    string's length can change. If it can't hit the target size within
    `_FIT_ATTEMPTS`, the case **returns without the fit checks** rather
    than failing or skipping. Decide whether that silent early return is
    acceptable.
- **`MIN_INDEX_BYTES = 1024`** is a new requirement on adopters' fixtures.
  The reference uses 4096. A smaller value is a fixture error, not a
  skip.
- **Exact-message pins** (mod:92–98). These are copied from core by hand,
  and only the drift test (`msg`) keeps them in sync. A remote client is
  bound to core's exact wording for every argument `ValueError`.
- **Local error construction in US10.4** (mod:2313). Expected messages
  come from locally built core errors that carry `_ABSENT_TOKEN`. This is
  correct only while core's messages leave out the version.
- **Sentinel handling.** Every list and index case passes results
  through `without_sentinel`, except US8.3's `capped`, which is now
  compared raw by design.

## Follow-ups

- Bring spec.md US8.3, plan.md:195, and ADR 0023 decision 4 in line with
  the code: raw `capped`, the `MIN_INDEX_BYTES` floor, and the exact-fit
  / +1 probe. The code is already correct, so only the docs change.
- **AIE-1044** (tool layer, ADR 0022) uses these transport semantics: the
  transport accepts every well-formed write, including `system/`, and
  enforcement happens only at the tool layer.
- **AIE-1059** ("End-to-end integration test against reference adopter
  config") and **AIE-1060** ("Host-mounting smoke test"), both in
  milestone 5.
- If core's argument-error wording changes, update the `MSG_*` constants
  in the same PR. The drift test will fail until that is done.
