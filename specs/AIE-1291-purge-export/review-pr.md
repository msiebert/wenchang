# PR Review: AIE-1291 — Purge and export all memory for an entity

## What changed & why

GDPR and project/org deletion need to remove or hand over everything under
`{scope}/{entity_id}/`. `MemoryStore` gains two operator-only methods in
`src/wenchang/core.py`: `purge` (guarded deletes, repeated passes, one
index-cache invalidation) and `export` (raw `ExportedObject`s), plus
`PurgeIncompleteError` and `PURGE_MAX_PASSES = 5`. They are built only from
existing `Storage` methods, with no storage, transport, tools, or MCP change.

## Acceptance criteria → tests

| Acceptance criterion | Test(s) |
| -------------------- | ------- |
| US1.1–1.9 purge empties the prefix, spares neighbours, is idempotent, validates args, paginates, allows re-create | `tests/test_core_purge.py`: `test_purge_deletes_everything_under_prefix`, `_leaves_no_visible_files`, `_leaves_neighbours_unchanged`, `_of_empty_entity_returns_zero`, `_twice_second_returns_zero`, `_rejects_non_str`, `_rejects_invalid_segments`, `_paginates_seven_objects`, `test_create_after_purge_gets_new_version` |
| US2.1–2.3 concurrent writes/deletes handled on later passes | `test_write_before_cursor_is_deleted_on_next_pass`, `test_changed_object_is_deleted_at_new_version_on_next_pass`, `test_object_deleted_by_another_writer_is_not_counted` |
| US2.4–2.4g `max_passes`, `PurgeIncompleteError`, no entity ID in message | `test_relentless_writer_raises_purge_incomplete`, `test_max_passes_bounds_restarts_and_names_passed_value`, `test_max_passes_not_positive_raises_value_error`, `test_max_passes_wrong_type_raises_type_error`, `test_type_errors_precede_value_errors`, `test_single_pass_succeeds_without_writer`, `test_single_pass_misses_write_behind_cursor`, `test_purge_incomplete_message_omits_entity_id`, `test_purge_incomplete_still_invalidates_index` |
| US2.5–2.6 backend error / interrupt still invalidate | `test_backend_failure_mid_purge_invalidates_and_propagates`, `test_keyboard_interrupt_mid_purge_invalidates` |
| US3.1–3.6 index cache | `test_purge_drops_entity_from_cached_index_only`, `test_purge_tombstones_cached_listing`, `test_purge_invalidates_once_after_last_storage_call`, `test_cache_failure_after_successful_purge_propagates`, `test_cache_failure_after_failed_purge_is_logged`, `test_purge_without_cache` |
| US4.1–4.12 export raw, ordered, read-only, round-trips, non-snapshot | `tests/test_core_export.py`: all 15 tests (`test_export_returns_every_object_in_key_order` … `test_export_propagates_get_failure`) |
| US5.1–5.4 both backends | `EntityPurgeExportConformance` in `tests/storage_conformance.py`, run by `TestInMemoryEntityPurgeExport` (`tests/test_storage_memory.py`) and `TestGcsEntityPurgeExport` (`tests/integration/test_storage_gcs.py`) |
| US6.1–6.2 not agent-facing; public names | `tests/test_core_api_surface.py`: `test_purge_and_export_are_not_agent_facing`, `test_public_names_importable` |

Results: `make check` green (5603 passed, 18 skipped). `make
test-integration` green (44 passed, 1 pre-existing skip); the 4 GCS
`EntityPurgeExport` cases pass on fake-gcs-server, including the non-UTF-8
body and corrupt-metadata round trip.

## Architecture / ADR changes

- New [ADR 0038](../../docs/adr/0038-entity-purge-and-export.md).
- `ARCHITECTURE.md`: bird's-eye view (seven core operations plus two
  operator-only methods), `storage` entry (new conformance mixin;
  `delete_if_version` still the only delete), `core` entry, a key invariant
  for purge's guarantee, and an error-taxonomy note.

## Deviations from spec

- None from this issue's spec. `PurgeIncompleteError` subclasses
  `Exception`, outside ADR 0005's taxonomy, as the spec decided; recorded
  in ADR 0038.

## Look closely at

- `purge`'s `try/except BaseException` wrapper: one invalidation on every
  exit path, the purge error wins on failure, and the log names the scope
  only.
- The guarantee wording: `max_passes` bounds restarts, not a single pass;
  durable erasure needs writers stopped first.
- `ExportedObject` metadata as `MappingProxyType` (equality still compares
  as a mapping).
- `invalidate_index`'s argument checks moved into shared helpers
  (`_normalize_entity_args`, `_check_entity_segments`).

## Follow-ups

- ADR 0040 and its ARCHITECTURE.md text land with AIE-1293; this branch
  cites ADR 0040 by number only.
- GCS soft delete and versioning retain purged bytes; bucket policy is left
  to adopters.
