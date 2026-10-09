# Spec Review: AIE-1170 — Local behavioral eval harness run via Claude Code subagent

## What & why

Section 10.3 says prompt behavior is evaluated, not unit-tested, and eight
specs list eval scenarios that nothing runs. This adds a dev-only `evals/`
package that does:

1. **Eval MCP server.** It runs the seven memory tools over an in-memory
   store, using AIE-1060's `register_memory_tools` with a reference-adopter
   identity. Four harness tools reset and seed the store, tag turns, record
   replies, and dump the store and tool-call trace to JSON.
2. **Eval subagent.** `wenchang-eval` gets the memory prompt and only the
   seven `mcp__wenchang__*` tools.
3. **Scenarios and graders.** Scenarios are YAML. Graders are pure functions
   over the dump and trace, with an optional LLM-judge rubric.
4. **Runner.** `/run-evals` plus `python -m evals` plan a run, grade
   trials, and write a report.

The graders work without the driver, so a later SDK driver can reuse them.
Live runs stay out of `make check`.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| US1 | eval server | list tools, reset, call, dump | Tools are `TOOL_NAMES` plus 4 harness tools, with descriptions equal to `tool_descriptions("Mixpanel")`. Reset swaps the store, identity, and trace atomically. The trace is tagged by session and turn, and carries each record's MCP `request_id` and `duration_s`. Dump writes `store.json`, `trace.json`, and `transcript.json`. It works over stdio |
| US2 | `.claude/agents/wenchang-eval.md`, `.mcp.json` | parse | Tools are exactly the 7 `mcp__wenchang__*`. The body is the preamble plus the prompt, and a drift check enforces it. The name is not guard-routed. Server name `wenchang` |
| US3 | scenario YAML | load | Typed `Scenario`. 15 rejection cases raise `ScenarioError`. The corpus covers privacy, filing, recall, and forgetting |
| US4 | 15 assertion kinds | grade canned dumps and traces | Pass and fail per kind. Order-sensitive checks use issue order: integer `request_id`, with `seq` as the fallback. Graders never import `mcp` |
| US5 | CLI | `new-run`, `grade`, `report` | Writes run and trial metadata, `grade.json`, and `report.md`/`report.json` with per-assertion pass counts over N. Judge verdicts are kept separate |
| US6 | 4 required scenarios | scripted correct and wrong drivers | Correct runs get all passes. Each wrong run fails its target assertion |
| US7 | after PR #34 | rebase | `evals/reference_adopter.py` is the only fixture, and imports are switched |
| US8 | `make check`, docs | run, read | No model calls. `src/` never imports `evals`. ADR 0028, ARCHITECTURE, README, glossary |

The full Given/When/Then for all 52 criteria is in [spec.md](spec.md).

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| Harness tools live on the same server, and the agent's `tools:` excludes them | Second server; control files | One process holds the store. The allowlist is the boundary, and a test pins it |
| Dump through an explicit `eval_dump` | Dump at shutdown; dump per call | The server outlives trials. Per-call dumps would race |
| Server `instructions` are neutral, and the prompt goes in the agent body | `build_server` with the prompt as instructions | Keeps the orchestrator session clean and avoids sending the prompt twice |
| Replies are recorded through the `eval_record_turn` MCP tool | The orchestrator writes files | The main-session guard hook allows only `specs/**` |
| YAML with PyYAML as a dev dependency | TOML, JSON | The issue names YAML |
| `dev-mode-dirs` makes `evals` importable | pytest `pythonpath` | Works for the server subprocess, pyright, and pytest |
| The fixture moves to `evals/reference_adopter.py` | A separate `reference/` package | One dev-only package serves both tests and evals |
| A scripted-driver end-to-end test runs in `make check` | No end-to-end test | Proves the driver contract deterministically |

## Files/modules to be touched

- New `evals/` modules: `scenario`, `graders`, `server`, `agent`,
  `report`, `__main__`, and `reference_adopter`, plus 17 scenario files.
- New `.claude/` files: `agents/wenchang-eval.md` (generated),
  `agents/wenchang-eval-judge.md`, and `commands/run-evals.md`. Also a new
  `.mcp.json`.
- Config: `pyproject.toml`, `uv.lock`, and `.gitignore`.
- 9 new `tests/test_evals_*.py` modules. `tests/prompts_reference_adopter.py`
  becomes a re-export, and is deleted after #34.
- Docs: ADR 0028, `ARCHITECTURE.md`, `README.md`, and the glossary.

## Open questions / assumptions

- **Live end-to-end runs are manual.** Agent files and `.mcp.json` load at
  session start and need one-time approval. `make check` proves the
  pipeline with a scripted driver instead. A human or orchestrator in a
  fresh session does the live run of the four required scenarios.
- **The prompt gets a 2-sentence framing preamble.** It says messages come
  from the user. Without it, a subagent treats its input as a parent's
  task. The prompt bytes are unchanged.
- **Merge order: PR #34 before this PR.** T1 copies the fixture into
  `evals/`. T10 deletes the `tests/` copies after rebasing onto `main`. If
  #34 is late, T10 is reported as pending.
- **Checked-in `.mcp.json`.** Every session in the repo is offered the
  `wenchang` eval server. It is harmless until approved.
- **Not ported.** Scenarios that need host features the harness lacks:
  on-demand tool loading, a curated refresh between sessions,
  `systems_of_record=None`, and a near-full file.
- **ADR number 0028.** It may collide with another in-flight issue. The
  next free number is used if so.

## Risks

- Claude Code's harness prompt sits under the eval agent, so results guide
  prompt iteration but cannot gate releases. This is the issue's stated
  limitation.
- Multi-turn sessions depend on `SendMessage` resuming a subagent. If a
  driver cannot do that, the multi-turn scenarios cannot run on it. Only the
  ask-first scenarios (`slots-ask-before-shared`, `curated-correction`) use
  a second turn.
- `on_call` misses schema-rejected calls, so graders see only calls that
  reached the wrapper.
