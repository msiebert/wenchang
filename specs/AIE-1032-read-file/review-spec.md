# Spec Review: AIE-1032 — read_file and the storage layer

## What & why

`read_file(path)` returns a memory file's content, its four metadata
fields, and an opaque version token — the starting point of every
read-modify-write in the library. No storage layer exists yet, so this
issue also builds it (ADR 0003): a narrow GCS-mirroring protocol with `get`
and unconditional `put`, an in-memory fake, and a GCS implementation, held
identical by one conformance suite.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | File at valid path with body B, metadata M | `read_file(path)` | Returns B exactly, M, the path, a `VersionToken` |
| 2 | Unicode, `\r\n`, no trailing newline, empty, fact-like markdown | read | Content byte-for-byte equal |
| 3 | File unchanged between reads / overwritten between reads | read twice | Tokens equal / tokens differ + new content |
| 4 | Well-formed path, no object | read | `NotFoundError(FILE_ABSENT)` |
| 5 | Malformed path (empty, `//`, leading/trailing `/`, `.`/`..`, `\`, control char, ≠4 segments, not `*.md`) | read | `NotFoundError(INVALID_PATH)`, storage not called |
| 6 | Backend times out / unavailable | read | `BackendUnavailableError` with TIMEOUT / UNAVAILABLE |
| 7 | Stored metadata malformed / bytes not UTF-8 | read | `MetadataFormatError` / `ValueError` (not a taxonomy error) |
| 8 | Same conformance suite | run vs fake and vs GCS emulator | Identical results: absent→None, round-trip, new token per put, content+metadata from one write, exact-key lookup |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| Core API as methods on `MemoryStore(storage)` | Free functions `read_file(storage, path)` | Later functions need config (size limit, index cap); in-process transport wraps one object |
| Storage protocol speaks `VersionToken`; only `GcsStorage` converts to generation | Protocol exposes `int` generation | Token parsing lives in exactly one place |
| `{root}` = the storage instance (one bucket); paths relative | Key prefix inside bucket now | YAGNI; addable without changing callers |
| Path = exactly 4 segments `{scope}/{entity}/{area}/{name}.md` | Allow nested areas | Matches Notion layout; easy to relax later |
| Corrupt objects raise `ValueError` | New taxonomy error | Data-integrity bug, not something the agent can repair (matches ADR 0006) |
| `put` unconditional here | Add `ifGenerationMatch` now | Precondition/conflict semantics belong to AIE-1033 (write_file) |
| GCS `get` pins download to the fetched generation, retries ≤3 on race | Two unpinned calls | Guarantees content+metadata come from one write |

## Files/modules to be touched

- New: `src/wenchang/paths.py`, `src/wenchang/core.py`,
  `src/wenchang/storage/{__init__,memory,gcs}.py`
- New tests: `test_paths.py`, `storage_conformance.py`,
  `test_storage_memory.py`, `test_storage_gcs_errors.py`,
  `test_core_read_file.py`, `integration/test_storage_gcs.py`
- Docs: ARCHITECTURE.md, new ADR 0007
- Also in this PR (your call earlier): `.claude/commands/implement-issue.md`
  Linear status transitions

## Open questions / assumptions

- **Nested areas?** Spec says one area segment. If agents should create
  sub-areas (`taxonomy/events/x.md`), say so now — it changes the validator.
- **`MemoryStore` name/shape** — fine, or prefer free functions?
- Reads perform no scope/role check (Notion restricts writes only).
- Non-timeout GCS failures (403, missing bucket) propagate uncategorized.

## Risks

- fake-gcs-server support for `ifGenerationMatch` on media download — if
  missing, fall back to `generation=` pinned download; T3 will surface it.
- PR is larger than a typical single issue (storage + core).
