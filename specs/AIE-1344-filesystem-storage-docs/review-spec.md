# Spec Review: AIE-1344 — Document FilesystemStorage on the site and agent-facing docs

## What & why

AIE-1335 added `FilesystemStorage`, but the site, `llms.txt`, README, and
CHANGELOG do not mention it, and several pages say only GCS plus an in-memory
fake exist. This change documents the third backend, adds a runnable
quickstart snippet, fixes the stale claims, and regenerates `site/`. Docs and
tests only; no `src/` change.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | `reference.md` Storage backends | read | Third entry with import path, POSIX only, `%obj`/`%meta` layout, accepted limits; "Two ship" gone |
| 2 | thread-safety table | read | `FilesystemStorage` row present |
| 3 | quickstart "Run it without GCS" | read | Persistent local option, embeds `local_filesystem.py` |
| 4 | the snippet | snippet tests run | RUNNABLE, exits 0, has `assert`, temp dir, `%obj` file asserted |
| 5 | site pages, `llms.txt`, product README | searched | Four stale phrases absent (test-enforced) plus "No swappable storage backend" |
| 6 | `storage.md`, `concepts.md` | read | GCS-only framing qualified; tokens differ for filesystem |
| 7-8 | status, index, and all backend-listing pages | read | Name all three backends |
| 9-10 | `llms.txt`, README, CHANGELOG | read | Filesystem option mentioned; `[Unreleased]` entry |
| 11 | edits done | build twice | `site/` committed, second build no diff |
| 12 | all | `make check` | passes, no tests weakened |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| Extend existing `STALE_PHRASES` test and add an all-backends-named test | Manual review only | Stale claims here recurred; a test keeps them out |
| New snippet is RUNNABLE on a temp dir | SKIPPED | Needs no network, so it can run offline in CI |
| Edit site via general-purpose agent | implementer (cannot edit `site-src/`) | Hook rule 6 allows it; rule 4 does not |
| No new ADR, ARCHITECTURE, or glossary change | n/a | ADR 0047 already covers the backend |

## Files/modules to be touched

- `site-src/{reference,quickstart,integrate-without-mcp,status,index,storage,concepts}.md`
- `site-src/snippets/local_filesystem.py` (new), `site/**` (regenerated),
  `site/llms.txt`
- `README.md`, `docs/product/README.md`, `CHANGELOG.md`
- `tests/test_site.py`, `tests/test_site_snippets.py` (extended only)

## Resolved at checkpoint

- The banned stale phrase is narrowed to the exact sentence `**GCS only.**`
  (bold, with period), so legitimate wording like "GCS only supports..." is
  not flagged. spec.md and plan.md updated to match.

## Risks

- `site/` is committed and has no sync CI, so a missed rebuild goes unnoticed;
  AC11 requires a double build with a clean diff.
