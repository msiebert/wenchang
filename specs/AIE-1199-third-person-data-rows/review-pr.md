# PR Review: AIE-1199 — Third-person reply check skips data uses of "the user"

## What changed & why

The eval reply check (ADR 0031) flagged "the user" where it names a data row or product vocabulary ("whether the user has at least one Purchase event" in an SQL fix, "the user ID", "the user property", "the user taps"). That inflated the third-person counts in the AIE-1182 and AIE-1185 runs. The grader now skips those uses and `build_report` recomputes the check of every current trial, so old runs pick up the fix. Pass counts never change.

Design (all in `evals/graders.py` and `evals/report.py`):

1. **SQL turns.** A turn is an SQL turn if its reply or any user text of the session up to that turn holds an SQL statement. There, "the user" + data verb (has, is, who, ...) is skipped, unless an addressee word precedes it ("ask the user") or a speech verb follows ("the user has asked"). Linear-time scan.
2. **Vocabulary, any turn.** "the user" + data noun (id, profile, property, ...) or interface verb (taps, clicks, ...) is not a match.
3. **Re-report.** `build_report` recomputes the check of every current `grade.json` whose transcript exists and rewrites it only when the check fields changed.

## Acceptance criteria → tests

Grader tests are in `tests/test_evals_graders.py` (`test_reply_check_*`), report tests in `tests/test_evals_report.py`.

| Acceptance criterion | Test(s) |
| -------------------- | ------- |
| US1.1, US1.2 verbatim AIE-1185 trials 1 and 3 not flagged | `skips_a_data_row_in_the_applying_trial_1`, `..._trial_3` |
| US1.3, US1.4 SQL in the reply (fenced or unfenced) makes an SQL turn | `sql_in_a_fenced_reply_makes_an_sql_turn`, `sql_in_an_unfenced_reply_makes_an_sql_turn` |
| US1.5 SQL in an earlier user turn covers later turns | `sql_in_an_earlier_turn_makes_later_turns_sql` |
| US1.6 every data verb exempt in an SQL turn | `every_data_verb_is_exempt_in_an_sql_turn` |
| US1.7 data nouns from the AIE-1182 run, every noun, separators | `skips_data_nouns_from_the_aie_1182_run`, `every_data_noun_is_exempt`, `data_noun_separators`, `a_newline_is_not_a_vocabulary_separator` |
| US1.8 interface verbs, list coverage, verbs left out still flagged | `skips_an_interface_verb_from_the_aie_1182_run`, `every_interface_verb_is_exempt`, `flags_verbs_left_out_of_the_interface_list` |
| US1.9 vocabulary applies in SQL turns; possessive and caller unchanged | `vocabulary_applies_in_an_sql_turn`, `flags_a_possessive_before_a_data_noun`, `vocabulary_never_exempts_the_caller` |
| US2.1 existing reply-check tests unchanged | existing suite |
| US2.2 the 8 AIE-1184 true positives still flagged | `still_flags_the_true_positives` |
| US2.3 non-data uses in an SQL turn flagged | `sql_turn_still_flags_non_data_uses` |
| US2.4 data verb then speech verb flagged | `sql_turn_flags_a_data_verb_before_a_speech_verb` |
| US2.5 one flag, first non-exempt match | `sql_turn_flags_once_with_the_first_non_exempt_match` |
| US2.6 data verb without SQL flagged | `flags_a_data_verb_without_sql` |
| US2.7 prose is not an SQL turn | `prose_is_not_an_sql_turn` |
| US2.8, US2.9 SQL in another session or a later turn does not count | `sql_in_another_session_does_not_count`, `sql_in_a_later_turn_does_not_count` |
| US2.10 "the caller" never exempt | `the_caller_is_never_exempt` |
| US2.11 look-ahead edges and punctuation | `sql_turn_lookahead_edges`, `sql_turn_punctuation_ends_the_lookahead` |
| US2.12 every addressee word, adverb, speech verb | `every_addressee_word_blocks_the_exemption`, `curly_apostrophe_addressee_blocks_the_exemption`, `every_adverb_is_skipped_before_a_speech_verb`, `every_speech_verb_after_a_data_verb_is_flagged` |
| US2.13 200,000-character `select ` run is fast | `long_select_run_is_checked_quickly` |
| US3.1 stale recorded check replaced, results and passed kept | `test_report_replaces_a_stale_check_of_a_current_grade` |
| US3.2 unchanged check not rewritten | `test_report_leaves_a_current_check_alone` |
| US4.1 limit (transcript_error rewrite): recorded `transcript_error` replaced once transcript is valid | `test_report_replaces_a_recorded_transcript_error_once_the_transcript_is_valid` |
| US3.3 to US3.6 re-report of copies | manual, see counts below |

## Trial classification (manual review)

| Run | Flags | True | False |
| --- | ----- | ---- | ----- |
| AIE-1184 N=6 | 8 | 8 | 0 |
| AIE-1185 N=3 | 2 | 0 | 2 |
| AIE-1182 N=6 | 12 | 6 | 6 |
| AIE-1183 N=6 | 6 | 6 | 0 |

The 10 flags in AIE-1184 plus AIE-1185 and the 18 in AIE-1182 plus AIE-1183 all reviewed by hand.

## Re-report counts

`cp -Rp` copies; originals unchanged by file hash; `trials_run`, `passed_trials`, `assertions`, and `judge` identical to the originals. The AIE-1184 copy was re-reported from this branch (main contains AIE-1184) with scenario paths left at the AIE-1184 worktree. The AIE-1182, AIE-1183, and AIE-1185 copies were re-reported on scratch worktrees at their run commits (7eb3894, c0f6a66, 58425a1) with this evals diff applied and scenario paths pinned there (AIE-1183's scenarios gained assertions after its run).

| Run | Before | After |
| --- | ------ | ----- |
| AIE-1184 `aie1184-n6` | 8/138 | 8/138 |
| AIE-1185 `aie1185-n3` | 2/30 | 0/30 |
| AIE-1182 `aie1182-n6` | 12/168 | 6/168 |
| AIE-1183 `aie1183-n6` | 6/168 | 6/168 |
| Total | 28 | 20 |

All 8 removed flags are false positives; no true positive removed, no new flag.

## Architecture / ADR changes

- Amendment to `docs/adr/0031-reply-addressee-check.md` (SQL-turn rule, vocabulary rule, re-report rule replacing the "older than the transcript" refresh, limits).
- `ARCHITECTURE.md`: no change; it does not state the match or refresh rules.

## Deviations from spec

- None. The spec was amended after code review (see history).

## Look closely at

- The SQL-statement recognizer in `evals/graders.py`: regexes must stay linear and not fire on prose.
- The exemption boundaries: addressee words before, speech verbs after (one adverb or "been", whitespace only).
- `_refresh_reply_check` in `evals/report.py`: writes only when check fields change; never touches `results` or `passed`.
- Known misses (ADR limits): "the user has a draft" in an SQL turn.

## Review history

- Spec review: 3 rounds, all findings addressed.
- Code review A: found a quadratic SQL scan and prose that made false SQL turns. Fixed.
- Code review B: found list coverage gaps and an addressee-word mismatch. Fixed.

## Follow-ups

- Merge note: AIE-1185 PR #40 also edits `_refresh_reply_check` in `evals/report.py`. Whichever merges second rebases; the resolution is to compute `fresh = _reply_check(trial_dir, scenario, *_load_transcript(trial_dir))`.
- A transcript_error naming an absolute path is rewritten once after a run dir is copied.
