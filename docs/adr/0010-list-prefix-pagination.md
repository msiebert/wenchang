# 0010. list_prefix pagination

Date: 2026-09-29

## Status

Accepted

## Context

AIE-1035 delivers `list_prefix`, the fourth core API function: a
metadata-only, paginated listing of files under a prefix (Notion Section 5,
`list_prefix(prefix, cursor)`, and "Startup load and capping"). It needs a
new storage primitive — nothing in the `Storage` protocol so far returns
more than one object — plus prefix validation and cursor handling with no
direct precedent in the Notion spec. All points below were raised and
resolved at the spec checkpoint on 2026-09-29, building on `read_file`
(AIE-1032), `FileMetadata` / `metadata_from_map` (AIE-1031), and
`NotFoundError` (AIE-1030).

## Decision

- **A new `Storage.list_page(prefix, start_after, limit)` primitive is
  added to the protocol**, returning `ListedObject(key, metadata, version)`
  in ascending key order, plain-string prefix match, exclusive
  `start_after`, at most `limit`, never reading bodies. This widens the
  `Storage` protocol (as `put_if_version` did in ADR 0008) rather than
  exposing GCS's own page tokens through it. Rejected alternative: passing
  through `google.cloud.storage`'s iterator/page-token object, which would
  leak a GCS-specific type into the protocol `InMemoryStorage` has to
  satisfy too, and would give `core` no uniform way to resume a listing
  across backends.
- **`core` encodes its own opaque `ListCursor` (URL-safe base64 of the last
  examined key) rather than handing the caller a raw key or a GCS page
  token.** A raw key would invite callers to parse or construct one, the
  same reasoning as the existing rule that version tokens are opaque
  (`ARCHITECTURE.md`'s optimistic-concurrency invariant). A GCS token
  doesn't exist for `InMemoryStorage` and would couple the cursor format to
  one backend. A cursor is validated against the `prefix` it was issued for
  by decoding it and checking the key still starts with that prefix;
  malformed or foreign-prefix cursors raise a plain `ValueError` (not a
  `WenchangError` subclass) — mapping that to a tool-facing error is
  deferred to the tool layer (AIE-1044), consistent with `ValueError` from
  `old_string == ""` in `replace_fact` (ADR 0009).
- **A valid prefix is 1-3 valid segments, each followed by `/`; the empty
  prefix (the whole bucket) is disallowed.** This mirrors `is_valid_path`'s
  existing segment rules (`paths._is_valid_segment`) and matches how memory
  paths are actually laid out (`{scope}/{entity_id}/{area}/{name}.md`), so
  every valid prefix names a scope, an entity, or an area exactly. Rejected
  alternative: accepting an arbitrary string prefix (a substring match
  against raw keys), which would let a prefix cut a path segment in half
  (e.g. `"a/e/x"` would also match `"a/e/xy/..."`) and would give
  `list_prefix` no natural stopping point for "listing is recursive but
  segment-aligned."
- **Page size is `MemoryStore` construction config
  (`list_page_size`, default `DEFAULT_LIST_PAGE_SIZE = 100`), not a
  per-call argument**, matching the Notion signature
  `list_prefix(prefix, cursor)` exactly. Rejected alternative: a per-call
  `limit` parameter, which the spec doesn't have room for and which would
  let different callers see different page boundaries against the same
  store.
- **`list_prefix` fetches `list_page_size + 1` keys per call and trims the
  extra one to decide `next_cursor`.** This is the only way to know whether
  a key remains after the page without a second round trip or a
  storage-level "has more" signal, and it means the *last* page never comes
  back with a spurious non-`None` cursor pointing at nothing (FR-002: no
  trailing empty page).
- **A key under the prefix that isn't a well-formed memory path is skipped,
  but corrupt metadata on a well-formed key propagates as
  `MetadataFormatError`.** These are different failure modes: a malformed
  key (e.g. `a/e/x/notes.txt`) was never a memory file to begin with and
  listing should route around it silently, the same way `read_file` would
  simply not be called on it; corrupt metadata is a well-formed file that's
  broken, and hiding it from a listing would contradict `read_file`'s own
  behavior of surfacing that corruption. A page can therefore be shorter
  than `list_page_size` while `next_cursor` is still non-`None` — accepted
  as an edge case (spec `Edge Cases`) rather than fetching further pages
  internally to backfill the count, which would make one `list_prefix` call
  do an unbounded number of storage calls.
- **Listing is not a snapshot.** Each page reflects storage as read at the
  time that page was fetched; a file written after an earlier page but
  before a later one is included, and a file deleted between pages is
  simply absent from the page that would have held it. No isolation
  mechanism (e.g. a GCS generation-pinned listing) is introduced, matching
  the accepted looseness of `append_line`'s no-version-guard and
  `replace_fact`'s stale-retry semantics elsewhere in `core`.

## Consequences

`list_prefix` and `Storage.list_page` are testable end-to-end against
`InMemoryStorage` (`tests/test_core_list_prefix.py`) and conformance-tested
against both backends (`tests/storage_conformance.py`), the same pattern
established for `get`/`put` (ADR 0007) and `put_if_version` (ADR 0008).
Because widening `Storage` with a new abstract method breaks `GcsStorage`
under pyright strict until it implements `list_page`, the storage-layer
task and the GCS implementation landed together, as `put_if_version` did.

`get_memory_index` (AIE-1044), scope-map fan-out, and `system/` enforcement
(AIE-1040) remain out of scope; `list_prefix` lists `system/` areas like
any other, since read-only enforcement is a tool-layer concern per ADR
0008's note on `write_file`.

**Update (AIE-1046):** `get_memory_index` and its scope-map fan-out, deferred
above, are implemented per
[ADR 0020](0020-memory-index-and-in-process-client.md) (rescoped from
AIE-1044 by [ADR 0019](0019-transport-client-interface.md)). For each scope
in the map it drains every page of the base `MemoryStore.list_prefix` until
`next_cursor` is `None`, never stopping on an empty page, so the paging
semantics above, including skipped malformed keys and the no-snapshot rule,
carry over to the index unchanged.
