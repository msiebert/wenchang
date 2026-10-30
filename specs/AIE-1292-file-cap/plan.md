# Implementation Plan: Cap the number of files per entity

**Linear**: AIE-1292 | **Spec**: [spec.md](spec.md) | **ADR**: 0039

## Summary

Add a per-entity file-count cap to `MemoryStore`, checked only when `write_file` creates a file, raising a new recoverable `FileQuotaExceededError`. No change to the `Storage` protocol, `TransportClient`, or the tool layer's logic.

## Public interface

### `wenchang.errors`

```python
class FileQuotaExceededError(RecoverableError):
    """A create would put an entity over its file-count limit."""

    def __init__(self, path: str, limit: int) -> None: ...
    path: str
    limit: int
```

- `limit < 1` raises `ValueError("limit must be positive")`.
- Message (`str(err)`), with `loc = _location(path) or "the file"` and `scope = parse_path(path).scope` when the path parses:

  ```
  Cannot create a new file at {loc}: memory in scope {scope} is at its limit of {limit} files. Add this content to an existing file instead (append_line, replace_fact, or write_file with that file's version), or merge related files into one and delete the merged ones with delete_file, then retry. {RecoverableError.guidance}
  ```

  If the path does not parse, `memory in scope {scope}` becomes `memory for this entity` and `loc` is `the file`.
  Example for `("user/u1/notes/new.md", 3)`: `Cannot create a new file at scope user, area notes, name new: memory in scope user is at its limit of 3 files. Add this content ... then retry. This is normal coordination, ...`

### `wenchang.core`

```python
DEFAULT_MAX_FILES_PER_ENTITY: int = 500

class MemoryStore:
    def __init__(
        self,
        storage: Storage,
        *,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
        clock: Callable[[], datetime] = _utc_now,
        list_page_size: int = DEFAULT_LIST_PAGE_SIZE,
        index_max_bytes: int = DEFAULT_INDEX_MAX_BYTES,
        scope_priority: Sequence[str] = (),
        max_files_per_entity: int | None = DEFAULT_MAX_FILES_PER_ENTITY,
    ) -> None: ...

    @property
    def max_files_per_entity(self) -> int | None: ...
```

- Validation: after `index_max_bytes`'s check, `max_files_per_entity is not None and max_files_per_entity <= 0` raises `ValueError("max_files_per_entity must be positive or None")`. All existing `TypeError`s still precede it.
- `write_file(path, content, metadata, None, source=...)`, check order: invalid path → `NotFoundError(INVALID_PATH)`; empty source → `ValueError`; oversize → `OversizeWriteError`; then, if the cap is not `None`, the cap check; then the conditional put as today.
- Cap check: `parts = parse_path(path)`, `prefix = build_prefix(parts.scope, parts.entity_id)`. Loop `Storage.list_page(prefix, start_after, limit - count)`, adding the number of returned keys with `is_valid_path(key)`, advancing `start_after` to the last returned key, stopping when `count >= limit` or a page returns fewer keys than requested. If `count >= limit`: `obj = storage.get(path)`; if `obj` is not `None`, check its metadata with `metadata_from_map` and raise `VersionConflictError(path, content, obj.version)`; otherwise raise `FileQuotaExceededError(path, limit)`.
- A private helper (e.g. `_entity_at_cap(path, limit) -> bool`) holds the loop; it is not public API.
- `write_file` replace, `append_line`, `replace_fact`, `delete_file`, `read_file`, `list_prefix`, `get_memory_index`: unchanged.

### `wenchang.tools`

No logic change. `render_error(FileQuotaExceededError(...))` already renders `error`, `category`, `message`, `limit`, and `scope`/`area`/`name` from `path`, and no `path`. A test pins it.

### Unchanged

`Storage`, `InMemoryStorage`, `GcsStorage`, `TransportClient`, `InProcessClient` (constructor-only setting; `InProcessClient` passes through), `testing.TransportConformance` (no new fixture; see ADR 0039), `prompts`, `mcp`, `evals` (default cap applies).

## Tests (by file)

- `tests/test_errors.py` (or the existing errors test module): constructor, attributes, category, exact message for a parseable path and fallback for an unparseable one, `ValueError` for `limit` 0 and -1, no entity ID in the message.
- `tests/test_core_file_cap.py` (new): spec User Stories 1–4 and 6 against `MemoryStore(InMemoryStorage(), max_files_per_entity=3)` (and 500 / `None` for the default and disabled cases), plus the edge cases: oversize at the cap raises `OversizeWriteError`; corrupt metadata on another file does not block a create (cap counts via `list_page`); create-on-existing at the cap raises `VersionConflictError`.
- `tests/test_tools.py` (or a new tools test): User Story 5 scenario 3.
- Integration (`tests/integration/`, marker `integration`): one test that the cap is enforced over `GcsStorage` (create at cap fails, delete frees a slot), since the count uses `list_page`.

## Docs

- `docs/adr/0039-file-count-cap-per-entity.md`: setting location, default 500 / `None`, entity = `{scope}/{entity_id}/` including `system/`, well-formed keys only, only creates checked, new recoverable error vs. reusing `OversizeWriteError`, enforcement in `core` vs. tools, soft cap under concurrency, counting cost (≤ `limit` keys listed per create), conformance suite unchanged.
- ARCHITECTURE.md: `core` entry (constructor, property, create check), `errors` entry (new kind), Key invariants (new bullet beside the byte ceiling), error taxonomy (recoverable list).
