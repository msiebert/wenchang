# PR Review: AIE-1208 — Run eval sessions in dontAsk mode and record the subagent's full reply

> No live eval run in this PR. A clean N=6 baseline on main follows the merge (orchestrator).

## What changed & why

**Finding 1.** In auto mode every non-fork subagent gets a `SubagentHandback`
tool, even when its `tools:` list omits it. About 7% of recorded replies
(68 of 1,428, back to the 2026-10-14 baselines) were third-person summaries.
Judge grades, the third-person count, and reply-text checks were affected;
store and trace assertions were not. Fix: launch with `--permission-mode
dontAsk`, plus `"Edit(evals/runs/**)"` so the judge can still write
`judge.json`.

**Finding 2.** Under `dontAsk` the Agent result is only the subagent's final
text block, in a hand-back frame, so text before its last tool call was lost.
Fix: `eval_record_turn` reads the reply from the subagent's Claude Code
transcript by `agent_id`; the runner's `reply` is kept as `agent_result`.

Final launch commands (from `.claude/commands/run-evals.md`):

```
CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 claude --permission-mode dontAsk --mcp-config evals/mcp.json --strict-mcp-config --allowedTools mcp__wenchang "Bash(uv run python -m evals *)" "Edit(evals/runs/**)" --settings '{"includeGitInstructions": false}'
CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 claude -p "/run-evals --model sonnet --trials 3 --judge --shard 1/3" --permission-mode dontAsk --mcp-config evals/mcp.json --strict-mcp-config --allowedTools mcp__wenchang "Bash(uv run python -m evals *)" "Edit(evals/runs/**)" --settings '{"includeGitInstructions": false}'
```

The preflight now asks for the index call first and a marker last line, and
judges the recorded reply (checks a to d). The runner stops on any denied
call and if `judge.json` is missing.

## Acceptance criteria → tests

| Acceptance criterion | Test(s) |
| -------------------- | ------- |
| AC1-AC2 launch commands in run-evals.md | `test_launch_constants_match_the_spec`, `test_runner_doc_has_both_launch_commands` (`tests/test_evals_agent.py`) |
| AC3 every launch line has the flag and rule | `test_every_launch_line_has_permission_mode_and_edit_rule` |
| AC4-AC6, AC17 preflight prompt, checks, relaunch text | `test_runner_doc_has_the_exact_preflight_prompt`, `test_runner_doc_preflight_checks_the_agent_result`, `test_runner_doc_tells_a_wrong_session_to_relaunch` |
| AC7 "What each part does" | `test_runner_doc_launch_section_explains_each_part` |
| AC10 denied call, missing `judge.json` | `test_runner_doc_stops_on_denials_and_missing_judge_output` |
| AC17 step 3.2 requires `agent_id` | `test_runner_doc_requires_agent_id_for_the_full_reply` |
| AC11 reply reconstruction, uuid dedupe | `test_reply_is_the_assistant_text_in_order`, `test_reply_dedupes_entries_by_uuid_first_wins` (`tests/test_evals_subagent_transcript.py`) |
| AC12 lookup errors | `test_find_returns_the_single_match`, `test_find_with_no_match_names_the_id`, `test_find_with_two_matches_names_the_id`, `test_find_rejects_unsafe_ids` |
| AC13 projects root | `test_default_root_uses_claude_config_dir`, `test_default_root_falls_back_to_home` |
| AC14b filtering, root in error | `test_reply_ignores_thinking_blocks`, `test_reply_skips_api_error_and_synthetic_entries`, `test_not_found_error_names_the_root_and_the_flag` |
| AC14-AC15 `EvalState` and the tool | `tests/test_evals_server.py`: `test_record_turn_reads_the_reply_from_the_subagent_transcript`, `test_record_turn_without_a_findable_transcript_records_nothing`, `test_record_turn_tool_errors_when_the_transcript_is_missing`, `test_record_turn_is_unchanged_without_a_transcripts_root`, `test_record_turn_normalizes_a_decorated_agent_id`, `test_record_turn_rejects_a_blank_agent_id`, `test_record_turn_requires_the_final_text_in_the_agent_result`, `test_record_turn_consistency_check_ignores_whitespace_and_framing`, `test_missing_transcript_error_names_the_root_and_the_flag`, `test_record_turn_retries_until_the_transcript_appears`, `test_record_turn_retries_a_transcript_that_is_still_incomplete`, `test_record_turn_raises_on_a_persistently_torn_line`, `test_record_turn_raises_on_an_ambiguous_agent_id`, `test_reset_writes_an_empty_transcript_file` |
| AC16 `agent_result` round trip | `tests/test_evals_agent_result.py` |
| AC8 docs, AC9 `make check` | reviewer-checked; no unit test by design |

## Architecture / ADR changes

- New [ADR 0035](../../docs/adr/0035-eval-sessions-dontask.md). It reverses
  the rejection in ADR 0028 decision 7. Dated pointers added to ADR 0028
  (decisions 6 and 7, the 2026-10-14 note), 0031, and 0032.
- ARCHITECTURE.md: ADR 0035 link and an `evals.subagent_transcript` bullet.
- AGENTS.md and README.md carry the new launch command.

## Deviations from spec

- None from the issue's text beyond two additions: the `Edit` rule (needed or
  `--judge` loses `judge.json`) and the transcript route (needed or replies
  lose pre-tool text). ADR 0035 is used because 0034 is reserved by open
  PR #41.

## Live probe results

- Under `dontAsk`, the Agent result held only the final block; "I'll check my
  memory first." was lost.
- Through the harness, the preflight passed checks (a) to (d). The recorded
  reply was "I'll check my memory first.\n\nMy memory is empty, so there are no
  saved files in any scope yet.\n\nPROBE-END", while `agent_result` lacked the
  first sentence.
- Observation: in that probe the runner had to load the `eval_*` tools via
  ToolSearch, and the eval agent's reply mentioned deferred tools. Worth
  watching in the clean baseline. The probe session was launched from inside
  another Claude Code session, which may explain the deferral.

## Look closely at

- The transcript parser's layout assumptions (verified on Claude Code
  2.1.304) and its fail-loud paths.
- The flush-race check and retry in `record_turn`. `PermanentTranscriptError`
  (invalid id, ambiguous match) fails at once; other transcript errors retry
  up to 2 s.
- Preflight check (b) is self-reported; (d) is the backstop.
- `dontAsk` could deny something else the runner needs; D5 stops the run.
- Recorded replies now include pre-tool text, so reply-text checks,
  third-person counts, judge grades, `unmatched_reply_paths`, and the replay
  all shift versus old baselines.

## Follow-ups

- Clean N=6 baseline on main after merge (orchestrator); it resets baselines.
- A mechanical check for preflight (b) from the transcript's tool list.
- Compare the deferred-tools observation against the baseline.
