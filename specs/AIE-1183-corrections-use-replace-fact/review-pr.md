# PR Review: AIE-1183 — A changed fact states only what is true now

## What changed & why

**Diagnosis** (AIE-1170 N=3 live runs):

- 11 of 12 superseding writes kept history. Only 2 of 12 used `write_file`.
- `write-correct-seeded-fact` silently failed 6 of 6 (for example "(changed from PDF)"). It had no absence assertion.
- The prompt had no current-truth principle. Forgetting's no-trace rule ("Removal is total") covers only removal.

**Fix** (general, not scenario-specific):

- One new Forgetting paragraph: a changed fact's old value is gone.
- One new Write-mechanics sentence: changing one fact is still `replace_fact` for a one-line file or a metadata change.
- The earlier branch text was rejected because it quoted the failing trials' phrasing. It is removed (`test_no_trial_phrasing`).
- Stale aliases are out of scope.

### Final text

`src/wenchang/prompts/forgetting.py` (new paragraph):

> When a fact changes, its old value is gone too: rewrite the line to state only what is true now, as though it had always read that way, with no note, date, or comparison recording the change. Keep an earlier value only if the user asks you to keep a record of it.

`src/wenchang/prompts/write_mechanics.py` (new sentence):

> Changing one fact is still `replace_fact` when it is the file's only line or when the change also updates `description` or `aliases`.

### Held-out evidence (commit d8d4c24, before the prompt commit)

- `write-correct-seeded-fact`: new `line_absent` assertion `old-format-gone`. The append wrong driver fails exactly `{replaced-quoting-old, one-format-line, old-format-gone}`.
- `write-superseded-tool`: one-line seeded Notion to Confluence switch. The append wrong driver fails exactly `{replaced-tool-line, old-tool-gone, one-notes-line}`.
- `recall-superseded-definition`: 7-day to 14-day window across two sessions. The append wrong driver fails exactly `{replaced-in-session-2, one-window-line, old-window-gone}`.
- `write-added-not-superseded` (guard): sales is added to design. A wrong driver that replaces the design line fails exactly `{design-kept}`.
- `write-superseded-kept-on-request` (guard): the user asks to keep a record of Jenkins. A replace-only wrong driver fails exactly `{old-tool-recorded}`. Its header cites the new exception sentence only from the prompt commit, because its behavior depends on that sentence.

## Acceptance criteria → tests

Parametrized end-to-end cases are `test_correct_driver_passes_every_assertion[<id>]` and `test_wrong_driver_fails_exactly_the_listed_assertions[<id>]` in `tests/test_evals_end_to_end.py`.

| Acceptance criterion (Given/When/Then) | Test(s) |
| --------------------------------------- | ------- |
| US1.1 `write-correct-seeded-fact` has `old-format-gone`; correct driver passes, append driver fails the 3 listed | end-to-end `[write-correct-seeded-fact]` (both) |
| US1.2 `write-superseded-tool` correct passes, append fails exactly 3 | end-to-end `[write-superseded-tool]` (both) |
| US1.3 `recall-superseded-definition` correct passes, append fails exactly 3 | end-to-end `[recall-superseded-definition]` (both) |
| US1.4 `write-added-not-superseded` guard | end-to-end `[write-added-not-superseded]` (both) |
| US1.5 `write-superseded-kept-on-request` guard | end-to-end `[write-superseded-kept-on-request]` (both) |
| US1.6 corpus includes the 4 ids; every scenario has `index-first` and a `# Prompt:` header | `test_corpus_is_the_planned_set`, `test_corpus_loads_with_unique_ids`, `test_every_shipped_scenario_has_scripted_drivers` |
| US2.1 `forgetting.BODY` has the 4 load-bearing terms; existing forgetting tests pass | `test_forgetting_body_supersedes_changed_facts`, `test_forgetting_body_omits_write_tools`, `test_forgetting_body_has_no_used_to_tombstones` |
| US2.2 one "the file's only line" sentence names `replace_fact`, `description`, `aliases`; rejected phrases absent | `test_one_fact_change_stays_replace_fact`, `test_no_trial_phrasing` |
| US2.3 existing write-mechanics and invariants tests pass unchanged | `tests/test_prompts_write_mechanics.py` (`test_us2_*` to `test_us5_*`) |
| US2.4 `recall-replace-fact` header cites both new sentences | `test_recall_replace_fact_header_cites_the_supersession_sentences` |
| US2.5 `.claude/agents/wenchang-eval.md` equals `render_agent_file()` | `test_eval_agent_body_is_preamble_plus_prompt`, `test_render_agent_writes_the_file` |
| US3 branch drivers (`old-recipient-gone`, overwrite, stale-metadata) unchanged | end-to-end `[recall-replace-fact]`, `test_recall_replace_fact_flags_a_previously_clause`, `test_recall_replace_fact_ignores_stale_metadata` |

## Architecture / ADR changes

- None. No public API, module boundary, or storage change.
- Rejected: a `write_file` docstring sentence. ADR 0025 decision 6 has the prompt own tool choice and the docstrings own per-call mechanics.

## Deviations from spec

- None.

## Look closely at

- "date ... recording the change" against forward end dates. A forward end date (for example "only until October 30") describes the current fact, so it is unaffected. `remembering-expiry` is in the corpus run.
- Curated corrections may drop their reference to the curated note. No assertion depends on it, and `system/` content still persists under the curated-content rule.
- In the live run, watch for alias cleanup done through a single combined `write_file`. Cleanup of that kind would be fine, but it is out of scope here.

## Live evals — PENDING

This is the human's merge checkpoint and not a release gate (ADR 0028).

**Identity.** Agent sha256 `52426257a4c7ecb20676573cc3fbb6d328b49f682824a0f9a988cfe9a02645ad`, commit = the PR head. Each `run.json` must match both. Ordering: after #39 merges, rebase this branch onto main, re-render the agent file, update the sha here and commit, then run.

**Gate.** Full corpus at N=3, twice, each as 3 shards merged with `merge-runs`. From the worktree root, for k = 1..3:

```
CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 claude -p "/run-evals --model sonnet --trials 3 --judge --shard k/3" --mcp-config evals/mcp.json --strict-mcp-config --allowedTools mcp__wenchang "Bash(uv run python -m evals *)" --settings '{"includeGitInstructions": false}'
```

Then merge, and repeat the whole procedure for the second run:

```
uv run python -m evals merge-runs evals/runs/<name> <shard dirs>
```

**Floors over the combined N=6:**

| Scenario | Floor |
| -------- | ----- |
| `recall-replace-fact` | 6/6 |
| `write-correct-seeded-fact` (including `old-format-gone`) | 6/6 |
| `write-superseded-tool` | at least 5/6 |
| `recall-superseded-definition` | at least 5/6 |
| `write-added-not-superseded` | 6/6 |
| `write-superseded-kept-on-request` | 6/6 |
| Every other scenario | its AIE-1170 rate |

**Baseline at main for the held-outs.** Held-outs that pass at main do not demonstrate the fix. Use a throwaway worktree, never the primary checkout:

```
git -C /Users/marksiebert/p/github/wenchang fetch origin
git -C /Users/marksiebert/p/github/wenchang worktree add --detach /tmp/wenchang-baseline origin/main
make -C /tmp/wenchang-baseline install
git -C /tmp/wenchang-baseline checkout origin/AIE-1183-replace-fact-corrections -- evals/scenarios/write-superseded-tool.yaml evals/scenarios/recall-superseded-definition.yaml evals/scenarios/write-added-not-superseded.yaml evals/scenarios/write-superseded-kept-on-request.yaml evals/scenarios/write-correct-seeded-fact.yaml
# launch the eval session from /tmp/wenchang-baseline and run:
/run-evals --model sonnet --trials 3 --judge write-superseded-tool recall-superseded-definition write-added-not-superseded write-superseded-kept-on-request write-correct-seeded-fact
git -C /Users/marksiebert/p/github/wenchang worktree remove --force /tmp/wenchang-baseline
```

**AIE-1170 baseline.**

| Run | Commit | Result |
| --- | ------ | ------ |
| A | 9c51a50 | `recall-replace-fact` 1/3, others 3/3 |
| B | a0b1e23 | `recall-replace-fact` 3/3, others 3/3 (agent sha b668ca85...) |

Per the diagnosis, run B's `recall-replace-fact` "passes" kept history.

**Miss policy.** Inspect the failing transcripts, adjust only the new sentences, and rerun. After two rounds, the human decides.

**Results.** _Pending._

## Follow-ups

- Stale aliases. Old names still find the file, and dropping them needs `write_file`.
- The corpus test and `CASES` conflict textually with #37 and #40 at rebase.
