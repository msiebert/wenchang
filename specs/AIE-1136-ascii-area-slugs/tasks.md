# Tasks: ASCII slug areas at the tool layer

**Linear issue**: AIE-1136 | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

## T1 — Area slug and name rules

test-writer adds failing tests to `tests/test_tools.py` for spec US1.1–1.3,
US2.1–2.2, US3.1–3.4, and US4.4 (docstring phrase); implementer adds
`_AREA_SLUG`, `_check_area`, `_check_name` and calls them from `_path` /
`_prefix` per plan.md. `make check` green.

## T2 — Docs

doc-updater: ADR 0022 decision 14 and consequences, ARCHITECTURE.md `tools`
entry, glossary "Scope-relative address" (US4.1–4.3). Applied at the spec
checkpoint; re-check against the final diff before the PR.
