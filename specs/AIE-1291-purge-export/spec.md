# Feature Specification: Purge and export all memory for an entity

**Linear issue**: AIE-1291 — Delete and export all memory for an entity

**Feature Branch**: `AIE-1291-purge-export` (based on `AIE-1293-index-cache`)

**Created**: 2026-10-30

**Status**: Draft — awaiting spec review

**Input**: There is no way to delete or export everything under a
`{scope}/{entity_id}/` prefix. GDPR deletion and project/org deletion need
it. The library owns the key layout, so the operation belongs in the
library, exposed to operators, not to agents.

## Summary

- `MemoryStore.purge(scope, entity_id) -> int` deletes **every object**
  whose key starts with `build_prefix(scope, entity_id)` (`"{scope}/{entity_id}/"`),
  including `system/` files, keys that are not well-formed memory paths,
  and objects with corrupt metadata. Returns the number of objects it
  deleted.
- `MemoryStore.export(scope, entity_id) -> tuple[ExportedObject, ...]`
  returns every object under the same prefix, raw: `key`, `data` (bytes),
  `metadata` (the stored flat string map), `version`. Nothing is parsed, so
  nothing is dropped or raises for being malformed; the output can be put
  back byte-for-byte with `Storage.put`.
- Both are `MemoryStore` methods only. They are not on `TransportClient`,
  `InProcessClient`, `MemoryTools`, or the MCP adapter (operators call
  `MemoryStore` directly; `InProcessClient.store` exposes it).
- **No storage interface change.** Both are built in `core` from the
  existing `Storage.list_page`, `Storage.get`, and
  `Storage.delete_if_version`, so they run unchanged on `InMemoryStorage`
  and `GcsStorage`. Purge deletes each listed object guarded on the
  version it listed; there is still no unconditional delete in the
  protocol.
- **Concurrent writers.** Purge works in passes: each pass drains the
  prefix listing and deletes each object at its listed version (a
  precondition failure — the object changed or is already gone — is
  skipped; the next pass sees the current state). Purge returns once a pass
  lists nothing. It makes at most `max_passes` passes (keyword-only,
  default `PURGE_MAX_PASSES = 5`); if all of them found objects, a final
  check lists the prefix once more (limit 1) and, if anything is still
  there, raises `PurgeIncompleteError` (so `max_passes=1` with no
  concurrent writer succeeds: one deleting pass, then an empty check).
  Guarantee: when `purge`
  returns, the prefix was observed empty after every delete it made; a
  write that lands after that final listing survives. Callers needing a
  durable erasure stop writers to the entity first (revoke the grant), then
  purge.
- **Index cache (ADR 0040).** Purge calls `invalidate_index(scope,
  entity_id)` once, after all its deletes have finished (success or
  failure), which replaces the entity's token and tombstones its cached
  listing. ADR 0040's documented race remains: a reader that listed before
  the purge can store its pre-purge listing after the tombstone; it is never
  served and persists until re-index or `ttl`. Erasure-bound adopters must
  set a finite `ttl`.
- **Export consistency.** Export is not a snapshot: it lists pages, then
  `get`s each listed key. Each returned object is internally consistent
  (one write's bytes, metadata, and version); an object deleted between
  listing and `get` is omitted; one written after its page was listed may
  be missing. A consistent export requires writers stopped.
- Interaction with AIE-1292 (file cap): none needed; purge removes every
  object under the prefix, freeing all of the entity's slots.

Out of scope: storage protocol changes, batch deletes, agent-facing tools,
transport protocol changes, deleting GCS soft-deleted or noncurrent object
versions (documented only).

## Definitions

- **Entity prefix** `P = build_prefix(scope, entity_id)`, i.e.
  `f"{scope}/{entity_id}/"`. Plain string match, so `user/u1/` never
  matches `user/u10/...`.
- **Object under P**: any storage key starting with `P`, whatever its shape.

## User stories and acceptance criteria

Fixtures: `S` is an `InMemoryStorage`; `M = MemoryStore(S,
list_page_size=2)` (small, to force pagination). Seed data, written with
`S.put` so it can include shapes core would refuse:

- `user/u1/notes/a.md`, `user/u1/notes/b.md`, `user/u1/system/rules.md`
  (valid, well-formed metadata), `user/u1/prefs/c.md` with corrupt metadata
  (e.g. `{"aliases": "not json"}`), `user/u1/odd-key` (not a memory path),
  and `user/u1/notes/bin.md` with non-UTF-8 bytes.
- Neighbours: `user/u10/notes/a.md`, `user/u2/notes/a.md`,
  `project/u1/notes/a.md`, `user-archive/u1/notes/a.md`.

### US1 — Purge

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1.1 | seed data | `M.purge("user", "u1")` | returns 6; `S.list_page("user/u1/", None, 100)` is empty |
| 1.2 | same | after purge | `M.list_prefix("user/u1/")` has no entries and `next_cursor is None`; `M.get_memory_index({"user": "u1"})` equals `MemoryIndex()`; `read_file` of each former well-formed path raises `NotFoundError(FILE_ABSENT)` |
| 1.3 | same | after purge | every neighbour object is unchanged (same data, metadata, version via `S.get`) |
| 1.4 | an entity with no objects | `purge` | returns 0; no exception; `Storage` received no delete call |
| 1.5 | seed data | `purge` twice | 2nd call returns 0 |
| 1.6 | — | `purge` with a non-`str` (real type) `scope` or `entity_id` | `TypeError`, no storage call |
| 1.7 | — | `purge` with a `scope` / `entity_id` failing `is_valid_segment` (`""`, `"a/b"`, `".."`) | `ValueError("invalid scope: ...")` / `ValueError("invalid entity_id: ...")`, no storage call |
| 1.8 | more objects than `list_page_size` (e.g. 7 with page size 2) | `purge` | all deleted; returns 7 |
| 1.9 | a `put` after purge returns, at a former path | `write_file(path, ..., expected_version=None)` | succeeds (create), and the new version differs from every pre-purge version |

### US2 — Purge with concurrent writers

`H` wraps `S` and can run a callback inside `list_page` (after the inner
result is captured) or inside `delete_if_version` (before delegating), and
counts calls.

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 2.1 | `H` hook in the first `delete_if_version` call: `S.put` a new object `user/u1/notes/new.md` | `purge` | returns normally; `new.md` is gone (deleted on a later pass); return value counts it |
| 2.2 | `H` hook in the first `delete_if_version` call for key K: `S.put(K, ...)` (rewrites K, so the guarded delete fails) | `purge` | K is gone afterwards (deleted at its new version on the next pass); no exception |
| 2.3 | `H` hook in the first `delete_if_version` for key K: `S` deletes K first (already gone) | `purge` | no exception; K is absent; K is not counted |
| 2.4 | `H` hook in every `list_page` for `user/u1/` that `S.put`s a fresh key under `user/u1/` | `purge` | raises `PurgeIncompleteError` after exactly `PURGE_MAX_PASSES` passes plus the final check (`PURGE_MAX_PASSES + 1` listings starting at `start_after=None`); its `scope`, `entity_id`, and `passes == PURGE_MAX_PASSES` attributes match; its message names the scope but not the entity ID; with a cache configured, the entity's listing key holds no purged data afterwards |
| 2.4b | hook as 2.4 | `purge(..., max_passes=2)` | raises `PurgeIncompleteError` with `passes == 2` after 3 listings starting at `start_after=None` |
| 2.4c | — | `purge(..., max_passes=x)`: `0`, `-1` | `ValueError("max_passes must be positive")`, no storage call; `True`, `1.0`, `"3"`: `TypeError`, no storage call |
| 2.4d | seed data, no writer | `purge(..., max_passes=1)` | returns 6 (one deleting pass, then an empty check) |
| 2.4e | `H` hook that `S.put`s a fresh key during the 1st pass's `list_page` only | `purge(..., max_passes=1)` | raises `PurgeIncompleteError` (the check finds the fresh key) |
| 2.5 | `H` whose `delete_if_version` raises `BackendUnavailableError` on the 2nd call, with a cache configured and the index cached | `purge` | `BackendUnavailableError` propagates; the 1st delete stands; the entity's cache token was replaced (next index re-lists) |
| 2.6 | `H` hook in the first `delete_if_version` that raises `KeyboardInterrupt`, cache configured and index cached | `purge` | `KeyboardInterrupt` propagates; the entity's cache token was replaced |

### US3 — Index cache

`C` is an `InMemoryIndexCache`; `MC = MemoryStore(S, list_page_size=2,
index_cache=IndexCache(get=C.get, set=C.set))`. Cache keys follow ADR 0040's
documented format.

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 3.1 | `MC`, `get_memory_index({"user": "u1", "project": "u1"})` cached | `MC.purge("user", "u1")`, then index again | `user/u1` contributes no entries; `project/u1` entries unchanged |
| 3.2 | same | after purge | the raw value at `user/u1`'s listing key contains none of the purged paths, descriptions, or aliases |
| 3.3 | `MC` over a cache wrapper that records, in order, every storage delete and every cache `set` | `purge` | both `set`s of `invalidate_index` (token, then listing tombstone) come after the last `delete_if_version` call; exactly one token `set` and one tombstone `set` are made for the entity |
| 3.4 | `MC`, a cache whose `set` raises | `purge` | all objects deleted, then the cache's exception propagates |
| 3.5 | `MC`, a cache whose `set` raises, and `delete_if_version` raising `BackendUnavailableError` | `purge` | `BackendUnavailableError` propagates (not the cache error); a WARNING is logged on `wenchang.core` naming the scope, not the entity ID |
| 3.6 | `M` (no cache) | `purge` | no cache interaction; works as US1 |

### US4 — Export

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 4.1 | seed data | `M.export("user", "u1")` | a `tuple` of 6 `ExportedObject`s in ascending `key` order, one per object under `user/u1/`, including `system/`, the corrupt-metadata, non-UTF-8, and non-path keys |
| 4.2 | same | export | each object's `data`, `metadata` (as a `dict`), and `version` equal `S.get(key)`'s |
| 4.3 | same | export | no neighbour key appears (`user/u10/`, `user/u2/`, `project/u1/`, `user-archive/u1/`) |
| 4.4 | same | export | storage is unchanged (every object, including neighbours, same version) |
| 4.5 | **round trip**: export E; `purge`; `S.put(o.key, o.data, o.metadata)` for each `o` in E; export E2 | compare | `[(o.key, o.data, dict(o.metadata)) for o in E] == ` the same for E2; `read_file` of the well-formed valid files returns the original content and metadata |
| 4.6 | an entity with no objects | export | `()` |
| 4.7 | more objects than `list_page_size` | export | all present, in order |
| 4.8 | `H` hook in `list_page`: delete one listed key before export `get`s it | export | that key is omitted; no exception |
| 4.9 | `H` hook in `list_page`: rewrite one listed key | export | the object carries the new data, metadata, and version together |
| 4.10 | — | export with bad arguments | same `TypeError` / `ValueError` rules as 1.6–1.7, no storage call |
| 4.11 | `ExportedObject` | mutate the `dict` passed as `metadata` after export, or try to assign a field | exported value unchanged; `FrozenInstanceError` |
| 4.12 | `BackendUnavailableError` from `list_page` or `get` | export | propagates |

### US5 — Storage conformance (both implementations)

The shared `StorageConformance` suite gains purge and export cases that
build a `MemoryStore` over the suite's `storage` fixture, so they run on
`InMemoryStorage` (unit) and `GcsStorage` against fake-gcs-server
(integration).

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 5.1 | seed data (as above) in `storage` | purge | US1.1, 1.3 hold |
| 5.2 | same | export, purge, restore with `storage.put`, export | US4.1–4.5 hold |
| 5.3 | more objects than `list_page_size` | purge and export | all objects handled |
| 5.4 | empty entity | purge; export | `0`; `()` |

### US6 — API surface

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 6.1 | — | `TransportClient`, `InProcessClient`, `MemoryTools`, `descriptions()` | none has `purge` or `export`; the transport signature-parity test still passes |
| 6.2 | — | `from wenchang.core import ExportedObject, PurgeIncompleteError` | importable; `PurgeIncompleteError` subclasses `Exception`, not `WenchangError` (operator-only, outside the agent-facing taxonomy) |

## Non-functional

- No new dependencies. No storage protocol change.
- Purge and export cost one `list_page` call per `list_page_size` objects
  per pass; purge adds one `delete_if_version` per object, export one `get`
  per object. Export holds the whole result in memory (bounded by the
  entity's file count × file size; AIE-1292's cap bounds the count).
- GCS soft delete and object versioning: a purge removes live objects only.
  With a bucket soft-delete policy (GCS default 7 days) or object
  versioning enabled, deleted bytes remain recoverable for the retention
  window. Documented in ADR 0038 and the `purge` docstring; adopters with
  erasure obligations configure the bucket accordingly.
- ADR 0038 and ARCHITECTURE.md (core entry, concurrency section) record the
  API, decisions, and guarantees.
