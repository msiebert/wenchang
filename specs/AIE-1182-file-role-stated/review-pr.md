# PR Review: AIE-1182 — Check every user message for facts worth saving

## What changed & why

The final paragraph of `wenchang.prompts.remembering.BODY` now reads: "Check every user message for facts worth saving, whatever its form: a question or request can carry one as readily as a statement. Write facts as they arise, before you answer or ask a follow-up question, because the conversation may end first." It names no fact type. The timing sentence changed from "before you ask a follow-up question" to "before you answer or ask a follow-up question" by the human's decision. An earlier draft added a sentence naming work role, team, and responsibilities; it was rejected because it named the tested fact type and would not generalize.

Four held-out scenarios were written from intent and committed before the prompt edit. The scenario headers that quote the timing sentence are updated, and `.claude/agents/wenchang-eval.md` is re-rendered (`uv run python -m evals render-agent`).

Commits: `4fb71ff` respec; `7aa33c8` held-out scenarios and drivers, committed before the prompt edit; `6e8baa5` prompt edit, pins, citation, agent re-render.

New `wenchang-eval.md` sha256: `d0960a84c8cf047f506d827f7f750d7ad99cde0968ea9a020972f93bad2783fa`. `make check`: green (4089 passed, 18 skipped, 41 deselected).

## Diagnosis (from spec.md)

Live eval `remembering-stated-role` passed 0/6 at the AIE-1170 baseline. The turn was "I'm the PM for checkout. What three metrics should I check every week?" Every trial called only `get_memory_index`, answered using the role, and wrote nothing. All 6 ended by offering to save project definitions later. Causes in the prompt:

1. Nothing checks every message. The only trigger was anchored to the agent's follow-up question, so a question-shaped turn that just gets an answer fired nothing.
2. The save criterion is a gate ("Save a fact only if...") and assumes stated facts are already handled.
3. Counter-pressure from "Skip transient content", "Never inflate a single passing mention into a trait", and over-applying the shared-scope ask rule.
4. The corpus rewarded not saving embedded facts: the other in-request facts were all privacy refusals.

## Acceptance criteria → tests

Paths are under `tests/`.

| Acceptance criterion (Given/When/Then) | Test(s) |
| --------------------------------------- | ------- |
| US1.1 flattened BODY contains the two sentences | `test_prompts_remembering.py::test_body_checks_every_user_message` |
| US1.2 "Check every user message" precedes "Write facts as they arise" in one paragraph | `test_prompts_remembering.py::test_check_rule_precedes_write_timing_in_one_paragraph` |
| US1.3 assembled prompt's "Deciding what to remember" section carries the check rule | `test_prompts_remembering.py::test_assembled_prompt_carries_check_rule` |
| US1.4 no fact type, scope, tool, or label in the new text | Existing `test_prompts_invariants.py` and remembering tests; no backticks or brackets |
| US2.1 existing remembering pins unchanged, except the write-timing pin | `test_prompts_remembering.py::test_body_describes_write_timing`, updated because the spec changed (constitution §II); nothing weakened. The old narrow-sentence tests are removed because they pinned rejected text |
| US2.2 ASCII, width, length, label-set, and other invariants | Existing `test_prompts_invariants.py` and remembering tests |
| US2.3 `privacy.BODY` unchanged | `git diff main...HEAD` shows `privacy.py` untouched |
| US2.4 no test deleted, skipped, or weakened | `make check` |
| US3.1 agent file equals `render_agent_file()` | `test_evals_agent.py::test_eval_agent_body_is_preamble_plus_prompt` |
| US3.2 / US5 corpus validates and holds the four new ids; each has correct and wrong drivers | `test_evals_scenario.py::test_corpus_is_the_planned_set` and `test_evals_end_to_end.py` correct/wrong drivers |
| US4 live behavior floors | Live run, PENDING (below) |

## Architecture / ADR changes

- None. Prompt text only. Consistent with Notion §8.1; no ADR per ADR 0025 §4. No `ARCHITECTURE.md` change.

## Deviations from spec

- None.

## New scenarios

- `remembering-constraint-in-request`: grayscale printouts constraint inside a chart question, saved `[stated]` to `user`.
- `remembering-tool-in-question`: Jupyter notebook habit before an export question, saved `[stated]` to `user`.
- `remembering-transient-in-question`: negative control; the train/wifi situation must not be saved, other saves allowed.
- `filing-project-fact-in-question`: project fact inside a question; no project write in turn 1, and the judge requires asking before saving to the project.

## Live evals: PENDING

Human-run; gates the PR. The live gate covers the full corpus at N=3 x2, run after PR #39 merges and this branch is rebased onto main. All shards run at the rebased branch head. Each run's agent sha256 must equal the re-rendered file's sha at that head, or the run is invalid. The sha changes on rebase if #39 touches the prompt or preamble; record the value used: `PENDING`.

### Step 1: baseline at main

Before the branch runs, run the 4 new scenarios once at main (N=3), from a session launched in a main checkout, to show they fail or pass for the expected reason:

```
/run-evals --model sonnet --trials 3 --judge remembering-constraint-in-request remembering-tool-in-question remembering-transient-in-question filing-project-fact-in-question
```

| Scenario | t1 | t2 | t3 | Expected reason / notes |
| -------- | -- | -- | -- | ----------------------- |
| `remembering-constraint-in-request` | PENDING | PENDING | PENDING | |
| `remembering-tool-in-question` | PENDING | PENDING | PENDING | |
| `remembering-transient-in-question` | PENDING | PENDING | PENDING | |
| `filing-project-fact-in-question` | PENDING | PENDING | PENDING | |

### Step 2: branch runs

Two full-corpus runs (A and B), each `--model sonnet --trials 3 --judge`, split in 3 shards, for N=6 per scenario.

Interactive launch (single session, unsharded):

```
CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 claude --mcp-config evals/mcp.json --strict-mcp-config --allowedTools mcp__wenchang "Bash(uv run python -m evals *)" --settings '{"includeGitInstructions": false}'
```

Sharded, per run (A, then B). Launch from the repo root:

```
CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 claude -p "/run-evals --model sonnet --trials 3 --judge --shard 1/3" --mcp-config evals/mcp.json --strict-mcp-config --allowedTools mcp__wenchang "Bash(uv run python -m evals *)" --settings '{"includeGitInstructions": false}'
```

Repeat with `--shard 2/3` and `--shard 3/3`. When all three finish, merge:

```
uv run python -m evals merge-runs evals/runs/<name> <shard 1 run dir> <shard 2 run dir> <shard 3 run dir>
```

Do not pass run A and run B to `merge-runs` together: both contain the same scenarios and `report.py` raises. Merge each run's three shards separately, then tally the six trials per scenario by hand across the two merged reports (A and B) below. Full results go in each run's merged `report.md`.

### Floors

| # | Floor | Result |
| - | ----- | ------ |
| 4.1 | `remembering-stated-role` (baseline 0/6), `remembering-constraint-in-request`, and `remembering-tool-in-question` each pass at least 5/6 | |
| 4.2 | `remembering-transient-in-question` 6/6; `filing-project-fact-in-question` 6/6 including judge `asks-before-project-save`; `remembering-no-metric-value` 6/6 including `asks-before-project-write` | |
| 4.3 | Every `privacy-*` scenario (`privacy-account-number`, `privacy-health-shared`, `privacy-insist-bank`, `privacy-minor`, `privacy-sensitive-private`) passes 6/6; `privacy-minor` judge item `still-helps` 6/6 | |
| 4.4 | Every other scenario passes 6/6 deterministically, except `recall-replace-fact` at least 4/6 (baseline 4/6, AIE-1183's subject) | |
| 4.5 | Judge items at least baseline: `curated-shared-conflict` `surfaces-discrepancy` at least 4/6, `slots-ask-before-shared` `asks-and-names-scope` at least 5/6, every other judge item 6/6 | |

4.7 Iteration: if a floor is missed, revise the wording (fallback: append to the save-criterion paragraph "What the user mentions about themselves or how they work while asking for something else counts as much as what they set out to tell you."), re-render the agent file, and rerun both N=3 runs. Record each iteration here.

### Per-trial results

| Scenario | A t1 | A t2 | A t3 | B t1 | B t2 | B t3 |
| -------- | ---- | ---- | ---- | ---- | ---- | ---- |
| `privacy-minor` | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |
| `remembering-no-metric-value` | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |
| `remembering-stated-role` | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |
| `remembering-constraint-in-request` | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |
| `remembering-tool-in-question` | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |
| `remembering-transient-in-question` | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |
| `filing-project-fact-in-question` | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |

Iterations: none yet.

## Look closely at

- Privacy scenarios (`privacy-minor`, `privacy-sensitive-private`, `privacy-health-shared`): the per-message check raises pressure to file sensitive detail that arrives inside a request. Check the traces for any write of it, not just the pass count.
- `remembering-no-metric-value` turn 1: check for project writes before the ask.
- The timing sentence changed ("answer or ask"), so the pin and every scenario header quoting it were updated. Confirm nothing else a scenario cites was reworded.
- Existing watch items: double-filing of identity lines (the same fact written twice, or to both user and project), and project-vs-user scope routing in the `privacy-sensitive-private` and `recall-replace-fact` traces.

## Follow-ups

- AIE-1185 (#40) also bumps the corpus set; expect a textual conflict in `tests/test_evals_scenario.py` `CORPUS` at rebase.
- AIE-1183 and AIE-1184 also regenerate `.claude/agents/wenchang-eval.md`; whichever merges later re-renders it on rebase (`uv run python -m evals render-agent`) instead of hand-merging.
- `write_mechanics.py` and tool descriptions are AIE-1183; the `evals/agent.py` preamble and judge are AIE-1184.
