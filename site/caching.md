# Caching the index

`get_memory_index` lists storage every time it is called. For each scope in the caller's scope map, it pages through every object under that scope's `{scope}/{entity_id}/` prefix. Hosts call it at the start of every session, and the cost grows with the number of files.

You can give `MemoryStore` a cache to avoid that. The cache is optional, and without one nothing changes. With one, the store caches each entity's listing separately, and every write or delete through the store invalidates that entity's entry. Ordering, the size cap, and `capped` are still worked out on each call, so a cached index has the same shape as an uncached one.

wenchang does not ship a cache server. You supply two functions over the cache you already run, such as Redis.

## What you provide

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

## A Redis example

This adapter uses redis-py. It is an illustration, not something wenchang depends on: install the client yourself (`pip install redis`).

```python
import os
from datetime import timedelta

import redis
from google.cloud import storage

from wenchang.core import MemoryStore
from wenchang.index_cache import IndexCache
from wenchang.storage.gcs import GcsStorage

# decode_responses=True makes get return str, which the cache must return.
r = redis.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)


def cache_get(key: str) -> str | None:
    return r.get(key)


def cache_set(key: str, value: str, ttl: timedelta | None) -> None:
    if ttl is None:
        r.set(key, value)
    else:
        r.set(key, value, px=max(1, ttl // timedelta(milliseconds=1)))


index_cache = IndexCache(get=cache_get, set=cache_set, ttl=timedelta(minutes=10))

bucket = storage.Client(project="my-gcp-project").bucket(os.environ["WENCHANG_BUCKET"])
store = MemoryStore(
    GcsStorage(bucket),
    scope_priority=("user", "project", "organization"),
    index_cache=index_cache,
)
```

Points to notice:

- **`get` must return `str`.** redis-py returns `bytes` unless the client is created with `decode_responses=True`. If you share a client that does not decode, decode in `get` instead: `value = r.get(key)`, then `return None if value is None else value.decode()`. A `bytes` result is not an error, but the store treats it as a miss and logs a warning on every call, so the cache never helps.
- **`set` maps `ttl` to an expiry.** A finite `ttl` becomes `px` in milliseconds. `None` stores the key with no expiry.
- **One Redis primary is enough.** The cache needs each key's `get` and `set` to be linearizable, which a single primary provides. See [Guarantees and limits](#limits) for replicas.

## In-process cache

`wenchang.index_cache.InMemoryIndexCache` is a thread-safe cache held in one process, for tests and single-process hosts:

```python
from datetime import timedelta

from wenchang.index_cache import IndexCache, InMemoryIndexCache

cache = InMemoryIndexCache()
index_cache = IndexCache(get=cache.get, set=cache.set, ttl=timedelta(minutes=5))
store = MemoryStore(storage, index_cache=index_cache)
```

It drops expired entries only when they are read, so with `ttl=None` it grows without bound. A host that runs several instances needs a shared cache: each instance's in-process cache misses the other instances' writes.

## Writes that bypass the cache

`write_file`, `append_line`, `replace_fact`, and `delete_file` on a store that has the cache invalidate the entity themselves, whether the storage call succeeded or raised. Anything else that changes files in the bucket does not. That includes:

- a seeding job or admin tool,
- another `MemoryStore` built without the cache (such as the seed script in [Setup](setup.md#seed)),
- a direct write through `gcloud` or the GCS API.

The simplest fix is to give those writers the same `IndexCache`. Otherwise, after they finish, call `MemoryStore.invalidate_index(scope, entity_id)` on a store that has the cache:

```python
seed_store = MemoryStore(GcsStorage(bucket))  # no cache, so its writes do not invalidate
# ... seed_store writes under organization/o-hanlin-press/ ...
cached_store = MemoryStore(GcsStorage(bucket), index_cache=index_cache)
cached_store.invalidate_index("organization", "o-hanlin-press")
```

The next `get_memory_index` that includes that entity lists storage again. `invalidate_index` also overwrites the entity's cached listing, so deleted descriptions and aliases do not stay in your cache. A purge calls it once all of its deletes finish.

`invalidate_index` raises `TypeError` for a non-`str` argument and `ValueError` for an invalid scope or entity ID, before touching the cache. It does nothing on a store with no cache. Unlike the store's own invalidation, it does not swallow cache errors: if `set` raises, so does `invalidate_index`, because the caller asked for the invalidation and should know it did not happen.

A writer that does not invalidate leaves the entity stale until its next write through the cached store, or until `ttl` expires.

## When the cache fails

The cache never makes a memory operation fail.

- If `get` raises, or returns something that is not a `str`, the store logs a warning and lists storage as if nothing were cached.
- If `set` raises, the store logs a warning and skips the store or invalidation. Writes still return their normal result.

Warnings go to the `wenchang.core` logger. They name the scope and the exception or result type, never the entity ID or the key. An exception that is not an `Exception` subclass (such as `KeyboardInterrupt`) still propagates. Storage errors while listing propagate as they do without a cache, and nothing is cached for that entity.

A swallowed invalidation failure leaves the entity's old listing in place, and only `ttl` bounds how long it is served. Watch for these warnings.

## Guarantees and limits

The store keeps a random generation token for each entity. A reader records the token before listing storage and tags its cached listing with it. Every write replaces the token after its storage call, so a listing taken before that write is never served afterwards, even if it is stored late. What this does not cover:

- **`ttl=None` means unbounded staleness.** Tokens cannot detect a write that did not invalidate: an out-of-band write, or an invalidation whose `set` failed. With a finite `ttl`, such an entity is stale for at most `ttl`. With `ttl=None`, it stays stale until something invalidates it or your cache evicts the key. Use a finite `ttl` in production.
- **Timed-out writes.** A write that raised `BackendUnavailableError` (for example a timeout) may still commit in GCS after the store has replaced the token. A reader in between can cache the listing from before the commit under the new token. That listing is served until the entity's next write or invalidation, or until `ttl` expires.
- **Deleted metadata can linger, unserved.** A reader that listed before a delete can store its pre-delete listing after the delete overwrote it. Its tag is stale, so it is never served, but it stays in your cache until the entity is indexed again or `ttl` expires. If you have erasure obligations, a finite `ttl` is required, not just recommended.
- **Per-key linearizable `get` and `set`.** A cache where a `get` can miss an earlier `set` to the same key, such as one reading from asynchronous replicas, bounds freshness only by `ttl`. Operations do not need to be atomic across keys.
- **One `key_prefix` per storage root.** Keys do not identify the bucket. Stores over different buckets or roots that share one cache need distinct prefixes, and no prefix may be a string prefix of another (`"a:"` and `"a:b:"` collide, because scope and entity names may contain `:`). End each prefix in a delimiter and keep them distinct. This is not checked at runtime.
- **Large entities make large values.** A cached listing holds one entry per file in the entity.

> **The cache holds memory metadata.** Cached values contain each file's description, aliases, and sources. Keys contain scope names and entity IDs, which are often user IDs. Your cache inherits the same data-handling obligations as the bucket. File content is never cached.

---

HTML version: <https://msiebert.github.io/wenchang/caching.html>
