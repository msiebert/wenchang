# Feature Specification: Purge and export all memory for an entity

**Linear issue**: AIE-1291 — Delete and export all memory for an entity

**Feature Branch**: `AIE-1291-purge-export` (based on `AIE-1293-index-cache`)

**Created**: 2026-10-30

**Status**: Revised after spec review (round 1)

**Input**: There is no way to delete or export everything under a
`{scope}/{entity_id}/` prefix. GDPR deletion and project/org deletion need
it. The library owns the key layout, so the operation belongs in the
library, exposed to operators, not to agents.

## Orchestrator decisions (2026-10-30)

- No storage interface change.
- The method is named `export`.
- `PURGE_MAX_PASSES = 5` is a public default; `purge` also takes a
  keyword-only `max_passes`.

## Summary

- `MemoryStore.purge(scope, entity_id, *, max_passes=PURGE_MAX_PASSES) ->
  int` deletes **every object** whose key starts with
  `build_prefix(scope, entity_id)` (`"{scope}/{entity_id}/"`), including
  `system/` files, keys that are not well-formed memory paths, and objects
  with corrupt metadata. Returns the number of successful deletes it made.
- `MemoryStore.export(scope, entity_id) -> tuple[ExportedObject, ...]`
  returns every object under the same prefix, raw: `key`, `data` (bytes),
  `metadata` (the stored flat string map, read-only), `version`. Nothing is
  parsed, so nothing is dropped or raises for being malformed; the output
  can be put back byte-for-byte with `Storage.put`.
- Both are `MemoryStore` methods only. They are not on `TransportClient`,
  `InProcessClient`, `MemoryTools`, or the MCP adapter (operators call
  `MemoryStore` directly; `InProcessClient.store` exposes it).
- **No storage interface change.** Both are built in `core` from the
  existing `Storage.list_page`, `Storage.get`, and
  `Storage.delete_if_version`, so they run unchanged on `InMemoryStorage`
  and `GcsStorage`. Purge deletes each listed object guarded on the
  version it listed; the protocol still has no unconditional delete.
- **Passes and concurrent writers.** A pass drains the prefix listing page
  by page (`list_page_size`), deleting each listed object at its listed
  version; a precondition failure (the object changed or is already gone)
  is skipped and left for the next pass. A pass that lists nothing ends the
  purge successfully. Purge makes at most `max_passes` passes; if every one
  found objects, a final check lists the prefix once more (limit 1) and, if
  anything is there, raises `PurgeIncompleteError(scope, entity_id,
  passes=max_passes)`. So `max_passes=1` with no concurrent writer
  succeeds: one deleting pass, then an empty check.
- **What `max_passes` bounds.** It bounds re-listing only, i.e. how many
  times purge starts over from the beginning of the prefix. It does not
  bound a single pass: a writer that keeps adding keys that sort after the
  pass's cursor faster than purge deletes them keeps that pass running
  without limit. Stated in the spec, ADR 0038, and the `purge` docstring.
- **Guarantee.** When `purge` returns, the prefix was observed empty after
  every delete it made; a write that lands after that last listing
  survives. A durable erasure requires stopping writers to the entity first
  (revoke the grant), then purging.
- **Count.** The return value counts successful `delete_if_version` calls.
  A delete that landed in GCS but whose response was lost (raised as
  `BackendUnavailableError`, or retried by the client and then seen as a
  precondition failure) is not counted. Re-running purge is always safe.
- **Index cache (ADR 0040).** Purge calls `invalidate_index(scope,
  entity_id)` exactly once, after its last storage call, on every exit
  path. On success, an exception from the cache propagates (the delete
  count is then lost; re-running purge returns 0 and invalidates again). If
  purge itself failed (including `PurgeIncompleteError` and
  `BaseException`s such as `KeyboardInterrupt`), a cache exception is
  logged as a WARNING on `wenchang.core` (scope and exception type, never
  the entity ID) and the original failure re-raised. On interrupt, purge
  still calls the adopter's cache, which may block. ADR 0040's documented
  race is unchanged: a reader that listed before the purge can store its
  pre-purge listing after the tombstone; it is never served and persists
  until re-index or `ttl`. Erasure-bound adopters must set a finite `ttl`.
- **Export consistency.** Export is not a snapshot: it lists pages, then
  `get`s each listed key. Each returned object is internally consistent
  (one write's bytes, metadata, and version); an object deleted between
  listing and `get` is omitted; one written after its page was listed may
  be missing. A consistent export requires writers stopped.
- **Cost and memory.** Purge and export make one `list_page` per
  `list_page_size` objects per pass, plus N sequential `delete_if_version`
  (purge) or `get` (export) calls for N objects, roughly N × round-trip
  time on GCS. Export holds every object's bytes in memory at once, and
  the library does not bound that: `system/` files and malformed keys are
  not counted by AIE-1292's file cap, the cap is soft and may be disabled,
  and direct storage writes bypass both it and `max_file_bytes`. Stated in
  ADR 0038 and both docstrings.
- **AIE-1292 (file cap):** no interaction needed; purge removes every
  object under the prefix, freeing all of the entity's slots.
- **Error taxonomy deviation.** `PurgeIncompleteError` subclasses
  `Exception`, not `WenchangError`: it is operator-only and never reaches
  an agent, so it carries no agent-facing guidance. Recorded in ADR 0038 and
  ARCHITECTURE.md's error-taxonomy section.

Out of scope: storage protocol changes, batch deletes, agent-facing tools,
transport protocol changes, deleting GCS soft-deleted or noncurrent object
versions (documented only).

## Definitions

- **Entity prefix** `P = build_prefix(scope, entity_id)`, i.e.
  `f"{scope}/{entity_id}/"`. Plain string match, so `user/u1/` never
  matches `user/u10/...`.
- **Object under P**: any storage key starting with `P`, whatever its shape.
- **Pass**: one drain of the listing of `P`, from `start_after=None` until
  a page shorter than `list_page_size`.

## Fixtures

- `S` is an `InMemoryStorage`. `H` wraps `S` as a `Storage`, records every
  call (method and arguments) in order, and can run a callback inside
  `list_page` (before or after delegating, as each case states) or inside
  `delete_if_version` (before delegating), or raise from either.
- `M = MemoryStore(H, list_page_size=2)` (small, to force pagination).
  Every case below uses `M` over `H` unless it says otherwise; "no storage
  call" means `H` recorded no call.
- `C` is an `InMemoryIndexCache`; `MC = MemoryStore(H, list_page_size=2,
  index_cache=IndexCache(get=C.get, set=C.set))`. Cache keys follow ADR
  0040's documented format.
- Seed data, written with `S.put` so it can include shapes core would
  refuse, under entity `E = ("user", "u1")`:
  `user/u1/notes/a.md`, `user/u1/notes/b.md`, `user/u1/system/rules.md`
  (valid, well-formed metadata), `user/u1/prefs/c.md` with corrupt metadata
  (e.g. `{"aliases": "not json"}`), `user/u1/odd-key` (not a memory path),
  and `user/u1/notes/bin.md` with non-UTF-8 bytes. Ascending key order:
  `notes/a.md`, `notes/b.md`, `notes/bin.md`, `odd-key`, `prefs/c.md`,
  `system/rules.md`.
- `E_valid`: the same seed minus `user/u1/prefs/c.md` (5 objects), with
  well-formed metadata (`metadata_to_map` of a valid `FileMetadata`) on
  every object, so `get_memory_index` succeeds over it (`odd-key` is
  skipped by listing; `notes/bin.md`'s body is never read). Every case that
  caches the index before purging uses `E_valid`.
- Neighbours: `user/u10/notes/a.md`, `user/u2/notes/a.md`,
  `project/u1/notes/a.md`, `user-archive/u1/notes/a.md`.
- Tests that check a message or log omits the entity ID use a distinctive
  entity ID (e.g. `"ent-q7zx-erasure"`) that cannot appear by accident.

## User stories and acceptance criteria

### US1 — Purge

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1.1 | seed data | `M.purge("user", "u1")` | returns 6; `S.list_page("user/u1/", None, 100)` is empty |
| 1.2 | same | after purge | `M.list_prefix("user/u1/")` has no entries and `next_cursor is None`; `M.get_memory_index({"user": "u1"})` equals `MemoryIndex()`; `read_file` of each former well-formed path raises `NotFoundError(FILE_ABSENT)` |
| 1.3 | same | after purge | every neighbour object is unchanged (same data, metadata, version via `S.get`) |
| 1.4 | an entity with no objects | `purge` | returns 0; no exception; `H` recorded no `delete_if_version` call |
| 1.5 | seed data | `purge` twice | 2nd call returns 0 |
| 1.6 | — | `purge` with a non-`str` (real type) `scope` or `entity_id` | `TypeError`; `H` recorded no call |
| 1.7 | — | `purge` with a `scope` / `entity_id` failing `is_valid_segment` (`""`, `"a/b"`, `".."`) | `ValueError("invalid scope: ...")` / `ValueError("invalid entity_id: ...")`; `H` recorded no call |
| 1.8 | 7 objects under the prefix (page size 2) | `purge` | all deleted; returns 7 |
| 1.9 | after purge, a former path | `write_file(path, ..., expected_version=None)` | succeeds (create); the new version differs from every pre-purge version |

### US2 — Passes and concurrent writers

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 2.1 | seed data; `H` hook in the first `delete_if_version` call: `S.put("user/u1/aa/new.md", ...)` (sorts before the pass's cursor) | `purge` | returns 7; `aa/new.md` is gone (deleted on pass 2) |
| 2.2 | seed data; `H` hook in the first `delete_if_version` call (key K = `notes/a.md`): `S.put(K, ...)` before delegating, so the guarded delete fails | `purge` | returns 6; K is gone (deleted at its new version on pass 2); no exception |
| 2.3 | seed data; `H` hook in the first `delete_if_version` (key K): `S` deletes K before delegating | `purge` | returns 5; K is absent; no exception |
| 2.4 | seed data; `H` hook in **every** `list_page` call under `user/u1/`, run **before** delegating: `S.put` one fresh key `user/u1/zz/fresh-{n:04d}.md` with valid metadata (`metadata_to_map` of a valid `FileMetadata`) (`n` = call count; sorts after every seed key and every earlier fresh key, so after any cursor) | `purge` | raises `PurgeIncompleteError`; `H` recorded exactly `PURGE_MAX_PASSES + 1` `list_page` calls with `start_after=None` (5 passes + the check); `e.scope == "user"`, `e.entity_id == "u1"`, `e.passes == PURGE_MAX_PASSES` |
| 2.4b | hook as 2.4 | `purge(..., max_passes=2)` | raises `PurgeIncompleteError` with `passes == 2`; exactly 3 `list_page` calls with `start_after=None`; `str(e)` contains `"after 2 passes"` (the passed value, not the constant) |
| 2.4c | — | `purge(..., max_passes=x)` | `0`, `-1`: `ValueError("max_passes must be positive")`; `True`, `1.0`, `"3"`: `TypeError`; `H` recorded no call in either case |
| 2.4d | seed data, no writer | `purge(..., max_passes=1)` | returns 6 (one deleting pass, then an empty check) |
| 2.4e | seed data; `H` hook in the first `delete_if_version` call: `S.put("user/u1/aa/late.md", ...)` (sorts before the cursor, so pass 1 misses it) | `purge(..., max_passes=1)` | raises `PurgeIncompleteError` with `passes == 1` (the check finds `aa/late.md`) |
| 2.4f | entity `("user", "ent-q7zx-erasure")` seeded like E under `user/ent-q7zx-erasure/`; the 2.4 hook keyed on `list_page` calls under `user/ent-q7zx-erasure/`, writing `user/ent-q7zx-erasure/zz/fresh-{n:04d}.md` | `purge("user", "ent-q7zx-erasure")` | raises `PurgeIncompleteError`; `str(e)` contains `"user"` and not `"ent-q7zx-erasure"` |
| 2.4g | `MC`, `E_valid` seeded; `MC.get_memory_index({"user": "u1"})` called (cached); **then** the 2.4 hook installed | `MC.purge("user", "u1")` raises `PurgeIncompleteError` | the raw value at `user/u1`'s listing key contains none of the `E_valid` paths, descriptions, or aliases; the token key changed |
| 2.5 | `MC`, `E_valid` seeded, `MC.get_memory_index({"user": "u1"})` cached; then `H` set to raise `BackendUnavailableError` from the 2nd `delete_if_version` call | `purge` | `BackendUnavailableError` propagates; the 1st delete stands; the entity's token key changed (next index re-lists `user/u1/`) |
| 2.6 | `MC`, `E_valid` seeded, index cached as in 2.5; then `H` set to raise `KeyboardInterrupt` from the first `delete_if_version` call | `purge` | `KeyboardInterrupt` propagates; the entity's token key changed |

### US3 — Index cache

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 3.1 | `MC`, `E_valid` plus `project/u1/notes/a.md` (valid metadata); `get_memory_index({"user": "u1", "project": "u1"})` cached | `MC.purge("user", "u1")`, then index again | `user/u1` contributes no entries; `project/u1` entries unchanged |
| 3.2 | same as 3.1 (`E_valid`, index cached) | after purge | the raw value at `user/u1`'s listing key contains none of the purged paths, descriptions, or aliases |
| 3.3 | `MC` over a cache wrapper that appends each `set(key, ...)` to `H`'s call log | `purge` | exactly one `set` on the entity's token key and one on its listing key (the tombstone), in that order, both after the last storage call `H` recorded |
| 3.4 | `MC` with a cache whose `set` raises; seed data (E, 6 objects; no index call, so corrupt metadata is harmless) | `purge` | all 6 objects deleted, then the cache's exception propagates |
| 3.5 | `MC` with a cache whose `set` raises; entity `("user", "ent-q7zx-erasure")` seeded like E under `user/ent-q7zx-erasure/` (no index call); `H` raising `BackendUnavailableError` from the first `delete_if_version` | `purge("user", "ent-q7zx-erasure")` | `BackendUnavailableError` propagates (not the cache error); one WARNING on `wenchang.core` names the scope and the cache exception type; no record contains `"ent-q7zx-erasure"` |
| 3.6 | `M` (no cache) | `purge` | works as US1; `M.index_cache is None` |

### US4 — Export

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 4.1 | seed data | `M.export("user", "u1")` | a `tuple` of 6 `ExportedObject`s in ascending `key` order, one per object under `user/u1/`, including `system/`, corrupt-metadata, non-UTF-8, and non-path keys |
| 4.2 | same | export | each object's `data`, `dict(metadata)`, and `version` equal `S.get(key)`'s |
| 4.3 | same | export | no neighbour key appears |
| 4.4 | same | export | `H` recorded no `put`, `put_if_version`, or `delete_if_version` call; every object, including neighbours, has its prior version |
| 4.5 | **round trip**: export E1; `purge`; `S.put(o.key, o.data, o.metadata)` for each `o` in E1; export E2 | compare | `[(o.key, o.data, dict(o.metadata)) for o in E1]` equals the same for E2; `read_file` of `notes/a.md`, `notes/b.md`, `system/rules.md` returns the original content and metadata |
| 4.6 | an entity with no objects | export | `()` |
| 4.7 | 7 objects (page size 2) | export | all 7 present, in ascending key order |
| 4.8 | seed data; `H` hook in the first `list_page`, after delegating: `S` deletes the first listed key | export | that key is omitted; 5 objects; no exception |
| 4.9 | seed data; `H` hook in the first `list_page`, after delegating: `S.put` the first listed key with new data and metadata | export | that object carries the new data, metadata, and version together |
| 4.10 | — | export with the bad arguments of 1.6–1.7 | same `TypeError` / `ValueError`; `H` recorded no call |
| 4.11a | `o = ExportedObject(key, data, m, version)` with a `dict` `m` | mutate `m` | `o.metadata` unchanged |
| 4.11b | same, and an object from `export` | `o.metadata["x"] = "y"`; `o.data = b""` | `TypeError`; `dataclasses.FrozenInstanceError` |
| 4.12 | `H` raising `BackendUnavailableError` from `list_page`, or from `get` | export | propagates |

### US5 — Conformance on both storage implementations

A new mixin, `EntityPurgeExportConformance` (not `Test`-prefixed, in
`tests/storage_conformance.py` beside `StorageConformance`), takes the same
`storage` fixture, builds `MemoryStore(storage, list_page_size=2)`, seeds
with `storage.put`, and is subclassed by the unit module for
`InMemoryStorage` and by `tests/integration/test_storage_gcs.py` for
`GcsStorage` against fake-gcs-server. Concurrency cases (US2) stay
unit-only: fake-gcs-server does not enforce `ifGenerationMatch` on DELETE.

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 5.1 | seed data and neighbours in `storage` | purge | returns 6; prefix empty; neighbours unchanged |
| 5.2 | same | export, purge, restore with `storage.put`, export | the two exports match on key, data, metadata (as in 4.5); E1 has the 6 seed keys and no neighbour |
| 5.3 | 7 objects | purge; then (re-seeded) export | 7 deleted; 7 exported in order |
| 5.4 | empty entity | purge; export | `0`; `()` |

### US6 — API surface

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 6.1 | — | `TransportClient`, `InProcessClient`, `MemoryTools`, `descriptions()` | none has `purge` or `export`; the transport signature-parity test still passes (inherently green: guards against later drift) |
| 6.2 | — | `from wenchang.core import ExportedObject, PurgeIncompleteError, PURGE_MAX_PASSES` | importable; `PurgeIncompleteError` subclasses `Exception` and not `WenchangError`; `PURGE_MAX_PASSES == 5` |

## Non-functional

- No new dependencies. No storage protocol change.
- GCS soft delete and object versioning: purge removes live objects only.
  With a bucket soft-delete policy (GCS default 7 days) or object
  versioning, deleted bytes remain recoverable for the retention window.
  Documented in ADR 0038 and the `purge` docstring; erasure-bound adopters
  configure the bucket accordingly.
- ADR 0038 records the API, decisions, guarantees, the taxonomy deviation,
  the undercount on lost delete responses, and the cost/memory statement.
  ARCHITECTURE.md: `core` entry (the "seven core operations" wording, plus
  `purge`, `export`, `ExportedObject`, `PurgeIncompleteError`,
  `PURGE_MAX_PASSES`), the error-taxonomy section (operator-only
  non-taxonomy errors), the storage entry's conformance description (the
  new mixin), and the concurrency section. The `MemoryStore` docstring's
  operation list is updated too.
