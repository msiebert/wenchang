# Implementation Plan: AIE-1291 Purge and export all memory for an entity

**Branch**: `AIE-1291-purge-export` (based on `AIE-1293-index-cache`) | **Date**: 2026-10-30 | **Spec**: [spec.md](spec.md)

## Summary

Two operator methods on `MemoryStore`, `purge` and `export`, plus
`ExportedObject`, `PurgeIncompleteError`, and `PURGE_MAX_PASSES`, all in
`src/wenchang/core.py`. Built from the existing `Storage` protocol methods;
no storage, transport, tools, prompts, or mcp change.

## Technical Context

Python 3.11+, pytest, pyright strict, ruff. No new dependencies. Depends on
AIE-1293's `MemoryStore(index_cache=...)`, `MemoryStore.index_cache`, and
`MemoryStore.invalidate_index(scope, entity_id)`; the build starts only after
AIE-1293's implementation is rebased in. Gate: `make check`; also
`make emulator-up` + `make test-integration` for the GCS conformance run.

## Constitution Check

- Tests first; no existing test weakened.
- Storage only through the `Storage` protocol (V): both methods call only
  `list_page`, `get`, `delete_if_version`.
- Public API change: ADR 0038 + ARCHITECTURE.md in the same PR (VII).
- `PurgeIncompleteError` is outside the `WenchangError` taxonomy (ADR 0005):
  recorded as a deviation in ADR 0038 and ARCHITECTURE.md.
- Tests cite `AIE-1291, USx.y`.

## Public interface (`src/wenchang/core.py`)

```python
PURGE_MAX_PASSES: Final = 5


@dataclass(frozen=True)
class ExportedObject:
    """One stored object under an entity's prefix, exactly as stored."""

    key: str                      # full storage key, e.g. "user/u1/notes/a.md"
    data: bytes                   # raw stored bytes, not decoded
    metadata: Mapping[str, str]   # raw stored flat map, not parsed; read-only
    version: VersionToken

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


class PurgeIncompleteError(Exception):
    """Objects were still present under the prefix after the final pass."""

    def __init__(self, scope: str, entity_id: str, passes: int) -> None
    scope: str
    entity_id: str
    passes: int
    # str(e) == f"purge of an entity in scope {scope!r} did not finish: "
    #           f"objects were still present after {passes} passes"
    # names the scope and the passed `passes`, never the entity ID


class MemoryStore:
    def purge(self, scope: str, entity_id: str, *, max_passes: int = PURGE_MAX_PASSES) -> int
    def export(self, scope: str, entity_id: str) -> tuple[ExportedObject, ...]
```

`ExportedObject` does no type validation; it is built by the library. Its
equality compares `metadata` as mappings (`MappingProxyType.__eq__`
delegates to the dict).

### Argument validation (before any storage or cache call)

One private helper shared with `invalidate_index`: a `scope` or
`entity_id` whose real type is not `str` → `TypeError`; both normalized
with `str.__str__`. `purge` also checks `max_passes`: real type not `int`,
or a `bool` → `TypeError`. Then `ValueError`s: `ValueError(f"invalid scope:
{scope!r}")`, `ValueError(f"invalid entity_id: {entity_id!r}")` (failing
`is_valid_segment`), then `ValueError("max_passes must be positive")` for
`max_passes < 1`. All `TypeError`s before any `ValueError`.

### `purge`

Private helper `_purge_passes(prefix, scope, entity_id, max_passes) -> int`
(no cache calls, no try/finally):

```
deleted = 0
for _ in range(max_passes):
    found = False
    start_after = None
    while True:
        page = storage.list_page(prefix, start_after, list_page_size)
        for obj in page:
            found = True
            try:
                storage.delete_if_version(obj.key, obj.version)
                deleted += 1
            except PreconditionFailedError:
                pass                       # changed or gone; the next pass sees it
        if len(page) < list_page_size:
            break
        start_after = page[-1].key
    if not found:
        return deleted
if not storage.list_page(prefix, None, 1):
    return deleted                         # final check
raise PurgeIncompleteError(scope, entity_id, max_passes)
```

`purge` validates, builds `prefix = build_prefix(scope, entity_id)`, and
wraps the helper. This wrapper is the only place `invalidate_index` is
called, so each purge makes exactly one call:

```
try:
    deleted = self._purge_passes(prefix, scope, entity_id, max_passes)
except BaseException:
    try:
        self.invalidate_index(scope, entity_id)
    except Exception as cache_exc:
        _logger.warning("index cache invalidation failed after purge of scope %r: %s",
                        scope, type(cache_exc).__name__)
    raise                                  # the purge failure wins
self.invalidate_index(scope, entity_id)    # a cache failure propagates; the count is lost
return deleted
```

- Listings starting at `start_after=None` never exceed `max_passes + 1`.
  `max_passes` bounds only those restarts; a single pass runs while pages
  come back full.
- `start_after` moves past keys already handled in this pass, so a failed
  delete is not retried within the pass.
- Any exception from `list_page` or `delete_if_version` other than
  `PreconditionFailedError` propagates; deletes already made stand.
- Never reads object bodies or parses metadata.
- No cache configured: `invalidate_index` returns without a cache call.

Docstring (concise) states: deletes everything under the prefix including
`system/`; operator-only; guarantee and "stop writers first"; `max_passes`
bounds restarts, not a single pass; count excludes deletes whose response
was lost, and re-running is safe; invalidation on every exit path, cache
error propagates on success (count lost) and is logged on failure; on
interrupt it calls the adopter's cache, which may block; ADR 0040 residual
race and finite `ttl`; GCS soft delete / versioning retain bytes; cost is N
sequential deletes (≈ N × RTT on GCS).

### `export`

```
prefix = build_prefix(scope, entity_id)
out = []
start_after = None
while True:
    page = storage.list_page(prefix, start_after, list_page_size)
    for obj in page:
        stored = storage.get(obj.key)
        if stored is None:
            continue                       # deleted since listing
        out.append(ExportedObject(obj.key, stored.data, stored.metadata, stored.version))
    if len(page) < list_page_size:
        break
    start_after = page[-1].key
return tuple(out)
```

Docstring states: raw objects, nothing parsed or dropped for being
malformed; restore with `Storage.put(o.key, o.data, o.metadata)`; not a
snapshot; no cache interaction; memory is unbounded by the library (every
object's bytes held at once) and cost is N sequential `get`s (≈ N × RTT on
GCS).

`MemoryStore`'s class docstring lists `purge` and `export` as operator
methods alongside the seven core operations.

## Test plan (files)

- `tests/test_core_purge.py` — US1, US2, US3. A test-local recording
  `Storage` wrapper `H` over `InMemoryStorage`: an ordered call log
  (method, args), per-method hooks run before or after delegating, and
  injectable exceptions. A test-local cache wrapper over
  `InMemoryIndexCache` that appends its `set` calls to `H`'s log and can be
  made to raise. Uses AIE-1293's `IndexCache` / `InMemoryIndexCache` and
  key format (`f"{key_prefix}v1:token:{scope}/{entity_id}"`,
  `...v1:listing:...`), and `caplog`.
- `tests/test_core_export.py` — US4, same `H`.
- `tests/storage_conformance.py` — US5: new mixin
  `EntityPurgeExportConformance`. Subclassed in `tests/test_storage_memory.py`
  (unit, `InMemoryStorage`) and `tests/integration/test_storage_gcs.py`
  (emulator).
- `tests/test_core_api_surface.py` — US6.

## Docs

- `docs/adr/0038-entity-purge-and-export.md`: decision (core methods over
  the existing protocol; no unconditional delete), rejected alternatives
  (new `Storage.delete` / `delete_prefix`; GCS batch delete; parsed export;
  streaming export; agent-facing tools; `TransientError` subclass), the
  pass algorithm and its guarantee, `max_passes` bounds restarts only,
  idempotency, the delete count and its undercount when a delete landed but
  its response was lost (re-running is safe), export format and
  non-snapshot semantics, corrupt objects included raw, cost (N sequential
  calls, ≈ N × RTT) and unbounded export memory (why AIE-1292's cap does
  not bound it), ADR 0040 interaction (one invalidation after the last
  storage call; failure-path logging; may block on interrupt; residual
  race; finite `ttl`), GCS soft delete / versioning, AIE-1292 (purge frees
  all slots), and the taxonomy deviation for `PurgeIncompleteError`.
- `ARCHITECTURE.md`: `core` entry (operation count wording; `purge`,
  `export`, `ExportedObject`, `PurgeIncompleteError`, `PURGE_MAX_PASSES`);
  error-taxonomy section (operator-only errors outside the taxonomy:
  `PurgeIncompleteError`); storage entry's conformance description (the
  new `EntityPurgeExportConformance` mixin run on both backends; the only
  delete is still `delete_if_version`); concurrency section (purge).
- `specs/AIE-1291-purge-export/review-pr.md`.
