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

The whole `IndexCache` is optional (`index_cache=None` is the default). When
given, both `get` and `set` are required: `set` is how the library
invalidates, so a read-only cache cannot be correct.

Accepted defaults (orchestrator, 2026-10-30): public `invalidate_index`;
cache errors logged and swallowed inside index and mutation paths; `ttl`
optional, default `None`; per-key linearizability documented as a
requirement.

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
  admin tooling). `invalidate_index` and `delete_file` also overwrite the
  entity's listing key with a tombstone (using only `set`, after replacing
  the token), so deleted or purged descriptions and aliases do not linger
  in the adopter's cache. `write_file`, `append_line`, and `replace_fact`
  replace only the token; the listing value they leave behind is never
  served and is overwritten by the next index call for that entity.
- **Remaining race (documented, not closed):** a reader that listed before a
  delete or purge can store its pre-delete listing after the tombstone. It
  is never served (its tag is stale), but it persists in the cache until
  the entity is indexed again or `ttl` expires. Adopters with erasure
  obligations must set a finite `ttl`, and a purge must call
  `invalidate_index` after all its deletes finish.
- **Race handling — generation tokens.** Each entity has a token key holding
  a random token. Invalidation replaces the token with a fresh random one.
  A reader reads (or creates) the token *before* listing and stores its
  listing tagged with that token; a cached listing is used only when its tag
  equals the current token. A reader that listed before a write and stores
  after the writer's invalidation stores a listing tagged with a stale token,
  which no later reader accepts. Only `get`/`set` are needed — no atomic
  increment or compare-and-set.
- Tokens cannot see two things: a write made by something that does not
  invalidate (a `MemoryStore` without the cache, a direct GCS write) and an
  invalidation that failed. With a finite `ttl`, staleness from either is
  bounded by `ttl`. With `ttl=None` it is **unbounded**: the entity stays
  stale until something else invalidates it or the adopter's cache evicts
  the key. A finite `ttl` is recommended in production.
- Cache failures never fail a memory operation: an exception from `get` or
  `set`, or a non-`str` result from `get` (e.g. `bytes` from redis-py), is
  logged as a WARNING and treated as a miss (reads) or skipped (stores,
  invalidations inside a mutation). `invalidate_index` called directly
  propagates the exception, since its caller asked for it. Warnings name the
  scope and the exception or result type, never the entity ID or the key.
- Keys carry no storage identity: two `MemoryStore`s over different storage
  roots sharing one cache must use distinct `key_prefix` values.

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
`InMemoryIndexCache` with an injectable clock. `W` is a test-local cache
wrapper over `C` that can run a callback inside `get` or `set` for a given
key, delete a single key, and return a scripted value from `get`. `M` is
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
| 3.3 | `M` and `MemoryStore(S)` (no cache) over the same files, including `system/` areas, several scopes, a `scope_priority`, an `index_max_bytes` small enough to cap, and a `last_updated` with a non-UTC offset (seeded directly through `S.put` with a metadata map whose `last-updated` carries e.g. `+05:30`) | index from each, and a 2nd (cached) call on `M` | all three `MemoryIndex` values equal; every entry's `last_updated` has the same `utcoffset()` as the uncached one |
| 3.4 | `M` with files under more pages than `list_page_size` | two calls | 2nd call zero `list_page` calls, all entries present |
| 3.5 | `M`, a key under the prefix that is not a well-formed memory path | two calls | it is absent from both results |

### US4 — Writes and deletes are visible on the next call

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 4.1 | `M`, index cached | `write_file` (create) under `user/u1` | next index includes it |
| 4.2 | same | `write_file` (replace), `append_line`, `replace_fact` (each separately) | next index has the new version token and metadata |
| 4.3 | same | `delete_file` | the raw listing value no longer contains the deleted file's path, description, or aliases; next index omits it |
| 4.4 | same, after any 4.1–4.3 | next index | lists `user/u1/` only; `project/p1/` makes zero `list_page` calls |
| 4.5 | same | a mutation whose `put_if_version` / `delete_if_version` raises (`PreconditionFailedError` → `VersionConflictError`, or `BackendUnavailableError`) | the entity's token was replaced; next index re-lists `user/u1/` |
| 4.6 | same | `replace_fact` succeeds on its 2nd attempt after a concurrent write | next index reflects the committed content's version |
| 4.7 | same | `invalidate_index("user", "u1")` | the raw value at `user/u1`'s listing key no longer contains any of the old entries' paths, descriptions, or aliases; next index re-lists `user/u1/` only |
| 4.8 | `M` | `invalidate_index` with an invalid scope or entity ID | `ValueError("invalid scope: ...")` / `ValueError("invalid entity_id: ...")`, no cache call; a non-`str` argument raises `TypeError` |

### US5 — Concurrency

The deterministic cases (5.1, 5.2, 5.4–5.9) carry the correctness proof:
each forces one interleaving with a hook. 5.3 is a threaded smoke test.

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 5.1 | `M`; a hook in the `S` wrapper's `list_page` for `user/u1/` that, on the first call only, runs **after** the inner `list_page` result is captured and before it is returned, and commits a `write_file` to `user/u1/` through `M` (the writer finishes, including invalidation, before the listing returns) | `get_memory_index(map2)`, then a 2nd call | the 1st result lacks the write (so a pre-write listing was stored); the 2nd call re-lists `user/u1/` and includes the write |
| 5.2 | `M`; hook as 5.1 but the write is a `delete_file` of an existing file | same | 1st result still contains the file; 2nd call re-lists and omits it |
| 5.3 | `M`; two writer threads each doing N `append_line` / `replace_fact` calls to the same entity (retrying on `VersionConflictError`), and a reader thread calling `get_memory_index` in a loop, started together via a barrier | all threads join | a final `get_memory_index` on `M` equals `get_memory_index` on `MemoryStore(S)` (no cache) |
| 5.4 | Two stores `M1`, `M2` over the same `S` and the same `C` (two hosts) | `M2` caches the index; `M1` writes to `user/u1` | `M2`'s next index includes the write |
| 5.5 | `M` over `W`, empty cache; a hook in `W.set` on `user/u1`'s **token key**, first call only, that runs **before delegating** and performs a second full `get_memory_index(map2)` on `M` (two readers both saw no token; the inner one sets token `t_in`, lists, and stores a listing tagged `t_in`; the outer then sets `t_out`, lists, and stores tagged `t_out`) | outer call returns; then a 3rd call | outer and inner results are correct; the 3rd call makes zero `list_page` calls for `user/u1/` and is correct |
| 5.5b | as 5.5, with `W` recording every value `set` on the listing key; after the outer call, the first recorded listing value (the inner reader's, tagged `t_in`) is written back to the listing key, modelling the inner reader's store landing last | 3rd call; 4th call | 3rd call re-lists `user/u1/` (tag `t_in` != token `t_out`) and is correct; 4th makes zero `list_page` calls |
| 5.6 | `M`; a hook in the `S` wrapper's `put_if_version` for `user/u1/...`, first call only, that runs a full `get_memory_index(map2)` on `M` **before** delegating to the real put | `write_file` (create, and separately replace) returns; then index | the next index includes the write (proves invalidation runs after the storage call, not before) |
| 5.7 | same, hook in `delete_if_version` | `delete_file` returns; then index | the next index omits the file |
| 5.8 | `M` over `W`, index cached | only the token key of `user/u1` is deleted; index | re-lists `user/u1/`; result correct |
| 5.9 | same | only the listing key is deleted; index | re-lists `user/u1/`; the token key's value is unchanged; a further call makes zero `list_page` calls |
| 5.10 | `M` over `C` with `ttl=T`; the token key was set at `t0`, the listing key at `t0 + d` (`0 < d < T`, by advancing the clock inside a `list_page` hook) | clock at `t0 + T` (token expired, listing not) ; index | re-lists `user/u1/`; result correct |
| 5.11 | Two stores over different `InMemoryStorage` objects sharing one `C`, with `key_prefix`es `"a:"` and `"b:"`, same scope map, different files | each caches, then each writes | each index only ever shows its own storage's files |

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
| 7.1 | cache whose `get` raises | `get_memory_index` | correct result from storage; a WARNING is logged on logger `wenchang.core` naming the scope; no log record contains the entity ID |
| 7.1b | `W` whose `get` returns `bytes` (a valid encoding as bytes) for both keys | `get_memory_index` | WARNING logged; treated as a miss; storage listed; result correct |
| 7.2 | cache whose `set` raises | `get_memory_index`; then a `write_file` | both return normally with correct results; warnings logged |
| 7.3 | cache whose `set` raises | `invalidate_index` | the cache's exception propagates |
| 7.4 | listing key holds, under the current token, a value that is not a valid encoding: garbage; wrong JSON shape; wrong field types; a naive `last_updated`; an entry whose `path` fails `is_valid_path`; an entry whose path is not under `build_prefix(scope, entity_id)` of that entity (e.g. another entity's file); two entries with the same path; the tombstone | `get_memory_index` (one case each) | treated as a miss: storage is listed and the result is correct |
| 7.5 | stored metadata on a file is corrupt | `get_memory_index` twice | each call raises `MetadataFormatError`; nothing is stored under the listing key |
| 7.6 | a `BaseException` that is not an `Exception` from `get` | `get_memory_index` | propagates |
| 7.7 | `get_memory_index` with an invalid `scope_map` | call | the same `TypeError`/`ValueError` as today, with no cache call |

### US8 — Reference implementation and conformance

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 8.1 | `InMemoryIndexCache(clock=f)` | `set(k, v, None)`; `get(k)` | `v`; never expires |
| 8.2 | same | `set(k, v, T)`; advance clock to exactly `T` later | `get(k)` returns `None` (expiry is at `now >= set_time + T`) |
| 8.3 | same | `get` of a missing key | `None` |
| 8.3b | — | `InMemoryIndexCache` docstring | states that with `ttl=None` it grows without bound (documentation; checked in review, not by a test) |
| 8.4 | — | `TransportConformance` run against `InProcessClient(M)` | passes with no skips |

## Non-functional

- Cache key and value are `str`; the value encoding is versioned (`v1` in the
  key) and opaque to adopters.
- The cache must offer single-key read-your-writes consistency
  (linearizable `get`/`set` per key, as a single Redis primary does). A cache
  with weaker consistency weakens the guarantee to the `ttl` bound. Stated in
  the `IndexCache` docstring and the ADR.
- Every `MemoryStore` writing a storage root must share the cache config,
  or call `invalidate_index`, or accept staleness. Stated in the ADR.
- **`ttl=None` with a swallowed invalidation failure or an out-of-band
  writer leaves an entity stale with no bound.** Stated in the `IndexCache`
  docstring and ADR 0040, both recommending a finite `ttl` in production.
- Distinct storage roots sharing one cache need distinct `key_prefix`es.
  Stated in the `IndexCache` docstring and ADR 0040; tested by 5.11.
- ADR 0040 records the decision, including: why a derived,
  non-source-of-truth cache is compatible with constitution principle V
  (storage is reached only through the `Storage` interface; the cache holds
  only a copy of listing metadata, never file content, is never written
  ahead of storage, and every cache miss or failure falls back to storage);
  and privacy (cached values hold descriptions, aliases, and sources; keys
  contain scope names and entity IDs; the adopter's cache inherits the
  memory store's data-handling obligations). The privacy guarantee is
  narrow: `delete_file` and `invalidate_index` tombstone the listing, but a
  reader that listed before them can store pre-delete metadata afterwards;
  that value is never served yet persists until the entity is re-indexed or
  `ttl` expires. A finite `ttl` is **required** for adopters with erasure
  obligations, and a purge must call `invalidate_index` after all its
  deletes finish. The same statement goes in the `invalidate_index`
  docstring. ARCHITECTURE.md updated.
