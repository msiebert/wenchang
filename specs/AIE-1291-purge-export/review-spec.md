# Spec Review: AIE-1291 — Purge and export all memory for an entity

## What & why

Operators need to erase (GDPR, project/org deletion) or export everything
stored for one entity, `{scope}/{entity_id}/`. The library owns the key
layout, so it provides `MemoryStore.purge(scope, entity_id, *,
max_passes=5) -> int` and `MemoryStore.export(scope, entity_id) ->
tuple[ExportedObject, ...]`. Both are operator-only: no agent tool and no
transport method.

## Acceptance criteria (condensed; full Given/When/Then in spec.md)

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | an entity with valid, `system/`, corrupt-metadata, non-UTF-8, and non-path objects | `purge` | all gone; listing and index empty; count returned |
| 2 | neighbours `user/u10`, `user/u2`, `project/u1`, `user-archive/u1` | purge / export | untouched / absent from output |
| 3 | an empty entity, or a second purge | `purge` | returns 0, no error |
| 4 | a write lands mid-purge | `purge` | a later pass deletes it; a writer that keeps writing raises `PurgeIncompleteError` after `max_passes` restarts |
| 5 | an index cache is configured (AIE-1293) | `purge` | exactly one `invalidate_index`, after the last storage call, on every exit path; the cached listing holds no purged data |
| 6 | the entity in 1 | `export`, purge, `Storage.put` each object back, export | identical keys, bytes, and metadata |
| 7 | an object deleted or rewritten between export's list and get | `export` | omitted, or returned at its new version consistently |
| 8 | both storage implementations | `EntityPurgeExportConformance` | purge and export pass on the fake and on fake-gcs-server |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| Build both in `core` from the existing `list_page` / `get` / `delete_if_version`; no storage protocol change (orchestrator-approved) | A new `Storage.delete(key)` or `delete_prefix(prefix)` | The protocol deliberately has no unconditional delete. Version-guarded deletes never remove an object version purge didn't list, and the existing methods already run on both backends |
| Purge runs passes until one lists nothing. After at most `max_passes` passes (default `PURGE_MAX_PASSES = 5`), one final check listing runs, then `PurgeIncompleteError` | A single pass; an unbounded loop | One pass misses mid-purge writes. `max_passes` bounds only restarts, not a single pass under an adversarial writer (documented). Durable erasure needs writers stopped first |
| `PurgeIncompleteError(Exception)` in `core`, outside the `WenchangError` taxonomy | A `TransientError` subclass | Taxonomy errors carry agent-facing guidance; this one is operator-only. Recorded as a deviation from ADR 0005 |
| Export returns raw objects (`key`, `bytes`, read-only raw metadata, `version`) | Parsed `MemoryFile`s; skipping or raising on corrupt objects | Lossless; never drops or raises on malformed data; restores byte-for-byte with `Storage.put` |
| Export returns a tuple, paging internally | An iterator or stream; a caller-driven cursor | Keeps errors eager and the API simple. Memory is not bounded by the library (documented); cost is N sequential gets |
| Export is not a snapshot | A re-list-and-compare retry loop | Matches `list_prefix` and the index. A consistent export needs writers stopped, as erasure does |
| One `invalidate_index` call, in a wrapper around the pass loop. On success a cache error propagates (the count is lost; re-running is safe). On failure the cache error is logged and the original re-raised | Invalidating per delete; swallowing cache errors on success | ADR 0040 requires invalidation after the deletes, and an operator must learn that the cache may still hold purged metadata |

## Files/modules to be touched

- `src/wenchang/core.py` (`purge`, `export`, `ExportedObject`, `PurgeIncompleteError`, `PURGE_MAX_PASSES`, docstrings)
- `tests/test_core_purge.py`, `tests/test_core_export.py`, `tests/test_core_api_surface.py`, `tests/storage_conformance.py` (new mixin), `tests/test_storage_memory.py`, `tests/integration/test_storage_gcs.py`
- `docs/adr/0038-entity-purge-and-export.md`, `ARCHITECTURE.md`, `review-pr.md`

## Open questions / assumptions

- Resolved by the orchestrator: no storage interface change (a GCS batch
  delete would be a follow-up); the name stays `export`; `max_passes` is a
  keyword argument whose default is `PURGE_MAX_PASSES = 5`.
- Choice made here: a cache error on the success path propagates without
  carrying the delete count; ADR 0038 and the docstring say so, and
  re-running purge is safe.

## Risks

- GCS soft delete (default 7 days) and object versioning keep purged bytes
  recoverable. This is documented only; bucket configuration is the
  adopter's job.
- ADR 0040's race remains: a reader that listed before the purge can store
  pre-purge metadata in the cache after the tombstone. It is never served,
  but it lives until the next re-index or `ttl`, so a finite `ttl` is
  required for erasure.
- A delete that landed but whose response was lost is not counted.
- Blocked on AIE-1293's implementation being rebased in.
