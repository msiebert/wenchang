# Tasks: Privacy refusal categories

**Linear issue**: AIE-1054 | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

## T1 — Privacy section prose

test-writer adds `tests/test_prompts_privacy.py` covering spec US1.1-1.3,
US2.1, US3.1-3.4, US4.1-4.3, US5.1-5.3, using the pinned tokens and
negative pins in plan.md; confirms the positive pins fail against the
current empty `BODY`. implementer sets `privacy.BODY` to the proposed text
in plan.md. `make check` green.

## T2 — Review artifact

doc-updater drafts `specs/AIE-1054-privacy/review-pr.md` from
`docs/templates/review-pr-template.md`, with the criteria -> test mapping
(file:line). No ARCHITECTURE.md, ADR, or glossary change (no new term, no
deviation from §8.1).
