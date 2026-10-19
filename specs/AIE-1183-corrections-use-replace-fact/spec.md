# Feature Specification: A changed fact states only what is true now

**Linear issue**: AIE-1183

**Feature Branch**: `AIE-1183-replace-fact-corrections`

**Created**: 2026-10-16

**Status**: Respecced after diagnosis (the human chose Option A), revised
after the generality review.

**Input**: Live eval finding from the AIE-1170 N=3 runs
(`specs/AIE-1170-eval-harness/review-pr.md`, "Live runs at N=3").

## Diagnosis

Trials read: `evals/runs/20261014-225317-sonnet` and
`evals/runs/20261014-231845-sonnet-merged` in the AIE-1170 worktree.

- **History was kept in 11 of 12 writes that replaced a fact.**
  - `recall-replace-fact` kept it in 5 of 6 trials. That includes all three
    run B trials that "passed".
  - `write-correct-seeded-fact` kept it in 6 of 6 trials, sometimes with a
    change date. That scenario has no absence assertion, so it fails
    silently.
  - The replies show the agent did this on purpose, keeping a short note of
    the earlier value.
- **Only 2 of 12 used `write_file`.** Tool choice is the minor failure.
- **Why history is kept.** The prompt has no principle that memory states
  what is true now.
  - The only no-trace rule is Forgetting's "Removal is total: leave no note
    that the fact was ever true", and it is scoped to removal.
  - The contradiction rule covers only shared scopes.
  - Curated content models a correction that sits beside the old value.
- **Why `write_file` is picked.**
  - Write mechanics justifies `replace_fact` only by protecting surrounding
    lines. A one-line file has none.
  - Both `write_file` trials also changed `description` and `aliases`, which
    `write_file` sets in one call.
- **Aliases.** All 12 trials kept old aliases, sometimes on purpose ("so it
  can still be found under that name"). An old name still finds the right
  file.

## Fix (general, not scenario-specific)

### Forgetting: new paragraph after "Keep anything with support of its own."

> When a fact in a file you can write changes, its old value is gone too:
> rewrite the line with a fresh label to state only what is true now, as
> though it had always read that way, with no note, date, or comparison
> recording the change. Keep an earlier value only if the user asks you to
> keep a record of it. A correction to a curated fact may name the curated
> fact it overrides.

What each part does:
- "a file you can write" keeps `system/` out of scope.
- "fresh label" matches Remembering's "only new or changed lines get a
  fresh one".
- The last sentence leaves the curated-content correction pattern alone.

### Write mechanics: two changes

1. The cited sentence where `replace_fact` is introduced gains "writing the
   new line as the current truth and":
   > Use `append_line` to add one fact to an existing file and `replace_fact`
   > to change one fact, writing the new line as the current truth and
   > quoting the existing line as `old_string` so surrounding lines stay
   > intact; …
2. A new sentence follows it:
   > Changing one fact is still `replace_fact` when it is the file's only
   > line or when the change also replaces `description` or adds `aliases`.

   It is accurate about aliases: `replace_fact` only adds them, and
   "dropping a name from `aliases`" stays `write_file`.

### Rejected

- **PR #38's first two sentences** ("To change or correct a fact … no
  \"previously\" or \"instead of\" clause …"). They quoted the failing
  trials' phrasing, and they are removed.
- **A `write_file` docstring sentence.** ADR 0025 decision 6 has the prompt
  own tool choice and the docstrings own per-call mechanics.

### Out of scope

- Stale aliases, including any alias-drop instruction.
- `remembering.py` (AIE-1182) and `evals/agent.py` (AIE-1184).
- Grader changes and new assertion kinds.

## User Scenarios & Testing

### US1 - Held-out evidence, committed before any prompt edit (P1)

- **Written from intent.** Turns are in the first person, so the prompt
  does not route them to a shared scope with an ask. The exception is
  US1.7, which is about a shared scope on purpose.
- **Headers in the held-out commit** cite only sentences that already exist
  on main.
- **Headers in the prompt commit:**
  - `write-superseded-tool`, `recall-superseded-definition` and
    `write-correct-seeded-fact` add the Forgetting principle sentence,
    because their assertions depend on it.
  - `write-superseded-kept-on-request` adds the exception sentence.
- **`source:`** in every new YAML is this spec.

1. **Given** `write-correct-seeded-fact.yaml`, **When** loaded, **Then** it
   has a `line_absent` assertion `old-format-gone` with pattern `(?i)pdf`,
   scoped to `user/preferences/report-format`.
   - This is compatible with `seed_lines_preserved except: (?i)pdf`.
   - The append wrong driver fails exactly `{replaced-quoting-old,
     one-format-line, old-format-gone}`.
2. **Given** `write-superseded-tool`, **When** graded, **Then** the drivers
   behave as below.
   - Setup: the seeded one-line file `- [stated] Keeps standup notes in
     Notion.`, and the turn "I moved my standup notes to Confluence last
     week."
   - New assertion `no-change-date`: `line_absent (?i)last week`.
   - The correct driver (`replace_fact`) passes everything.
   - The append wrong driver fails exactly `{replaced-tool-line,
     old-tool-gone, one-notes-line}`.
3. **Given** `recall-superseded-definition`, **When** graded, **Then** the
   drivers behave as below.
   - Setup: a 7-day activation window in session 1 becomes 14 days in
     session 2.
   - The correct driver passes everything.
   - The append wrong driver fails exactly `{replaced-in-session-2,
     one-window-line, old-window-gone}`.
4. **Given** `write-added-not-superseded` (a guard), **When** graded,
   **Then** the drivers behave as below.
   - Setup: the user adds a sales audience "too".
   - The append driver passes everything.
   - The replace wrong driver fails exactly `{design-kept}`.
5. **Given** `write-superseded-kept-on-request` (a guard), **When** graded,
   **Then** the drivers behave as below.
   - Setup: the turn "I switched my deploys from Jenkins to GitHub Actions.
     I still want to remember that I used Jenkins before, since my old
     runbooks reference it." It paraphrases the request rather than reusing
     the prompt's wording, so the scenario tests the rule, not phrase
     matching.
   - New assertion `old-line-changed`: `line_absent ^- \[stated\] Deploys
     with Jenkins\.?$`.
   - The correct driver (replace, then append a record line) passes
     everything.
   - The replace-only wrong driver fails exactly `{old-tool-recorded}`.
   - An append-only driver, which records the change without touching the
     old line, fails exactly `{old-line-changed}`. It is tested separately.
6. **Given** the corpus test, **When** run, **Then** `CORPUS` includes the
   five new ids, and every scenario has `index-first` and a `# Prompt:`
   header.
7. **Given** `write-superseded-shared-fact`, **When** graded, **Then** the
   drivers behave as below.
   - Setup: a seeded, non-curated project fact, and a user turn that
     changes it.
   - Its header cites the existing shared-contradiction sentence.
   - Assertion: no project or organization write in turn 1.
   - Assertion: the seed line is still present.
   - Judge item: the agent shows the stored fact and asks which to keep.
   - The correct driver (no write) passes the deterministic assertions.
   - A driver that replaces the project line fails exactly
     `{no-shared-write-before-ask, old-fact-kept}`.

### US2 - The prompt states current truth (P1)

1. **Given** `forgetting.BODY`, collapsed, **When** read, **Then** it
   contains these phrases, and all existing forgetting tests still pass:
   - "a file you can write"
   - "its old value is gone"
   - "fresh label"
   - "state only what is true now"
   - "recording the change"
   - "keep a record"
   - "may name the curated fact it overrides"
2. **Given** `write_mechanics.BODY`, **When** read, **Then**:
   - It contains "writing the new line as the current truth".
   - Exactly one sentence contains "the file's only line", and it contains
     `replace_fact`, "replaces `description`" and "adds `aliases`".
   - The trial phrasings ("previously", "instead of", "even when you have
     read the whole file", "of a changed fact") are absent.
3. **Given** the existing write-mechanics and invariants tests, **When**
   run, **Then** they pass. The pins and citations on the reworded cited
   sentence are updated.
4. **Given** the `recall-replace-fact` header, **When** collapsed, **Then**
   it cites "When a fact in a file you can write changes, its old value is
   gone too" and "Changing one fact is still `replace_fact` when it is the
   file's only line". The header test asserts both.
5. **Given** the agent file, **When** `tests/test_evals_agent.py` runs,
   **Then** it equals `render_agent_file()`. Its sha256 is recorded in
   `review-pr.md`.

### US3 - Branch drivers stay (P2)

`old-recipient-gone`, the overwrite driver and the stale-metadata driver on
`recall-replace-fact` are unchanged.

### Live check: the human's merge checkpoint (ADR 0028, not a release gate)

- **When:** after #39 merges and this branch is rebased and re-rendered.
- **Runs:** two full-corpus runs at N=3 with `--judge`. Each run is 3
  shards merged with `merge-runs`. Never pass both runs to `merge-runs`.
- **N=6 tally:** sum `passed_trials` per scenario across the two merged
  `report.json` files.
- **Floors:**

  | Scenario | Floor |
  | -------- | ----- |
  | `recall-replace-fact` | 6/6 |
  | `write-correct-seeded-fact` (including `old-format-gone`) | 6/6 |
  | `write-superseded-tool` | at least 5/6 |
  | `recall-superseded-definition` | at least 5/6 |
  | `write-added-not-superseded` | 6/6 |
  | `write-superseded-kept-on-request` | 6/6 |
  | `write-superseded-shared-fact` (judge included) | 6/6 |
  | Every other scenario | its AIE-1170 rate |

- **Held-out baseline at main:** run in a throwaway worktree and copy the
  run out before removing the worktree (`review-pr.md` has the steps).
  Held-outs that pass at main do not demonstrate the fix.
- **Miss policy:**
  1. Inspect the transcripts.
  2. Adjust only the new sentences.
  3. Rerun.
  4. After two rounds, the human decides.

### Edge Cases

- **Forward end dates.** "with no note, date, or comparison recording the
  change" bans dates that record the change. An expiry end date describes
  the current fact, so it is unaffected.
- **Curated corrections.** These are covered by "may name the curated fact
  it overrides".
- **A contradicted shared fact.** The Scopes rule (ask which to keep) still
  comes first. `write-superseded-shared-fact` pins this.

## Requirements

- **FR-001**: Only the cited `replace_fact` sentence is reworded, and its
  citations and pins are updated. The two sentences added earlier on this
  branch are removed.
- **FR-002**: The scenario-only commit precedes the prompt and citation
  commit.
- **FR-003**: `make check` passes at both commits. The scenario-only commit
  is checked in a throwaway worktree.
