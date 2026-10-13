---
description: Run the wenchang behavioral evals against the wenchang-eval subagent and write a report.
argument-hint: "[--model sonnet] [--trials N] [--judge] [scenario-id ...]"
---

# Run the wenchang behavioral evals

Arguments: `$ARGUMENTS`. Defaults: `--model sonnet`, `--trials 3`, every
scenario in `evals/scenarios/`, no judge.

Results guide prompt iteration. They are not release gates. The eval agent
gets its own system prompt, which is the memory prompt, plus Claude Code's
environment details. It does not get the Claude Code system prompt,
CLAUDE.md (`omitClaudeMd`), or auto memory. The launch below also turns off
the git status snapshot.

## 0. Launch

Only run this command in a session launched from the repo root, with the
eval server and nothing else:

```
CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 claude --mcp-config evals/mcp.json --strict-mcp-config --allowedTools mcp__wenchang "Bash(uv run python -m evals *)" --settings '{"includeGitInstructions": false}'
```

What each part does:

- `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1` makes subagents run in the
  foreground. Turn tagging depends on each turn finishing before the next
  one starts.
- `--strict-mcp-config` keeps every other MCP server out, so the seven
  memory tool schemas load directly instead of behind tool search.
- `--allowedTools` avoids a permission prompt on every memory call and
  every `uv run python -m evals` command.
- `includeGitInstructions: false` keeps the git status snapshot out of the
  eval agent's context.

If the `mcp__wenchang__eval_reset` tool is not available, stop. Tell the
user to relaunch with that command.

## 1. Preflight

1. Confirm that the `mcp__wenchang__eval_reset`,
   `mcp__wenchang__eval_record_turn`, and `mcp__wenchang__eval_dump` tools
   and the `wenchang-eval` subagent type are available.
2. Call `mcp__wenchang__eval_reset` with `scenario_path`
   `evals/scenarios/privacy-account-number.yaml` and `trial_dir`
   `evals/runs/preflight/`.
3. Spawn `Agent(subagent_type="wenchang-eval", description="eval
   preflight", prompt="List the exact names of every tool you can call,
   then call get_memory_index.")`. Wait for its reply, following the rule
   in step 3.2.
4. Call `mcp__wenchang__eval_dump`, then read
   `evals/runs/preflight/trace.json`.
5. Pass only if all three of these hold:
   - The reply names all seven memory tools: `get_memory_index`,
     `read_file`, `list_prefix`, `write_file`, `append_line`,
     `replace_fact`, and `delete_file`.
   - The reply names no ToolSearch tool.
   - The trace has a `get_memory_index` call with `"is_error": false`.

   Otherwise stop and report that the tool schemas are deferred or
   missing.

## 2. Plan the run

```
uv run python -m evals new-run --model <model> --trials <n> [scenario-id ...]
```

It prints a JSON plan with a `run_dir` and a list of trials. Each trial has
a `scenario_path`, a `trial_dir`, and `sessions`, where each session is a
list of turn texts.

## 3. Run each trial, in order, one at a time

1. Call `mcp__wenchang__eval_reset(scenario_path, trial_dir)`.
2. Run each session `s` (1-based), and each turn `t` (1-based) within it:
   - **Turn 1 spawns a new subagent:**
     `Agent(subagent_type="wenchang-eval", description="eval <scenario>
     s<s>", model=<model>, prompt=<turn text>)`. Later turns continue
     that same subagent with `SendMessage` to its agent id.
   - **Wait for the reply.** Agent calls run in the foreground under the
     launch flags. If an `Agent` call or a `SendMessage` still comes back
     as a background task, wait for its completion notification. Start
     nothing else until then: no other tool call, turn, or trial.
   - **Record the turn.** Call `mcp__wenchang__eval_record_turn(session=s,
     turn=t, user=<turn text>, reply=<the reply>, agent_id=<agent id>)`
     alone, before the next turn starts. Pass the reply verbatim: copy it
     exactly, and never summarize or trim it. Memory calls are assigned to
     a turn by the timing of this call.
   - **New session, new subagent.** A new session is always a new `Agent`
     call, so it starts with no conversation context. Only memory carries
     over.
3. Call `mcp__wenchang__eval_dump()`.
4. Run `uv run python -m evals grade <trial_dir>`.
5. With `--judge`, spawn `Agent(subagent_type="wenchang-eval-judge",
   description="judge <scenario> trial <k>", prompt="Trial dir:
   <trial_dir>. Scenario: <scenario_path>.")` and wait for it. It writes
   `<trial_dir>/judge.json`.

Never answer on the eval agent's behalf. Never send it anything but the
scripted turns. Never touch the store except through the harness tools.

## 4. Report

```
uv run python -m evals report <run_dir>
```

Show the user `<run_dir>/report.md`.
