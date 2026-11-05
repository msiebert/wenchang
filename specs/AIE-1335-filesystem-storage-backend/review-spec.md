# Spec Review: AIE-1335 — Local-filesystem storage backend

## What & why

Add `FilesystemStorage(root: Path)`, a third `Storage` backend that keeps one
body file and one metadata/version sidecar per object under a local directory.
It lets wenchang run and be tested with no GCS or emulator, and lets people read
memory files directly on disk. It is a test/local-dev backend held to the same
conformance suite, not a production provider.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | Backend on `tmp_path` | Conformance + purge/export suites run | Pass, no emulator |
| 2 | `MemoryStore` on it | Create/read/update/conflict/delete/index/purge/export | Same behavior as the fake |
| 3 | `put("user/u1/notes/a.md")` | Inspect disk | `a.md%obj` is the exact body; `a.md%meta` is JSON with version + metadata |
| 4 | Keys `a`, `a/b`, `a/` | Get/list/delete | All coexist and stay independent |
| 5 | `..`, `/abs`, `a//b`, NUL, `A` vs `a`, unicode | Put/get/list | Round-trip exactly; nothing leaves `root`; case-distinct |
| 6 | Empty key, lone surrogate, >200-byte encoded segment | Any mutating/get call | `InvalidStorageKeyError`, nothing written |
| 7 | Put, delete, re-put 50x | Compare tokens | Never repeats |
| 8 | Fresh instance, same root | Read, then conditional write | Same token; CAS works; old holder gets `PreconditionFailedError` |
| 9 | Two instances, 16 threads | Race create / update / delete | One winner each |
| 10 | 4 processes | Race create | One winner per key |
| 11 | Body without sidecar, stray temp files | get/list/create | Invisible; create succeeds |
| 12 | Awkward key set (`a-b`, `a/b`, `a0`, `B`...) | list + paging | `sorted()` order, no gaps/repeats |
| 13 | Unreadable bodies | `list_page` | Works (never reads bodies) |
| 14-16 | Missing key; read-only root / bad sidecar; missing root | get; put/get; construct | `None`; `BackendUnavailableError`; root created |
| 17-19 | Whole change | typecheck, `make check`, docs | Pass; ARCHITECTURE + new ADR amending 0003 |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| Per-segment percent-encoding; `%obj`/`%meta` suffixes (`%` + non-hex) | Naive key-to-path; hashing keys; leaf-vs-dir marker directories | Collision-free for `a` and `a/b`; reversible; paths stay readable |
| Escape uppercase letters | Literal uppercase | Avoids silent collisions on case-insensitive macOS filesystems |
| Over-long segment (>200 encoded bytes) raises `InvalidStorageKeyError` | Hash/truncate | Keeps encoding reversible |
| Random `uuid4().hex` tokens | Counter file; GCS-style integers | No persisted state; survives delete/restart/copied roots; bogus-token tests pass by equality |
| Sidecar `os.replace` is the commit point; delete unlinks sidecar first | Body first | Body without sidecar is harmless orphan |
| `threading.Lock` + `fcntl.flock` (EX writes, SH reads) | Thread lock only; lock-free CAS | Cross-instance/process safety; readers never see a half-committed pair |
| `list_page` walks matching subtree, sorts decoded keys, reads only sidecars of the page | Trust directory order | Correct code-point order; no body reads |
| `InvalidStorageKeyError(ValueError)` in the new module | Reuse `InvalidArgumentError` | Storage-layer signal, not agent-facing |

## Files/modules to be touched

- `src/wenchang/storage/filesystem.py` (new)
- `tests/test_storage_filesystem.py`, `tests/test_storage_filesystem_memory_store.py` (new)
- `ARCHITECTURE.md`, new ADR, ADR 0003 amendment note (docs step)

## Resolved at checkpoint

- Escape uppercase letters: accepted.
- Torn overwrite window on crash between body and sidecar replace: accepted;
  documented as a known limitation of a test/dev backend.
- Hand-edited bodies keep their old version: accepted.
- POSIX/local filesystem only: accepted.
- Probabilistic uuid token uniqueness: accepted.

## Risks

- Cross-process tests (spawn) may be slow or flaky on CI; keep them few.
- `chmod`-based tests must skip when run as root.
- Directory pruning on delete runs under the lock but races with humans
  editing the tree by hand; errors are ignored.
