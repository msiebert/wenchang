# Spec Review: AIE-1170 — Local behavioral eval harness run via Claude Code subagent

## What & why

Section 10.3 says prompt behavior is evaluated, not unit-tested, and seven
specs list eval scenarios that nothing runs. This adds a dev-only `evals/`
package that does:

1. **Eval MCP server.** It runs the seven memory tools over an in-memory
   store, using AIE-1060's `register_memory_tools` with a reference-adopter
   identity. Three harness tools reset and seed the store, record each
   turn, and dump the store and the timed tool-call trace to JSON.
2. **Eval subagent.** `wenchang-eval` gets the memory prompt with
   `omitClaudeMd: true`, and only the seven `mcp__wenchang__*` tools.
3. **Scenarios and graders.** Scenarios are YAML. Graders are pure functions
   over the dump and trace, with an optional LLM-judge rubric.
4. **Runner.** `/run-evals` runs in a session launched with
   `evals/mcp.json`, and `python -m evals` plans a run, grades trials, and
   writes a report.

The graders work without the driver, so a later SDK driver can reuse them.
Live runs stay out of `make check`. One live run is required before merge.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| US1 | eval server | list tools, reset, call, dump | Tools are `TOOL_NAMES` plus 3 harness tools, with descriptions equal to `tool_descriptions("Mixpanel")`. Trace records carry `request_id`, `duration_s`, and start and completion times. `eval_record_turn` tags the turn's calls. `trial_dir` must be under the runs root. Works over stdio |
| US2 | agent, judge, `evals/mcp.json`, runner doc | parse | Tools are exactly the 7 `mcp__wenchang__*`, with `omitClaudeMd: true`. A drift test pins the body. The config uses `${CLAUDE_PROJECT_DIR:-.}`. There is no root `.mcp.json`. The doc has the launch command and preflight |
| US3 | scenario YAML | load | Typed `Scenario` reusing `SeedFile`. 16 rejection cases, including `min > max`. The corpus is exactly 8 scenarios |
| US4 | 10 assertion kinds | grade canned dumps and traces | Pass and fail per kind. Order is `(session, turn, started_ms, seq)`, never `request_id`, which restarts per connection. `index_read_first` is strict: a parallel batch with the index read fails. `no_content_matching` never scans `expected_version` or `old_string`. Graders never import `mcp` |
| US5 | CLI | `new-run`, `grade`, `report` | Model and ids are validated. Per-assertion pass counts over N. Judge verdicts are kept separate |
| US6 | 8 scenarios | scripted correct and wrong drivers | Correct runs pass. Each wrong move fails its target assertion |
| US7 | packaging, fixture | inspect, rebase | `dev-mode-dirs`. The fixture is moved with importers rewritten (no shim), before and after #34 |
| US8 | `make check`, docs, PR | run, read | No model calls. `src/` never imports `evals`. ADR 0028, ARCHITECTURE, README, glossary, AGENTS.md. "Do not merge before one live N=1 run" |

The full Given/When/Then for all 56 criteria is in [spec.md](spec.md).

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| Harness tools live on the same server, and the agent's `tools:` excludes them | Second server; control files | One process holds the store. The model-facing surface is the allowlist (deviation from "surface matches `TOOL_NAMES`", recorded in ADR 0028) |
| `eval_record_turn` tags untagged calls; no `eval_begin_turn` | A begin-turn tool | A turn's calls complete before its reply, so tagging is exact |
| Order by `(session, turn, started_ms, seq)`; strict `index_read_first` | `seq`; integer `request_id`; accepting a parallel index batch | Records arrive in completion order. `request_id` restarts per connection (mcp 2.3.0). A call issued alongside the index read was not chosen from it |
| `evals/mcp.json` with `--mcp-config --strict-mcp-config --allowedTools mcp__wenchang` | Root `.mcp.json` | No prompt or extra tools in ordinary sessions. Schemas load directly. No per-call permission prompts |
| `omitClaudeMd: true`, plus a 2-sentence framing preamble | Default loading; bare prompt | CLAUDE.md files would contaminate trials. Without framing, a subagent treats turns as delegated tasks |
| Replies recorded verbatim by instruction | Reading Claude Code's transcript jsonl | That layout is internal |
| `dev-mode-dirs` makes `evals` importable | pytest `pythonpath` | Works for subprocesses, pyright, and pytest. Side effect: `tests`, `scripts`, and `docs` become namespace packages |
| 8 scenarios, each with correct and wrong scripted drivers | 17 unproven scenarios | Unproven assertions can ship unsatisfiable |

## Files/modules to be touched

- New `evals/` modules: `scenario`, `graders`, `server`, `agent`, `report`,
  `__main__`, and `reference_adopter`. Also `mcp.json` and 8 scenario
  YAMLs.
- New `.claude/` files: `agents/wenchang-eval.md` (generated),
  `agents/wenchang-eval-judge.md`, and `commands/run-evals.md`.
- Config: `pyproject.toml`, `uv.lock`, and `.gitignore`.
- 7 new `tests/test_evals_*.py` modules. `tests/prompts_reference_adopter.py`
  is deleted and its 6 import sites are rewritten. After #34, its 4 test
  modules are rewritten too.
- Docs: ADR 0028, `ARCHITECTURE.md`, `README.md`, the glossary, and
  `AGENTS.md`.

## Open questions / assumptions

- **Live run before merge.** The scripted driver is the in-build proof.
  The human or orchestrator then runs:

  ```
  claude --mcp-config evals/mcp.json --strict-mcp-config --allowedTools mcp__wenchang
  /run-evals --model sonnet --trials 1 privacy-account-number filing-alias-append recall-across-sessions forgetting-one-fact
  ```

- **Context leakage.** Environment details and git status still reach the
  eval agent. Whether auto-memory does too is unverified. Both are part of
  the known limitation.
- **Merge order: PR #34 before this PR.** T1 moves the fixture now. T9
  rewrites #34's importers after the rebase, and is reported as pending if
  #34 is late.
- **ADR number 0028.** It may collide with another in-flight issue. The
  next free number is used if so.

## Follow-ups

- **Human:** widen `scripts/hooks/guard-edits.sh` rule 4 for `evals/**`
  and the eval `.claude/` files. The hook is protected.
- Port the deferred scenarios, listed in spec.md's Assumptions, after the
  first live run.

## Risks

- Claude Code's harness prompt sits under the eval agent, so results guide
  prompt iteration but cannot gate releases.
- `on_call` misses schema-rejected calls.
- The runner could paraphrase a reply. That affects only the judge.

## Adversarial review

**Round 1: FAIL** (4 blocking, 11 should-fix, 7 nits), all folded in.

- **Blocking:**
  - **B1. Guard hook.** The AGENTS.md implementer row is widened. ADR 0028
    notes it against ADR 0004. Widening the hook itself is a human
    follow-up.
  - **B2.** `omitClaudeMd: true` on both eval agents (2.1, 2.6).
  - **B3.** `${CLAUDE_PROJECT_DIR:-.}` in `evals/mcp.json` (2.5).
  - **B4.** `no_content_matching` scans a fixed argument set (4.4). New
    test 4.14 covers it.
- **Should-fix:**
  - **S1.** Timing fields drive ordering (1.6, 4.1, 4.13).
    `issue_order` and integer `request_id` parsing are dropped.
  - **S2.** The tool-surface deviation is recorded.
  - **S3.** `eval_begin_turn` is cut (1.7).
  - **S4.** The live run is a merge gate (8.4).
  - **S5, S6.** Dedicated launch flags and the preflight (2.7).
  - **S7.** The YAML example is fixed, and `min > max` is rejected.
  - **S8.** Every scenario is scripted-proven (US6).
  - **S9.** Six plus four importers are listed, with no shim.
  - **S10.** `eval_record_turn` is kept, with `agent_id`.
  - **S11.** The loading note is corrected.
- **Nits:**
  - `SeedFile` and `seed_path` are reused.
  - Regex case rules and vacuity rules are stated.
  - `trial_dir` must be under the runs root.
  - "Atomic swap" is dropped.
  - `--model` is validated.
  - The test modules are merged down to 7.
- **Cut:**
  - `eval_begin_turn`, `render-agent --check`, and `validate`.
  - The `called_before`, `max_tool_calls`, `file_exists`,
    `file_unchanged`, and `alias_absent` assertion kinds.
  - 9 of the 17 scenarios.
