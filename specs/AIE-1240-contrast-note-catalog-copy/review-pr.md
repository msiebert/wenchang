# PR Review: AIE-1240 — Accept a contrast note that names the catalog definition

## What changed & why

`slots-system-of-record`'s `no-catalog-copy` failed 5 of 18 live trials on notes that store the user's order-ships claim and say the event catalog disagrees. The human decided that is acceptable. `no_content_matching` gains an optional `except_contrast: {source, stated}`: a clause naming the catalog definition passes only when attributed to the catalog and the user's version sits in a separate contrasting clause of the same file or call. The scenario uses it and gains a judge item. No prompt change. Without `except_contrast`, grading is unchanged.

Judge item `contrast-note-attributed`: "The turn 1 reply's memory writes mention the event catalog's payment-authorization definition only as a contrast. Anything stored about Purchase Completed records the user's order-shipped definition as what they stated; any stored mention of the catalog definition attributes it to the event catalog, marks the discrepancy as unresolved or awaiting the user's answer, and does not adopt it as the fact. Storing nothing about Purchase Completed passes."

## Acceptance criteria → tests

Graders tests are in `tests/test_evals_graders.py`, all prefixed `test_contrast_`.

| Criterion (spec rows) | Test(s) |
| --------------------- | ------- |
| US1 loader: parses, absent is `None`, malformed rejected (1.1-1.3) | `test_except_contrast_parses`, `test_no_except_contrast_is_none`, `test_except_contrast_rejected` (scenario tests) |
| US2 bare fact fails; unattributed, negated, attributed-without-contrast fail (2.1, 2.7, 2.10) | `bare_catalog_fact_fails`, `attributed_without_contrasting_clause_fails`, `unattributed_negated_mention_fails` |
| US2 issue example, paraphrase, append_line, description contrast pass (2.3-2.6, 2.9) | `issue_example_passes`, `paraphrase_in_file_with_stated_line_passes`, `append_line_to_file_with_stated_line_passes`, `in_description_with_stated_content_passes`, `user_stated_fact_only_passes` |
| US2 clause order, anaphor attribution, boundaries (2.8, 2.12, 2.13, 2.25) | `unattributed_then_attributed_fails`, `attributed_then_unattributed_fails`, `anaphor_preceding_clause_attribution_passes`, `non_anaphor_preceding_clause_fails`, `clause_boundaries`, `anaphor_is_a_whole_word` |
| US2 line limits (2.14, 2.14t) | `nested_list_is_known_false_fail`, `trace_multiline_arg_attribution_never_crosses_lines` |
| US2 trace context: name, description, deleted file, bad args, replace_fact, area/name scan (2.16-2.20, 2.23, 2.26, 2.27) | `call_name_does_not_supply_contrast`, `name_unit_attribution_rules_apply`, `description_never_supplies_stated`, `file_deleted_later_adds_no_context`, `missing_or_nonstring_args_add_no_context`, `replace_fact_*`, `pattern_still_scans_area_and_name` |
| US2 unchanged without `contrast`; details; independence (2.11, 2.22, 2.24) | `test_no_contrast_grades_as_before`, `failure_detail_formats`, `mixed_hits_without_stated_clause_use_plain_detail`, `store_and_trace_scanned_independently` |
| Catalog name in a user clause is not attribution (2.21) | `catalog_name_in_user_clause_is_not_attribution` |
| US3.1 shipped YAML | `test_slots_system_of_record_has_contrast_exception_and_judge` |
| US2.2, US4 drivers | existing CASES entry (wrong driver); `test_slots_system_of_record_bare_fact_fails_only_catalog_copy`, `test_slots_system_of_record_contrast_drivers_pass` |
| US3.2, 3.3, US5 | non-test: YAML read, `make check`, ADR read |

## Architecture / ADR changes

- New `docs/adr/0046-no-content-matching-contrast-exception.md`; short amendment note beside the "Scanned writes" bullet in `docs/adr/0028-behavioral-eval-harness.md`.
- ARCHITECTURE.md unchanged: `evals/` is not the public API.

## Deviations from spec

- None.

## Look closely at

- Clause splitting and the attribution rules in `evals/graders.py` `_no_content_matching`: anaphor gating, never crossing a line, contrast context per file or per call.
- What the reviewers caught:
  - Spec review rounds 1-3: the stated clause could self-satisfy, so it must now be a contrasting clause; area/name were excluded from the context; attribution is anaphor-gated and never crosses a line; boundary tests are discriminating; descriptions could supply `stated` (now content only).
  - Build: the source regex `catalogu?e` never matched "catalog", fixed to `catalog(ue)?`; a pyright error in a test helper; the rubric had to start "The turn 1 reply".
  - Code review: a fail-open when the pattern spans clauses (now fails closed); quadratic clause splitting (now linear); the detail suffix with mixed hits; anaphor whole-word handling.
- Residuals that pass deterministically and are judge-only: an attributed line that adopts the catalog; "authorized (per the event catalog); the order ships afterwards."; "[stated] Purchase Completed is the catalog event name. It fires when payment is authorized." with a separate stated line; punctuation-dependent excusal ("; not shipping" passes, ", not shipping" fails).
- Known false-fail: a nested list with the catalog mention and the authorization on separate lines.

## Follow-ups

- Verification pending, human: live eval. Expect `no-catalog-copy` at 17/18-equivalent or better and `contrast-note-attributed` passing on trials that store a note.

  `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 claude -p "/run-evals --model sonnet --trials 12 --judge slots-system-of-record" --permission-mode dontAsk --mcp-config evals/mcp.json --strict-mcp-config --allowedTools mcp__wenchang "Bash(uv run python -m evals *)" "Edit(evals/runs/**)" --settings '{"includeGitInstructions": false}'`
