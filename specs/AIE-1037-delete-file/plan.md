# Implementation Plan: delete_file

**Linear issue**: AIE-1037 | **Branch**: `AIE-1037-delete-file` | **Date**: 2026-09-29 | **Spec**: [spec.md](spec.md)

## Summary

Add `Storage.delete_if_version` to the storage protocol and both backends,
then `MemoryStore.delete_file`: validate → read → version check →
`delete_if_version`, with a re-read on precondition failure to choose between
a conflict and not-found.

## Technical Context

Python ≥ 3.12; pytest (`unit` / `integration` markers); pyright strict; ruff.
Storage behavior is covered by the shared `StorageConformance` suite
(`tests/storage_conformance.py`), subclassed by `tests/test_storage_memory.py`
(unit) and `tests/integration/test_storage_gcs.py` (fake-gcs-server). Core
tests run over `InMemoryStorage` with wrapper storages that run a callback
before delegating `delete_if_version`.

## Constitution Check

| Principle | Status |
| --------- | ------ |
| I. Tests-first | T1, T2 each test-writer → implementer |
| IV. Strict typing | New signatures fully annotated |
| V. Storage only through interface | New protocol method; core uses `get` / `delete_if_version` only |
| VI. Spec fidelity | Matches Notion Section 5; no deviation |
| VII. Architecture documented | Storage protocol change + new public method → ARCHITECTURE.md + ADR 0012 |
| VIII. Traceability | Test docstrings reference AIE-1037 |

**Decisions to record in ADR 0012:** the storage protocol gains
`delete_if_version(key, expected)`, with no unconditional delete. An absent
object raises `PreconditionFailedError`, the same as a version mismatch, so the
protocol needs no new exception, and core tells the two apart by re-reading.
`delete_file` returns `None` and takes no `source`. After a precondition
failure, "now absent" raises `FILE_ABSENT`, because a landed-then-retried
delete can't be told apart from someone else's delete and the end state is
the same.

## Public interface

### `src/wenchang/storage/__init__.py` — `Storage` protocol

```python
class Storage(Protocol):
    def delete_if_version(self, key: str, expected: VersionToken) -> None:
        """Delete the object at `key` only if it is at `expected`.

        Raises PreconditionFailedError if the object is absent or at a
        different version.
        """
```

### `src/wenchang/storage/memory.py` — `InMemoryStorage.delete_if_version`

Removes `key` from `_objects` if its token equals `expected`; otherwise
raises `PreconditionFailedError(key)`. Does not reuse tokens.

### `src/wenchang/storage/gcs.py` — `GcsStorage.delete_if_version`

```text
if not _GENERATION_TOKEN_RE.fullmatch(expected): raise PreconditionFailedError(key)
blob = bucket.blob(key)
try: blob.delete(if_generation_match=int(expected))
except (PreconditionFailed, NotFound): raise PreconditionFailedError(key)
except Exception: _map_backend_error → BackendUnavailableError, else re-raise
```

`NotFound` maps to `PreconditionFailedError` because it is what GCS returns
when the object is absent, including on a client-level retry after the
first delete landed.

### `src/wenchang/core.py`

```python
class MemoryStore:
    def delete_file(self, path: str, expected_version: VersionToken) -> None:
        """Delete the file at `path`, if it is at `expected_version`."""
```

Errors, in check order:

| Condition | Raised | Storage consulted? |
| --------- | ------ | ------------------ |
| `not is_valid_path(path)` | `NotFoundError(path, NotFoundReason.INVALID_PATH)` | no |
| no object at `path` | `NotFoundError(path, NotFoundReason.FILE_ABSENT)` | yes |
| `obj.version != expected_version` | `VersionConflictError(path, content, obj.version)` | yes |
| precondition failed, file now absent | `NotFoundError(path, NotFoundReason.FILE_ABSENT)` | yes |
| precondition failed, file present | `VersionConflictError(path, cur_content, cur.version)` | yes |
| backend error | `BackendUnavailableError` propagates | yes |

Algorithm:

```text
1. validate path → INVALID_PATH
2. obj = storage.get(path); None → FILE_ABSENT
   obj.version != expected_version → VersionConflictError(path, obj.data.decode("utf-8"), obj.version)
3. try: storage.delete_if_version(path, expected_version)
   except PreconditionFailedError:
       cur = storage.get(path); None → FILE_ABSENT
       raise VersionConflictError(path, cur.data.decode("utf-8"), cur.version)
4. return None
```

Metadata is not parsed. Deleting a file with corrupt metadata succeeds.

## Test layout

- `tests/storage_conformance.py`: add `delete_if_version` cases (spec US4.1–5)
  to `StorageConformance`, so they run for both backends.
- `tests/integration/test_storage_gcs.py`: GCS-only cases (US4.6: malformed
  token with no client call, backend-error mapping), following the existing
  `put_if_version` GCS-only tests.
- `tests/test_core_delete_file.py` (new, unit) over `InMemoryStorage`, reusing
  the `_fixed_clock` / `_metadata` / `_seed` / `_new_store` helper style from
  `tests/test_core_append_line.py`. It adds a wrapper that runs a callback
  (another write, or a delete) before delegating `delete_if_version`, and a
  stub that raises `BackendUnavailableError`.
- Any existing test doubles that structurally implement `Storage` gain a
  `delete_if_version` so pyright strict still passes. The test-writer owns
  that change, and no test behavior changes.

## Project Structure

```text
specs/AIE-1037-delete-file/            spec.md plan.md tasks.md review-spec.md
src/wenchang/storage/__init__.py       # Storage.delete_if_version
src/wenchang/storage/memory.py         # InMemoryStorage.delete_if_version
src/wenchang/storage/gcs.py            # GcsStorage.delete_if_version
src/wenchang/core.py                   # MemoryStore.delete_file
tests/storage_conformance.py
tests/integration/test_storage_gcs.py
tests/test_core_delete_file.py
```

## Complexity Tracking

None.
