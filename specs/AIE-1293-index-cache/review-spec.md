# Spec Review: AIE-1293 — Optional adopter-injected cache for get_memory_index

## What & why

`get_memory_index` lists every file in every granted entity on every call.
Adopters can now pass `MemoryStore(..., index_cache=IndexCache(get=..., set=..., ttl=...))`
backed by any key-value store (Redis, memcache, the bundled in-memory one).
Each entity's listing is cached; the library invalidates it on every write
and delete. Without a cache, nothing changes.

## Acceptance criteria (condensed; full table in spec.md)

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | no cache | index twice | lists every call (unchanged) |
| 2 | cache, no writes | index twice | 2nd call: zero `list_page` calls, equal result |
| 3 | cached index | write / append / replace / delete, or a mutation whose storage call raised | next index reflects it; only that entity re-lists |
| 4 | reader mid-listing when a writer commits; or a reader runs between a writer's storage call starting and its invalidation | reader stores its stale listing | next index still reflects the write (deterministic hooks) |
| 4b | only the token or only the listing key evicted / expired; racing token creation | index | re-lists when needed, never serves stale |
| 4c | two storage roots, one cache, distinct `key_prefix` | write in each | isolated |
| 5 | two writer threads + a reader on one entity | join | final cached index == uncached index |
| 6 | two stores sharing storage + cache | one writes | the other's next index sees it |
| 7 | write by a store without the cache | before / after `ttl` | stale / fresh; `invalidate_index` fixes immediately |
| 8 | cache `get`/`set` raises, or `get` returns `bytes` | index or write | succeeds from storage, warning logged (scope only, no entity ID) |
| 9 | garbage, foreign-entity, invalid, or duplicate paths in a cached value | index | miss, re-list |
| 9b | `invalidate_index` or `delete_file` | raw cache value | old entries tombstoned |
| 10 | `TransportConformance` on a cached store | run | passes |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | --------------------- | --- |
| Adopter callables `get`/`set` + `ttl` + `key_prefix` on a frozen `IndexCache` | Storage summary object; built-in local cache | Human decision; shared across instances; no extra GCS write per mutation |
| Cache per entity's raw listing; order and cap computed per call | Cache the finished `MemoryIndex` per scope_map | A write invalidates one key, not every scope_map containing it; config changes (cap, priority) never serve stale shapes |
| Generation token per entity, replaced on each write; listing tagged with the token read before listing | Delete-on-write only; CAS/atomic-incr primitives | Delete-on-write loses the read/invalidate race; tokens fix it with only `get`/`set` |
| Invalidate in `finally` after every storage mutation attempt | Only on success | A `BackendUnavailableError` may hide a landed write |
| Cache errors logged and swallowed inside index and mutations; public `invalidate_index` propagates | Propagate everywhere | A committed write must not report failure because the cache is down; ttl bounds the staleness |
| `str` keys and values, JSON value with `v1` in key | Pickle / adopter-chosen shape | Serializable to any store; format can evolve |
| `invalidate_index` and `delete_file` tombstone the listing after replacing the token; other mutations only replace the token | Tombstone on every mutation; never tombstone | Deleting and purging are privacy actions, worth one extra `set`; for ordinary writes the old value is never served and is soon overwritten |

## Files/modules to be touched

- New `src/wenchang/index_cache.py`; `src/wenchang/core.py`.
- New tests: `tests/test_index_cache.py`, `tests/test_core_index_cache.py`, cached conformance run.
- `docs/adr/0040-index-cache.md`, `ARCHITECTURE.md`.

## Open questions / assumptions

Settled by the orchestrator (2026-10-30): public `invalidate_index` (the
AIE-1291 hook); swallow-and-log on cache errors; `ttl` optional, default
`None`; per-key linearizability documented as a requirement.

- Writers that bypass the cache (seeding job, another `MemoryStore` without
  it, direct GCS) are stale up to `ttl` unless they call `invalidate_index`.

## Risks

- `ttl=None` plus a swallowed invalidation failure or an out-of-band writer
  leaves an entity stale with no bound. Docs recommend a finite `ttl`.
- A cache without per-key linearizability (async replicas) weakens freshness to the ttl bound.
- Cached values hold descriptions and aliases, and keys hold entity IDs; the
  adopter's cache inherits the store's data-handling obligations (ADR 0040).
- Remaining race: a reader that listed before a delete or purge can store
  pre-delete metadata after the tombstone. Never served, but it persists
  until the entity is re-indexed or `ttl` expires. A finite `ttl` is
  required for adopters with erasure obligations; a purge must call
  `invalidate_index` after all its deletes finish.
- Large entities produce large cache values (bounded by file count × metadata size).
- Two Redis round-trips per entity on a hit; still far cheaper than a GCS list.
