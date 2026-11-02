# Tasks: Cap the number of files per entity (AIE-1292)

Tests first for each task; implementation never edits `tests/`. Every new test docstring references AIE-1292.

- [ ] **T1 — Error type.** Tests (docstrings cite AIE-1292) for `FileQuotaExceededError` (spec US5 scenarios 1–2, US6 scenario 3), both literal messages from plan.md. Implement in `src/wenchang/errors.py`.
- [ ] **T2 — Setting.** Tests (docstrings cite AIE-1292) for `DEFAULT_MAX_FILES_PER_ENTITY`, the property, and constructor validation (US1 scenario 3 first half, US6 scenario 2). Implement in `src/wenchang/core.py`.
- [ ] **T3 — Enforcement on create.** Tests (docstrings cite AIE-1292) for US1 scenarios 1–3, US2 (incl. vanished file and corrupt same-path object), US3, US4 (incl. `system/` exclusion), US6 scenario 1, and the plan's edge cases (oversize at cap, corrupt metadata elsewhere, small page size with `system/` keys). Also change `_StubStorage.list_page` in `tests/test_core_write_file.py` to return `[]`, leaving the four create tests' assertions unchanged and not setting `max_files_per_entity=None`. Implement the cap check in `MemoryStore.write_file`.
- [ ] **T4 — Tool and MCP surface.** Tests (docstrings cite AIE-1292) for US5 scenarios 3–7: render, reference-seed boundary, role-gated check order, MCP `isError` + `limit`, `write_file` description sentence. Implement the docstring sentence in `src/wenchang/tools.py`; report any other `src/` change needed.
- [ ] **T5 — Integration.** Test (docstring cites AIE-1292) the cap over `GcsStorage` against fake-gcs-server; run `make test-integration`.
- [ ] **T6 — Docs.** ADR 0039, ARCHITECTURE.md, `docs/product/glossary.md` ("File cap (`max_files_per_entity`)"), `review-pr.md`.
- [ ] **T7 — Gate.** `make check` green.
