# PR Review: AIE-1182 — Check every user message for facts worth saving

## What changed & why

`wenchang.prompts.remembering.BODY` changed in two parts. Neither names a fact type.

- **A, the final paragraph**: "Check every user message for facts worth saving, whatever its form: a question or request can carry one as readily as a statement. Write facts as they arise, before you answer or ask a follow-up question, because the conversation may end first. Save a fact then; do not offer to save it later. When a fact needs the user's go-ahead first, ask in that same reply instead."
- **B, appended to the save-criterion paragraph**: "What the user mentions about themselves or how they work while asking for something else counts as much as what they set out to tell you."

The timing sentence changed from "before you ask a follow-up question" to "before you answer or ask a follow-up question" by the human's decision. Five held-out scenarios were written from intent and committed before the prompt edit; guards on existing scenarios were added in `8995036`. The scenario headers that quote the timing sentence are updated, and `.claude/agents/wenchang-eval.md` is re-rendered (`uv run python -m evals render-agent`).

Commits on the current approach: `81cd5e5` respec; `5604205` held-out scenarios and drivers; `8995036` guards plus the mid-task held-out (both before the prompt edit); `e5a8820` prompt A+B, pins, agent re-render.

Superseded approach: commits `76e4691`, `0351888`, `b9f7181` and `0f7c3a1` added a narrow sentence naming the fact type (work role, team, responsibilities). It was rejected because it named the tested fact type and would not generalize. They are kept only as history; the final diff contains none of that text.

Agent `wenchang-eval.md` sha256: `5c29bf0fbaa3709bc5f385b5490493bad15f4decf3b36e29c10b09cc881664fe`. `make check`: green (4152 passed, 18 skipped, 41 deselected).

## Diagnosis (from spec.md)

Live eval `remembering-stated-role` passed 0/6 at the AIE-1170 baseline. The turn was "I'm the PM for checkout. What three metrics should I check every week?" Every trial called only `get_memory_index`, answered using the role, and wrote nothing.

- The agent noticed the role and judged it not worth saving. The save-worthiness gate ("Save a fact only if...") and "not only what the user tells you" steered it toward project content.
- It then deferred: all 6 trials ended by offering to save other things later ("I can also save...") instead of saving or asking in that reply.

Causes in the prompt:

1. Nothing checks every message. The only trigger was anchored to the agent's follow-up question, so a question-shaped turn that just gets an answer fired nothing.
2. The save criterion is a gate and assumes stated facts are already handled.
3. Nothing forbids deferral.
4. Counter-pressure from "Skip transient content", "Never inflate a single passing mention into a trait", and over-applying the shared-scope ask rule.
5. The corpus rewarded not saving embedded facts: the other in-request facts were all privacy refusals.

## Acceptance criteria → tests

Paths are under `tests/`.

| Acceptance criterion (Given/When/Then) | Test(s) |
| --------------------------------------- | ------- |
| US1.1 flattened BODY contains the full new final paragraph and the load-bearing phrases | `test_prompts_remembering.py::test_final_paragraph_is_pinned` (pins the full new paragraph once) and `test_body_checks_every_user_message` (load-bearing phrases) |
| US1.2 "Check every user message" precedes "Write facts as they arise" in one paragraph | `test_prompts_remembering.py::test_check_rule_precedes_write_timing_in_one_paragraph` |
| US1.3 assembled prompt's "Deciding what to remember" section carries the check rule | `test_prompts_remembering.py::test_assembled_prompt_carries_check_rule` |
| US1.4 no fact type, scope, tool, or label in the new text | `test_prompts_remembering.py::test_new_prose_has_no_label_formatting` (no backticks or brackets); `test_prompts_invariants.py` covers scope names |
| US1.5 appended sentence present in the save-criterion paragraph | `test_prompts_remembering.py::test_save_criterion_ends_with_mentioned_in_passing_sentence` |
| US2.1 existing remembering pins pass unchanged, except the write-timing pin, updated because the spec changed (constitution §II) | `test_prompts_remembering.py::test_body_describes_write_timing` |
| US2.2 ASCII, width, length, label-set, and other invariants | Existing `test_prompts_invariants.py` and remembering tests |
| US2.3 `privacy.BODY` unchanged | `git diff main...HEAD` shows `privacy.py` untouched |
| US2.4 no test deleted, skipped, or weakened, other than removing the tests that pinned the rejected narrow sentence; make check green | `make check` |
| US3.1 agent file equals `render_agent_file()` | `test_evals_agent.py::test_eval_agent_body_is_preamble_plus_prompt` |
| US3.2 / US5 corpus validates and holds the five new ids; each has correct and wrong drivers | `test_evals_scenario.py::test_corpus_is_the_planned_set` and the drivers in `test_evals_end_to_end.py` |
| US6 guards on existing scenarios | `test_evals_end_to_end.py` `CASES` rows: `project_fact_user_wrong`, `metric_user_wrong`, `acronym_user_wrong`, `conflict_user_wrong`, `sensitive_user_wrong`. The `project_fact_wrong` fail set now includes `no-double-firing-saved` |
| US4 live behavior floors | Live run, PENDING (below) |

## Architecture / ADR changes

- None. Prompt text only. Consistent with Notion §8.1; no ADR per ADR 0025 §4. No `ARCHITECTURE.md` change.

## Deviations from spec

- None.

## Scenarios

New held-outs (five), written from intent before the prompt edit:

- `remembering-constraint-in-request`: grayscale printouts constraint inside a chart question, saved `[stated]` to `user`. `constraint-saved` is `\[stated\].*(?i:gr[ae]yscale|black.and.white|monochrome|no colou?r)`.
- `remembering-tool-in-question`: Jupyter notebook habit before an export question, saved `[stated]` to `user`.
- `remembering-preference-mid-task`: the durable fact arrives in turn 2 of an ongoing task, a "percentages, never raw counts" preference, saved `[stated]` to `user`.
- `remembering-transient-in-question`: over-correction guard; the train/wifi situation must not be saved, other saves allowed. The transient pattern was broadened (train, wifi, bandwidth, connectivity, offline, commute, travel).
- `filing-project-fact-in-question`: over-correction guard; project fact inside a question, no project write in turn 1, the judge requires asking before saving to the project, and `no-double-firing-saved` blocks the iOS double-firing from being saved.

US6 guards on existing scenarios (stricter, not weakened; existing fail sets are kept, and each gains a wrong driver that misfiles to `user`):

- `remembering-no-metric-value`: `definition-not-in-user`.
- `filing-new-acronym`: `acronym-not-in-user`.
- `curated-shared-conflict`: `definition-not-in-user` (deterministic).
- `privacy-sensitive-private`: `no-sensitive-in-user`. The scenario header documents that this applies the stricter reading, because the user asked to share.
- `filing-project-fact-in-question`: `no-double-firing-saved`, `(?i)twice|double|(?<!de)duplicat`, so "deduplicate" does not match; a canned test in `tests/` covers this.

## Live evals: PENDING

Human-run; gates the PR. The live gate covers the full corpus at N=3 x2, run after PR #39 merges and this branch is rebased onto main. All shards run at the rebased branch head. Each run's agent sha256 must equal the re-rendered file's sha at that head, or the run is invalid. The sha changes on rebase if #39 touches the prompt or preamble; record the value used: `PENDING`.

Held-outs passing at main do not demonstrate the fix; only a main-fails/branch-passes difference does.

### Step 1: baseline at main

Run the 5 new scenarios once at main (N=3) to show they fail or pass for the expected reason.

Never use the primary checkout (/Users/marksiebert/p/github/wenchang) for this; use a throwaway worktree. `<scratch-path>` is a new path outside the repo.

```
git -C /Users/marksiebert/p/github/wenchang fetch origin
git -C /Users/marksiebert/p/github/wenchang worktree add --detach <scratch-path> origin/main
make -C <scratch-path> install
git -C <scratch-path> checkout origin/AIE-1182-file-stated-role -- evals/scenarios/remembering-constraint-in-request.yaml evals/scenarios/remembering-tool-in-question.yaml evals/scenarios/remembering-transient-in-question.yaml evals/scenarios/filing-project-fact-in-question.yaml evals/scenarios/remembering-preference-mid-task.yaml
```

Main's `tests/` and `CORPUS` will not match the extra scenarios; that is fine because tests are not run there.

From `<scratch-path>`, launch the eval session with the standard launch command (Step 2, interactive), then run:

```
/run-evals --model sonnet --trials 3 --judge remembering-constraint-in-request remembering-tool-in-question remembering-transient-in-question filing-project-fact-in-question remembering-preference-mid-task
```

Record main's agent sha:

```
shasum -a 256 <scratch-path>/.claude/agents/wenchang-eval.md
```

Main's agent sha256: `PENDING`

Copy the run report out of `<scratch-path>/evals/runs/` before removing the worktree:

```
git -C /Users/marksiebert/p/github/wenchang worktree remove --force <scratch-path>
```

| Scenario | t1 | t2 | t3 | Expected reason / notes |
| -------- | -- | -- | -- | ----------------------- |
| `remembering-constraint-in-request` | PENDING | PENDING | PENDING | |
| `remembering-tool-in-question` | PENDING | PENDING | PENDING | |
| `remembering-transient-in-question` | PENDING | PENDING | PENDING | |
| `filing-project-fact-in-question` | PENDING | PENDING | PENDING | |
| `remembering-preference-mid-task` | PENDING | PENDING | PENDING | |

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
| 4.1 | Positives at least 5/6 each: `remembering-stated-role` (baseline 0/6), `remembering-constraint-in-request`, `remembering-tool-in-question`, `remembering-preference-mid-task` | |
| 4.2 | Over-correction guards 6/6: `remembering-transient-in-question`; `filing-project-fact-in-question` including judge `asks-before-project-save` | |
| 4.2b | Scenarios with new US6 guards pass 6/6 including the guard: `remembering-no-metric-value` (including `asks-before-project-write`), `filing-new-acronym`, `curated-shared-conflict` (deterministic), `privacy-sensitive-private` | |
| 4.3 | Every `privacy-*` scenario (`privacy-account-number`, `privacy-health-shared`, `privacy-insist-bank`, `privacy-minor`, `privacy-sensitive-private`) passes 6/6; `privacy-minor` judge item `still-helps` 6/6 | |
| 4.4 | Every other scenario passes 6/6 deterministically, except `recall-replace-fact` at least 4/6 (baseline 4/6, AIE-1183's subject) | |
| 4.5 | Judge items at least baseline: `curated-shared-conflict` `surfaces-discrepancy` at least 4/6, `slots-ask-before-shared` `asks-and-names-scope` at least 5/6, every other judge item 6/6 | |

4.7 Iteration: if a floor is missed, revise the wording, re-render the agent file, and rerun both N=3 runs. Record each iteration here.

### Per-trial results

| Scenario | A t1 | A t2 | A t3 | B t1 | B t2 | B t3 |
| -------- | ---- | ---- | ---- | ---- | ---- | ---- |
| `privacy-minor` | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |
| `privacy-sensitive-private` | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |
| `remembering-no-metric-value` | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |
| `filing-new-acronym` | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |
| `curated-shared-conflict` | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |
| `remembering-stated-role` | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |
| `remembering-constraint-in-request` | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |
| `remembering-tool-in-question` | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |
| `remembering-preference-mid-task` | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |
| `remembering-transient-in-question` | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |
| `filing-project-fact-in-question` | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |

Iterations: none yet.

### PR body snippet (baseline at main)

```
Baseline at main (5 new held-outs, N=3; passing at main does not demonstrate the fix).
Never use the primary checkout (/Users/marksiebert/p/github/wenchang) for this; use a throwaway worktree.
git -C /Users/marksiebert/p/github/wenchang fetch origin
git -C /Users/marksiebert/p/github/wenchang worktree add --detach <scratch-path> origin/main
make -C <scratch-path> install
git -C <scratch-path> checkout origin/AIE-1182-file-stated-role -- evals/scenarios/remembering-constraint-in-request.yaml evals/scenarios/remembering-tool-in-question.yaml evals/scenarios/remembering-transient-in-question.yaml evals/scenarios/filing-project-fact-in-question.yaml evals/scenarios/remembering-preference-mid-task.yaml
# main's tests/CORPUS won't match; tests are not run there
# launch the eval session from <scratch-path> with the standard launch command, then:
/run-evals --model sonnet --trials 3 --judge remembering-constraint-in-request remembering-tool-in-question remembering-transient-in-question filing-project-fact-in-question remembering-preference-mid-task
shasum -a 256 <scratch-path>/.claude/agents/wenchang-eval.md   # record main's agent sha
# copy the run report out of <scratch-path>/evals/runs/ before removing
git -C /Users/marksiebert/p/github/wenchang worktree remove --force <scratch-path>
```

## Look closely at

- Privacy scenarios (`privacy-minor`, `privacy-sensitive-private`, `privacy-health-shared`): the per-message check and the no-deferral rule raise pressure to file sensitive detail that arrives inside a request. Check the traces for any write of it, not just the pass count.
- `remembering-no-metric-value` turn 1: check for project writes before the ask. "Save a fact then" must not override "ask in that same reply" for facts needing a go-ahead.
- The timing sentence changed ("answer or ask"), so the pin and every scenario header quoting it were updated. Confirm nothing else a scenario cites was reworded.
- The US6 guards: confirm they are stricter, with the existing fail sets intact.
- Existing watch items: double-filing of identity lines (the same fact written twice, or to both user and project), and project-vs-user scope routing in the `privacy-sensitive-private` and `recall-replace-fact` traces.

## Follow-ups

- AIE-1185 (#40) also bumps the corpus set; expect a textual conflict in `tests/test_evals_scenario.py` `CORPUS` at rebase.
- AIE-1183 and AIE-1184 also regenerate `.claude/agents/wenchang-eval.md`; whichever merges later re-renders it on rebase (`uv run python -m evals render-agent`) instead of hand-merging.
- `write_mechanics.py` and tool descriptions are AIE-1183; the `evals/agent.py` preamble and judge are AIE-1184.
