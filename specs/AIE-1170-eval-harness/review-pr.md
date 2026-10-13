# PR Review: AIE-1170 — Local behavioral eval harness run via Claude Code subagent

> **Do not merge before one live N=1 run of the four required scenarios.**
> Run it in a fresh session from the repo root:
>
> ```
> claude --mcp-config evals/mcp.json --strict-mcp-config --allowedTools mcp__wenchang
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
- **Scenarios and graders.** Scenarios are YAML, with eight shipped.
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
| 1.6 trace fields incl. `request_id`, `duration_s`, timing; harness calls untraced | srv `test_trace_records_carry_timing_and_correlation` |
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
| 3.1 every field; defaults | scn `test_full_scenario_parses_every_field`, `test_defaults_apply` |
| 3.2 reference seeds first; collision rejected | scn `test_reference_seed_comes_first`, `test_seed_colliding_with_reference_seed_is_rejected` |
| 3.3 16 malformed cases (plus unknown tool, missing file) | scn `test_malformed_scenarios_are_rejected[*]`, `test_non_mapping_yaml_is_rejected`, `test_unknown_tool_name_is_rejected`, `test_missing_file_is_rejected` |
| 3.4 corpus loads; unique ids; closed kinds | scn `test_corpus_loads_with_unique_ids`, `test_assertion_kinds_are_the_closed_set` |
| 3.5 corpus is the planned eight; categories; sources; prompt cite | scn `test_corpus_is_the_planned_eight` |
| 4.1 `index_read_first` | grd `test_index_read_first_*` (5 tests) |
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
| 5.1 `new-run` metadata and plan | rpt `test_new_run_writes_metadata_and_plan`, `test_new_run_cli_prints_the_plan` |
| 5.2 unknown id or model exits 2, creates nothing | rpt `test_new_run_rejects_unknown_ids_and_models[*]` |
| 5.3 `grade` | rpt `test_grade_writes_results`, `test_grade_rejects_missing_inputs` |
| 5.4 `report` counts; not-run trials | rpt `test_report_counts_passes_and_lists_unrun_trials`, `test_report_cli_prints_the_path` |
| 5.5 judge verdicts separate; invalid flagged | rpt `test_report_keeps_judge_verdicts_separate` |
| 6.1 correct drivers pass, 1/1 | e2e `test_correct_driver_passes_every_assertion[*8]`, `test_every_shipped_scenario_has_scripted_drivers` |
| 6.2 wrong drivers fail exactly the listed ids, 0/1 | e2e `test_wrong_driver_fails_exactly_the_listed_assertions[*8]` |
| 7.1 wheel, `dev-mode-dirs`, pyright, yaml dev-only | pkg `test_wheel_ships_only_the_library`, `test_editable_install_adds_repo_root`, `test_pyright_covers_evals`, `test_yaml_is_a_dev_dependency_only` |
| 7.2 import from any cwd | pkg `test_evals_imports_from_any_working_directory` |
| 7.3 fixture moved; importers rewritten | pkg `test_tests_fixture_module_is_gone`, `test_no_test_imports_the_old_fixture_module`; existing prompt and MCP tests unchanged and green |
| 7.4 post-#34 relocation | **Pending (T9)**: PR #34 is not merged |
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
  of `build_memory_prompt`". It is recorded in ADR 0028 §5.
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

- **Turn tagging** (`EvalState._tag`) relies on the runner rule that
  `eval_record_turn` runs alone after each reply, with foreground `Agent`
  calls. The runner doc states the rule, and a test cannot enforce it.
- **Strict `index_read_first`** fails a parallel batch of the index read
  and another call. That is intended, and the rationale is in spec 4.1 and
  ADR 0028.
- **`dev-mode-dirs = [".", "src"]`** makes `tests`, `scripts`, and `docs`
  importable as namespace packages in the dev venv.
- **The fixture move.** `tests/test_mcp_server.py`'s `python -OO`
  subprocess snippet no longer inserts `tests/` into `sys.path`, and
  `TESTS_DIR` is gone. The import resolves through `dev-mode-dirs`.

## Follow-ups

- **T9 (pending):** after PR #34 merges and this branch is rebased, rewrite
  #34's four importers to `evals.reference_adopter`. Then delete
  `tests/reference_adopter.py`, replace `evals/reference_adopter.py` with
  `main`'s copy if it changed, and extend `tests/test_evals_packaging.py`.
- **Human:** widen `scripts/hooks/guard-edits.sh` rule 4 for `evals/**`,
  `.claude/agents/wenchang-eval*.md`, `.claude/commands/run-evals.md`, and
  `.gitignore`. Also give doc-updater (rule 5) `AGENTS.md`.
- **Human:** before merge, do the live N=1 run above.
- Port the deferred scenarios after the first live run calibrates them.
  The list is in spec.md's Assumptions.
- An Anthropic SDK driver that writes the same three JSON files.

## Live run

Not yet run. It needs a fresh session launched with the command above.
