# Spec Review: AIE-1291 — Purge and export all memory for an entity

## What & why

Operators need to erase (GDPR, project/org deletion) or export everything
stored for one entity, `{scope}/{entity_id}/`. The library owns the key
layout, so it provides `MemoryStore.purge(scope, entity_id) -> int` and
`MemoryStore.export(scope, entity_id) -> tuple[ExportedObject, ...]`. They're
operator-only: no agent tool, no transport method.

## Acceptance criteria (condensed; full Given/When/Then in spec.md)

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | entity with valid, `system/`, corrupt-metadata, non-UTF-8, and non-path objects | `purge` | all gone; listing and index empty; count returned |
| 2 | neighbours `user/u10`, `user/u2`, `project/u1`, `user-archive/u1` | purge / export | untouched / absent from output |
| 3 | empty entity, or purge twice | `purge` | returns 0, no error |
| 4 | a write lands mid-purge | `purge` | a later pass deletes it; a writer that never stops raises `PurgeIncompleteError` after 5 passes |
| 5 | index cache configured (AIE-1293) | `purge` | `invalidate_index` runs after the last delete; the cached listing holds no purged data; it runs on failure paths too |
| 6 | entity as in 1 | `export`, purge, `Storage.put` each object back, export | identical keys, bytes, and metadata |
| 7 | object deleted / rewritten between export's list and get | `export` | omitted / returned at its new version, consistently |
| 8 | both storage implementations | conformance suite | purge and export cases pass on the fake and on fake-gcs-server |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| Build both in `core` from existing `list_page` / `get` / `delete_if_version`; no storage protocol change | New `Storage.delete(key)` or `delete_prefix(prefix)` | The protocol deliberately has no unconditional delete; version-guarded deletes never remove an object version purge didn't list, and the existing methods already run on both backends |
| Purge in passes until a pass lists nothing; at most `max_passes` (default `PURGE_MAX_PASSES = 5`) deleting passes, then a final check listing, then `PurgeIncompleteError` | Single pass; unbounded loop | One pass misses mid-purge writes; an unbounded loop can spin forever under a live writer. Documented guarantee: the prefix was seen empty after purge's last delete; durable erasure needs writers stopped first |
| `PurgeIncompleteError(Exception)` in `core`, not in the `WenchangError` taxonomy | `TransientError` subclass | Taxonomy errors carry agent-facing guidance; this is operator-only |
| Export returns raw objects (`key`, `bytes`, raw metadata map, `version`) | Parsed `MemoryFile`s; skip or raise on corrupt objects | Lossless, never drops or raises on malformed data, and restores with `Storage.put` byte-for-byte |
| Export returns a tuple, paging internally | Iterator/streaming; caller-driven cursor | Entity size is bounded (file cap AIE-1292 × file size); a tuple keeps errors eager and the API simple |
| Export is not a snapshot | Re-list-and-compare retry loop | Matches `list_prefix` and the index; consistent export needs writers stopped, as does erasure |
| Purge calls `invalidate_index` once after all deletes, also on failure (cache error logged there, original re-raised); on success a cache error propagates | Invalidate per delete; swallow on success | ADR 0040 requires post-delete invalidation; an operator must learn the cache still holds purged metadata |

## Files/modules to be touched

- `src/wenchang/core.py` (methods, `ExportedObject`, `PurgeIncompleteError`, `PURGE_MAX_PASSES`)
- `tests/test_core_purge.py`, `tests/test_core_export.py`, `tests/storage_conformance.py`, an API-surface test
- `docs/adr/0038-entity-purge-and-export.md`, `ARCHITECTURE.md`, `review-pr.md`

## Open questions / assumptions

- Resolved by the orchestrator: no storage interface change (a GCS batch
  delete would be a follow-up); the name stays `export`; the pass cap is the
  public default `PURGE_MAX_PASSES = 5`, which a keyword-only `max_passes`
  overrides.

## Risks

- GCS soft delete (default 7 days) and object versioning keep purged bytes
  recoverable; documented only, bucket config is the adopter's job.
- ADR 0040's race remains: a reader that listed before the purge can store
  pre-purge metadata in the cache after the tombstone (never served; lives
  until re-index or `ttl`). Erasure-bound adopters must set a finite `ttl`.
- Base branch AIE-1293 is still being built; rebase before the build.
