# Implementation Plan: AIE-1291 Purge and export all memory for an entity

**Branch**: `AIE-1291-purge-export` (based on `AIE-1293-index-cache`) | **Date**: 2026-10-30 | **Spec**: [spec.md](spec.md)

## Summary

Two operator methods on `MemoryStore` — `purge` and `export` — plus the
`ExportedObject` value type and `PurgeIncompleteError`, all in
`src/wenchang/core.py`. Built from the existing `Storage` protocol methods;
no storage, transport, tools, prompts, or mcp change.

## Technical Context

Python 3.11+, pytest, pyright strict, ruff. No new dependencies. Depends on
AIE-1293's `MemoryStore(index_cache=...)` and
`MemoryStore.invalidate_index(scope, entity_id)` (rebase onto its final tip
before the build). Gate: `make check`; storage behavior is exercised against
GCS, so also `make emulator-up` + `make test-integration`.

## Constitution Check

- Tests first; no existing test weakened.
- Storage only through the `Storage` protocol (V): both methods call only
  `list_page`, `get`, `delete_if_version`.
- Public API change: ADR 0038 + ARCHITECTURE.md in the same PR (VII).
- Tests cite `AIE-1291, USx.y`.

## Public interface (`src/wenchang/core.py`)

```python
PURGE_MAX_PASSES: Final = 5

@dataclass(frozen=True)
class ExportedObject:
    """One stored object under an entity's prefix, exactly as stored."""
    key: str                      # full storage key, e.g. "user/u1/notes/a.md"
    data: bytes                   # raw stored bytes, not decoded
    metadata: Mapping[str, str]   # raw stored flat map (a fresh dict copy), not parsed
    version: VersionToken


class PurgeIncompleteError(Exception):
    """Objects were still present under the prefix after the final pass."""
    def __init__(self, scope: str, entity_id: str) -> None
    scope: str
    entity_id: str
    # message: f"purge of {scope!r} did not finish: objects kept appearing
    #           under the entity's prefix after {PURGE_MAX_PASSES} passes"
    # (names the scope, never the entity ID, matching ADR 0040's log rule)


class MemoryStore:
    def purge(self, scope: str, entity_id: str) -> int
    def export(self, scope: str, entity_id: str) -> tuple[ExportedObject, ...]
```

The constant is public as `PURGE_MAX_PASSES` so tests assert the exact pass
count without hardcoding 5.

### Argument validation (both methods, before any storage or cache call)

Same rules and messages as `invalidate_index` (share one private helper):
a `scope` or `entity_id` whose real type is not `str` → `TypeError`; both
normalized with `str.__str__`; failing `is_valid_segment` →
`ValueError(f"invalid scope: {scope!r}")` then
`ValueError(f"invalid entity_id: {entity_id!r}")`. All `TypeError`s before
any `ValueError`.

### `purge`

```
prefix = build_prefix(scope, entity_id)
deleted = 0
try:
    for pass in range(PURGE_MAX_PASSES):
        found = False
        start_after = None
        loop:
            page = storage.list_page(prefix, start_after, list_page_size)
            if not page: break
            for obj in page:
                found = True
                try: storage.delete_if_version(obj.key, obj.version); deleted += 1
                except PreconditionFailedError: pass   # changed or gone; next pass sees it
            start_after = page[-1].key
            if len(page) < list_page_size: break
        if not found: return deleted   # (via the finally below)
    raise PurgeIncompleteError(scope, entity_id)
finally:
    invalidate (see below)
```

- A pass that lists nothing ends the purge. With no concurrent writer:
  one deleting pass plus one empty pass.
- `start_after` continues past keys already handled in this pass, so a
  failed delete is not retried within the pass (no hot loop on one key).
- `BackendUnavailableError` (or any other exception) from `list_page` or
  `delete_if_version` propagates; deletes already made stand.
- Never reads object bodies or parses metadata, so corrupt objects are
  deleted like any other.
- Returns the count of successful `delete_if_version` calls (an object
  rewritten mid-purge and deleted again on a later pass counts once per
  successful delete, i.e. once).

**Invalidation** (ADR 0040 requires it after all deletes finish). The pass
loop above runs in a private helper; `purge` wraps it:

```
try:
    deleted = self._purge_passes(prefix, scope, entity_id)   # may raise PurgeIncompleteError
except BaseException:
    try:
        self.invalidate_index(scope, entity_id)
    except Exception as cache_exc:
        log WARNING (scope + type(cache_exc).__name__, never entity_id)
    raise                                                     # the purge failure wins
self.invalidate_index(scope, entity_id)                       # cache failure propagates
return deleted
```

- Success: a cache exception from `invalidate_index` propagates, after
  every delete has landed (the operator must know the cache still holds
  purged metadata).
- Purge failure (`PurgeIncompleteError`, `BackendUnavailableError`, any
  other exception, or a `BaseException` such as `KeyboardInterrupt`):
  invalidation is still attempted; a cache exception there is logged on
  `logging.getLogger("wenchang.core")` and the original failure re-raised.
- No cache configured: `invalidate_index` is a no-op (AIE-1293).

### `export`

```
prefix = build_prefix(scope, entity_id)
out = []
start_after = None
loop:
    page = storage.list_page(prefix, start_after, list_page_size)
    for obj in page:
        stored = storage.get(obj.key)
        if stored is None: continue            # deleted since listing
        out.append(ExportedObject(obj.key, stored.data, dict(stored.metadata), stored.version))
    if len(page) < list_page_size: break
    start_after = page[-1].key
return tuple(out)
```

- Keys ascend (listing order). Values come from `get`, so each object's
  bytes, metadata, and version are from one write.
- No parsing: corrupt metadata, non-UTF-8 bytes, and non-path keys are
  returned verbatim. Restoring is `storage.put(o.key, o.data, o.metadata)`.
- Not a snapshot (see spec). No cache interaction.
- `BackendUnavailableError` from `list_page` or `get` propagates.

## Test plan (files)

- `tests/test_core_purge.py` — US1, US2, US3. Uses a test-local `Storage`
  wrapper `H` over `InMemoryStorage` with hooks inside `list_page` (after
  the inner result is captured) and `delete_if_version` (before
  delegating), call counters, an event log shared with a recording cache
  wrapper (for 3.3), and injectable exceptions. US3 uses AIE-1293's
  `IndexCache` / `InMemoryIndexCache` and its documented key format
  (`f"{key_prefix}v1:listing:{scope}/{entity_id}"`).
- `tests/test_core_export.py` — US4 (same `H`).
- `tests/storage_conformance.py` — US5 cases appended to
  `StorageConformance`, building `MemoryStore(storage, list_page_size=2)`;
  seeding via `storage.put` with unique keys per test. Run by
  `tests/test_storage_memory.py` (unit) and
  `tests/integration/test_storage_gcs.py` (emulator). Concurrency cases stay
  unit-only (fake-gcs-server does not enforce `ifGenerationMatch` on
  DELETE).
- `tests/test_core_api_surface.py` (or an existing transport/tools test
  module) — US6.

## Docs

- `docs/adr/0038-entity-purge-and-export.md`: decision (core methods over the
  existing protocol, no unconditional delete), rejected alternatives
  (new `Storage.delete` / `delete_prefix`; GCS batch delete; parsed export;
  streaming export; agent-facing tools), concurrent-writer guarantee and pass
  cap, idempotency, export format and non-snapshot semantics, corrupt
  objects included raw, pagination, ADR 0040 interaction (invalidate after
  all deletes; residual race; finite `ttl`), GCS soft delete / versioning,
  AIE-1292 interaction (purge frees all slots).
- `ARCHITECTURE.md`: `core` entry gains `purge`, `export`,
  `ExportedObject`, `PurgeIncompleteError`; the storage entry's "only
  delete is `delete_if_version`" stays true; concurrency section notes purge.
- `specs/AIE-1291-purge-export/review-pr.md`.
