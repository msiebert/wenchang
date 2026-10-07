# Tasks: Filing and deduplication discipline

**Linear issue**: AIE-1049 | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

## T1 — Filing section prose

test-writer adds `tests/test_prompts_filing.py` per plan.md "Tests",
covering spec US1.1-1.3, US2.1-2.3, US3.1-3.7, US4.1-4.3; confirms they fail
against the empty `BODY`. implementer sets `filing.BODY` to the exact text
in plan.md. `make check` green.

## T2 — Review artifact

doc-updater drafts `review-pr.md` from `docs/templates/review-pr-template.md`
with the criterion -> test mapping (file:line). No ARCHITECTURE, ADR, or
glossary change.
