# Implementation Plan: append_line

**Linear issue**: AIE-1036 | **Branch**: `AIE-1036-append-line` | **Date**: 2026-09-29 | **Spec**: [spec.md](spec.md)

## Summary

Add `MemoryStore.append_line`, a version-guarded read → check → append →
`put_if_version` over the existing `Storage` protocol, with no automatic
re-apply. No storage, path, or file-format changes.

## Technical Context

Python ≥ 3.12; pytest (`unit` marker); pyright strict; ruff. Unit tests over
`InMemoryStorage`, plus thin storage wrappers that run a callback before
delegating `put_if_version` (same technique as the `replace_fact`
stale-version tests).

## Constitution Check

| Principle | Status |
| --------- | ------ |
| I. Tests-first | T1 test-writer → implementer |
| IV. Strict typing | New signature fully annotated |
| V. Storage only through interface | Uses `get` / `put_if_version` only |
| VI. Spec fidelity | Design change (required token), Notion updated to match → ADR 0011 |
| VII. Architecture documented | New public method + concurrency semantics → ARCHITECTURE.md + ADR 0011 |
| VIII. Traceability | Test docstrings reference AIE-1036 |

**Decisions to record in ADR 0011:** `append_line` takes a required
`expected_version`, which deviates from Notion Section 5 and reverses the
"appends commute" rationale in exchange for retry safety. There is no
automatic re-apply on a stale token. After a precondition failure, the
store re-reads and returns success if the stored bytes and metadata equal
what it wrote (a backend-level retry of its own landed write). Missing file
→ `FILE_ABSENT` rather than create. `line` must parse as one fact line. A
separator is inserted when content lacks a trailing newline. Notes that the
Section 10.2 "append commutativity" conformance clause becomes "concurrent
appends: one lands, the other conflicts and lands on retry" (AIE-1045).

## Public interface

### `src/wenchang/core.py`

```python
class MemoryStore:
    def append_line(
        self,
        path: str,
        line: str,
        expected_version: VersionToken,
        *,
        source: str,
    ) -> MemoryFile:
        """Append one fact line to the existing file at `path`, if it is at `expected_version`."""
```

Errors, in check order:

| Condition | Raised | Storage consulted? |
| --------- | ------ | ------------------ |
| `not is_valid_path(path)` | `NotFoundError(path, NotFoundReason.INVALID_PATH)` | no |
| `parse_fact(line) is None` | `ValueError` | no |
| `source == ""` | `ValueError` | no |
| no object at `path` | `NotFoundError(path, NotFoundReason.FILE_ABSENT)` | yes |
| `obj.version != expected_version` | `VersionConflictError(path, content, obj.version)` | yes |
| encoded new content `> max_file_bytes` | `OversizeWriteError(path, size, limit)` | yes |
| precondition failed, stored ≠ what was written | `VersionConflictError(path, current_content, current_version)` | yes |
| precondition failed, file now absent | `NotFoundError(path, NotFoundReason.FILE_ABSENT)` | yes |
| corrupt metadata / backend error | `MetadataFormatError` / `BackendUnavailableError` propagate | yes |

Returns `MemoryFile(path, content=new_content, metadata=stamped,
version=new_version)`.

Algorithm:

```text
1. validate path, line, source (table above).
2. obj = storage.get(path); None → FILE_ABSENT
   content = obj.data.decode("utf-8")
   obj.version != expected_version → VersionConflictError(path, content, obj.version)
   metadata = metadata_from_map(obj.metadata)
3. sep = "\n" if content and not content.endswith("\n") else ""
   new_content = content + sep + line + "\n"; data = new_content.encode("utf-8")
   size check → OversizeWriteError
4. stamped = replace(metadata, sources=metadata.sources | {source}, last_updated=clock())
   meta_map = metadata_to_map(stamped)
5. try: v = storage.put_if_version(path, data, meta_map, expected_version)
   except PreconditionFailedError:
       cur = storage.get(path); None → FILE_ABSENT
       if cur.data == data and cur.metadata == meta_map:
           return MemoryFile(path, new_content, stamped, cur.version)
       raise VersionConflictError(path, cur.data.decode("utf-8"), cur.version)
6. return MemoryFile(path, new_content, stamped, v)
```

## Test layout

- `tests/test_core_append_line.py` (new, unit) over `InMemoryStorage`,
  reusing the `_fixed_clock` / `_metadata` / `_seed` / `_new_store` helper
  style from `tests/test_core_replace_fact.py`. It adds a wrapper storage
  that runs a callback (another write) before delegating `put_if_version`,
  and one whose `put_if_version` performs the real write and then raises
  `PreconditionFailedError` (simulating a lost response followed by a
  retried 412). A stub raises `BackendUnavailableError`.

## Project Structure

```text
specs/AIE-1036-append-line/   spec.md plan.md tasks.md review-spec.md
src/wenchang/core.py          # append_line
tests/test_core_append_line.py
```

## Complexity Tracking

None.
