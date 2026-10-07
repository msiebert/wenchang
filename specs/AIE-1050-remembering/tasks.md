# Tasks: Deciding what to remember

**Linear issue**: AIE-1050 | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

## T1 — remembering BODY and its tests

test-writer: `tests/test_prompts_remembering.py` for US1.1-1.3, US2.1-2.5,
US3.1-3.2, US4.1-4.5, US5.1-5.7, US6.1-6.2, per plan.md "Test design"
(fails against the empty `BODY` on main). implementer: set
`remembering.BODY` to the exact text in plan.md. `make check` green.

## T2 — Docs

doc-updater: glossary entry "In-line expiry" directly after "Confidence
label" in `docs/product/glossary.md` (one hunk); `review-pr.md` from
`docs/templates/review-pr-template.md` with the criteria -> test mapping
(file:line). No ARCHITECTURE.md or ADR change.
