# Tasks: AIE-1344 document FilesystemStorage

Tests first. Roles follow `scripts/hooks/guard-edits.sh`: test-writer edits
only `tests/**`; doc-updater edits `ARCHITECTURE.md`, `README.md`, `docs/**`,
`specs/**`; a general-purpose agent may edit everything except `src/**` and
`tests/**` (so `site-src/**`, `site/**`, `CHANGELOG.md`). The implementer
cannot edit `site-src/` and is not used.

- [x] T1 — test-writer: `tests/test_site_snippets.py`. Add
  `local_filesystem.py` to `RUNNABLE` and to the `test_outcome_snippets_assert`
  parameters (AC4). Red until T4.
- [x] T2 — test-writer: `tests/test_site.py`. Extend `STALE_PHRASES`, add the
  all-backends-named test, the `docs/product/README.md` check, and the
  quickstart include check (AC1, AC3, AC5, AC7, AC8, AC9). Red until T4 to T7.
- [x] T3 — general-purpose: write `site-src/snippets/local_filesystem.py`
  per `plan.md`; run it directly and run the snippet tests (AC4).
- [x] T4 — general-purpose: edit `site-src/reference.md`, `quickstart.md`,
  `integrate-without-mcp.md`, `status.md`, `index.md`, `storage.md`,
  `concepts.md` per `plan.md` (AC1, AC2, AC3, AC5 to AC8).
- [x] T5 — general-purpose: edit `site/llms.txt` (hand-maintained) and
  `CHANGELOG.md` `[Unreleased]` (AC9, AC10).
- [x] T6 — doc-updater: edit `README.md` and `docs/product/README.md`
  (AC9); draft `review-pr.md` from `docs/templates/review-pr-template.md`
  (no ARCHITECTURE.md, ADR, or glossary change expected: no new architecture
  or product term).
- [x] T7 — general-purpose: run `uv run scripts/build_site.py` twice; confirm
  the second run leaves no diff; stage regenerated `site/` (AC11). Depends on
  T3 to T5.
- [x] T8 — `make check` green (AC12). Depends on all.
