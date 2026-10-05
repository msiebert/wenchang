# Tasks: Prompt layer skeleton and adopter slots

**Linear issue**: AIE-1055 | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

## T1 — PromptSlots

test-writer: `tests/test_prompts_slots.py` for US1.1-1.13 (fails on import
of `wenchang.prompts.slots`). implementer: `slots.py` per plan.md and a
minimal `src/wenchang/prompts/__init__.py` (docstring only; T2 adds the
exports). `make check` green.

## T2 — Section modules, assembly, owned prose, invariants, fixture

test-writer: `tests/prompts_reference_adopter.py` (exact text from
plan.md), `tests/test_prompts_assembly.py` (US2, US3, US6),
`tests/test_prompts_overview.py` (US4.1),
`tests/test_prompts_systems_of_record.py` (US4.2),
`tests/test_prompts_invariants.py` (US5). implementer: `assemble.py`, the
nine section modules with exact headings and prose, full `__init__.py`.
`make check` green.

## T3 — Docs

doc-updater: ARCHITECTURE.md (US7.1), glossary (US7.2), README (US7.3),
ADR 0025 (US7.4), `review-pr.md` with the criteria -> test mapping.
