# PR Review: AIE-1045 — Transport conformance test cases

## What changed & why

Notion §10.2 lists nine groups of assertions the shared transport suite
must make so the in-process and remote transports can't be told apart.
AIE-1047 built the harness and five baseline cases. This PR adds the full
set of §10.2 cases: 43 methods on `TransportConformance` in
`src/wenchang/testing/transport_conformance.py`, one per assertion and
grouped by §10.2 bullet, plus private case helpers and message constants
copied from core (`MSG_*`). On the test side it adds a broken-client
self-test for each group (`tests/test_transport_conformance_cases_self.py`)
and a drift test that holds the pinned messages equal to core's
(`tests/test_transport_conformance_messages.py`). It also updates the
method-name test to the full list of 48 cases and makes the pytester
fixture-error test compute its counts from the case signatures instead
of hardcoding them. Nothing in `core`, `transport`, or the harness
helpers changes. The branch is based on `AIE-1047-transport-harness`, and
the PR targets that branch until it merges.

## Acceptance criteria → tests

Line numbers are as of this draft. `mod` =
`src/wenchang/testing/transport_conformance.py` (where each case is
defined), `ref` = `tests/test_transport_conformance_reference.py`, `cs` =
`tests/test_transport_conformance_cases_self.py`, `msg` =
`tests/test_transport_conformance_messages.py`, `pkg` =
`tests/test_testing_package.py`. Every case also runs in the reference run
ref:111 `TestInProcessClient` (inherited), and in a parametrized check
that runs it against both the reference client and the forwarding
wrapper: cs:195 `test_reference_client_passes_case` (US1–US3), cs:425
`..._conflict_replace_append_case` (US4–US6), cs:544
`..._enforcement_index_listing_case` (US7–US9), and cs:654
`..._error_parity_case` (US10). Each broken-client self-test first calls
`_reference_passes` (cs:171).

| Acceptance criterion (Given/When/Then) | Case (mod) | Self-test / drift test |
| --------------------------------------- | ---------- | ---------------------- |
| US1.1 Unicode content, description, aliases round-trip | mod:995 `test_round_trip_unicode_content_and_metadata` | cs:218 `test_unicode_round_trip_dropped_alias_fails` (`round trip.*aliases`) |
| US1.2 Fact-like markdown, blank line, code fence byte-for-byte | mod:1015 `test_round_trip_markdown_resembling_fact_syntax` | cs:195 |
| US1.3 No trailing newline / empty content unchanged | mod:1027 `test_round_trip_content_without_trailing_newline`; mod:1040 `test_round_trip_empty_content` | cs:195 |
| US1.4 Empty aliases, many sources; `source` unioned | mod:1051 `test_round_trip_empty_aliases_and_many_sources` | cs:195 |
| US1.5 Replace stores new fields; sources accumulate | mod:1064 `test_write_replace_round_trips` | cs:195 |
| US2.1 Stale replace → conflict with content B; read shows B **and** dB | mod:1099 `test_failed_replace_leaves_content_and_metadata_together` | cs:265 `test_failed_replace_new_content_old_description_fails` |
| US2.2 Delete → `FILE_ABSENT` and not listed | mod:1140 `test_delete_removes_content_and_metadata_together` | cs:195 |
| US2.3 Append moves content and `last_updated` (`<`, same client) together; source stamped | mod:1177 `test_append_updates_content_and_last_updated_together` | cs:195 |
| US3.1 Tokens from write, append, replace_fact, read, list each accepted | mod:1219 `test_tokens_from_every_operation_are_accepted` | cs:370 `test_rejected_token_from_operation_fails[write_file, read_file, append_line, replace_fact, list_prefix]` |
| US3.2 Index entry token accepted by `delete_file` | mod:1280 `test_index_entry_tokens_are_accepted` | cs:385 `test_rejected_index_entry_token_fails` |
| US4.1 Stale write → conflict with current content; carried token accepted | mod:1326 `test_stale_write_conflicts_with_current_content` | cs:453 `test_stale_write_success_fails` (`did not raise`) |
| US4.2 Create on existing → conflict with observed content; unchanged | mod:1362 `test_create_on_existing_path_conflicts` | cs:425 |
| US4.3 Token write on absent path → `FILE_ABSENT` | mod:1384 `test_write_with_token_on_absent_path_is_not_found` | cs:425 |
| US4.4 Stale delete conflicts, file kept; carried token deletes | mod:1406 `test_stale_delete_conflicts` | cs:425 |
| US4.5 Delete absent → `FILE_ABSENT` | mod:1434 `test_delete_absent_is_not_found` | cs:425 |
| US5.1 Unique match replaced, others kept | mod:1455 `test_replace_fact_unique_match_succeeds` | cs:425 |
| US5.2 Zero matches → `ReplaceFactMatchError(match_count=0)`, content | mod:1474 `test_replace_fact_zero_matches_rejected` | cs:485 `test_replace_fact_wrong_match_count_fails` (`wrong payload.*match_count`) |
| US5.3 Two matches → `match_count=2` | mod:1498 `test_replace_fact_multiple_matches_rejected` | cs:425 |
| US5.4 Stale token, still-unique match → re-applied | mod:1522 `test_replace_fact_stale_token_unique_match_reapplies` | cs:425 |
| US5.5 Stale token, zero matches now → conflict | mod:1546 `test_replace_fact_stale_token_non_unique_conflicts` | cs:425 |
| US5.6 Empty `old_string` → `ValueError(MSG_REPLACE_ARGS)` | mod:1573 `test_replace_fact_empty_old_string_is_value_error` | cs:425; msg:48 `test_replace_fact_empty_old_string_message_matches` |
| US6.1 Two appends at one token: one lands, one conflicts, retry lands once, in order | mod:1597 `test_concurrent_appends_one_lands_one_conflicts` | cs:509 `test_concurrent_appends_both_landing_fails` |
| US6.2 Retried landed append conflicts, no duplicate | mod:1634 `test_retried_append_does_not_duplicate` | cs:425 |
| US6.3 Separator only when needed; trailing `"\n"` always | mod:1659 `test_append_inserts_separator_when_needed` | cs:425 |
| US6.4 Append to absent → `FILE_ABSENT`, nothing created | mod:1687 `test_append_to_absent_file_is_not_found_and_creates_nothing` | cs:425 |
| US6.5 Non-fact or two-line line → `ValueError(MSG_APPEND_ARGS)` | mod:1708 `test_append_non_fact_line_is_value_error` | cs:425; msg:69 `test_append_line_non_fact_line_message_matches`; msg:76 `test_append_line_two_line_line_message_matches` |
| US7.1 Oversize append → `OversizeWriteError` with exact UTF-8 size (multi-byte) | mod:1733 `test_oversize_append_is_rejected` | cs:570 `test_oversize_mutation_accepted_fails[append]` |
| US7.2 Oversize replace_fact → exact post-replacement size | mod:1766 `test_oversize_replace_fact_is_rejected` | cs:570 `test_oversize_mutation_accepted_fails[replace_fact]` |
| US7.3 `system/` write **accepted** at the transport (decision (a)) | mod:1802 `test_system_area_write_is_accepted_at_transport` | cs:598 `test_system_area_write_rejected_fails` (`unexpected error`) |
| US8.1 Index fans out over every scope; `capped == ()` | mod:1827 `test_index_fans_out_over_every_scope` | cs:544 |
| US8.2 `system/` first, then priority tiers, recency within | mod:1857 `test_index_orders_system_first_then_priority_then_recency` | cs:544 |
| US8.3 Cap: exact longest fitting prefix, within budget, exact `capped` | mod:1907 `test_index_byte_cap_degrades_with_capped_prefixes` | cs:613 `test_index_omitting_entries_without_capped_fails` (`wrong capped`) |
| US8.4 Empty map → `((), ())` | mod:1984 `test_index_of_empty_scope_map_is_empty` | cs:544 |
| US9.1 Pagination: full page + cursor, then rest + `None`; stable; ascending | mod:1997 `test_list_prefix_paginates_with_stable_cursors` | cs:633 `test_full_first_page_without_cursor_fails` |
| US9.2 Entity and scope levels are supersets of the area level | mod:2036 `test_list_prefix_levels` | cs:544 |
| US9.3 `"nope"` and `""` → `INVALID_PATH` | mod:2062 `test_list_prefix_invalid_prefix_is_not_found` | cs:544 |
| US9.4 Malformed / foreign cursor → exact `ValueError` | mod:2081 `test_list_prefix_malformed_cursor_is_value_error` | cs:544; msg:89 `test_list_prefix_malformed_cursor_message_matches`; msg:100 `test_list_prefix_foreign_cursor_message_matches` |
| US10.1 Malformed path → `INVALID_PATH` for every path operation; no storage effect | mod:2124 `test_invalid_path_is_not_found_for_every_operation` | cs:654 |
| US10.2 Absent path → `FILE_ABSENT` for read, append, replace_fact, delete | mod:2170 `test_absent_file_is_not_found_for_every_mutating_read` | cs:674 `test_absent_read_raising_key_error_fails` (`wrong error type`, names `KeyError`) |
| US10.3 Empty `source` → per-method message; real token; unchanged | mod:2203 `test_empty_source_is_value_error` | cs:654; msg:115 `test_write_file_empty_source_message_matches`; msg:55 `test_replace_fact_empty_source_message_matches`; msg:62 `test_append_line_empty_source_message_matches` |
| US10.4 `str(exc)` equals a locally built core error and ends with guidance | mod:2237 `test_error_messages_carry_category_guidance` | cs:654 |
| US10.5 `get_memory_index`: `TypeError` (type only); invalid scope / entity → exact `ValueError` | mod:2345 `test_get_memory_index_argument_errors_match_core` | cs:654; msg:126 `test_get_memory_index_invalid_scope_message_matches`; msg:136 `test_get_memory_index_invalid_entity_message_matches` |
| US11.1 Method-name set complete; reference run has no skips | all of the above | ref:164 `test_suite_public_methods_are_exactly_the_listed_cases`; ref:111 `TestInProcessClient`; `tests/test_transport_conformance_self.py`:2240 `test_subclass_missing_fixture_reports_fixture_error` (counts now derived from case signatures) |
| US11.2 One broken client per group, phrase + label matched, reference passes | — | cs:218, 265, 370, 385, 453, 485, 509, 570, 598, 613, 633, 674 (each via `_case_fails`, cs:177) |
| US11.3 Token scan unchanged and passing; no Linear IDs; no marks | — | pkg:444 `test_transport_conformance_never_operates_on_version_tokens`; pkg:439 `test_transport_conformance_cites_no_linear_ids`; pkg:432 `test_transport_conformance_applies_no_pytest_marks`; pkg:385 `test_transport_conformance_imports_only_allowed_modules` |

`make check` is the gate.

## Architecture / ADR changes

- New [ADR 0023](../../docs/adr/0023-transport-conformance-cases.md):
  plan decisions 1–8 with rejected alternatives: one method per
  assertion; exact-message parity with a drift test; the corrupt-metadata
  exclusion; replaying the index cap; the token rule with no scanner
  exemption; recency via the clock contract; transport accepts `system/`
  (decision (a)); `get_memory_index` `TypeError`s checked by type only,
  and the duplicate-scope exclusion. It also records the adversarial
  review.
- Verified present, not edited: ADR 0019's "Update (2026-10-02)" amendment
  to decision 6 (a remote must not enforce scope at the transport), and
  ADR 0021's "Decision (human, 2026-10-02): option (a)". ADR 0023 cites
  both.
- `ARCHITECTURE.md`:
  - `testing` entry: the 43 cases across the nine §10.2 groups; the
    cap replay; the `MSG_*` constants and their drift test; `TypeError`s
    checked by type only; the duplicate-scope and corrupt-metadata
    exclusions; `_ABSENT_TOKEN` and the token rule; the acceptance case
    for `system/`; how the repo checks the suite; `version_token` added
    to the imports.
  - `transport` entry: the conformance suite is complete.
  - "transport mirrors core" invariant: notes that the suite asserts the
    acceptance, and links ADR 0023.
- `docs/product/glossary.md`: "Transport conformance suite" lists the
  nine groups, exact argument-error wording, and the `system/` acceptance
  rule.
- `spec.md` / `plan.md`: the US8.3 stop rule now matches the code. It
  stops once the replay omits an `INDEX_AREA` entry, not merely the
  sentinel. US10.3 notes that the case creates `P` and uses its real
  token.

## Deviations from spec

- **None from Notion beyond those already recorded.** The enforcement
  reading (option (a)) was decided by the human and is recorded in ADR
  0021 and ADR 0019. This PR adds the acceptance case for it.
- **Exclusions, recorded in ADR 0023:** corrupt-metadata parity
  (`MetadataFormatError`, `UnicodeDecodeError`) can't be reached through
  a conforming client; corrupt stored metadata is covered by core's
  `read_file`/`list_prefix` tests and the storage conformance suite
  (`tests/storage_conformance.py`), and the tool layer passes
  `MetadataFormatError` through. Duplicate scopes in `scope_map` can't be built
  with a real `Mapping`. `get_memory_index`'s `TypeError` texts are not
  pinned.
- **Small differences between spec text and code:**
  - US11.2's US5 broken client reports `match_count=2` for zero matches
    (spec updated; a count of 1 is invalid for `ReplaceFactMatchError`).
  - US11.2's US4 client "returns success on a stale write" by
    re-applying the write at the current version.
  - The US2.1 self-test (cs:265) accepts either phrase (regex
    `round trip|wrong content`); the case itself reports `wrong content`.

## Adversarial review findings

Two rounds of adversarial spec review ran before implementation:

1. **Append newline.** The spec misstated the separator rule. Core
   always appends `"\n"` after the line and inserts one before it only
   when the content is non-empty and lacks a trailing newline. US6.3 and
   US7.1's size formula now follow core.
2. **Token-scan misread.** The spec misread what `find_version_misuse`
   flags. It only flags names and attributes ending in `version` used as
   operands, so `_ABSENT_TOKEN = VersionToken("1")` needs no exemption.
   Passing `exc.version` to a local error constructor *would* be flagged,
   so US10.4 builds its local errors with `_ABSENT_TOKEN`.
3. **Per-method messages.** Core shares one message across causes within
   a method, but each method has its own message. The spec now pins one
   constant per method (`MSG_WRITE_ARGS` / `MSG_REPLACE_ARGS` /
   `MSG_APPEND_ARGS`), and the drift test covers every (method, cause)
   pair.
4. **Edge case in the cap arithmetic.** Stopping once listed bytes plus
   the sentinel passed the budget could leave the sentinel as the only
   capped entry. `capped` is then empty after `without_sentinel`, and the
   case checks nothing about the probe files.

Tightened later, during implementation: US8.3's stop rule moved from a
size threshold to the replay's own prediction (point 4). US10.3 creates
the file and hands back its real token, since core validates arguments
before it checks that the file exists. The spec now says both.

## Look closely at

- **US8.3 replay** (mod:1907, `_replay_cap` mod:780). The expected order
  is rebuilt from scope tiers and write order, with the sentinel oldest
  in its tier. The case asserts that the returned paths *including* the
  sentinel equal the replayed included prefix, and compares `capped` with
  the sentinel's area removed on both sides. Check that the tier key
  (`_tier`, mod:770) matches core's handling of unlisted scopes.
- **Exact-message pins** (mod:88–94). These are copied from core by
  hand, and only the drift test (msg) keeps them honest. A remote client
  is now bound to core's exact wording for every argument `ValueError`.
- **Local error construction in US10.4** (mod:2237). Expected messages
  come from `str(NotFoundError(...))`, `str(VersionConflictError(p,
  observed, _ABSENT_TOKEN))`, `str(OversizeWriteError(...))`, and
  `str(ReplaceFactMatchError(p, current, _ABSENT_TOKEN, 0))`. This is
  correct only while those messages leave out the version. If core ever
  puts the version in the message, this case breaks for every client.
- **Sentinel handling.** Every list and index case passes results
  through `without_sentinel`. US8.3 sizes the sentinel with
  `sentinel_entry_bytes` and assumes it was written first, so it is the
  oldest entry. If a case forgets the filter, that is a case bug, not an
  adopter bug.
- **`_ABSENT_TOKEN`** is handed to calls on absent or malformed paths
  only. Any such call that ever reached an existing file would test the
  wrong thing.

## Follow-ups

- **AIE-1044** (tool layer, ADR 0022) uses these transport semantics: the
  transport accepts every well-formed write, including `system/`, and
  enforcement happens only at the tool layer.
- **AIE-1059** ("End-to-end integration test against reference adopter
  config") and **AIE-1060** ("Host-mounting smoke test"), both in
  milestone 5, "Integration and conformance close-out".
- If core's argument-error wording changes, update the `MSG_*` constants
  in the same PR. The drift test will fail until that is done.
