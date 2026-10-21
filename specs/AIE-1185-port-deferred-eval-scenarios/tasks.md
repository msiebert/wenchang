# Tasks: Port the deferred eval scenarios

**Linear issue**: AIE-1185 | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

The branch is rebased onto `AIE-1184-eval-reply-addressee` (6e1d259)
before any grader or report code. Every task runs the same loop:

1. test-writer writes failing tests, with "AIE-1185, USx.y" in each
   docstring, and confirms they fail for the right reason.
2. implementer makes them pass.
3. Run `make -C <repos>/wenchang-AIE-1185 check` and
   get it green.

## T1: Reply assertion kinds

- **Covers:** US1.1 to US1.8.
- **Tests:**
  - `test_evals_scenario.py`: parse and reject cases for both kinds. The
    closed-set test gains exactly two kinds.
  - `test_evals_graders.py`: canned transcripts, and the US1.8 replies
    against the `no-trait-reply` pattern.
  - `test_evals_report.py`: `grade_trial` with no transcript, a valid one,
    and a malformed one. A full regrade happens on a newer transcript for a
    reply-kind scenario. AIE-1184's refresh-only path still applies to a
    scenario without reply kinds.
- **Implementation:**
  - `evals/scenario.py`: `ReplyMatching` and `ReplyNotMatching`.
  - `evals/graders.py`: the `grade` transcript parameter, the two helpers,
    and the module docstring.
  - `evals/report.py`: a single transcript load in `grade_trial`,
    `uses_reply_kinds`, and `_grade_is_current(trial_dir, scenario)`.

## T2: Context records

- **Covers:** US2.1 to US2.4.
- **Tests:**
  - `test_evals_scenario.py`: `context_records` parse and reject cases.
  - `test_evals_report.py`: `turn_prompt` with and without records.
  - `test_evals_agent.py`: the two `run-evals.md` sentences.
- **Implementation:**
  - `evals/scenario.py`: `ContextRecord` and `Scenario.context_records`.
  - `evals/report.py`: `turn_prompt`.
  - `.claude/commands/run-evals.md`.

## T3: Ten scenarios and their drivers

- **Covers:** US3.1 to US3.5.
- **Tests:**
  - `test_evals_end_to_end.py`: `Driver.turn` gains a `reply` argument;
    20 drivers; 10 `CASES` rows.
  - `test_evals_scenario.py`: the corpus at 37, `CITATIONS`, and the
    rubric form.
- **Implementation:**
  - The `applying` category.
  - Ten YAMLs.
  - The header comment in `curated-shared-conflict.yaml`.
- If a wrong driver's fail set differs from spec.md, stop and report. Do
  not edit the set.

## T4: Docs

- **Covers:** US4.1 to US4.5. Owned by doc-updater.
- **Changes:**
  - ADR 0032.
  - The ADR 0028 §3 and §7 pointers.
  - ARCHITECTURE.md.
  - The AIE-1170 deferred-list pointer.
  - `review-pr.md`, with the live sections marked PENDING.

## T5: Offline regression check

- **Covers:** US5.7. The orchestrator runs it.
- **Steps:** follow plan.md "Offline regression check" and record the
  result in `review-pr.md`.

## T6: Live run (human)

- **Covers:** US5.1 to US5.6.
- **Steps:**
  1. Run two headless shard sessions: `/run-evals --model sonnet --trials 3
     --judge --shard k/2 <ten ids>`.
  2. Combine them with `merge-runs`.
  3. Classify every miss.
  4. Fill in the PENDING sections of `review-pr.md`.
- The PR is not merged before this run.

## T7: Held-out forgetting scenarios and prompt fix

- **Covers:** US6.1 to US6.10.
- **Steps:**
  1. test-writer and implementer add the four held-out scenarios (commit
     e5f9406), before any prompt edit.
  2. test-writer adds phrase tests in `test_prompts_forgetting.py` and
     citations in the `forgetting-ambiguous-that` and `forgetting-two-files`
     headers.
  3. implementer edits `forgetting.py` and re-renders
     `.claude/agents/wenchang-eval.md`.
  4. Run `make check`.
  5. Human reruns live: `forgetting-ambiguous-that`, the four held-outs,
     `forgetting-two-files`, `forgetting-one-fact`, `forgetting-whole-file`,
     `forgetting-only-fact`, `forgetting-nickname-alias`.
