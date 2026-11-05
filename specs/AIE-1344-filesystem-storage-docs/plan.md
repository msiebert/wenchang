# Plan: AIE-1344 document FilesystemStorage

Docs, one snippet, and test extensions. `src/` is untouched.

## Test changes (written first)

`tests/test_site_snippets.py` (test-writer):
- Add `"local_filesystem.py"` to `RUNNABLE`. The existing parametrized
  `test_runnable_snippet_exits_zero` then runs it; the classification test
  fails until the file exists.
- Add `"local_filesystem.py"` to the `test_outcome_snippets_assert` parameter
  list.

`tests/test_site.py` (test-writer):
- Extend `STALE_PHRASES` (used by `test_no_stale_claims` over `site-src/*.md`
  and `site/llms.txt`) with: `**GCS only.**`, `"Storage other than GCS"`,
  `"Two ship with the library"`, ``"everything goes through `GcsStorage`"``.
  Verify each is not matched by legitimate new text before finalizing.
- New `test_storage_backends_named`: each of `reference.md`, `quickstart.md`,
  `status.md`, `index.md`, `integrate-without-mcp.md`, `storage.md` in
  `site-src/`, plus `site/llms.txt`, contains `FilesystemStorage`; `reference.md`
  also contains `wenchang.storage.filesystem`, `%obj`, and `%meta`; `GcsStorage`
  and `InMemoryStorage` remain named in `reference.md`.
- New `test_product_readme_names_storage_backends`: `docs/product/README.md`
  lacks "No swappable storage backend is provided".
- New check that `quickstart.md` includes `local_filesystem.py` (the include
  marker), if the existing include-resolution test does not already cover a
  new snippet being referenced.

## Snippet: `site-src/snippets/local_filesystem.py`

```python
import tempfile
from pathlib import Path

from wenchang.core import MemoryStore
from wenchang.storage.filesystem import FilesystemStorage
```

Behavior: with `tempfile.TemporaryDirectory() as tmp`, build
`MemoryStore(FilesystemStorage(Path(tmp) / "memory"))`, write one file
through the same call shape `integrate_direct.py` / the quickstart uses
(implementer of the snippet must read `MemoryStore.write_file`'s real
signature), read it back, `assert` the content matches, then
`assert any(Path(tmp).rglob("*%obj"))` and print the first object's path
relative to the root. Cleanup is automatic. No install commands.

## Page edits (general-purpose agent; confirm exact lines with grep)

- `site-src/reference.md` "Storage backends": "Two ship" becomes "Three ship".
  Add third bullet **`FilesystemStorage(root)`** in
  `wenchang.storage.filesystem` (not re-exported from `wenchang.storage`):
  `root` a `Path`, created if missing; POSIX only; layout `<key>%obj` body plus
  `%meta` sidecar, directories mirror key segments; version tokens random
  strings; safe across threads, instances, processes; accepted limits (crash
  window on overwrite, hand-edited body keeps old version but the edit shows
  on read, no fsync, stray `.tmp-` files not collected, local filesystem only);
  for tests and local dev, not production.
- `site-src/integrate-without-mcp.md`: add `FilesystemStorage` row to the
  thread-safety table (safe to share, per-instance lock plus file lock; also
  safe across instances and processes on one root). Lines ~81-82 and ~120:
  name all three where backends are listed.
- `site-src/quickstart.md` "Run it without GCS": keep `InMemoryStorage` for
  throwaway runs; add `FilesystemStorage(root)` as the persistent local option
  with `<!--include python local_filesystem.py-->`; mention you can open the
  `%obj` files to read memory directly.
- `site-src/status.md` (30, 37, 39): `**GCS only.**` becomes GCS for production plus
  `FilesystemStorage` and `InMemoryStorage` for local/test; limitations still
  say no other production backend.
- `site-src/index.md` (16, 31, 195, 205, 235, 241, 299, 326): replace
  "Storage other than GCS, apart from an in-memory fake" with wording naming
  all three; review the other lines for GCS-only claims and fix only those.
- `site-src/storage.md:3`: reword to "This page describes the GCS backend; the
  same operations apply to `FilesystemStorage` except where noted" (avoid the
  banned literal phrase) and add a short caveat where it matters (version
  tokens, no network failures/timeouts/retries).
- `site-src/concepts.md` (3, 67): version tokens are GCS generations under
  `GcsStorage`; `FilesystemStorage` tokens are random strings. Opaque either
  way.
- `site/llms.txt` (hand-maintained; lines ~3, 15, 16): add the filesystem
  option for local and agent use, one line.
- `README.md` (49, 65, 77-78): mention `FilesystemStorage` for local use and
  inspecting memory files on disk. (doc-updater may edit README.md.)
- `docs/product/README.md:20`: replace "No swappable storage backend is
  provided" with a statement that GCS is the production backend and a
  filesystem backend exists for tests and local dev. (doc-updater)
- `CHANGELOG.md` `[Unreleased]`: `### Added` entry for `FilesystemStorage`
  (`wenchang.storage.filesystem`), local-directory backend for tests and local
  dev, POSIX only.

## Regenerate

`uv run scripts/build_site.py` then again; second run must leave no diff.
Commit `site/` including `llms-full.txt`, `sitemap.xml`, and
`memory-prompt.md` if changed. Check that pages are in `PAGES` (no new page is
added).

## Gate

`make check`.
