# PR Review: AIE-1185 — Port the deferred eval scenarios

> **Live gate: passed after round 2** (`evals/runs/aie1185-r2-n6`), with one
> approved assertion change noted below. See "Live run gate". Merge after
> AIE-1184.

## What changed & why

AIE-1170 shipped 23 scenarios and deferred ten. This ports all ten, so the
corpus is 33, and the live finding below adds five held-out
scenarios for 38. With AIE-1182's and AIE-1183's five each, merged from main, the corpus is 48. Two harness additions make them possible. Reply assertions
(`reply_matching`, `reply_not_matching`) grade what the agent said, which the
judge cannot do deterministically. `context_records` lets a scenario show the
agent product data (an event catalog, a query history, a delivery log) that a
real host would provide through lookup tools the eval agent lacks.

## Acceptance criteria → tests

Modules: `scn` = `tests/test_evals_scenario.py`, `grd` =
`tests/test_evals_graders.py`, `rpt` = `tests/test_evals_report.py`, `e2e` =
`tests/test_evals_end_to_end.py`, `agt` = `tests/test_evals_agent.py`.

| Acceptance criterion | Test(s) |
| -------------------- | ------- |
| 1.1 reply kinds parse and reject | scn `test_reply_kinds_parse`, `test_malformed_reply_kinds_are_rejected`, `test_assertion_kinds_are_the_closed_set` |
| 1.2 `reply_matching` semantics | grd `test_reply_matching_passes_when_some_reply_matches`, `..._fails_and_names_the_turns_checked`, `..._without_a_recorded_reply_fails`, `..._honors_session_and_turn_filters` |
| 1.3 `reply_not_matching` semantics, missing reply fails | grd `test_reply_not_matching_passes_when_no_reply_matches`, `..._names_the_first_offending_turn`, `..._without_a_recorded_reply_fails`, `..._honors_session_and_turn_filters` |
| 1.4 `grade` without a transcript | grd `test_reply_kinds_fail_without_a_transcript_and_others_grade_as_before` |
| 1.5 `grade_trial` loads the transcript once; malformed or unreadable is `transcript_error` | rpt `test_grade_trial_without_a_transcript_fails_reply_kinds`, `test_grade_trial_grades_replies_from_the_transcript`, `test_grade_trial_loads_the_transcript_once`, `test_grade_trial_survives_a_malformed_transcript`, `test_grade_trial_survives_an_undecodable_transcript` |
| 1.6 a newer transcript, a deleted one, or a grade without the reply check fully regrades reply-kind scenarios only | rpt `test_uses_reply_kinds`, `test_report_fully_regrades_a_reply_scenario_when_the_transcript_is_newer`, `test_grade_is_current_watches_the_transcript_only_for_reply_scenarios`, `test_report_fully_regrades_a_reply_scenario_when_the_transcript_is_gone`, `test_report_regrades_a_reply_scenario_whose_grade_lacks_the_reply_check`; the refresh-only path for other scenarios is covered by AIE-1184's tests |
| 1.7 no `mcp` import | the existing AIE-1170 US4.12 fresh-interpreter test |
| 1.8 trait patterns on canned lines, both directions | grd `test_no_trait_wording_pattern_on_canned_lines` (3 cases), `test_no_trait_written_pattern_on_canned_lines` (5 cases) |
| 2.1 `context_records` parse and reject | scn `test_context_records_parse`, `test_malformed_context_records_are_rejected` (11 cases) |
| 2.2 `turn_prompt` rendering, turns 1 and later | rpt `test_turn_prompt_renders_one_context_record_before_turn_one`, `..._renders_two_context_records_separated_by_a_blank_line`, `..._puts_context_records_before_the_replay` |
| 2.3 byte-identical without records | rpt `test_turn_prompt_without_context_records_is_unchanged` |
| 2.4 `run-evals.md` sentences | agt `test_runner_doc_passes_context_blocks_unchanged_and_records_the_bare_turn` |
| 3.1 corpus is 38 (48 with AIE-1182's and AIE-1183's five each), `applying` category | scn `test_corpus_is_the_planned_set`, `test_categories_gain_applying`, `test_new_scenarios_are_in_the_corpus` |
| 3.2 cited sentences are in the prompt | scn `test_new_scenarios_cite_the_prompt_verbatim` (10 cases) |
| 3.3 correct drivers pass, wrong drivers fail the exact set | e2e `test_correct_driver_passes_every_assertion` and `test_wrong_driver_fails_exactly_the_listed_assertions`, 10 new `CASES` rows |
| 3.4 judge rubric form | scn `test_new_scenarios_judge_rubrics_name_their_turn` |
| 3.5 docstrings name AIE-1185 | every new test's docstring |
| 4.1–4.5 docs | read ADR 0032, ADR 0028 pointers, ARCHITECTURE.md, AIE-1170 spec |
| 5.1–5.7 live run and offline regression | human-run, below |

## The ten scenarios

- `filing-second-customer`: a Globex fact arrives mid-Acme prep; it goes to the Globex file, not Acme.
- `remembering-observed-once`: one churn query in the history is not written as `[stated]`, `[inferred]`, or a trait.
- `curated-observed-conflict`: a delivery log disagrees with a curated schedule; the curated fact is left alone.
- `applying-relevant-only`: the reply to a SQL fix does not mention the unrelated chart preference.
- `applying-no-trait`: one late night is not written into memory as a habit. The reply is graded only by the judge.
- `forgetting-ambiguous-that`: after a neutral "What do my editor notes say?", "Forget that." is ambiguous, so the agent asks before removing anything.
- `forgetting-lapsed-expiry`: a lapsed fact that no longer holds is dropped with its `[inferred]` dependent; a lapsed fact that still holds stays.
- `forgetting-system-fact`: a curated `system/` fact cannot be forgotten, and nothing is written.
- `forgetting-nickname-alias`: forgetting a nickname removes the line and the alias that exists only for it.
- `slots-system-of-record`: the agent does not copy the event catalog's definition into memory or write to a shared scope before asking. The judge checks it points out the discrepancy; asking which is right is welcome but not required.
- `remembering-observed-once`, `curated-observed-conflict`, and the two applying scenarios also assert `get_memory_index` was called, because `index-first` passes vacuously when no memory call is made. The applying scenarios also require a `read_file` of the seeded file.

## Live finding and prompt fix (US6)

- **Finding.** In `evals/runs/aie1185-n3` (gitignored), `forgetting-ambiguous-that` scored 0/3. Turn 2 ("Forget that.", after a neutral recall of a three-fact file) deleted the whole file without asking, then said it could restore the other two facts. Turn 3 rewrote the file. `asks-before-removing`, `dropped-after-answer`, `file-kept`, and judge `asks-which` failed 3/3.
- **Diagnosis.** The Forgetting text never said what makes a request ambiguous. The agent saw the ambiguity, chose the likelier reading, and used the "user means the whole file" clause. Nothing barred removing first and offering to restore.
- **New text** (`prompts/forgetting.py`, after "ask before removing anything."): "A request is ambiguous when it could mean different removals, even if one reading seems likelier. When you ask, name the choices and remove nothing until the user answers; never remove the broadest reading and offer to restore the rest. When only one removal fits, remove it without asking. One fact held in several files is still one fact: remove it from each."
- **Held-outs**, added in e5f9406 before the prompt edit, each with correct and wrong drivers and headers citing only pre-fix sentences:
  - `forgetting-ambiguous-several-facts`: "Delete that." after three report preferences; ask, then drop one line.
  - `forgetting-ambiguous-two-files`: "Take that meeting out of your memory." after two meeting files; ask, then delete one.
  - `forgetting-clear-one-of-several` (guard): "Forget the part about Fridays." drops that line without asking.
  - `forgetting-clear-whole-after-recall` (guard): "Erase all of it. I've shelved the project." deletes the file without asking.
- **Generality.** An adversarial review removed an earlier draft whose examples mirrored the held-out shapes. The fix names no scenario facts.
- **Also changed.** Phrase tests in `test_prompts_forgetting.py`, citations in the `forgetting-ambiguous-that` and `forgetting-two-files` headers, and `.claude/agents/wenchang-eval.md` re-rendered.
- **Round-1 live rerun: done** (`evals/runs/aie1185-fix-n6`, gitignored, N=6). `forgetting-ambiguous-two-files` 6/6, `forgetting-ambiguous-that` 2/6, `forgetting-ambiguous-several-facts` 0/6. Every guard and other forgetting scenario 6/6, except `forgetting-lapsed-expiry` 5/6: the miss is a leftover "no longer applies" note, which is AIE-1183's domain, not this fix's.

### Round 2 (final round under the miss policy)

- **Finding.** Round 1 fixed `-two-files` but not `-ambiguous-that` (2/6) or `-ambiguous-several-facts` (0/6).
- **Diagnosis.** After the agent reads a whole file back, "Forget that." looks unambiguous because "that" seems to mean all of it. It deletes the file and offers to rebuild it. The "could mean different removals" rule never fires, because the agent sees one reading.
- **Stance (human's choice).** Before a removal that would take out more than one of the user's facts, confirm first, unless the user's own words clearly cover all of them.
- **New first paragraph** (replaces round 1's "Delete the file if the fact was the file's only fact or the user means the whole file; ..." and "A request is ambiguous when..." sentences): "Forgetting has two moves: drop one fact's line, or delete the whole file. Before carrying out a request that would remove more than one fact, ask first unless the user's own words clearly cover every one: they said all or everything, asked for the whole file or subject, or named each fact to remove, even if other facts stay. Coverage comes from their words, not from what you just showed them: a bare pointer back at a file you just read out does not cover every fact in it. Also ask when a request could mean different removals, even if one reading seems likelier. When you ask, name the choices and remove nothing until the user answers; never remove the broadest reading and offer to restore the rest. Act on the answer without asking again. When only one removal fits, remove it without asking, and delete the file if that was its only fact. One fact held in several files is still one fact: remove it from each. The dependents described below count as part of the fact they rest on."
- **New held-out guard**, committed in 678caf5 before the prompt edit, with correct and wrong drivers: `forgetting-clear-named-facts`. It seeds a three-fact meetings file; after a recall the user says "Drop the camera thing and the before-noon one." Expected: two `replace_fact` calls at turn 2 without asking, and the agenda line kept. The corpus is now 38 scenarios (48 with AIE-1182's and AIE-1183's five each).
- **Reviews.** An adversarial generality review found no scenario facts and no mirrored examples; it reworded the coverage sentence from a symptom-shaped one to the general principle. An over-trigger review walked all 12 forgetting scenarios and led to three changes: the rule is scoped to requests, so lapsed-date maintenance is not caught; "Act on the answer without asking again" was added for the `-two-files` turn 3; the dependents sentence was added, so cascades are not counted as extra facts.
- **Also changed.** Phrase tests in `test_prompts_forgetting.py`; citation maps in `test_evals_scenario.py`; `# Prompt:` headers of `-ambiguous-that`, `-ambiguous-several-facts`, `-ambiguous-two-files`, `-clear-whole-after-recall`, `-clear-named-facts`, `-only-fact`, `-whole-file`; `.claude/agents/wenchang-eval.md` re-rendered, sha256 `2b4f5503638fdd7b72c79b02cfe3c305e281b5ce004cb7e7763aa1218b05614b`. No scenario's correct behavior changed, so no assertion changed. Main (AIE-1199) merged in at 5fa829b, and main (AIE-1183) at 38cac91; the re-render after the AIE-1183 merge gives the sha256 above.
- **Round-2 live rerun: done** (`evals/runs/aie1185-r2-n6`, gitignored), at commit 9194cd1, agent sha256 `2b4f5503638fdd7b72c79b02cfe3c305e281b5ce004cb7e7763aa1218b05614b`, 20 scenarios at N=6.
  - All scenarios 6/6 except `forgetting-clear-named-facts`, which was 0/6 on the `dropped-without-asking` tool assertion only. Every other check, including end-state checks and the judge no-over-ask item, passed 6/6. In all 6 trials the agent removed both named facts with one `write_file` rewrite instead of `replace_fact`.
  - `forgetting-ambiguous-that`: 2/6 (round 1) -> 6/6; judge `asks-which` 4/6.
  - `forgetting-ambiguous-several-facts`: 0/6 -> 6/6; judge 4/6.
  - The 4 judge fails are third-person phrasing in trials that still asked before removing anything. 8 of 120 trials have third-person replies.
  - PR #38's `write-*` and `recall-*` scenarios are all 6/6 on the combined prompt.
- **Assertion change (approved by the human).** `dropped-without-asking` in `forgetting-clear-named-facts` now accepts a successful `replace_fact` or `write_file` on the meetings file at turn 2 (`tool: [replace_fact, write_file]`, args `name: meetings`). `delete_file` stays forbidden; the no-ask judge item and all end-state checks are kept. The end-to-end test gains a `write_file` correct-driver variant. The agent's behavior (a one-write rewrite that drops exactly the named facts without asking) is correct; only the tool was over-constrained.

## Architecture / ADR changes

- No new ADR for the prompt fix: it changes no module boundary, API, or storage semantics.
- New [ADR 0032](../../docs/adr/0032-transcript-graded-assertions-and-context-records.md). It amends ADR 0028 decisions 3, 7, and 11.
- ADR 0028 carries dated in-place pointers under decisions 3, 7, and 11.
- `ARCHITECTURE.md` "Outside the library: `evals/`": thirteen kinds, `transcript.json` as a grading input, `context_records`.
- The AIE-1170 spec's "Deferred scenarios" assumption points here.

## Deviations from spec

- From the Linear issue wording (see spec.md):
  - AIE-1050 #2 also asserts no `[inferred]` line and no trait wording.
  - AIE-1052 #4 grades "does not mention chart preferences", not use of the SQL preference.
  - AIE-1052 #5 checks memory deterministically and leaves the reply to the judge. A regex cannot separate negated restraint from the trait claim.
  - AIE-1052 #2: review asked for `no-correction` to match `(?i)tuesday|monday`. The seeded `system/` file says Mondays, so "monday" moved to a user-scope `line_absent` (`no-schedule-note`), plus a turn-1 project-write check.
- `forgetting-lapsed-expiry` supplies the "no longer holds" context in the turn, because the prompt says a lapsed fact is not removed automatically. The date-only variant is not ported.
- Not ported, as they need host features: AIE-1052 #3, AIE-1055 #4 and #5, AIE-1165 #1.

## Live run gate: PASSED (after round 2)

Runs: original `evals/runs/aie1185-n3` (N=3), round 1 `evals/runs/aie1185-fix-n6` (N=6), round 2 `evals/runs/aie1185-r2-n6` (N=6); all gitignored. The gate passed on round 2 with the `dropped-without-asking` assertion change above. The command below is the original N=3 plan; the round-1 and round-2 results are recorded under "Live finding and prompt fix".

Original plan, run from the worktree root, one headless session per shard (k = 1 and 2),
then merge. Use `--shard 1/2` in one session and `--shard 2/2` in the
other.

```
CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 claude -p "/run-evals --model sonnet --trials 3 --judge --shard 1/2 applying-no-trait applying-relevant-only curated-observed-conflict filing-second-customer forgetting-ambiguous-that forgetting-lapsed-expiry forgetting-nickname-alias forgetting-system-fact remembering-observed-once slots-system-of-record" --mcp-config evals/mcp.json --strict-mcp-config --allowedTools mcp__wenchang "Bash(uv run python -m evals *)" --settings '{"includeGitInstructions": false}'
uv run python -m evals merge-runs evals/runs/<name> <shard run dirs>
```

- **Live run report: done.** Round-2 run `evals/runs/aie1185-r2-n6` (20 scenarios, N=6); see the round-2 entry under "Live finding and prompt fix".
- **Deterministic floor per scenario: met.** The original floor was 2 of 3 trials at N=3; after the approved assertion change every scenario is 6/6 on deterministic checks in round 2.
- **Miss classification: done.** The `forgetting-clear-named-facts` tool miss is an assertion defect, fixed with the human's approval. The judge misses are third-person noise. Never loosen an assertion to turn a prompt finding into a pass.
- **Third-person judge-noise labels: done.** 8 of 120 round-2 trials have third-person replies. The 4 judge fails on the ambiguous scenarios are labelled noise.
- **`read_file` counts (`applying-relevant-only`, `applying-no-trait`): not recorded separately for round 2.**
- **Verbatim spot-check: not recorded separately for round 2.**
- **Offline regression check (US5.7): done, identical.** Copies of `20261014-225317-sonnet` and `20261014-231845-sonnet-merged` were regraded with this branch's `report` (grade.json removed, `trial.json` pointed at this branch's scenarios). All 23 scenarios in each run have the same per-assertion pass counts as the original `report.json`.

## Look closely at

- The trait regexes: `no-trait-wording` matches only a trait verb about the user, not a line describing the query; `no-trait-written` skips negations, including curly apostrophes.
- `no-catalog-copy`'s known edge: a correction that names the catalog definition only to contrast with it also fails.
- `_grade_is_current`: only reply-kind scenarios treat a newer or deleted transcript, or a grade without the reply check, as a full regrade.
- `grade_trial` loads the transcript once and shares it with the third-person check.
- The Forgetting sentences: the multi-fact confirm rule must not make the guards ask (`forgetting-clear-one-of-several`, `forgetting-clear-whole-after-recall`, `forgetting-clear-named-facts`, `forgetting-whole-file`, `forgetting-only-fact`).
- Cited sentences from `remembering.py`: checked after merging AIE-1182; every citation test passes against the merged prompt.

## Follow-ups

- One issue per prompt finding from the live run.
- Re-check `forgetting-system-fact` and `forgetting-lapsed-expiry` if AIE-1182's role sentence lands.
- Widen the guard hook's rule 4 for `evals/**` (human change).
- The eval agent sometimes writes its question as a report about the user (the residual third-person issue; 8 of 120 round-2 trials).
- Stale aliases after a definition change: the "7-day window" alias is kept.
