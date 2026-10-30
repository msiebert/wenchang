# Tasks: Cap the number of files per entity (AIE-1292)

Tests first for each task; implementation never edits `tests/`.

- [ ] **T1 — Error type.** Tests for `FileQuotaExceededError` (spec US5 scenarios 1–2, US6 scenario 3). Implement in `src/wenchang/errors.py`.
- [ ] **T2 — Setting.** Tests for `DEFAULT_MAX_FILES_PER_ENTITY`, the property, and constructor validation (US1 scenario 3 first half, US6 scenario 2). Implement in `src/wenchang/core.py`.
- [ ] **T3 — Enforcement on create.** Tests for US1 scenarios 1–3, US2, US3, US4, US6 scenario 1, and the spec's edge cases (oversize at cap, corrupt metadata elsewhere, create-on-existing at cap). Implement the cap check in `MemoryStore.write_file`.
- [ ] **T4 — Tool rendering.** Test for US5 scenario 3 (tools over `InProcessClient`, `render_error`). No `src/` change expected; if one is needed, report it.
- [ ] **T5 — Integration.** Test the cap over `GcsStorage` against fake-gcs-server; run `make test-integration`.
- [ ] **T6 — Docs.** ADR 0039, ARCHITECTURE.md, `review-pr.md`.
- [ ] **T7 — Gate.** `make check` green.
