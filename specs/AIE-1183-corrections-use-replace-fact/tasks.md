# Tasks: Corrections use replace_fact (AIE-1183)

Tests come first. In each task, test-writer writes the failing tests,
implementer makes them pass, and `make check` must be green before the
next task starts.

- [ ] T1 (US1, US2), test-writer:
  - Add the prose tests from plan §4.
  - Add the end-to-end driver and fail-set changes from plan §3.
  - Confirm they fail for the right reason: the new sentences are missing,
    and `old-recipient-gone` is not a known assertion yet.
- [ ] T2 (US1), implementer: replace `write_mechanics.BODY` with the exact
  text in plan §1.
- [ ] T3 (US2), implementer: edit `evals/scenarios/recall-replace-fact.yaml`
  as described in plan §2.
- [ ] T4 (US3), implementer:
  - Run `uv run python -m evals render-agent`.
  - Confirm `tests/test_evals_agent.py` passes.
  - Run `make check`.
- [ ] T5, doc-updater: write `review-pr.md` (plan §6), including the agent
  sha256 and the commit.
- [ ] T6, human: run the live checks (plan, "Live runs") and record the
  results in `review-pr.md`.
