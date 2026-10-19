# Tasks: AIE-1198

Order matters: held-outs are committed before the prompt edit.

## T1 — Held-out scenarios (implementer, then test-writer)

Spec US3.1-3.4. implementer writes the four yaml files. test-writer adds the
correct and wrong drivers with exact fail sets to
`tests/test_evals_end_to_end.py` and the 4 ids to the corpus set. Commit.

## T2 — Reply-path grader (test-writer, then implementer)

Spec US2.1-2.5. test-writer writes failing tests in
`tests/test_evals_graders.py`; implementer adds `find_unmatched_reply_paths`
to `evals/graders.py`.

## T3 — grade.json and report (test-writer, then implementer)

Spec US2.6-2.8 and US3.5. Tests in `tests/test_evals_report.py` and
`tests/test_evals_end_to_end.py`; implementation in `evals/report.py`.
Commit.

## T4 — Re-report (lead)

Spec US2.9 on `cp -Rp` copies in the scratchpad. Record numbers and the
false-positive review for T6.

## T5 — Prompt sentence (test-writer, then implementer)

Spec US1. test-writer adds the pins; implementer edits `overview.BODY`,
runs `uv run python -m evals render-agent`, records the sha256. Commit.

## T6 — Docs (doc-updater)

ADR 0033, ARCHITECTURE.md evals bullets, review-pr.md with the US5 gate.
Commit.
