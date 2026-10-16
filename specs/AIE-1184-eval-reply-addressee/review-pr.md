# PR Review: AIE-1184 — Flag eval replies addressed to someone other than the user

> **Live-eval measurement: PENDING.** Merge waits on it. See "Live eval
> gate" below.

## What changed & why

The eval agent is a Claude Code subagent, and it sometimes replies as a
report to a parent ("The user said..."). The judge caught 3 of 138 baseline
trials. A new deterministic reply check finds 16. The check writes its
flags to `grade.json` and the report, separately from every pass count. The
report shows how many judge fails co-occur with a flagged reply. The
preamble now says the reply goes to the user word for word and addresses
them as "you". That change is kept only if the live gate below passes.

## Acceptance criteria → tests

Abbreviations: grd = `tests/test_evals_graders.py`, rpt =
`tests/test_evals_report.py`, agt = `tests/test_evals_agent.py`, e2e =
`tests/test_evals_end_to_end.py`.

| Acceptance criterion | Test(s) |
| -------------------- | ------- |
| 1.1 third-person report flagged | grd `test_reply_check_flags_a_third_person_report` |
| 1.2 normalized phrases, curly apostrophe, "the caller" | grd `test_reply_check_phrases_are_normalized` |
| 1.3 second person passes | grd `test_reply_check_passes_second_person_replies` |
| 1.4 user scope, possessive included | grd `test_reply_check_ignores_the_user_scope` |
| 1.5 quotes, backticks, fences, `>` lines | grd `test_reply_check_ignores_quoted_text` |
| 1.6, 1.7 echoes of user text and seed content | grd `test_reply_check_ignores_echoes_of_the_users_text`, `..._of_seed_content` |
| 1.8 seed description and aliases | grd `test_reply_check_ignores_echoes_of_seed_metadata` |
| 1.9 only the echoed phrase is exempt | grd `test_reply_check_exempts_only_the_echoed_phrase` |
| 1.10 context is per session and up to the turn | grd `test_reply_check_context_is_per_session`, `test_reply_check_later_user_turns_do_not_exempt_earlier_replies` |
| 1.11 one flag per reply | grd `test_reply_check_flags_once_per_reply` |
| 1.12–1.14 word-boundary context match | grd `test_reply_check_context_match_needs_word_boundaries`, `..._is_not_a_prefix_match`, `test_reply_check_exempts_a_bounded_echo_without_next_word` |
| 1.15 "the users" not matched | grd `test_reply_check_ignores_the_users` |
| 1.18 bare echo needs the same ending (curated-shared-conflict) | grd `test_reply_check_bare_echo_needs_the_same_ending`, `test_reply_check_bare_echo_at_the_end_of_both_texts` |
| 1.19 "the caller's" | grd `test_reply_check_caller_possessive` |
| 1.20 any whitespace between "the" and "user" | grd `test_reply_check_any_whitespace_between_the_and_user` |
| 1.21 U+02BC apostrophe | grd `test_reply_check_modifier_letter_apostrophe` |
| 1.22 en and em dash before "scope" | grd `test_reply_check_dashes_before_scope` |
| 1.16, 1.17 no `mcp` import; `grade` unchanged | grd `test_graders_do_not_import_the_driver` and the existing grader tests |
| 2.1 preamble text, rendered file | agt `test_preamble_frames_each_message_as_the_users_turn`, `test_eval_agent_body_is_preamble_plus_prompt` |
| 2.2–2.4 grade.json key flagged, empty, absent | rpt `test_grade_records_third_person_replies`, `test_grade_records_an_empty_reply_check`, `test_grade_without_a_transcript_has_no_reply_check` |
| 2.5 malformed, undecodable, or deep transcript never blocks | rpt `test_malformed_transcript_never_blocks_grading`, `test_unreadable_transcript_never_blocks_grading` |
| 2.6 CLI line | rpt `test_grade_cli_prints_third_person_replies` |
| 2.7 no silent regrade | rpt `test_report_adds_the_reply_check_without_regrading` |
| 2.8 newer transcript refreshes check only | rpt `test_report_rechecks_replies_when_the_transcript_is_newer` |
| 2.9 newer dumps regrade fully | rpt `test_report_fully_regrades_when_dumps_are_newer` |
| 2.10–2.13 report entries, totals, markdown | rpt `test_report_separates_third_person_trials`, `test_report_json_totals_third_person_trials`, `test_report_markdown_shows_third_person_trials`, `test_report_markdown_omits_empty_addressee_lines` |
| 2.14 merged totals | rpt `test_merge_runs_sums_third_person_trials` |
| 2.16 deleted transcript drops the check | rpt `test_report_drops_the_check_when_the_transcript_is_gone` |
| 2.17 current check left alone | rpt `test_report_leaves_a_current_check_alone` |
| 2.15 scripted correct drivers clean | e2e `test_correct_driver_passes_every_assertion` |
| 3.1–3.5 live gate | human-run, below |

## Architecture / ADR changes

- New [ADR 0031](../../docs/adr/0031-reply-addressee-check.md).
- The ADR 0028 Consequences note now points to ADR 0031.
- In `ARCHITECTURE.md` "Outside the library: `evals/`", the
  `evals.graders` and `evals.report` bullets are updated.

## Deviations from spec

- None from the spec.
- From the issue: this adds neither an assertion kind nor a judge rubric
  line. It adds a harness-wide reply check that never changes a pass count
  (spec "Deviation from the issue", ADR 0031).

## Agent file

- Before: sha256 `b668ca85407c598dcb793f52c69f5fde96fbb99f53f57831717801c250a5c687`.
- After: sha256 `36508763a0f914db4fc36e93f0a953217be24b83f17244415049720ac5548fb3`.

## Baseline re-measured with the shipped code (US3.1)

Copies of the AIE-1170 baseline dirs, made with `cp -Rp` to preserve
mtimes, were re-reported with the shipped code, after the review fixes.
For every trial, `results` and `passed` matched the originals:

- Run A (`20261014-225317-sonnet`): `Trials with a third-person reply: 7 of
  69 checked.` Deterministic results are unchanged
  (`recall-replace-fact` 1/3, `remembering-stated-role` 0/3, all others
  3/3).
- Run B (`20261014-231845-sonnet-merged`): `9 of 69 checked.`
  Deterministic results are unchanged (`remembering-stated-role` 0/3, all
  others 3/3).
- Baseline B = 16, so the gate threshold is floor(16/2) = 8.

Keep the AIE-1170 worktree, `/Users/marksiebert/p/github/wenchang-AIE-1170`,
until this PR merges. Its `evals/runs/` holds the baseline and is
gitignored.

## Live eval gate (US3): PENDING

**Order.**

1. Measure on this branch (main abe49c9 plus this change), before AIE-1182
   or AIE-1183 land.
2. Merge AIE-1184 first. AIE-1182 and AIE-1183 then measure against the
   new main.

**Known confound.** The baseline predates 5bd1355, which requires
`model=` on every per-turn Agent call. Run A reran one trial that omitted
it.

**Commands.** Run these from the worktree root. Run each run's three
shards concurrently, in separate terminals.

```
CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 claude -p "/run-evals --model sonnet --trials 3 --judge --shard 1/3" --mcp-config evals/mcp.json --strict-mcp-config --allowedTools mcp__wenchang "Bash(uv run python -m evals *)" --settings '{"includeGitInstructions": false}'
CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 claude -p "/run-evals --model sonnet --trials 3 --judge --shard 2/3" --mcp-config evals/mcp.json --strict-mcp-config --allowedTools mcp__wenchang "Bash(uv run python -m evals *)" --settings '{"includeGitInstructions": false}'
CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 claude -p "/run-evals --model sonnet --trials 3 --judge --shard 3/3" --mcp-config evals/mcp.json --strict-mcp-config --allowedTools mcp__wenchang "Bash(uv run python -m evals *)" --settings '{"includeGitInstructions": false}'
uv run python -m evals merge-runs evals/runs/aie1184-run1 <shard1 dir> <shard2 dir> <shard3 dir>
```

Repeat for a second run (`evals/runs/aie1184-run2`).

**Gate.** Count only the 23 baseline scenario ids. Keep the preamble only
if all three hold:

- (a) Flagged trials over both runs are at most 8 of 138.
- (b) No scenario's combined deterministic trials-passed is more than 1
  below baseline. Baseline is 6/6 for every scenario except
  `recall-replace-fact` (4/6) and `remembering-stated-role` (0/6).
- (c) Summed judge passes over all judged items are no lower than the
  baseline sum. Record per-item deltas below.

Also spot-check the stored fact lines in the new `store.json` files for
phrasing drift caused by the preamble, such as "you" in facts (US3.3).

| Measure | Baseline (A+B) | New (run1+run2) |
| ------- | -------------- | --------------- |
| Flagged trials | 16 / 138 | PENDING |
| Scenarios more than 1 below baseline | n/a | PENDING |
| Summed judge passes | 45 / 48 | PENDING |
| Per-item judge deltas | n/a | PENDING |
| Fact-line spot check | n/a | PENDING |

**Revert path if the gate fails.** Restore `main`'s versions of three
files:

- `evals/agent.py`: the `EVAL_AGENT_PREAMBLE` text;
- `.claude/agents/wenchang-eval.md`: re-render with `uv run python -m evals
  render-agent`, so the sha256 returns to `b668ca85...`;
- `tests/test_evals_agent.py::test_preamble_frames_each_message_as_the_users_turn`:
  both its expected string and its docstring.

For example, `git checkout main -- evals/agent.py
.claude/agents/wenchang-eval.md`, then restore that one test by hand. Keep
everything else. Record the outcome here and in ADR 0031.

## Look closely at

- `THIRD_PERSON_PATTERN` in `evals/graders.py`. Its possessive `?+` keeps
  "the user's scope" from matching by backtracking to "the user".
- `_refresh_reply_check` in `evals/report.py`. It must never touch
  `results` or `passed`.
- The new judge-table column. Existing substring assertions still hold.

## Follow-ups

- Widen the guard hook's rule 4 for `evals/**`. This is a human change,
  already listed in AGENTS.md.
- An Anthropic SDK driver would remove the subagent framing altogether.
  It is not scheduled.
