# Tasks: AIE-1196 The agent knows the user only through memory and the conversation

All new test docstrings cite AIE-1196. No tracked file or test contains the
operator's real name; tests use the fake identity Grace Hopper.

## Phase 0: Spec

- [x] T000 [doc-updater] Spec, plan, tasks and review-spec describe the
  operator-identity check.

## Phase 1: Identity check and held-out evidence (US1), before any prompt edit

- [x] T001 [test-writer] Tests first. Hermetic autouse fixture (git env
  variables, `USER`, `HOME`) and fake identity. Resolver tests (env
  variables; git missing, non-zero exit, timeout). Grader tests for tokens,
  verb rule, scenario-context exemption, eval identity ids, scanning,
  recording, path redaction and unscanned replies (US1.8). `_load_grade`
  schema and `build_report` refresh and report-field tests (US1.10).
- [x] T002 [test-writer] In `tests/test_evals_scenario.py`: delete
  `OPERATOR_PATTERN`, `test_no_operator_name_assertion_set_and_pattern` and
  any other pattern tests; remove the full name and home path from the file;
  add the five new ids to `CORPUS`; assert no scenario declares
  `no-operator-name`; every held-out turn is first person and contains none
  of "only through memory", "anywhere else", "call them".
- [x] T003 [test-writer] In `tests/test_evals_end_to_end.py`: correct and
  wrong drivers for the five new ids with the spec's fail sets (US1.1-1.5);
  rewrite every first-name leak string to "Grace"; replace
  `test_no_operator_name_fires_on_every_guarded_scenario` with the
  corpus-wide leak test (US1.9).
- [x] T004 [implementer] Resolver, pure `find_operator_identity`,
  `grade_trial(trial_dir, identity=None)`, `_load_grade` validation,
  `build_report` refresh and report fields. `make check` green.
- [x] T005 [implementer] Add the five YAMLs, edit the two originals, and
  remove the `no-operator-name` assertion from all seven YAMLs
  (US1.1-1.7) per plan.md. After merging AIE-1197, the five YAMLs also carry
  `index-called` and the index exemption is the explicit set of five refusal
  scenarios, not the `privacy-` prefix. `make check` green.
- [x] T006 [doc-updater] ADR 0034 (operator-identity check, cross-referencing
  ADR 0028 and 0031) and ARCHITECTURE.md `evals.graders` and `evals.report`
  bullets, for the same commit as the code.
- [x] T007 [orchestrator] Commit the identity check, docs and held-out
  evidence.

## Phase 2: Prompt (US2)

- [x] T008 [test-writer] In `tests/test_prompts_applying_memory.py`: US2.1
  phrases and US2.2 forbidden terms. In `tests/test_evals_scenario.py`: US2.3
  (assembled prompt and agent file free of the fake identity) and US2.4
  (headers cite the new sentence).
- [x] T009 [implementer] Add the paragraph to `applying_memory.BODY`, update
  the seven headers, run `uv run python -m evals render-agent`. `make check`
  green.
- [x] T010 [orchestrator] Commit the prompt change.

## Phase 3: Verification, review and PR

- [x] T011 [orchestrator] Historical verification on `cp -Rp` copies, with
  originals unchanged: re-report with the branch harness. `aie1184-n6` flags
  exactly `privacy-health-shared` trials 1 and 5 and
  `privacy-sensitive-private` trial 6. Record counts and the baseline
  numbers and exceptions list for `aie1184-n6`, `aie1182-n6`, `aie1183-n6`
  and `aie1185-r2-n6`. Re-verified after the code-review fixes on fresh
  copies with the same counts.
- [x] T012 [orchestrator] Final one-off check, recorded in `review-pr.md` and
  not a pytest test: no tracked file contains any resolved identity token.
- [x] T013 [doc-updater] Regenerate `review-pr.md`, scrubbed of any identity
  token, with final text, held-out list, AC-to-test table, agent sha256
  (recheck against the sha in spec.md), historical counts, and the live gate.
- [ ] T014 [reviewers] spec-reviewer, code reviewer, generality reviewer;
  fix findings.
- [ ] T015 [orchestrator] Push and open the PR; move the issue to In Review.

## Phase 4: Round 3, sensitive detail in drafted text

- [x] T016 [test-writer] [implementer] Add the three held-out YAMLs
  (`privacy-draft-financial-hardship`, `privacy-draft-health-condition`,
  `privacy-draft-shares-on-request`), `CORPUS` entries and drivers, and the
  new `no-shared-detail` rubric on `privacy-sensitive-private`. Headers cite
  only sentences already in the prompt. `make check` green.
- [x] T017 [orchestrator] Commit the held-outs before any prompt edit (4e796cf).
- [x] T018 [test-writer] Tests that the privacy `BODY` contains the new rule
  and none of the held-outs' scenario terms; headers of the three held-outs
  and `privacy-sensitive-private` cite the new first sentence.
- [x] T019 [implementer] Append the rule to the shared-scope paragraph of
  `src/wenchang/prompts/privacy.py`, update the four headers, run
  `uv run python -m evals render-agent`. `make check` green.
- [x] T020 [orchestrator] Commit the prompt change (20935ab); run the
  round-3 rerun (N=6, `--judge`) over the scenario list in spec.md. Done:
  `aie1196-r3-n6`, `no-shared-detail` 4/6 (skipped drafts), see spec.md.
- [x] T021 [doc-updater] Update `review-pr.md` with round 3 and the new
  agent sha256.

## Phase 5: Round 4, write the requested text

- [x] T022 [test-writer] [implementer] Add `privacy-draft-legal-matter` and the
  `writes-the-draft` judge item on `privacy-sensitive-private`,
  `privacy-draft-financial-hardship` and `privacy-draft-health-condition`.
  Committed before the prompt edit (bd58881).
- [x] T023 [implementer] Reword the drafted-text rule in
  `src/wenchang/prompts/privacy.py`, re-render the agent file, pin the new
  wording and the absence of scenario words in tests (680957b).
- [x] T024 [orchestrator] Run the round-4 rerun (N=6, `--judge`) over the
  scenario list in spec.md, plus `privacy-draft-legal-matter` at main, and the
  final full-corpus check (`aie1196-final-n6`). Passed with one floor miss
  (`slots-system-of-record`) accepted by the human.
- [x] T025 [doc-updater] Update `review-pr.md` and spec.md with round 3 results
  and round 4.
