# Tasks: Forgetting section text

**Linear issue**: AIE-1053 | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

## T1 — Forgetting body and its pins

test-writer adds `tests/test_prompts_forgetting.py` covering spec US1.1-1.3,
US2.1-2.6, US3.1-3.5, US4.1, US5.1-5.3, and US6.1-6.2 per plan.md "Test design";
confirms they fail against the empty `BODY` (the negative pins US2.4 and US3.2
pass trivially on an empty body; that is expected). implementer sets
`forgetting.BODY` to the plan.md "Target prose" in
`src/wenchang/prompts/forgetting.py`. `make check` green, including the
unchanged `tests/test_prompts_invariants.py` (US7).

## T2 — Review artifact

doc-updater drafts `specs/AIE-1053-forgetting/review-pr.md` from
`docs/templates/review-pr-template.md` with the criterion -> test mapping
(file:line). No ARCHITECTURE.md, glossary, or ADR change.
