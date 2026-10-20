# PR Review: AIE-1198 — Quote the tool's path when saying where something is stored

> **Live gate: PASSED.** One judge-floor miss accepted as harness noise. See "Live gate".

## What changed & why

In the AIE-1184 N=6 run, `remembering-no-metric-value` replies said
`project/metrics/dau.md` for `project/p-checkout/metrics/dau.md`, and
`project/metrics/daily-active-users.md` for a real file with the same missing
entity segment. The tools take `(scope, area, name)` and return the full
`path`. The prompt never said how to name a location, so the agent rebuilt one
from its arguments, and nothing graded it.

- **Prompt.** One sentence, the second of `overview.BODY`:
  "When you tell the user where something is stored, quote the full `path` a
  tool returned for it; never rebuild one from its scope, area, and name."
- **Harness.** A reply-path check flags scope-rooted paths in replies that no
  tool result named up to that turn. It never changes `results` or `passed`.
- **Tools.** Output is unchanged.

Final overview `BODY`:

```
Memory is short markdown files that outlast this conversation, each addressed by a scope, an
area in that scope, and a name. When you tell the user where something is stored, quote the full
`path` a tool returned for it; never rebuild one from its scope, area, and name. Call
`get_memory_index()` at the start of every session, before you answer from memory or write to it.
When a subject outgrows its file's size limit, split it into narrower files.
```

Agent `wenchang-eval.md` sha256:
`73631e3b06dc80e0687533e1530efc185d6aaec53a9ae5a471be4441308be194`.

## Held-out scenarios

All four have `index-first` and `index-called`. Each was written from intent,
before the prompt edit.

| Id | Scope | Turn | Key assertions | Wrong driver fails |
| -- | ----- | ---- | -------------- | ------------------ |
| `filing-says-saved-path` | user, new file | "I export every query result as CSV with a header row, never as Excel. Keep that in mind for me, and tell me which file it ended up in." | `csv-saved`; `names-full-path`; `no-rebuilt-path` | `names-full-path`, `no-rebuilt-path` |
| `slots-says-shared-path` | project | T1: "On this project, we write every dashboard name in sentence case, never title case." T2: "Go ahead, put it in the project's memory." | `convention-saved`; `no-rebuilt-path` (vacuous if no path is named) | path rebuild: `no-rebuilt-path`; user-scope write: `convention-saved` |
| `recall-says-stored-path` | organization, read only | "My new teammate keeps asking what counts as an enterprise account here. Which memory file has that, so I can send her the location?" | `names-full-path`; `no-rebuilt-path`; `no-write` | `names-full-path`, `no-rebuilt-path` |
| `applying-no-path-unasked` | user, seeded `reports` | "I'm putting together a chart of weekly signups for last quarter. What title should I give it?" | `no-path-in-reply`; judge `applies-preference` | `no-path-in-reply` |

`recall-says-stored-path` is a regression guard. The full path is in context
after the index, so it likely passes at main. `applying-no-path-unasked`
guards against over-application. `names-full-path` checks only the entity
segment.

**Generality review.** `slots-says-shared-path` never asks where the fact is
stored, so it can pass without naming a path. This is deliberate: it is the
only held-out where the user does not ask, matching the motivating failure.
The reply-path check and 5.3's held-out delta carry its signal. The held-outs
were not edited after the prompt commit.

## Reply-path check design

`evals.graders.find_unmatched_reply_paths(scenario, trace, transcript)`. Full
rules are in [ADR 0033](../../docs/adr/0033-reply-path-check.md).

- Tokens are scope-rooted runs read from the raw reply. Quotes and fences are
  not stripped. URLs, prose pairs, and echoes of user text are skipped.
- Known locations come from `path` and `prefix` in tool results up to that
  turn, failed calls included, arguments never.
- `entity_omitted` means the path matches a known one once its entity segment
  is removed. Anything else is `unmatched`.
- `grade.json` gains `unmatched_reply_paths`. The report gains per-scenario
  `reply_path_trials` and `reply_path_unchecked_trials`, and a run-level
  `reply_paths`. Pass counts are untouched.

## Re-report of the historical runs (US2.9)

`cp -Rp` copies, re-reported with origin/main's code (before) and this branch
(after), each with the code's worktree as cwd. Originals are unchanged by file
hash. `trials_run`, `passed_trials`, `assertions`, `judge`, and `third_person`
are identical before and after.

| Run | Reply-path flagged | Entity omitted | Third-person (unchanged) |
| --- | ------------------ | -------------- | ------------------------ |
| `aie1184-n6` | 51/138 | 45 | 8/138 |
| `aie1182-n6` | 37/168 | 34 | 6/168 |
| `aie1183-n6` | 74/168 | 68 | 6/168 |
| `aie1185-r2-n6` | 47/120 | 47 | 8/120 |
| Total | 209/594 (35%) | 194 | 28/594 |

**False-positive review** (manual, every flagged token). No URL, prose, or
correct-proposal false positives. Every `entity_omitted` flag is a scope,
area, and name rebuild (`user/preferences/editor`,
`user/workflows/atlas-migration`, `project/entities/checkout-redesign`,
`organization/system/fiscal-calendar`).

15 trials were flagged only `unmatched` (1184: 6, 1182: 3, 1183: 6, 1185: 0).
All are turn 1 proposals in ask-before-shared flows that name a location
before any write (`organization/vocabulary`, `project/glossary`,
`project/conventions/signup-definition`,
`organization/business-context/fiscal-year`). The location does not exist and
never would as written. They are counted, but the sentence's scope does not
strictly cover them, so 15 of 209 is an upper bound on contested flags.

## Acceptance criteria → tests

| Acceptance criterion | Test(s) |
| -------------------- | ------- |
| US1.1, 1.2, 1.4 sentence is the second sentence, names no example values, is in the "Memory" section | `tests/test_prompts_overview.py` `test_overview_body_second_sentence_quotes_tool_paths`, `test_quote_path_sentence_names_no_example_values`, `test_memory_section_of_reference_prompt_carries_quote_path_sentence` |
| US1.3 existing overview tests unchanged | the rest of `tests/test_prompts_overview.py` |
| US1.5 agent file equals the render | `tests/test_evals_agent.py` (existing pin) |
| US2.1-2.5 roots, tokens, skips, known locations, match, kind | `tests/test_evals_graders.py`, section "reply paths (AIE-1198, US2)" |
| US2.6 `grade.json` field, `transcript_error`, no transcript, `_load_grade` validation | `tests/test_evals_report.py`, section "reply-path check in grade.json and the report" |
| US2.7 refresh, missing `trace.json` | same section |
| US2.8 report fields, markdown, merge | same section |
| US2.9 re-report, false-positive review | this file and ADR 0033 (manual) |
| US3.1-3.4 held-out scenarios and drivers | `tests/test_evals_end_to_end.py` `CASES` rows; `tests/test_evals_scenario.py` `CORPUS` |
| US3.5 check on the drivers | `tests/test_evals_end_to_end.py` `test_correct_driver_has_no_unmatched_reply_paths`, `test_wrong_driver_flags_the_rebuilt_path_as_entity_omitted` |
| US4 unchanged behavior | `make check` |
| US5 live gate | human-run, below |

## Architecture / ADR changes

- New [ADR 0033](../../docs/adr/0033-reply-path-check.md).
- `ARCHITECTURE.md` "Outside the library: `evals/`": the `evals.graders` and
  `evals.report` bullets mention the reply-path check.

## Deviations from spec

- None.

## Live gate (US5): PASSED

Human-run, never by agents. The baselines predate AIE-1197's `index-called`,
which can only lower a pass. A drop explained by `index-called` alone is
noted, not counted. Launch command: AGENTS.md (`/run-evals`).

**5.1 Baseline at main.** The 4 held-outs, N=6, `--judge`, in a throwaway
worktree. `<scratch>` is a new path outside the repo.

```
git -C /Users/marksiebert/p/github/wenchang fetch origin
git -C /Users/marksiebert/p/github/wenchang worktree add --detach <scratch> origin/main
make -C <scratch> install
git -C <scratch> checkout origin/AIE-1198-reply-paths -- evals/scenarios/filing-says-saved-path.yaml evals/scenarios/slots-says-shared-path.yaml evals/scenarios/recall-says-stored-path.yaml evals/scenarios/applying-no-path-unasked.yaml
# launch the eval session from <scratch>, then:
/run-evals --model sonnet --trials 6 --judge filing-says-saved-path slots-says-shared-path recall-says-stored-path applying-no-path-unasked
shasum -a 256 <scratch>/.claude/agents/wenchang-eval.md
# from this worktree (cwd), for the reply-path counts:
uv run python -m evals report <scratch>/evals/runs/<run id>
# copy the run dir out of <scratch>/evals/runs/, then:
git -C /Users/marksiebert/p/github/wenchang worktree remove --force <scratch>
```

Baseline commit: main 147e2a3. Report copy: `evals/runs/baseline-main-1198`
(gitignored copy in this worktree). Results: `filing-says-saved-path` 5/6,
`slots-says-shared-path` 4/6, `recall-says-stored-path` 6/6,
`applying-no-path-unasked` 6/6.

**5.2 Branch run.** The full corpus (52) at N=6 with `--judge`, sharded across
7 sessions from the worktree root, merged with `merge-runs`.

Run: `evals/runs/aie1198-n6`, commit 5730696, 312 trials, agent sha256
`73631e3b06dc80e0687533e1530efc185d6aaec53a9ae5a471be4441308be194`.

```
CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 claude -p "/run-evals --model sonnet --trials 6 --judge --shard 1/7" --mcp-config evals/mcp.json --strict-mcp-config --allowedTools mcp__wenchang "Bash(uv run python -m evals *)" --settings '{"includeGitInstructions": false}'
# repeat for --shard 2/7 .. 7/7, then:
uv run python -m evals merge-runs evals/runs/aie1198-n6 evals/runs/<shard 1 dir> ... evals/runs/<shard 7 dir>
```

**5.3 Floors.**

| Floor | Main | Branch | Met? |
| ----- | ---- | ------ | ---- |
| `filing-says-saved-path` at least 5/6 | 5/6 | 6/6 | Yes |
| `filing-says-saved-path` + `slots-says-shared-path` pass at least 3 more trials than main, or main at least 10/12 and branch at least 11/12 (then record "held-outs do not discriminate"; the reply-path floor carries the gate) | 9/12 | 12/12 (+3) | Yes; main was below 10/12, so the +3 rule applies |
| `recall-says-stored-path` at least 5/6 | 6/6 | 6/6 | Yes |
| `applying-no-path-unasked` 6/6 deterministic; `applies-preference` no lower than main | 6/6; judge 6/6 | 6/6; judge 6/6 | Yes |
| `remembering-no-metric-value` at least 5/6 | n/a | 6/6 | Yes |
| Every other scenario at most 1 below baseline (most recent of the four re-reported runs by `run.json` `created`; for `applying-no-trait`, `applying-relevant-only`, `curated-observed-conflict`, `filing-second-customer`, `remembering-observed-once`, `slots-system-of-record`, the most recent main N=6 count in `specs/*/review-pr.md`, else 5/6). A miss counts only if a second N=6 run of that scenario also misses. | per baseline rule | Every other scenario 6/6 except `recall-superseded-definition` 5/6 | Yes; within 1 |
| Judge items at least baseline minus 1 (same baseline rule) | per baseline rule | All at or above baseline except `write-superseded-shared-fact` `asks-which-to-keep` 4/6 against 6/6 | Accepted miss (below) |
| Reply-path flagged trials at most half the baseline's, on scenarios common to the branch run and the after re-report. Note how many are proposal flags. | 209/594 | 1/312, 0 with entity omitted | Yes |
| Third-person flagged trials at most the after re-report's pooled rate times the branch's checked trials, plus 2 | n/a | 12/312 | Yes |

**Accepted judge miss.** `write-superseded-shared-fact` `asks-which-to-keep`
is 4/6 against a 6/6 baseline, two below. Both fails co-occur with
third-person replies ("I asked the user..."). The orchestrator accepted this
as harness noise, consistent with AIE-1183. Separately,
`filing-project-fact-in-question` `asks-before-project-save` is 6/6, up from
3/6 in the AIE-1182 run.

**5.4 Iteration.** If a floor is missed, revise the wording (still general),
re-render with `uv run python -m evals render-agent`, rerun, and record each
iteration here.

Iterations: none. The first wording passed.

## Look closely at

- `find_unmatched_reply_paths` in `evals/graders.py`: the two-segment prose
  rule and the echo rule decide most false positives.
- `_refresh_reply_check` in `evals/report.py`: it must never touch `results`
  or `passed`, and must not raise on a missing `trace.json`.
- The 15 `unmatched`-only proposal flags. They put a floor under the
  reply-path floor.
- The prompt sentence names no fact, scope, area, or file.

## Follow-ups

- Promote the check to pass/fail once its false-positive rate is known.
- PR #41 (AIE-1196) also re-renders `wenchang-eval.md`. Whichever merges later
  re-renders on rebase and rechecks the ADR number (0033).
- Rootless rebuilds (`metrics/dau.md`) are not detected.
- Widen the guard hook's rule 4 for `evals/**` (human change, in AGENTS.md).
