Linear: AIE-1384

Allow-test-changes: update (not weaken or remove) tests/test_evals_report.py::test_new_run_writes_metadata_and_plan — its expected run.json dict gains the default arm {"index_tool": "get_memory_index", "agent_prompt": true} required by AC9. No test is deleted or skipped.

# Feature Specification: Eval arms to compare names for the memory index tool

**Linear issue**: AIE-1384 — Test alternative names for get_memory_index to raise call-first compliance

**Feature Branch**: `AIE-1384-memory-tool-name-eval`

**Created**: 2026-11-13

**Status**: Draft

**Input**: Since AIE-1382, the `get_memory_index` MCP result carries the
memory rules (scopes, confidence labels, never-store) along with the index.
Clients that drop MCP `instructions` (Claude Desktop, claude.ai) only see the
rules if the model calls that tool first. The name may undersell it. The issue
asks to compare candidate names against the baseline on a setup with neutral
instructions. Measure how often the model calls the tool first and how often it
follows the label rules. Rename only if a name clearly beats the baseline.
Candidates: `get_memory_index` (baseline), `load_memory`,
`get_memory_rules_and_index`, `start_memory_session`, `get_memory_entrypoint`.

Today the eval server already uses neutral instructions
(`EVAL_SERVER_INSTRUCTIONS = "Memory tools for this workspace."`). But
`render_agent_body()` puts the full memory prompt into the subject agent's
system prompt, so the subject is already told to call `get_memory_index`. That
does not model a client that drops instructions. The agent file and the MCP
server are loaded at Claude Code session start, so each arm needs a fresh
session.

## Summary

- Add eval "arms": an index tool name plus an on/off switch for the memory
  prompt in the agent body. An arm lives in a gitignored `evals/arm.json`,
  written by a new `set-arm` command and read by the eval server and the agent
  renderer.
- The eval server renames the index tool by string substitution of
  `get_memory_index` in tool descriptions and in the result's prompt block. The
  trace keeps the canonical name, so scenarios and graders need no changes.
- `new-run` records the arm in `run.json`. `report.md` shows it. `merge-runs`
  refuses runs with different arms.
- A new `compare` command turns run directories into one markdown table:
  call-first rate, label rate, pass rates, deltas against a baseline.
- `.claude/commands/run-evals.md` documents the arm procedure and uses the
  arm's index tool in the preflight.
- Pre-registered experiment (run live, by a human): five arms, one panel, one
  decision rule. The decision goes in an ADR.

Out of scope: any change to `src/` or the public API, and the rename itself.
If a name wins, the rename is a follow-up issue (see Open questions in
`review-spec.md`).

## Phases

1. **Code (this PR)**: arms infrastructure. All under `evals/`, plus
   `.claude/agents/wenchang-eval.md`, `.claude/commands/run-evals.md`,
   `.gitignore`, and `tests/`.
2. **Live runs (human)**: run the five arms in separately launched sessions,
   commit `eval-report.md`, record the decision in an ADR.
3. **Rename (conditional)**: only if a name wins by the rule. Needs an ADR, a
   CHANGELOG breaking-change entry, and every mention updated. Proposed as a
   follow-up issue, not this PR.

## User scenarios

1. **Maintainer running the experiment.** Runs `set-arm`, relaunches the
   session, runs the panel, resets the arm, and repeats for each name. Then
   runs `compare` and reads one table.
2. **Maintainer doing a normal eval run.** No `evals/arm.json`. Nothing
   changes.
3. **Reviewer of a later rename.** Reads `eval-report.md` and the ADR to see
   the numbers and the rule that was applied.

## Acceptance criteria

Tests are unit tests unless noted and cite `AIE-1384`.

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | No `evals/arm.json` | The eval server is built, the agent file is rendered, or `new-run` runs | Behavior is identical to today: index tool is `get_memory_index`; agent body is preamble plus memory prompt; the committed `.claude/agents/wenchang-eval.md` is unchanged; `run.json` records the default arm |
| 2 | `python -m evals set-arm --index-tool load_memory --no-agent-prompt` | It runs | `evals/arm.json` is `{"index_tool": "load_memory", "agent_prompt": false}`; `.claude/agents/wenchang-eval.md` is regenerated: the tools line has `mcp__wenchang__load_memory` in place of `mcp__wenchang__get_memory_index` (same position), and the body is `EVAL_AGENT_PREAMBLE` only (it names no memory tool) |
| 3 | An arm with `agent_prompt` true and index tool X | The agent is rendered | The body is preamble plus memory prompt with every `get_memory_index` replaced by X |
| 4 | An invalid name (not matching `^[a-z][a-z0-9_]{0,63}$`, or equal to another memory tool name or a harness tool name) | `set-arm` runs | It exits 2 with a message naming the problem and writes nothing |
| 4b | An `arm.json` that is malformed or invalid | `load_arm` reads it | `ArmError` is raised, so the server fails at startup instead of silently using the default |
| 5 | Arm index tool X | The eval server lists tools | X is listed and `get_memory_index` is not; the other six memory tools and the three harness tools keep their names; each memory tool description equals the default-arm description with every `get_memory_index` replaced by X, and nothing else differs |
| 6 | Arm X | X is called successfully | `content` has the JSON payload, then the memory prompt with every `get_memory_index` replaced by X; `structured_content` equals the default arm's |
| 7 | Arm X | X is called | The trace record names the tool `get_memory_index` (canonical), so `index_read_first` and tool-call assertions grade with no scenario changes |
| 8 | Any arm | The server is built | Its instructions equal `EVAL_SERVER_INSTRUCTIONS` |
| 9 | An arm | `new-run` runs | `run.json` has `"arm": {"index_tool": ..., "agent_prompt": ...}`; `report.md`'s header shows both; `merge-runs` exits 2 when its runs have different arms; a `run.json` without `"arm"` (older runs) is read as the default arm |
| 10 | Run directories | `python -m evals compare OUT_FILE RUN_DIR... [--baseline RUN_DIR]` runs | `OUT_FILE` is markdown with one row per run: index tool, agent prompt on/off, model, trials, sessions, call-first rate (% and k/n), sessions with no memory call, `index_read_first` pass rate, label rate, overall deterministic assertion pass rate, and judge pass rate when judged. Rows other than the baseline (default: first `RUN_DIR`) show deltas in percentage points. It exits 2 if the runs cover different scenario sets |
| 11 | `.claude/commands/run-evals.md` | A runner follows it | The preflight calls the index tool named by the run's arm; the file documents the arm procedure: `set-arm`, relaunch the session, `new-run` with the panel ids, and `set-arm --reset` afterwards |
| 12 | The five arms run live (human) with the pre-registered panel and rule | Results are in | `specs/AIE-1384-memory-tool-name-eval/eval-report.md` holds the `compare` output, and an ADR in `docs/adr/` records the decision (keep or rename) against the rule |
| 13 | The change | `make check` | Passes |

Metric definitions for AC10:

- **Memory tools**: the seven `TOOL_NAMES`, by canonical name in the trace.
- **Call-first rate**: sessions whose first memory-tool call is the index tool,
  over all sessions.
- **Sessions with no memory call**: sessions with no memory-tool call at all.
- **Label rate**: added fact lines carrying `[stated]`, `[observed]`, or
  `[inferred]`, over added fact lines.
- **Added fact line**: a line in the trial's final `store.json` that is not in
  the scenario's seed files, starts with `- ` after leading whitespace, and
  does not contain `[system]`.

## Functional requirements

- **FR-001**: Arm names MUST be validated in one place (`evals/arm.py`), used by
  `set-arm`, `load_arm`, and `Arm.__post_init__`.
- **FR-002**: With no `evals/arm.json`, every output MUST be byte-identical to
  today's.
- **FR-003**: Only the name of the index tool varies between arms. Descriptions
  and the prompt block differ from the default only by the substituted name.
- **FR-004**: `set-arm` MUST write nothing when it exits 2.
- **FR-005**: `new-run` MUST print a warning when the arm is not the default.
- **FR-006**: No change to `src/`, the public API, or any scenario file.

## Experiment design (pre-registered)

- All five arms: `agent_prompt` false (models a client that drops
  instructions), Sonnet 5.5 (`--model sonnet`), 3 trials.
- Panel (10 existing scenarios): `remembering-stated-name`,
  `remembering-observed-once`, `remembering-stated-role`,
  `remembering-fact-about-user`, `remembering-preference-mid-task`,
  `recall-across-sessions`, `filing-new-acronym`, `privacy-account-number`,
  `forgetting-one-fact`, `curated-correction`.
- Optional reference run: default arm with `agent_prompt` true (the AIE-1382
  follow-up).
- **Decision rule**: rename only if a candidate's call-first rate is at least 15
  points above the baseline AND its label rate and overall pass rate are each no
  more than 5 points below the baseline. If several qualify, the highest
  call-first rate wins. Otherwise keep `get_memory_index`.

## Assumptions

- Claude Code loads the MCP server and the agent file at session start, so
  each arm needs a fresh session. The orchestrator cannot run live evals.
- `evals/arm.json` is local state (gitignored). Only `set-arm` writes it.
- The eval server may rename the registered tool through the `MCPServer`
  private managers, as `register_memory_tools` already does under the `mcp<3`
  pin.
- Substitution also renames mentions in prose. Accepted, since only the name
  should vary.
- 30 trials per arm cannot detect small effects. The rule acts only on large
  ones.
