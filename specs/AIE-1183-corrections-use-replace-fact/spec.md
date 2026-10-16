# Feature Specification: A changed fact states only what is true now

**Linear issue**: AIE-1183

**Feature Branch**: `AIE-1183-replace-fact-corrections`

**Created**: 2026-10-16

**Status**: Respecced after diagnosis (Option A chosen by the human)

**Input**: Live eval finding from the AIE-1170 N=3 runs
(`specs/AIE-1170-eval-harness/review-pr.md`, "Live runs at N=3").

## Diagnosis

Trials read: `evals/runs/20261014-225317-sonnet` and
`evals/runs/20261014-231845-sonnet-merged` in the AIE-1170 worktree.

- **11 of 12 superseding writes kept history.**
  - `recall-replace-fact` kept it in 5 of 6 trials, including all three
    trials of run B that "passed".
  - `write-correct-seeded-fact` kept it in 6 of 6 trials, and some lines
    added a change date. That scenario has no absence assertion, so it fails
    silently.
  - The replies show the agent did this on purpose, keeping a short note of
    the earlier value.
- **Only 2 of 12 used `write_file`.** Tool choice is the minor failure.
- **Why history is kept.** The prompt has no principle that memory states
  what is true now.
  - The only no-trace rule is Forgetting's "Removal is total: leave no note
    that the fact was ever true", which is scoped to removal.
  - The contradiction rule covers only shared scopes.
  - Curated content models a correction that sits beside the old value.
- **Why `write_file` is picked.**
  - Write mechanics justifies `replace_fact` only by protecting surrounding
    lines, and a one-line file has none.
  - Both `write_file` trials also changed `description` and `aliases`, which
    `write_file` sets in one call.
- **Aliases.** All 12 kept old aliases, sometimes deliberately ("so it can
  still be found under that name"). An old name still finds the right file.

## Fix (general, not scenario-specific)

- Add a Forgetting paragraph saying a changed fact's old value is gone. The
  line states only what is true now, unless the user asks to keep a record.
  This covers any superseded preference, owner, schedule, definition, or
  tool.
- Add a Write-mechanics sentence: changing one fact is still `replace_fact`
  when it is the file's only line or when the change also updates metadata.
- **Rejected earlier text.** PR #38's first two sentences ("To change or
  correct a fact … no \"previously\" or \"instead of\" clause …") were
  rejected because they quoted the failing trials' phrasing. They are
  removed.
- **Rejected: a `write_file` docstring sentence.** ADR 0025 decision 6 has
  the prompt own tool choice and the docstrings own per-call mechanics.
- **Out of scope:**
  - Stale aliases. Old names still find the file, and dropping them needs
    `write_file`.
  - `remembering.py` (AIE-1182), `evals/agent.py` (AIE-1184), grader
    changes, and new assertion kinds.

## User Scenarios & Testing

### US1 - Held-out evidence, committed before any prompt edit (P1)

The scenarios are written from intent. Their headers cite only sentences
that already exist on main; the exception is noted in US1.5.

1. **Given** `write-correct-seeded-fact.yaml`, **When** loaded, **Then** it
   has a `line_absent` assertion with id `old-format-gone`, pattern
   `(?i)pdf`, scoped to `user/preferences/report-format`.
   - This is compatible with `seed_lines_preserved except: (?i)pdf`.
   - The correct driver passes everything.
   - The append wrong driver fails exactly `{replaced-quoting-old,
     one-format-line, old-format-gone}`.
2. **Given** `write-superseded-tool`, **When** graded, **Then** the correct
   and wrong drivers behave as follows.
   - Setup: a seeded one-line file
     (`- [stated] Keeps standup notes in Notion.`). The user moved the
     notes to Confluence.
   - The correct driver (`replace_fact`) passes everything.
   - The append wrong driver fails exactly `{replaced-tool-line,
     old-tool-gone, one-notes-line}`.
3. **Given** `recall-superseded-definition`, **When** graded, **Then** the
   correct and wrong drivers behave as follows.
   - Setup: session 1 states a 7-day activation window, and session 2
     switches it to 14 days.
   - The correct driver (`replace_fact` in session 2) passes everything.
   - The append wrong driver fails exactly `{replaced-in-session-2,
     one-window-line, old-window-gone}`.
4. **Given** `write-added-not-superseded`, an over-correction guard,
   **When** graded, **Then** the correct and wrong drivers behave as
   follows.
   - Setup: a seeded dashboard is shared with design, and the user adds
     sales "too".
   - The correct driver (append) passes everything.
   - A wrong driver that replaces the design line fails exactly
     `{design-kept}`.
5. **Given** `write-superseded-kept-on-request`, an over-correction guard,
   **When** graded, **Then** the correct and wrong drivers behave as
   follows.
   - Setup: the user switches deploys from Jenkins to GitHub Actions and
     explicitly asks to keep a record of the old tool.
   - The correct driver (replace, then append a record line) passes
     everything.
   - A wrong driver that replaces the line and leaves no record fails
     exactly `{old-tool-recorded}`.
   - Its header cites an existing sentence in commit 1 ("Save a fact only if
     it would let a future session answer better, differently, or faster").
     It adds the new exception sentence in commit 2, because the behaviour
     depends on that sentence.
6. **Given** the corpus test, **When** run, **Then** `CORPUS` includes the
   four new ids, and every scenario has `index-first` and a `# Prompt:`
   header.

### US2 - The prompt states current truth (P1)

1. **Given** `forgetting.BODY`, **When** whitespace is collapsed, **Then**
   it contains these load-bearing terms:
   - "its old value is gone"
   - "state only what is true now"
   - "recording the change"
   - "keep a record"

   All existing forgetting tests still pass: no tool names, no "used to"
   or "formerly".
2. **Given** `write_mechanics.BODY`, **When** split into sentences,
   **Then**:
   - Exactly one sentence contains "the file's only line", and it names
     `replace_fact`, `description`, and `aliases`.
   - The phrases "previously", "instead of", "even when you have read the
     whole file", and "of a changed fact" are absent.
3. **Given** the existing write-mechanics and invariants tests, **When**
   run, **Then** they pass unchanged.
4. **Given** the `recall-replace-fact` header, **When** collapsed, **Then**
   it cites "When a fact changes, its old value is gone too" and "Changing
   one fact is still `replace_fact` when it is the file's only line". The
   header test asserts both.
5. **Given** `.claude/agents/wenchang-eval.md`, **When**
   `tests/test_evals_agent.py` runs, **Then** it equals
   `render_agent_file()`. The sha256 is recorded in `review-pr.md`.

### US3 - Branch drivers stay (P2)

`old-recipient-gone`, the overwrite driver, and the stale-metadata driver
on `recall-replace-fact` stay unchanged. They test grader mechanics and do
not tune the prompt.

### Live check: the human's merge checkpoint (ADR 0028, not a release gate)

- **When:** after #39 merges and this branch is rebased and re-rendered.
- **Runs:** two full-corpus runs at N=3 with `--judge`, in 3 shards each,
  merged with `merge-runs`.
- **Floors over the combined N=6:**

  | Scenario | Floor |
  | -------- | ----- |
  | `recall-replace-fact` | 6/6 |
  | `write-correct-seeded-fact` (including `old-format-gone`) | 6/6 |
  | `write-superseded-tool` | at least 5/6 |
  | `recall-superseded-definition` | at least 5/6 |
  | `write-added-not-superseded` | 6/6 |
  | `write-superseded-kept-on-request` | 6/6 |
  | Every other scenario | its AIE-1170 rate |

- **Held-out baseline at main:** run in a throwaway worktree (see
  `review-pr.md`). Held-outs that pass at main do not demonstrate the fix.
- **Miss policy:** inspect the failing transcripts, adjust only the new
  sentences, and rerun. After two rounds, the human decides.

### Edge Cases

- **Forward end dates.** "with no note, date, or comparison recording the
  change" bans dates that record the change. A forward end date that the
  expiry paragraph requires ("only until … on October 30") describes the
  current fact, not the change, so it is unaffected. No wording change is
  needed. `remembering-expiry` is in the corpus run.
- **Curated corrections.** The curated value is not "gone", because
  `system/` persists. The curated-content rule still governs, and
  `curated-*` are in the run.

## Requirements

- **FR-001**: No existing sentence is reworded. The two sentences added
  earlier on this branch are removed.
- **FR-002**: The held-out commit precedes the prompt commit.
- **FR-003**: `make check` passes after each commit.
