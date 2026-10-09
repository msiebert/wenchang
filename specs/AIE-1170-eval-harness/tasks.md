# Tasks: Local behavioral eval harness

**Linear issue**: AIE-1170 | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

Each task follows the same loop:

1. Write the failing tests.
2. Run them and confirm they fail for the right reason.
3. Implement.
4. Re-run the tests.
5. Get `make check` green.
6. Commit as `AIE-1170: <what>`.

## T1: `evals/` package, config, and the reference adopter move

- **Covers:** US7.1 to US7.3, US8.2.
- **Config:** `uv add --dev pyyaml types-pyyaml`; `dev-mode-dirs`; pyright
  `include`; ruff `src` and first-party; `.gitignore` `evals/runs/`.
- **Tests:** `tests/test_evals_packaging.py`: wheel packages exactly
  `["src/wenchang"]`; `dev-mode-dirs`; `import evals.reference_adopter` in a
  subprocess whose cwd is a temp dir; `pyyaml` and `types-pyyaml` in the dev
  group only; no `src/wenchang` module imports `evals` (`ast`);
  `tests/prompts_reference_adopter.py` is absent.
- **Implementation:** `evals/__init__.py`; `evals/reference_adopter.py`
  from `git show AIE-1059-e2e-reference-adopter:tests/reference_adopter.py`;
  delete `tests/prompts_reference_adopter.py`; rewrite the six import sites
  listed in plan.md (including the `test_mcp_server.py` subprocess
  snippet). Existing tests stay green with no assertion changes.

## T2: Scenario types and loader

- **Covers:** US3.1 to US3.3.
- **Depends on:** T1.
- **Tests:** `tests/test_evals_scenario.py` with YAML written to `tmp_path`;
  one test per rejection case in US3.3.
- **Implementation:** `evals/scenario.py`.

## T3: Graders and loaders

- **Covers:** US4.1 to US4.14.
- **Depends on:** T2.
- **Tests:** `tests/test_evals_graders.py`, canned `StoreDump`/trace
  fixtures built in the test module; a pass and a fail case per kind; the
  ordering cases (4.13) and the unscanned-argument case (4.14); the
  import-isolation check (4.12) in a subprocess.
- **Implementation:** `evals/graders.py`.

## T4: Eval MCP server, in memory and over stdio

- **Covers:** US1.1 to US1.13.
- **Depends on:** T2, T3.
- **Tests:** `tests/test_evals_server.py` through an in-memory MCP
  `Client(build_eval_server(EvalState(runs_root=tmp_path)))`; the stdio
  case launches `sys.executable -m evals.server --runs-root <tmp>` with
  `cwd` a temp dir and a 30 s timeout.
- **Implementation:** `evals/server.py`.

## T5: Agent definitions, launch config, runner doc

- **Covers:** US2.1 to US2.7.
- **Depends on:** T1.
- **Tests:** `tests/test_evals_agent.py` (frontmatter parsed with `yaml`;
  `render-agent --out` via `main(argv)`; `evals/mcp.json`; no root
  `.mcp.json`; the judge agent; the runner doc's required strings).
- **Implementation:** `evals/agent.py`, the `render-agent` subcommand in
  `evals/__main__.py`, the generated `.claude/agents/wenchang-eval.md`,
  `.claude/agents/wenchang-eval-judge.md`, `evals/mcp.json`,
  `.claude/commands/run-evals.md`.

## T6: Run planning, grading, report, CLI

- **Covers:** US5.1 to US5.5.
- **Depends on:** T3.
- **Tests:** `tests/test_evals_report.py` with a fixed `now` and
  `runs_dir=tmp_path`; CLI exercised through `main(argv)`.
- **Implementation:** `evals/report.py`; `new-run`, `grade`, `report`
  subcommands.

## T7: Scenario corpus and scripted end to end

- **Covers:** US3.4, US3.5, US6.1, US6.2, US8.1.
- **Depends on:** T4, T6.
- **Tests:** corpus checks appended to `tests/test_evals_scenario.py`;
  `tests/test_evals_end_to_end.py` with one correct and one wrong scripted
  driver per scenario, through `Client(build_eval_server(...))` into
  `tmp_path`, then `grade_trial` and `build_report`.
- **Deliverables:** the eight YAML files in plan.md's corpus table. A
  scenario whose correct driver cannot pass is fixed or dropped, never
  shipped unproven.

## T8: Docs and review artifact

- **Covers:** US8.3, US8.4.
- **Deliverables:** ADR 0028; ARCHITECTURE.md; README "Behavioral evals";
  glossary; AGENTS.md implementer row; `review-pr.md` with the
  criteria-to-test table and the "do not merge before one live N=1 run"
  block with the exact commands.

## T9: Relocation after PR #34 merges

- **Covers:** US7.4.
- **Precondition:** PR #34 is on `main`. Rebase as the orchestrator
  directs.
- **Work:** delete `tests/reference_adopter.py`; replace
  `evals/reference_adopter.py` with `main`'s fixture if it changed; rewrite
  the four PR #34 importers listed in plan.md; no assertion changes. Extend
  `tests/test_evals_packaging.py` with US7.4's checks.
- If #34 has not merged by the end of the build phase, report T9 as
  pending.

## Human follow-ups (outside this PR)

- Widen `scripts/hooks/guard-edits.sh` rule 4 so the implementer may edit
  `evals/**`, `.claude/agents/wenchang-eval*.md`,
  `.claude/commands/run-evals.md`, and `.gitignore` (the hook file is
  protected).
- The live N=1 run of the four required scenarios before merge.
- Port the deferred scenarios after the first live run calibrates them.
