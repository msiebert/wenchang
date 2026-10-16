# Tasks: File a role the user states inside a question

**Linear issue**: AIE-1182 | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

## T1 — Pins (test-writer), prompt text (implementer)

Criteria US1.1-1.4, US2.1-2.2. test-writer adds plan.md B1-B3 to
`tests/test_prompts_remembering.py` and confirms they fail against `main` for the
right reason. implementer applies plan.md A to `src/wenchang/prompts/remembering.py`.

## T2 — Agent file and scenario citation (implementer)

Criteria US3.1-3.2. implementer runs `uv run python -m evals render-agent` (plan.md D),
records the sha256, and applies plan.md C to `evals/scenarios/remembering-stated-role.yaml`.
`tests/test_evals_agent.py` and `tests/test_evals_scenario.py` pass.

## T3 — Docs (doc-updater)

Criteria US3.1 (sha recorded), US4.1-4.6 (documented, human-run). Draft `review-pr.md`
per plan.md E.

## Gate

`make -C /Users/marksiebert/p/github/wenchang-AIE-1182 check` green after T1-T2 and after
T3. PR merge gated on the human live run (US4).
