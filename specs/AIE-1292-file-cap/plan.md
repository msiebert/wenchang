# Implementation Plan: Cap the number of files per entity

**Linear**: AIE-1292 | **Spec**: [spec.md](spec.md) | **ADR**: 0039

## Summary

Add a per-entity file-count cap to `MemoryStore`, checked only when `write_file` creates a file outside `system/`, raising a new recoverable `FileQuotaExceededError`. No change to the `Storage` protocol or `TransportClient`; the tool layer gains one docstring sentence.

## Public interface

### `wenchang.errors`

```python
class FileQuotaExceededError(RecoverableError):
    """A create would put an entity over its file-count limit."""

    def __init__(self, path: str, limit: int) -> None: ...
    path: str
    limit: int
```

- `limit < 1` raises `ValueError("limit must be positive")`, before any attribute is set.
- When `parse_path(path)` succeeds (`loc = _location(path)`, `scope = parse_path(path).scope`), the message is
  `f"Cannot create a new file at {loc}: memory in scope {scope} is at its limit of {limit} files (system/ files not counted). Add this content to an existing file instead (append_line, replace_fact, or write_file with that file's version), or merge related files into one and delete the merged ones with delete_file, then retry. {RecoverableError.guidance}"`.
- When it does not parse, the message is
  `f"Cannot create a new file: memory for this entity is at its limit of {limit} files (system/ files not counted). Add this content to an existing file instead (append_line, replace_fact, or write_file with that file's version), or merge related files into one and delete the merged ones with delete_file, then retry. {RecoverableError.guidance}"`.

Literal for `FileQuotaExceededError("user/u1/notes/new.md", 3)`:

```
Cannot create a new file at scope user, area notes, name new: memory in scope user is at its limit of 3 files (system/ files not counted). Add this content to an existing file instead (append_line, replace_fact, or write_file with that file's version), or merge related files into one and delete the merged ones with delete_file, then retry. This is normal coordination, not an error the user needs to know about. Use the details above to correct the call and retry in the same turn, without asking the user.
```

Literal for `FileQuotaExceededError("not-a-path", 3)`:

```
Cannot create a new file: memory for this entity is at its limit of 3 files (system/ files not counted). Add this content to an existing file instead (append_line, replace_fact, or write_file with that file's version), or merge related files into one and delete the merged ones with delete_file, then retry. This is normal coordination, not an error the user needs to know about. Use the details above to correct the call and retry in the same turn, without asking the user.
```

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

- Validation: after `index_max_bytes`'s check, `max_files_per_entity is not None and max_files_per_entity <= 0` raises `ValueError("max_files_per_entity must be positive or None")`. All existing `TypeError`s still precede it. No type check; `bool` is accepted as for `max_file_bytes`.
- `write_file(path, content, metadata, None, source=...)`, check order: invalid path → `NotFoundError(INVALID_PATH)`; empty source → `ValueError`; oversize → `OversizeWriteError`; then, if the cap is not `None` and `parse_path(path).area != INDEX_SYSTEM_AREA`, the cap check; then the conditional put as today.
- Cap check: `parts = parse_path(path)`, `prefix = build_prefix(parts.scope, parts.entity_id)`. Loop `Storage.list_page(prefix, start_after, max(limit - count, self._list_page_size))`; for each returned key, count it iff `is_valid_path(key) and parse_path(key).area != INDEX_SYSTEM_AREA`; advance `start_after` to the last returned key; stop when `count >= limit` or a page returns fewer keys than requested. Keys listed per create: at most `limit` + uncounted keys under the prefix + `list_page_size`.
- At the cap: `obj = storage.get(path)`. If `obj` is not `None`: `content = obj.data.decode("utf-8")`, then `metadata_from_map(obj.metadata)` (so `UnicodeDecodeError`, then `MetadataFormatError`, propagate as on the existing conflict path), then raise `VersionConflictError(path, content, obj.version)`. If `obj` is `None` (absent, including a file that vanished after the count): raise `FileQuotaExceededError(path, limit)`.
- A private helper (e.g. `_at_file_cap(path, limit) -> bool`) holds the loop; it is not public API.
- `write_file` replace, `append_line`, `replace_fact`, `delete_file`, `read_file`, `list_prefix`, `get_memory_index`: unchanged.

### `wenchang.tools`

- No logic change. `render_error(FileQuotaExceededError(...))` already renders `error`, `category`, `message`, `limit`, and `scope`/`area`/`name` from `path`, and no `path`.
- `MemoryTools.write_file` docstring: after the byte-ceiling sentence (tools.py:232-233), add one sentence, e.g. "Creating a file fails once the scope holds its file limit; add to an existing file, or merge files and delete the extras, then retry." Exact wording is the implementer's; it must not contain `.md` or `is read-only` (`test_shared_mechanics_stated_once`, `tests/test_tools_descriptions.py:289`).

### Unchanged

`Storage`, `InMemoryStorage`, `GcsStorage`, `TransportClient`, `InProcessClient` (constructor-only setting), `testing.TransportConformance` (no new fixture; see ADR 0039), `prompts`, `mcp`, `evals` (default cap applies; `reference_store` gains no parameter — tests build `MemoryStore` directly when they need a cap).

## Tests (by file)

Every new test docstring references AIE-1292.

- `tests/test_errors.py`: US5 scenarios 1–2 and US6 scenario 3 — constructor, attributes, category, both exact literals, `ValueError` for `limit` 0 and -1, no entity ID in the message.
- `tests/test_core_file_cap.py` (new): US1–US4 and US6 scenarios 1–2 against `MemoryStore(InMemoryStorage(), max_files_per_entity=3)` (500 / `None` for default and disabled); edge cases: oversize at the cap raises `OversizeWriteError`; corrupt metadata on another file does not block a create; create-on-existing at the cap raises `VersionConflictError`; vanished file (storage wrapper whose `get` returns `None`) raises `FileQuotaExceededError`; corrupt metadata / non-UTF-8 content on the same path propagates `MetadataFormatError` / `UnicodeDecodeError`; a test with `list_page_size=1` and several `system/` keys preceding counted keys still counts correctly.
- `tests/test_core_write_file.py`: `_StubStorage.list_page` (line 107) raises `NotImplementedError`; change it to return `[]` so the four create tests at lines 515, 529, 563, 582 keep passing under the default cap. Their assertions stay unchanged, and they do not set `max_files_per_entity=None`.
- `tests/test_tools.py` (or `test_tools_end_to_end.py`): US5 scenarios 3–5 (render, reference-seed boundary, role-gated check order). Build the store as `MemoryStore(InMemoryStorage(), scope_priority=REFERENCE_SCOPE_PRIORITY, max_files_per_entity=...)` and seed with `seed_reference_memory`.
- `tests/test_tools_descriptions.py`: US5 scenario 7.
- `tests/test_mcp_server.py`: US5 scenario 6.
- `tests/integration/`: the cap over `GcsStorage` against fake-gcs-server (create at cap fails, a `system/` file does not count, delete frees a slot).

## Docs

- `docs/adr/0039-file-count-cap-per-entity.md`: setting location, default 500 / `None`, entity = `{scope}/{entity_id}/` excluding `system/` (count and enforcement) and malformed keys, only creates checked, new recoverable error vs. reusing `OversizeWriteError`, enforcement in `core` vs. tools, soft cap under concurrency, counting cost (≤ `limit` + uncounted keys + one page per create), conformance gap (error covered by the parity contract, not exercised; no cap fixture).
- ARCHITECTURE.md: `core` entry (constructor, property, create check), `errors` entry (new kind), `tools` entry (docstring sentence, if docstrings are described), Key invariants (new bullet beside the byte ceiling), error taxonomy (recoverable list).
- `docs/product/glossary.md`: "File cap (`max_files_per_entity`)" — per `{scope}/{entity_id}/`, `system/` excluded, default 500, `None` disables.
