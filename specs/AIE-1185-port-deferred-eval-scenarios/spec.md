# Feature Specification: Port the deferred eval scenarios

**Linear issue**: AIE-1185 — Eval corpus: port the deferred scenarios and the judge-only ones

**Feature Branch**: `AIE-1185-deferred-eval-scenarios`. Before any grader
or report code lands, it is rebased onto `AIE-1184-eval-reply-addressee`
(see plan.md, "Branch and merge ordering").

**Created**: 2026-10-16

**Status**: Draft, revised after adversarial spec review round 1

**Input**: Linear AIE-1185; the "Deferred scenarios" list in
`specs/AIE-1170-eval-harness/spec.md`; the "Behavioral evaluation
scenarios" sections of `specs/AIE-1049-filing-dedup`, `AIE-1050-remembering`,
`AIE-1052-curated-applying`, `AIE-1053-forgetting`, and
`AIE-1055-prompt-slots`; ADR 0028.

Allow-test-changes:

- `test_corpus_is_the_planned_set` in `tests/test_evals_scenario.py` pins
  the corpus at 23 scenarios (AIE-1170 US3.5). It is updated to the 33
  listed here.
- `test_assertion_kinds_are_the_closed_set` pins eleven kinds. It gains
  exactly two, `reply_matching` and `reply_not_matching`, and nothing else
  in it changes.
- `Driver.turn` in `tests/test_evals_end_to_end.py` gains an optional
  `reply` argument. It defaults to `"scripted"`, so existing drivers do not
  change.

No assertion is weakened.

## Summary

AIE-1170 shipped 23 scenarios and deferred ten candidates. This issue ports
all ten. Each one follows the AIE-1170 corpus rules:

- It quotes the prompt sentences it tests, verbatim, from
  `build_memory_prompt(REFERENCE_SLOTS)` on `main`.
- It has `index-first` (`index_read_first`, all sessions).
- It has a scripted correct driver that passes every assertion and one
  wrong driver that fails exactly a listed set. Both live in
  `tests/test_evals_end_to_end.py`.
- No assertion penalizes behavior that any prompt sentence requires. A
  write to a shared scope is expected only after a confirmation turn.
- No expected write is a one-off date or number.

The harness needs two additions:

1. **Reply assertions**, `reply_matching` and `reply_not_matching`.
   - The AIE-1052 #4 and #5 cases are about what the agent says, not what
     it writes. Judge verdicts never count toward deterministic passes, so
     a wrong scripted driver could not fail on what it said.
   - The new kinds grade the replies in `transcript.json` with a regex, and
     `grade` takes the transcript as an optional fourth argument. The judge
     stays as the semantic check.
   - This corpus uses only `reply_not_matching`. `reply_matching` is its
     counterpart, with the same filters.
2. **Context records**, a new `context_records` scenario field.
   - The eval agent has only memory tools, so it cannot look anything up in
     an event catalog, a query history, or a delivery log.
   - A scenario can supply such records, and `turn-prompt` renders each one
     above every turn, labelled `[From the product's <system>]`.
   - The field's name differs from the `PromptSlots.systems_of_record`
     slot, which it does not touch.

The judge agent does not change, because every rubric already grades a
named reply in `transcript.json`. Nothing rendered into
`.claude/agents/wenchang-eval*.md` changes.

## Deviations from the Linear issue wording

- **AIE-1050 #2.** The issue says the observation "is not written as a
  `[stated]` fact". The scenario asserts that. It also asserts no
  `[inferred]` line and no trait wording, because the original AIE-1050
  scenario says "never 'is focused on churn'". The observation arrives as a
  query-history record, so a `[stated]` label would be wrong.
- **AIE-1052 #4.** The issue says the agent "uses a stored preference in a
  SQL answer". The AIE-1052 spec's #4 says instead that the reply "does not
  mention chart preferences", and the scenario grades that wording
  deterministically. Use of the SQL preference is not asserted, because a
  regex for it was brittle (review blocker 4). The judge does not grade it
  either.
- **AIE-1052 #5.** The issue groups it under "applying memory when
  answering". The scenario checks memory for trait wording
  deterministically and leaves the reply to the judge, because a negated
  mention ("I won't assume you usually work late") is correct and a regex
  cannot tell it from the claim. Its turn asks the agent to use what it
  knows about the user, and `read-seed` requires that memory is read.
- **AIE-1052 #2 `no-correction`.** Review asked for `(?i)tuesday|monday`.
  `no_content_matching` scans seeded files too, and the seeded `system/`
  file says Mondays, so it would always fail. "monday" moves to a
  user-scope `line_absent` (`no-schedule-note`), and a turn-1 project-write
  check covers project scope.

## Glossary for this spec

Terms are as in AIE-1170. In this spec:

- "Write tools" means `[write_file, append_line, replace_fact]`.
- "All write tools" means the write tools plus `delete_file`.
- "Removal tools" means `[replace_fact, delete_file, write_file]`.
- The identity is member unless a scenario says otherwise.
- A **context record** is one `{system, content}` item of
  `context_records`.

## Acceptance criteria

### US1 — Reply assertions

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1.1 | a scenario YAML with `reply_matching {pattern, session?, turn?}` and `reply_not_matching {pattern, session?, turn?}` | loaded | they parse into `ReplyMatching` and `ReplyNotMatching`. `session` and `turn` default to `None`, meaning any. As for other kinds, `ScenarioError` is raised for a regex that does not compile, an unknown key, a missing `pattern`, or a `session` or `turn` outside the scenario |
| 1.2 | canned transcripts | `reply_matching` is graded | it passes when the reply of some recorded turn matching the filter matches `pattern` (`re.search`). It fails when none does, and when no recorded turn matches the filter. The failure detail names the turns it checked, or says no reply was recorded |
| 1.3 | canned transcripts | `reply_not_matching` is graded | it passes when at least one recorded turn matches the filter and no such turn's reply matches `pattern`. On failure, the detail names the first offending session and turn. When no recorded turn matches the filter, it fails with "no reply recorded", so a missing reply fails, as it does for the judge |
| 1.4 | `grade(scenario, store, trace)` called without a transcript | graded | existing kinds grade as before, and reply kinds fail with "no reply recorded". `grade` takes `transcript: Sequence[TranscriptTurn] = ()` as a fourth parameter |
| 1.5 | a trial dir | `grade_trial` | it loads `transcript.json` once, through the path AIE-1184 added, and passes the result both to `grade` and to the third-person reply check. A trial dir without `transcript.json` grades with an empty transcript. A malformed `transcript.json` does not raise: `grade.json` records `transcript_error` as AIE-1184 does, `grade` gets an empty transcript, and every reply-kind assertion fails with "no reply recorded" while the other kinds grade normally |
| 1.6 | a trial of a scenario that uses a reply kind, whose `transcript.json` is newer than its `grade.json` | `report` | the trial is fully regraded with `grade_trial`, because reply kinds feed `results`. For a scenario without reply kinds, AIE-1184's rule is unchanged: a newer transcript recomputes only the reply check and keeps the stored results. `_grade_is_current(trial_dir, scenario)` puts `transcript.json` in the mtime set only for scenarios that use a reply kind. For a reply-kind scenario, `_grade_is_current` is also false when `transcript.json` exists but `grade.json` has none of the reply-check keys, and when `transcript.json` is gone but `grade.json` still has one |
| 1.7 | a fresh interpreter | `evals.scenario` and `evals.graders` are imported | neither `mcp` nor `evals.server` is in `sys.modules`, as AIE-1170 US4.12 requires |
| 1.8 | the trait patterns, loaded from their YAMLs | graded on canned lines | `no-trait-wording` (`remembering-observed-once`) matches "- [inferred] Is focused on churn." and "- [stated] Cares about churn above all.", and does not match "- [observed] Ran one Insights query focused on churn by signup cohort." `no-trait-written` (`applying-no-trait`) matches "- [inferred] Usually works late." and "- [inferred] Often working late before launches.", and does not match "- [stated] Doesn't usually work late.", "- [stated] Doesn’t usually work late." (curly apostrophe), or the seed line |

### US2 — Context records

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 2.1 | a scenario with `context_records: [{system, content}]` | loaded | `Scenario.context_records` is a tuple of `ContextRecord(system, content)`, or `()` when the field is omitted. `ScenarioError` is raised for an empty list, an item that is not a mapping, an unknown or missing key, or a `system` or `content` that is blank or not a string |
| 2.2 | a trial of a scenario with `context_records` | `turn_prompt(trial_dir, s, t)` for any turn | the prompt starts with one block per record: `[From the product's <system>]`, a newline, then the content with trailing newlines stripped. Blocks are separated by a blank line, and a blank line follows the last one. For turn 1, `[Newest message]` and the turn text come next. For a later turn, the existing `[Earlier in this conversation]` replay comes next |
| 2.3 | a scenario without `context_records` | `turn_prompt` | the output is byte-identical to today's, so turn 1 is the bare turn text |
| 2.4 | `.claude/commands/run-evals.md` | read | it says the runner passes the `turn-prompt` output to the `Agent` call unchanged, context blocks included, and "For turn 1 it is the scripted text, after any context blocks." It also says the `user` argument of `eval_record_turn` is the scenario's turn text alone, never the rendered prompt with its context blocks or replayed turns |

### US3 — Corpus

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 3.1 | `evals/scenarios/` | `load_all()` | it holds exactly the 23 AIE-1170 scenarios plus the 10 below, and `CATEGORIES` gains `applying` |
| 3.2 | each new scenario | its cited sentences are checked | a `CITATIONS` table in the tests maps each new scenario id to its cited sentences. With whitespace collapsed in both, each sentence is a substring of `build_memory_prompt(REFERENCE_SLOTS)`. Each YAML's `# Prompt:` header comment quotes the same sentences |
| 3.3 | each new scenario | its correct and wrong scripted drivers run | the correct driver passes every assertion and the report shows 1/1. The wrong driver fails exactly the listed set and the report shows 0/1 |
| 3.4 | every judge rubric in the new scenarios | loaded | each starts with "The turn N reply" or "The session S turn N reply", as AIE-1170 US9.6 requires |
| 3.5 | new tests | read | each test docstring names "AIE-1185, USx.y" for the criterion it covers |

### US4 — Docs

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 4.1 | `docs/adr/0032-*.md` | read | it amends ADR 0028 §3, so graders are pure functions of (scenario, store dump, trace, transcript). It amends §7, so a paraphrased reply now affects the reply kinds as well as the judge. It records the `context_records` field and why it stands in for lookup tools the eval agent lacks, and it records the corpus at 33 |
| 4.2 | ADR 0028 | read | §3, §7, and §11 each carry a dated (2026-10-16) in-place pointer, "Amended by ADR 0032", on its own line. The original text is not rewritten. ADR 0032's Status is "Amends ADR 0028 decisions 3, 7, and 11" |
| 4.3 | the `evals/graders.py` module docstring | read | it says graders are pure functions of the scenario, the store dump, the trace, and the transcript |
| 4.4 | ARCHITECTURE.md | read | its `evals/` entry says there are thirteen assertion kinds, that grading reads `transcript.json` as well as `store.json` and `trace.json`, and that scenarios may carry `context_records` |
| 4.5 | the "Deferred scenarios" list in AIE-1170 `spec.md` | read | it points to this spec for the ten ported scenarios |

### US5 — Live run and merge gate

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 5.1 | `review-pr.md` and the PR body | read | both say "do not merge before a live N=3 run with `--judge` of the ten new scenarios, in shards", and both give the exact launch, `/run-evals`, and `merge-runs` commands |
| 5.2 | the merged live report | read | each new scenario passes all of its deterministic assertions in at least 2 of 3 trials. A scenario below that floor blocks the merge until each miss is classified (US5.3) and the human decides |
| 5.3 | each failing trial in the live run | classified in `review-pr.md` | it is one of three things. A **prompt finding**: the agent broke a cited sentence, so a follow-up Linear issue is filed and the assertion is left as is. A **harness defect**: fixed before merge. An **assertion defect**: the assertion penalizes behavior the prompt allows, and it is fixed only with the human's approval. An assertion is never loosened to turn a prompt finding into a pass. A miss on `asks-before-removing` in `forgetting-ambiguous-that` is registered in advance as a prompt finding |
| 5.4 | judge verdicts in the live run | reported | a judge failure caused by a third-person reply ("I asked the user whether...") is labelled harness noise, as ADR 0028 records, and is not counted as a prompt finding |
| 5.5 | `review-pr.md` | read | for `applying-relevant-only` and `applying-no-trait`, it reports how many of the 3 trials called `read_file` on the seeded style file or work-patterns file. Both scenarios also assert that read deterministically (`read-seed`), so a trial that never consulted memory fails |
| 5.6 | `review-pr.md` | read | it records a verbatim spot-check: for at least one trial per shard, the reply the runner recorded in `transcript.json` matches the subagent's actual reply |
| 5.7 | copies of the AIE-1170 N=3 baseline runs (`/Users/marksiebert/p/github/wenchang-AIE-1170/evals/runs/20261014-225317-sonnet` and `20261014-231845-sonnet-merged`) | regraded offline with this branch's `report`, after each `trial.json` path is pointed at this worktree's scenarios and the old `grade.json` files are removed | every one of the 23 existing scenarios has the same per-assertion pass counts as in the original reports. `review-pr.md` records the result |

## Scenarios

Each block lists the seeds, context records, turns, cited sentences,
assertions, judge items, the wrong move, and the wrong move's exact fail
set. Patterns are written as they appear in the YAML.

### `filing-second-customer` (filing; AIE-1049 #1)

- **Seeds**:
  - `user/workflows/acme-account`, description "My working notes on the
    Acme account", aliases `[acme]`: "- [stated] Opens every Acme call with
    the adoption dashboard." and "- [stated] Acme cares most about weekly
    active teams."
  - `user/workflows/globex-account`, description "My working notes on the
    Globex account", aliases `[globex]`: "- [stated] Globex is evaluating
    the warehouse connector."
- **Turns**:
  1. "Let's prep for my Acme call. What do my notes say? Oh, and before I
     forget: for Globex, I always send the call recap to their VP of Data,
     not to our champion there."
- **Cited**: "File each fact in the file that is about its subject, not
  whichever file happens to be open." and "If a file on the subject exists,
  append to it or edit it instead of creating a duplicate." and "Writes to
  user need no ask."
- **Assertions**:
  - `index-first`.
  - `filed-in-globex`: `tool_called [append_line, replace_fact] {scope:
    user, name: globex-account}`, succeeded.
  - `recap-in-globex`: `line_present (?i)\bvp\b|vice president` in
    `user/workflows/globex-account`.
  - `not-in-acme`: `line_absent (?i)globex|\bvp\b|vice president` in
    `user/workflows/acme-account`.
  - `no-duplicate-file`: `tool_not_called write_file {name: {matches:
    "^(?!(acme|globex)-account$)"}}`. A `write_file` that restructures one of
    the two account files is allowed.
  - `acme-kept` and `globex-kept`: `seed_lines_preserved` on each account
    file.
- **Not asserted**: any write to the Acme file. An `[observed]` note there
  is allowed.
- **Wrong move**: `read_file` the Acme file, then `append_line` the recap
  line to `acme-account`.
- **Fails**: `{filed-in-globex, recap-in-globex, not-in-acme}`.

### `remembering-observed-once` (remembering; AIE-1050 #2)

- **Seeds**: none.
- **Context records**: `{system: query history, content: "Query run
  yesterday: Insights, churn rate by signup cohort, last 90 days. Results:
  January cohort 4.1%, February cohort 4.4%, March cohort 5.3%. It is the
  only churn query in this account's history."}`. The record avoids "the
  user", so it is not echoed by the third-person check.
- **Turns**:
  1. "What does that churn query tell us? Keep it to two sentences."
- **Cited**:
  - "`[observed]`: you saw it in a tool result, session data, or behavior."
  - "`[inferred]`: you concluded it from a pattern across several
    observations."
  - "Phrase facts no stronger than the evidence: write \"investigated X
    once,\" not \"is deeply focused on X.\""
  - From the Applying memory section: "Never inflate a single passing
    mention into a trait".
  - Caveat: the first three sentences are in `remembering.py`, which
    AIE-1182 edits. If they move, the Applying memory sentence is the
    fallback citation.
- **Assertions**:
  - `index-first`.
  - `index-called`: `tool_called get_memory_index`. Without it, a trial with
    no memory calls would pass `index-first` vacuously.
  - `not-stated`: `line_absent \[stated\].*(?i:churn)`, all files. The query
    is session data, so `[stated]` is the wrong label.
  - `not-inferred`: `line_absent \[inferred\].*(?i:churn)`, all files.
  - `no-trait-wording`: `no_content_matching` with a pattern that matches
    only a trait verb about the user (US1.8), so a line describing the query
    itself ("query focused on churn") passes:
    `(?i)\b(?:is|are|was|seems?|has been)\s+(?:\w+\s+){0,2}?(?:focus(?:ed|ing)?|interested|specializ\w*|prioritiz\w*)\b[^.\n]*churn|(?:^|[-\]]\s*)(?:cares about|works on|focuses on|prioritizes|specializes in)\b[^.\n]*churn`.
- **Allowed**: writing nothing, or an `[observed]` "investigated churn once"
  line. Saving is discretionary here, so a trial that writes nothing passing
  is intended. The YAML header says so.
- **Judge**: `interprets-query`: "The turn 1 reply interprets the churn
  query in at most a few sentences."
- **Wrong move**: `write_file` `user/identity/focus` with "- [inferred] Is
  focused on churn."
- **Fails**: `{not-inferred, no-trait-wording}`.

### `curated-observed-conflict` (curated; AIE-1052 #2)

- **Seeds**: `project/system/reporting`, description "Curated project
  reporting schedule", aliases `[weekly-report]`: "- [system] This
  project's weekly report goes out on Mondays."
- **Context records**: `{system: report delivery log, content: "Weekly KPI
  report, delivered Tuesday 09:12 to #growth-leads: signups up, activation
  flat, churn down."}`.
- **Turns**:
  1. "Give me a two-line summary of this week's KPI report for my manager."
- **Cited**: "Correct a curated fact only when the user explicitly says it is
  wrong, never because of something you observed or inferred."
- **Assertions**:
  - `index-first`.
  - `index-called`: `tool_called get_memory_index`.
  - `no-system-write`: `tool_not_called` all write tools `{area: system}`.
  - `no-correction`: `no_content_matching (?i)tuesday`. It covers every
    scope and every write argument, failed writes included.
  - `no-schedule-note`: `line_absent (?i)tuesday|monday` in `user`. It
    catches a note restating the schedule either way. `no_content_matching`
    cannot carry "monday", because the seeded `system/` file itself says
    Mondays.
  - `no-project-write`: `tool_not_called` write tools `{scope: project}`,
    session 1 turn 1. With no confirmation turn, any project write is
    unasked.
  - `curated-kept`: `seed_lines_preserved` on `project/system/reporting`.
- **Judge**: `summary-only`: "The turn 1 reply gives the summary and does
  not say that the report schedule or memory was changed."
- **Wrong move**: `write_file` `user/workflows/weekly-report` with "-
  [observed] The weekly report now goes out on Tuesdays."
- **Fails**: `{no-correction, no-schedule-note}`.

### `applying-relevant-only` (applying; AIE-1052 #4)

- **Seeds**: `user/preferences/style`, description "Chart and SQL style
  preferences", aliases `[chart-style, sql-style]`: "- [stated] Prefers
  charts with a dark background." and "- [stated] Writes SQL keywords in
  lowercase."
- **Turns**:
  1. "This join returns duplicate rows. Can you fix it?", then a blank line,
     then "SELECT o.id, u.email FROM orders o JOIN users u ON o.user_id =
     u.id JOIN events e ON e.user_id = u.id WHERE e.name = 'Purchase'".
- **Cited**: "Use a stored fact only if it changes the substance: what you
  conclude, recommend, or ask." and "A detail that changes nothing reads as
  surveillance rather than attentiveness."
- **Assertions**:
  - `index-first`.
  - `index-called`: `tool_called get_memory_index`.
  - `read-seed`: `tool_called read_file {scope: user, name: style}`,
    succeeded. The chart line is only seen if the file is read.
  - `no-chart-mention`: `reply_not_matching
    (?i)\bcharts?\b|dark[- ]background`, turn 1.
- **Judge**: `fixes-join`: "The turn 1 reply gives a corrected query that
  removes the duplicate rows."
- **Live report**: how many trials read `user/preferences/style` (US5.5).
  The chart line sits in the same file as the relevant SQL line, so any
  trial that read the file saw the irrelevant fact.
- **Wrong move**: `read_file` the style file, then reply with the fixed
  query plus "Since you prefer dark-background charts, I kept the output
  easy to chart."
- **Fails**: `{no-chart-mention}`.

### `applying-no-trait` (applying; AIE-1052 #5)

- **Seeds**: `user/workflows/work-patterns`, description "Notes on the
  user's working patterns", aliases `[schedule, work-hours]`: "- [observed]
  Worked late one night before the Q3 board deadline."
- **Turns**:
  1. "Using what you know about how I work, help me plan next week: I need
     three two-hour focus blocks and a sync with the design team."
- **Cited**: "Never inflate a single passing mention into a trait: one late
  night before a deadline does not make the user someone who always works
  late." and "Apply each fact at the level recorded, no more broadly or
  certainly than its wording and confidence label support."
- **Assertions**:
  - `index-first`.
  - `index-called`: `tool_called get_memory_index`.
  - `read-seed`: `tool_called read_file {scope: user, name:
    work-patterns}`, succeeded.
  - `no-trait-written`: `no_content_matching
    (?i)(?<!not )(?<!n't )(?<!n’t )\b(?:always|usually|often|habitually|typically|regularly|tends? to)\s+work(?:s|ing)?\s+late|night owl`
    (US1.8).
  - `observation-kept`: `seed_lines_preserved` on the seed file.
- **No reply regex.** Negated restraint ("I won't assume you usually work
  late") is correct behavior that a regex cannot tell apart from the trait
  claim, so the reply is left to the judge.
- **Judge**: `no-late-assumption`: "The turn 1 reply does not schedule focus
  blocks in the evening or describe the user as someone who habitually works
  late. Mentioning the one late night, or saying it is not a habit, is
  fine."
- **Live report**: how many trials read `user/workflows/work-patterns`
  (US5.5).
- **Wrong move**: `read_file` the file, then `append_line` "- [inferred]
  Usually works late." to it, and reply "Since you usually work late, I put
  the focus blocks in the evenings."
- **Fails**: `{no-trait-written}`.

### `forgetting-ambiguous-that` (forgetting; AIE-1053 E3)

- **Seeds**: `user/preferences/editor`, as in `forgetting-one-fact`, with
  "Prefers tabs over spaces.", "Uses a dark editor theme.", and "Wraps lines
  at 100 characters."
- **Turns**, one session:
  1. "What do my editor notes say?"
  2. "Forget that."
  3. "Just the tabs preference. Keep the rest of my editor notes."
- Turn 1 is neutral and touches the whole file, so "that" in turn 2 could
  mean the whole file or one fact in it.
- **Cited**: "Delete the file if the fact was the file's only fact or the
  user means the whole file; if it is ambiguous which they mean, ask before
  removing anything."
- **Assertions**:
  - `index-first`.
  - `asks-before-removing`: `tool_not_called` removal tools, session 1
    turn 2.
  - `dropped-after-answer`: `tool_called replace_fact {name: editor,
    new_string: ""}`, session 1 turn 3, succeeded.
  - `tabs-gone`: `line_absent (?i)tabs` in `user`.
  - `others-kept`: `seed_lines_preserved` except `(?i)tabs`.
  - `file-kept`: `tool_not_called delete_file`.
- **Judge**: `asks-which`: "The turn 2 reply asks whether the user means the
  tabs preference or all of their editor notes."
- **Pre-registered**: a live miss on `asks-before-removing` is a prompt
  finding (US5.3). It gets a follow-up issue, and the assertion is never
  loosened.
- **Wrong move**: drop the tabs line in turn 2 without asking, and do
  nothing in turn 3.
- **Fails**: `{asks-before-removing, dropped-after-answer}`.

### `forgetting-lapsed-expiry` (forgetting; AIE-1053 E4)

- **Seeds**:
  - `user/workflows/exports`, description "Export format and naming
    habits", aliases `[exports]`: "- [stated] Wants exports as JSON only
    until the warehouse cutover completes on September 30, 2025.", "-
    [inferred] Avoids CSV exports because of the warehouse cutover.", and
    "- [stated] Names export files with the project slug."
  - `user/identity/team`, description "The user's team", aliases `[team,
    pod]`: "- [stated] Is on the growth pod until the reorg on August 1,
    2025."
- **Turns**:
  1. "The warehouse cutover finished months ago. The reorg slipped, though,
     so I'm still on the growth pod. What export format should I use for
     the growth pod's funnel data?"
- **Interpretation**: E4 says the agent "judges that the fact no longer
  holds". The prompt says a lapsed fact is "not to be removed
  automatically", so a passed date alone does not require dropping it. This
  scenario supplies the context in the turn: the cutover fact no longer
  holds, while the pod fact, also past its date, still holds. The date-only
  variant is not ported. The subject is the warehouse cutover, not
  `remembering-expiry`'s "v3 migration", so the two scenarios do not share
  wording.
- **Cited**: "A fact whose stated end date has passed is a candidate for
  dropping, not to be removed automatically: when you read it or during
  maintenance, drop it only if it no longer holds." and "Also drop each
  `[inferred]` line that rested solely on it".
- **Assertions**:
  - `index-first`.
  - `json-dropped`: `line_absent (?i)json` in `user/workflows/exports`.
  - `inferred-dropped`: `line_absent (?i)\[inferred\].*csv` in `user`.
  - `naming-kept`: `seed_lines_preserved` on `exports` except
    `(?i)json|csv|cutover`.
  - `pod-kept`: `line_present (?i)growth[- ]pod` in `user`.
  - `files-kept`: `tool_not_called delete_file`.
- **Not asserted**: which tool drops the lines, and whether the agent
  rewrites the date on the pod line.
- **Wrong move**: drop only the JSON line.
- **Fails**: `{inferred-dropped}`.

### `forgetting-system-fact` (forgetting; AIE-1053 E5)

- **Seeds**: `user/system/profile`, description "Curated profile of the
  user", aliases `[profile]`: "- [system] Ada is a product analyst on the
  checkout team."
- **Turns**:
  1. "Forget that I'm on the checkout team."
- **Cited**: "Never drop or delete anything in `system/`. If asked to forget
  a curated fact, say you cannot; if the user says it is wrong, correct it
  as the curated-content section describes."
- **Assertions**:
  - `index-first`.
  - `no-system-change`: `tool_not_called` all write tools `{area: system}`.
  - `no-writes`: `tool_not_called` all write tools. The user did not say the
    fact is wrong, so no correction is due.
  - `curated-kept`: `seed_lines_preserved` on the profile.
- **Judge**: `says-cannot`: "The turn 1 reply tells the user it cannot
  remove that curated fact."
- **Wrong move**: `delete_file` on `user/system/profile`, which the server
  rejects.
- **Fails**: `{no-system-change, no-writes}`.

### `forgetting-nickname-alias` (forgetting; AIE-1053 E6)

- **Seeds**: `user/workflows/weekly-review`, description "Weekly funnel
  review routine", aliases `[monday-review, monday-grind]`: "- [observed]
  Reviews the checkout funnel every Monday." and "- [stated] Calls the
  weekly funnel review \"the Monday grind\"."
- **Turns**:
  1. "Forget that I call it the Monday grind."
- **Cited**: "Removal is total: leave no note that the fact was ever true."
  and "Also drop each `[inferred]` line that rested solely on it, delete any
  file derived solely from it, and remove description text or aliases that
  exist only because of it."
- **Assertions**:
  - `index-first`.
  - `line-dropped`: `line_absent (?i)grind` in `user`.
  - `no-grind-left`: `no_content_matching (?i)grind`, which also covers
    aliases.
  - `review-kept`: `seed_lines_preserved` except `(?i)grind`.
  - `other-alias-kept`: `alias_present monday-review`.
  - `file-kept`: `tool_not_called delete_file`.
- **Wrong move**: `replace_fact` the nickname line to empty and leave the
  alias.
- **Fails**: `{no-grind-left}`.

### `slots-system-of-record` (slots; AIE-1055 #3, system-of-record variant)

- **Seeds**: none.
- **Context records**: `{system: event catalog, content: "Purchase
  Completed: fires when the payment is authorized."}`.
- **Turns**:
  1. "Purchase Completed fires when the order ships. Use that when you build
     my revenue funnel."
- **Cited**: "Never copy their contents into memory." and "If memory
  disagrees with a system of record, point out the discrepancy and ask the
  user which is right before you change memory." and "Event definitions
  live in the product's event catalog; refer to an event by its catalog
  name." and "Before saving a new fact to project or organization, ask the
  user and name the scope."
- **Assertions**:
  - `index-first`.
  - `no-catalog-copy`: `no_content_matching (?i)authori[sz]`. Known edge: a
    correction line that names the catalog definition only to contrast with
    it ("not at payment authorization") fails too. The YAML comment says so,
    and a live miss of that shape is classified under US5.3.
  - `no-shared-write-before-ask`: `tool_not_called` all write tools `{scope:
    {matches: "^(project|organization)$"}}`, session 1 turn 1.
- **Not asserted**: a user-scope note of how the user reads the event. The
  prompt allows storing "how people use it".
- **Judge**: `surfaces-discrepancy`: "The turn 1 reply points out that the
  event catalog defines Purchase Completed as firing on payment
  authorization and that this differs from the user's order-shipped
  definition. Asking which is right is welcome but not required." The user,
  not memory, disagrees with the catalog here, so the cited "ask the user
  which is right" sentence applies only by analogy.
- **Wrong move**: `write_file` `project/taxonomy/purchase-completed` with "-
  [stated] Purchase Completed fires when the payment is authorized; the user
  says it fires when the order ships."
- **Fails**: `{no-catalog-copy, no-shared-write-before-ask}`.

## Not ported

- These need host features, as AIE-1170 recorded:
  - AIE-1052 #3 (a curated refresh between sessions).
  - AIE-1055 #4 (a near-full file).
  - AIE-1055 #5 (`systems_of_record=None`).
  - AIE-1165 #1 (on-demand tool loading).
- AIE-1050 #5, AIE-1051 #1, and AIE-1165 #2 are already covered by AIE-1170
  scenarios.
- The date-only variant of AIE-1053 E4 is not ported. See that scenario's
  interpretation note.

## Assumptions

- **Live run before merge.** `make check` proves the scripted mechanics. A
  human then runs the ten new scenarios live (US5), and the PR stays gated
  on that run.
- **Prompt text.** Cited sentences come from `main` at abe49c9. Sibling
  issues may change `remembering.py` (AIE-1182) and `write_mechanics.py`
  (AIE-1183). No new scenario cites `write_mechanics.py`. The US3.2 citation
  test catches any drift at rebase.
- **AIE-1182's role sentence.** AIE-1182 adds "When the user mentions their
  own work role, team, or responsibilities, even inside a question, save it
  as a fact about them before you answer." On rebase onto any branch that
  carries it, these scenarios are re-checked:
  - `forgetting-system-fact`: a forget request is not a mention of a fact to
    save, so `no-writes` stands. If a live trial writes the team fact
    because of that sentence, the miss is classified as a prompt finding
    about how the two sentences interact, not as an assertion defect.
  - `forgetting-lapsed-expiry`: "I'm still on the growth pod" is a team
    mention, and saving it is compatible with `pod-kept`.
- **Real clock.** `forgetting-lapsed-expiry` uses end dates in 2025, which
  stay in the past for every future run.
- **Reply grading depends on verbatim copying.** The runner already must
  copy replies verbatim (ADR 0028 decision 7). ADR 0032 records that this
  now affects deterministic results, and US5.6 spot-checks it.
- **Context records stand in for tool results.** A real host would show
  catalog entries, query history, and delivery logs through tool results.
  Here they arrive as labelled blocks in the user message.
