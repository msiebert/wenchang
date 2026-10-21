---
description: Run the wenchang behavioral evals against the wenchang-eval subagent and write a report.
argument-hint: "[--model sonnet] [--trials N] [--judge] [--shard k/n] [scenario-id ...]"
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
CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 claude --permission-mode dontAsk --mcp-config evals/mcp.json --strict-mcp-config --allowedTools mcp__wenchang "Bash(uv run python -m evals *)" "Edit(evals/runs/**)" --settings '{"includeGitInstructions": false}'
```

What each part does:

- `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1` makes subagents run in the
  foreground. Turn tagging depends on each turn finishing before the next
  one starts.
- `--permission-mode dontAsk` runs the session outside auto mode, which
  would give every subagent a `SubagentHandback` tool and let the eval
  agent return a report about its turn instead of its reply. It also denies,
  without prompting, any call not allowed here.
- `--strict-mcp-config` keeps every other MCP server out, so the seven
  memory tool schemas load directly instead of behind tool search.
- `--allowedTools` avoids a permission prompt on every memory call and
  every `uv run python -m evals` command.
- `"Edit(evals/runs/**)"` lets the judge write `judge.json` (Edit rules
  cover Write).
- `includeGitInstructions: false` keeps the git status snapshot out of the
  eval agent's context. `--allowedTools` stays followed by `--settings`,
  because it takes any number of values.

Use Bash only for the `uv run python -m evals ...` commands shown here, with
no pipes, redirects, or `cd`. If any tool call is denied, stop and tell the
user to relaunch with the step 0 command.

If the `mcp__wenchang__eval_reset` tool is not available, stop. Tell the
user to relaunch with that command.

## 1. Preflight

1. Confirm that the `mcp__wenchang__eval_reset`,
   `mcp__wenchang__eval_record_turn`, and `mcp__wenchang__eval_dump` tools
   and the `wenchang-eval` subagent type are available.
2. Call `mcp__wenchang__eval_reset` with `scenario_path`
   `evals/scenarios/privacy-account-number.yaml` and `trial_dir`
   `evals/runs/preflight/`. With `--shard k/n`, use
   `evals/runs/preflight-<k>of<n>/` instead, so concurrent shards never
   share a preflight dir.
3. Spawn `Agent(subagent_type="wenchang-eval", description="eval preflight", prompt="Call get_memory_index first. After it returns, reply with the exact names of every tool you can call, and finish your reply with this line on its own, as the last line: WENCHANG-PREFLIGHT-END")`.
4. Call `mcp__wenchang__eval_record_turn(session=1, turn=1, user=<that prompt>, reply=<the Agent result>, agent_id=<its agentId>)`, as in step 3.2.
5. Call `mcp__wenchang__eval_dump`, then read `trace.json` and
   `transcript.json` in that preflight dir.
6. Pass only if all of these hold, judged on the reply recorded in
   `transcript.json`:
   - (a) The reply names all seven memory tools: `get_memory_index`,
     `read_file`, `list_prefix`, `write_file`, `append_line`,
     `replace_fact`, and `delete_file`, bare or `mcp__wenchang__`-prefixed.
   - (b) The reply names no other tool, for example `SubagentHandback` or
     any ToolSearch tool.
   - (c) The trace has a `get_memory_index` call with `"is_error": false`.
   - (d) The reply's last non-empty line is exactly
     `WENCHANG-PREFLIGHT-END`.

   An `eval_record_turn` error also fails the preflight. Otherwise stop,
   report which check failed, and tell the user to relaunch with the step 0
   command.

## 2. Plan the run

```
uv run python -m evals new-run --model <model> --trials <n> [--shard k/n] [scenario-id ...]
```

Pass `--shard k/n` through when the arguments include it.

It prints a JSON plan with a `run_dir` and a list of trials. Each trial has
a `scenario_path`, a `trial_dir`, and `sessions`, where each session is a
list of turn texts.

## 3. Run each trial, in order, one at a time

Never stop, pause, skip, or reorder trials because of their results. A
failing trial is data, and the report is where it shows up. Stop only if
the preflight fails, or if `eval_reset`, `eval_record_turn`, or `eval_dump`
returns an error. Never edit any file outside `evals/runs/`.

1. Call `mcp__wenchang__eval_reset(scenario_path, trial_dir)`.
2. Run each session `s` (1-based), and each turn `t` (1-based) within it:
   - **Build the prompt.** Run `uv run python -m evals turn-prompt
     <trial_dir> <s> <t>` and use its output exactly as the prompt. For
     turn 1 it is the scripted text, after any context blocks. For a later turn it replays the
     session's earlier exchanges, then the new turn. The `turn-prompt`
     output, including any `[From the product's ...]` context blocks, is
     passed unchanged as the whole `Agent` prompt.
   - **Every turn is a new subagent.** Call
     `Agent(subagent_type="wenchang-eval", description="eval <scenario>
     s<s> t<t>", model=<model>, prompt=<that output>)`. Do not continue an
     earlier subagent.
   - **Always pass the model.**
     Every `Agent` call, including every later turn, passes `model=<model>`.
     The agent definition says `model: inherit`, so a call without it runs
     on the runner's own model.
     A turn run on the wrong model invalidates the trial: call
     `eval_reset` again and rerun the trial from session 1, turn 1.
   - **Wait for the reply.** Agent calls run in the foreground under the
     launch flags. If an `Agent` call still comes back as a
     background task, wait for its completion notification. Start nothing
     else until then: no other tool call, turn, or trial.
   - **Record the turn.** Call `mcp__wenchang__eval_record_turn(session=s,
     turn=t, user=<the scripted turn text>, reply=<the Agent result text>,
     agent_id=<the token after agentId: in the Agent result, nothing else>)`
     alone, before the next turn starts. Pass the Agent result verbatim:
     never summarize or trim it. `agent_id` is required. The server replaces
     the reply with the subagent's full text from the subagent's transcript,
     so text written before a tool call is kept, and keeps the passed text
     as `agent_result`.
     The `user` argument is the scenario's turn text alone, never the
     rendered prompt with its context blocks or replayed turns.
     Memory calls are assigned to a turn by the timing of this call.
     The call also updates `transcript.json`, which the next turn's prompt
     is built from.
   - **Sessions start fresh.** Turn 1 of a new session carries no earlier
     exchanges. Only memory carries over between sessions.
3. Call `mcp__wenchang__eval_dump()`.
4. Run `uv run python -m evals grade <trial_dir>`.
5. With `--judge`, spawn `Agent(subagent_type="wenchang-eval-judge",
   description="judge <scenario> trial <k>", prompt="Trial dir:
   <trial_dir>. Scenario: <scenario_path>.")` and wait for it. It writes
   `<trial_dir>/judge.json`. After it returns, check that the file exists.
   If it is missing, stop and report that the judge could not write it.

Never answer on the eval agent's behalf. Never send it anything but the
prompts `turn-prompt` prints. Never touch the store except through the
harness tools.

## 4. Report

```
uv run python -m evals report <run_dir>
```

Show the user `<run_dir>/report.md`.

The report also counts trials whose reply referred to the user in the
third person ("the user said"). These counts are a separate signal and
never change a pass count. A judge fail in such a trial is co-occurrence,
not proof the addressee caused it. Counts from runs before 2026-10-20
include auto-mode handback summaries (ADR 0035).

## Parallel shards

Trials inside one session stay serial. One eval server holds one store,
and memory calls are assigned to turns by the timing of
`eval_record_turn`, so two trials in one session would mix their stores and
traces. To run trials in parallel, launch several sessions. Each one starts
its own eval server and runs one shard.

1. Launch one headless session per shard, from the repo root, with
   `--shard k/n` passed through to `new-run`. For example, for 3 shards:

   ```
   CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 claude -p "/run-evals --model sonnet --trials 3 --judge --shard 1/3" --permission-mode dontAsk --mcp-config evals/mcp.json --strict-mcp-config --allowedTools mcp__wenchang "Bash(uv run python -m evals *)" "Edit(evals/runs/**)" --settings '{"includeGitInstructions": false}'
   ```

   Repeat with `--shard 2/3` and `--shard 3/3`. Shard k takes the
   scenarios, sorted by id, whose index % n is k - 1. Its run dir ends in
   `-shard<k>of<n>`, so shards started in the same second do not collide.
2. When every shard has finished, merge them into one report:

   ```
   uv run python -m evals merge-runs evals/runs/<name> <shard run dir> ...
   ```

   This checks that every shard has the same model, trial count, git
   commit, and agent sha256. It copies each scenario's trials, writes a
   combined `run.json` listing the sources, and writes `report.md` and
   `report.json` covering every scenario.
