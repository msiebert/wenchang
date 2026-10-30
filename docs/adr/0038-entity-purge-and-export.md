# 0038. Entity purge and export

Date: 2026-10-30

## Status

Accepted. Deviates from [ADR 0005](0005-error-taxonomy-as-exceptions.md) for
one operator-only error (see Deviation). Interacts with
[ADR 0040](0040-index-cache.md) (index cache).

## Context

GDPR deletion and project or org deletion need to remove, or hand over,
everything stored for one entity: every object under
`build_prefix(scope, entity_id)`, i.e. `{scope}/{entity_id}/`. That includes
`system/` files, keys that are not well-formed memory paths, and objects with
corrupt metadata. The library owns the key layout, so the operation belongs
in the library. It is for operators, not agents.

The `Storage` protocol has no unconditional delete
([ADR 0012](0012-delete-file.md)); `delete_if_version` is its only delete.

## Decision

1. **Two `MemoryStore` methods, no storage change.**
   `purge(scope, entity_id, *, max_passes=PURGE_MAX_PASSES) -> int` and
   `export(scope, entity_id) -> tuple[ExportedObject, ...]`, built in `core`
   from `Storage.list_page`, `get`, and `delete_if_version`. Both run
   unchanged on `InMemoryStorage` and `GcsStorage`. The protocol still has no
   unconditional delete. `PURGE_MAX_PASSES = 5` is public.
2. **Operator-only.** Neither method is on `TransportClient`,
   `InProcessClient`, `MemoryTools`, or the MCP adapter. Operators call the
   store directly (`InProcessClient.store` exposes it).
3. **Arguments.** A `scope` or `entity_id` whose real type is not `str`, or a
   `max_passes` that is a `bool` or not an `int`, raises `TypeError`. Then a
   segment failing `is_valid_segment` raises `ValueError("invalid scope:
   ...")` or `ValueError("invalid entity_id: ...")`, and `max_passes < 1`
   raises `ValueError`. All checks run before any storage or cache call.
4. **Pass algorithm.** A pass lists the prefix from the start, page by page
   (`list_page_size`). It deletes each listed object guarded on its listed
   version. A `PreconditionFailedError` (changed or already gone) is skipped
   and left for the next pass. The cursor moves past handled keys, so a
   failed delete is not retried within the pass. A pass that lists nothing
   ends the purge. After `max_passes` passes that all found objects, one
   final `list_page(prefix, None, 1)` decides: empty returns, otherwise
   `PurgeIncompleteError(scope, entity_id, passes=max_passes)`. Any other
   storage exception propagates, and deletes already made stand. Purge never
   reads bodies or parses metadata.
5. **What `max_passes` bounds.** It bounds restarts only: at most
   `max_passes + 1` listings start from the beginning of the prefix. It does
   not bound a single pass. A writer that keeps adding keys after the pass's
   cursor faster than purge deletes them keeps that pass running.
6. **Guarantee.** When `purge` returns, the prefix was observed empty after
   every delete it made. A write landing after that last listing survives.
   Durable erasure requires stopping the entity's writers first (revoke the
   grant), then purging.
7. **Idempotent.** Re-running purge is always safe; on an empty prefix it
   returns 0 with no delete call.
8. **Count.** The return value counts successful `delete_if_version` calls.
   A delete that landed in GCS but whose response was lost is not counted:
   it surfaces as `BackendUnavailableError`, or a client retry sees a
   precondition failure. Re-running purge is safe.
9. **Export format.** `ExportedObject(key, data, metadata, version)` is a
   frozen dataclass: the full storage key, raw bytes, the stored flat
   metadata map (copied into a read-only `MappingProxyType`), and the
   version. It is unhashable and pickles or deep-copies by rebuilding
   through its constructor. Nothing is parsed, so corrupt metadata, non-UTF-8 bodies, and
   malformed keys are exported raw rather than dropped or raised. Restore
   with `Storage.put(o.key, o.data, o.metadata)`. Output is in ascending key
   order.
10. **Export is not a snapshot.** It lists a page, then `get`s each key.
    Each object is internally consistent (one write's bytes, metadata, and
    version). An object deleted between listing and `get` is omitted; one
    written after its page was listed may be missing. A consistent export
    requires writers stopped. Export never touches the index cache.
11. **Cost.** One `list_page` per `list_page_size` objects per pass, plus N
    sequential `delete_if_version` (purge) or `get` (export) calls for N
    objects: roughly N × round-trip time on GCS.
12. **Export memory is unbounded by the library.** Every object's bytes are
    held at once. AIE-1292's per-entity file cap does not bound it: `system/`
    files and malformed keys are not counted, the cap is soft and may be
    disabled, and direct storage puts bypass both it and `max_file_bytes`.
13. **Index cache ([ADR 0040](0040-index-cache.md)).** Purge calls `invalidate_index(scope,
    entity_id)` exactly once, after its last storage call, on every exit
    path. On success a cache exception propagates and the delete count is
    lost (re-running returns 0 and invalidates again). If purge itself failed
    (including `PurgeIncompleteError` and `BaseException`s such as
    `KeyboardInterrupt`), a cache exception is logged as a WARNING on
    `wenchang.core` naming the scope and exception type, never the entity ID,
    and the original failure is re-raised. On an interrupt purge still calls
    the adopter's cache, which may block. ADR 0040's race is unchanged: a
    reader that listed before the purge can store its pre-purge listing
    after the tombstone. It is never served and persists until re-index or
    `ttl`, so erasure-bound adopters must set a finite `ttl`.
14. **GCS soft delete and versioning.** Purge removes live objects only. A
    bucket soft-delete policy (GCS default 7 days) or object versioning
    keeps deleted bytes recoverable for the retention window. Configuring the
    bucket is the adopter's job; the library documents it only.
15. **File cap (AIE-1292).** No interaction needed: purge removes every
    object under the prefix, freeing all of the entity's slots.
16. **Conformance.** A new mixin, `EntityPurgeExportConformance` in
    `tests/storage_conformance.py`, runs purge and export through
    `MemoryStore` on `InMemoryStorage` and on `GcsStorage` against
    fake-gcs-server. The concurrency cases are unit-only, because
    fake-gcs-server does not enforce `ifGenerationMatch` on DELETE.

### Deviation

`PurgeIncompleteError` subclasses `Exception`, not `WenchangError`, outside
the ADR 0005 taxonomy. The taxonomy classifies errors by what the agent
should do next. This error is operator-only, never reaches an agent, and
carries no agent guidance. It exposes `scope`, `entity_id`, and `passes`,
and pickles and copies with all three; its message names the scope and
`passes` ("after 1 pass" / "after N passes"), never the entity ID.

### Known limitation

The invalid-argument `ValueError` for `entity_id` echoes the value
(`invalid entity_id: '...'`), so it can expose an entity ID that
`PurgeIncompleteError` and the cache-failure log avoid. It is kept because
the message is shared library-wide with `invalidate_index` and
`get_memory_index` and is pinned by existing tests, including the transport
conformance `MSG_INVALID_ENTITY`.

## Consequences

- Operators can erase or hand over an entity with one call, on either
  backend, without a storage protocol change or an unconditional delete.
- Erasure is only as strong as the operator's process: stop writers, set a
  finite cache `ttl`, and configure GCS soft delete and versioning to match
  the retention obligation.
- A large entity costs N sequential round trips, and its export must fit in
  memory.
- The delete count is a lower bound, not an audit record.

Rejected:

- **`Storage.delete` or `Storage.delete_prefix`.** A protocol change on both
  backends, and an unconditional delete races concurrent writers silently.
  The guarded delete plus re-listing gives the same result with a stated
  guarantee.
- **GCS batch delete.** GCS-specific, and it would need a new `Storage`
  protocol method that the in-memory fake must mirror. A follow-up can add
  it if large entities need it.
- **Parsed export (`MemoryFile`s).** Drops or raises on malformed keys,
  corrupt metadata, and non-UTF-8 bodies, exactly the objects an erasure
  export must include, and cannot be restored byte-for-byte.
- **Streaming export (an iterator).** Lazily held storage reads across
  caller code widen the non-snapshot window, and a tuple is simpler to test.
  Memory is documented instead.
- **Agent-facing tools.** Erasure is an operator decision; an agent must
  never be able to delete or dump a whole entity.
- **`PurgeIncompleteError` as a `TransientError`.** Its retry guidance is
  for agents, and retrying without stopping writers would fail again.
