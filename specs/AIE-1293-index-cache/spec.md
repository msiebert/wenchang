# Feature Specification: Optional adopter-injected cache for get_memory_index

**Linear issue**: AIE-1293 — Stop get_memory_index from listing every object on each call

**Feature Branch**: `AIE-1293-index-cache`

**Created**: 2026-10-30

**Status**: Draft — awaiting spec review

**Input**: `get_memory_index` drains a full listing of every granted
`{scope}/{entity_id}/` prefix on every call. Cost grows with file count.

## Human decision (2026-10-30)

The user chose an **adopter-injected, optional cache** over a maintained
summary object: "an optional function that you call to get a cached object
that gives you a None if it's not cached ... an optional function for
updating the cache ... on an object that contains cache options like ttl".

| Alternative | Why rejected |
| ----------- | ------------ |
| Summary object in storage, rewritten on every write | An extra conditional GCS write per mutation, a hot object contended by every writer to an entity, and a new storage format; the adopter cannot choose the backing store |
| Built-in process-local cache only | Wrong for multi-instance hosts (each instance would miss other instances' writes); the adopter's cache (e.g. Redis) is shared |

## Summary

- New module `wenchang.index_cache` with `IndexCache`, a frozen config
  object holding two adopter callables — `get(key) -> str | None` and
  `set(key, value, ttl) -> None` — plus `ttl` and `key_prefix`; and
  `InMemoryIndexCache`, a thread-safe reference implementation.
- `MemoryStore(..., index_cache: IndexCache | None = None)`. With `None`
  (default) behavior is byte-for-byte unchanged: every call lists storage.
- With a cache, `get_memory_index` caches each **entity's drained listing**
  (`{scope}/{entity_id}/`) separately; ordering, the byte cap, and `capped`
  are still computed per call from the per-entity listings, so cached and
  uncached results are equal.
- Every core mutation that attempts a storage write or delete (`write_file`,
  `append_line`, `replace_fact`, `delete_file`) **invalidates** that entity
  before returning or raising. `MemoryStore.invalidate_index(scope,
  entity_id)` is the public hook for any other writer (purge, seeding,
  admin tooling).
- **Race handling — generation tokens.** Each entity has a token key holding
  a random token. Invalidation replaces the token with a fresh random one.
  A reader reads (or creates) the token *before* listing and stores its
  listing tagged with that token; a cached listing is used only when its tag
  equals the current token. A reader that listed before a write and stores
  after the writer's invalidation stores a listing tagged with a stale token,
  which no later reader accepts. Only `get`/`set` are needed — no atomic
  increment or compare-and-set.
- `ttl` bounds staleness from the two things tokens cannot see: a write
  made by something that does not invalidate (a `MemoryStore` without the
  cache, a direct GCS write) and an invalidation that failed.
- Cache failures never fail a memory operation: an exception from `get` or
  `set` is logged as a warning and treated as a miss (reads) or skipped
  (stores, invalidations inside a mutation). `invalidate_index` called
  directly propagates the exception, since its caller asked for it.

Out of scope: the `TransportClient` protocol, `InProcessClient`, tools,
prompts, `mcp`, and storage are unchanged.

## Definitions

- **Entity key** `E = f"{scope}/{entity_id}"`.
- **Token key** `f"{key_prefix}v1:token:{E}"`; **listing key**
  `f"{key_prefix}v1:listing:{E}"`. `key_prefix` defaults to
  `"wenchang:index:"`.
- **Listing a scope** means draining `list_prefix(build_prefix(scope,
  entity_id))` pages, i.e. one or more `Storage.list_page` calls.
- **Mutation attempt**: a call to `Storage.put_if_version` or
  `Storage.delete_if_version` made by a core method.

## User stories and acceptance criteria

Fixtures: `S` is an `InMemoryStorage` wrapped by a counting/hooking
`Storage` wrapper that records `list_page` calls per prefix and can run a
callback inside `list_page` or inside `put_if_version`. `C` is an
`InMemoryIndexCache` with an injectable clock. `M` is
`MemoryStore(S, index_cache=IndexCache(get=C.get, set=C.set, ttl=T))`.
`map2 = {"user": "u1", "project": "p1"}`.

### US1 — Configuration

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1.1 | — | `IndexCache(get=g, set=s)` | `ttl is None`, `key_prefix == "wenchang:index:"` |
| 1.2 | — | `get` or `set` not callable; `ttl` not `None` and not a real `timedelta`; `key_prefix` not a real `str` | `TypeError` |
| 1.3 | — | `ttl <= timedelta(0)` | `ValueError` |
| 1.4 | — | `key_prefix` is a `str` subclass | stored as exact `str` |
| 1.5 | — | `MemoryStore(S, index_cache=x)` where `x` is not `None` and its real type is not `IndexCache` | `TypeError` |
| 1.6 | `MemoryStore(S)` | `index_cache` property | `None`; with a cache, the same `IndexCache` object |

### US2 — No cache: unchanged

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 2.1 | `MemoryStore(S)` with files | `get_memory_index(map2)` twice | each call lists both scopes; results equal |
| 2.2 | `MemoryStore(S)` | `invalidate_index("user", "u1")` | returns `None`, no error |

### US3 — Repeated call does not re-list

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 3.1 | `M`, files in both scopes | `get_memory_index(map2)` twice, no writes between | 2nd call makes zero `list_page` calls; results equal |
| 3.2 | `M`, an entity with no files | two calls | 2nd call makes zero `list_page` calls; result has no entries for it |
| 3.3 | `M` and `MemoryStore(S)` (no cache) over the same files, including `system/` areas, several scopes, a `scope_priority`, an `index_max_bytes` small enough to cap, and a `last_updated` with a non-UTC offset | index from each, and a 2nd (cached) call on `M` | all three `MemoryIndex` values equal; every entry's `last_updated` has the same `utcoffset()` as the uncached one |
| 3.4 | `M` with files under more pages than `list_page_size` | two calls | 2nd call zero `list_page` calls, all entries present |
| 3.5 | `M`, a key under the prefix that is not a well-formed memory path | two calls | it is absent from both results |

### US4 — Writes and deletes are visible on the next call

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 4.1 | `M`, index cached | `write_file` (create) under `user/u1` | next index includes it |
| 4.2 | same | `write_file` (replace), `append_line`, `replace_fact` (each separately) | next index has the new version token and metadata |
| 4.3 | same | `delete_file` | next index omits it |
| 4.4 | same, after any 4.1–4.3 | next index | lists `user/u1/` only; `project/p1/` makes zero `list_page` calls |
| 4.5 | same | a mutation whose `put_if_version` / `delete_if_version` raises (`PreconditionFailedError` → `VersionConflictError`, or `BackendUnavailableError`) | the entity's token was replaced; next index re-lists `user/u1/` |
| 4.6 | same | `replace_fact` succeeds on its 2nd attempt after a concurrent write | next index reflects the committed content's version |
| 4.7 | same | `invalidate_index("user", "u1")` | next index re-lists `user/u1/` only |
| 4.8 | `M` | `invalidate_index` with an invalid scope or entity ID | `ValueError("invalid scope: ...")` / `ValueError("invalid entity_id: ...")`, no cache call; a non-`str` argument raises `TypeError` |

### US5 — Concurrency

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 5.1 | `M`; a hook inside `list_page` for `user/u1/` that, on the first call only, commits a write to `user/u1/` through `M` (the writer finishes, including invalidation, before the listing returns) | `get_memory_index(map2)` (the reader stores its pre-write listing), then a 2nd call | 2nd call re-lists `user/u1/` and includes the write |
| 5.2 | `M`; hook as 5.1 but the write is a `delete_file` | same | 2nd call omits the deleted file |
| 5.3 | `M`; two writer threads each doing N `append_line` / `replace_fact` calls to the same entity (retrying on `VersionConflictError`), and a reader thread calling `get_memory_index` in a loop, started together via a barrier | all threads join | a final `get_memory_index` on `M` equals `get_memory_index` on `MemoryStore(S)` (no cache) |
| 5.4 | Two stores `M1`, `M2` over the same `S` and the same `C` (two hosts) | `M2` caches the index; `M1` writes to `user/u1` | `M2`'s next index includes the write |
| 5.5 | Two readers, both seeing no token, race to create one | both finish | final index correct; any listing whose tag is not the surviving token is a miss on the next call |

### US6 — TTL and out-of-band writers

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 6.1 | `M` with `ttl=T`, index cached | a write through `MemoryStore(S)` (no cache), then index before `T` elapses | stale: write absent, zero `list_page` calls |
| 6.2 | same | clock advanced past `T`, index | write present |
| 6.3 | same as 6.1 | `M.invalidate_index("user", "u1")`, then index | write present |
| 6.4 | `M` | every `set` call | receives `ttl` exactly as configured (`None` passes `None`) |

### US7 — Cache failures and bad values

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 7.1 | cache whose `get` raises | `get_memory_index` | correct result from storage; a WARNING is logged on logger `wenchang.core` |
| 7.2 | cache whose `set` raises | `get_memory_index`; then a `write_file` | both return normally with correct results; warnings logged |
| 7.3 | cache whose `set` raises | `invalidate_index` | the cache's exception propagates |
| 7.4 | listing key holds a value that is not a valid encoding (garbage, wrong JSON shape, wrong field types) | `get_memory_index` | treated as a miss: storage is listed and the result is correct |
| 7.5 | stored metadata on a file is corrupt | `get_memory_index` twice | each call raises `MetadataFormatError`; nothing is stored under the listing key |
| 7.6 | a `BaseException` that is not an `Exception` from `get` | `get_memory_index` | propagates |
| 7.7 | `get_memory_index` with an invalid `scope_map` | call | the same `TypeError`/`ValueError` as today, with no cache call |

### US8 — Reference implementation and conformance

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 8.1 | `InMemoryIndexCache(clock=f)` | `set(k, v, None)`; `get(k)` | `v`; never expires |
| 8.2 | same | `set(k, v, T)`; advance clock to exactly `T` later | `get(k)` returns `None` (expiry is at `now >= set_time + T`) |
| 8.3 | same | `get` of a missing key | `None` |
| 8.4 | — | `TransportConformance` run against `InProcessClient(M)` | passes with no skips |

## Non-functional

- Cache key and value are `str`; the value encoding is versioned (`v1` in the
  key) and opaque to adopters.
- The cache must offer single-key read-your-writes consistency
  (linearizable `get`/`set` per key, as a single Redis primary does). A cache
  with weaker consistency weakens the guarantee to the `ttl` bound. Stated in
  the `IndexCache` docstring and the ADR.
- Every `MemoryStore` writing a storage root must share the cache config,
  or call `invalidate_index`, or accept `ttl` staleness. Stated in the ADR.
- ADR 0040 records the decision; ARCHITECTURE.md updated.
