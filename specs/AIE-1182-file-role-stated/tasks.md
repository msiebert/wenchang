# Tasks: File a fact the user states inside a question

**Linear issue**: AIE-1182 | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

## T1 — Spec (doc-updater)

This spec, plan, and tasks. Commit on its own.

## T2 — Held-out scenarios (implementer, test-writer)

Criteria US5.1-5.4. implementer writes the four scenario yaml files (plan.md E).
test-writer writes the correct and wrong drivers in
`tests/test_evals_end_to_end.py` with exact fail sets and adds the ids to the
CORPUS set. Separate commit, before any prompt edit.

## T5 — Guards and the fifth held-out (implementer, test-writer)

Criteria US5.5 and US6.1-6.7. implementer writes
`remembering-preference-mid-task` and applies the guard edits to the existing
scenarios (stricter, not weakened). test-writer adds its drivers, exact fail sets
for the edited scenarios, extra wrong-driver rows that misfile to `user`, and the
fifth id to the CORPUS set (5 new ids in total). Separate commit, before any
prompt edit.

## T3 — Prompt edit (test-writer, then implementer)

Criteria US1.1-1.5, US2.1-2.4, US3.1-3.2. test-writer applies plan.md B and
confirms the new pins fail first. implementer applies plan.md A, updates the
scenario headers (C), re-renders the agent file (D), and records the sha256.
Separate commit.

## T6 — Prompt parts A and B (implementer)

Apply both parts of the fix in `src/wenchang/prompts/remembering.py` (plan.md
A): the new final paragraph, and the sentence appended to the save-criterion
paragraph with existing sentences verbatim. Re-render the agent file and record
the sha256. This is the substance of T3's implementer step; do it once, after T5.

## T7 — review-pr.md (doc-updater)

Criteria US3.1 (sha recorded), US4.1-4.7 (documented, human-run), including the
main baseline step (4.6) and the line that held-outs passing at main do not
demonstrate the fix. Draft `review-pr.md` per plan.md F.

## Gate

`make -C /Users/marksiebert/p/github/wenchang-AIE-1182 check` green after T2, T5,
T3/T6, and T7. PR merge gated on the human live run (US4).
