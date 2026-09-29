# PR Review: AIE-1035 — list_prefix

## What changed & why

Adds `MemoryStore.list_prefix(prefix, cursor=None) -> ListPage(entries,
next_cursor)` to `src/wenchang/core.py`: metadata-only, paginated listing of
files under a prefix, needed so a caller can enumerate what's stored without
reading every file's body. It's built on a new `Storage.list_page(prefix,
start_after, limit)` primitive implemented on both `InMemoryStorage` and
`GcsStorage`, plus `paths.is_valid_prefix` for prefix validation. `core`
mints its own opaque, base64-encoded `ListCursor` rather than exposing a raw
key or GCS page token.

## Acceptance criteria → tests

| Acceptance criterion (Given/When/Then) | Test(s) |
| --------------------------------------- | ------- |
| US1.1: Entries returned in order, no next cursor when everything fits | `test_list_prefix_returns_entries_in_order_with_no_next_cursor` |
| US1.2: A shorter prefix recurses into all areas beneath it | `test_list_prefix_recurses_into_all_areas_under_a_shorter_prefix` |
| US1.3: Prefix match is segment-aligned, not substring | `test_list_prefix_is_segment_aligned_not_substring_match` |
| US1.4: No matching files returns an empty page | `test_list_prefix_with_no_files_returns_empty_page` |
| US1.5: Listed entries agree with `read_file` | `test_list_prefix_entries_agree_with_read_file` |
| US1.6: Unicode names ordered by ascending code point | `test_list_prefix_orders_unicode_names_by_ascending_code_point` |
| US2.1: Repeated cursors page through the full result set | `test_list_prefix_paginates_across_repeated_cursors` |
| US2.2: Exact multiple of page size has no trailing empty page | `test_list_prefix_exact_multiple_of_page_size_has_no_trailing_empty_page` |
| US2.3: Write/delete between pages is reflected, not snapshotted | `test_list_prefix_reflects_concurrent_write_and_delete_between_pages` |
| US2.4: Unknown or foreign-prefix cursor rejected | `test_list_prefix_rejects_cursor_strings_it_never_issued`, `test_list_prefix_rejects_cursor_issued_for_a_different_prefix` |
| US2.5: Page size is construction config, validated positive | `test_memory_store_rejects_non_positive_list_page_size`, `test_memory_store_default_list_page_size_is_100_and_named_constant` |
| US3.1: Malformed prefix rejected without consulting storage | `test_list_prefix_rejects_malformed_prefix_without_consulting_storage`, prefix tables in `tests/test_paths.py` |
| US3.2: Malformed keys skipped but valid files still all reached | `test_list_prefix_omits_malformed_keys_but_still_reaches_every_valid_file`, `test_list_prefix_page_of_only_malformed_keys_can_be_short_with_a_cursor` |
| US3.3: Corrupt metadata on a well-formed key fails the page | `test_list_prefix_propagates_metadata_format_error_for_corrupt_metadata` |
| US3.4: Backend unavailability propagates from `list_page` | `test_list_prefix_propagates_backend_unavailable_from_list_page` |
| US4.1–4.4: `list_page` ordering, `start_after`, `limit`, prefix match conformance across both backends | `test_list_page_*` in `tests/storage_conformance.py` |
| GCS error mapping and no unnecessary blob download during listing | `tests/test_storage_gcs_errors.py` |

## Architecture / ADR changes

- `ARCHITECTURE.md` — `core` module entry updated: `list_prefix` moved from
  *(planned)* to implemented, with cursor, pagination, and prefix-validation
  semantics described; `Storage` protocol entry documents `list_page`.
- `docs/adr/0010-list-prefix-pagination.md` (new) — records the new
  `Storage.list_page` primitive, the opaque `ListCursor` design (vs. a raw
  key or GCS page token), the 1–3-segment valid-prefix rule, page size as
  construction config rather than a per-call argument, the
  fetch-`limit+1`-and-trim trick for `next_cursor`, the malformed-key-skip
  vs. corrupt-metadata-fails split, and the no-snapshot listing semantics.

## Deviations from spec

- None from the Notion `list_prefix(prefix, cursor)` signature itself. The
  design decisions above (cursor opacity, prefix validity rules, page-size
  placement, corrupt-metadata handling) have no direct precedent in the
  Notion spec and were made and approved at the spec checkpoint on
  2026-09-29; see ADR 0010 for each one's rationale and rejected
  alternatives.

## Look closely at

- `core.py`: `list_prefix`'s cursor encode/decode (`_encode_cursor`,
  `_decode_cursor`) and the `limit + 1`/trim logic that decides
  `next_cursor` — confirm the "no trailing empty page" behavior matches
  intuition.
- `gcs.py`: `list_page`'s `start_offset` handling is inclusive at the GCS
  API level, so the implementation explicitly drops a returned blob whose
  name equals `start_after`; also note the iteration over `blob_iter`
  happens inside the same `try` as the error mapping, so a mid-iteration
  backend error is still mapped correctly.
- `tests/storage_conformance.py`'s new `list_page` cases — these run against
  both `InMemoryStorage` and `GcsStorage` (via fake-gcs-server) and are the
  main guarantee the two backends agree on ordering, `start_after`
  exclusivity, and `limit`.
- Existing `Storage` protocol consumers (`test_core_read_file.py`,
  `test_core_write_file.py`, `test_core_replace_fact.py`) only gained a
  `list_page` stub method to satisfy the widened protocol — no behavior
  changes in those files.

## Follow-ups

- AIE-1044: tool-layer mapping of the plain `ValueError` `list_prefix`
  raises for a bad/foreign-prefix cursor into a tool-facing error, and
  `get_memory_index`'s consumption of `list_page`.
- AIE-1040: `system/` read-only and role-gated scope enforcement remains
  unenforced for `list_prefix`, as for the other `core` methods — it lists
  `system/` areas like any other for now.

## Verification

- `make check`: green — 458 unit tests, pyright strict 0 errors.
- `make test-integration`: 34 passed against fake-gcs-server, including
  `start_offset` support in the real GCS client.
- spec-reviewer: 0 FAIL.
