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
   `evals/runs/preflight/`. With `--shard k/n`, use
   `evals/runs/preflight-<k>of<n>/` instead, so concurrent shards never
   share a preflight dir.
3. Spawn `Agent(subagent_type="wenchang-eval", description="eval
   preflight", prompt="List the exact names of every tool you can call,
   then call get_memory_index.")`. Wait for its reply, following the rule
   in step 3.2.
4. Call `mcp__wenchang__eval_dump`, then read `trace.json` in that
   preflight dir.
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
     turn 1 it is the scripted text. For a later turn it replays the
     session's earlier exchanges, then the new turn.
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
     turn=t, user=<the scripted turn text>, reply=<the reply>,
     agent_id=<this subagent's id>)` alone, before the next turn starts.
     Pass the reply verbatim: copy it exactly, and never summarize or trim
     it. Memory calls are assigned to a turn by the timing of this call.
     The call also updates `transcript.json`, which the next turn's prompt
     is built from.
   - **Sessions start fresh.** Turn 1 of a new session carries no earlier
     exchanges. Only memory carries over between sessions.
3. Call `mcp__wenchang__eval_dump()`.
4. Run `uv run python -m evals grade <trial_dir>`.
5. With `--judge`, spawn `Agent(subagent_type="wenchang-eval-judge",
   description="judge <scenario> trial <k>", prompt="Trial dir:
   <trial_dir>. Scenario: <scenario_path>.")` and wait for it. It writes
   `<trial_dir>/judge.json`.

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
not proof the addressee caused it.

## Parallel shards

Trials inside one session stay serial. One eval server holds one store,
and memory calls are assigned to turns by the timing of
`eval_record_turn`, so two trials in one session would mix their stores and
traces. To run trials in parallel, launch several sessions. Each one starts
its own eval server and runs one shard.

1. Launch one headless session per shard, from the repo root, with
   `--shard k/n` passed through to `new-run`. For example, for 3 shards:

   ```
   CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 claude -p "/run-evals --model sonnet --trials 3 --judge --shard 1/3" --mcp-config evals/mcp.json --strict-mcp-config --allowedTools mcp__wenchang "Bash(uv run python -m evals *)" --settings '{"includeGitInstructions": false}'
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
