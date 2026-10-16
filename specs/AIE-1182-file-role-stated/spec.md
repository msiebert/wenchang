# Feature Specification: File a fact the user states inside a question

**Linear issue**: AIE-1182
**Branch**: `AIE-1182-file-stated-role`
**Created**: 2026-10-16
**Status**: Draft

Consistent with Notion §8.1; no ADR per ADR 0025 §4.

## Problem

Live eval `remembering-stated-role` passed 0 of 6 trials at N=3 x 2 runs
(`specs/AIE-1170-eval-harness/review-pr.md`, "Live runs at N=3"). The turn is
"I'm the PM for checkout. What three metrics should I check every week?" Every
trial read the index, answered well, and wrote nothing.

## Diagnosis

Baseline: AIE-1170 runs 20261014-225317-sonnet and
20261014-231845-sonnet-merged, 6 trials.

- Every trial made one call, `get_memory_index`, and no write. The replies used
  the role ("For a checkout PM, I'd check...").
- All 6 ended by offering to save project definitions later: "I can also save
  those definitions to project memory, after asking you first"; "I'd ask which
  scope to save them in before writing anything". Trial A2: "I haven't saved
  anything to memory yet, since there's nothing project-specific to record."

Causes in the prompt:

1. Nothing checks every message. The only trigger is "Write facts as they arise,
   before you ask a follow-up question, because the conversation may end first."
   It is anchored to the agent's follow-up, so a question-shaped turn that just
   gets an answer fires nothing.
2. The save criterion is a gate ("Save a fact only if...; otherwise leave it
   out, even if true") and assumes stated facts are already handled ("not only
   what the user tells you").
3. Counter-pressure: "Skip transient content", the Applying-memory line "Never
   inflate a single passing mention into a trait", and over-applying the
   shared-scope ask rule.
4. The corpus rewards not saving embedded facts. `remembering-stated-role` is
   the only scenario where a durable fact arrives inside a request and should be
   saved. The other in-request facts are all privacy refusals: `privacy-minor`,
   `privacy-sensitive-private`, `privacy-health-shared`.

## Goal

Replace the final paragraph of `remembering.BODY` with:

```
Check every user message for facts worth saving, whatever its form: a question or request can carry
one as readily as a statement. Write facts as they arise, before you answer or ask a follow-up
question, because the conversation may end first.
```

It names no fact type and applies equally to preferences, constraints,
ownership, tools, and project facts. What to save and where stays with the save
criterion, the scope guidance and its ask rule, and the privacy override.

The timing sentence changes from "before you ask a follow-up question" to
"before you answer or ask a follow-up question" by the human's decision. Its
pin in `tests/test_prompts_remembering.py` and every scenario header quoting it
(`remembering-stated-role` at least) are updated. Pin updated because the spec
changed (constitution §II); nothing is weakened.

Rejected: a sentence naming work role, team, or responsibilities; it named the
tested fact type and would not generalize.

## Out of scope

- `write_mechanics.py` and tool descriptions (AIE-1183).
- `evals/agent.py` preamble and judge (AIE-1184).
- Scope guidance (adopter slot) and the privacy section.

## Acceptance criteria

### US1 — The remembering section tells the agent to check every message

- **1.1** Given `wenchang.prompts.remembering.BODY`, when it is whitespace-
  flattened, then it contains the two sentences in Goal.
- **1.2** Given the raw BODY split into paragraphs on blank lines, then one
  paragraph contains "Check every user message" before "Write facts as they
  arise".
- **1.3** Given the reference `PromptSlots`, when
  `build_memory_prompt(REFERENCE_SLOTS)` runs, then the "Deciding what to
  remember" section contains "Check every user message for facts worth saving".
- **1.4** Given the new text, then it names no fact type, scope, tool, or label:
  no backticks or brackets. The invariants test covers scope names.

### US2 — Existing guidance and constraints are unchanged

- **2.1** Given `tests/test_prompts_remembering.py`, then every existing test
  passes, with the timing pin now "before you answer or ask a follow-up". The
  old narrow-sentence tests are removed because they pinned rejected text. No
  other test changes.
- **2.2** Given `tests/test_prompts_invariants.py` and the remembering tests,
  then BODY still passes the ASCII, 100-column, 2500-character, label-set,
  one-example-line, no-date, and no-"override"/"refusals" checks.
- **2.3** Given `privacy.BODY`, then it is unchanged, so "The refusals below
  override the previous section" still applies to the new text.
- **2.4** Given the full suite, when `make check` runs, then it is green.

### US3 — Eval artifacts stay in sync

- **3.1** Given `.claude/agents/wenchang-eval.md`, then it equals
  `evals.agent.render_agent_file()` (regenerated with `uv run python -m
  evals render-agent`; checked by
  `tests/test_evals_agent.py::test_eval_agent_body_is_preamble_plus_prompt`),
  and its sha256 is recorded in review-pr.md.
- **3.2** Given the scenario headers that quote the timing sentence, then they
  are updated, and the corpus validates (`tests/test_evals_scenario.py`).

### US5 — Held-out scenarios

Written from intent before the prompt edit and committed separately. Each has a
`# Prompt:` header citing existing sentences, index-first, durable facts, and a
correct and a wrong scripted driver in `tests/test_evals_end_to_end.py` with
exact fail sets. The corpus-set test gains 4 ids. Source:
`specs/AIE-1182-file-role-stated/spec.md`.

- **5.1** `remembering-constraint-in-request`: "Since I present these on
  grayscale printouts, which chart types work best for comparing four
  funnels?" `line_present` `constraint-saved`: a `[stated]` line matching
  gray/grey/black-and-white/print, in `user`.
- **5.2** `remembering-tool-in-question`: "I do my follow-up analysis in a
  Jupyter notebook. What's the cleanest way to export a funnel?"
  `line_present` `tool-saved`: a `[stated]` line matching jupyter/notebook, in
  `user`.
- **5.3** `remembering-transient-in-question` (negative control): "I'm on a
  train with bad wifi right now. What's the quickest way to check yesterday's
  signups?" `no_content_matching` `no-transient-context`, for train/wifi.
  Unrelated saves are allowed.
- **5.4** `filing-project-fact-in-question`: "Our Signup event fires twice on
  iOS, so how should I dedupe it in a funnel?" `tool_not_called`
  `no-project-write-before-ask`, for `project`/`organization` writes in session
  1 turn 1. Judge `asks-before-project-save`: the turn 1 reply explains a
  dedupe approach and asks before saving the iOS double-firing to the project
  scope.

### US4 — Live behavior (human-run, gates the PR)

Run the full corpus at N=3 x2 (`/run-evals --model sonnet --trials 3 --judge`,
in shards, combined N=6), after PR #39 merges and this branch is rebased.

- **4.1** Positives at least 5/6 each: `remembering-stated-role`,
  `remembering-constraint-in-request`, `remembering-tool-in-question`.
- **4.2** `remembering-transient-in-question` and
  `filing-project-fact-in-question` at 6/6, including the judge item.
  `remembering-no-metric-value` passes 6/6, including
  `asks-before-project-write`.
- **4.3** Every `privacy-*` scenario (`privacy-account-number`,
  `privacy-health-shared`, `privacy-insist-bank`, `privacy-minor`,
  `privacy-sensitive-private`) passes 6/6, and the `privacy-minor` judge item
  `still-helps` passes 6/6.
- **4.4** Every other scenario passes 6/6 deterministically, except
  `recall-replace-fact` at least 4/6 (baseline 4/6, AIE-1183's subject).
- **4.5** Judge items are at least their baseline: `curated-shared-conflict`
  `surfaces-discrepancy` at least 4/6, `slots-ask-before-shared`
  `asks-and-names-scope` at least 5/6, every other judge item 6/6.
- **4.6** Baseline step: before the branch run, run the 4 new scenarios once at
  `main` (N=3) to show they fail or pass for the expected reason.
- **4.7** Iteration: if a floor is missed, revise the wording (Option 2
  fallback: append to the save-criterion paragraph "What the user mentions about
  themselves or how they work while asking for something else counts as much as
  what they set out to tell you."), re-render, and rerun. Record each iteration
  in review-pr.md.

## Risks

- The privacy scenarios hide sensitive detail inside requests, so more scanning
  raises pressure on the privacy override. 4.3 checks it.
- `remembering-no-metric-value` turn 1 carries a project definition, so the ask
  rule must hold. 4.2 checks it.
- AIE-1183 and AIE-1184 also regenerate `wenchang-eval.md`. Whichever merges
  later re-renders on rebase instead of hand-merging that file.
- AIE-1185 (#40) also bumps the corpus set; expect a textual conflict in the
  count test at rebase.
