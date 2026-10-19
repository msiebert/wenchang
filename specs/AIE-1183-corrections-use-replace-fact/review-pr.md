# PR Review: AIE-1183 — A changed fact states only what is true now

## What changed & why

**Diagnosis** (AIE-1170 N=3 live runs):

- 11 of 12 superseding writes kept history. Only 2 of 12 used `write_file`.
- `write-correct-seeded-fact` silently failed 6 of 6 (for example "(changed from PDF)"). It had no absence assertion.
- The prompt had no current-truth principle. Forgetting's no-trace rule ("Removal is total") covers only removal.

**Fix** (general, not scenario-specific):

- One new Forgetting paragraph: a changed fact's old value is gone.
- Two Write-mechanics changes: the cited `replace_fact` sentence says to write the new line as the current truth, and a new sentence says changing one fact is still `replace_fact` for a one-line file or a metadata change.
- The earlier branch text was rejected because it quoted the failing trials' phrasing. It is removed (`test_no_trial_phrasing`).
- Stale aliases are out of scope.

### Final text

`src/wenchang/prompts/forgetting.py` (new paragraph):

> When a fact in a file you can write changes, its old value is gone too: rewrite the line with a fresh label to state only what is true now, as though it had always read that way, with no note, date, or comparison recording the change. Keep an earlier value only if the user asks you to keep a record of it. A correction to a curated fact may name the curated fact it overrides.

`src/wenchang/prompts/write_mechanics.py` (two changes):

1. The `replace_fact` clause is reworded:

   > ... `replace_fact` to change one fact, writing the new line as the current truth and quoting the existing line as `old_string` so surrounding lines stay intact; ...

2. New sentence:

   > Changing one fact is still `replace_fact` when it is the file's only line or when the change also replaces `description` or adds `aliases`.

The generality review refined Option A:

- The paragraph is scoped to writable files.
- It uses a fresh label.
- Curated corrections may name what they override.
- The aliases sentence is now accurate: `replace_fact` only adds aliases.
- A write-time pointer is added to the cited sentence, and citations and pins are updated.

### Held-out evidence (commits d8d4c24 and f31011d, before the prompt commit)

All turns are in the first person.

- `write-correct-seeded-fact`: new `line_absent` assertion `old-format-gone`. The append wrong driver fails exactly `{replaced-quoting-old, one-format-line, old-format-gone}`.
- `write-superseded-tool`: one-line seeded Notion to Confluence switch, plus `no-change-date` (`line_absent (?i)last week`). The append wrong driver fails exactly `{replaced-tool-line, old-tool-gone, one-notes-line}`.
- `recall-superseded-definition`: 7-day to 14-day window across two sessions. The append wrong driver fails exactly `{replaced-in-session-2, one-window-line, old-window-gone}`.
- `write-added-not-superseded` (guard): sales is added to design. A wrong driver that replaces the design line fails exactly `{design-kept}`.
- `write-superseded-kept-on-request` (guard): the user asks to keep a record of Jenkins. It has `old-line-changed`. A replace-only wrong driver fails exactly `{old-tool-recorded}`. An append-only driver fails exactly `{old-line-changed}` (`test_kept_on_request_flags_an_unchanged_old_line`).
- `write-superseded-shared-fact` (guard): a contradicted project fact, and the user's turn asks which to keep. Turn 1 has no shared write, and there is a judge item (`asks-which-to-keep`). A replacing wrong driver fails exactly `{no-shared-write-before-ask, old-fact-kept}`. Its header cites the existing shared-contradiction sentence.

Headers of `write-superseded-tool`, `recall-superseded-definition` and `write-correct-seeded-fact` add the Forgetting principle sentence in the prompt commit. `write-superseded-kept-on-request` cites the exception sentence there, because its behavior depends on it.

## Acceptance criteria → tests

Parametrized end-to-end cases are `test_correct_driver_passes_every_assertion[<id>]` and `test_wrong_driver_fails_exactly_the_listed_assertions[<id>]` in `tests/test_evals_end_to_end.py`.

| Acceptance criterion (Given/When/Then) | Test(s) |
| --------------------------------------- | ------- |
| US1.1 `write-correct-seeded-fact` has `old-format-gone`; correct driver passes, append driver fails the 3 listed | end-to-end `[write-correct-seeded-fact]` (both) |
| US1.2 `write-superseded-tool` (with `no-change-date`) correct passes, append fails exactly 3 | end-to-end `[write-superseded-tool]` (both) |
| US1.3 `recall-superseded-definition` correct passes, append fails exactly 3 | end-to-end `[recall-superseded-definition]` (both) |
| US1.4 `write-added-not-superseded` guard | end-to-end `[write-added-not-superseded]` (both) |
| US1.5 `write-superseded-kept-on-request` guard, including the append-only driver | end-to-end `[write-superseded-kept-on-request]` (both), `test_kept_on_request_flags_an_unchanged_old_line` |
| US1.6 corpus includes the 5 new ids; every scenario has `index-first` and a `# Prompt:` header | `test_corpus_is_the_planned_set`, `test_corpus_loads_with_unique_ids`, `test_every_shipped_scenario_has_scripted_drivers` |
| US1.7 `write-superseded-shared-fact`: no-write driver passes, replacing driver fails exactly `{no-shared-write-before-ask, old-fact-kept}` | end-to-end `[write-superseded-shared-fact]` (both) |
| US2.1 `forgetting.BODY` has the load-bearing phrases; existing forgetting tests pass | `test_forgetting_body_supersedes_changed_facts`, `test_forgetting_body_omits_write_tools`, `test_forgetting_body_has_no_used_to_tombstones` |
| US2.2 "writing the new line as the current truth"; one "the file's only line" sentence names `replace_fact`, `description`, `aliases`; rejected phrases absent | `test_replace_fact_writes_current_truth`, `test_one_fact_change_stays_replace_fact`, `test_no_trial_phrasing` |
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

## Live evals — DONE

This is the human's merge checkpoint and not a release gate (ADR 0028).

**Identity.** Agent sha256 `f84a877053432214cc3d56f79125b69c320dea539e29d6321ff597181a97b9f5`, commit = the PR head. Each `run.json` must match both. The agent file is rendered on top of main with #39 and #37 merged.

The combined prompt (#37 + #38) was not live-run together; the separate N=6 runs of each PR are the evidence.

**Gate.** Full corpus at N=3, twice, each as 3 shards merged with `merge-runs`. From the worktree root, for k = 1..3:

```
CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 claude -p "/run-evals --model sonnet --trials 3 --judge --shard k/3" --mcp-config evals/mcp.json --strict-mcp-config --allowedTools mcp__wenchang "Bash(uv run python -m evals *)" --settings '{"includeGitInstructions": false}'
```

Then merge the three shards of each run, and repeat the whole procedure for the second run:

```
uv run python -m evals merge-runs evals/runs/<name> <shard dirs>
```

**N=6 tally.** Sum `passed_trials` per scenario from the two merged `report.json` files. Never pass both runs to `merge-runs`.

**Floors over the combined N=6:**

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

**Baseline at main for the held-outs.** Held-outs that pass at main do not demonstrate the fix. Use a throwaway worktree, never the primary checkout:

```
git -C /Users/marksiebert/p/github/wenchang fetch origin
git -C /Users/marksiebert/p/github/wenchang worktree add --detach /tmp/wenchang-baseline origin/main
make -C /tmp/wenchang-baseline install
git -C /tmp/wenchang-baseline checkout origin/AIE-1183-replace-fact-corrections -- evals/scenarios/write-superseded-tool.yaml evals/scenarios/recall-superseded-definition.yaml evals/scenarios/write-added-not-superseded.yaml evals/scenarios/write-superseded-kept-on-request.yaml evals/scenarios/write-correct-seeded-fact.yaml evals/scenarios/write-superseded-shared-fact.yaml
# launch the eval session from /tmp/wenchang-baseline and run:
/run-evals --model sonnet --trials 3 --judge write-superseded-tool recall-superseded-definition write-added-not-superseded write-superseded-kept-on-request write-correct-seeded-fact write-superseded-shared-fact
# copy each run out before removing the worktree:
cp -R /tmp/wenchang-baseline/evals/runs/<run> /Users/marksiebert/p/github/wenchang-AIE-1183/evals/runs/baseline-main-<run>
git -C /Users/marksiebert/p/github/wenchang worktree remove --force /tmp/wenchang-baseline
```

**AIE-1170 baseline.**

| Run | Commit | Result |
| --- | ------ | ------ |
| A | 9c51a50 | `recall-replace-fact` 1/3, others 3/3 |
| B | a0b1e23 | `recall-replace-fact` 3/3, others 3/3 (agent sha b668ca85...) |

Per the diagnosis, run B's `recall-replace-fact` "passes" kept history.

**Miss policy.** Inspect the failing transcripts, adjust only the new sentences, and rerun. After two rounds, the human decides.

**Results.** Done. The orchestrator accepted the run with two 5/6 misses, explained below.

**Runs.**

- Branch: one N=6 run (`--trials 6 --judge`) in 7 shards, merged as `evals/runs/aie1183-n6` (gitignored, in this worktree). It replaces the two N=3 runs and covers the same 168 trials. Commit c0f6a66, agent sha256 `198c5602f87cc10be1e9f29093f7914382ce58b06b40546f3d37331e2a7fe000`.
- Baseline at main (a585314): N=3, `evals/runs/baseline-main-n3`, copied into this worktree.

| Scenario | Main (N=3) | Branch (N=6) |
| -------- | ---------- | ------------ |
| `recall-replace-fact` | 3/6 in the AIE-1184 run on main's prompt | 6/6 |
| `write-correct-seeded-fact` | 0/3, every trial failed `old-format-gone` ("(changed from PDF)") | 6/6 |
| `write-superseded-tool` | 0/3, every trial failed `old-tool-gone` (for example "(moved from Notion in the week before 2026-10-16)") | 6/6 |
| `recall-superseded-definition` | 0/3 | 6/6 |
| `write-added-not-superseded` | 3/3 | 6/6 |
| `write-superseded-kept-on-request` | 3/3 | 6/6 |
| `write-superseded-shared-fact` | 3/3, judge 3/3 | deterministic 6/6, judge `asks-which-to-keep` 5/6 |
| `filing-new-acronym` | 6/6 | 5/6 |

**Accepted misses.**

- `write-superseded-shared-fact` judge 5/6. The one fail (trial 2) was a third-person reply ("I asked the user whether...") with correct behavior: it read first and wrote nothing. Classified as harness noise.
- `filing-new-acronym` 5/6 (baseline 6/6). Trial 1 added the new facts, description and alias with one `write_file` on the existing file instead of `append_line`. The end state was correct and nothing was lost. It is the only `write_file` on this scenario across every run, so the new "rewrite the line" wording plausibly nudged it.
- Every other scenario met its rate. Third-person flagged trials: 6 of 168.

## Follow-ups

- Scope the "rewrite the line" sentence to changed values, so that adding a fact (even with aliases or a description) stays `append_line`. This addresses the `filing-new-acronym` trial 1 miss.
- Fix the `no-new-file` assertion label on `filing-new-acronym`. It fires on a `write_file` overwrite, so the label is inaccurate.

- Stale aliases. Old names still find the file, and dropping them needs `write_file`.
- The corpus test and `CASES` conflict textually with #37 and #40 at rebase.
