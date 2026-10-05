# Tasks: Curated-content correction and applying memory

**Linear issue**: AIE-1052 | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

## T1 — Curated content and applying memory prose

test-writer adds failing `tests/test_prompts_curated_content.py` (US1.1-1.10)
and `tests/test_prompts_applying_memory.py` (US2.1-2.7) per plan.md;
implementer sets `curated_content.BODY` and `applying_memory.BODY` to the
exact text in plan.md (US3.1 is covered by the unchanged invariant tests).
`make check` green.

## T2 — Review artifact

doc-updater drafts `review-pr.md` from the template with the criterion ->
test mapping (file:line). No ARCHITECTURE.md, ADR, or glossary change.
