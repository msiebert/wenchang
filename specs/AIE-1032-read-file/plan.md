# Implementation Plan: read_file and the storage layer

**Linear issue**: AIE-1032 | **Branch**: `AIE-1032-read-file` | **Date**: 2026-09-25 | **Spec**: [spec.md](spec.md)

## Summary

Add three modules and a storage package:

- `wenchang.paths` — `is_valid_path`, the syntactic check for
  `{scope}/{entity_id}/{area}/{name}.md`.
- `wenchang.storage` — the `Storage` protocol (`get`, `put`) and
  `StoredObject`; `wenchang.storage.memory.InMemoryStorage`; and
  `wenchang.storage.gcs.GcsStorage`, the only module importing
  `google.cloud`.
- `wenchang.core` — `MemoryStore`, holding a `Storage`, with
  `read_file(path) -> MemoryFile`.

## Technical Context

**Language/Version**: Python ≥ 3.12

**Primary Dependencies**: `google-cloud-storage` (already a dependency),
used only in `wenchang/storage/gcs.py`; stdlib otherwise

**Storage**: GCS via `GcsStorage`; `InMemoryStorage` for unit tests

**Testing**: pytest; `@pytest.mark.unit` for everything except the GCS
conformance run, which is `@pytest.mark.integration` against
fake-gcs-server (`make emulator-up`, `STORAGE_EMULATOR_HOST`); pyright
strict; ruff

**Project Type**: library

**Constraints**: FR-008 — `google.cloud` imported only in
`storage/gcs.py`. `core` depends on `storage` (protocol only), `paths`,
`file_format`, `errors`, `version_token`; never on a concrete storage
class.

## Constitution Check

| Principle | Status |
| --------- | ------ |
| I. Tests-first | Each task is test-writer → implementer |
| IV. Strict typing | All public types and functions fully annotated |
| V. Storage only through interface | `core` sees only the `Storage` protocol; one conformance suite runs against fake and GCS |
| VI. Spec fidelity | Interpretations below go in an ADR |
| VII. Architecture documented | New modules `paths`, `storage`, `core` → ARCHITECTURE.md update + ADR |
| VIII. Traceability | Test docstrings reference AIE-1032 |
| IX. Single-issue PR | Storage layer folded into AIE-1032 by the human's decision (no separate issue exists; read_file cannot be tested without it) |

**Decisions to record in an ADR:**

1. The core API is methods on a `MemoryStore` object constructed with a
   `Storage`, not free functions taking storage as an argument: later core
   functions also need configuration (size limit, index cap), and the
   in-process transport wraps one object.
2. `{root}` in the Notion path layout is the storage instance (one GCS
   bucket); paths are relative to it.
3. Paths are exactly four segments; nested areas are not valid.
4. The storage protocol carries `VersionToken` directly. Only `GcsStorage`
   converts it to/from a generation.
5. Corrupt stored objects raise `ValueError` subclasses
   (`MetadataFormatError`, `UnicodeDecodeError`), not taxonomy errors.
6. `put` is unconditional in this issue; AIE-1033 adds a generation-match
   precondition.

## Public interface

Nothing is re-exported from `wenchang` top level.

### `src/wenchang/paths.py`

```python
def is_valid_path(path: str) -> bool: ...


# True iff path.split("/") has exactly 4 segments, each non-empty, none
# equal to "." or "..", none containing "\\" or a control character
# (unicodedata category "Cc"), and the last ends with ".md" and is longer
# than ".md". Unicode, spaces, and mixed case within segments are allowed.
# Never raises. Leading/trailing "/" produce an empty segment → False.
```

| path | valid |
| ---- | ----- |
| `user/u_42/preferences/editor.md` | yes |
| `project/p 1/glossary/café.md` | yes |
| `system/x/system/a.md` | yes |
| `` (empty), `/user/u/a/b.md`, `user/u/a/b.md/`, `user//a/b.md` | no |
| `user/u/a/./b.md`-style (`.` or `..` as any segment) | no |
| `user/u/a/b\\c.md`, `user/u/a/b\tc.md`, `user/u/a/b\nc.md` | no |
| `user/u/b.md` (3 segments), `user/u/a/b/c.md` (5 segments) | no |
| `user/u/a/b.txt`, `user/u/a/b`, `user/u/a/.md`, `user/u/a/b.MD` | no |

### `src/wenchang/storage/__init__.py`

```python
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from wenchang.version_token import VersionToken


@dataclass(frozen=True)
class StoredObject:
    data: bytes
    metadata: Mapping[str, str]
    version: VersionToken


class Storage(Protocol):
    def get(self, key: str) -> StoredObject | None: ...

    # None when no object exists at exactly `key` (no prefix matching).
    # data, metadata, and version always belong to the same write.
    # May raise BackendUnavailableError.

    def put(self, key: str, data: bytes, metadata: Mapping[str, str]) -> VersionToken: ...

    # Unconditionally replaces the object at `key` with data + metadata,
    # atomically. Returns the new version token, which differs from every
    # earlier token for `key`. The caller's mapping is copied.
    # May raise BackendUnavailableError.
```

### `src/wenchang/storage/memory.py`

```python
class InMemoryStorage:  # satisfies Storage structurally
    def __init__(self) -> None: ...
    def get(self, key: str) -> StoredObject | None: ...
    def put(self, key: str, data: bytes, metadata: Mapping[str, str]) -> VersionToken: ...
```

Tokens come from a counter shared across all keys of the instance
(mirroring GCS generations, which are never reused), rendered as
`VersionToken(str(n))`. `get` returns a fresh `dict` copy of metadata, so a
caller mutating it (after a cast) cannot affect stored state.

### `src/wenchang/storage/gcs.py`

```python
from google.cloud.storage import Bucket


class GcsStorage:  # satisfies Storage structurally
    def __init__(self, bucket: Bucket) -> None: ...
    def get(self, key: str) -> StoredObject | None: ...
    def put(self, key: str, data: bytes, metadata: Mapping[str, str]) -> VersionToken: ...
```

- `get`: `bucket.get_blob(key)` (None → return None), then
  `blob.download_as_bytes(if_generation_match=blob.generation)` so data and
  metadata come from the same generation. If the object changed or vanished
  between the two calls (412 / 404 on download), repeat from `get_blob`, up
  to 3 attempts total; after that raise `BackendUnavailableError(UNAVAILABLE)`.
  Version = `VersionToken(str(blob.generation))`; metadata =
  `dict(blob.metadata or {})`.
- `put`: `blob = bucket.blob(key)`; `blob.metadata = dict(metadata)`;
  `blob.upload_from_string(data, content_type="text/markdown; charset=utf-8")`
  (metadata and media in one request); return
  `VersionToken(str(blob.generation))`.
- Error mapping, applied to every client call:
  - `google.api_core.exceptions.DeadlineExceeded`, `GatewayTimeout`,
    `requests.exceptions.Timeout` → `BackendUnavailableError(TIMEOUT, detail)`
  - `ServiceUnavailable`, `InternalServerError`, `BadGateway`,
    `TooManyRequests`, `requests.exceptions.ConnectionError` →
    `BackendUnavailableError(UNAVAILABLE, detail)`
  - anything else propagates unchanged.

### `src/wenchang/core.py`

```python
from dataclasses import dataclass

from wenchang.file_format import FileMetadata
from wenchang.storage import Storage
from wenchang.version_token import VersionToken


@dataclass(frozen=True)
class MemoryFile:
    path: str
    content: str
    metadata: FileMetadata
    version: VersionToken


class MemoryStore:
    def __init__(self, storage: Storage) -> None: ...

    def read_file(self, path: str) -> MemoryFile: ...

    # 1. not is_valid_path(path) → raise NotFoundError(path, INVALID_PATH);
    #    storage is not called.
    # 2. storage.get(path) is None → raise NotFoundError(path, FILE_ABSENT).
    # 3. content = data.decode("utf-8") (strict; UnicodeDecodeError propagates).
    # 4. metadata = metadata_from_map(obj.metadata) (MetadataFormatError propagates).
    # 5. return MemoryFile(path, content, metadata, obj.version).
    # BackendUnavailableError from storage propagates unchanged.
```

The storage key is the path itself.

## Test layout

- `tests/test_paths.py` — `is_valid_path` table (unit).
- `tests/storage_conformance.py` — `StorageConformance`, a class of test
  methods using a `storage: Storage` fixture; no fixture defined here.
- `tests/test_storage_memory.py` — subclasses `StorageConformance`,
  provides `storage` = `InMemoryStorage()` (unit).
- `tests/integration/test_storage_gcs.py` — subclasses
  `StorageConformance`, provides `storage` = `GcsStorage` over a fresh
  uniquely-named bucket on the emulator (integration). Client built with
  `AnonymousCredentials`, `project="test"`, and
  `client_options={"api_endpoint": storage_emulator_host}`.
- `tests/test_storage_gcs_errors.py` — error-mapping and get-retry tests
  against a stubbed `Bucket`/`Blob` (unit; no network).
- `tests/test_core_read_file.py` — `MemoryStore.read_file` over
  `InMemoryStorage`, plus a stub `Storage` that raises (unit). Seed files
  with `storage.put(path, body.encode(), metadata_to_map(meta))`.

## Project Structure

```text
specs/AIE-1032-read-file/
├── spec.md
├── plan.md
├── tasks.md
└── review-spec.md

src/wenchang/
├── paths.py              # new
├── core.py               # new
└── storage/
    ├── __init__.py       # new: Storage, StoredObject
    ├── memory.py         # new: InMemoryStorage
    └── gcs.py            # new: GcsStorage

tests/
├── test_paths.py                 # new
├── storage_conformance.py        # new
├── test_storage_memory.py        # new
├── test_storage_gcs_errors.py    # new
├── test_core_read_file.py        # new
└── integration/
    └── test_storage_gcs.py       # new
```

## Complexity Tracking

| Item | Why |
| ---- | --- |
| Storage layer in the same PR as read_file | No storage issue exists and read_file is untestable without it; human chose to fold it in |
