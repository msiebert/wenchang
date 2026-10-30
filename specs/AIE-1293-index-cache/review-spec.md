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
| 4 | reader mid-listing when a writer commits | reader stores its stale listing | next index still reflects the write |
| 5 | two writer threads + a reader on one entity | join | final cached index == uncached index |
| 6 | two stores sharing storage + cache | one writes | the other's next index sees it |
| 7 | write by a store without the cache | before / after `ttl` | stale / fresh; `invalidate_index` fixes immediately |
| 8 | cache `get`/`set` raises | index or write | succeeds from storage, warning logged |
| 9 | garbage in cache | index | miss, re-list |
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

## Files/modules to be touched

- New `src/wenchang/index_cache.py`; `src/wenchang/core.py`.
- New tests: `tests/test_index_cache.py`, `tests/test_core_index_cache.py`, cached conformance run.
- `docs/adr/0040-index-cache.md`, `ARCHITECTURE.md`.

## Open questions / assumptions

- Public `MemoryStore.invalidate_index(scope, entity_id)` (also the hook for
  AIE-1291) — assumed acceptable as a public addition.
- Swallow-and-log on cache errors (vs. raising). Assumed; ttl is the backstop.
- `ttl` defaults to `None` (no expiry). Alternative: require a ttl. Assumed
  optional, with the ADR recommending one.
- Writers that bypass the cache (seeding job, another `MemoryStore` without
  it, direct GCS) are stale up to `ttl` unless they call `invalidate_index`.

## Risks

- A cache without per-key linearizability (async replicas) weakens freshness to the ttl bound.
- Large entities produce large cache values (bounded by file count × metadata size).
- Two Redis round-trips per entity on a hit; still far cheaper than a GCS list.
