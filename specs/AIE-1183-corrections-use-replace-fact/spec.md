# Feature Specification: Corrections use replace_fact, not a full-file overwrite

**Linear issue**: AIE-1183

**Feature Branch**: `AIE-1183-replace-fact-corrections`

**Created**: 2026-10-16

**Status**: Approved after spec review (revised)

**Input**: Live eval finding from the AIE-1170 N=3 runs
(`specs/AIE-1170-eval-harness/review-pr.md`, "Live runs at N=3").

## Problem

`recall-replace-fact` passed 4 of 6 live trials. Session 1: "I send my
weekly report to the growth team." Session 2: "I now send my weekly report
to the retention team instead." In both failing trials the session-2 agent
read the file, then corrected it with `write_file` (a whole-file overwrite)
instead of `replace_fact`. The end state had one recipient line, but it
read "Sends a weekly report to the retention team (previously sent to the
growth team)", which keeps the superseded fact.

The write-mechanics section says `replace_fact` changes one fact, but it
does not say that a correction stays a one-fact change after a full read.
It also does not say that the new line carries no trace of the old value.

## Scope

- Add two sentences to `wenchang.prompts.write_mechanics.BODY`. Existing
  sentences stay verbatim, because scenarios and tests cite them.
- Add a `line_absent` assertion to `evals/scenarios/recall-replace-fact.yaml`
  and update its scripted drivers.
- Re-render `.claude/agents/wenchang-eval.md`.
- Out of scope: `remembering.py` (AIE-1182), `evals/agent.py` (AIE-1184),
  new scenarios (AIE-1185), new assertion kinds, grader changes, and tool
  docstrings.

### Considered and rejected: a `write_file` docstring sentence

Adding "To change one fact in an existing file, use `replace_fact`
instead." to the `write_file` docstring was rejected. ADR 0025 decision 6
and ARCHITECTURE.md give the prompt ownership of tool choice and give the
docstrings ownership of per-call mechanics. This issue keeps that split
rather than amending it, so no tool description and no ADR changes.

## User Scenarios & Testing

### User Story 1 - The prompt makes corrections one-fact replaces (Priority: P1)

When a user says a fact stored in a file the agent can write has changed,
the agent edits only that line with `replace_fact` and writes only the
current value.

**Independent Test**: unit tests over `write_mechanics.BODY` (whitespace
collapsed). They pin only load-bearing terms (ADR 0025 decision 8).

**Acceptance Scenarios**:

1. **Given** the body, **When** it is split into sentences, **Then**
   exactly one sentence contains "even when you have read the whole file".
   That sentence contains `replace_fact`, `write_file`, "you can write",
   and "never rewrite the file".
2. **Given** the body, **When** it is split into sentences, **Then**
   exactly one sentence contains "states only the current fact". That
   sentence contains `new_string`, "\"previously\"", and "no note of the
   old value".
3. **Given** the body, **When** the existing tests in
   `tests/test_prompts_write_mechanics.py` and the invariants in
   `tests/test_prompts_invariants.py` run, **Then** they all pass unchanged.
   Every cited phrase is still present, each single-sentence anchor is
   still in exactly one sentence, no forbidden mechanics term appears, and
   the body stays under 2500 characters, ASCII, with lines of at most 100.

### User Story 2 - The eval catches a correction that keeps the old value (Priority: P1)

**Acceptance Scenarios**:

1. **Given** `recall-replace-fact.yaml`, **When** loaded, **Then** it has a
   `line_absent` assertion with id `old-recipient-gone`, pattern
   `(?i)growth`, and `scope: user`.
   - `line_absent` scans only end-state content lines, so a session-1 alias
     or description is not penalized.
   - `no_content_matching` cannot be used here: it also scans session 1's
     legitimate write.
2. **Given** the correct scripted driver, **When** graded, **Then** every
   assertion passes.
3. **Given** the existing wrong driver, which appends the retention line in
   session 2, **When** graded, **Then** it fails exactly
   `{replaced-in-session-2, one-recipient-line, old-recipient-gone}`.
4. **Given** a scripted driver that reproduces the live failure, **When**
   graded, **Then** it fails exactly
   `{replaced-in-session-2, old-recipient-gone}`.
   - In session 2 it reads the file, then calls `write_file` with the
     single line "- [stated] Sends the weekly report to the retention team
     (previously sent to the growth team)."
5. **Given** a driver whose session 1 writes the growth line with
   description "Weekly report to the growth team" and aliases
   `["growth report"]`, and whose session 2 does a correct `replace_fact`,
   **When** graded, **Then** every assertion passes, including
   `old-recipient-gone`.
6. **Given** the scenario's leading `# Prompt:` comment, **When** read,
   **Then** it also cites the "even when you have read the whole file"
   sentence and the "states only the current fact" sentence.

### User Story 3 - The eval agent file matches the prompt (Priority: P1)

1. **Given** `.claude/agents/wenchang-eval.md`, re-rendered with
   `uv run python -m evals render-agent`, **When**
   `tests/test_evals_agent.py` runs, **Then** the file equals
   `render_agent_file()`.

### Live check: the human's merge checkpoint (not a release gate, ADR 0028)

Baseline (AIE-1170, agent sha256 b668ca85...):

| Run | Commit | recall-replace-fact | Other scenarios in the set |
| --- | ------ | ------------------- | -------------------------- |
| A (serial) | 9c51a50 | 1/3 | 3/3 |
| B (3 shards) | a0b1e23 | 3/3 | 3/3 |

Required runs:

1. A targeted N=6 run with `--judge` over `recall-replace-fact`,
   `write-correct-seeded-fact`, `write-new-subject`, `forgetting-one-fact`,
   `forgetting-whole-file`, `forgetting-two-files`, `forgetting-only-fact`,
   `curated-correction`, and `curated-shared-conflict`. Target: 6/6 on
   each.
2. A full-corpus N=3 run with `--judge`, in 3 shards merged with
   `merge-runs`. Target: no scenario below its AIE-1170 rate.
   `remembering-stated-role` stays at 0/3; that is AIE-1182's issue.

Each run must report the agent sha256 and the commit that `review-pr.md`
records.

Miss policy:

1. If a run comes in under target, inspect the failing transcripts, adjust
   only the new sentences, and rerun.
2. After two rounds, the human decides.

### Edge Cases

- A system fact is wrong: the sentence covers only files the agent can
  write. curated_content.py still records the correction as a new line in
  a writable area. `curated-correction` and `curated-shared-conflict` are
  in the live set to check this.
- Out of scope: stale aliases or a stale description that name the old
  value (one live trial kept a "growth report" alias).
  - Dropping an alias needs `write_file`, and filing.py already owns the
    description rule.
  - No assertion checks them; US2.5 pins that they are not penalized.

## Requirements

- **FR-001**: Only new sentences are added. No existing sentence of
  `write_mechanics.BODY` is reworded.
- **FR-002**: No tool docstring, grader, scenario loader, or assertion
  kind changes.
- **FR-003**: `make check` passes.
