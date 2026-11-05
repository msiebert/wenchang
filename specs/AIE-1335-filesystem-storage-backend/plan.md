# Implementation Plan: Local-filesystem storage backend (AIE-1335)

Linear: AIE-1335. Spec: `spec.md`. Detailed enough to write tests without
reading `src/`.

## Public interface

Module: `src/wenchang/storage/filesystem.py` (import as
`from wenchang.storage.filesystem import FilesystemStorage, InvalidStorageKeyError`).
Not re-exported from `wenchang/storage/__init__.py`, like `memory` and `gcs`.

```python
class InvalidStorageKeyError(ValueError):
    """A key cannot be stored: empty, not encodable as UTF-8, or a segment too long."""


class FilesystemStorage:
    def __init__(self, root: Path) -> None: ...
    @property
    def root(self) -> Path: ...
    def get(self, key: str) -> StoredObject | None: ...
    def put(self, key: str, data: bytes, metadata: Mapping[str, str]) -> VersionToken: ...
    def put_if_version(
        self,
        key: str,
        data: bytes,
        metadata: Mapping[str, str],
        expected: VersionToken | None,
    ) -> VersionToken: ...
    def delete_if_version(self, key: str, expected: VersionToken) -> None: ...
    def list_page(
        self, prefix: str, start_after: str | None, limit: int
    ) -> Sequence[ListedObject]: ...
```

Public constants (module level, so tests can build paths): none required.
Tests build expected paths from the layout below. `FilesystemStorage`
structurally satisfies `Storage`.

`__init__` calls `root.mkdir(parents=True, exist_ok=True)` and stores the
path as given (no `resolve()`). An `OSError` there maps to
`BackendUnavailableError`.

Semantics of the five methods are exactly the `Storage` protocol docstrings
and the conformance suite. Filesystem-specific points follow.

## Key encoding

A key is split on `/` into segments (`"a//b"` has three, the middle empty;
`"a/"` has two, the last empty; `""` is rejected). Each segment is encoded
independently:

- Literal (unescaped) characters: `a`-`z`, `0`-`9`, `_`, `-`, and `.` except
  as the segment's first character.
- Every other character, taken as UTF-8 bytes, becomes `%XX` per byte with
  UPPERCASE hex. This escapes `%`, uppercase letters, a leading `.`, space,
  `\`, NUL, `:`, and all non-ASCII. So `.` -> `%2E`, `..` -> `%2E.`, `A` ->
  `%41`, `é` -> `%C3%A9`, NUL -> `%00`.
- The empty segment is encoded as a lone `%` (never produced otherwise, since
  an escape is always `%` plus two hex digits).

Why this is collision-free and safe:

- Encoded segments contain no `/`, never equal `.` or `..`, and never start
  with `.`, so no key can leave `root` or hit a dot-prefixed reserved name
  (`.lock`, `.tmp-*`).
- Escape output is `%` followed by two uppercase hex digits (or the lone-`%`
  segment). The suffixes `%obj` and `%meta` have `%` followed by `o`/`m`, which
  are not hex digits, so no encoded segment can end with or equal a suffix. A
  leaf file, a directory, and a sidecar therefore never share a name.
- Uppercase is escaped so keys differing only by case cannot collide on
  case-insensitive filesystems (the macOS default).
- Decoding is strict: a name is a valid encoded segment only if re-encoding the
  decoded text gives the same name. Files in `root` that do not parse are
  ignored by `list_page`.

Limits: a segment whose encoded form exceeds 200 bytes raises
`InvalidStorageKeyError` rather than being hashed or truncated (a hash would
break reversibility and readability; 200 leaves room under the 255-byte
filename limit for `%meta` and the temp prefix). A key that cannot be encoded
as UTF-8 (a lone surrogate) and the empty key raise `InvalidStorageKeyError`.
Total path length is not checked; an `ENAMETOOLONG` surfaces as
`BackendUnavailableError`. `get`, `put`, `put_if_version`, and
`delete_if_version` validate the key before touching disk. `list_page` never
raises for a prefix or `start_after` shape: a prefix no stored key can start
with returns `[]`.

## On-disk layout

Per key, with last segment `L` and parent segments `P1..Pn` (all encoded):

```
root/P1/.../Pn/L%obj     body: the bytes exactly as written
root/P1/.../Pn/L%meta    sidecar: UTF-8 JSON {"format": 1, "version": "<token>", "metadata": {...}}
root/.lock               advisory lock file (empty)
root/P1/.../Pn/.tmp-<uuid hex>   temp files, same directory as the target
```

Worked example after:

```
put("user/u1/notes/a.md", b"- fact\n", {"k": "v"})
put("user/u1/notes", b"x", {})            # a key equal to a directory prefix
put("User/Éa", b"y", {})
put("a//b", b"z", {})
```

```
root/.lock
root/user/u1/notes/a.md%obj      -> "- fact\n"
root/user/u1/notes/a.md%meta     -> {"format": 1, "version": "9f3c...", "metadata": {"k": "v"}}
root/user/u1/notes%obj           -> "x"          (sibling of the notes/ directory)
root/user/u1/notes%meta
root/%55ser/%C3%89a%obj          -> "y"          (U -> %55, É -> %C3%89)
root/%55ser/%C3%89a%meta
root/a/%/b%obj                   -> "z"          (empty middle segment -> %)
root/a/%/b%meta
```

The sidecar is written with `json.dumps(..., ensure_ascii=True, sort_keys=True)`
(`ensure_ascii` so lone surrogates in metadata values round-trip). Metadata
comes back as a new `dict[str, str]` each call. Humans may edit a body in place;
that does not change the version.

## Version tokens

`VersionToken(uuid.uuid4().hex)`: 32 lowercase hex characters, generated per
successful write, stored in the sidecar.

- Unique across deletes and restarts with no persisted counter or tombstone: a
  delete removes the sidecar, and the next create draws a fresh random token.
  Distinctness is probabilistic (2^-122 collision), documented, not guaranteed.
- Across keys, tokens are also distinct (not required by the protocol).
- Matching is exact string equality against the sidecar's token. `"abc"`,
  `"0"`, `"-1"`, `"007"`, `""`, `"999999999999"`, and a valid token plus
  `"\n"` therefore all mismatch with no special parsing.
- Rejected: a counter file under `root` (needs durable increment under the
  lock, collides when two copies of a root diverge); GCS-style integer
  generation (needs the same).

## Locking

Every public method holds, for its whole read-modify-write:

1. the instance's `threading.Lock` (cheap serialization of its own threads;
   avoids opening many descriptors), then
2. an `fcntl.flock` on `root/.lock`: `LOCK_EX` for `put`, `put_if_version`,
   `delete_if_version`; `LOCK_SH` for `get` and `list_page`. The lock file is
   opened per call and the lock is released (and the descriptor closed) in a
   `finally`.

`flock` locks are per open file description, so two instances in one process
exclude each other as well as two processes do. Blocking, no timeout. Platform
assumption: POSIX local filesystem; `flock` is unreliable on some network
filesystems (NFS), which is unsupported. Readers use the shared lock so they
never see the two-file pair between a writer's two `os.replace` calls.

## Write path and commit order

`put` / `put_if_version` (under `LOCK_EX`):

1. Validate and encode the key; create parent directories (`mkdir -p`).
2. For `put_if_version`: read the sidecar; compare its version (or absence)
   to `expected`; mismatch raises `PreconditionFailedError(key)` with nothing
   written.
3. Write the body to `.tmp-<uuid>` and the sidecar to a second `.tmp-<uuid>`,
   both fully (so ENOSPC and similar fail here, before any visible change).
4. `os.replace(body_tmp, L%obj)`.
5. `os.replace(sidecar_tmp, L%meta)` — the commit point.
6. On any exception, remove both temp files (best effort), then map the error.

`delete_if_version` (under `LOCK_EX`): read the sidecar; absent or version
mismatch raises `PreconditionFailedError(key)`; otherwise `unlink` the sidecar
(the commit point: the object is now gone), then `unlink` the body, then
`rmdir` now-empty parent directories up to but excluding `root` (best effort,
errors ignored).

What a reader sees:

- Visibility is defined by the sidecar. A body without a sidecar is invisible
  to `get`, `list_page`, and `put_if_version(..., None)`; a later create
  overwrites it.
- Crash after step 4 of a create: orphan body, key absent.
- Crash after the sidecar `unlink` of a delete: key absent, orphan body.
- Crash between steps 4 and 5 of an OVERWRITE: the new body is paired with the
  old sidecar (old metadata and version). This is the one torn window; it needs
  a crash between two consecutive `os.replace` calls, since every fallible
  write already happened in step 3. Accepted for a test/local backend and
  documented. Rejected alternative: versioned body filenames, which make it
  atomic but put tokens in the filenames.
- `.tmp-*` files are never listed or read. Stale ones are not collected.
- No `fsync`: atomic with respect to process crashes, not power loss.

## list_page

Never opens a body. Under `LOCK_SH`:

1. Split `prefix` on `/` into complete segments and a trailing partial
   segment (possibly empty). Descend directly to `root/enc(complete...)`; if
   absent, return `[]`.
2. In that directory, take entries whose decoded name starts with the partial
   segment: `*%meta` files (decoded leaf name) and subdirectories (decoded
   directory name), then recurse through each matching subdirectory's whole
   subtree. Only `*%meta` files count as keys; undecodable names, dot names,
   bodies, and temp files are skipped.
3. Join decoded segments with `/`, keep keys with `key.startswith(prefix)` and
   `key > start_after`, then `sorted(keys)` by Python string comparison (equals
   code-point order; independent of directory-walk order).
4. Slice to `limit`, then read only the selected sidecars for metadata and
   version. A sidecar that vanishes between steps is impossible under the lock;
   an invalid one raises `BackendUnavailableError`.

## Error mapping

- Version mismatch (absent when expected non-`None`, present when expected is
  `None`, or token differs): `PreconditionFailedError(key)`.
- `get`: `FileNotFoundError` on the sidecar means absent, return `None`. A body
  missing while the sidecar exists is a corrupt store: `BackendUnavailableError`.
- Any other `OSError` (permissions, ENOSPC, EIO, ENAMETOOLONG, read-only
  filesystem), and a sidecar that is invalid JSON or the wrong shape, raise
  `BackendUnavailableError(TransientReason.UNAVAILABLE, detail)` using
  `raise ... from exc`, following `gcs.py`'s pattern. `TransientReason.TIMEOUT`
  is never used (lock waits are unbounded). `PreconditionFailedError` and
  `InvalidStorageKeyError` pass through unmapped.
- `InvalidStorageKeyError` is a `ValueError`, not a `WenchangError`: like
  `PreconditionFailedError` it is a storage-layer signal. `core` always builds
  keys through `paths`, so agents cannot trigger it.

## Tests

- `tests/test_storage_filesystem.py` (unit): `storage` fixture
  `FilesystemStorage(tmp_path / "root")`; `TestFilesystemStorage(StorageConformance)`;
  `TestFilesystemEntityPurgeExport(EntityPurgeExportConformance)`; then the
  filesystem-specific tests for AC3 to AC17. Multi-process cases use
  `multiprocessing` with the `spawn` context and a module-level worker function.
- MemoryStore end-to-end (AC2) in `tests/test_storage_filesystem_memory_store.py`.

## Constraints surfaced from the conformance suite

- Bogus-token cases (`"0"`, `"007"`, `""`, `"999999999999"`, token plus
  newline) work with exact-equality random tokens.
- `purge_export_support` seeds a non-UTF-8 body: bodies are bytes end to end,
  never decoded.
- Neighbours `user/u10/...` and `user-archive/...` must not match prefix
  `user/u1/`: directory descent is on whole segments, prefix filtering is on
  the decoded key.
- `list_page` metadata and version must equal `get`'s: both come from the same
  sidecar.
