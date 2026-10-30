# 0040. Optional adopter-injected index cache

Date: 2026-10-30

## Status

Accepted

## Context

`get_memory_index` drains a full listing of every granted
`{scope}/{entity_id}/` prefix on every call ([ADR
0020](0020-memory-index-and-in-process-client.md)). Each call costs one or
more `Storage.list_page` round trips per scope, and the cost grows with file
count. Hosts call it at the start of every session.

On 2026-10-30 (AIE-1293) the human chose an adopter-injected, optional cache:
a `get` that returns `None` when nothing is cached, a `set` that updates it,
and an options object carrying `ttl`. The whole cache is optional. When one
is given, both `get` and `set` are required, because `set` is how the library
invalidates; a read-only cache cannot be correct.

## Decision

1. **Configuration.** `wenchang.index_cache.IndexCache(get, set, ttl=None,
   key_prefix=DEFAULT_KEY_PREFIX)` is a frozen value. `get(key) -> str |
   None` returns the value last set for `key`, or `None` if absent or
   expired. `set(key, value, ttl) -> None` stores it, expiring `ttl` from now
   (`None`: never). `DEFAULT_KEY_PREFIX` is `"wenchang:index:"`.
   `InMemoryIndexCache` is a thread-safe reference implementation for tests
   and single-process hosts; with `ttl=None` it grows without bound.
   `MemoryStore(..., index_cache=None)` accepts one, exposes it as the
   `index_cache` property, and behaves exactly as before without one. The
   module imports nothing from `wenchang`.
2. **Cache each entity's listing, not the finished index.** With a cache,
   `get_memory_index` caches each `(scope, entity_id)`'s drained listing
   separately. Ordering, the byte cap, and `capped` are still computed per
   call, so a cached result equals an uncached one, and a write invalidates
   one entity rather than every scope map that contains it.
3. **Generation tokens.** Each entity has a token key holding a random
   token and a listing key holding the listing tagged with a token. A reader
   reads the token (or creates and sets one) *before* listing, and stores
   its listing tagged with that token. A cached listing is used only if its
   tag equals the current token. Invalidation sets a fresh random token.
   Only per-key `get` and `set` are needed, with no increment or
   compare-and-set.

   Why this is safe: a writer replaces the token only after its storage call.
   If a listing's tag still equals the current token, no write has completed
   its invalidation since before that listing began, and every write whose
   invalidation completed earlier had also committed earlier, so it is in
   the listing. A reader that listed before a write and stores afterwards
   tags its listing with a token the writer has already replaced, so the
   stale listing is never served. Two concurrent `set`s on the token key
   only replace one fresh random token with another. The lost write costs at
   most an extra miss.

   Known hole: the argument assumes a write has committed or never will by
   the time its call returns or raises. A write that raised
   `BackendUnavailableError` (for example a timeout) can still commit
   server-side after the `finally` in decision 4 has replaced the token. A
   reader can then cache a pre-commit listing under the fresh token, and it
   is served until the entity's next write or invalidation, or until `ttl`
   expires (decision 10).
4. **Invalidate after every storage mutation attempt.** `write_file`,
   `append_line`, `replace_fact` (on every attempt), and `delete_file`
   replace the entity's token in a `finally` around each `put_if_version`
   and `delete_if_version`. Invalidation runs whether the storage call
   returned or raised, because a `BackendUnavailableError` can hide a write
   that landed. It never replaces or masks the method's own result or
   exception. It cannot cover a write that commits only after the call
   raised; see the known hole in decision 3.
5. **Tombstones on delete and explicit invalidation only.** `delete_file`
   and `MemoryStore.invalidate_index(scope, entity_id)` also overwrite the
   listing key with a tombstone after replacing the token, so deleted
   descriptions and aliases do not stay in the adopter's cache. The other
   mutations replace only the token: their old listing is never served, and
   the next index call for the entity overwrites it.
6. **Public `invalidate_index`.** It validates its arguments (`TypeError`
   for a non-`str`, `ValueError("invalid scope: ...")` or
   `ValueError("invalid entity_id: ...")`) before any cache call and does
   nothing without a cache. It is the hook for writers that bypass this
   store's cache, such as seeding, admin tooling, a `MemoryStore` without the
   cache, or a direct GCS write. Those writers must call it or accept
   staleness. A purge (AIE-1291) must call it after all its deletes finish.
7. **Keys and values.** For `E = f"{scope}/{entity_id}"`, the token key is
   `f"{key_prefix}v1:token:{E}"` and the listing key is
   `f"{key_prefix}v1:listing:{E}"`. The listing value is compact JSON
   holding the tag and, per entry, path, version, description, aliases,
   sorted sources, and `last_updated` in ISO form with its stored offset.
   The value is opaque to adopters; `v1` in the key lets the encoding
   change. A value that does not decode, has the wrong shape or types, has
   a naive `last_updated`, has a path that is invalid, outside that entity's
   prefix, or repeated, or is the tombstone is a miss. Keys carry no storage
   identity, so stores over different storage roots that share one cache
   need distinct `key_prefix`es. Because scope and entity segments may
   contain `":"`, those prefixes must also be prefix-free: no configured
   `key_prefix` may be a string prefix of another sharing the cache. Ending
   each in a delimiter and keeping them distinct satisfies this. It is not
   validated at runtime.
8. **Consistency requirement.** `get` and `set` must be linearizable per key,
   as a single Redis primary is. They need not be atomic across keys. A
   cache weaker than per-key linearizable, such as one reading from
   asynchronous replicas, bounds freshness only by `ttl`.
9. **Failure policy.** In `get_memory_index` and the mutations, an
   `Exception` from `get` or `set` is logged as a WARNING on logger
   `wenchang.core` and treated as a miss, or the store or invalidation is
   skipped. A `get` result whose real type is not `str` (for example `bytes`
   from redis-py) is also a logged miss. Warnings name the scope and the
   exception or result type, never the entity ID or key. A `BaseException`
   that is not an `Exception` propagates. `invalidate_index` called directly
   propagates the cache's exception, because its caller asked for the
   invalidation. A `MetadataFormatError` or `BackendUnavailableError` during
   listing propagates, and nothing is stored for that entity.
10. **`ttl`.** It is passed unchanged to every `set`. Tokens cannot detect a
    write by something that does not invalidate, an invalidation that
    failed and was swallowed, a write that commits after its call raised
    `BackendUnavailableError` (decision 3), or staleness from a cache
    weaker than per-key linearizable (decision 8). A finite `ttl` bounds
    staleness from all of these. With `ttl=None` staleness is
    **unbounded**: the entity stays stale until something invalidates it or
    the cache evicts the key. A finite `ttl` is recommended in production
    and **required** for adopters with erasure obligations (see Privacy).

### Constitution principle V

Storage is still reached only through the `Storage` interface. The cache is
a derived copy of listing metadata, not a second store: it never holds file
content, is never written ahead of storage, and is not a source of truth.
Every miss, decode failure, or cache error falls back to listing storage.

### Privacy

Cached values hold descriptions, aliases, and sources. Keys hold scope names
and entity IDs. The adopter's cache inherits the memory store's
data-handling obligations. Logs never name entity IDs or keys.

The deletion guarantee is narrow. `delete_file` and `invalidate_index`
tombstone the listing, but a reader that listed before the delete can store
its pre-delete listing after the tombstone. Its tag is stale, so it is never
served, but it stays in the cache until the entity is indexed again or `ttl`
expires. The race is documented, not closed. A finite `ttl` is therefore
required for adopters with erasure obligations, and a purge must call
`invalidate_index` after all its deletes finish.

### Rejected alternatives

- **A summary object in storage, rewritten on every write.** It costs an
  extra conditional GCS write per mutation, creates a hot object contended
  by every writer to an entity, and adds a storage format. The adopter
  cannot choose where it lives.
- **A built-in process-local cache.** On multi-instance hosts each instance
  misses the others' writes. An adopter's shared cache, such as Redis, does
  not.
- **Delete-on-write without tokens.** A reader that listed before a write
  and stores after the writer's delete leaves a stale listing that is
  served. Tokens close this race with only `get` and `set`.
- **Caching the finished `MemoryIndex` per scope map.** A write would have to
  invalidate every scope map containing the entity, and changes to the cap
  or priority could serve a stale shape.
- **A tombstone on every mutation.** It costs an extra `set` per write for
  no correctness gain: the old listing is never served and is soon
  overwritten. Deletes and purges are where lingering metadata matters.

## Consequences

- A host with a cache lists each entity once until something writes to it.
  A hit costs two cache `get`s per entity instead of a full storage listing.
- `MemoryStore`'s seven core signatures are unchanged, so the
  `TransportClient` protocol, `InProcessClient`, tools, prompts, `mcp`, and
  storage are unchanged. The transport conformance suite passes against a
  cached store.
- Every writer to a storage root must share the cache config, call
  `invalidate_index`, or accept staleness up to `ttl`, or with no bound when
  `ttl=None`. The same bound covers a timed-out write that commits late.
- Stores sharing one cache need distinct, prefix-free `key_prefix`es; this
  is the adopter's responsibility and is not validated.
- Pre-delete metadata can stay, unserved, in the adopter's cache until
  re-index or `ttl`. Adopters with erasure obligations must set a finite
  `ttl`.
- Large entities produce large cache values, bounded by file count times
  metadata size.
