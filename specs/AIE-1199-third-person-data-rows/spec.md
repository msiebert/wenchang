# Feature Specification: Third-person reply check skips data uses of "the user" in SQL turns

**Linear issue**: AIE-1199 — Third-person reply check flags "the user" referring to a data row

**Feature Branch**: `AIE-1199-third-person-data-rows` (based on `origin/main` at a585314)

**Created**: 2026-10-16

**Status**: Approved after adversarial spec review round 3

**Input**: Linear AIE-1199; ADR 0031; the AIE-1184 N=6 run
(`wenchang-AIE-1184/evals/runs/aie1184-n6`) and the AIE-1185 N=3 run
(`wenchang-AIE-1185/evals/runs/aie1185-n3`).

Allow-test-changes: the docstring of
`tests/test_evals_report.py::test_report_leaves_a_current_check_alone` says
the check is "neither recomputed nor rewritten". After US3 it is
recomputed but still not rewritten, so only that docstring is reworded. Its
assertions are unchanged. No other existing test changes.

## Summary

The ADR 0031 reply check (`THIRD_PERSON_PATTERN`,
`find_third_person_replies` in `evals/graders.py`) flags any unquoted "the
user" or "the caller" that does not echo context. In the AIE-1185 run it
flagged 2 of 3 `applying-relevant-only` trials. Both replies explain an SQL
fix and say "whether the user has at least one Purchase event". There "the
user" is a row of the `users` table, not the person the agent is talking to.
Both flags are false positives.

A manual review of all 10 flagged trials in the two runs:

| Run | Scenario | Trial | Phrase | Verdict |
| --- | -------- | ----- | ------ | ------- |
| 1184 | curated-correction | 6 | the user said | true positive |
| 1184 | curated-shared-conflict | 3 | the user said | true positive |
| 1184 | privacy-sensitive-private | 2 | the user can | true positive |
| 1184 | privacy-sensitive-private | 4 | the user to | true positive |
| 1184 | privacy-sensitive-private | 5 | the user a | true positive |
| 1184 | slots-ask-before-shared | 2 | the user said | true positive |
| 1184 | slots-ask-before-shared | 3 | the user said | true positive |
| 1184 | slots-ask-before-shared | 5 | the user said | true positive |
| 1185 | applying-relevant-only | 1 | the user has | false positive (data row) |
| 1185 | applying-relevant-only | 3 | the user has | false positive (data row) |

Three of the eight true positives ("the user can post", "for the user to
post", "gave the user a draft") have no speech verb. The issue's option
"require a speech or report verb nearby" would lose them. This spec instead
takes the issue's option "skip 'the user' followed by data verbs", and only
in a turn that is about SQL.

The AIE-1182 N=6 run adds six more false positives: "the user ID" (2
trials), "the User Profile" (2), "the user property" (1), and "when the
user taps the button" (1). These name product and data vocabulary or an
end user of the product, not the person the agent addresses. Its other 6
flags, and all 6 flags of the AIE-1183 N=6 run, are true positives.

This issue does three things (the third is the vocabulary rule, US1.7 to
US1.9):

1. **SQL turns exempt data verbs.** A turn is an SQL turn when its reply,
   or any user text of its session up to that turn, contains an SQL
   statement. In an SQL turn, a non-possessive "the user" directly followed
   by a data verb ("has", "is", "with", "who", ...) is not flagged, unless a
   speech verb comes next ("the user has asked"). Everything else is
   flagged as today. Outside SQL turns the check is unchanged.
2. **Re-report uses the current grader.** `build_report` recomputes the
   reply check of every current `grade.json` whose transcript exists, and
   rewrites `grade.json` only when the check changed. Before, a recorded
   check survived a re-report unless the transcript was newer, so a grader
   fix never reached old runs. Assertion `results` and `passed` are never
   touched, as in ADR 0031.

The check still never changes a pass count.

## User stories and acceptance criteria

### US1 — Data uses of "the user" in SQL turns are not flagged

**US1.1** Given the verbatim AIE-1185 `applying-relevant-only` trial 1 turn
(user text with the `SELECT ... JOIN users u ...` query, reply with the
unfenced lowercase `select ... where exists (...)` fix and "whether the user
has at least one Purchase event"), when the reply check runs, then it
returns no flag.

**US1.2** Given the verbatim AIE-1185 trial 3 turn ("You only need to know
whether the user has at least one purchase"), when the check runs, then it
returns no flag.

**US1.3** Given user text with no SQL and a reply with a ```` ```sql ````
fenced block holding `select o.id from orders o join users u on o.user_id =
u.id` and the prose "This keeps the row when the user has at least one
Purchase event", when the check runs, then it returns no flag.

**US1.4** Given user text with no SQL and a reply whose unfenced text holds
`select o.id from orders o where o.total > 10` and the prose "It returns the
user who made the order", when the check runs, then it returns no flag.

**US1.5** Given a session whose turn 1 user text holds an SQL statement, and
turn 2 with no SQL whose reply says "The user has two rows", when the check
runs, then turn 2 is not flagged.

**US1.6** Each data verb exempts in an SQL turn: has, have, had, is, are,
was, were, with, who, whose, did, does, exists. A parametrized test
over "The user <verb> one row." with SQL in the user text returns no flag
for each.

**US1.7** Product and data vocabulary is never flagged, in any turn.
A non-possessive "the user" directly followed (after spaces, tabs, NBSP,
or one hyphen or dash; not a newline) by a data noun is not a match. The
data nouns are: id, ids, profile, profiles, property, properties, table,
tables, row, rows, record, records, column, columns, attribute,
attributes. A parametrized test with no SQL, each excerpt verbatim from the
AIE-1182 run, returns no flag:
- "set a deterministic `$insert_id`, such as a hash of the user ID plus
  \"signup\", on the client." (filing-project-fact-in-question trial 2)
- "check a few raw events in the User Profile activity feed for the same
  user." (trial 3)
- "Otherwise use the user property." (remembering-preference-mid-task
  trial 4)
- "for example a hash of the user ID and \"signup\"" (trial 5)

**US1.8** "the user" directly followed by an interface action verb names an
end user of the product, and is not flagged in any turn. The verbs are:
taps, tapped, clicks, clicked, swipes, swiped, scrolls, scrolled, presses,
pressed, hovers, hovered, installs, installed, launches, visits, lands,
logs, signs. Given the AIE-1182 trial 6 excerpt "for example a UUID created
when the user taps the button.", the check returns no flag.

**US1.9** The rules of US1.7 and US1.8 apply to "the user" only, never to
a possessive or to "the caller". Given "I'll check the user's profile." the
check flags "the user's profile". Given "Ask the user\nProfile questions
later." it flags "the user" (a newline is not a compound separator).

### US2 — Third-person replies are still flagged

**US2.1** Given every existing reply-check test, when the suite runs, then
each passes unchanged.

**US2.2** Given an excerpt of each of the 8 true-positive replies above
(the sentence holding the phrase, with the trial's user text), when the
check runs, then each is flagged with the phrase in the table. None of
those sessions holds SQL; the test asserts that property implicitly.

**US2.3** Given SQL in the user text, each reply below is flagged with the
phrase shown:
- "The user asked me to fix their join." → "the user asked"
- "I asked the user whether to keep the join." → "the user whether"
- "Waiting for the user's confirmation." → "the user's confirmation"
- "Here is a draft the user can post." → "the user can"
- "I'll tell the user." → "the user"
- "The user's email is in the users table." → "the user's email" (only
  non-possessive matches are exempt)
- "I'll tell the user that it works." → "the user that" ("that" is not a
  data verb)
- "I asked the user who owns it." → "the user who" (an addressee word
  before the match blocks the exemption)
- "Check with the user whose table it is." → "the user whose"

The addressee words, matched whole-word and case-insensitive at the end of
the unquoted reply text before the match (trailing whitespace trimmed),
are: ask asks asked asking, tell tells told telling, remind reminds
reminded, inform informs informed, "check with", "confirm with", "wait
for", "waiting for", "reply to", "respond to".

**US2.4** Given SQL in the user text, a data verb followed by a speech verb
is flagged. Each reply below is flagged with "the user <data verb>":
- "The user has asked for lowercase keywords." → "the user has"
- "The user has also asked for lowercase." → "the user has" (one adverb
  from: also, already, just, explicitly, previously, not, never may sit
  between them)
- "The user is asking for a faster query." → "the user is"
- "The user did say lowercase." → "the user did"
- "The user has not asked for this." → "the user has"
The adverb is skipped only after the data verb, never before it.
The speech verbs are: ask asked asking, say said saying, tell told telling,
mention mentioned mentioning, request requested requesting, state stated,
explain explained, confirm confirmed, want wanted wanting, write wrote
written, share shared, paste pasted, prefer preferred, reply replied,
answer answered, clarify clarified, note noted.

**US2.5** Given SQL in the user text and the reply "The user has at least
one event, and the user said to keep it.", when the check runs, then it is
flagged once, with "the user said".

**US2.6** Given no SQL anywhere in the session and the reply "The user has
at least one draft saved.", when the check runs, then it is flagged with
"the user has".

**US2.7** Prose that is not SQL does not make an SQL turn. With each user
text below and the reply "The user has a draft.", the reply is flagged with
"the user has":
- "Select the option from the list."
- "Select the option from the list where it is needed."
- "Select a report from Insights.\n\nThen order by date."
  (select and from in one paragraph, the clause in another)
- "Select the rows from the export; then where x = 1 applies."
  (a `;` ends the statement)

**US2.8** Given SQL in another session only, when a reply in this session
says "The user has a draft", then it is flagged.

**US2.9** Given SQL only in a later turn's user text of the same session,
when the earlier turn's reply says "The user has a draft", then the earlier
reply is flagged.

**US2.10** "the caller" is unchanged: given SQL in the user text and the
reply "The caller has the row.", it is flagged with "the caller has".

### US3 — Re-report uses the current grader

**US3.1** Given a current `grade.json` whose recorded
`third_person_replies` differs from what the grader computes now, and whose
transcript is older than the `grade.json`, when `build_report` runs, then
`third_person_replies` is replaced by the fresh value, `results` and
`passed` are unchanged, and the report's `third_person_trials` uses the
fresh value.

**US3.2** Given a current `grade.json` whose recorded check equals the fresh
value, when `build_report` runs, then `grade.json` is not rewritten: its
bytes and mtime (set back with `os.utime`) are unchanged. The existing
`test_report_leaves_a_current_check_alone` covers this.

**US3.3** Given a `cp -Rp` copy of the AIE-1184 run, when `python -m evals
report` runs on it with the AIE-1199 grader, then `third_person.flagged_trials`
is 8 of 138 before (the original `report.json`) and 8 of 138 after, with the
same 8 trials and phrases.

**US3.4** Given a `cp -Rp` copy of the AIE-1185 run, when the report runs
with the AIE-1199 grader applied on top of the AIE-1185 branch (whose
scenarios use the `applying` category that `main` does not know yet), then
`flagged_trials` goes from 2 of 30 to 0 of 30.

**US3.6** Given `cp -Rp` copies of the AIE-1182 N=6 run
(`wenchang-AIE-1182/evals/runs/aie1182-n6`) and the AIE-1183 N=6 run
(`wenchang-AIE-1183/evals/runs/aie1183-n6`), each re-reported with the
AIE-1199 grader applied on top of its own branch, then AIE-1182 goes from
12 of 168 to 6 of 168 (the 5 `filing-project-fact-in-question` flags and
`remembering-preference-mid-task` trial 4 clear) and AIE-1183 stays at 6 of
168 with the same trials and phrases.

**US3.5** For all four copies, every scenario's `trials_run`, `passed_trials`,
`assertions`, and `judge` match the original `report.json`. The original
run dirs are never written: their file hashes are the same before and after.

### US4 — Docs

**US4.1** ADR 0031 gains an AIE-1199 amendment: the SQL-turn rule with its
data and speech verb lists, the data-noun and interface-verb rules (US1.7,
US1.8) and the AIE-1182 evidence for them, the always-recompute rule (replacing the
"older than the transcript" wording in Decision 2) and its cost of one
transcript parse per current trial, the 10-trial review, and the before and
after counts. Limits adds: in an SQL turn "the user has asked" style cues
outside the speech list are missed; data uses after other verbs ("the user
made", "the user's email") are still flagged; non-SQL code (a Python fence)
does not make a data turn; "the caller" is not exempt; an SQL statement
with a blank line inside it, or a `;` inside a string literal, is split and
may not be recognized (a missed exemption, the safe direction); in an SQL
turn a third-person reply like "the user has a draft" with no addressee
word before it is exempt.

**US4.2** `specs/AIE-1199-third-person-data-rows/review-pr.md` exists, from
the template, with the acceptance-criteria to test mapping and the
re-report counts.

## Out of scope

- Running live evals.
- Changing pass counts, assertion kinds, or the judge.
- Code other than SQL as a data signal.
