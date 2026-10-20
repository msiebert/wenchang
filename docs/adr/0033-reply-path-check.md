# 0033. Reply path check

Date: 2026-10-19

## Status

Accepted.

## Context

The tools take `(scope, area, name)` and return an entity-qualified `path`,
such as `project/p-checkout/metrics/dau.md`. In the AIE-1184 N=6 run
(`aie1184-n6`), `remembering-no-metric-value` replies named the saved file
wrongly:

- Trials 1 and 4 said `project/metrics/dau.md`.
- Trial 5 said `project/metrics/daily-active-users.md`.

The issue described trial 5 as a wrong file name. The trace shows that
`daily-active-users.md` is a real file. Only its entity segment is missing, so
all three are the same mistake: the agent rebuilt a path from the arguments it
passed instead of quoting the one the tool returned.

The prompt never said how to name a stored location. Nothing graded it. The
`curated-correction` judge item `says-where-saved` passes a wrong path.

## Decision

1. **Add one prompt sentence.** It is the second sentence of `overview.BODY`:
   "When you tell the user where something is stored, quote the full `path` a
   tool returned for it; never rebuild one from its scope, area, and name."
   It names no fact, scope, area, file, or scenario. It is conditional, so it
   asks for no path where none is needed.

2. **Run a harness-wide reply-path check, not an assertion kind or judge
   rule.** `evals.graders.find_unmatched_reply_paths(scenario, trace,
   transcript)` is pure and imports no `mcp`. It returns one `{session, turn,
   token, kind}` per distinct unmatched token per reply.
   - **Roots.** A token needs a segment equal to a root: `user`, `project`,
     `organization`, the scenario identity's grant keys, `org`, or `system`.
     Matching is case-sensitive.
   - **Tokens.** A token is a maximal run of `[A-Za-z0-9_.~/-]` that contains
     `/`, read from the raw reply. Backticks, quotes, `*`, and parens are
     delimiters. Fenced blocks and quotes are not stripped, because a path in
     backticks is still a claim about where something is. Trailing `.,;:!?`
     are stripped. Segments before the first root are dropped.
   - **Skips.** A token is skipped when it is:
     - part of a URL or host path;
     - fewer than two segments from the root, or all roots;
     - two segments whose second is neither a known area nor a known entity
       id (prose such as `user/session`);
     - an echo of a token in the session's user text up to that turn.
   - **Known locations.** For a reply at (session s, turn t), every string
     under a `path` or `prefix` key in the results of calls from earlier
     sessions, untagged calls, and session s up to turn t, to a depth of 32.
     Failed calls count, since the tool returned the path. Arguments never
     count. Every directory prefix of a known location is known too.
   - **Match.** The token, with `.md` added if absent, equals a known location
     or is a suffix of one at a segment boundary.
   - **Kind.** `entity_omitted` when a known location with at least three
     segments, minus its second segment, matches the token. Otherwise
     `unmatched`.
   - **Recording.** `grade.json` gains `unmatched_reply_paths` when
     `transcript.json` and `trace.json` load. A `transcript_error` is shared
     with the third-person check and writes neither list. `results` and
     `passed` never change.
   - **Refresh.** `build_report` recomputes both checks for every current
     `grade.json` and rewrites it only if a check field changed. A missing or
     unloadable `trace.json` still refreshes the third-person check and omits
     `unmatched_reply_paths`; the trial counts as reply-path unchecked.
   - **Report.** Each scenario gains `reply_path_trials` and
     `reply_path_unchecked_trials`. The run gains `reply_paths:
     {flagged_trials, checked_trials, entity_omitted_trials}`. The markdown
     gains a total line and per-scenario lines. `trials_run`, `passed_trials`,
     `assertions`, `judge`, and the third-person fields are unchanged.

3. **Tool output is unchanged.** The full path is already consistent across
   `get_memory_index`, `list_prefix`, `read_file`, and the writes.

Rejected:

- **Returning a shorter path from the tools.** `path` is the stable address in
  every result and in the index. Changing it is a storage and API change for
  an eval symptom.
- **A sentence in `curated_content.BODY`.** That section covers corrections
  only. The failure happens on any save or recall.
- **A new assertion kind.** Like ADR 0031, it is opt-in per scenario, and it
  would move the pass counts of every existing scenario at once.
- **Tightening the `curated-correction` judge item.** It would break judge
  comparability with every baseline. Four held-out scenarios and the check
  cover it.
- **Stripping fenced code and quotes before extraction.** A path in backticks
  or a fence is still a claim about where something is.

## Consequences

- **Measurement.** Two `cp -Rp` copies of each of four runs were re-reported.
  One set used origin/main's code (before) and one used this branch (after).
  Both ran `python -m evals report` with the code's worktree as cwd.
  - The originals are unchanged by file hash.
  - `trials_run`, `passed_trials`, `assertions`, `judge`, and `third_person`
    are identical before and after.

  | Run | Reply-path flagged | Entity omitted | Third-person (unchanged) |
  | --- | ------------------ | -------------- | ------------------------ |
  | `aie1184-n6` | 51/138 | 45 | 8/138 |
  | `aie1182-n6` | 37/168 | 34 | 6/168 |
  | `aie1183-n6` | 74/168 | 68 | 6/168 |
  | `aie1185-r2-n6` | 47/120 | 47 | 8/120 |
  | Total | 209/594 (35%) | 194 | 28/594 |

- **False-positive review.** Every flagged token was reviewed by hand. No flag
  is a URL, prose, or a correct proposal. Every `entity_omitted` flag is a
  scope, area, and name rebuild, such as `user/preferences/editor`,
  `user/workflows/atlas-migration`, `project/entities/checkout-redesign`, and
  `organization/system/fiscal-calendar`.
- **Contested flags.** 15 trials were flagged only as `unmatched` (AIE-1184: 6,
  AIE-1182: 3, AIE-1183: 6, AIE-1185: 0). All are turn 1 proposals in
  ask-before-shared flows. They name a location before any write, such as
  `organization/vocabulary`, `project/glossary`,
  `project/conventions/signup-definition`, and
  `organization/business-context/fiscal-year`. That location does not exist
  and never would as written, because it has no entity segment. They are
  counted. The sentence's scope ("where something is stored") does not
  strictly cover them, so 15 of 209 is an upper bound on contested flags.
- **Grade refresh.** `_grade_is_current` still keys only on
  `third_person_replies` and `transcript_error`. Older grades without the new
  field stay current and gain it on refresh.
- **Live gate.** The prompt sentence is kept only if the human-run gate in
  `specs/AIE-1198-reply-paths-quote/review-pr.md` passes. Its result is
  recorded there.
- **Limits.**
  - Rootless rebuilds (`metrics/dau.md`) are invisible.
  - Three-segment prose with a root would flag.
  - Proposals before a write are flagged.
  - The held-out `names-full-path` checks only the entity segment.
  - The numbers depend on the `trial.json` scenario paths pointing into
    worktrees that still exist.
  - The baselines predate AIE-1197's `index-called` assertion.
  - A path glued to a word and colon with no space (`Path:user/u-ada/x.md`,
    `e.g.user/...`) is skipped as if the word were a URL scheme.
  - Echo compares exact normalized tokens, so a user's `user/foo/bar` does not
    exempt a reply's `user/foo/bar.md`.
  - Unix-style prose paths such as `/system/bin/foo` are flagged `unmatched`.
    Dot segments (`user/./x`) are kept.
  - The check is linear in reply length. The token pattern starts only at run
    boundaries, and the scheme lookup reads at most 64 characters back.
  - The held-out `slots-says-shared-path` never asks where the fact is stored,
    so it can pass without naming a path. This is deliberate: it is the only
    held-out where the user does not ask, which matches the motivating
    failure. The reply-path check and the live gate's held-out delta carry its
    signal. The held-outs were not edited after the prompt commit.
