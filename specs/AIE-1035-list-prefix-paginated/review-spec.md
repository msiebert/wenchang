# Spec Review: AIE-1035 — list_prefix

## What & why

`MemoryStore.list_prefix(prefix, cursor=None)` returns one page of
`FileEntry(path, metadata, version)` for the memory files under a scope,
entity, or area prefix, plus an opaque cursor for the next page. No content
is read. It is how the agent enumerates an area the startup index reported
as capped. It needs a new storage primitive, `Storage.list_page`, on both
backends.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | Files under `a/e/x/` | `list_prefix("a/e/x/")` | Entries with metadata + version (equal to `read_file`), ascending by path, `next_cursor=None` |
| 2 | Files under `a/e/x/`, `a/e/y/`, `a/f/x/`, `a/e/xy/` | `list_prefix("a/e/")` / `("a/e/x/")` | Recursive under `a/e/`; `a/e/xy/` not matched by `a/e/x/` |
| 3 | Empty prefix | list | `entries=()`, no error |
| 4 | `list_page_size=2`, 5 files | Follow cursors | Pages 2/2/1, each file once; exactly 4 files → no trailing empty page |
| 5 | Files added/deleted between pages | Next page | Files present throughout appear exactly once; no snapshot |
| 6 | Cursor for another prefix, or garbage | list | `ValueError` |
| 7 | Prefix `""`, `a`, `a/e/x`, `a//`, `a/../`, 4 segments, a file path | list | `NotFoundError(INVALID_PATH)`, no storage call |
| 8 | Malformed key under prefix (`notes.txt`, too deep) | list | Skipped; pagination still complete |
| 9 | Corrupt metadata / backend down | list | `MetadataFormatError` / `BackendUnavailableError` propagate |
| 10 | Storage `list_page(prefix, start_after, limit)` | Both backends | Ascending, exclusive `start_after`, ≤ `limit`, metadata/version match `get` |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| Storage primitive `list_page(prefix, start_after, limit)` | Expose GCS page tokens | Key-based resume behaves identically in fake and GCS, survives concurrent writes, and needs no backend state |
| Cursor = base64 of last examined key, checked against prefix | Raw key; GCS page token | Opaque to callers (same discipline as version tokens), cheap to validate |
| Prefix = 1–3 segments ending in `/` | Arbitrary string prefix; allow `""` | Matches the path layout; `a/e/x` can't accidentally match `a/e/xy/`; no whole-bucket scans |
| Page size is store config (default 100) | Per-call `limit` arg | Keeps the Notion signature; ~100 entries ≈ 10–20 KB |
| Fetch `page_size + 1` to detect more | Cursor whenever page is full | No trailing empty page |
| Skip malformed keys, propagate corrupt metadata | Skip both; fail on both | Stray objects aren't memory files; corrupt memory files shouldn't vanish silently (matches `read_file`) |

## Files/modules to be touched

- `src/wenchang/storage/{__init__,memory,gcs}.py`, `src/wenchang/paths.py`, `src/wenchang/core.py`
- `tests/storage_conformance.py`, `tests/test_core_list_prefix.py` (new), paths tests
- `ARCHITECTURE.md`, `docs/adr/0010-list-prefix-pagination.md`

## Open questions / assumptions

- Bad cursor raises plain `ValueError` (not a taxonomy error). The tool layer (AIE-1044) can map it; OK?
- Empty prefix disallowed. `get_memory_index` fans out per scope, so it shouldn't need a whole-bucket scan.
- Corrupt metadata fails the whole page instead of skipping the file. Fine for now?

## Risks

- fake-gcs-server's `startOffset` support is assumed. If it's missing, T2 falls back to a prefix-only listing filtered on the client side.
- Storage protocol change: every `Storage` stub in tests must add `list_page` to keep pyright strict green.
