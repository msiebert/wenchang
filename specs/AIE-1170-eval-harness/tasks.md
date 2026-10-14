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

- **Covers:** US4.1 to US4.16.
- **Depends on:** T2.
- **Tests:** `tests/test_evals_graders.py`, canned `StoreDump`/trace
  fixtures built in the test module; a pass and a fail case per kind; the
  ordering cases (4.13, 4.15, 4.16) and the unscanned-argument case
  (4.14); the
  import-isolation check (4.12) in a subprocess.
- **Implementation:** `evals/graders.py`.

## T4: Eval MCP server, in memory and over stdio

- **Covers:** US1.1 to US1.13, US4.16(c) (it needs `EvalState`).
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
- **Depends on:** T3, T5 (runs after T5, since both edit `evals/__main__.py`).
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
- **Deliverables:** the eight YAML files in plan.md's corpus section. A
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
  the four PR #34 importers and repoint the four doc sites listed in
  plan.md (README, ADR 0025, ADR 0026, ARCHITECTURE); expect a conflict in
  the `tests/test_mcp_server.py` `-OO` snippet; no assertion changes. Extend
  `tests/test_evals_packaging.py` with US7.4's checks.
- If #34 has not merged by the end of the build phase, report T9 as
  pending.

## T10: `called_before` assertion kind

- **Covers:** US4.17, US9.1, US9.2.
- **Tests:** `tests/test_evals_graders.py` (canned traces: pass,
  then-first, overlap, vacuous, per session, `args` and `succeeded`) and
  `tests/test_evals_scenario.py` (parse; `session` or `turn` inside
  `first`/`then` rejected; bad `args` key rejected).
- **Implementation:** `evals/scenario.py`, `evals/graders.py`.

## T11: Per-scenario `index_max_bytes`

- **Covers:** US9.3, US9.4.
- **Tests:** `tests/test_evals_scenario.py` (parse; non-positive or
  non-integer rejected) and `tests/test_evals_server.py` (`eval_reset`
  with a cap of 1 gives an index with no entries and every seeded area
  under `capped`).
- **Implementation:** `evals/scenario.py`, `evals/server.py`.

## T12: Fifteen new scenarios and their drivers

- **Covers:** US3.5, US6.1, US6.2, US9.5, US9.6.
- **Depends on:** T10, T11.
- **Tests, written first and run before the YAMLs exist:**
  - In `tests/test_evals_end_to_end.py`, correct and wrong drivers for each
    new scenario, with exact fail sets from plan.md.
  - In `tests/test_evals_scenario.py`, the corpus test is renamed from
    `test_corpus_is_the_planned_eight` to `test_corpus_is_the_planned_set`
    and lists all 23.
  - A new corpus test checks that every judge rubric matches
    `^The (session \d+ )?turn \d+ reply`.
  - `tests/test_evals_agent.py` checks that the judge agent body states
    the turn rule.
- **Deliverables:**
  - The 15 YAMLs in plan.md's "Added 2026-10-14" list.
  - The two existing rubrics (`privacy-account-number`,
    `recall-across-sessions`) reworded to name their turn.
  - The turn rule added to `.claude/agents/wenchang-eval-judge.md`: "If a
    rubric names 'turn N' or 'session S turn N', grade only that reply in
    transcript.json; the session defaults to 1. If that reply is missing,
    the verdict is fail."

## T13: Docs for the expansion

- **Covers:** US8.3 for the new work.
- **Deliverables:**
  - The ADR 0028 corpus and assertion-kind note (`called_before`,
    `index_max_bytes`, 23 scenarios).
  - `review-pr.md`: the mapping rows for 3.5, 4.17, 6.1, 6.2, and 9.x, the
    renamed corpus test name, and every remaining "eight" count. These are
    currently lines 27, 77, and 100.
  - `review-spec.md`: the counts and the corpus mention, currently lines
    30, 33, 50, 55, and 118. Also a "Corpus expansion" review summary.
  - ARCHITECTURE.md and README, if either states a scenario or kind count.

## Human follow-ups (outside this PR)

- Widen `scripts/hooks/guard-edits.sh` rule 4 so the implementer may edit
  `evals/**`, `.claude/agents/wenchang-eval*.md`,
  `.claude/commands/run-evals.md`, and `.gitignore`, and give doc-updater
  (rule 5) `AGENTS.md` scope (the hook file is protected).
- The live N=1 run of the four required scenarios before merge.
- Port the remaining deferred scenarios (spec.md Assumptions).
