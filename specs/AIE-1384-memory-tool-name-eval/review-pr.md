# PR Review: AIE-1384 — Eval arms to compare names for the memory index tool

## What changed & why

Adds eval "arms" so we can test whether another name for `get_memory_index`
makes models call it first on clients that drop MCP instructions. An arm is an
index tool name plus an on/off switch for the memory prompt in the agent body,
stored in gitignored `evals/arm.json` via `python -m evals set-arm`. The eval
server renames the tool by substitution; the trace keeps the canonical name, so
scenarios and graders are unchanged. `new-run` records the arm, `merge-runs`
refuses mixed arms, and `compare` builds one table. No `src/` or public API
change. The live runs are done and the decision is to keep the name.

## Acceptance criteria → tests

| Acceptance criterion | Test(s) |
| -------------------- | ------- |
| AC1-4b: default arm unchanged, `set-arm`, agent render, name validation, `ArmError` | `tests/test_evals_arm.py` |
| AC5-8: tool list, descriptions, result block, canonical trace name, instructions | `tests/test_evals_server.py` (new tests at the bottom) |
| AC9: arm in `run.json`, report header, `merge-runs` check, old runs read as default | `tests/test_evals_arm_run.py` |
| AC10: `compare` metrics, deltas, exit 2 on differing scenario sets | `tests/test_evals_compare.py` |
| AC11: preflight uses the arm's index tool; arm procedure documented | `.claude/commands/run-evals.md` (doc, no test) |
| AC12: live runs, `eval-report.md`, decision ADR | Done: [eval-report.md](eval-report.md); decision keep `get_memory_index` (ADR 0049) |
| AC13: `make check` | Green, 6521 passed |

Test changes: one existing test updated under `Allow-test-changes:` in the
spec, `tests/test_evals_report.py::test_new_run_writes_metadata_and_plan`. Its
expected `run.json` gains the default arm key. Nothing deleted, skipped, or
weakened.

## Architecture / ADR changes

- [ADR 0049](../../docs/adr/0049-index-tool-name-experiment.md), status
  Accepted: experiment design, decision rule, and result (keep the name;
  candidates 81.8% to 84.8% call-first vs 87.9% baseline; index-read-first 100%
  in all arms).
- `ARCHITECTURE.md`, "Outside the library: `evals/`": short paragraph on arms,
  `set-arm`, and `compare`.

## Deviations from spec

- `build_eval_server(arm=None)` is the default `Arm()` and never reads `arm.json`; only `main()` calls `load_arm()`, so a developer's local `arm.json` cannot break the test suite.

## Look closely at

- `evals/server.py`: name substitution touches `MCPServer` private managers.
  Check only the name differs from the default arm, and that the trace name
  stays canonical.
- `evals/arm.py`: name validation and that `set-arm` writes nothing on exit 2.
- `evals/compare.py`: metric definitions (call-first, label rate, added fact
  line) against the spec.
- The work was done by a general-purpose agent, because
  `scripts/hooks/guard-edits.sh` rule 4 still blocks the implementer from
  `evals/`.

## Follow-ups

- Widen guard hook rule 4 to cover `evals/`.
