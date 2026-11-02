# Tasks: AIE-1316 GCS client thread-safety

Tests first; implementation never edits `tests/`.

- [ ] T1 — test-writer: write `tests/integration/test_storage_gcs_threads.py`
  (spec AC1 to AC6). Behavior already exists, so the tests must go green: run
  `make emulator-up`, then
  `uv run pytest -m integration tests/integration/test_storage_gcs_threads.py`.
  Then show they can detect failure with one named in-test sabotage per AC
  class, run once and then removed, with the red output recorded for
  `review-pr.md`. Sabotage is a temporary wrapper `Storage` or monkeypatch in
  the test run, never `src/` edits. Examples:
  - AC2/AC3: a wrapper that strips `if_generation_match`/`expected`.
  - AC1: a wrapper whose `get` returns another thread's key.
  - AC6: credentials whose `apply()` skips the header.
  Confirm `pyproject` `filterwarnings` has no `error` filter (AC4).
- [ ] T2 — implementer: extend the `GcsStorage` class docstring in
  `src/wenchang/storage/gcs.py` (safe to share across threads, as is the
  Client/Bucket it wraps, because it adds no mutable state). Docstring only; no
  behavior change; no AIE ID in the docstring.
- [ ] T3 — doc-updater: update `site-src/integrate-without-mcp.md` (including
  line 30), `site-src/storage.md`, `site-src/status.md`,
  `site-src/snippets/integrate_direct.py` comment; rebuild `site/` with
  `uv run scripts/build_site.py`; grep `site/` and `site-src/` for "per
  thread", "not documented as thread-safe", "Not guaranteed"; update
  `ARCHITECTURE.md`; add "Amended (2026-11-02, AIE-1316)" notes to
  `docs/adr/0027-mcp-host-adapter.md` and
  `docs/adr/0003-storage-interface-with-in-memory-fake-and-gcs-emulator.md`;
  draft `review-pr.md` including the T1 red output.
- [ ] T4 — `make check` and `make test-integration` green.
