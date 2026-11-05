Linear: AIE-1344

# Feature Specification: Document FilesystemStorage on the site and agent-facing docs

**Linear issue**: AIE-1344 — Document FilesystemStorage on the site and agent-facing docs

**Feature Branch**: `AIE-1344-filesystem-storage-docs`

**Created**: 2026-11-04

**Status**: Draft

**Input**: AIE-1335 added `FilesystemStorage` (`wenchang.storage.filesystem`).
The site, `llms.txt`, README, and CHANGELOG do not mention it, and several
pages say only GCS and an in-memory fake exist.

## Summary

- Docs and one site snippet only. No change to `src/`.
- Document the third backend wherever backends are listed; remove the stale
  `**GCS only.**` / "two ship" claims.
- New runnable snippet `site-src/snippets/local_filesystem.py`, classified
  RUNNABLE in `tests/test_site_snippets.py`.
- Regenerate `site/` with `uv run scripts/build_site.py` and commit it.

## Facts to document (from `src/wenchang/storage/filesystem.py`, ADR 0047)

- Import: `from wenchang.storage.filesystem import FilesystemStorage` (not
  re-exported from `wenchang.storage`). Constructor: `FilesystemStorage(root)`,
  `root` a `pathlib.Path`; created if missing.
- POSIX local filesystems only (uses `fcntl.flock`).
- Layout: per object `<key>%obj` (the body, bytes exactly as written) and a
  `%meta` sidecar (version and metadata); directories mirror the key's `/`
  segments. Hand-editing a body shows up on read; the version is unchanged.
- Safe across threads, instances, and processes on one root.
- Accepted limits: a crash between the body and sidecar replace of an
  overwrite pairs the new body with the old sidecar; hand-edited bodies keep
  the old version; no fsync (power loss not covered); stray `.tmp-` files are
  not garbage-collected; local filesystem only (no network filesystems).
- A test and local-dev backend, not a production provider.

## Acceptance Criteria

1. **Reference lists all three.** Given `site-src/reference.md`, when the
   "Storage backends" section is read, then it has a `FilesystemStorage(root)`
   entry giving the import path `wenchang.storage.filesystem`, POSIX-only
   support, the `<key>%obj` body plus `%meta` sidecar layout, and the accepted
   limits above; and the sentence "Two ship with the library" is gone (now
   "Three").
2. **Thread table.** Given `site-src/integrate-without-mcp.md`, when the
   thread-safety table is read, then it has a `FilesystemStorage` row, and any
   prose naming only GCS and in-memory backends names all three.
3. **Quickstart.** Given `site-src/quickstart.md` "Run it without GCS", when it
   is read, then it presents `FilesystemStorage` as the persistent local option
   (contrast: `InMemoryStorage` forgets on exit) and embeds
   `<!--include python local_filesystem.py-->`.
4. **Snippet runs.** Given `site-src/snippets/local_filesystem.py`, when
   `tests/test_site_snippets.py` runs, then the file is in `RUNNABLE`, exits 0
   in a subprocess, contains an `assert`, uses
   `tempfile.TemporaryDirectory`, builds `MemoryStore(FilesystemStorage(...))`,
   writes and reads a file, and asserts a `%obj` file exists on disk under the
   temp directory.
5. **Stale claims gone.** Given all of `site-src/*.md`, `site/llms.txt`, and
   `docs/product/README.md`, when searched, then none contains `**GCS only.**`,
   "Storage other than GCS", "Two ship with the library", or "No swappable
   storage backend is provided". `tests/test_site.py::test_no_stale_claims`
   enforces the first four phrases on site pages and `llms.txt`.
6. **Storage page caveat.** Given `site-src/storage.md`, when read, then the
   opening no longer says everything goes through `GcsStorage` unqualified: it
   says the page describes the GCS backend and notes that
   `FilesystemStorage` differs (local files, random version tokens, no
   network). `concepts.md` version-token text (lines 3, 67) notes that
   `FilesystemStorage` tokens are random strings, not GCS generations.
7. **Status and index.** Given `site-src/status.md` and `site-src/index.md`,
   when read, then every storage claim names GCS (production), the in-memory
   fake, and `FilesystemStorage` (local/test); "limitations" still states
   there is no other production backend.
8. **All pages name three.** Given every site page that lists backends
   (`reference.md`, `quickstart.md`, `status.md`, `index.md`,
   `integrate-without-mcp.md`, `storage.md`), when searched, then each also
   contains `FilesystemStorage`. `tests/test_site.py` asserts this for the
   page set.
9. **Agent-facing and repo docs.** Given `site/llms.txt`, `README.md`, and
   `docs/product/README.md`, when read, then each mentions the filesystem
   option for local and agent use (inspect memory files on disk), and
   `docs/product/README.md` no longer says no swappable backend exists.
10. **CHANGELOG.** Given `CHANGELOG.md`, when read, then `[Unreleased]` has an
    entry (Added) for `FilesystemStorage` with its import path.
11. **Site rebuilt.** Given the edits, when `uv run scripts/build_site.py` is
    run twice, then `site/` is committed with the new content and the second
    run produces no `git diff`; `tests/test_site.py` passes (including
    `test_no_stale_outputs` and internal link checks).
12. **Gate.** `make check` passes. No existing test is deleted, skipped, or
    weakened; `tests/test_site.py` and `tests/test_site_snippets.py` are only
    extended.

## Out of Scope

- Changes to `src/`, ARCHITECTURE.md, or ADRs (done in AIE-1335).
- Re-exporting `FilesystemStorage` from `wenchang.storage`.
- A CI check that `site/` is in sync with `site-src/`.
- Cutting a release (CHANGELOG entry only).
