# PR Review: AIE-1292 — Cap the number of files per entity

## What changed & why

Nothing bounded how many files an entity could hold, so a looping agent could create thousands. `MemoryStore` gains `max_files_per_entity` (default 500, `None` disables). A `write_file` create outside `system/` counts the entity's well-formed non-`system/` keys via `Storage.list_page` and, at the cap, raises the new recoverable `FileQuotaExceededError` (or `VersionConflictError` if the path exists). Replaces, appends, `replace_fact`, deletes, and reads never consult the cap. The tool layer only gains one `write_file` docstring sentence.

## Acceptance criteria → tests

| Acceptance criterion (Given/When/Then) | Test(s) |
| --------------------------------------- | ------- |
| US1.1–1.3 create past cap rejected, cap inclusive, default 500 | `tests/test_core_file_cap.py`: `test_create_past_cap_is_rejected_and_nothing_is_stored`, `test_create_up_to_cap_is_allowed`, `test_default_max_files_per_entity_is_500`, `test_default_cap_rejects_the_501st_file` |
| US2.1–2.3 replace, append, replace_fact at cap succeed | `test_replace_with_version_at_cap_succeeds`, `test_append_line_at_cap_succeeds`, `test_replace_fact_at_cap_succeeds` |
| US2.4–2.6 existing path → conflict; vanished → quota; corrupt data propagates | `test_create_existing_path_at_cap_is_version_conflict`, `test_create_vanished_path_at_cap_is_quota_error`, `test_create_existing_path_with_corrupt_metadata_at_cap_propagates`, `test_create_existing_path_with_non_utf8_content_at_cap_propagates` |
| US3.1 delete frees a slot | `test_delete_frees_a_slot`; `tests/integration/test_gcs_file_cap.py::test_file_cap_on_gcs` |
| US4.1–4.6 per entity, `system/` and malformed keys excluded | `test_other_entity_in_same_scope_is_unaffected`, `test_same_entity_id_in_other_scope_is_unaffected`, `test_system_files_do_not_count_at_cap`, `test_system_files_do_not_count_below_cap`, `test_system_create_at_cap_is_not_checked`, `test_malformed_keys_do_not_count` |
| US5.1–5.2 exact messages, recoverable | `tests/test_errors.py`: `test_file_quota_exceeded_error_message_is_exact_literal`, `..._unparseable_path_uses_fallback_literal`, `..._is_recoverable`, `..._exposes_path_and_limit` |
| US5.3–5.5 tool render, reference seeds, role check first | `tests/test_tools_end_to_end.py`: `test_file_quota_error_renders_location_and_limit`, `test_file_quota_over_reference_seeds`, `test_role_check_precedes_file_quota` |
| US5.6 MCP `isError` with limit | `tests/test_mcp_server.py::test_create_at_file_cap_is_rendered_recoverable` |
| US5.7 docstring sentence | `tests/test_tools_descriptions.py::test_write_file_description_states_file_cap_beside_byte_ceiling` |
| US6.1–6.3 `None` disables; bad cap/limit rejected | `test_none_cap_allows_more_than_500_files`, `test_max_files_per_entity_is_configurable`, `test_non_positive_max_files_per_entity_is_rejected`, `test_file_quota_exceeded_error_rejects_non_positive_limit` |
| FR-001/002 edges (check order, `list_page` not `list_prefix`, paging) | `test_index_max_bytes_check_precedes_max_files_check`, `test_bool_cap_is_accepted_as_one`, `test_oversize_create_at_cap_is_oversize_error`, `test_corrupt_metadata_on_another_file_does_not_block_create`, `test_count_ignores_list_prefix_override`, `test_count_uses_storage_list_page_under_entity_prefix`, `test_small_page_size_with_leading_system_keys_*`, `test_lowered_cap_blocks_creates_but_keeps_files` |
| US7.1 limit recorded | ADR 0039, ARCHITECTURE.md, glossary (this PR) |

`make check` green (5391 passed, 18 skipped); `make test-integration` green (41 passed, 1 skipped).

## Architecture / ADR changes

- New [ADR 0039](../../docs/adr/0039-file-count-cap-per-entity.md).
- ARCHITECTURE.md: `errors` and `core` module entries, a Key invariants bullet beside the byte ceiling, the error taxonomy's recoverable list, and the `prompts` division-of-labor note.
- `docs/product/glossary.md`: new "File cap (`max_files_per_entity`)" entry.

## Deviations from spec

- None.

## Look closely at

- `core.write_file`: the cap check sits after the oversize check and before the put; at the cap, an existing path raises `VersionConflictError` after decoding and `metadata_from_map`, matching the below-cap conflict path.
- `_at_file_cap` paging: page size `max(limit - count, list_page_size)`, exit on a short page; counted keys exclude `system/` and malformed keys.
- Soft cap: count and put are not atomic. Every non-`system/` create now calls `list_page`; `tests/test_core_write_file.py`'s `_StubStorage.list_page` returns `[]` for this reason.
- `FileQuotaExceededError` message wording (it is what the agent reads) and that it never names the entity ID.

## Follow-ups

- Transport conformance gap: the error is under the parity contract but no case exercises it (no cap fixture; a required fixture would break adopters' suites).
