# PR Review: AIE-1183 — Corrections use replace_fact, not a full-file overwrite

> **Live evals are pending.** They are the human's merge checkpoint, not a
> release gate (ADR 0028). See "Live evals — PENDING" below.

## What changed & why

The AIE-1170 N=3 live runs found `recall-replace-fact` passing 4 of 6
trials. In the failing trials the session-2 agent read the file, then
corrected it with `write_file` (a whole-file overwrite) instead of
`replace_fact`. The end state had one recipient line, but it kept
"(previously sent to the growth team)".

- **Prompt.** Two sentences are added to `write_mechanics.BODY`. Existing
  sentences are verbatim.
  - "To correct a fact stored in a file you can write, use `replace_fact`
    even when you have read the whole file; never rewrite the file with
    `write_file` to change a fact."
  - "A correcting `new_string` states only the current fact, with no
    "previously" or "instead of" clause, and leaves no note of the old
    value."
- **Eval.** `recall-replace-fact.yaml` gains a `line_absent` assertion,
  `old-recipient-gone` (`(?i)growth`, `scope: user`). Two new scripted
  drivers prove it: one reproduces the live failure, one has a session-1
  alias and description naming "growth" that must not be penalized.
- **Agent file.** `.claude/agents/wenchang-eval.md` is re-rendered.

## Acceptance criteria → tests

Prompt tests are in `tests/test_prompts_write_mechanics.py`. Eval tests are
in `tests/test_evals_end_to_end.py` (e2e), `tests/test_evals_scenario.py`
(scn), and `tests/test_evals_agent.py` (agt).

| Acceptance criterion | Test(s) |
| -------------------- | ------- |
| US1.1 one sentence with "even when you have read the whole file" and its terms | `test_correction_uses_replace_fact_even_after_full_read` |
| US1.2 one sentence with "states only the current fact" and its terms | `test_correcting_new_string_states_only_current_fact` |
| US1.3 existing phrases, anchors, forbidden terms, size limits unchanged | existing tests in `test_prompts_write_mechanics.py` and `tests/test_prompts_invariants.py`, unchanged and green |
| US2.1 `old-recipient-gone` loads with pattern and scope; US2.6 prompt comment cites both sentences | scn corpus test (`test_corpus_loads_with_unique_ids` and the prompt-cite check in `test_corpus_is_the_planned_set`) |
| US2.2 correct driver passes every assertion | e2e `test_correct_driver_passes_every_assertion[recall-replace-fact]` |
| US2.3 wrong driver fails exactly `{replaced-in-session-2, one-recipient-line, old-recipient-gone}` | e2e `test_wrong_driver_fails_exactly_the_listed_assertions[recall-replace-fact]` |
| US2.4 live-failure driver fails exactly `{replaced-in-session-2, old-recipient-gone}` | e2e `test_recall_replace_fact_flags_a_previously_clause` |
| US2.5 stale alias and description not penalized | e2e `test_recall_replace_fact_ignores_stale_metadata` |
| US3.1 agent file equals `render_agent_file()` | agt `test_eval_agent_body_is_preamble_plus_prompt` |

## Architecture / ADR changes

- None. No module boundary, public API, or storage semantics change.
- Considered and rejected: a sentence in the `write_file` docstring. ADR
  0025 decision 6 gives the prompt ownership of tool choice and the
  docstrings ownership of per-call mechanics. This change keeps that split,
  so no tool description changes.

## Deviations from spec

- None.

## Look closely at

- **"A file you can write" scoping.** The first sentence covers only
  writable files. A wrong system fact is still recorded as a new line in a
  writable area per `curated_content.py`. `curated-correction` and
  `curated-shared-conflict` are in the live set to check this.
- **Stale aliases and description are out of scope.** A live trial kept a
  "growth report" alias. Dropping an alias needs `write_file`, and
  `filing.py` owns the description rule. `old-recipient-gone` must not
  penalize them (US2.5).
- **`line_absent` scans only end-state content lines.** That is why it is
  used instead of `no_content_matching`, which also scans session 1's
  legitimate write.

## Follow-ups

- Stale alias and description cleanup on a correction. There is no
  assertion kind for alias absence, so it cannot be graded yet.
- Merge conflicts: `.claude/agents/wenchang-eval.md` is generated, and
  AIE-1182 and AIE-1184 also change its inputs. Resolve by re-rendering
  with `uv run python -m evals render-agent`, not by hand-merging. AIE-1185
  touches `CASES` in the end-to-end tests.

## Live evals — PENDING (human merge checkpoint)

This is the human's merge checkpoint, not a release gate (ADR 0028).

- **Agent file sha256 for this branch:**
  `c9076b7d4303c2f45de147cf0ee1b3cc5758b2ffa595df0360d1b74472236e06`
- **Commit:** the PR head commit. Every run's `run.json` git commit must
  equal it, and its agent sha256 must equal the value above. If the branch
  changes, re-render the agent file and update both here.

### Baseline (AIE-1170, agent sha256 b668ca85...)

| Run | Commit | Agent sha256 | recall-replace-fact | Others in the targeted set |
| --- | ------ | ------------ | ------------------- | -------------------------- |
| A (serial) | 9c51a50 | b668ca85... | 1/3 | 3/3 |
| B (3 shards merged) | a0b1e23 | b668ca85... | 3/3 | 3/3 |

### Run 1: targeted, N=6

Launch from the worktree root:

```
CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 claude --mcp-config evals/mcp.json --strict-mcp-config --allowedTools mcp__wenchang "Bash(uv run python -m evals *)" --settings '{"includeGitInstructions": false}'
/run-evals --model sonnet --trials 6 --judge recall-replace-fact write-correct-seeded-fact write-new-subject forgetting-one-fact forgetting-whole-file forgetting-two-files forgetting-only-fact curated-correction curated-shared-conflict
```

Target: 6/6 on each scenario.

### Run 2: full corpus, N=3 in 3 shards (required)

```
CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 claude -p "/run-evals --model sonnet --trials 3 --judge --shard 1/3" --mcp-config evals/mcp.json --strict-mcp-config --allowedTools mcp__wenchang "Bash(uv run python -m evals *)" --settings '{"includeGitInstructions": false}'
```

Repeat for `--shard 2/3` and `--shard 3/3`; the shards can run
concurrently. Then merge:

```
uv run python -m evals merge-runs evals/runs/<name> <shard run dirs...>
```

Target: no scenario below its AIE-1170 rate. `remembering-stated-role`'s
0/3 belongs to AIE-1182.

### Miss policy

If a run is under target, inspect the failing transcripts, adjust only the
two new sentences, and rerun. After two rounds, the human decides.

### Results

PENDING.

| Run | Commit | Agent sha256 | recall-replace-fact | Others in the targeted set / full-corpus notes |
| --- | ------ | ------------ | ------------------- | ---------------------------------------------- |
| 1 (targeted, N=6) | TBD | TBD | TBD | TBD |
| 2 (full corpus, N=3, merged) | TBD | TBD | TBD | TBD |
