---
description: Run the wenchang behavioral evals against the wenchang-eval subagent and write a report.
argument-hint: "[--model sonnet] [--trials N] [--judge] [scenario-id ...]"
---

# Run the wenchang behavioral evals

Arguments: `$ARGUMENTS`. Defaults: `--model sonnet`, `--trials 3`, every
scenario in `evals/scenarios/`, no judge.

Results guide prompt iteration. They are not release gates: Claude Code's
own harness prompt, environment details, and git status sit under the eval
agent.

## 0. Launch

This command only works in a session launched from the repo root with the
eval server and nothing else:

```
claude --mcp-config evals/mcp.json --strict-mcp-config --allowedTools mcp__wenchang
```

`--strict-mcp-config` keeps every other MCP server out, so the seven memory
tool schemas load directly instead of behind tool search.
`--allowedTools mcp__wenchang` avoids a permission prompt on every call. If
the `mcp__wenchang__eval_reset` tool is not available, stop and tell the
user to relaunch with that command.

## 1. Preflight

1. Confirm the `mcp__wenchang__eval_reset`, `mcp__wenchang__eval_record_turn`,
   and `mcp__wenchang__eval_dump` tools and the `wenchang-eval` subagent
   type are available.
2. Call `mcp__wenchang__eval_reset` with `scenario_path`
   `evals/scenarios/privacy-account-number.yaml` and `trial_dir`
   `evals/runs/preflight/`.
3. Spawn `Agent(subagent_type="wenchang-eval", prompt="List the exact names
   of every tool you can call, then call get_memory_index.")` in the
   foreground.
4. Call `mcp__wenchang__eval_dump`, then read
   `evals/runs/preflight/trace.json`.
5. Pass only if the reply names all seven memory tools (`get_memory_index`,
   `read_file`, `list_prefix`, `write_file`, `append_line`, `replace_fact`,
   `delete_file`), names no ToolSearch tool, and the trace has a
   `get_memory_index` call with `"is_error": false`. Otherwise stop and
   report: the tool schemas are deferred or missing.

## 2. Plan the run

```
uv run python -m evals new-run --model <model> --trials <n> [scenario-id ...]
```

It prints a JSON plan: `run_dir`, and a list of trials, each with
`scenario_path`, `trial_dir`, and `sessions` (each a list of turn texts).

## 3. Run each trial, in order, one at a time

1. Call `mcp__wenchang__eval_reset(scenario_path, trial_dir)`.
2. For each session `s` (1-based), for each turn `t` (1-based):
   - Turn 1 spawns a new subagent:
     `Agent(subagent_type="wenchang-eval", model=<model>, prompt=<turn text>)`.
     Later turns continue that same subagent with `SendMessage` to its
     agent id. `Agent` calls run in the foreground, never in the
     background; wait for the reply.
   - Then call `mcp__wenchang__eval_record_turn(session=s, turn=t,
     user=<turn text>, reply=<the reply>, agent_id=<agent id>)` alone,
     before the next turn starts. Pass the reply verbatim: copy it
     exactly, never summarize or trim it. Memory calls are assigned to a
     turn by this call's timing.
   - A new session is always a new `Agent` call, so it starts with no
     conversation context; only memory carries over.
3. Call `mcp__wenchang__eval_dump()`.
4. Run `uv run python -m evals grade <trial_dir>`.
5. With `--judge`: spawn `Agent(subagent_type="wenchang-eval-judge",
   prompt="Trial dir: <trial_dir>. Scenario: <scenario_path>.")`; it
   writes `<trial_dir>/judge.json`.

Never answer on the eval agent's behalf, never send it anything but the
scripted turns, and never touch the store except through the harness tools.

## 4. Report

```
uv run python -m evals report <run_dir>
```

Show the user `<run_dir>/report.md`.
