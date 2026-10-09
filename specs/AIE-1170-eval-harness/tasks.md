# Tasks: Local behavioral eval harness

**Linear issue**: AIE-1170 | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

Each task follows the same loop:

1. Write the failing tests.
2. Run them and confirm they fail for the right reason.
3. Implement.
4. Re-run the tests.
5. Get `make check` green.
6. Commit as `AIE-1170: <what>`.

## T1: `evals/` package skeleton, config, and the reference adopter copy

- **Covers:** US7.2, US8.2; the pre-#34 half of the relocation (plan,
  "Branch base and merge ordering").
- **Config:** `uv add --dev pyyaml types-pyyaml`; `dev-mode-dirs`; pyright
  `include`; ruff `src` and first-party; `.gitignore` `evals/runs/`.
- **Tests:** `tests/test_evals_packaging.py`: wheel packages exactly
  `["src/wenchang"]`; `import evals` and `import evals.reference_adopter`
  succeed in a subprocess whose cwd is a temp dir; `pyyaml` and
  `types-pyyaml` are in the dev group and nowhere else; no `src/wenchang`
  module imports `evals` (`ast`).
- **Implementation:** `evals/__init__.py`; `evals/reference_adopter.py`
  from `git show AIE-1059-e2e-reference-adopter:tests/reference_adopter.py`;
  `tests/prompts_reference_adopter.py` re-exports from it (existing prompt
  tests unchanged and green).

## T2: Scenario types and loader

- **Covers:** US3.1 to US3.3.
- **Depends on:** T1.
- **Tests:** `tests/test_evals_scenario.py` with YAML written to `tmp_path`;
  one test per rejection case in US3.3.
- **Implementation:** `evals/scenario.py`.

## T3: Graders and loaders

- **Covers:** US4.1 to US4.16.
- **Depends on:** T2.
- **Tests:** `tests/test_evals_graders.py`, canned `StoreDump`/trace
  fixtures built in the test module; pass and fail case per kind; the
  import-isolation check (4.15) runs in a subprocess.
- **Implementation:** `evals/graders.py`.

## T4: Eval MCP server

- **Covers:** US1.1 to US1.12.
- **Depends on:** T2, T3.
- **Tests:** `tests/test_evals_server.py` through an in-memory MCP
  `Client(build_eval_server())`, scenario files in `tmp_path`.
- **Implementation:** `evals/server.py`.

## T5: Stdio

- **Covers:** US1.13.
- **Depends on:** T4.
- **Tests:** `tests/test_evals_server_stdio.py`: launches
  `sys.executable -m evals.server` with `cwd=tmp_path`, 30 s timeout.

## T6: Agent definitions and server registration

- **Covers:** US2.1 to US2.5, US5.6.
- **Depends on:** T1.
- **Tests:** `tests/test_evals_agent.py` (frontmatter parsed with `yaml`;
  `render-agent --check` exit codes via `main(argv)` against a temp copy).
- **Implementation:** `evals/agent.py`, the `render-agent` subcommand in
  `evals/__main__.py`, the generated `.claude/agents/wenchang-eval.md`,
  hand-written `.claude/agents/wenchang-eval-judge.md`, `.mcp.json`.

## T7: Run planning, grading, report, CLI

- **Covers:** US5.1 to US5.4.
- **Depends on:** T3.
- **Tests:** `tests/test_evals_report.py` with a fixed `now` and
  `runs_dir=tmp_path`; CLI exercised through `main(argv)`.
- **Implementation:** `evals/report.py`, `validate`, `new-run`, `grade`,
  `report` subcommands.

## T8: Scenario corpus and runner doc

- **Covers:** US3.4, US3.5, US5.5.
- **Depends on:** T2, T6.
- **Tests:** `tests/test_evals_corpus.py`: every scenario loads, ids
  unique, categories covered, `source` files exist; the runner doc names
  every harness tool, CLI subcommand, and `wenchang-eval`.
- **Deliverables:** the 17 YAML files in plan.md's corpus table;
  `.claude/commands/run-evals.md`.

## T9: Scripted end to end

- **Covers:** US6.1, US6.2, US8.1.
- **Depends on:** T4, T7, T8.
- **Tests:** `tests/test_evals_end_to_end.py`: for the four required
  scenarios, a correct and a wrong scripted driver through
  `Client(build_eval_server())` into `tmp_path`, then `grade_trial` and
  `build_report`.

## T10: Relocation after PR #34 merges

- **Covers:** US7.1.
- **Precondition:** PR #34 is on `main`. Rebase onto `main` (after AIE-1060
  merges) or onto `AIE-1060-host-mounting` rebased on such a `main`, as the
  orchestrator directs.
- **Work:** delete `tests/reference_adopter.py` and
  `tests/prompts_reference_adopter.py`; replace `evals/reference_adopter.py`
  with `main`'s fixture if it changed; switch every importer to
  `evals.reference_adopter`; no assertion changes. Extend
  `tests/test_evals_packaging.py` with US7.1's checks.
- If #34 has not merged by the end of the build phase, report T10 as
  pending.

## T11: Docs and review artifact

- **Covers:** US8.3.
- **Deliverables:** ADR 0028; ARCHITECTURE.md; README "Behavioral evals";
  glossary; `review-pr.md` with the criteria-to-test table.
- **Manual check:** if a fresh Claude Code session is available, one live
  run of the four required scenarios with N=1, reported in review-pr.md.
