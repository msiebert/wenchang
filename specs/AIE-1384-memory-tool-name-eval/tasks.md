# Tasks: AIE-1384 eval arms for index tool names

Tests first; implementation never edits `tests/`. Run `make check` at the end
of the code tasks. Live runs are human only.

- [x] T1 — `evals/arm.py` (AC4, AC4b).
  - test-writer: `tests/test_evals_arm.py`.
  - implementer: `evals/arm.py`.
  - Given an invalid name, Then `Arm(...)` raises `ArmError`.
  - Given a missing file, Then `load_arm` returns `Arm()`; given bad JSON,
    unknown keys, or wrong types, Then `ArmError`.
  - Given an arm, Then `save_arm` and `load_arm` round-trip and
    `rename_index_tool` replaces every `get_memory_index`.
- [x] T2 — Agent rendering and `set-arm` (AC1 to AC3, AC4).
  - test-writer: agent tests and `set-arm` CLI tests.
  - implementer: `evals/agent.py`, `evals/__main__.py`.
  - Given no arm, Then output equals today's and the committed agent file.
  - Given `set-arm --index-tool load_memory --no-agent-prompt`, Then
    `arm.json` and the agent file are as in AC2.
  - Given an invalid name, Then exit 2 and nothing written.
- [x] T3 — Eval server arms (AC5 to AC8).
  - test-writer: new tests in `tests/test_evals_server.py`.
  - implementer: `evals/server.py` (`build_eval_server(state, arm)`, `main()`).
  - Given arm X, Then the tool list, descriptions, result blocks, trace name,
    and instructions are as in AC5 to AC8.
- [x] T4 — Arm in `run.json`, report header, `merge-runs` check (AC9).
  - test-writer: run-recording and merge tests.
  - implementer: `evals/__main__.py`, `evals/report.py`.
  - Given a run with no `"arm"`, Then it reads as the default arm.
  - Given runs with different arms, Then `merge-runs` exits 2.
- [x] T5 — `compare` command (AC10).
  - test-writer: `tests/test_evals_compare.py` with small fixture runs
    (inspect the existing run fixtures in `tests/` for formats).
  - implementer: `evals/compare.py`, `compare` subcommand in
    `evals/__main__.py`.
  - Given fixture runs, Then each metric, the deltas, and the exit-2 case for
    differing scenario sets are as in AC10.
- [x] T6 — Run procedure and ignore rule (AC11).
  - implementer: `.claude/commands/run-evals.md` (preflight uses the arm's
    index tool; arm procedure section), `.gitignore` (`evals/arm.json`).
- [x] T7 — Docs (doc-updater).
  - ADR draft for the experiment design (arms, pre-registered rule,
    alternatives rejected); decision filled in at T8.
  - Evals docs: arms, `set-arm`, `compare`.
  - Draft `review-pr.md`.
- [x] T7b — `make check` green (AC13).
- [x] HUMAN CHECKPOINT — live runs, one fresh session per arm, in a session
  launched as `/run-evals` requires. For each of the five arms:
  `set-arm`, relaunch, `new-run` with the panel ids (Sonnet 5.5 (`--model sonnet`), 3 trials),
  `grade`, then `set-arm --reset`. Optional: default arm with the agent prompt
  on.
- [x] T8 — `eval-report.md` and the decision (AC12).
  - Run `compare` over the five runs, baseline `get_memory_index`; save the
    output as `specs/AIE-1384-memory-tool-name-eval/eval-report.md`.
  - Apply the decision rule; record the result in the ADR.
- [-] T9 — Not needed: the decision was to keep `get_memory_index`.
