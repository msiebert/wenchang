# Feature Specification: Flag eval replies addressed to someone other than the user

**Linear issue**: AIE-1184 — Eval harness: agent sometimes replies as a report to a parent, failing judge rubrics

**Feature Branch**: `AIE-1184-eval-reply-addressee` (based on `main` at abe49c9)

**Created**: 2026-10-16

**Status**: Revised after adversarial spec review round 1

**Input**: Linear AIE-1184; ADR 0028 Consequences note (2026-10-14, N=3
runs); `specs/AIE-1170-eval-harness/review-pr.md` "Live runs at N=3"; the
baseline run dirs `evals/runs/20261014-225317-sonnet` (run A, 9c51a50) and
`evals/runs/20261014-231845-sonnet-merged` (run B, a0b1e23), kept locally
in the AIE-1170 worktree.

Allow-test-changes: `tests/test_evals_agent.py::test_preamble_frames_each_message_as_the_users_turn`
pins the old preamble byte for byte. This issue changes the preamble, so
that test's expected string and docstring are rewritten (US2.1). If the
US3 gate fails, the revert restores both. The end-to-end correct-driver
test is extended with a `third_person_replies == []` check (US2.15). No
other existing test is weakened.

## Deviation from the issue

The issue asks for "a deterministic sanity assertion kind OR a judge rubric
line". This spec does neither. It adds a harness-wide deterministic reply
check instead. The check runs on every trial, reads `transcript.json`, and
never changes an assertion result or a pass count. An assertion kind would
count toward deterministic pass/fail, and a judge line would be LLM-graded.
Either would blur the two failure types the issue asks to keep apart. The
reasoning is in [ADR 0031](../../docs/adr/0031-reply-addressee-check.md),
and the PR body repeats it.

## Summary

The eval agent is a Claude Code subagent, and Claude Code frames subagent
output as a report to a parent agent. The preamble says "reply to them
directly", which usually wins but not always. When it loses, the reply
talks about the user in the third person ("I asked the user whether to
save it", "waiting for the user's confirmation").

The issue counted 3 such trials of 138, the ones whose judge item failed.
A calibration pass over the same 138 baseline trials with the US1 check
finds **16** (run A 7/69, run B 9/69), including all 3, with no false
positives on manual review. The other 13 passed their judge items because
their rubrics do not hinge on wording.

This issue does two things:

1. **Reply check (deterministic, always on).** Grading scans every
   recorded reply for third-person references to the user. Hits go into
   `grade.json` and the report as a separate signal. The report shows, per
   judged item, how many failures came from trials with a third-person
   reply. That count shows co-occurrence, not cause: a judge fail in a
   flagged trial may still be a wrong answer.
2. **Stronger preamble (conditional).** `EVAL_AGENT_PREAMBLE` says the
   reply goes to the user word for word, and that the reply addresses them
   as "you". It is kept only if the US3 human-run measurement passes.
   Otherwise it is reverted before merge and the reply check lands alone.

The judge agent file, every judge rubric, and every scenario YAML are
unchanged.

## Glossary for this spec

- **Third-person reply**: a recorded reply that the reply check flags (US1).
- **Flagged trial**: a graded trial with at least one third-person reply.
- **Checked trial**: a graded trial whose `grade.json` has a
  `third_person_replies` key.
- **Unchecked trial**: a graded trial whose `grade.json` lacks that key,
  because `transcript.json` was missing or malformed.
- **Baseline**: runs A and B above, agent file sha256 `b668ca85...`, 138
  trials over 23 scenario ids, 16 flagged.

## Acceptance criteria

### US1 — Reply check

Rules, applied to one reply (`TranscriptTurn.reply`) at a time:

- **R1 Quoted text is ignored.** The check removes the following before
  matching:
  - fenced code blocks (from a line starting with ```` ``` ```` through the
    next such line, or to the end of the reply);
  - lines whose first non-blank character is `>`;
  - text inside `"..."`, `“...”`, or `` `...` `` on one line.

  Replies quote memory lines and curated files, which may say "the user".
- **R2 Pattern.** The match is case-insensitive.
  - It is `\bthe`, any whitespace run (newlines and NBSP included), then
    `user`.
  - An optional `'s`, `’s`, or `ʼs` follows. It is taken possessively and
    never backtracked.
  - No word character or apostrophe may come after it.
  - It must not be followed by hyphens, en or em dashes, or whitespace and
    then `scope` or `scopes`.
  - `the caller` matches the same way, possessive included, with no scope
    exclusion.
  - "the user scope", "the user-scope", "the user—scope", "the user's
    scope", and "the users" do not match.
- **R3 Echoes are ignored.**
  - The phrase is the match plus, when whitespace and a word follow it,
    that next word. It is lowercased, `’` becomes `'`, and whitespace
    collapses to single spaces.
  - A match with a next word is skipped if its phrase occurs in the same
    normalization of a context text, bounded on both sides by a non-word
    character or the text's edge.
  - A bare match has no next word. It is skipped only if a context text
    has the phrase, after a non-word character or at the text's start,
    followed by the same next non-space character. If the reply ends
    after the match, the phrase must instead end a context text.
  - The context is the user text of every transcript turn in the same
    session up to and including this turn, plus every scenario seed file's
    content, description, and aliases.
- **R4 One flag per reply.** The check reports the first match that R3
  does not skip, with its R3 phrase.

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1.1 | a transcript whose session 1 turn 1 reply is "I haven't saved anything yet. The user asked me to remember that the company calls them accounts." | `find_third_person_replies(scenario, transcript)` | returns exactly `(ThirdPersonReply(session=1, turn=1, phrase="the user asked"),)` |
| 1.2 | one turn each with the replies "I need the user's confirmation before writing there.", "I asked the user whether to save it.", "Waiting for the user’s yes or no.", and "(Note for the caller: they said they are 15.)" | as 1.1 | four flags in transcript order, with phrases `"the user's confirmation"`, `"the user whether"`, `"the user's yes"`, and `"the caller"` |
| 1.3 | a second-person reply: "You said Signup means verified email. Should I save it to the project scope?" | as 1.1 | returns `()` |
| 1.4 | the replies "Saved to your private user scope.", "It belongs in the user scope, or the user-scope fallback.", and "It goes in the user's scope." | as 1.1 | returns `()` (R2 scope exclusion, possessive included) |
| 1.5 | the reply `It says: "Signup fires when the user submits the form."`, a reply with `` `the user` `` in backticks, a reply whose only "the user" is inside a fenced code block, and a reply whose only "the user" is on a `> ` line | as 1.1 | returns `()` (R1) |
| 1.6 | the user turn "Signup means the user has verified their email." and the reply "You said Signup means the user has verified their email." | as 1.1 | returns `()` (R3, user text) |
| 1.7 | a seed file whose content contains "the user submits", and the unquoted reply "Signup fires when the user submits the form." | as 1.1 | returns `()` (R3, seed content) |
| 1.8 | a seed file whose description is "The Atlas migration the user leads", and the reply "That is the Atlas migration the user leads." | as 1.1 | returns `()` (R3, seed description); the same holds for a seed alias |
| 1.9 | as 1.6, but the reply goes on: "The user said that at their company it differs." | as 1.1 | one flag, phrase `"the user said"` (R3 exempts only the echoed phrase) |
| 1.10 | "the user said" appears only in a session 2 user turn, and a session 1 reply says "The user said X." | as 1.1 | the session 1 reply is flagged (R3 context is per session and up to the turn) |
| 1.11 | a reply with two qualifying matches | as 1.1 | exactly one flag, for the first match (R4) |
| 1.12 | the user turn "Did the user asked event fire?" and the reply "I gave the user a draft." | as 1.1 | one flag, phrase `"the user a"` (R3 needs a word boundary, so "the user a" does not match inside "the user asked") |
| 1.13 | the user turn "Ask the users team." and the reply "The user said yes." | as 1.1 | one flag, phrase `"the user said"` |
| 1.14 | the user turn "Tell the user, then stop." and the reply "Tell the user, then stop." | as 1.1 | returns `()` (the phrase `"the user"` is followed by `,` in the reply, has no next word, and occurs at a word boundary in the context) |
| 1.15 | the reply "Ask the users which one." | as 1.1 | returns `()` (R2 does not match "the users") |
| 1.10b | a session 1 turn 1 reply "The user said X." and a turn 2 user text "the user said X" | as 1.1 | the turn 1 reply is flagged (later turns are not context) |
| 1.18 | the shipped `curated-shared-conflict` scenario, whose seed says "the user submits", and the reply "I'll check with the user." | as 1.1 | one flag, phrase `"the user"`; a reply ending "tell the user" is exempt only if a context text ends with "the user" |
| 1.19 | the reply "This is the caller’s note." | as 1.1 | one flag, phrase `"the caller's note"` |
| 1.20 | "the", a newline, an NBSP, or several spaces, then "user whether" | as 1.1 | one flag, phrase `"the user whether"` |
| 1.21 | the reply "I need the userʼs confirmation." (U+02BC) | as 1.1 | one flag, phrase `"the user's confirmation"` |
| 1.22 | the reply "Saved to the user–scope file." with an en or em dash | as 1.1 | returns `()` |
| 1.16 | `evals.graders` | its imports are checked (existing test) | it still imports no `mcp` module |
| 1.17 | any scenario, store, and trace | `grade(scenario, store, trace)` | its signature and results are unchanged |

### US2 — Preamble, grade.json, CLI, and report

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 2.1 | the eval agent | `EVAL_AGENT_PREAMBLE` is read | it equals the plan.md §3 text exactly; after `uv run python -m evals render-agent`, `.claude/agents/wenchang-eval.md` equals `render_agent_file()` (existing drift test); the pin test's docstring cites AIE-1184 |
| 2.2 | a dumped trial with `transcript.json` whose session 1 turn 1 reply is flagged | `grade_trial(trial_dir)` | `grade.json` has `"third_person_replies": [{"session": 1, "turn": 1, "phrase": "the user asked"}]`; `results` and `passed` equal those for the same trial with a second-person reply |
| 2.3 | a dumped trial with `transcript.json` and no flagged reply | as 2.2 | `grade.json` has `"third_person_replies": []` |
| 2.4 | a dumped trial with no `transcript.json` | as 2.2 | `grade.json` has neither `third_person_replies` nor `transcript_error`, and grading succeeds as today |
| 2.5 | a dumped trial whose `transcript.json` is malformed, undecodable (`b'{"turns": [\xff]}'`), or nested 100000 deep | as 2.2, and `python -m evals grade`, then `build_report` | grading succeeds with the usual `results` and `passed`; `grade.json` has no `third_person_replies` and has `"transcript_error": "<message naming transcript.json>"`; the CLI exits 0, and its last line is exactly `TRANSCRIPT ERROR: <that message>`; the report lists the trial as unchecked |
| 2.6 | the trial of 2.2 | `python -m evals grade <trial_dir>` | stdout has the existing PASS/FAIL lines, then `THIRD-PERSON session 1 turn 1: the user asked`; exit code 0 |
| 2.7 | a `grade.json` that is current for store.json and trace.json, lacks `third_person_replies`, and whose `results` and `passed` deliberately differ from what a fresh grade would give, with `transcript.json` present | `build_report(run_dir)` | `grade.json` gains `third_person_replies`, its `results` and `passed` are kept unchanged, and the report counts them as they were |
| 2.8 | a `grade.json` current for store and trace but older than `transcript.json` | `build_report(run_dir)` | only `third_person_replies` (or `transcript_error`) is recomputed; `results` and `passed` are kept |
| 2.9 | a `grade.json` older than store.json or trace.json | `build_report(run_dir)` | the trial is fully regraded as today, including the reply check |
| 2.10 | a scenario with 3 trials: trial 1 flagged (session 1 turn 1, "the user said"), trial 2 clean, trial 3 graded without a transcript; judge item `polite` fails in trials 1 and 2; judge item `kind` has no verdicts | `build_report(run_dir)` | the scenario entry has `"third_person_trials": [{"trial": 1, "replies": [{"session": 1, "turn": 1, "phrase": "the user said"}]}]`, `"addressee_unchecked_trials": [3]`, and `"judge_third_person_fails": [{"id": "polite", "fails": 1}]` (unjudged `kind` absent, as in `judge`); its `judge`, `assertions`, `passed_trials`, and `pass_rate` equal what they would be without the reply check |
| 2.11 | the run of 2.10 | `report.json` is read | the top level has `"third_person": {"flagged_trials": 1, "checked_trials": 2}` |
| 2.12 | the run of 2.10 | `report.md` is read | it has `Trials with a third-person reply: 1 of 2 checked.` after the summary table; the scenario section has `Third-person replies: trial 1 (session 1 turn 1: "the user said")` and `Addressee not checked: 3`; the judge table header is `\| Judge item \| Passes \| Fails with a third-person reply \|` and its row is `\| polite \| 0/2 \| 1 \|` |
| 2.13 | a scenario with no flagged and no unchecked trials | as 2.12 | its section has no `Third-person replies:` or `Addressee not checked` line |
| 2.14 | shard runs with flagged trials | `merge_runs(out, shards)` | the merged `third_person` totals are the sums over the shards |
| 2.16 | a recorded check whose `transcript.json` was then deleted | `build_report(run_dir)` | `third_person_replies` and `transcript_error` are dropped from `grade.json`, `results` and `passed` are kept, and the trial counts as unchecked |
| 2.17 | a `grade.json` current for store, trace, and transcript that already has the check | `build_report(run_dir)` | it is not rewritten (mtime unchanged) and its flags are unchanged |
| 2.15 | any shipped scenario run by its scripted correct driver (end to end) | it is graded | `grade.json` has `"third_person_replies": []` |

### US3 — Measurement gate for the preamble (human-run, not in `make check`)

Order: measure on this branch (main abe49c9 plus this change) before
AIE-1182 or AIE-1183 land, and merge AIE-1184 first. Those issues then
measure against the new main. Known confound: the baseline runs predate
5bd1355, which requires `model=` on every per-turn Agent call. Run A
reran one trial whose turn 2 omitted it.

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 3.1 | this branch with US1 and US2, and the AIE-1170 worktree kept so its `evals/runs/` baseline dirs survive | `uv run python -m evals report` on copies of baseline run dirs A and B | they report 7 of 69 and 9 of 69 flagged trials, with deterministic results unchanged (US2.7). If the shipped code gives other counts, those counts are the baseline B. |
| 3.2 | two full `/run-evals --model sonnet --trials 3 --judge` runs at this branch's head, sharded or serial, counting only the 23 baseline scenario ids | their reports are read | **keep the preamble** only if all three hold: (a) flagged trials total at most floor(B/2), which is 8 of 138 for B = 16; (b) no scenario's combined deterministic trials-passed is more than 1 below its baseline combined count (baseline: 6/6 for every scenario except `recall-replace-fact` 4/6 and `remembering-stated-role` 0/6); (c) summed judge passes over all judged items are no lower than the baseline sum, with per-item deltas recorded in `review-pr.md` |
| 3.3 | either outcome | the stored fact lines in the new runs' `store.json` files are spot-checked | lines are not phrased differently because of the preamble (for example "you" where the baseline wrote facts neutrally); any change is recorded in `review-pr.md` |
| 3.4 | 3.2 fails | before merge | `EVAL_AGENT_PREAMBLE`, `.claude/agents/wenchang-eval.md`, and the US2.1 test (string and docstring) revert to `main`'s text; US1 and US2 still land |
| 3.5 | either outcome | the PR is finalized | ADR 0031 and `review-pr.md` record the measured counts, and `review-pr.md` records the shipped agent file's sha256 |

## Out of scope

- An Anthropic SDK driver (issue option 2; not scheduled).
- Any change to the judge agent, judge rubrics, scenario YAML, scripted
  drivers, or the memory prompt.
- Failing any trial or assertion because of a third-person reply.
- Widening the guard hook's rule 4 for `evals/**`. That is a separate
  human follow-up, already listed in AGENTS.md.
