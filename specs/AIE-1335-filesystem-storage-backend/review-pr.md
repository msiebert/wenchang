# PR Review: AIE-1335 — Local-filesystem storage backend

## What changed & why

Adds `FilesystemStorage(root)` (`src/wenchang/storage/filesystem.py`), a third
`Storage` implementation that keeps a body file and a JSON metadata/version
sidecar per object under a local directory, plus `InvalidStorageKeyError`. It
lets wenchang run and be tested with no GCS or emulator and lets people read
memory files on disk. It is a test and local-dev backend held to the shared
conformance suites, not a production provider. No change to the `Storage`
protocol, `MemoryStore`, transport, or tools.

## Acceptance criteria → tests

Tests are in `tests/test_storage_filesystem.py` unless noted.

| Acceptance criterion (Given/When/Then) | Test(s) |
| --------------------------------------- | ------- |
| 1. Conformance and purge/export suites pass on `tmp_path`, no emulator | `TestFilesystemStorage`, `TestFilesystemEntityPurgeExport` |
| 2. `MemoryStore` on the backend behaves like the fake | `tests/test_storage_filesystem_memory_store.py`: `test_create_then_read_round_trips_content_and_metadata`, `test_update_with_current_version_succeeds_and_stale_version_conflicts`, `test_create_over_existing_file_conflicts`, `test_delete_with_current_version_removes_the_file`, `test_memory_index_lists_the_files`, `test_export_then_purge_removes_the_entity_and_spares_neighbours`, `test_state_persists_to_a_fresh_store_on_the_same_root` |
| 3. Body file is the exact bytes; sidecar is JSON with version and metadata | `test_put_writes_body_and_sidecar_in_mirrored_directories`, `test_worked_example_layout`, `test_sidecar_is_ascii_sorted_json_and_round_trips_lone_surrogates`, `test_no_temp_files_remain_after_writes_and_deletes`, `test_delete_removes_files_and_empty_parent_directories`, `test_hand_edited_body_is_visible_and_keeps_its_version` |
| 4. `a`, `a/b`, `a/b/c`, `a/` coexist | `test_a_and_a_slash_b_coexist_in_any_write_order`, `test_deleting_a_leaves_children_intact` |
| 5. Awkward keys round-trip, stay case-distinct, never leave `root` | `test_awkward_key_round_trips_and_lists_under_its_exact_key`, `test_awkward_keys_coexist_distinctly_and_stay_inside_root`, `test_list_page_with_traversal_prefix_returns_nothing`, `test_case_variants_get_distinct_names_on_disk` |
| 6. Empty key, lone surrogate, over-long segment raise `InvalidStorageKeyError`; `list_page` does not raise | `test_invalid_key_raises_on_every_keyed_method_and_writes_nothing`, `test_invalid_storage_key_error_is_a_value_error`, `test_segment_of_exactly_200_encoded_bytes_is_accepted`, `test_list_page_with_unencodable_prefix_returns_nothing`, `test_list_page_with_unusual_start_after_does_not_raise` |
| 7. Tokens never repeat across delete and re-put | `test_tokens_have_documented_shape`, `test_tokens_never_repeat_across_put_delete_reput` |
| 8. Fresh instance on same root sees same state and tokens; CAS works | `test_fresh_instance_sees_same_state_and_tokens` |
| 9. Two instances, 16 threads, one winner per race | `test_two_instances_race_create_update_delete_with_one_winner` |
| 10. Four processes, one winner per key | `test_processes_race_create_with_exactly_one_winner_per_key` |
| 11. Orphan body and temp files are invisible; create overwrites orphan | `test_orphan_body_and_temp_files_are_invisible`, `test_create_overwrites_orphan_body`, `test_sidecar_less_body_after_interrupted_delete_is_absent` |
| 12. `list_page` is code-point ordered and pages without gaps or repeats | `test_list_page_returns_code_point_order_not_walk_order`, `test_list_page_pages_through_every_key_once`, `test_list_page_matches_sorted_filter_for_any_prefix_and_start_after`, `test_list_page_metadata_and_version_match_get` |
| 13. `list_page` works with unreadable bodies | `test_list_page_never_opens_bodies` |
| 14. Missing key returns `None` | `test_get_missing_key_returns_none_in_every_shape` |
| 15. `OSError` and bad sidecars map to `BackendUnavailableError` | `test_put_into_read_only_root_raises_backend_unavailable`, `test_invalid_json_sidecar_raises_backend_unavailable_on_get_and_list`, `test_wrong_shape_sidecar_raises_backend_unavailable`, `test_invalid_sidecar_does_not_silently_pass_conditional_writes`, `test_body_missing_while_sidecar_exists_raises_backend_unavailable`, `test_unreadable_sidecar_raises_backend_unavailable`, `test_precondition_and_key_errors_are_not_mapped` |
| 16. Missing `root` and parents are created; existing root untouched | `test_missing_root_and_parents_are_created`, `test_construction_on_existing_root_changes_nothing`, `test_root_that_is_a_file_raises_backend_unavailable` |
| 17. Type-checks as `Storage` with no cast | `test_filesystem_storage_satisfies_storage_protocol` and `make typecheck` |
| 18. `make check` passes | `make check` |
| 19. Docs name the third backend; ADR amends 0003 | `ARCHITECTURE.md`, ADR 0047, ADR 0003 note (below) |

## Architecture / ADR changes

- New [ADR 0047](../../docs/adr/0047-filesystem-storage-backend.md): a
  filesystem backend for tests and local dev, held to the conformance suite.
  It amends ADR 0003 only to the extent of a dev/test backend, and records the
  encoding, token, commit-order, and locking choices with rejected alternatives
  and accepted limitations.
- [ADR 0003](../../docs/adr/0003-storage-interface-with-in-memory-fake-and-gcs-emulator.md)
  gains an amendment note pointing to ADR 0047.
- `ARCHITECTURE.md`: storage section (three implementations, layout, locking,
  limits), Mermaid diagram (filesystem node), storage-root and version-token
  invariants. `docs/product/glossary.md`: version token and storage root
  entries mention the filesystem backend.

## Deviations from spec

- None.

## Look closely at

- Key encoding and the `%obj` / `%meta` suffix argument (no encoded segment can
  collide with a suffix), and the strict-decode rule in `list_page`.
- Lock scope and ordering (thread lock then `flock`; shared for reads) and that
  every public method releases in a `finally`.
- Commit order: sidecar replace as the commit point, sidecar-first delete, and
  the accepted torn-overwrite window.
- Error mapping: only `OSError` and malformed sidecars become
  `BackendUnavailableError`; `PreconditionFailedError` and
  `InvalidStorageKeyError` pass through.
- Chmod-based tests skip as root (`Allow-test-changes` marker in `spec.md`);
  the cross-process test uses `spawn` and may be slow on CI.

## Follow-ups

- No backend-selection config or CLI; the host constructs the storage.
- Stale `.tmp-*` files are not garbage-collected.
- Windows and network-filesystem support are out of scope.
