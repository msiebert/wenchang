# Implementation Plan: write_file

**Linear issue**: AIE-1033 | **Branch**: `AIE-1033-write-file` | **Date**: 2026-09-28 | **Spec**: [spec.md](spec.md)

## Summary

- `wenchang.storage` — add `PreconditionFailedError` and a conditional put,
  `Storage.put_if_version(key, data, metadata, expected)`, to the protocol,
  `InMemoryStorage`, and `GcsStorage`. `put` stays unconditional.
- `wenchang.core` — `MemoryStore` gains keyword-only `max_file_bytes`
  (default 16384) and `clock` (default current UTC) constructor options, and
  `write_file(path, content, metadata, expected_version) -> MemoryFile`.

## Technical Context

**Language/Version**: Python ≥ 3.12

**Primary Dependencies**: `google-cloud-storage` (only in
`wenchang/storage/gcs.py`); stdlib otherwise

**Storage**: GCS via `GcsStorage`; `InMemoryStorage` for unit tests

**Testing**: pytest; `@pytest.mark.unit` except GCS conformance
(`@pytest.mark.integration`, fake-gcs-server); pyright strict; ruff

**Project Type**: library

**Constraints**: FR-008 — `google.cloud` imported only in `storage/gcs.py`;
only `GcsStorage` converts a `VersionToken` to a generation. `core` depends
on the `Storage` protocol, never a concrete class.

## Constitution Check

| Principle | Status |
| --------- | ------ |
| I. Tests-first | Each task is test-writer → implementer |
| IV. Strict typing | All new signatures fully annotated |
| V. Storage only through interface; fake matches GCS preconditions | Conditional put added to the protocol; one conformance suite runs against fake and GCS, including the "create only if absent" and unrecognized-token cases |
| VI. Spec fidelity | Interpretations below go in an ADR |
| VII. Architecture documented | Storage protocol + `MemoryStore` API change → ARCHITECTURE.md + ADR |
| VIII. Traceability | Test docstrings reference AIE-1033 |
| X. Ask, don't guess | `last-updated` stamping raised at the spec checkpoint |

**Decisions to record in an ADR:**

1. `expected_version=None` means "create; must not exist" (GCS
   `ifGenerationMatch=0`). The parameter is required, with no default, so
   every caller states which one it means.
2. A non-`None` token against an absent file raises
   `NotFoundError(FILE_ABSENT)`, not a conflict.
3. An unrecognized token is a mismatch (conflict), never a parse error. In
   `GcsStorage`, a token that is not the canonical decimal form of a
   positive integer fails the precondition without calling GCS, so `"0"`
   cannot be read as "must not exist".
4. The byte ceiling counts the content's UTF-8 bytes only, is inclusive
   (exactly the limit is allowed), and is checked before storage.
5. The core layer stamps `last_updated` from an injectable clock,
   overriding the caller's value.
6. The storage layer signals a failed precondition with its own
   `PreconditionFailedError` (not a `WenchangError`). `core` translates it
   into `VersionConflictError` by fetching the current object.

## Public interface

Nothing is re-exported from `wenchang` top level.

### `src/wenchang/storage/__init__.py` (additions)

```python
class PreconditionFailedError(Exception):
    def __init__(self, key: str) -> None: ...

    key: str


class Storage(Protocol):
    def get(self, key: str) -> StoredObject | None: ...  # unchanged
    def put(
        self, key: str, data: bytes, metadata: Mapping[str, str]
    ) -> VersionToken: ...  # unchanged

    def put_if_version(
        self,
        key: str,
        data: bytes,
        metadata: Mapping[str, str],
        expected: VersionToken | None,
    ) -> VersionToken: ...

    # expected is None: commit only if no object exists at `key`.
    # expected is a token: commit only if the current object's version equals it.
    # Otherwise raise PreconditionFailedError(key) and change nothing (including
    # when `expected` is a token and no object exists).
    # On success: same guarantees as put (atomic, new token, mapping copied).
    # May raise BackendUnavailableError.
```

`PreconditionFailedError` subclasses `Exception` directly: it is an internal
storage signal, never surfaced to agents.

### `src/wenchang/storage/memory.py`

`InMemoryStorage.put_if_version`: compare `expected` against the stored
object's token by string equality (`None` ↔ absent); on match, behave
exactly as `put` (same shared counter).

### `src/wenchang/storage/gcs.py`

`GcsStorage.put_if_version`:

- `expected is None` → generation `0`.
- Otherwise the token must match `^[1-9][0-9]*$`; if not, raise
  `PreconditionFailedError(key)` without any client call. Else generation =
  `int(expected)`.
- `blob = bucket.blob(key)`; `blob.metadata = dict(metadata)`;
  `blob.upload_from_string(data, content_type="text/markdown; charset=utf-8",
  if_generation_match=generation)`; return
  `VersionToken(str(blob.generation))`.
- `google.api_core.exceptions.PreconditionFailed` →
  `PreconditionFailedError(key)`. Timeout/unavailable mapping as for `get`
  and `put`; anything else propagates.

### `src/wenchang/core.py`

```python
from collections.abc import Callable
from datetime import datetime

DEFAULT_MAX_FILE_BYTES: int = 16 * 1024


class MemoryStore:
    def __init__(
        self,
        storage: Storage,
        *,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
        clock: Callable[[], datetime] = ...,  # default: datetime.now(timezone.utc)
    ) -> None: ...

    # max_file_bytes <= 0 → ValueError.

    def read_file(self, path: str) -> MemoryFile: ...  # unchanged

    def write_file(
        self,
        path: str,
        content: str,
        metadata: FileMetadata,
        expected_version: VersionToken | None,
    ) -> MemoryFile: ...

    # 1. not is_valid_path(path) → NotFoundError(path, INVALID_PATH); no storage call.
    # 2. data = content.encode("utf-8"); len(data) > max_file_bytes →
    #    OversizeWriteError(path, len(data), max_file_bytes); no storage call.
    # 3. stamped = dataclasses.replace(metadata, last_updated=clock());
    #    a naive datetime from clock → ValueError from FileMetadata.__post_init__
    #    (dataclasses.replace re-runs it); no storage call.
    # 4. version = storage.put_if_version(path, data, metadata_to_map(stamped),
    #    expected_version).
    # 5. On PreconditionFailedError: obj = storage.get(path);
    #    obj is None → NotFoundError(path, FILE_ABSENT);
    #    else → VersionConflictError(path, obj.data.decode("utf-8"), obj.version).
    #    MetadataFormatError / UnicodeDecodeError / BackendUnavailableError propagate.
    # 6. return MemoryFile(path, content, stamped, version).
```

## Test layout

- `tests/storage_conformance.py` — add conditional-put cases to
  `StorageConformance` (spec US7); they run automatically in
  `tests/test_storage_memory.py` (unit) and
  `tests/integration/test_storage_gcs.py` (integration).
- `tests/test_storage_gcs_errors.py` — add stubbed-`Blob` cases:
  `if_generation_match` passed (0 for `None`, int for a token), non-canonical
  tokens (`"abc"`, `"0"`, `"-1"`, `"007"`, `""`) raise
  `PreconditionFailedError` with no upload call, `PreconditionFailed` →
  `PreconditionFailedError`, timeout/unavailable mapping on the conditional
  upload.
- `tests/test_core_write_file.py` — new; `MemoryStore.write_file` over
  `InMemoryStorage` with a fixed clock, plus stub storages that raise
  (unit).

## Project Structure

```text
specs/AIE-1033-write-file-full/
├── spec.md
├── plan.md
├── tasks.md
├── review-spec.md
└── checklists/requirements.md

src/wenchang/
├── core.py               # write_file, constructor options
└── storage/
    ├── __init__.py       # PreconditionFailedError, put_if_version
    ├── memory.py         # put_if_version
    └── gcs.py            # put_if_version

tests/
├── storage_conformance.py        # conditional-put cases
├── test_storage_gcs_errors.py    # conditional-put mapping cases
└── test_core_write_file.py       # new
```

## Complexity Tracking

None.
