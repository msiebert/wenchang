# Spec Review: AIE-1033 — write_file

## What & why

Add `MemoryStore.write_file(path, content, metadata, expected_version)`, a
full-file replace guarded by optimistic locking. It is the only way to
create a file, and every later mutating call follows its conflict contract.
The storage layer gets a conditional put (GCS `ifGenerationMatch`) so the
in-memory fake and GCS enforce the version guard the same way.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | No file at path | write with `expected_version=None` | Created; returns `MemoryFile` + token; `read_file` agrees |
| 2 | File exists | write with `None` | `VersionConflictError` with current content + version; unchanged |
| 3 | File at `V` | write with `V` | New token `≠ V`; new content + metadata stored together |
| 4 | File moved on to `V2` | write with stale `V` | `VersionConflictError(content@V2, V2)`; retry with `V2` succeeds |
| 5 | No file | write with a non-`None` token | `NotFoundError(FILE_ABSENT)` |
| 6 | Unrecognized/non-numeric token | write | Conflict, never a parse error |
| 7 | Content = 16384 / 16385 UTF-8 bytes | write (default ceiling) | Accepted / `OversizeWriteError(size=16385, limit=16384)`, no storage call |
| 8 | `max_file_bytes=100` / `≤ 0` | write 101 bytes / construct | `limit=100` in error / `ValueError` |
| 9 | Any rejected write | read afterwards | File and token unchanged |
| 10 | Clock returns `T` | write with `last_updated=T0` | Stored `last_updated == T`; other fields as given |
| 11 | Malformed path | write | `NotFoundError(INVALID_PATH)`, no storage call |
| 12 | Fake and GCS | same conditional-put conformance cases | Identical results |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| `expected_version=None` means create-only; parameter required | Separate `create_file`; optional param defaulting to unconditional | Matches GCS `ifGenerationMatch=0`; no silent overwrite path |
| Token given + file absent → `FILE_ABSENT` | `VersionConflictError` with empty content | No current content to return; the fix is to create the file |
| New `Storage.put_if_version`; `put` stays unconditional | Add an optional precondition to `put` | Leaves test seeding and existing callers alone; no sentinel |
| Storage raises its own `PreconditionFailedError`; core builds the conflict | Storage raises `VersionConflictError` | Storage doesn't decode content; taxonomy stays in core |
| Ceiling = content UTF-8 bytes, inclusive, checked before storage | Count metadata too | Ceiling exists so a read's body fits one response |
| GCS rejects non-canonical tokens (`"0"`, `"007"`) locally as a mismatch | `int(token)` | `"0"` would otherwise mean "must not exist" |

## Files/modules to be touched

- `src/wenchang/storage/{__init__,memory,gcs}.py`, `src/wenchang/core.py`
- `tests/storage_conformance.py`, `tests/test_storage_gcs_errors.py`, new `tests/test_core_write_file.py`
- `ARCHITECTURE.md`, new ADR `docs/adr/0008-*`

## Open questions / assumptions

- **Resolved (human, 2026-09-28): the core layer stamps `last-updated`**
  from an injectable clock, overriding the caller's value. Notion says it is
  "refreshed on any write", and `append_line`/`replace_fact` have no
  metadata argument, so core has to stamp there anyway.
- `sources` is stored as supplied; stamping the calling surface is the tool
  layer's job (AIE-1044).
- `system/` read-only (AIE-1040) and role gating (AIE-1042) are out of
  scope; `system/` paths are writable until those land.

## Risks

- GCS client auto-retries conditional uploads. A retry after a landed
  write comes back as 412, so it surfaces as a conflict carrying our own
  content. That is the documented retry-safe behavior, and US2.6 covers it.
- fake-gcs-server's 412 behavior for "token given, object absent" is
  checked only by the integration run, not by the unit suite.
