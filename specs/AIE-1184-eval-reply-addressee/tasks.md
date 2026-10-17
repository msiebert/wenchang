# Tasks: AIE-1184 eval reply addressee

Spec: [spec.md](spec.md). Plan: [plan.md](plan.md). Run the tasks in
order. Write each task's tests first and confirm they fail for the right
reason, then implement. Get `make check` green before the next task.

## T1 — Reply check grader (US1)

- **Tests:** append to `tests/test_evals_graders.py` one canned-transcript
  test per spec criterion, 1.1 to 1.15.
- **Implementation:** add `THIRD_PERSON_PATTERN`, `ThirdPersonReply`, and
  `find_third_person_replies` to `evals/graders.py`, per plan §2.1.

## T2 — grade.json, CLI, and re-grade rules (US2.2 to 2.9)

- **Tests:** append to `tests/test_evals_report.py`.
- **Implementation:** update `evals/report.py` and `evals/__main__.py`.

## T3 — Report aggregation and markdown (US2.10 to 2.15)

- **Tests:**
  - append to `tests/test_evals_report.py`;
  - add the `third_person_replies: []` check to the correct-driver test in
    `tests/test_evals_end_to_end.py`.
- **Implementation:** update `build_report` and `_markdown`.

## T4 — Preamble (US2.1)

- **Tests:** rewrite the pin test's expected string, and its docstring to
  cite AIE-1184.
- **Implementation:**
  - update `EVAL_AGENT_PREAMBLE`;
  - run `uv run python -m evals render-agent` and record the new sha256;
  - append the sentence to section 4 of `run-evals.md`.

## T5 — Docs

Write:

- ADR 0031;
- a pointer in ADR 0028's Consequences;
- the ARCHITECTURE.md `evals.graders` and `evals.report` bullets;
- `review-pr.md`, with the live-eval section PENDING.

## T6 — Measurement gate (human, US3)

1. Keep the AIE-1170 worktree. Re-grade copies of runs A and B (US3.1).
2. On this branch, before AIE-1182 or AIE-1183 land, run two N=3 runs
   with `--judge`. Count only the 23 baseline ids.
3. Apply US3.2 (a), (b), and (c), and spot-check the stored fact lines
   (US3.3).
4. If the gate fails, revert T4 (US3.4).
5. Record the results in ADR 0031 and `review-pr.md`. Merge AIE-1184
   before AIE-1182 and AIE-1183.
