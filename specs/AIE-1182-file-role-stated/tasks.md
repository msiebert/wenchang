# Tasks: File a fact the user states inside a question

**Linear issue**: AIE-1182 | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

## T1 — Spec (doc-updater)

This spec, plan, and tasks. Commit on its own.

## T2 — Held-out scenarios (implementer, test-writer)

Criteria US5.1-5.4. implementer writes the four scenario yaml files (plan.md E).
test-writer writes the correct and wrong drivers in
`tests/test_evals_end_to_end.py` with exact fail sets and adds the 4 ids to the
CORPUS set. Separate commit, before any prompt edit.

## T3 — Prompt edit (test-writer, then implementer)

Criteria US1.1-1.4, US2.1-2.4, US3.1-3.2. test-writer applies plan.md B and
confirms the new pins fail first. implementer applies plan.md A, updates the
scenario headers (C), re-renders the agent file (D), and records the sha256.
Separate commit.

## T4 — review-pr.md (doc-updater)

Criteria US3.1 (sha recorded), US4.1-4.7 (documented, human-run). Draft
`review-pr.md` per plan.md F.

## Gate

`make -C /Users/marksiebert/p/github/wenchang-AIE-1182 check` green after T2, T3,
and T4. PR merge gated on the human live run (US4).
