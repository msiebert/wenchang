# PR Review: AIE-1344 — Document FilesystemStorage on the site and agent-facing docs

## What changed & why

AIE-1335 added `FilesystemStorage`, but the site, `llms.txt`, README, and
CHANGELOG still said only GCS and an in-memory fake exist. This change
documents the third backend wherever backends are listed, removes the stale
"GCS only" / "Two ship" claims, adds a runnable `local_filesystem.py` snippet,
and regenerates `site/`. Docs and one snippet only; no `src/` change.

## Acceptance criteria → tests

| Acceptance criterion (Given/When/Then) | Test(s) |
| --------------------------------------- | ------- |
| AC1 Reference lists all three backends, import path, layout, "Three ship" | `tests/test_site.py::test_storage_backends_named`, `test_no_stale_claims` |
| AC2 Thread table has a FilesystemStorage row | `test_storage_backends_named` (page names it); row content is a manual review item |
| AC3 Quickstart presents FilesystemStorage and embeds the snippet | `test_quickstart_includes_filesystem_snippet`, `test_storage_backends_named` |
| AC4 Snippet runs, asserts `%obj` on disk | `tests/test_site_snippets.py::test_runnable_snippet_exits_zero[local_filesystem.py]`, `test_outcome_snippets_assert[local_filesystem.py]` |
| AC5 Stale claims gone | `tests/test_site.py::test_no_stale_claims` (extended `STALE_PHRASES`), `test_product_readme_names_storage_backends` |
| AC6 Storage page caveat, concepts token note | `test_no_stale_claims` (old opening phrase); wording is a manual review item |
| AC7 Status and index name all three | `test_storage_backends_named` |
| AC8 All pages name three | `test_storage_backends_named` (`BACKEND_PAGES`) |
| AC9 llms.txt, README, product README | `test_storage_backends_named` (llms.txt), `test_product_readme_names_storage_backends`; README manual |
| AC10 CHANGELOG entry | Manual review |
| AC11 Site rebuilt, idempotent | `test_no_stale_outputs`, internal link checks in `tests/test_site.py`; second build left no diff |
| AC12 Gate | `make check` (run by orchestrator) |

## Architecture / ADR changes

- N/A. ARCHITECTURE.md, ADRs, and the glossary are unchanged; ADR 0047
  (AIE-1335) already covers the backend.

## Deviations from spec

- None.

## Look closely at

- Accuracy of the accepted-limits wording (POSIX only, crash window, no fsync,
  stray `.tmp-` files, hand-edited bodies keep the old version) against
  `src/wenchang/storage/filesystem.py`.
- The thread-safety table row and the storage/concepts caveats (random version
  tokens vs GCS generations), which tests only check loosely.
- `site/` is generated output; review `site-src/` and skim `site/` for sync.
- Test changes are additive only (no deletions or weakening).

## Follow-ups

- Re-exporting `FilesystemStorage` from `wenchang.storage` (out of scope).
- CI check that `site/` matches `site-src/` (out of scope).
- Cut a release to publish the CHANGELOG entry.
