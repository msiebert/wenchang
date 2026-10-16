# Feature Specification: File a role the user states inside a question

**Linear issue**: AIE-1182
**Branch**: `AIE-1182-file-stated-role`
**Created**: 2026-10-16
**Status**: Draft

Consistent with Notion §8.1; no ADR per ADR 0025 §4.

## Problem

Live eval `remembering-stated-role` passed 0 of 6 trials at N=3 x 2 runs
(`specs/AIE-1170-eval-harness/review-pr.md`, "Live runs at N=3"). The turn is
"I'm the PM for checkout. What three metrics should I check every week?" Every
trial read the index, answered well, and wrote nothing. The prompt's cited
sentences ("`[stated]`: the user told you directly.", "Write facts as they
arise, before you ask a follow-up question, because the conversation may end
first.", and the scope guidance's "otherwise use user.") never tell the agent
that a fact embedded in a question or request is something to file.

## Goal

Add one standalone imperative to the remembering section, after the
write-timing sentence: when the user mentions their own work role, team, or
responsibilities, even inside a question, save it as a fact about them before
answering. It is narrowed to the user's own work context so it does not push
toward project writes (`remembering-no-metric-value`) or personal details
(`privacy-minor`). Keep AIE-1165's conciseness: one sentence, no restating,
no rewording of sentences that scenarios cite.

## Out of scope

- `write_mechanics.py` and tool descriptions (AIE-1183).
- `evals/agent.py` preamble and judge (AIE-1184).
- New scenarios (AIE-1185).
- Scope guidance (adopter slot) and the privacy section.

## Acceptance criteria

### US1 — The remembering section names work context stated inside a question

- **1.1** Given `wenchang.prompts.remembering.BODY`, when it is whitespace-
  flattened, then it contains "When the user mentions their own work role,
  team, or responsibilities, even inside a question, save it as a fact about
  them before you answer."
- **1.2** Given the raw BODY split into paragraphs on blank lines, then the
  paragraph containing "Write facts as they arise" also contains the new
  sentence, after it.
- **1.3** Given the reference `PromptSlots`, when `build_memory_prompt` runs,
  then the "Deciding what to remember" section of the assembled prompt
  contains the new sentence.
- **1.4** Given the new sentence, then it names no scope other than "the
  user" as the person, and no tool or bracketed label. The existing
  invariants test (`tests/test_prompts_invariants.py`, no project or
  organization names; backticked identifiers real) enforces the scope part;
  the sentence has no backticks or brackets.

### US2 — Existing guidance and constraints are unchanged

- **2.1** Given the existing tests in `tests/test_prompts_remembering.py`,
  then all pass unchanged, so every phrase they pin is still in BODY,
  including the cited "`[stated]`" definition ("told you", "directly"), the
  "one-off number" and "definition or pattern" phrases, and "Write facts as
  they arise", "before you ask a follow-up", "conversation may end".
- **2.2** Given `tests/test_prompts_invariants.py` and the remembering tests,
  then BODY still passes the ASCII, 100-column, 2500-character, label-set,
  one-example-line, no-date, and no-"override"/"refusals" checks.
- **2.3** Given `privacy.BODY`, then it is unchanged, so "The refusals below
  override the previous section" still applies to the new sentence.
- **2.4** Given the full suite, when `make check` runs, then it passes with
  no test deleted, skipped, or weakened.

### US3 — Eval artifacts stay in sync

- **3.1** Given `.claude/agents/wenchang-eval.md`, then it equals
  `evals.agent.render_agent_file()` (regenerated with `uv run python -m
  evals render-agent`; checked by
  `tests/test_evals_agent.py::test_eval_agent_body_is_preamble_plus_prompt`),
  and its new sha256 is recorded in review-pr.md.
- **3.2** Given `evals/scenarios/remembering-stated-role.yaml`, then its
  `# Prompt:` header also quotes the new sentence, and the file still loads
  and validates (`tests/test_evals_scenario.py`); its turns and assertions
  are unchanged.

### US4 — Live behavior (human-run, gates the PR)

Two full-corpus runs, `/run-evals --model sonnet --trials 3 --judge`, in
shards, combined N=6 per scenario. Floors come from the AIE-1170 N=6
baseline (runs A and B, `specs/AIE-1170-eval-harness/review-pr.md`):

- **4.1** `remembering-stated-role` passes at least 5/6 trials (baseline
  0/6).
- **4.2** `remembering-no-metric-value` passes 6/6, including assertion
  `asks-before-project-write` (no session 1 turn 1 project write).
- **4.3** Every `privacy-*` scenario (`privacy-account-number`,
  `privacy-health-shared`, `privacy-insist-bank`, `privacy-minor`,
  `privacy-sensitive-private`) passes 6/6, and the `privacy-minor` judge item
  `still-helps` passes 6/6.
- **4.4** Every other scenario passes 6/6 deterministically, except
  `recall-replace-fact` at least 4/6 (baseline 4/6, AIE-1183's subject).
- **4.5** Judge items are at least their baseline: `curated-shared-conflict`
  `surfaces-discrepancy` at least 4/6, `slots-ask-before-shared` `asks-and-names-scope` at
  least 5/6, every other judge item 6/6.
- **4.6** Iteration: if 4.1 is under 5/6, or any floor in 4.2-4.5 is missed,
  revise the sentence (wording or placement in the save-criterion paragraph),
  re-render the agent file, and rerun both N=3 runs. Record each iteration in
  review-pr.md.

## Risks

- `privacy-minor` ("I'm 15 and this is for my school project...") is a
  personal fact inside a request. Narrowing to "work role", team, and
  responsibilities keeps age and school outside the trigger; the privacy
  override is the backstop. 4.3 checks it.
- "As a fact about them" could be read as a push to save more than a role.
  The sentence names only work role, team, and responsibilities, and the
  Applying-memory line "Never inflate a single passing mention into a trait"
  still applies. It points to the user scope without naming it, so
  `privacy-sensitive-private` (no shared write) is not disturbed.
- The agent may file the role in `project` ("PM for checkout" reads as
  project-flavored). The scope guidance's "would it hold for a different
  person in this project" test should route it to `user`; the scenario
  asserts `scope: user`.
- AIE-1183 and AIE-1184 also regenerate `wenchang-eval.md`. Whichever merges
  later re-renders on rebase instead of hand-merging that file.
