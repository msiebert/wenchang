# Feature Specification: Run eval sessions outside auto mode; record the subagent's full reply

**Linear issue**: AIE-1208
**Branch**: `AIE-1208-eval-permission-mode`
**Created**: 2026-10-20
**Status**: Draft

## Problem

In auto mode, Claude Code gives every non-fork subagent a `SubagentHandback`
tool even when its frontmatter `tools:` list omits it
(https://code.claude.com/docs/en/tools-reference). Eval sessions inherit
`defaultMode: auto` from user settings, so `wenchang-eval` sometimes returned
a third-person report about its turn instead of its reply, and the runner
recorded that verbatim. An audit found about 7% of recorded replies (68 of
1,428) were such summaries, back to the 2026-10-14 baselines. Store and trace
assertions are unaffected; judge grades, the ADR 0031 third-person count, and
reply-text checks are affected (about 16 of the roughly 20 judge fails
labelled "third-person noise" were summaries).

A probe with `--permission-mode dontAsk` showed only the 7 memory tools. Live
`dontAsk` runs then showed a second effect: without `SubagentHandback`, the
Agent tool returns only the subagent's final assistant text block. Text
before its last tool call is lost (an answer, then `write_file`, then
"Saved." records only "Saved."), and every clean-baseline shard failed
preflight that way. The parent also wraps the result in a "[Subagent
hand-back]" frame with indented lines and trailing `agentId:` and `<usage>`
lines.

## Decisions

- **D1.** Add `--permission-mode dontAsk` to every eval launch command:
  right after `claude` in the interactive command, right after the
  `-p "<prompt>"` argument in the sharded command. `--mcp-config` and
  `--allowedTools` are variadic, each ended by the next `--flag`, so
  `--allowedTools ...` must stay followed by `--settings`. Each command stays
  on one line in every doc.
- **D2.** Add `"Edit(evals/runs/**)"` to `--allowedTools`. `dontAsk` denies
  every call that would prompt (https://code.claude.com/docs/en/permission-modes),
  and the judge writes `<trial_dir>/judge.json` with Write. File writes are
  checked only against `Edit(path)` rules (https://code.claude.com/docs/en/permissions);
  the relative path resolves against the cwd, the repo root. Rejected:
  `acceptEdits` (not what was probed); broad `Edit` (too wide).
- **D3.** Preflight in `.claude/commands/run-evals.md`. The prompt is exactly:
  `Call get_memory_index first. After it returns, reply with the exact names of
  every tool you can call, and finish your reply with this line on its own, as
  the last line: WENCHANG-PREFLIGHT-END`. Steps: `eval_reset` (as now), Agent,
  `eval_record_turn(session=1, turn=1, user=<the prompt>, reply=<the Agent
  result>, agent_id=<its agentId>)`, `eval_dump`, read `trace.json` and
  `transcript.json` in the preflight dir. Pass only if all hold, judged on
  `transcript.json`'s recorded reply: (a) it names all seven memory tools (bare
  or `mcp__wenchang__`-prefixed); (b) it names no other tool, for example
  `SubagentHandback` or any ToolSearch tool; (c) the trace has
  `get_memory_index` with `"is_error": false`; (d) its last non-empty line is
  exactly `WENCHANG-PREFLIGHT-END`. An `eval_record_turn` error also fails.
  On failure: stop, report the failed check, and tell the user to relaunch with
  the step 0 command. Check (b) is self-reported, which is why (d) exists.
- **D4.** ADR `docs/adr/0035-eval-sessions-dontask.md` (0034 is reserved by open
  PR #41). It covers D1-D6, the SubagentHandback injection (even past
  `disallowedTools`), the 68 of 1,428 audit, that most third-person flags and
  "third-person noise" judge fails were this artifact, that store/trace
  assertions are unaffected, the self-reported tool list, and the decision 7
  reversal. Dated (2026-10-20) pointers: ADR 0028 decision 6 (command and bullet
  list), decision 7, and the "Note (2026-10-14, N=3 runs)" bullet; ADR 0031
  (`0031-reply-addressee-check.md`) "Amendment (2026-10-20, AIE-1208)"; ADR
  0032 (`0032-transcript-graded-assertions-and-context-records.md`, near
  "third-person reply is harness noise"); ARCHITECTURE.md eval reply-check
  section (about lines 1200-1216) one-line ADR 0035 link.
- **D5.** Runner rules under `dontAsk`: Bash only for the documented
  `uv run python -m evals ...` commands (no pipes, redirects, `cd`). If any
  tool call is denied, stop and tell the user to relaunch with the step 0
  command. With `--judge`, after the judge returns, check that
  `<trial_dir>/judge.json` exists; if it is missing, stop and report that the
  judge could not write it (the `Edit(evals/runs/**)` rule). The orchestrator's
  post-merge baseline confirms this live.
- **D6.** Record the reply from the subagent transcript. `eval_record_turn`
  keeps its signature. When the server has a transcripts root (the live server
  always does), it requires `agent_id`, finds
  `<projects_root>/*/*/subagents/agent-<agent_id>.jsonl` (projects_root is
  `$CLAUDE_CONFIG_DIR/projects` if set, else `~/.claude/projects`), and records
  as `reply` every `type: "assistant"` entry's `text` blocks in file order
  (deduped by entry `uuid`), each stripped, empties dropped, joined with a blank
  line. The runner's `reply` argument is kept as `agent_result` for audit. A
  missing or ambiguous file, an `agent_id` not matching `^[A-Za-z0-9_-]+$`,
  malformed JSONL, or no text returns an error and records nothing; the runner
  already stops on an `eval_record_turn` error. Runner step 3.2 passes
  `reply=<the Agent result text>` and `agent_id=<the agentId the result
  reports>`, and says the server replaces the reply with the subagent's full
  text; `agent_id` is required.
  - Refinements: entries with `isApiErrorMessage: true` or `message.model ==
    "<synthetic>"` are skipped; `thinking` blocks are ignored (text only).
    `agent_id` is normalized to the first whitespace token of the stripped
    value, so the runner may paste the `agentId:` trailer (the runner doc still
    says pass the bare token). Flush-race check: the reconstruction's last text
    block (whitespace-normalized) must be a substring of the normalized passed
    Agent result; if not, `record_turn` re-reads for up to `transcript_retry_s`
    (`EvalState` arg, default 2.0), then raises `SubagentTranscriptError` and
    records nothing. The not-found error names the searched root and
    `--transcripts-root`. `evals/mcp.json` stays unchanged (no env block;
    expansion there is unverified per ADR 0028), so a custom `CLAUDE_CONFIG_DIR`
    may not reach the server; it fails loudly at preflight and
    `--transcripts-root` is the lever. The boundary timestamp is taken at the
    start of `record_turn`, before the transcript read.
  - Rejected, preamble route (tell the agent to put its whole reply in one
    final message): it changes the measured agent prompt, depends on model
    compliance, and fails silently. An adopter's host shows every text block, so
    the transcript reconstruction is what a user would see.
  - Cost: it reads Claude Code's internal transcript layout, which ADR 0028
    decision 7 rejected; mitigated by failing loudly on any mismatch, a
    fixture-based unit test, and the preflight exercising it live.
  - Recorded replies now include pre-tool-call text, so reply-text checks, the
    third-person count, judge grades, `unmatched_reply_paths` (pre-tool
    narration can name paths), and the turn-prompt replay shift. Later turns
    replay the full recorded reply (what the user saw), a deliberate choice. The
    clean baseline after merge resets them. Accepted weakness: preflight check
    (b) is self-reported; a mechanical check from the transcript's
    `api-request-shape` tool list is a possible follow-up. Layout verified
    against Claude Code 2.1.304. The agent file and preamble are unchanged. Scripted drivers
    build `EvalState` without a transcripts root and record `reply` as passed.

## Launch commands (pinned)

Interactive:

```
CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 claude --permission-mode dontAsk --mcp-config evals/mcp.json --strict-mcp-config --allowedTools mcp__wenchang "Bash(uv run python -m evals *)" "Edit(evals/runs/**)" --settings '{"includeGitInstructions": false}'
```

Sharded (shard 1 of 3 shown):

```
CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 claude -p "/run-evals --model sonnet --trials 3 --judge --shard 1/3" --permission-mode dontAsk --mcp-config evals/mcp.json --strict-mcp-config --allowedTools mcp__wenchang "Bash(uv run python -m evals *)" "Edit(evals/runs/**)" --settings '{"includeGitInstructions": false}'
```

## Acceptance criteria

Tests are in `tests/test_evals_agent.py` (runner doc) and the evals test files
unless noted. "Normalized" means `" ".join(text.split())`.

- **AC1.** `run-evals.md` contains the interactive command exactly.
- **AC2.** `run-evals.md` contains the sharded command exactly.
- **AC3.** In AGENTS.md, README.md, `run-evals.md`, and ADR 0028, per line, for
  lines containing `claude ` and `--mcp-config evals/mcp.json`: each file has
  at least one, and each contains `--permission-mode dontAsk` and
  `"Edit(evals/runs/**)"`. ADR 0035 is not scanned.
- **AC4.** Normalized `run-evals.md` contains the exact D3 prompt.
- **AC5.** Normalized `run-evals.md` contains `all seven memory tools`,
  `SubagentHandback`, `"is_error": false`, `WENCHANG-PREFLIGHT-END`, and
  `last non-empty line`.
- **AC6.** Normalized `run-evals.md` contains `relaunch with the step 0
  command`.
- **AC7.** Between the "What each part does" heading and "## 1. Preflight",
  `run-evals.md` contains `--permission-mode dontAsk`, `SubagentHandback`,
  `Edit(evals/runs/**)`, and `judge.json`.
- **AC8.** (Doc, reviewer-checked; no unit test by design.) ADR 0035 exists
  with the D4 content; ADR 0028 (decisions 6 and 7, the note), 0031, 0032
  carry dated pointers; ARCHITECTURE.md links 0035.
- **AC9.** (No unit test by design.) `make -C
  /Users/marksiebert/p/github/wenchang-AIE-1208 check` passes.
- **AC10.** Normalized `run-evals.md` contains `If it is missing, stop` and
  `If any tool call is denied, stop`.
- **AC11.** `reply_from_transcript` on a fixture with text, `tool_use`, text
  entries plus non-assistant entries returns both texts joined by `"\n\n"`; a
  duplicate `uuid` counts once.
- **AC12.** `find_subagent_transcript`: no match raises, two matches raise, a
  bad `agent_id` (for example `../x`) raises, one match returns the path.
- **AC13.** `default_projects_root` honours a non-empty `CLAUDE_CONFIG_DIR`.
- **AC14.** `EvalState` with `transcripts_root` records the transcript reply
  and `agent_result`; `transcript.json` has both. A missing `agent_id` or file
  raises and records nothing (no boundary, no turn); the MCP tool returns an
  error result.
- **AC14b.** With a transcripts root: entries with `isApiErrorMessage: true` or
  model `<synthetic>` and `thinking` blocks are excluded; `agent_id` with a
  trailing `agentId:`-style suffix normalizes to its first token; a last block
  not found in the Agent result raises after `transcript_retry_s` (a test passes
  a small value) and records nothing; a late-flushed transcript succeeds on
  retry; the not-found error names the root and `--transcripts-root`.
- **AC15.** `EvalState` without `transcripts_root` is unchanged;
  `agent_result` is absent from `transcript.json`.
- **AC16.** `load_transcript` round-trips `agent_result`; a non-str non-null
  value raises in the existing error style.
- **AC17.** Normalized `run-evals.md` contains the D3 prompt with
  `get_memory_index first` before `WENCHANG-PREFLIGHT-END`; the preflight
  records the turn and reads `transcript.json`; step 3.2 says `agent_id` is
  required and the server reads the full reply from the subagent transcript.

## Out of scope

- Running live evals (the orchestrator runs the live probe and clean baseline).
- Historical `specs/*/review-pr.md` and other spec files.
- Grader assertion changes; the guard hook; the agent file and preamble.
