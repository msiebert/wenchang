# 0035. Eval sessions run in dontAsk mode and record the subagent's full reply

Date: 2026-10-20

## Status

Accepted.

## Context

In auto mode, Claude Code gives every non-fork subagent a `SubagentHandback`
tool, even when its frontmatter `tools:` list omits it and past
`disallowedTools` (the tools-reference docs). Eval sessions inherited
`defaultMode: auto` from user settings. The eval agent therefore sometimes
ended a turn by handing back a third-person report about its turn, and the
runner recorded that report as the reply.

An audit found about 7% of recorded replies (68 of 1,428) were such summaries,
back to the 2026-10-14 baselines. Most "third-person reply" flags (ADR 0031)
and about 16 of the roughly 20 judge fails labelled third-person noise were
this artifact. Some ask-type and draft-content judge passes may be unverified,
because a summary can describe a question the agent never put to the user.
Deterministic store and trace assertions are unaffected.

A probe with `--permission-mode dontAsk` showed only the seven memory tools.
It also showed a second effect. Without `SubagentHandback`, the Agent result
is only the subagent's final text block, wrapped in a hand-back frame. In the
probe, "I'll check my memory first." before the `get_memory_index` call was
lost. In real trials an answer followed by `write_file` and "Saved." recorded
only "Saved.". Every clean-baseline shard failed its preflight this way.

## Decision

1. **Launch every eval session in `dontAsk` mode.**
   - Both launch commands add `--permission-mode dontAsk`, and
     `--allowedTools` adds `"Edit(evals/runs/**)"`.
   - `dontAsk` denies every call that would prompt. The judge writes
     `judge.json` with Write, and file writes are checked only against `Edit`
     rules, so the rule is needed. `acceptEdits` and a bare `Edit` were
     rejected: the first is not what was probed, the second is too wide.
   - The runner uses Bash only for the documented `uv run python -m evals`
     commands. A denied call stops the run. With `--judge`, the runner checks
     that `<trial_dir>/judge.json` exists and stops if it does not.

2. **Harden the preflight.** The prompt asks for `get_memory_index` first,
   then the exact tool names, with `WENCHANG-PREFLIGHT-END` as the last line.
   The runner records the turn and judges `transcript.json`'s recorded reply.
   Pass needs all of:
   - (a) all seven memory tools named, bare or `mcp__wenchang__`-prefixed;
   - (b) no other tool named, such as `SubagentHandback` or a ToolSearch tool;
   - (c) a `get_memory_index` call with `"is_error": false` in the trace;
   - (d) the last non-empty line of the reply is exactly the marker.
   An `eval_record_turn` error also fails. Check (b) is self-reported, which
   is why (d) exists: a handback summary rarely ends on the marker.

3. **Record the reply from the subagent transcript.** This reverses the
   rejection in ADR 0028 decision 7.
   - `eval_record_turn` keeps its signature. With a transcripts root (the live
     server always has one; `--transcripts-root`, default
     `$CLAUDE_CONFIG_DIR/projects` or `~/.claude/projects`), it requires
     `agent_id`. It normalizes the value to its first whitespace token, so the
     runner may paste the `agentId:` trailer, and requires `^[A-Za-z0-9_-]+$`.
   - It finds exactly one `<root>/*/*/subagents/agent-<agent_id>.jsonl`. The
     reply is every `type: "assistant"` entry's `text` blocks in file order,
     deduped by `uuid`, stripped, empties dropped, joined with a blank line.
     Entries with `isApiErrorMessage: true` or `message.model ==
     "<synthetic>"` are skipped, and `thinking` blocks are ignored.
   - Flush race: the reconstruction's last text block, whitespace-normalized,
     must be a substring of the normalized Agent result. If not, it re-reads
     for up to `transcript_retry_s` (default 2.0) and then fails.
   - The runner's `reply` argument is kept as `agent_result` in
     `transcript.json` for audit. The turn boundary timestamp is taken at the
     start of the call, before the read.
   - A missing or ambiguous file, a bad `agent_id`, malformed JSONL, no text,
     or a failed race check returns an error and records nothing. The error
     names the searched root and `--transcripts-root`. `evals/mcp.json` has
     no env block, because variable expansion there is unverified (ADR 0028),
     so a custom `CLAUDE_CONFIG_DIR` may not reach the server. That fails
     loudly at preflight, and `--transcripts-root` is the lever.
   - `eval_reset` writes an empty `transcript.json`, so a reused trial dir
     never keeps a stale transcript.
   - The read retries transient errors (file not yet visible, torn last
     line, no text yet, last block not yet in the Agent result) for up to 2
     seconds. An ambiguous or invalid agent id fails at once.
   - `--transcripts-root` is a server flag, so a non-default root means
     editing the args in `evals/mcp.json`.
   - Scripted drivers build `EvalState` without a transcripts root and record
     `reply` as passed.

   The alternative was a preamble telling the agent to put its whole reply in
   one final message after its last tool call. It changes the measured agent
   prompt, depends on model compliance, and fails silently when the model
   ignores it. An adopter's host shows every text block, so the transcript
   reconstruction is what a user would see. The agent file and preamble are
   unchanged.

## Consequences

- **Measured shift.** Recorded replies now include text written before a tool
  call. Reply-text checks, the third-person count, judge grades,
  `unmatched_reply_paths` (narration can name paths), and the turn-prompt
  replay change. Later turns replay the full recorded reply, which is what the
  user saw; this is deliberate. A clean N=6 baseline on main follows the merge
  and resets these baselines. Counts before it are not comparable.
- **Layout dependency.** The route reads Claude Code's internal transcript
  layout, verified against Claude Code 2.1.304. Any mismatch fails loudly, a
  fixture-based unit test pins the parser, and the preflight exercises the
  route live.
- **Accepted weakness.** Check (b) is self-reported. A mechanical check from
  the transcript's `api-request-shape` tool list is a possible follow-up.
- Runner sessions can no longer run ad hoc shell commands. That is intended:
  a denied call stops the run instead of prompting.
- ADR 0028 decisions 6 and 7 and its 2026-10-14 note, ADR 0031, and ADR 0032
  carry dated pointers to this record.
