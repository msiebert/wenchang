# 0047. Filesystem storage backend for tests and local development

Date: 2026-11-04

## Status

Accepted. Amends [ADR 0003](0003-storage-interface-with-in-memory-fake-and-gcs-emulator.md)
(its "two implementations" and "not a hedge against switching providers"
stance), only to the extent of a test and local-development backend.

## Context

AIE-1335 asks for a way to run and test wenchang against a real filesystem with
no GCS and no fake-gcs-server: local development, evals, and reading memory
files directly on disk. ADR 0003 holds the `Storage` protocol to GCS semantics
and declines to abstract over providers. A filesystem backend must not reopen
that question or weaken the protocol, and it has to keep the properties the
protocol relies on: conditional writes with exactly one winner, version tokens
that never repeat for a key, and listing that never reads bodies.

## Decision

Add `FilesystemStorage(root: Path)` in `wenchang.storage.filesystem` (not
re-exported, like `memory` and `gcs`) as a third `Storage` implementation. It
is held to the same `StorageConformance` and `EntityPurgeExportConformance`
suites as the other two. It is a test and local-dev backend, not a production
provider, and the `Storage` protocol, `MemoryStore`, transport, and tools do
not change. The host constructs it and passes it in; there is no backend
selection mechanism.

- **Layout.** Each key is split on `/` and each segment is percent-encoded
  with uppercase hex. Only `a-z`, `0-9`, `_`, `-`, and a non-leading `.` stay
  literal; an empty segment is a lone `%`. An object is `<leaf>%obj` (the body
  bytes) plus `<leaf>%meta` (UTF-8 JSON with `format`, `version`, `metadata`).
  Because an escape is `%` plus two hex digits, the `%obj` and `%meta`
  suffixes never collide with an encoded segment, so `a` and `a/b` coexist.
  Encoded segments never contain `/`, equal `.` or `..`, or start with `.`, so
  no key can leave `root`.
- **Uppercase is escaped**, so keys that differ only by case stay distinct on
  case-insensitive filesystems (the macOS default).
- **Invalid keys.** The empty key, a key that is not UTF-8 encodable, and a
  segment encoding to over 200 bytes raise `InvalidStorageKeyError`, a
  `ValueError` and a storage-layer signal rather than a `WenchangError`.
  `core` always builds keys through `paths`, so agents cannot trigger it.
  `list_page` never raises for a prefix shape.
- **Version tokens** are `uuid4().hex`, drawn per write and stored in the
  sidecar. They never repeat across delete or restart with no persisted counter.
  Matching is exact string equality.
- **Commit order.** Body and sidecar are written to temp files first, then the
  body is replaced, then the sidecar is replaced; the sidecar replace is the
  commit point. A delete unlinks the sidecar first. A body without a sidecar
  is an invisible orphan that a later create overwrites.
- **Locking.** Every method holds a per-instance `threading.Lock` and an
  `fcntl.flock` on `root/.lock` (exclusive for writes and deletes, shared for
  reads). Two instances or processes on one root get one winner per conditional
  write, and readers never see a half-committed pair. POSIX local filesystems
  only.
- **`list_page`** descends to the prefix's complete segments, walks the matching
  subtree, sorts decoded keys by code point, and reads only the sidecars of the
  selected page, never a body.
- **Errors.** Other `OSError`s and malformed sidecars map to
  `BackendUnavailableError` with reason `UNAVAILABLE`, chained from the cause.
  Version mismatch is `PreconditionFailedError`.

Rejected alternatives:

- **Naive key-to-path mapping, hashed keys, or leaf-vs-directory marker
  directories.** The naive mapping cannot hold `a` and `a/b` together or
  contain `..`; hashing loses readability and reversibility; marker
  directories clutter the tree.
- **Literal uppercase.** Silent collisions on case-insensitive filesystems.
- **Hashing or truncating over-long segments.** Breaks reversibility.
- **A counter file or GCS-style integer generations for tokens.** Needs a
  durable increment under the lock and collides when two copies of a root
  diverge. Random tokens need no state.
- **Body first on delete, or versioned body filenames.** Body-first leaves a
  visible sidecar-less state; versioned filenames make overwrite atomic but put
  tokens in file names.
- **Thread lock only, or lock-free compare-and-swap.** Neither is safe across
  instances and processes.
- **Reusing `InvalidArgumentError`.** That error is agent-facing.

## Consequences

- Wenchang runs and is tested against a real directory with no emulator, and
  memory files are readable on disk (`user/u1/notes/a.md%obj` is the markdown as
  written). The conformance suites keep it identical in behavior to the fake and
  GCS.
- ADR 0003's seam stays narrow: the protocol still mirrors GCS semantics, and
  this backend is not a statement that wenchang is provider-agnostic or that
  production should use it.
- It accepts more keys than GCS (for example NUL and `a//b`); the protocol does
  not define key syntax.
- Accepted limitations:
  - A crash between the body replace and the sidecar replace of an overwrite
    pairs the new body with the old sidecar's metadata and version.
  - There is no `fsync`: atomic against process crashes, not power loss.
  - A body edited by hand keeps its old version token.
  - Stale `.tmp-*` files are not collected.
  - Token uniqueness is probabilistic (2^-122 collision).
  - POSIX only (`fcntl`); importing the module on Windows fails. `flock` is
    unreliable on network filesystems, which are unsupported.
