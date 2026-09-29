# Implementation Plan: list_prefix

**Linear issue**: AIE-1035 | **Branch**: `AIE-1035-list-prefix` | **Date**: 2026-09-29 | **Spec**: [spec.md](spec.md)

## Summary

Add a `Storage.list_page` primitive (protocol, in-memory fake, GCS), a
`paths.is_valid_prefix` check, and `MemoryStore.list_prefix` returning a
`ListPage` of `FileEntry` values with an opaque `ListCursor`.

## Technical Context

Python ≥ 3.12; pytest (`unit` / `integration` markers); pyright strict;
ruff. GCS integration tests run against fake-gcs-server via the existing
`StorageConformance` suite in `tests/storage_conformance.py`.

## Constitution Check

| Principle | Status |
| --------- | ------ |
| I. Tests-first | T1–T4 each test-writer → implementer |
| IV. Strict typing | All new signatures fully annotated |
| V. Storage only through interface | Core uses `Storage.list_page` only; GCS calls stay in `storage/gcs.py` |
| VI. Spec fidelity | Prefix rules, cursor, page size → ADR |
| VII. Architecture documented | Storage protocol change + new public method → ARCHITECTURE.md + ADR 0010 |
| VIII. Traceability | Test docstrings reference AIE-1035 |

**Decisions to record in an ADR (0010):** new `list_page` storage primitive
with exclusive `start_after`; segment-aligned prefixes of 1–3 segments;
cursor = encoded last-examined key, validated against the prefix; page size
as store config (default 100); malformed keys skipped, corrupt metadata
propagates; no snapshot across pages.

## Public interface

### `src/wenchang/storage/__init__.py`

```python
@dataclass(frozen=True)
class ListedObject:
    """One object's key, metadata, and version, as returned by a listing."""

    key: str
    metadata: Mapping[str, str]
    version: VersionToken


class Storage(Protocol):
    def list_page(self, prefix: str, start_after: str | None, limit: int) -> Sequence[ListedObject]:
        """Objects whose key starts with `prefix` (plain string match) and,
        if `start_after` is given, is strictly greater than it; ascending by
        key; at most `limit` (>= 1). No bodies read. Metadata mappings are
        copies. May raise BackendUnavailableError."""
```

Ordering is by Python `str` comparison (code point), which equals GCS's
UTF-8 byte order.

### `src/wenchang/storage/memory.py`

`InMemoryStorage.list_page` — sort matching keys, filter `> start_after`,
slice to `limit`.

### `src/wenchang/storage/gcs.py`

`GcsStorage.list_page` — `bucket.list_blobs(prefix=prefix,
start_offset=start_after, max_results=limit + 1)` (`start_offset` is
inclusive, so drop a key equal to `start_after`, then truncate to `limit`).
Metadata from `blob.metadata or {}`, version `str(blob.generation)`.
Exceptions raised during the call or iteration go through
`_map_backend_error`.

### `src/wenchang/paths.py`

```python
def is_valid_prefix(prefix: str) -> bool:
    """True iff prefix is 1–3 valid segments, each followed by '/'.
    Never raises for any str input."""
```

Segment validity is the same `_is_valid_segment` used by `is_valid_path`.

### `src/wenchang/core.py`

```python
ListCursor = NewType("ListCursor", str)
DEFAULT_LIST_PAGE_SIZE: int = 100


@dataclass(frozen=True)
class FileEntry:
    path: str
    metadata: FileMetadata
    version: VersionToken


@dataclass(frozen=True)
class ListPage:
    entries: tuple[FileEntry, ...]
    next_cursor: ListCursor | None


class MemoryStore:
    def __init__(
        self,
        storage: Storage,
        *,
        max_file_bytes: int = ...,
        clock: ... = ...,
        list_page_size: int = DEFAULT_LIST_PAGE_SIZE,
    ) -> None:
        ...
        # list_page_size <= 0 → ValueError

    def list_prefix(self, prefix: str, cursor: ListCursor | None = None) -> ListPage: ...
```

`FileEntry`, `ListPage`, `ListCursor` are exported from `wenchang.core`
alongside `MemoryFile`.

Algorithm:

```text
1. not is_valid_prefix(prefix) → NotFoundError(prefix, INVALID_PATH). No storage call.
2. start_after = None if cursor is None else _decode_cursor(cursor, prefix)
   (malformed, or decoded key not starting with prefix → ValueError).
3. objs = storage.list_page(prefix, start_after, list_page_size + 1)
4. page, more = objs[:list_page_size], len(objs) > list_page_size
5. entries = tuple(FileEntry(o.key, metadata_from_map(o.metadata), o.version)
                   for o in page if is_valid_path(o.key))
   (MetadataFormatError / BackendUnavailableError propagate)
6. next_cursor = _encode_cursor(page[-1].key) if more else None
```

Cursor encoding: URL-safe base64 of the UTF-8 key, no padding stripping.
Decoding uses strict validation; `binascii.Error` / `UnicodeDecodeError`
become `ValueError`.

## Test layout

- `tests/storage_conformance.py` — new `list_page` cases (US4), inherited
  by the existing in-memory unit test class and the GCS integration class.
- `tests/test_paths.py` (existing or new) — `is_valid_prefix` table.
- `tests/test_core_list_prefix.py` (new, unit) over `InMemoryStorage`,
  reusing the `_metadata` / `_seed` / `_new_store` helper style; a stub
  storage for malformed-key, corrupt-metadata, and backend-error cases.

## Project Structure

```text
specs/AIE-1035-list-prefix-paginated/  spec.md plan.md tasks.md review-spec.md
src/wenchang/storage/__init__.py       # ListedObject, Storage.list_page
src/wenchang/storage/memory.py         # list_page
src/wenchang/storage/gcs.py            # list_page
src/wenchang/paths.py                  # is_valid_prefix
src/wenchang/core.py                   # FileEntry, ListPage, ListCursor, list_prefix
tests/storage_conformance.py           # list_page cases
tests/test_core_list_prefix.py         # new
```

## Complexity Tracking

None.
