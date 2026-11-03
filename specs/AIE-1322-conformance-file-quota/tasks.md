# Tasks: AIE-1322 Cover FileQuotaExceededError in the transport conformance suite

- [ ] T1 (test-writer) Failing tests: reference + cached subclasses configure cap 32 and override `max_files_per_entity`; reference case list includes `test_create_at_file_cap_is_quota_exceeded`; self-tests for US1.3–US1.8, US2.1–US2.2, US3.1–US3.4. Confirm they fail because the case/fixture/helper does not exist yet.
- [ ] T2 (implementer) `src/wenchang/testing/transport_conformance.py`: `MIN_FILES_PER_ENTITY`, `check_files_per_entity`, default `max_files_per_entity` fixture, protocol-case validation, new case, `expect_error` hint, module docstring. `make check` green.
- [ ] T3 (doc-updater) ARCHITECTURE.md testing entry, ADR 0044 (+ note on ADR 0039 decision 8), review-pr.md.
- [ ] T4 (general-purpose) `site-src/reference.md` conformance bullet; regenerate `site/`; `make check` green.
