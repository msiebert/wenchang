# PR Review: AIE-1170 — Local behavioral eval harness run via Claude Code subagent

> **Do not merge before one live N=1 run of the four required scenarios.**
> Run it in a fresh session from the repo root:
>
> ```
> CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 claude --mcp-config evals/mcp.json --strict-mcp-config --allowedTools mcp__wenchang "Bash(uv run python -m evals *)" --settings '{"includeGitInstructions": false}'
> /run-evals --model sonnet --trials 1 privacy-account-number filing-alias-append recall-across-sessions forgetting-one-fact
> ```
>
> Then paste the resulting `evals/runs/<run-id>/report.md` below, under
> "Live run".

## What changed & why

Spec Section 10.3 says prompt behavior is evaluated, not unit-tested, and
several specs list scenarios that nothing ran. This adds a dev-only
`evals/` package, outside the wheel:

- **Eval MCP server.** It serves the seven memory tools over a resettable
  in-memory store, using AIE-1060's `register_memory_tools`, with
  reference-adopter identities. It adds three harness tools: `eval_reset`,
  `eval_record_turn`, and `eval_dump`.
- **Eval agent.** `wenchang-eval` is a Claude Code subagent restricted to
  those seven tools, with `omitClaudeMd`. Its system prompt is a framing
  preamble plus the reference memory prompt.
- **Scenarios and graders.** Scenarios are YAML, with 23 shipped.
  Deterministic graders work over the store dump and a timed tool-call
  trace. An optional LLM-judge subagent is included.
- **Runner and CLI.** `/run-evals` is the runner, and `python -m evals`
  provides `new-run`, `grade`, `report`, and `render-agent`.

The reference adopter fixture moved from `tests/` to
`evals/reference_adopter.py`. The scenario format and the JSON trace and
store contract do not depend on the driver, so a later SDK driver can reuse
them.

## Acceptance criteria → tests

Test modules, abbreviated in the Test(s) column:

| Abbreviation | Module |
| ------------ | ------ |
| pkg | `tests/test_evals_packaging.py` |
| scn | `tests/test_evals_scenario.py` |
| grd | `tests/test_evals_graders.py` |
| srv | `tests/test_evals_server.py` |
| agt | `tests/test_evals_agent.py` |
| rpt | `tests/test_evals_report.py` |
| e2e | `tests/test_evals_end_to_end.py` |

| Acceptance criterion | Test(s) |
| -------------------- | ------- |
| 1.1 tool surface = `TOOL_NAMES` + harness tools; descriptions match | srv `test_tool_surface_is_memory_tools_plus_harness` |
| 1.2 neutral instructions; prompt resource | srv `test_instructions_are_neutral_and_prompt_is_a_resource` |
| 1.3 reset seeds the identity's entities, sources `seed-job` | srv `test_reset_seeds_the_store` |
| 1.4 second reset clears store, trace, transcript; seq restarts | srv `test_reset_replaces_store_trace_and_transcript` |
| 1.5 admin writes organization; member gets `role_required` | srv `test_identity_comes_from_the_scenario` |
| 1.6 trace fields incl. `request_id`, `duration_s`, timing; harness calls untraced; resets keep the time baseline | srv `test_trace_records_carry_timing_and_correlation`, `test_reset_does_not_move_the_time_baseline` |
| 1.7, 1.8 time-window turn tagging; transcript | srv `test_turns_tag_calls_by_time_window` |
| 1.9 dump files; deleted files absent; trailing calls 0/0 | srv `test_dump_writes_the_store_and_tags_trailing_calls` |
| 1.10 dump before reset errors; empty member store works | srv `test_dump_before_reset_is_an_error` |
| 1.11 bad scenario or out-of-root trial dir leaves state unchanged | srv `test_bad_reset_leaves_state_unchanged[missing,invalid,outside]` |
| 1.12 20 concurrent calls all traced | srv `test_concurrent_calls_are_all_traced` |
| 1.13 stdio from any cwd | srv `test_server_runs_over_stdio` |
| 2.1 agent tools, model, `omitClaudeMd` | agt `test_eval_agent_frontmatter` |
| 2.2 body = preamble + prompt; drift fails | agt `test_eval_agent_body_is_preamble_plus_prompt` |
| 2.3 `render-agent [--out]` | agt `test_render_agent_writes_the_file` |
| 2.4 not guard-routed | agt `test_eval_agent_is_not_guard_routed` |
| 2.5 `evals/mcp.json`; no root `.mcp.json` | agt `test_eval_mcp_config` |
| 2.6 judge agent | agt `test_judge_agent` |
| 2.7 runner doc contents | agt `test_runner_doc_names_everything_the_runner_needs` |
| 2.7 turn prompts (every turn a fresh Agent prompt) | rpt `test_turn_prompt_for_the_first_turn_is_the_bare_turn`, `test_turn_prompt_replays_the_session_so_far`, `test_turn_prompt_needs_the_earlier_replies`, `test_turn_prompt_cli_prints_the_prompt`; srv `test_record_turn_writes_the_transcript` |
| 3.1 every field; defaults | scn `test_full_scenario_parses_every_field`, `test_defaults_apply` |
| 3.2 reference seeds first; collision rejected | scn `test_reference_seed_comes_first`, `test_seed_colliding_with_reference_seed_is_rejected` |
| 3.3 21 malformed cases, incl. args not on every listed tool, unknown scope arg, non-string identity or kind, `seed_lines_preserved` on a non-seed (plus unknown tool, missing file) | scn `test_malformed_scenarios_are_rejected[*]`, `test_non_mapping_yaml_is_rejected`, `test_unknown_tool_name_is_rejected`, `test_missing_file_is_rejected` |
| 3.4 corpus loads; unique ids; closed kinds | scn `test_corpus_loads_with_unique_ids`, `test_assertion_kinds_are_the_closed_set` |
| 3.5 corpus is the planned 23; categories; sources; prompt cite; rubrics name their turn | scn `test_corpus_is_the_planned_set`, `test_judge_rubrics_name_their_turn` |
| 4.1 `index_read_first`; a session with no memory calls passes | grd `test_index_read_first_*` (6 tests) |
| 4.2 `file_absent` | grd `test_file_absent` |
| 4.3 `line_present` / `line_absent` | grd `test_line_present_and_absent_with_filters`, `test_line_patterns_are_case_sensitive_as_written`, `test_line_absent_is_vacuous_without_matching_files`, `test_blank_line_is_detected` |
| 4.4 `no_content_matching` | grd `test_no_content_matching_scans_files`, `test_no_content_matching_scans_write_arguments[*]`, `test_no_content_matching_scans_alias_lists`, `test_no_content_matching_ignores_reads` |
| 4.5 `no_duplicate_fact` | grd `test_no_duplicate_fact` |
| 4.6 `seed_lines_preserved` | grd `test_seed_lines_preserved` |
| 4.7 `tool_called` | grd `test_tool_called_counts_within_bounds`, `test_tool_called_argument_matchers`, `test_tool_called_filters_session_turn_and_outcome`, `test_tool_called_accepts_a_list_of_tools` |
| 4.8 `tool_not_called` | grd `test_tool_not_called` |
| 4.9 `alias_present` (casefold) | grd `test_alias_present_is_case_insensitive` |
| 4.10 `grade` order and shape | grd `test_grade_returns_results_in_scenario_order` |
| 4.11 loaders round-trip and reject | grd `test_loaders_round_trip`, `test_loaders_reject_malformed_input[*]`, `test_loaders_reject_a_missing_file` |
| 4.12 graders never import the driver | grd `test_graders_do_not_import_the_driver` |
| 4.13 strict index-first: sequential, parallel, late start | grd `test_index_first_is_strict_about_overlap` |
| 4.14 versions, `old_string`, deletes unscanned | grd `test_no_content_matching_skips_versions_old_strings_and_deletes` |
| 4.15 shuffled trace grades the same | grd `test_grade_ignores_trace_order` |
| 4.16 (a), (b) timing order; restarting request ids; 0/0 last | grd `test_ordering_uses_start_time_not_seq_or_request_id`, `test_order_key_puts_untagged_calls_last` |
| 4.16 (c) late record tagged by start time | srv `test_late_record_is_tagged_by_start_time` |
| 4.17 `called_before` | grd `test_called_before_passes_when_first_completes_before_then_starts`, `test_called_before_fails_unless_strictly_before[*]`, `test_called_before_is_vacuous_without_a_then_call`, `test_called_before_is_per_session`, `test_called_before_honors_first_args`, `test_called_before_counts_failed_calls_unless_succeeded_is_set` |
| 5.1 `new-run` metadata and plan; run-id collision suffix | rpt `test_new_run_writes_metadata_and_plan`, `test_new_run_cli_prints_the_plan`, `test_run_ids_do_not_collide` |
| 5.2 unknown id or model exits 2, creates nothing | rpt `test_new_run_rejects_unknown_ids_and_models[*]` |
| 5.3 `grade` | rpt `test_grade_writes_results`, `test_grade_rejects_missing_inputs` |
| 5.4 `report` counts; not-run trials; stale grades regraded; malformed `run.json` / `grade.json` exit 2 | rpt `test_report_counts_passes_and_lists_unrun_trials`, `test_report_cli_prints_the_path`, `test_report_regrades_when_dumps_are_newer`, `test_report_rejects_malformed_run_and_grade_files[*]` |
| 5.5 judge verdicts separate; invalid flagged | rpt `test_report_keeps_judge_verdicts_separate` |
| 6.1 correct drivers pass, 1/1 (all 23) | e2e `test_correct_driver_passes_every_assertion[*23]`, `test_every_shipped_scenario_has_scripted_drivers` |
| 6.2 wrong drivers fail exactly the listed ids, 0/1 (all 23) | e2e `test_wrong_driver_fails_exactly_the_listed_assertions[*23]` |
| 7.1 wheel, `dev-mode-dirs`, pyright, yaml dev-only | pkg `test_wheel_ships_only_the_library`, `test_built_wheel_contains_only_the_library`, `test_editable_install_adds_repo_root`, `test_pyright_covers_evals`, `test_yaml_is_a_dev_dependency_only` |
| 7.2 import from any cwd | pkg `test_evals_imports_from_any_working_directory` |
| 7.3 fixture moved; importers rewritten | pkg `test_tests_fixture_module_is_gone`, `test_no_test_imports_the_old_fixture_module`; existing prompt and MCP tests unchanged and green |
| 7.4 post-#34 relocation: tests copy deleted, #34's importers and doc sites point at `evals.reference_adopter` | pkg `test_evals_holds_the_only_reference_adopter`; #34's tests unchanged apart from the import line and green |
| 9.1 `called_before` grading | (see 4.17) |
| 9.2 `called_before` parsing and rejection | scn `test_called_before_parses`, `test_malformed_called_before_is_rejected[*]` |
| 9.3 `index_max_bytes` parsing | scn `test_index_max_bytes_parses`, `test_bad_index_max_bytes_is_rejected[*]` |
| 9.4 the cap reaches the store | srv `test_scenario_index_cap_reaches_the_store` |
| 9.5 23 scenarios proven | (see 6.1, 6.2) |
| 9.6 rubrics name their turn; judge turn rule | scn `test_judge_rubrics_name_their_turn`; agt `test_judge_agent` |
| 10.1 shards partition the scenarios | rpt `test_shards_partition_the_scenarios` |
| 10.2 bad shards rejected | rpt `test_bad_shard_is_rejected[*]`, `test_new_run_cli_shards` |
| 10.3 shard dir naming and run.json | rpt `test_shard_run_dir_is_named_and_recorded`, `test_new_run_cli_shards` |
| 10.4 merged report covers every scenario | rpt `test_merge_runs_reports_every_scenario` |
| 10.5 mismatched or overlapping runs rejected | rpt `test_merge_runs_rejects_mismatched_runs[*]`, `test_merge_runs_rejects_overlap_and_existing_output` |
| 10.6 runner doc parallel shards | agt `test_runner_doc_describes_parallel_shards` |
| 8.1 `make check` runs all, no model calls | the full suite (`make check`) |
| 8.2 `src/` never imports `evals` | pkg `test_library_never_imports_evals` |
| 8.3 docs | ADR 0028, ARCHITECTURE.md, README.md, glossary, AGENTS.md (reviewed by hand) |
| 8.4 live-run merge gate | this file's banner and the PR body |

## Architecture / ADR changes

- New [ADR 0028](../../docs/adr/0028-behavioral-eval-harness.md). It
  covers the `evals/` boundary, the dev-only dependencies, `dev-mode-dirs`
  and its side effect, and the driver contract. The contract includes the
  timing fields, order, turn tagging, strict index-first, the scanned
  argument set, and the runs-root restriction. The ADR also covers the
  harness tools and the tool-surface reading, neutral instructions,
  `omitClaudeMd`, the preamble, the launch flags, verbatim replies, the
  judge, and the AGENTS.md scope against ADR 0004.
- ARCHITECTURE.md gains a new "Outside the library: `evals/`" subsection
  and the invariant "`src/` never imports `evals`".
- README gains a "Behavioral evals" section. The glossary adds scenario,
  trial, and trace. AGENTS.md updates the commands and the implementer row.

## Deviations from spec

- **Framing preamble.** It deviates from "the system prompt is the output
  of `build_memory_prompt`". It is recorded in ADR 0028 §5. After the live
  run at a723dd8, it also says that relayed turns are the user's own,
  confirmations included. Claude Code delivers turns after the first as
  messages from another agent, and the agent had refused those
  confirmations. That wording did not hold, so the harness now sends every
  turn as a fresh `Agent` prompt that replays the session's earlier
  exchanges. The preamble is back to plain framing.
- **Tool surface.** The server exposes 3 harness tools beyond `TOOL_NAMES`.
  The agent's allowlist is exactly `TOOL_NAMES`. This is recorded in ADR
  0028 §4.
- **`RUNS_DIR` location.** It lives in `evals.scenario`, next to
  `SCENARIO_DIR`, and `evals.report` re-exports it. The plan had put it in
  `report`. The server imports it without importing `report`.
- **`assertion_kind()`.** This public helper was added to `evals.scenario`.
  `graders` and `report` share it.
- **Extra JSON writers.** `trace_to_json` and `transcript_to_json` sit
  beside the planned `store_dump_to_json` in `evals.graders`.

## Look closely at

- **Turn tagging** (`_Snapshot._tag`) relies on each turn finishing before
  `eval_record_turn` runs. Claude Code runs subagents in the background by
  default, so the launch sets `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1`. The
  runner also waits for any completion notification before recording a
  turn. A test cannot enforce this rule. The live run is its first check.
- **Strict `index_read_first`** fails a parallel batch of the index read
  and another call. That is intended, and the rationale is in spec 4.1 and
  ADR 0028.
- **`dev-mode-dirs = [".", "src"]`** makes `tests`, `scripts`, and `docs`
  importable as namespace packages in the dev venv.
- **The fixture move.** `tests/test_mcp_server.py`'s `python -OO`
  subprocess snippet no longer inserts `tests/` into `sys.path`, and
  `TESTS_DIR` is gone. The import resolves through `dev-mode-dirs`.

## Follow-ups

- **T9: done.** `origin/main` was merged in after #34 and #35. Conflicts
  were import lines and three doc passages, resolved toward
  `evals.reference_adopter`. `tests/reference_adopter.py`, which was
  byte-identical to the evals copy, is deleted. #34's two remaining
  importers and `ARCHITECTURE.md` are repointed.
- **Human:** widen `scripts/hooks/guard-edits.sh` rule 4 for `evals/**`,
  `.claude/agents/wenchang-eval*.md`, `.claude/commands/run-evals.md`, and
  `.gitignore`. Also give doc-updater (rule 5) `AGENTS.md`.
- **Human:** before merge, do the live N=1 run above.
- Port the deferred scenarios after the first live run calibrates them.
  The list is in spec.md's Assumptions.
- An Anthropic SDK driver that writes the same three JSON files.

## Code review

Correctness review: **PASS.** There were 55 mutants, and every grader
mutant was caught. A dry run of the runner procedure against the real
stdio server also passed.

Harness review: **FAIL**, then fixed:

- **Background subagents (blocker).** Subagents run in the background by
  default, which breaks turn tagging. The launch now sets
  `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1`, plus `--allowedTools ...
  "Bash(uv run python -m evals *)"` and `--settings
  '{"includeGitInstructions": false}'`. The runner also waits on any
  background completion notification. The runner-doc test pins this.
- **Limitation text.** It now reads: own system prompt plus environment
  details. There is no Claude Code system prompt and no auto memory, and
  the git status snapshot is disabled.
- **Neutral instructions.** They are now "Memory tools for this
  workspace.", and the startup warning is noted as by design.
- **Links and T9.** The broken fixture links in README, ADR 0025, and ADR
  0026 are fixed, and the T9 doc sites are listed.
- **Loader.** It now rejects args that are not parameters of every listed
  tool, unknown scope args, a non-string identity or kind, and
  `seed_lines_preserved` on a non-seed file.
- **Scenarios loosened to match the prompt.** `recall-across-sessions`
  accepts `read_file` or `get_memory_index`. `recall-replace-fact` drops
  `old-recipient-gone`. `filing-new-acronym` scopes `no-new-file` to
  project. `filing-alias-append` accepts `friday|due`.
- **Report.** It validates `run.json` and `grade.json` and regrades stale
  grades.
- **Nits.** These are all applied:
  - The stamp-lag docstring.
  - A single-lock snapshot for dumps.
  - A baseline pin test.
  - Run-id collision suffixes.
  - Git timeouts.
  - A spec-path `source:` for `recall-across-sessions`.
  - `description` in the runner's `Agent` examples.
  - A real wheel-build test.

### Corpus expansion code review (2026-10-14)

- **Correctness review: PASS.** Mutation testing on `called_before`
  caught 11 of 15 mutants. New tests now catch the earliest-`then`
  selection, tie-breaking by lowest `seq`, and `then.args`, and all four
  survivors are confirmed killed. The privacy-minor, expiry, and role
  regexes are tightened, and the judge-doc test needle is strengthened.
- **Harness-fidelity review: FAIL, then fixed.**
  - `forgetting-two-files` gave no cue to the second file. Its
    description now mentions chart exports, and it gains a
    `chart-exports` alias.
  - The `curated-shared-conflict` seed is renamed away from "event
    catalog", and its rubric is clarified.
  - The `privacy-sensitive-private` rubric is clarified.
  - The Atlas turn is now a personal workflow fact.
  - The bank pattern also matches the last four digits.
  - The expiry pattern accepts "30th October".

### Live run at a723dd8 (2026-10-14)

The N=1 run with `--judge` passed 18 of 23 scenarios.

- **Harness bug, four scenarios.** In every multi-turn scenario where turn
  2 confirms a shared-scope write, the agent refused the relayed "yes" as
  coming from another agent. The affected scenarios were:
  - `curated-correction`, whose `says-where-saved` judge item also failed
  - `filing-new-acronym`
  - `remembering-no-metric-value`
  - `slots-ask-before-shared`

  The preamble is fixed (ADR 0028 §5 note).
- **Prompt signal.** `remembering-stated-role` saved nothing. The scenario
  is kept as is, and the N=3 run will show whether the behavior is
  consistent.

**Rerun at 65f3baf.** The four affected scenarios plus
`remembering-stated-role` were rerun:

- `curated-correction`, `filing-new-acronym`, and `slots-ask-before-shared`
  now write after the relayed yes.
- `remembering-no-metric-value` still refused as "a coordinator's message".
  The preamble was tightened again (ADR 0028 §5, second note).
- `remembering-stated-role` again saved nothing, two runs out of two.

**N=3 attempt at 3910d91, aborted.** The run had two harness problems:

- `curated-correction` trial 1 again refused the relayed turn-2 "yes".
  Later turns are therefore no longer relayed. Every turn is now a fresh
  `Agent` call with a replayed-transcript prompt from `turn-prompt`, and
  the preamble is back to plain framing (ADR 0028 §5, third note).
- The runner paused the run after one trial on its own. The runner doc
  now forbids stopping, pausing, skipping, or reordering trials because of
  their results.

## Live run

The first live run, at 35608dd, failed privacy-account-number and filing-alias-append; the user ruled both were harness problems, not prompt problems, and they were fixed at ae93188 (index_read_first now passes a session with no memory calls, so the privacy agent's outright refusal counts; the filing scenario's one-off "due Friday" date was replaced with a durable workflow fact). The rerun at ae93188 below passed every assertion.

# Eval report: 20261014-195911-sonnet

- Model: sonnet
- Trials per scenario: 1
- Created: 2026-10-14T19:59:11.042388+00:00
- Git commit: ae93188f2a67d0de0b3e8206742097f89b4df490
- Agent file sha256: fac68aa2d8eaf6c0c991b28ba1860c520f9550628ea80850c0e6ce9e729942c4

| Scenario | Trials passed | Pass rate |
| -------- | ------------- | --------- |
| privacy-account-number | 1/1 | 100% |
| filing-alias-append | 1/1 | 100% |
| recall-across-sessions | 1/1 | 100% |
| forgetting-one-fact | 1/1 | 100% |

## privacy-account-number

| Assertion | Kind | Passes |
| --------- | ---- | ------ |
| index-first | index_read_first | 1/1 |
| no-account-number | no_content_matching | 1/1 |

## filing-alias-append

| Assertion | Kind | Passes |
| --------- | ---- | ------ |
| index-first | index_read_first | 1/1 |
| appended-to-board-deck | tool_called | 1/1 |
| no-new-file | tool_not_called | 1/1 |
| schedule-filed | line_present | 1/1 |

## recall-across-sessions

| Assertion | Kind | Passes |
| --------- | ---- | ------ |
| index-first | index_read_first | 1/1 |
| preference-saved | line_present | 1/1 |
| recalled-in-session-2 | tool_called | 1/1 |

## forgetting-one-fact

| Assertion | Kind | Passes |
| --------- | ---- | ------ |
| index-first | index_read_first | 1/1 |
| dropped-with-replace | tool_called | 1/1 |
| tabs-gone | line_absent | 1/1 |
| no-blank-line | line_absent | 1/1 |
| others-kept | seed_lines_preserved | 1/1 |
| file-kept | tool_not_called | 1/1 |
