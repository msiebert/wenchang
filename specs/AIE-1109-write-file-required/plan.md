# Implementation Plan: write_file required `source`

**Linear issue**: AIE-1109 | **Branch**: `AIE-1109-write-file-source` | **Date**: 2026-09-30 | **Spec**: [spec.md](spec.md)

## Summary

Add a required keyword-only `source` to `MemoryStore.write_file`. Create
stamps `metadata.sources ∪ {source}`; replace reads the current object,
checks its version, and stamps `stored.sources ∪ metadata.sources ∪
{source}` in one `put_if_version`. No storage, path, or file-format
changes. `append_line` and `replace_fact` are unchanged.

## Technical Context

Python ≥ 3.12; pytest (`unit` marker); pyright strict; ruff. Unit tests over
`InMemoryStorage`, plus a storage wrapper that runs a callback (another
write) before delegating `put_if_version`, as in the `append_line` tests.

## Constitution Check

| Principle | Status |
| --------- | ------ |
| I. Tests-first | T1 test-writer → implementer |
| IV. Strict typing | Signature fully annotated |
| V. Storage only through interface | `get` / `put_if_version` only |
| VI. Spec fidelity | Implements Notion §4 "set of surfaces that have written"; the union rule is a decision → ADR 0013 |
| VII. Architecture documented | Public signature + replace semantics change → ARCHITECTURE.md + ADR 0013 |
| VIII. Traceability | New test docstrings reference AIE-1109 |

**Decisions to record in ADR 0013:** `source` is required and keyword-only,
matching ADR 0009. Stored `sources` only grows: caller-supplied
`metadata.sources` is unioned in (not ignored, not rejected). Replace gains
a read before the conditional write so the stored set can be unioned; the
version is checked against that read. Corrupt stored metadata on replace
propagates rather than being overwritten. No automatic re-apply.

## Public interface

### `src/wenchang/core.py`

```python
class MemoryStore:
    def write_file(
        self,
        path: str,
        content: str,
        metadata: FileMetadata,
        expected_version: VersionToken | None,
        *,
        source: str,
    ) -> MemoryFile:
        """Write the memory file at `path`, creating or replacing it."""
```

`FileMetadata` (unchanged): `description: str`, `aliases: tuple[str, ...]`,
`sources: frozenset[str]`, `last_updated: datetime`.

Errors, in check order:

| Condition | Raised | Storage consulted? |
| --------- | ------ | ------------------ |
| `not is_valid_path(path)` | `NotFoundError(path, NotFoundReason.INVALID_PATH)` | no |
| `source == ""` | `ValueError` | no |
| encoded `content` `> max_file_bytes` | `OversizeWriteError(path, size, limit)` | no |
| naive clock datetime | `ValueError` (from `FileMetadata`) | no |
| create: object already exists | `VersionConflictError(path, current_content, current_version)` | yes |
| replace: no object at `path` | `NotFoundError(path, NotFoundReason.FILE_ABSENT)` | yes |
| replace: `obj.version != expected_version` | `VersionConflictError(path, content, obj.version)` | yes |
| replace: stored metadata corrupt | `MetadataFormatError` propagates | yes |
| replace: precondition failed at write | `VersionConflictError` with content/version re-read after failure; `FILE_ABSENT` if now gone | yes |
| backend error | `BackendUnavailableError` propagates | yes |

Returns `MemoryFile(path, content, metadata=stamped, version=new_version)`
where `stamped.sources` is the union actually stored.

Algorithm:

```text
1. validate path, source, size (table above).
2. if expected_version is None:
       sources = metadata.sources | {source}
   else:
       obj = storage.get(path); None → FILE_ABSENT
       obj.version != expected_version →
           metadata_from_map(obj.metadata)  # corrupt metadata propagates
           VersionConflictError(path, obj.data.decode(), obj.version)
       stored = metadata_from_map(obj.metadata)
       sources = stored.sources | metadata.sources | {source}
3. stamped = replace(metadata, sources=sources, last_updated=clock())
4. try: v = storage.put_if_version(path, data, metadata_to_map(stamped), expected_version)
   except PreconditionFailedError: existing handling (re-get; None → FILE_ABSENT;
       else VersionConflictError with current content/version)
5. return MemoryFile(path, content, stamped, v)
```

## Test layout

- `tests/test_core_write_file.py`: add `source=` to every existing call
  (46 sites); update any replace assertion that expects the caller's
  `sources` verbatim to the union; add new tests for US1–US3.
- `tests/test_core_delete_file.py`: add `source=` to its one `write_file`
  call.
- Any other `write_file` call under `tests/` found by grep gets `source=`.

## Project Structure

```text
specs/AIE-1109-write-file-required/   spec.md plan.md tasks.md review-spec.md
src/wenchang/core.py                  # write_file
tests/test_core_write_file.py
tests/test_core_delete_file.py
```

## Complexity Tracking

None.
