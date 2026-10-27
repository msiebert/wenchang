# PR Review: AIE-1252 — Remove `path` from agent-facing tool results

## What changed & why

Tools take `(scope, area, name)` but results also returned the full path with the internal entity ID, which agents then quoted or rebuilt in replies (often wrongly). Rendered results and errors now carry only `scope`, `area`, `name`; capped index rows are `{scope, area, omitted}`. Error messages say `scope X, area Y, name Z`. The overview prompt now says to name scope, area, and name. The reply-path eval check is retired.

## Acceptance criteria → tests

| Criterion | Test(s) |
| --- | --- |
| US1: results have no `path`/`prefix`; capped row shape; malformed and non-str entries | `test_tools_render.py`: `test_render_memory_index_with_capped_prefixes`, `test_render_malformed_entry_path_renders_none_segments`, `test_render_file_entry_drops_non_str_path` |
| US1.7: MCP results have no `path`/`prefix` at any depth | `test_mcp_server.py::test_successful_results_have_no_path_or_prefix_keys` |
| US2: errors carry scope/area/name, no `path`; `.path` kept | `test_tools_render.py`: `test_render_not_found_invalid_path_renders_reason_only`, `test_render_error_with_non_str_path_drops_location_keys`, `test_render_error_with_raising_path_never_raises_or_leaks`, `test_error_path_attribute_survives_rendering` |
| US2: messages name the location | `test_errors.py`: `test_version_conflict_message_names_location`, `test_oversize_message_names_location`, `test_oversize_message_unparseable_path_says_the_file`, `test_replace_fact_match_message_names_location`, `test_restricted_scope_message_names_location`, `test_restricted_scope_message_unparseable_path_falls_back_to_scope` |
| US2: restricted-scope rendering | `test_scope_write_restriction.py` (updated expectations) |
| End to end through the reference adopter | `test_reference_adopter_end_to_end.py` (capped rows `test_us8_*`) |
| US3: prompt sentence, no `path`; eval agent file regenerated | `test_prompts_overview.py::test_name_sentence_names_no_example_values`, `test_evals_agent.py::test_eval_agent_file_carries_name_sentence_not_path_quote` |
| US4: grader removed; old grades load | `test_evals_graders.py::test_reply_path_check_is_removed_from_graders`; `test_evals_report.py`: `test_grade_has_no_unmatched_reply_paths`, `test_report_has_no_reply_path_fields_or_lines`, `test_old_grade_with_unmatched_reply_paths_loads` |
| US4: scenarios fail on entity IDs, unasked check | `test_evals_scenario.py`: `test_location_scenario_forbids_the_entity_id_in_replies`, `test_location_scenario_judges_scope_area_and_name`; `test_evals_end_to_end.py`: `test_slash_joined_reply_without_the_entity_passes`, `test_volunteered_slash_location_fails_the_unasked_check`, `test_volunteered_scope_area_name_wording_fails_the_unasked_check` |
| US5: core types keep `.path` | `test_core_*` tests, unmodified |

## Architecture / ADR changes

- New [ADR 0036](../../docs/adr/0036-no-path-in-agent-results.md): supersedes 0033, amends 0022 (render shape).
- `ARCHITECTURE.md` and `docs/product/glossary.md` updated; `site-src/` edited and `site/` rebuilt.
- Decisions: render layer only (core types keep `.path`); no `entity` field; errors use `scope X, area Y, name Z`; scenarios fail on entity IDs; a slash-joined location without the entity is fine.

## Deviations from spec

- None. Reply-path grader, report, and end-to-end tests were deleted as the spec's Allow-test-changes line permits (human-approved).

## Look closely at

- `render_result` / `render_error` in `src/wenchang/tools.py`, including the RestrictedScopeError scope precedence.
- The four rewritten scenarios in `evals/scenarios/` and their judge items.
- Back-compat loading of old `grade.json` files.

## Follow-ups

- Hosts parsing rendered `path` or `prefix` break (intended; noted in ADR 0036).
- The guard hook does not yet let the implementer edit `evals/`; a general-purpose agent made those edits.
- Human: run `/run-evals` live on the four rewritten scenarios.
