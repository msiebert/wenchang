# Implementation Plan: replace_fact

**Linear issue**: AIE-1034 | **Branch**: `AIE-1034-replace-fact` | **Date**: 2026-09-28 | **Spec**: [spec.md](spec.md)

## Summary

`wenchang.core.MemoryStore` gains `replace_fact(path, old_string,
new_string, expected_version) -> MemoryFile`. No storage or error-module
changes: it uses `Storage.get`, `Storage.put_if_version`, and the existing
`ReplaceFactMatchError`, `VersionConflictError`, `OversizeWriteError`, and
`NotFoundError`.

## Technical Context

Python ≥ 3.12; pytest (`@pytest.mark.unit`); pyright strict; ruff. Core
depends on the `Storage` protocol only.

## Constitution Check

| Principle | Status |
| --------- | ------ |
| I. Tests-first | T1, T2 each test-writer → implementer |
| IV. Strict typing | Signature fully annotated |
| V. Storage only through interface | Uses `get` / `put_if_version` only |
| VI. Spec fidelity | "Genuine overlap" interpretation → ADR |
| VII. Architecture documented | New public method → ARCHITECTURE.md + ADR |
| VIII. Traceability | Test docstrings reference AIE-1034 |

**Decisions to record in an ADR:** the overlap test (anchor still unique in
current content), stale-call escalation as `VersionConflictError`,
overlapping match counting, empty anchor → `ValueError`, 3-attempt budget,
metadata carried over from storage, required keyword-only `source` added
to `sources` (deviation from the Notion signature), retry non-idempotence when
`new_string` contains `old_string`.

## Public interface

### `src/wenchang/core.py`

```python
class MemoryStore:
    def replace_fact(
        self,
        path: str,
        old_string: str,
        new_string: str,
        expected_version: VersionToken,
        *,
        source: str,
    ) -> MemoryFile: ...
```

Algorithm:

```text
1. not is_valid_path(path) → NotFoundError(path, INVALID_PATH). No storage call.
2. old_string == "" or source == "" → ValueError. No storage call.
3. Repeat up to 3 attempts:
   a. obj = storage.get(path); None → NotFoundError(path, FILE_ABSENT).
      content = obj.data.decode("utf-8"); metadata = metadata_from_map(obj.metadata)
      (UnicodeDecodeError / MetadataFormatError / BackendUnavailableError propagate).
   b. count = number of start indices i where content.startswith(old_string, i).
   c. If count != 1:
        obj.version == expected_version → ReplaceFactMatchError(path, content, obj.version, count)
        otherwise                       → VersionConflictError(path, content, obj.version)
   d. new_content = content.replace(old_string, new_string, 1)
      data = new_content.encode("utf-8"); len(data) > max_file_bytes →
        OversizeWriteError(path, len(data), max_file_bytes)
   e. stamped = dataclasses.replace(metadata, sources=metadata.sources | {source},
                                    last_updated=clock())  (naive → ValueError)
   f. version = storage.put_if_version(path, data, metadata_to_map(stamped), obj.version)
      success → return MemoryFile(path, new_content, stamped, version)
      PreconditionFailedError → next attempt
4. Attempts exhausted → VersionConflictError(path, <last read content>, <last read version>).
```

The put is guarded on the version just read (`obj.version`), not the
caller's `expected_version`; the caller's token only decides which error a
non-unique match raises. Token comparison is string equality — never parsed.

Error mapping on a later attempt follows the same rule: the re-read version
differs from `expected_version`, so a non-unique match raises
`VersionConflictError`.

`_MAX_REPLACE_ATTEMPTS = 3` is a module-level private constant.

## Test layout

`tests/test_core_replace_fact.py` (new, unit) over `InMemoryStorage` with a
fixed clock, reusing the helper style of `tests/test_core_write_file.py`
(`_metadata`, `_seed`, `_new_store`). Concurrency cases use a small stub /
wrapper storage that performs a second write between `get` and
`put_if_version` (once, or on every attempt), and a stub that raises on
demand.

## Project Structure

```text
specs/AIE-1034-replace-fact-unique/  spec.md plan.md tasks.md review-spec.md
src/wenchang/core.py                 # replace_fact
tests/test_core_replace_fact.py      # new
```

## Complexity Tracking

None.
