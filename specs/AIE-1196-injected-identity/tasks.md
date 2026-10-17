# Tasks: AIE-1196 The agent knows the user only through memory and the conversation

All new test docstrings cite AIE-1196.

## Phase 1: Held-out evidence (US1), before any prompt edit

- [ ] T001 [test-writer] In `tests/test_evals_scenario.py`: add the five new
  ids to `CORPUS`; add pattern tests (US1.8): all `no-operator-name`
  assertions across the corpus are exactly the seven planned scenarios and
  share one pattern; the pattern matches and rejects the spec's sample
  strings; no scenario turn matches it; every held-out turn is first
  person and contains none of "only through memory", "anywhere else",
  "call them".
- [ ] T002 [test-writer] In `tests/test_evals_end_to_end.py`: correct and
  wrong drivers for the five new ids with the spec's fail sets (US1.1-1.5).
- [ ] T003 [implementer] Add the five YAMLs and edit the two originals
  (US1.1-1.6) per plan.md. `make check` green.
- [ ] T004 [orchestrator] Commit the held-out evidence.

## Phase 2: Prompt (US2)

- [ ] T005 [test-writer] In `tests/test_prompts_applying_memory.py`: US2.1
  phrases, US2.2 forbidden terms and pattern. In `tests/test_evals_scenario.py`:
  US2.3 (assembled prompt and agent file free of the pattern) and US2.4
  (headers cite the new sentence).
- [ ] T006 [implementer] Add the paragraph to `applying_memory.BODY`, update
  the seven headers, run `uv run python -m evals render-agent`. `make check`
  green.
- [ ] T007 [orchestrator] Commit the prompt change.

## Phase 3: Review and PR

- [ ] T008 [doc-updater] `review-pr.md` with final text, held-out list,
  AC-to-test table, agent sha256, and the live gate.
- [ ] T009 [reviewers] spec-reviewer, code reviewer, generality reviewer;
  fix findings.
- [ ] T010 [orchestrator] Push and open the PR; move the issue to In Review.
