# Spec Review: AIE-1199 — Third-person reply check skips data uses of "the user" in SQL turns

## What & why

The eval reply check flags any unquoted "the user" in an agent reply, to catch the agent talking about its own conversation partner in the third person. In the AIE-1185 run it wrongly flagged 2 of 3 `applying-relevant-only` trials: both explain an SQL fix ("whether the user has at least one Purchase event"), where "the user" is a row of a `users` table. This change exempts data uses in SQL turns only, and makes `build_report` recompute every current trial's check so a grader fix reaches old runs. Pass counts never change.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| US1.1 | Verbatim AIE-1185 trial 1 turn (SQL in user text, unfenced lowercase `select ... where exists`, "the user has at least one Purchase event") | check runs | no flag |
| US1.2 | Verbatim AIE-1185 trial 3 turn | check runs | no flag |
| US1.3 | No SQL in user text; reply has a fenced `sql` join and "the user has at least one Purchase event" | check runs | no flag |
| US1.4 | No SQL in user text; reply has unfenced `select ... where o.total > 10` and "the user who made the order" | check runs | no flag |
| US1.5 | SQL in turn 1 user text; turn 2 reply "The user has two rows" | check runs | turn 2 not flagged |
| US1.7 to US1.9 | Any turn; data nouns (id, profile, property, table, row, record, column, attribute) and interface verbs (taps, clicks, ...) after "the user", from the AIE-1182 run | check runs | never flagged; possessives and "the caller" unchanged |
| US2.2 | The 8 true-positive replies from the AIE-1184 run (none holds SQL) | check runs | each flagged with its phrase |
| US2.3 | SQL present; "The user asked me...", "I asked the user who owns it", "the user's email", "the user that" | check runs | each flagged |
| US2.4 | SQL present; "The user has asked...", "has also asked", "is asking", "did say" | check runs | flagged as "the user <data verb>" |
| US2.5 | SQL present; "The user has at least one event, and the user said to keep it." | check runs | one flag, "the user said" |
| US2.6 | No SQL anywhere; "The user has at least one draft saved." | check runs | flagged |
| US2.7 | Prose that reads like SQL (select/from/where, insert into, create table of contents) | check runs | not an SQL turn; flagged |
| US3.1 | Current `grade.json` whose recorded check differs from the fresh one, transcript older | `build_report` runs | check replaced; `results` and `passed` unchanged; report uses fresh value |
| US3.3 | `cp -Rp` copy of the AIE-1184 run | report runs with new grader | 8 of 138 flagged before and after, same trials and phrases |
| US3.4 | `cp -Rp` copy of the AIE-1185 run (grader applied on the AIE-1185 branch) | report runs | 2 of 30 becomes 0 of 30 |
| US3.6 | `cp -Rp` copies of the AIE-1182 and AIE-1183 N=6 runs, each with the grader on its own branch | report runs | AIE-1182 goes from 12 of 168 to 6 of 168; AIE-1183 stays at 6 of 168 |
| US3.5 | Both copies | report runs | `trials_run`, `passed_trials`, `assertions`, `judge` match the originals; original run dirs unwritten (hashes equal) |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| Exempt "the user" + data verb, only in SQL turns, unless a speech verb follows | Require a speech verb nearby everywhere | Loses 3 of the 8 true positives, which have no speech verb ("the user can post", "for the user to post", "gave the user a draft") |
| Scope the exemption to SQL turns (reply or any user text up to that turn holds an SQL statement) | Skip everything near SQL | Loses "the user asked" in SQL turns; the data-verb plus speech-verb rule keeps it |
| Fixed lists (data verb, speech verb, addressee word, adverb) for SQL turns; a data-noun and interface-verb vocabulary rule for any turn | Cue families | Each list is bounded by the evidence from the reviewed AIE-1182/1184/1185 trials; "group by"/"order by" are not SQL markers (prose) |
| Recompute the check of every current `grade.json` whose transcript exists; rewrite only when the check fields changed | Keep stale recorded checks unless the transcript is newer | Grader fixes would never reach old runs |

## Files/modules to be touched

- `evals/graders.py`: `_has_sql`, verb sets, exemption in `find_third_person_replies`.
- `evals/report.py`: `_refresh_reply_check`.
- `tests/test_evals_graders.py`, `tests/test_evals_report.py`: new tests; one docstring reworded in `test_report_leaves_a_current_check_alone`.
- `docs/adr/0031-reply-addressee-check.md`: AIE-1199 amendment.
- `specs/AIE-1199-third-person-data-rows/review-pr.md`.

## Open questions / assumptions

- None blocking.
- AIE-1185 (PR #40) also edits `evals/report.py` `_refresh_reply_check`; whichever merges second rebases.
- US3.4 needs the AIE-1185 branch's scenarios (the `applying` category is unknown to `main`), so that check runs from a scratch worktree with this diff applied.

## Risks

- A third-person reply like "the user has a draft" in an SQL turn, with no addressee word before it, is exempt (a missed flag).
- SQL with a blank line inside, or a `;` in a string literal, is split and may not be recognized (a missed exemption, the safe direction).
- Always-recompute costs one transcript parse per current trial on every report.
- Heuristic SQL detection could misfire on unusual prose; US2.7 pins the known cases.
- A data noun or interface verb used of the addressee is missed (vocabulary rule applies in every turn).
