# Storage and operations

How wenchang uses a GCS bucket, what that costs, and how to erase or export one entity's memory. Everything on this page goes through `MemoryStore` over `GcsStorage` (`wenchang.storage.gcs`), unless it says otherwise. The [reference](reference.md#storage) has the `Storage` protocol and the store's signature.

## The bucket {#bucket}

Memory files are objects in one bucket. One `GcsStorage(bucket)` wraps one `google.cloud.storage.Bucket`. [Quickstart](quickstart.md#bucket) creates one with `gcloud`.

wenchang finds credentials through Application Default Credentials: locally `gcloud auth application-default login`, and on Google Cloud the attached service account. Whatever identity the server runs as needs to read, create, overwrite, delete, and list objects in the bucket. `roles/storage.objectUser` on the bucket grants those. Operator jobs that [purge](#erase) need the same permissions.

<!--html-->
<div class="callout"><strong>One bucket, many people.</strong> Every user and project writes into the same bucket under their own path prefix. Access control between users is wenchang's scope rules, not bucket permissions. Anyone who can read the bucket directly can read all of it.</div>
<!--/html-->
<!--md-->
> **One bucket, many people.** Every user and project writes into the same bucket under their own path prefix. Access control between users is wenchang's scope rules, not bucket permissions. Anyone who can read the bucket directly can read all of it.
<!--/md-->

Bucket soft delete and object versioning keep deleted bytes recoverable. Set them to match your retention obligations; see [Deleted bytes in GCS](#deleted-bytes).

## Objects and metadata {#metadata}

Each memory file is one object. Its key is the file's path, `{scope}/{entity_id}/{area}/{name}.md` (see [Concepts](concepts.md#paths)). Its body is the file content as UTF-8, with content type `text/markdown; charset=utf-8`. Its version is the object's generation.

The file metadata is GCS custom metadata on the object, under four keys:

| Stored key | Encoding | Example |
| --- | --- | --- |
| `description` | Plain string, one line. | `Lin Qiao, the protagonist` |
| `aliases` | JSON array of strings, in order. | `["Qiao", "Lin"]` |
| `sources` | JSON array of strings, sorted. | `["claude-code", "inkwell-web"]` |
| `last-updated` | ISO 8601 in UTC with a `Z` suffix. | `2026-10-30T14:02:11.402913Z` |

Tool results and the index show the last one as `last_updated`, with an underscore, and `aliases` and `sources` as arrays. Other keys on an object are ignored.

### Writing objects out of band {#out-of-band}

Reads and listings parse all four keys and require every one. An object written another way, such as `gcloud storage cp` or the GCS console, without them fails with `MetadataFormatError`: reading that file fails, and so do `list_prefix` and `get_memory_index` for every caller whose grants include that entity. The agent sees an `internal` error naming the key.

Write through a `MemoryStore`, as the [seed script](quickstart.md#seed) does, or set all four keys yourself. A store with an index cache does not see out-of-band writes; [invalidate](#invalidate) the entity afterwards.

## Files per entity {#file-cap}

An entity is everything under one `{scope}/{entity_id}/` prefix: one user's private memory, or one project's shared memory. `MemoryStore(max_files_per_entity=...)` caps how many files it holds. The default is 500 (`wenchang.core.DEFAULT_MAX_FILES_PER_ENTITY`); `None` disables the cap, and any other value must be positive (`ValueError` otherwise).

```python
store = MemoryStore(storage, max_files_per_entity=200)  # or None for no cap
```

Only creates are checked: a `write_file` with `expected_version=null` outside `system/`. Replacing a file, `append_line`, `replace_fact`, `delete_file`, and reads never are, so an entity at its cap keeps working on the files it has. Files in `system/` and keys that are not well-formed memory paths are not counted. Deleting a file frees a slot.

At the cap, the create fails with a recoverable `FileQuotaExceededError` whose payload carries `limit` (plus `scope`, `area`, and `name`). If a file already exists at that path, the create fails with `VersionConflictError` instead, as it would below the cap. For scope `user`, area `notes`, name `new`, and a limit of 3, the agent sees:

```
Cannot create a new file at scope user, area notes, name new: memory in scope user is at its limit of 3 files (system/ files not counted). Add this content to an existing file instead (append_line, replace_fact, or write_file with that file's version), or merge related files into one and delete the merged ones with delete_file, then retry.
```

followed by the standard recoverable guidance, so the agent consolidates and retries in the same turn without asking the user.

The cap is soft. Counting and writing are not atomic, so concurrent creates in one entity can exceed it by at most the number of creates racing at the boundary. Each checked create counts the entity's keys with `Storage.list_page`, in pages of `max(limit - count, list_page_size)` keys, stopping once it reaches the limit: at most the limit plus the uncounted keys plus one `list_page_size` page, and usually one list call.

## Index cost {#index-cost}

`get_memory_index` is what the agent calls at the start of every session. It costs you in two places.

- **The model's context.** The index is capped at `index_max_bytes`, 65536 by default. Each entry is sized as the UTF-8 bytes of its path, its four stored metadata keys and values (in the encodings above), and its version. Entries are added in index order until the next one would pass the cap; the rest are reported under `capped`. The JSON the agent receives adds field names and punctuation on top of that budget, so the payload is somewhat larger than `index_max_bytes`.
- **Storage calls.** Without a cache, every call lists every object under every granted `{scope}/{entity_id}/` prefix, in pages of `list_page_size`, before it caps anything. Listings never read bodies, but the work grows with the number of files in the caller's entities, and the cap does not reduce it. The [file cap](#file-cap) bounds it per entity.

An index cache removes the listing for entities that have not changed.

## The index cache {#index-cache}

You can give `MemoryStore` a cache for `get_memory_index`. The cache is optional, and without one nothing changes. With one, the store caches each entity's listing separately, and every write or delete through the store invalidates that entity's entry. Ordering, the size cap, and `capped` are still worked out on each call, so a cached index has the same shape as an uncached one.

wenchang does not ship a cache server. You supply two functions over the cache you already run, such as Redis.

### What you provide {#cache-contract}

`wenchang.index_cache.IndexCache(get, set, ttl=None, key_prefix="wenchang:index:")` is a frozen configuration object.

- **`get(key) -> str | None`** returns the value last set for `key`, or `None` if it is absent or expired.
- **`set(key, value, ttl) -> None`** stores `value` under `key`, expiring `ttl` (a `timedelta`) from now. `ttl` is `None` for no expiry.
- **`ttl`** is passed unchanged to every `set`. It must be positive if given.
- **`key_prefix`** starts every key the store writes.

Both functions are required: `set` is how the store invalidates, so a read-only cache cannot work. Keys and values are opaque strings. Do not parse them.

Pass it to the store:

```python
store = MemoryStore(storage, index_cache=IndexCache(get=..., set=..., ttl=timedelta(minutes=10)))
```

`store.index_cache` returns the configured cache, or `None`.

### A Redis example {#redis}

This adapter uses redis-py. It is an illustration, not something wenchang depends on: install the client yourself.

<!--include python cache_redis.py-->

Points to notice:

- **`get` must return `str`.** redis-py returns `bytes` unless the client is created with `decode_responses=True`. If you share a client that does not decode, decode in `get` instead: `value = r.get(key)`, then `return None if value is None else value.decode()`. A `bytes` result is not an error, but the store treats it as a miss and logs a warning on every call, so the cache never helps.
- **`set` maps `ttl` to an expiry.** A finite `ttl` becomes `px` in milliseconds. `None` stores the key with no expiry.
- **One Redis primary is enough.** The cache needs each key's `get` and `set` to be linearizable, which a single primary provides. See [Guarantees and limits](#cache-limits) for replicas.

### In-process cache {#in-memory}

`wenchang.index_cache.InMemoryIndexCache` is a thread-safe cache held in one process, for tests and single-process hosts:

```python
from datetime import timedelta

from wenchang.index_cache import IndexCache, InMemoryIndexCache

cache = InMemoryIndexCache()
index_cache = IndexCache(get=cache.get, set=cache.set, ttl=timedelta(minutes=5))
store = MemoryStore(storage, index_cache=index_cache)
```

It drops expired entries only when they are read, so with `ttl=None` it grows without bound. A host that runs several instances needs a shared cache: each instance's in-process cache misses the other instances' writes.

### Writes that bypass the cache {#invalidate}

`write_file`, `append_line`, `replace_fact`, and `delete_file` on a store that has the cache invalidate the entity themselves, whether the storage call succeeded or raised. Anything else that changes files in the bucket does not. That includes:

- a seeding job or admin tool,
- another `MemoryStore` built without the cache (such as the [seed script](quickstart.md#seed)),
- a direct write through `gcloud` or the GCS API, including a [restore](#export).

The simplest fix is to give those writers the same `IndexCache`. Otherwise, after they finish, call `MemoryStore.invalidate_index(scope, entity_id)` on a store that has the cache:

```python
seed_store = MemoryStore(GcsStorage(bucket))  # no cache, so its writes do not invalidate
# ... seed_store writes under organization/o-hanlin-press/ ...
cached_store = MemoryStore(GcsStorage(bucket), index_cache=index_cache)
cached_store.invalidate_index("organization", "o-hanlin-press")
```

The next `get_memory_index` that includes that entity lists storage again. `invalidate_index` also overwrites the entity's cached listing, so deleted descriptions and aliases do not stay in your cache. A [purge](#erase) calls it once all of its deletes finish.

`invalidate_index` raises `TypeError` for a non-`str` argument and `ValueError` for an invalid scope or entity ID, before touching the cache. It does nothing on a store with no cache. Unlike the store's own invalidation, it does not swallow cache errors: if `set` raises, so does `invalidate_index`, because the caller asked for the invalidation and should know it did not happen.

A writer that does not invalidate leaves the entity stale until its next write through the cached store, or until `ttl` expires.

### When the cache fails {#cache-failures}

The cache never makes a memory operation fail.

- If `get` raises, or returns something that is not a `str`, the store logs a warning and lists storage as if nothing were cached.
- If `set` raises, the store logs a warning and skips the store or invalidation. Writes still return their normal result.

Warnings go to the `wenchang.core` logger. They name the scope and the exception or result type, never the entity ID or the key. An exception that is not an `Exception` subclass (such as `KeyboardInterrupt`) still propagates. Storage errors while listing propagate as they do without a cache, and nothing is cached for that entity.

A swallowed invalidation failure leaves the entity's old listing in place, and only `ttl` bounds how long it is served. Watch for these warnings.

### Guarantees and limits {#cache-limits}

The store keeps a random generation token for each entity. A reader records the token before listing storage and tags its cached listing with it. Every write replaces the token after its storage call, so a listing taken before that write is never served afterwards, even if it is stored late. What this does not cover:

- **`ttl=None` means unbounded staleness.** Tokens cannot detect a write that did not invalidate: an out-of-band write, or an invalidation whose `set` failed. With a finite `ttl`, such an entity is stale for at most `ttl`. With `ttl=None`, it stays stale until something invalidates it or your cache evicts the key. Use a finite `ttl` in production.
- **Timed-out writes.** A write that raised `BackendUnavailableError` (for example a timeout) may still commit in GCS after the store has replaced the token. A reader in between can cache the listing from before the commit under the new token. That listing is served until the entity's next write or invalidation, or until `ttl` expires.
- **Deleted metadata can linger, unserved.** A reader that listed before a delete can store its pre-delete listing after the delete overwrote it. Its tag is stale, so it is never served, but it stays in your cache until the entity is indexed again or `ttl` expires. If you have erasure obligations, a finite `ttl` is required, not just recommended.
- **Per-key linearizable `get` and `set`.** A cache where a `get` can miss an earlier `set` to the same key, such as one reading from asynchronous replicas, bounds freshness only by `ttl`. Operations do not need to be atomic across keys.
- **One `key_prefix` per storage root.** Keys do not identify the bucket. Stores over different buckets or roots that share one cache need distinct prefixes, and no prefix may be a string prefix of another (`"a:"` and `"a:b:"` collide, because scope and entity names may contain `:`). End each prefix in a delimiter and keep them distinct. This is not checked at runtime.
- **Large entities make large values.** A cached listing holds one entry per file in the entity.

<!--html-->
<div class="callout callout-warn"><strong>The cache holds memory metadata.</strong> Cached values contain each file's description, aliases, and sources. Keys contain scope names and entity IDs, which are often user IDs. Your cache inherits the same data-handling obligations as the bucket. File content is never cached.</div>
<!--/html-->
<!--md-->
> **The cache holds memory metadata.** Cached values contain each file's description, aliases, and sources. Keys contain scope names and entity IDs, which are often user IDs. Your cache inherits the same data-handling obligations as the bucket. File content is never cached.
<!--/md-->

## Timeouts and retries {#retries}

wenchang has no timeout or retry setting of its own. `GcsStorage` calls google-cloud-storage with that library's defaults, plus one loop:

- **`get` retries a generation race.** It reads the object's metadata, then downloads the body only if the generation is unchanged. If the object was replaced or deleted in between, it starts over, up to 3 attempts, then raises `BackendUnavailableError`.
- **Timeout.** Each GCS request uses google-cloud-storage's default timeout, 60 seconds.
- **Retries.** google-cloud-storage retries 408, 429, 500, 502, 503, and 504 responses and connection errors, backing off from 1 second, doubling up to 60 seconds between tries, for at most 120 seconds. Which calls it retries depends on its major version. wenchang requires `google-cloud-storage>=2.18`, and its lockfile installs 3.14.1.

| Storage call | GCS request | google-cloud-storage 3.x | 2.x |
| --- | --- | --- | --- |
| `get`, `list_page` | get metadata, download, list | retried | retried |
| `put_if_version` | upload with `if_generation_match` | retried | retried |
| `delete_if_version` | delete with `if_generation_match` | retried | retried |
| `put` | upload with no precondition | retried | not retried |

`MemoryStore` writes only through `put_if_version` and `delete_if_version`, so a retried write is guarded by its generation. `put` is what a [restore](#export) calls.

How a failure reaches the agent:

- **A retried call that keeps failing** raises google-cloud-storage's `google.api_core.exceptions.RetryError` once the 120-second budget runs out. `GcsStorage` does not map it, so it propagates out of the store unchanged, and the agent sees an `internal` error with a generic message.
- **A timeout, connection error, or 429, 500, 502, 503, or 504 on a call that is not retried** (an unconditional `put` under google-cloud-storage 2.x) is mapped to `BackendUnavailableError`, reason `timeout` or `unavailable`, which the agent sees as `transient`. So is a `get` that loses the generation race 3 times.
- **A failed generation precondition** is not an error here: it becomes the store's `VersionConflictError`, or is skipped by purge.
- **Anything else**, such as a 403 from missing permissions, propagates unchanged and is an `internal` error.

## Erasing an entity {#erase}

Erasure requests and project or org deletion need everything stored for one entity removed or handed over. `MemoryStore` has two methods for that:

- **`purge(scope, entity_id, *, max_passes=PURGE_MAX_PASSES) -> int`** deletes every object under `{scope}/{entity_id}/`.
- **`export(scope, entity_id) -> tuple[ExportedObject, ...]`** returns every object under that prefix, raw.

Both are operator-only. They are not agent tools and not on the transport: `TransportClient`, `MemoryTools`, and the MCP adapter do not have them. Call them on a `MemoryStore` directly; `InProcessClient.store` returns the store a client wraps. Both work on `GcsStorage` and `InMemoryStorage`.

To erase one user, for example under a GDPR erasure request:

1. **Stop writers.** Change your resolver so it no longer grants that user's scope, and let in-flight sessions end.
2. **Export**, if you need to hand the data over or keep a copy.
3. **Purge** the prefix, on a store configured like your server's, including its `index_cache`, so the purge invalidates the cached index. The cache needs a finite `ttl` for erasure; see [Guarantees and limits](#cache-limits).
4. **Clear retained bytes.** Purge removes live objects only. See [Deleted bytes in GCS](#deleted-bytes).

<!--include python ops_erase.py-->

### How purge works {#purge}

A pass lists the prefix from the start and deletes each object it sees, guarded on the listed version. An object that changed or vanished in the meantime is left for the next pass. Passes repeat until one lists nothing.

- **Everything goes.** Purge deletes every object under `{scope}/{entity_id}/`, including `system/` files, keys that are not valid memory paths, and objects with corrupt metadata. It never reads bodies or parses metadata.
- **The guarantee.** When `purge` returns, the prefix was observed empty after its last delete. A write that lands after that survives. Durable erasure requires stopped writers.
- **`max_passes` bounds restarts, not a pass.** At most `max_passes + 1` listings start from the beginning of the prefix. A writer that adds keys faster than purge deletes them keeps a single pass running. `PURGE_MAX_PASSES` is 5.
- **`PurgeIncompleteError`** is raised if objects remain after the last pass. It is a plain `Exception`, not a `WenchangError`, with `scope`, `entity_id`, and `passes` attributes. Its message names the scope and pass count, never the entity ID.
- **Re-running is safe.** On an empty prefix purge returns 0 without deleting anything. The return value counts deletes storage confirmed: a delete that landed but whose response was lost is not counted, so treat it as a lower bound.
- **Other storage errors propagate.** Deletes already made stand. Re-run once the backend recovers.
- **Arguments are checked first.** A non-`str` `scope` or `entity_id`, or a non-`int` `max_passes`, raises `TypeError`. An invalid segment or `max_passes` below 1 raises `ValueError`. Neither touches storage or the cache.
- **Cost.** N objects take N sequential deletes, roughly N round trips on GCS.

Purge calls [`invalidate_index`](#invalidate) once, after its last storage call, whether it succeeded or failed. On success a cache error propagates and the delete count is lost; re-running returns 0 and invalidates again. On failure a cache error is logged to `wenchang.core` and the purge's own exception is raised. A reader that listed before the purge can still store its pre-purge listing in your cache. It is never served, but it stays until the entity is indexed again or `ttl` expires.

An invalid `entity_id` is echoed in the `ValueError` message (`invalid entity_id: '...'`), the same message `invalidate_index` and `get_memory_index` raise. If entity IDs identify people, do not log that message as is.

### Deleted bytes in GCS {#deleted-bytes}

Purge removes live objects only. A bucket's soft-delete policy (7 days by default on new GCS buckets) and object versioning keep deleted bytes recoverable for their retention window. Set both to match your retention obligation: `gcloud storage buckets update gs://BUCKET --clear-soft-delete` disables soft delete.

## Export and restore {#export}

`export` lists the prefix and `get`s each object, returning them in ascending key order. Each `ExportedObject` has:

| Field | Value |
| --- | --- |
| `key` | The full storage key. |
| `data` | The raw body, as `bytes`. |
| `metadata` | The stored metadata map, read-only, with the [stored keys](#metadata). |
| `version` | The storage version token. |

Nothing is parsed, so malformed keys, corrupt metadata, and non-UTF-8 bodies are exported as they are. To restore, `put` each object back through the same storage the store uses, then invalidate the entity's cached index:

<!--include python ops_restore.py-->

- **A backup, not a snapshot.** Each object is internally consistent, but an object deleted between listing and `get` is omitted, and one written after its page was listed may be missing. Stop writers for a consistent export. Export never touches the index cache.
- **Memory.** Every object's bytes are held at once. The library does not bound this.
- **Cost.** N objects take N sequential `get` calls, roughly N round trips on GCS.
