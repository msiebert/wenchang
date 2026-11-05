Linear: AIE-1335

Allow-test-changes: new filesystem tests use a skipif marker (needs_non_root) so chmod-based permission tests skip when run as root, where chmod cannot make files unreadable; no existing test is removed, skipped, or weakened.

# Feature Specification: Local-filesystem storage backend

**Linear issue**: AIE-1335 — Add a local-filesystem storage backend for testing and local development

**Feature Branch**: `AIE-1335-filesystem-storage`

**Created**: 2026-11-04

**Status**: Draft

**Input**: Add a `Storage` backend that keeps objects in a local directory, so
wenchang can run and be tested against a real filesystem with no GCS or
fake-gcs-server. Uses: local dev, evals, and looking at memory files directly
on disk.

## Summary

- New `FilesystemStorage(root: Path)` in `src/wenchang/storage/filesystem.py`,
  implementing all five `Storage` methods. Not re-exported from
  `wenchang.storage` (matches `memory` and `gcs`).
- One body file plus one sidecar file per object under `root`. The body holds
  the bytes exactly as written; the sidecar holds the metadata and version.
  Directories mirror the key's `/` segments, so `root` reads like the memory
  tree.
- A reversible per-segment key encoding makes the layout collision-free for
  every key the protocol allows, including `a` and `a/b` coexisting, and makes
  path escape impossible.
- Version tokens are random (`uuid4().hex`), so they never repeat for a key,
  across delete or across process restarts.
- A per-instance lock plus an advisory `fcntl.flock` file lock under `root`
  make conditional writes and deletes safe across threads, instances, and
  processes. POSIX only.
- It is a test and local-dev backend held to the same conformance suite as the
  other two. It is not a production provider. A new ADR amends ADR 0003.
- No backend-selection mechanism, CLI, or environment wiring is added. The host
  constructs the storage and passes it in.

Out of scope: any change to the `Storage` protocol, `MemoryStore`, transport,
or tools; Windows support; fsync/power-loss durability; garbage collection of
stale temp files; selecting a backend from config.

## User scenarios

1. **Developer runs wenchang locally without GCS.** They construct
   `FilesystemStorage(Path("~/.wenchang-dev"))`, pass it to `MemoryStore`, and
   use the memory tools. No emulator, no credentials.
2. **Test author wants a real-filesystem backend.** A `tmp_path` fixture gives
   a fresh backend per test. The same conformance suite that covers the fake
   and GCS passes against it.
3. **Eval operator inspects memory.** They open `root` in an editor or `ls`
   and see `user/u1/notes/a.md%obj` containing the markdown as written, with
   the metadata and version next to it in `a.md%meta`.
4. **Two processes share one root** (for example an eval harness and a test
   script). Conditional writes still have exactly one winner.

## Acceptance criteria

Tests are unit tests (`pytest.mark.unit`) using `tmp_path`; none needs an
emulator or network. "Fresh instance" means a new `FilesystemStorage(root)` on
a root another instance already wrote. Tests cite `AIE-1335`.

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | A `FilesystemStorage` on `tmp_path` | `TestFilesystemStorage(StorageConformance)` and `TestFilesystemEntityPurgeExport(EntityPurgeExportConformance)` run | Both suites pass unchanged, with no emulator |
| 2 | A `MemoryStore` built on a `FilesystemStorage` | Files are created, read, updated with the current version, rejected with a stale version, deleted, and the memory index is read; an entity is exported and purged | Each operation behaves as it does on `InMemoryStorage` (version conflicts surface as `VersionConflictError`, the index lists the files, purge returns the right count) |
| 3 | `put("user/u1/notes/a.md", body, {"k": "v"})` | The directory tree under `root` is inspected | The body file `root/user/u1/notes/a.md%obj` contains exactly `body`; the sidecar `root/user/u1/notes/a.md%meta` is UTF-8 JSON containing the version and `{"k": "v"}`; no other non-hidden file exists for the key |
| 4 | Keys `a`, `a/b`, `a/b/c`, and `a/`, written in any order | Each is read and listed | All coexist; each `get` returns its own bytes; `list_page("", None, 100)` returns all four in ascending key order; deleting `a` leaves `a/b` intact |
| 5 | Keys `../x`, `/abs`, `a/../b`, `.`, `..`, `a/./b`, `a//b`, `.hidden`, `a\x00b`, `%2e%2e/x`, `A` and `a`, `café/é`, and a key containing `\\` | Each is `put` then `get` and `list_page`d | Each round-trips byte-for-byte, lists under its exact original key, and `A` and `a` are distinct objects; after all puts, every file and directory under `root` resolves (after `os.path.realpath`) to a path inside `root`, and nothing exists outside `root` |
| 6 | The empty key, a key with a lone surrogate (`"\ud800"`), and a key with a segment whose encoding exceeds 200 bytes | Passed to `get`, `put`, `put_if_version`, or `delete_if_version` | Each raises `InvalidStorageKeyError` (a `ValueError`); no file is created. `list_page` with such a prefix or `start_after` does not raise and returns no object for an unencodable prefix |
| 7 | An object put, then deleted with its token | The key is put again (via `put`, then separately via `put_if_version(..., None)`), 50 times with deletes between | No returned token equals any earlier token for that key, including the one deleted |
| 8 | Instance A writes a key and gets token `t1` | A fresh instance B on the same root reads, then writes the key | B's `get` returns the same bytes, metadata, and `t1`; `put_if_version(..., expected=t1)` on B succeeds; B's new token differs from `t1`; A's `put_if_version(..., expected=t1)` then raises `PreconditionFailedError` |
| 9 | Two `FilesystemStorage` instances on one root | 16 threads (8 per instance) race `put_if_version(key, ..., None)`; then race `put_if_version(key, ..., v)`; then race `delete_if_version(key, v2)`, 5 rounds each | Exactly one thread wins each race, the rest raise `PreconditionFailedError`, and the stored object is the winner's (or absent after the delete) |
| 10 | Four processes (spawned with `multiprocessing`, each building its own instance on one root) on a POSIX platform | They race `put_if_version(key, ..., None)` once, 5 rounds with distinct keys | Exactly one process wins each key; every loser got `PreconditionFailedError` |
| 11 | A body file with no sidecar (simulating a crash between the two commits of a create or between the sidecar delete and body delete of a delete), and stray `.tmp-*` files in the same directory | `get`, `list_page`, `put_if_version(key, ..., None)` | `get` is `None`; `list_page` omits the key and ignores the temp files; the create succeeds and overwrites the orphan body |
| 12 | Keys `a-b`, `a/b`, `a0`, `a.b`, `a`, `B`, `a/`, `é`, put in shuffled order | `list_page("", None, 100)`, and paging with `limit=3` and `start_after` carried forward | Keys come back in `sorted(keys)` order (code-point order, not directory-walk order); paging reproduces the same sequence with no repeats or gaps |
| 13 | Objects whose body files are made unreadable (`chmod 000`; skipped when running as root) | `list_page` | It succeeds and returns the correct keys, metadata, and versions: it never opens bodies |
| 14 | A missing key | `get` | Returns `None`, not an error (FileNotFoundError is not mapped) |
| 15 | A `root` directory that is read-only (`chmod 0o500`; skipped as root), and separately a sidecar containing invalid JSON | `put`, and `get` / `list_page` respectively | Each raises `BackendUnavailableError` (reason `UNAVAILABLE`) chained from the underlying error; no raw `OSError` or `JSONDecodeError` escapes |
| 16 | `root` that does not exist | `FilesystemStorage(root)` is constructed | `root` and its parents are created; construction on an existing root changes nothing |
| 17 | A `FilesystemStorage` | Assigned to a `Storage`-typed variable | Type-checks under `make typecheck` with no cast |
| 18 | The change | `make check` | Passes |
| 19 | The docs | `ARCHITECTURE.md` storage section and diagram, and a new ADR amending ADR 0003 | ARCHITECTURE.md names the third backend and the layout/locking semantics; the ADR is complete (no template placeholders) and ADR 0003 has an amendment note pointing to it |

Notes:

- AC9 and AC10 are enforceable here, unlike the GCS suite, because
  `delete_if_version` is serialized by the lock.
- AC5's `\\` and NUL cases rely on encoding; the platform's filename rules never
  see those characters.
- GCS rejects some keys the filesystem backend accepts (for example NUL,
  `a//b`). The backend is deliberately more permissive; the protocol does not
  define key syntax.

## Resolved at checkpoint

- Escape uppercase letters: accepted.
- Torn overwrite window on crash between body and sidecar replace: accepted;
  documented as a known limitation of a test/dev backend.
- Hand-edited bodies keep their old version: accepted.
- POSIX/local filesystem only: accepted.
- Probabilistic uuid token uniqueness: accepted.

## Non-functional

- No new dependencies (stdlib only: `os`, `fcntl`, `json`, `threading`,
  `uuid`, `pathlib`, `urllib.parse` or a hand-rolled encoder).
- POSIX only (`fcntl`). Importing `wenchang.storage.filesystem` on Windows
  fails at import; nothing else imports it.
- Whole new unit-test set runs in a few seconds.
