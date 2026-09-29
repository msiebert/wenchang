# Feature Specification: list_prefix — paginated metadata listing

**Linear issue**: AIE-1035 — https://linear.app/mixpanel/issue/AIE-1035/list-prefix

**Feature Branch**: `AIE-1035-list-prefix`

**Created**: 2026-09-29

**Status**: Draft

**Input**: Linear AIE-1035 and Notion "Agent Memory Library — Specification",
Section 5 (`list_prefix(prefix, cursor)` — metadata only, paginated, returns
each file's metadata plus its version token) and Section 5 "Startup load and
capping" (the agent calls `list_prefix` for any area the index reported as
capped). Builds on `read_file` (AIE-1032), `FileMetadata` /
`metadata_from_map` (AIE-1031), and `NotFoundError` (AIE-1030).

## Summary

Add `MemoryStore.list_prefix(prefix, cursor=None)`, which returns one page
of `FileEntry(path, metadata, version)` for the memory files under a
segment-aligned prefix, plus an opaque `next_cursor` for the following page.
No file content is read.

This needs a new storage primitive: `Storage.list_page(prefix, start_after,
limit)`, returning objects' keys, metadata, and versions in ascending key
order, implemented by `InMemoryStorage` and `GcsStorage` and covered by the
shared storage conformance suite.

Out of scope: `get_memory_index` (AIE-1044), scope-map fan-out, `system/`
enforcement (AIE-1040), and agent-facing tool wording (AIE-1044).

## User Scenarios & Testing *(mandatory)*

The "user" is a caller inside the library (transport layer, a future
`get_memory_index`, tests) enumerating the files in one area or scope.

### User Story 1 - List a prefix in one page (Priority: P1)

**Acceptance Scenarios**:

1. **Given** files `a/e/x/1.md` and `a/e/x/2.md` written at versions `V1`,
   `V2` with metadata `M1`, `M2`, **When** `list_prefix("a/e/x/")` is
   called, **Then** it returns a `ListPage` whose `entries` are
   `(FileEntry("a/e/x/1.md", M1, V1), FileEntry("a/e/x/2.md", M2, V2))`, in
   that order, and `next_cursor is None`.
2. **Given** files under `a/e/x/`, `a/e/y/`, and `a/f/x/`, **When**
   `list_prefix("a/e/")` is called, **Then** every file under `a/e/` (both
   areas) is returned and none under `a/f/`. Listing is recursive.
3. **Given** prefix `a/e/x/` and a file at `a/e/xy/1.md`, **When** listed,
   **Then** that file is not returned (prefixes are segment-aligned).
4. **Given** no files under a well-formed prefix, **When** listed, **Then**
   `entries == ()` and `next_cursor is None` (no error).
5. **Given** entries returned by `list_prefix`, **Then** each entry's
   `metadata` and `version` equal what `read_file` returns for that path.
6. **Given** files whose names differ only in multi-byte unicode, **Then**
   entries are ordered by ascending code point of the path.

---

### User Story 2 - Paginate (Priority: P1)

**Acceptance Scenarios**:

1. **Given** a store with `list_page_size=2` and 5 files under a prefix,
   **When** `list_prefix(prefix)` is called and then repeatedly called with
   each returned `next_cursor` until it is `None`, **Then** pages hold 2, 2,
   and 1 entries, every file appears exactly once, in ascending path order.
2. **Given** `list_page_size=2` and exactly 4 files, **Then** the second
   page has 2 entries and `next_cursor is None` (no trailing empty page).
3. **Given** a cursor from page 1, **When** a file sorting after the cursor
   is written and another sorting before it is deleted before page 2 is
   requested, **Then** page 2 includes the new file and every file present
   throughout is returned exactly once across all pages.
4. **Given** a cursor from `list_prefix(P)`, **When** it is passed with a
   different prefix `Q` it was not issued for, or a cursor string not
   produced by `list_prefix`, **Then** `ValueError` is raised.
5. **Given** `list_page_size <= 0`, **When** `MemoryStore` is constructed,
   **Then** `ValueError` is raised.

---

### User Story 3 - Prefix validation and robustness (Priority: P1)

**Acceptance Scenarios**:

1. **Given** a prefix that is not 1–3 valid path segments each followed by
   `/` (e.g. `""`, `"a"`, `"a/e/x"`, `"a//"`, `"a/../"`, `"a/e/x/y/"`,
   `"a/e/x/1.md"`), **When** `list_prefix` is called, **Then**
   `NotFoundError(prefix, INVALID_PATH)` is raised without consulting
   storage.
2. **Given** an object under the prefix whose key is not a well-formed
   memory path (e.g. `a/e/x/notes.txt`, `a/e/x/deep/1.md`), **When**
   listed, **Then** it is omitted from `entries` and pagination still
   reaches every well-formed file.
3. **Given** an object under the prefix with corrupt metadata, **Then**
   `MetadataFormatError` propagates.
4. **Given** storage raising `BackendUnavailableError`, **Then** it
   propagates unchanged.

---

### User Story 4 - Storage primitive (Priority: P1)

Covered by the shared `StorageConformance` suite, run against
`InMemoryStorage` (unit) and `GcsStorage` (integration).

**Acceptance Scenarios**:

1. **Given** objects put at several keys, **When** `list_page(prefix, None,
   limit)` is called, **Then** it returns `ListedObject(key, metadata,
   version)` for keys starting with `prefix` (plain string prefix), ascending,
   at most `limit` of them; metadata and version equal what `get` returns.
2. **Given** `start_after=k`, **Then** only keys strictly greater than `k`
   are returned (`k` itself excluded, whether or not it exists).
3. **Given** no matching keys, **Then** an empty sequence is returned.
4. **Given** the caller mutates a returned metadata mapping, **Then**
   storage is unaffected.

### Edge Cases

- A page may hold fewer than `list_page_size` entries while `next_cursor`
  is non-`None`, when malformed keys were skipped.
- Pages are not a snapshot: a file changed between pages is reported at its
  version when its page was read.
- `system/` areas are listed like any other.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `MemoryStore.list_prefix(prefix, cursor=None) -> ListPage`
  MUST return well-formed memory files under `prefix` as `FileEntry(path,
  metadata, version)`, ascending by path, without reading content.
- **FR-002**: Pages MUST hold at most `list_page_size` (constructor
  keyword, default 100) storage keys; `next_cursor` MUST be `None` iff no
  key remains after the page.
- **FR-003**: A cursor MUST resume strictly after the last key examined by
  the page that issued it, and MUST be rejected with `ValueError` if
  malformed or not issued for this `prefix`.
- **FR-004**: An invalid prefix MUST raise `NotFoundError(prefix,
  INVALID_PATH)` without consulting storage.
- **FR-005**: `Storage.list_page(prefix, start_after, limit)` MUST be added
  to the protocol and implemented by `InMemoryStorage` and `GcsStorage`
  (GCS without downloading object bodies).

## Success Criteria *(mandatory)*

- **SC-001**: Draining any prefix page by page yields exactly the set of
  well-formed files that existed throughout, each once.
- **SC-002**: The storage conformance suite passes against both backends.

## Assumptions

- A valid prefix is one, two, or three valid segments (scope, entity,
  area), each followed by `/`. Anything else is a malformed path, reported
  like one. Empty prefix (the whole bucket) is not allowed.
- The cursor is an opaque `ListCursor` string; internally the last examined
  key, encoded so callers are not tempted to parse it.
- Page size is store configuration, not a per-call argument, matching the
  Notion signature.
- Corrupt metadata fails the listing, matching `read_file`, rather than
  silently hiding the file.
