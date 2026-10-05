# PR Review: AIE-1053 — Forgetting

## What changed & why

`forgetting.BODY` in `src/wenchang/prompts/forgetting.py` now holds the text
for the last prompt section, "Forgetting", following Notion §8.1 and the
Linear issue. It gives the agent two moves: drop one fact line with
`replace_fact`, or remove the whole file with `delete_file`. Removal is
total, and anything derived only from the removed fact goes too. When it is
unclear which move the user means, the agent asks. A fact whose in-line
expiry date has passed is a candidate for removal that the agent judges,
not something removed automatically. Content in `system/` is never removed.
The pins are in `tests/test_prompts_forgetting.py`. No other source file
changed.

## Acceptance criteria → tests

`f` = `tests/test_prompts_forgetting.py`, `i` = `tests/test_prompts_invariants.py`.
Line numbers are as of commit `6cee80f`. Phrase pins are cases of
`f::test_forgetting_body_contains_phrase` (L62); the parametrize id is shown.

`make check`: lint and typecheck clean; 3331 passed, 6 skipped.

| Acceptance criterion | Test(s) |
| -------------------- | ------- |
| US1.1 `BODY` non-empty | `f::test_forgetting_body_is_non_empty` (L19) |
| US1.2 `HEADING == "Forgetting"` | `f::test_forgetting_heading` (L24) |
| US1.3 prompt ends with the forgetting section | `f::test_build_memory_prompt_ends_with_forgetting_section` (L29) |
| US2.1 `two moves` | `[US2.1-two-moves]` |
| US2.2 `` `replace_fact` ``, `fact line` | `[US2.2-replace-fact]`, `[US2.2-fact-line]` |
| US2.3 `` `delete_file` ``, `whole file` | `[US2.3-delete-file]`, `[US2.3-whole-file]` |
| US2.4 no `` `write_file` `` / `` `append_line` `` | `f::test_forgetting_body_omits_write_tools` (L72) |
| US2.5 `write-tool section` | `[US2.5-write-tool-section]` |
| US2.6 `only content` | `[US2.6-only-content]` |
| US3.1 `Removal is total` | `[US3.1-removal-is-total]` |
| US3.2 no `used to` / `used-to` / `formerly` / `previously believed` | `f::test_forgetting_body_has_no_used_to_tombstones` (L80) |
| US3.3 `solely` | `[US3.3-solely]` |
| US3.4 `` `[inferred]` `` | `[US3.4-inferred]` |
| US3.5 `description`, `aliases` | `[US3.5-description]`, `[US3.5-aliases]` |
| US4.1 `ambiguous` and `\bask\b` | `[US4.1-ambiguous]`, `f::test_forgetting_body_says_ask` (L67) |
| US5.1 `end date`, `candidate` | `[US5.1-end-date]`, `[US5.1-candidate]` |
| US5.2 `not automatically` | `[US5.2-not-automatically]` |
| US5.3 `maintenance` | `[US5.3-maintenance]` |
| US6.1 `` `system/` ``, `curated-content section` | `[US6.1-system]`, `[US6.1-curated-content-section]` |
| US6.2 `Never drop or delete` | `[US6.2-never-drop-or-delete]` |
| US7 shared invariants (unchanged) | `i::test_text_is_ascii_with_short_lines` (L229), `::test_no_linear_ids_in_prompt_sources` (L234), `::test_text_has_no_paths_braces_or_entity` (L245), `::test_text_tool_calls_use_real_names_and_parameters` (L251), `::test_text_snake_case_identifiers_are_agent_visible` (L258), `::test_text_has_no_adopter_scope_names` (L274), `::test_text_length_limit` (L280) |

## Architecture / ADR changes

- N/A. Section wording is not API (ADR 0025, decision 2), and the text
  follows §8.1.

## Deviations from spec

- None.

## Look closely at

- **Pointers to sibling sections.** The text points in plain words to the
  "write-tool section" (AIE-1051, heading "Choosing a write tool") and the
  "curated-content section" (AIE-1052). Both sections land in sibling PRs.
  Check that the names will match once those PRs merge.
- **Paraphrasing "no softened 'used to think X'".** §8.1's example is not
  quoted, because quoting it would show the agent the phrasing it should
  avoid. The negative pin in US3.2 enforces this. Check that the paraphrase
  still carries the rule.
- **Two rules added during spec review**, both derived from "Removal is
  total": dropping a file's only fact means deleting the file (US2.6), and a
  description or aliases that still point to the removed fact get updated
  (US3.5).

## Follow-ups

- None required. Behavioral eval scenarios E1-E6 in `spec.md` are input to a
  later eval harness.

## Adversarial review findings

(Filled in after code review.)
