# Tasks: AIE-1240

Each group is test-first: test-writer writes failing tests (`tests/**` only), then implementer makes them pass (`evals/**`). Spec refs are `spec.md` rows. Interfaces are in `plan.md`.

## T1 - Loader (US1)

- [ ] T1a test-writer, `tests/test_evals_scenario.py`:
  - 1.1 `test_except_contrast_parses`
  - 1.2 `test_no_except_contrast_is_none`, `test_positional_no_content_matching_keeps_working`
  - 1.3 `test_except_contrast_rejected` (one parametrized function over: not a mapping, missing source, missing stated, unknown key, bad source regex, bad stated regex; each asserts the where string)
- [ ] T1b implementer: `evals/scenario.py`: add and export `ContrastException`; add `contrast` to `NoContentMatching`; allow `except_contrast` in `_KIND_KEYS["no_content_matching"]`; parse and validate.

## T2 - Grader (US2)

- [ ] T2a test-writer, `tests/test_evals_graders.py` (`_file`, `_call`, `_one`):
  - 2.1 `test_contrast_bare_catalog_fact_fails`
  - 2.3 `test_contrast_issue_example_passes`
  - 2.4 `test_contrast_paraphrase_in_file_with_stated_line_passes`
  - 2.5 `test_contrast_append_line_to_file_with_stated_line_passes`
  - 2.6 `test_contrast_in_description_with_stated_content_passes`
  - 2.7 `test_contrast_attributed_without_contrasting_clause_fails` (parametrized over the three texts)
  - 2.8 `test_contrast_unattributed_then_attributed_fails`, `test_contrast_attributed_then_unattributed_fails`
  - 2.9 `test_contrast_user_stated_fact_only_passes`
  - 2.10 `test_contrast_unattributed_negated_mention_fails`
  - 2.11 `test_no_contrast_grades_as_before`
  - 2.12 `test_contrast_anaphor_preceding_clause_attribution_passes`, `test_contrast_non_anaphor_preceding_clause_fails`
  - 2.13 and 2.25 `test_contrast_clause_boundaries` in `tests/test_evals_graders.py`: one parametrized, verdict-based test that does not import the splitter. Cases: the four 2.13 cases (a)-(d); "Fires on payment authorization, etc. per the catalog." passes; "Fires on payment authorization, etc. The catalog says so." fails; each of `vs.` before an uppercase word, `!`, `?`, `;`, `…`, and a line break fails when the catalog mention follows the authorization clause. Each case has a stated line in the file.
  - 2.14 `test_contrast_nested_list_is_known_false_fail`
  - 2.14t `test_contrast_trace_multiline_arg_attribution_never_crosses_lines`
  - 2.26 `test_contrast_name_unit_attribution_rules_apply`
  - 2.27 `test_contrast_description_never_supplies_stated`
  - 2.15 `test_contrast_residual_attributed_then_ships_afterwards_passes`
  - 2.16 `test_contrast_call_name_does_not_supply_contrast`
  - 2.17 `test_contrast_file_deleted_later_adds_no_context`, `test_contrast_missing_or_nonstring_args_add_no_context`
  - 2.18 `test_contrast_replace_fact_final_file_holds_stated_line_passes`
  - 2.19 `test_contrast_replace_fact_stated_line_gone_fails`
  - 2.20 `test_contrast_replace_fact_old_string_not_scanned`
  - 2.21 `test_contrast_catalog_name_in_user_clause_is_not_attribution`
  - 2.22 `test_contrast_failure_detail_formats`
  - 2.23 `test_contrast_pattern_still_scans_area_and_name`
  - 2.24 `test_contrast_store_and_trace_scanned_independently`
- [ ] T2b implementer: `evals/graders.py` `_no_content_matching`: clause splitting, attribution, contrasting clauses, store and trace contexts, detail suffix.

## T3 - Scenario and end-to-end (US2.2, US3, US4)

- [ ] T3a test-writer:
  - `tests/test_evals_end_to_end.py`: 2.2 unchanged, covered by the existing CASES entry (no new test), 4.1 `test_slots_system_of_record_bare_fact_fails_only_catalog_copy`, 4.2 `test_slots_system_of_record_contrast_drivers_pass` (issue example, paraphrase, append_line).
  - `tests/test_evals_scenario.py`: 3.1 `test_slots_system_of_record_has_contrast_exception_and_judge`.
- [ ] T3b implementer: `evals/scenarios/slots-system-of-record.yaml`: add `except_contrast`, replace the comment (3.2, non-test), add the judge item.
- [ ] T3c implementer: `make check` (3.3, non-test).

## T4 - Docs (doc-updater; 5.1 and 5.2 are non-test)

- [ ] T4a New `docs/adr/0046-no-content-matching-contrast-exception.md`, including the residuals (punctuation-dependent excusal among them) and that the judge item is the backstop.
- [ ] T4b `docs/adr/0028-behavioral-eval-harness.md`: note near the "Scanned writes" bullet pointing to ADR 0046.
- [ ] T4c `review-pr.md` at PR time.

## T5 - Final gate

- [ ] T5a `make check` green.
- [ ] T5b Human (3.4, non-test): live run of `slots-system-of-record` (command in spec US3.4).

## Order

T1 then T2 (the grader reads the new dataclass), then T3. T4 can run in parallel with T2 and T3 once the plan is approved. T5 is last.
