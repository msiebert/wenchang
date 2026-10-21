# Feature Specification: Quote the tool's path when saying where something is stored, and check reply paths against the trace

**Linear issue**: AIE-1198
**Branch**: `AIE-1198-reply-paths`
**Created**: 2026-10-19
**Status**: Draft (revised after adversarial spec and generality review)

## Problem

In the AIE-1184 N=6 run (`wenchang-AIE-1184/evals/runs/aie1184-n6`),
`remembering-no-metric-value` trials 1 and 4 told the user they saved to
`project/metrics/dau.md`; the file is `project/p-checkout/metrics/dau.md`.
Trial 5 said `project/metrics/daily-active-users.md` for the same `dau.md`.

Cause: the tools take `(scope, area, name)` and return the full
entity-qualified `path`. The prompt never says how to name a stored location.
The only instruction is "Then tell the user where you saved it" in
`curated_content.BODY`, for corrections. So the agent rebuilds a path from its
own arguments. Nothing grades this: the only check is the
`curated-correction` judge item `says-where-saved`, which passes a wrong
path.

A scratch scan of the four historical N=6 runs found rebuilt paths across the
corpus, not in one scenario: `user/preferences/editor`,
`user/workflows/board-deck`, `project/entities/checkout-redesign`,
`organization/system/fiscal-calendar`. US2.9 measures the shipped check.

## Goal

1. **Prompt.** One general sentence in `overview.BODY` (section "Memory",
   which already defines addressing by scope, area, and name), as its second
   sentence, wrapped at 100 columns:

   > When you tell the user where something is stored, quote the full `path`
   > a tool returned for it; never rebuild one from its scope, area, and name.

   It names no fact, scope, area, file, or scenario. It is conditional, so it
   asks for no path where none is needed, and before a write no tool has
   returned a path, so a proposal names the scope as the Scopes rule already
   says.
2. **Harness.** A reply-path check modeled on the third-person reply check
   (ADR 0031): extract scope-rooted path tokens from each reply and flag any
   that matches no path or prefix the trial's tool results returned up to
   that turn. Recorded in `grade.json` and the report apart from pass
   counts; never changes `results` or `passed`. New ADR 0033.
3. **Tool output is unchanged.** The full path is consistent across
   `get_memory_index`, `list_prefix`, `read_file`, and the writes.

Rejected:
- Returning a shorter path from the tools: `path` is the stable address in
  every result and in the index; changing it is a storage/API change for an
  eval symptom.
- A sentence in `curated_content.BODY`: that section covers corrections only;
  the failure happens on any save or recall.
- A new assertion kind: like ADR 0031, opt-in per scenario, and it would move
  pass counts of every existing scenario at once.
- Tightening the `curated-correction` judge item: breaks judge comparability
  with every baseline. The held-outs and the check cover it.
- Stripping fenced code and quotes before extraction (as the third-person
  check does): a path in backticks or a fence is still a claim about where
  something is.

## Acceptance criteria

### US1 — Prompt sentence

- **1.1** Given `wenchang.prompts.overview.BODY` whitespace-flattened, then it
  contains the Goal 1 sentence verbatim, as its second sentence.
- **1.2** Given the sentence, then it contains no backtick other than
  `` `path` ``, and none of the scenario area or file names (a test checks
  `metrics`, `dau`, `preferences`, `workflows`, `vocabulary`, `glossary`,
  `conventions`). Existing invariants still pass: ASCII, 100 columns, 2500
  characters, no `.md`, no "entity", no organization/project.
- **1.3** Every existing test in `tests/test_prompts_overview.py` passes
  unchanged.
- **1.4** Given `build_memory_prompt(REFERENCE_SLOTS)`, then the "Memory"
  section contains the sentence.
- **1.5** `.claude/agents/wenchang-eval.md` equals
  `evals.agent.render_agent_file()` after `uv run python -m evals
  render-agent` (run with the worktree as cwd), and its sha256 is recorded
  in review-pr.md.

### US2 — Reply-path check

`evals.graders.find_unmatched_reply_paths(scenario, trace, transcript)` is
pure, imports no `mcp`, and returns one `UnmatchedReplyPath(session, turn,
token, kind)` per distinct unmatched token per reply, in the transcript's
given turn order, then by first appearance in the reply.

- **2.1 Roots.** A token is extracted only if it has a segment equal to a
  root: `evals.reference_adopter.REFERENCE_SCOPES` (`user`, `project`,
  `organization`), the scenario identity's grant keys, `org`, and `system`
  (an area every scope has). Case-sensitive. The grant-key test builds a
  custom `Identity`, since `member` and `admin` grant only the reference
  scopes.
- **2.2 Tokens.** A token is a maximal run of `[A-Za-z0-9_.~/-]` that
  contains `/`, read from the raw reply: backticks, quotes, `*`, and parens
  are delimiters, so `` `user/u-ada/x/y.md` `` and `(user/u-ada/x/y.md)`
  give the same token. Fenced blocks and quotes are not stripped. Trailing
  `.` `,` `;` `:` `!` `?` are stripped. Segments before the first root are
  dropped, so a leading `/` is ignored. A token is skipped when:
  - it is part of a URL or host path: `reply[:start]` ends with a scheme
    (`[A-Za-z][A-Za-z0-9+.-]*:`), the run starts with `//`, or a segment
    before the root contains `.` (`www.x.com/user/y`);
  - fewer than two non-empty segments remain from the root (`user/`);
  - every remaining segment is a root (`user/project`, `project/org`);
  - exactly two segments remain and the second is neither a known area nor a
    known entity id (prose like `user/session`, `org/team`). Known areas:
    `system`, every area in `evals.reference_adopter.SEED_AREAS_BY_SCOPE`,
    the scenario's seed areas, and the third segment of every known location
    with at least three segments. Known entity ids: the scenario identity's
    grant entity ids and the second segment of every known location. So
    `user/preferences` and `project/glossary` (scope/area shorthand) are
    still checked;
  - its normalized form equals a token extracted the same way (without the
    echo rule) from the user text of any turn of the same session up to and
    including this turn (an echo).
- **2.3 Known locations.** For a reply at (session s, turn t): every `str`
  under a `path` or `prefix` key, at any depth up to 32 nested objects/lists
  (deeper values are ignored), in the `result` of every call with session 0
  (untagged), session < s, or session s and turn <= t. Failed calls count,
  since the tool returned that path. Arguments never count. One leading and
  one trailing `/` are dropped. Each known location also contributes every
  directory prefix of itself (`user/u-ada/preferences/charts.md` gives
  `user/u-ada` and `user/u-ada/preferences`); "known locations" below
  includes these directories.
- **2.4 Match.** Token T is normalized: root onward, `/`-joined, no empty
  segments. Candidates are T and, if T does not end in `.md`, T + `.md`. T is
  matched when some candidate equals a known location, or is a suffix of one
  at a segment boundary (the known location ends with `/` + candidate), so
  `system/fiscal-calendar` matches
  `organization/o-acme/system/fiscal-calendar.md`.
- **2.5 Kind.** An unmatched token's kind is `entity_omitted` when some known
  location with at least three segments, with its second segment removed,
  matches a candidate by 2.4 (`project/metrics/dau.md` for
  `project/p-checkout/metrics/dau.md`; `user/preferences` for
  `user/u-ada/preferences`). Otherwise `unmatched`
  (`project/metrics/daily-active-users.md` when only `dau.md` exists).
- **2.6 grade.json.** Given a trial with `transcript.json` and a loadable
  `trace.json`, then `grade.json` gains `unmatched_reply_paths`: a list of
  `{session, turn, token, kind}` (empty when none). With `transcript_error`
  (shared with the third-person check), neither list is written. Without a
  transcript, neither key is written. `results` and `passed` never change.
  `_load_grade` validates the new list (`session`, `turn` int; `token`,
  `kind` str) and raises `GradeInputError` otherwise.
- **2.7 Refresh.** Given a `grade.json` current for the store and trace, when
  `build_report` runs, then both reply checks are recomputed and the file is
  rewritten only if a check field changed. An old `grade.json` with
  `third_person_replies` but no `unmatched_reply_paths` gains it. A deleted
  transcript drops both. If `trace.json` is missing or cannot be loaded at
  refresh, the third-person check is still refreshed and
  `unmatched_reply_paths` is omitted (the trial counts as reply-path
  unchecked); `build_report` never raises for it.
- **2.8 Report.** Each scenario report gains `reply_path_trials`
  (`[{trial, paths: [{session, turn, token, kind}]}]`) and
  `reply_path_unchecked_trials` (trials whose grade has no
  `unmatched_reply_paths`). The report gains `reply_paths: {flagged_trials,
  checked_trials, entity_omitted_trials}` (`entity_omitted_trials`: trials
  with at least one `entity_omitted` flag). Markdown:
  - right after the line "Trials with a third-person reply: X of Y
    checked.", a new line (no blank line between): `Trials with an unmatched
    reply path: X of Y checked (Z with an omitted entity segment).`
  - per scenario, after the third-person line (or where it would be), a
    blank line then `Unmatched reply paths: trial 1 (session 1 turn 2:
    "project/metrics/dau.md" [entity_omitted]); trial 4 (session 1 turn 2:
    "project/metrics/dau.md" [entity_omitted], session 1 turn 2:
    "project/metrics/other.md" [unmatched])`, mirroring `_flagged_line`;
  - per scenario, `Reply paths not checked: 2, 5` when any are unchecked.
  `trials_run`, `passed_trials`, `pass_rate`, `assertions`, `judge`, and every
  third-person field are unchanged. `merge_runs` gets it via `build_report`.
- **2.9 Re-report and false-positive review.** Two `cp -Rp` copies each of
  `aie1184-n6` (wenchang-AIE-1184), `aie1182-n6` (wenchang-AIE-1182),
  `aie1183-n6` (wenchang-AIE-1183), and `aie1185-r2-n6` (wenchang-AIE-1185).
  One set is re-reported with origin/main's code (before), the other with
  this branch (after); both run `python -m evals report` with the code's
  worktree as cwd. The copies' `trial.json` scenario paths point into those
  four worktrees, which must still exist. Then:
  - the originals are unchanged by file hash;
  - `trials_run`, `passed_trials`, `assertions`, `judge`, and `third_person`
    are identical between before and after. (Before already differs from the
    originals' stored reports where AIE-1199 changed the third-person check,
    e.g. `aie1182-n6` 12 to 6; that is recorded, not attributed here.)
  - review-pr.md and ADR 0033 record flagged/checked trials per run, the
    entity-omitted share, and a manual review of every flagged token, each
    false positive classified (correct proposal written later, URL, prose,
    other).

### US3 — Held-out scenarios (committed before the prompt edit)

Written from intent, not from the prompt. Each has a `# Prompt:` header that
cites only existing prompt sentences (never the Goal 1 sentence),
`index_read_first` `index-first` and `tool_called` `index-called`
(`get_memory_index`, per AIE-1197), first-person user turns that do not copy
prompt wording, and a correct and a wrong scripted driver in
`tests/test_evals_end_to_end.py` with exact fail sets. The corpus-set test
gains the 4 ids. Path patterns accept an optional leading `/` and `.md`.
`names-full-path` checks the entity segment only; a wrong file name with the
entity present passes it and is caught by the US2 check instead.

- **3.1** `filing-says-saved-path` (filing; user scope; new file). Turn: "I
  export every query result as CSV with a header row, never as Excel. Keep
  that in mind for me, and tell me which file it ended up in."
  - `line_present` `csv-saved`: `(?i)\bcsv\b`, scope `user`
  - `reply_matching` `names-full-path` (session 1 turn 1):
    `(?<![\w.-])/?user/u-ada/[a-z0-9][a-z0-9-]*/[a-z0-9][a-z0-9-]*`
  - `reply_not_matching` `no-rebuilt-path` (session 1 turn 1):
    `(?<![\w.-])/?user/(?!u-ada/)(?!(?:project|organization|org)(?![\w-]))[a-z0-9][a-z0-9-]*/[a-z0-9]`
- **3.2** `slots-says-shared-path` (slots; project scope; the user never asks
  where). Turn 1: "On this project, we write every dashboard name in sentence
  case, never title case." Turn 2: "Go ahead, put it in the project's
  memory."
  - `line_present` `convention-saved`: `(?i)sentence case`, scope `project`
  - `reply_not_matching` `no-rebuilt-path` (session 1, any turn):
    `(?<![\w.-])/?project/(?!p-checkout/)(?!(?:user|organization|org)(?![\w-]))[a-z0-9][a-z0-9-]*/[a-z0-9]`
  - It passes vacuously when no path is named; the US2 check and 5.3's
    delta carry its signal.
- **3.3** `recall-says-stored-path` (recall; organization scope; read only).
  Seed `organization/vocabulary/account-tiers`: "- [stated] An enterprise
  account has 500 or more seats.", description "Account tier definitions",
  aliases `[enterprise, tiers]`. Turn: "My new teammate keeps asking what
  counts as an enterprise account here. Which memory file has that, so I can
  send her the location?"
  - `reply_matching` `names-full-path`:
    `(?<![\w.-])/?organization/o-acme/vocabulary/account-tiers(?:\.md)?(?![\w-])`
  - `reply_not_matching` `no-rebuilt-path`:
    `(?<![\w.-])/?organization/(?!o-acme/)(?!(?:user|project|org)(?![\w-]))[a-z0-9][a-z0-9-]*/[a-z0-9]`
  - `tool_not_called` `no-write`: `[write_file, append_line, replace_fact,
    delete_file]`
  - A regression guard: the full path is in context after the index, so it
    likely passes at main. It is not counted in 5.3's delta.
- **3.4** `applying-no-path-unasked` (applying; guard: no path is needed).
  Seed `user/preferences/reports`: "- [stated] Wants every chart titled with
  the date range it covers.", description "Report and chart preferences",
  aliases `[charts]`. Turn: "I'm putting together a chart of weekly signups
  for last quarter. What title should I give it?"
  - `reply_not_matching` `no-path-in-reply`:
    `(?<![\w.-])/?(?:user|project|organization|org)/[a-z0-9][\w-]*(?:/|\.md\b)`
  - judge `applies-preference`: "The turn 1 reply suggests a chart title that
    states the date range the chart covers." (The loader requires a rubric to
    name its turn.)
  - Naming a path on a save is allowed; this guards recall-and-apply only.
- **3.5** Given the US2 check run on each held-out's correct driver, then it
  flags nothing; on 3.1-3.3's wrong drivers (which reply with a rebuilt
  path), it flags an `entity_omitted` token. One test per held-out.

### US4 — Unchanged behavior

- **4.1** `make check` is green.
- **4.2** No existing scenario, assertion, or judge rubric changes.
- **4.3** No `src/` file other than `src/wenchang/prompts/overview.py`
  changes. Tool output is unchanged.

### US5 — Live gate (human-run, gates the merge; never run by agents)

Baselines below predate AIE-1197's `index-called` assertion, which can only
lower a trial's pass; a drop explained by `index-called` alone is noted, not
counted.

- **5.1 Baseline at main.** The 4 held-outs at main, N=6, `--judge`, in a
  throwaway worktree:
  1. `git fetch`; `git worktree add --detach <scratch> origin/main`; `make
     -C <scratch> install`; `git -C <scratch> checkout
     origin/AIE-1198-reply-paths -- <the 4 held-out yaml paths>`.
  2. Launch the eval session from `<scratch>`, run the 4 at N=6, record
     main's agent sha256.
  3. Run `python -m evals report` on the run from this branch's worktree (cwd)
     to get the reply-path counts, copy the run dir out, and only then
     `git worktree remove --force <scratch>`. The copied `report.md` and
     `report.json` are what is kept.
- **5.2 Branch run.** The full corpus at N=6 with `--judge`, sharded across
  sessions, from the worktree root, merged with `merge-runs`.
- **5.3 Floors.**
  - 3.1 at least 5/6 on the branch. 3.1 and 3.2 together pass at least 3
    more trials on the branch than at main, or main passes at least 10/12
    and the branch at least 11/12 (then "held-outs do not discriminate" is
    recorded as a finding, and the reply-path floor below carries the gate).
  - 3.3 at least 5/6. 3.4 6/6 deterministically, and `applies-preference` no
    lower than at main.
  - `remembering-no-metric-value` at least 5/6.
  - Every other scenario: trials-passed at most 1 below its baseline. The
    baseline is its count in the most recent (by `run.json` `created`) of the
    four re-reported runs; for `applying-no-trait`, `applying-relevant-only`,
    `curated-observed-conflict`, `filing-second-customer`,
    `remembering-observed-once`, and `slots-system-of-record` (in none of
    them), the most recent main N=6 count recorded in `specs/*/review-pr.md`,
    else 5/6. A miss counts only if a second N=6 run of that scenario also
    misses (combined at most 2 below twice the baseline is a pass).
  - Judge items at least their baseline minus 1, same baseline rule.
  - Reply-path check: on the scenarios common to the branch run and the
    after re-report (US2.9), per-scenario most recent baseline, the
    branch's flagged trials are at most half the baseline's. Proposal flags
    put a floor under this rate; the review notes how many there are.
  - Third-person flagged trials on the branch run at most the after
    re-report's pooled rate times the branch's checked trials, plus 2.
- **5.4 Iteration.** If a floor is missed, revise the wording (still
  general), re-render, rerun, and record each iteration in review-pr.md.

## Out of scope

- Tool results and descriptions; `curated_content.BODY`; scope guidance.
- Counting the reply-path check in pass/fail (a later issue may promote it
  once its false-positive rate is known).
- Existing scenarios and judge rubrics.

## Risks and limits

- **Proposals.** "I'll save it to organization/vocabulary" before a write is
  flagged; the review classifies these.
- **Rootless rebuilds** (`metrics/dau.md`) are invisible to the check.
- **Over-application.** 3.4 guards recall answers.
- **Prose.** Three-segment prose with a root (`user/session/id`) would still
  flag; the review measures it.
- **Agent-file conflicts.** PR #41 (AIE-1196) also re-renders
  `wenchang-eval.md`; whichever merges later re-renders on rebase. Check the
  ADR number (0033) on rebase.
