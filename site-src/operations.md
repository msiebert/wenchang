# Purge & export

Erasure requests and project or org deletion need everything stored for one entity removed or handed over. `MemoryStore` has two methods for that:

- **`purge(scope, entity_id, *, max_passes=PURGE_MAX_PASSES) -> int`** deletes every object under `{scope}/{entity_id}/`.
- **`export(scope, entity_id) -> tuple[ExportedObject, ...]`** returns every object under that prefix, raw.

Both are operator-only. They are not agent tools and not on the transport: `TransportClient`, `MemoryTools`, and the MCP adapter do not have them. Call them on a `MemoryStore` directly. `InProcessClient.store` returns the store a client wraps. Both work on `GcsStorage` and `InMemoryStorage`.

## Erasing an entity {#erase}

Stop the entity's writers first, then purge. For a user, that means your resolver no longer grants that user's scope. Export first if you need a copy.

<!--include python ops_erase.py-->

Use the same `MemoryStore` configuration as your server, including its `index_cache`, so the purge invalidates the cached index.

## How purge works {#purge}

A pass lists the prefix from the start and deletes each object it sees, guarded on the listed version. An object that changed or vanished in the meantime is left for the next pass. Passes repeat until one lists nothing.

- **Everything goes.** Purge deletes every object under `{scope}/{entity_id}/`, including `system/` files, keys that are not valid memory paths, and objects with corrupt metadata. It never reads bodies or parses metadata.
- **The guarantee.** When `purge` returns, the prefix was observed empty after its last delete. A write that lands after that survives. Durable erasure requires stopped writers.
- **`max_passes` bounds restarts, not a pass.** At most `max_passes + 1` listings start from the beginning of the prefix. A writer that adds keys faster than purge deletes them keeps a single pass running. `PURGE_MAX_PASSES` is 5.
- **`PurgeIncompleteError`** is raised if objects remain after the last pass. It is a plain `Exception`, not a `WenchangError`, with `scope`, `entity_id`, and `passes` attributes. Its message names the scope and pass count, never the entity ID.
- **Re-running is safe.** On an empty prefix purge returns 0 without deleting anything. The return value counts deletes storage confirmed: a delete that landed but whose response was lost is not counted, so treat it as a lower bound.
- **Other storage errors propagate.** Deletes already made stand. Re-run once the backend recovers.
- **Arguments are checked first.** A non-`str` `scope` or `entity_id`, or a non-`int` `max_passes`, raises `TypeError`. An invalid segment or `max_passes` below 1 raises `ValueError`. Neither touches storage or the cache.

### The index cache {#cache}

Purge calls [`invalidate_index`](caching.md#invalidate) once, after its last storage call, whether it succeeded or failed. On success a cache error propagates and the delete count is lost; re-running returns 0 and invalidates again. On failure a cache error is logged to `wenchang.core` and the purge's own exception is raised.

A reader that listed before the purge can still store its pre-purge listing in your cache. It is never served, but it stays until the entity is indexed again or `ttl` expires. If you have erasure obligations, a finite `ttl` is required. See [Guarantees and limits](caching.md#limits).

### Deleted bytes in GCS {#gcs}

Purge removes live objects only. A bucket's soft-delete policy (7 days by default on new GCS buckets) and object versioning keep deleted bytes recoverable for their retention window. Set both to match your retention obligation: `gcloud storage buckets update gs://BUCKET --clear-soft-delete` disables soft delete.

## Export {#export}

`export` lists the prefix and `get`s each object, returning them in ascending key order. Each `ExportedObject` has:

| Field | Value |
| --- | --- |
| `key` | The full storage key. |
| `data` | The raw body, as `bytes`. |
| `metadata` | The stored flat metadata map, read-only. |
| `version` | The storage version token. |

Nothing is parsed, so malformed keys, corrupt metadata, and non-UTF-8 bodies are exported as they are. To restore, `put` each object back through the same storage the store uses:

<!--include python ops_restore.py-->

- **A backup, not a snapshot.** Each object is internally consistent, but an object deleted between listing and `get` is omitted, and one written after its page was listed may be missing. Stop writers for a consistent export. Export never touches the index cache.
- **Memory.** Every object's bytes are held at once. The library does not bound this.
- **Cost.** N objects take N sequential `get` calls, roughly N round trips on GCS. Purge likewise makes N sequential deletes.

## Known limitation {#limitations}

An invalid `entity_id` is echoed in the `ValueError` message (`invalid entity_id: '...'`), the same message `invalidate_index` and `get_memory_index` raise. If entity IDs identify people, do not log that message as is.
