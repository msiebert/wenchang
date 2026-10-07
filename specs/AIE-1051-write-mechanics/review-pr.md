# PR Review: AIE-1051 — Write mechanics prose

## What changed & why

This fills in the body of the "Choosing a write tool" section of the memory prompt (`write_mechanics.BODY`, section 9 of `build_memory_prompt()`). The body tells the agent to:

- add a fact with `append_line`;
- change one fact with `replace_fact`, quoting the existing line;
- keep `write_file` for new files or restructuring many lines, so a write cannot disturb lines the agent was not editing.

It also says which call carries new aliases and a refreshed description, and gives the exact way to drop one fact line without leaving a blank line. Tests pin the load-bearing phrases.

## Acceptance criteria → tests

All tests are in `tests/test_prompts_write_mechanics.py`.

| Acceptance criterion (Given/When/Then) | Test(s) |
| --------------------------------------- | ------- |
| US1.1 body non-empty | `test_body_is_non_empty` (:30) |
| US1.2 heading "Choosing a write tool" | `test_heading_is_choosing_a_write_tool` (:35) |
| US1.3 section appears in assembled prompt | `test_assembled_prompt_contains_section` (:40) |
| US2.1 "Match the write to the change" | `test_us2_1_match_write_to_change` (:47) |
| US2.2 `append_line` for adding one fact to an existing file | `test_us2_2_append_line_adds_one_fact` (:53), `test_us2_2_add_one_fact_sentence_names_append_line` (:58) |
| US2.3 `replace_fact` for changing one fact, quoting the existing line, surrounding lines intact | `test_us2_3_replace_fact_changes_one_fact` (:72), `test_us2_3_change_one_fact_sentence_names_replace_fact` (:77) |
| US2.4 `write_file` for a new file or restructuring many lines | `test_us2_4_write_file_for_new_or_restructure` (:83), `test_us2_4_restructuring_sentence_names_write_file` (:88) |
| US2.5 mechanically impossible to disturb lines | `test_us2_5_mechanically_impossible` (:96) |
| US3.1 `aliases`, `description` | `test_us3_1_names_metadata_parameters` (:102) |
| US3.2 alias and description sentences each say "same call" | `test_us3_2_metadata_on_same_call` (:108) |
| US3.3 removing an alias / wholesale rewrite with no fact is `write_file` | `test_us3_3_removal_phrases_present` (:117), `test_us3_3_removing_alias_sentence_names_write_file` (:122) |
| US3.4 aliases sentence names all three write tools | `test_us3_4_alias_sentence_names_all_write_tools` (:128) |
| US4.1 drop one fact line with `replace_fact` and an empty `new_string` | `test_us4_1_drop_fact_via_empty_new_string` (:134), `test_us4_1_drop_sentence_names_replace_fact` (:139) |
| US4.2 line break after, or before if none follows | `test_us4_2_drop_includes_line_break` (:145) |
| US4.3 no blank line left | `test_us4_3_no_blank_line_left` (:150) |
| US4.4 `delete_file` only when the whole file goes | `test_us4_4_delete_file_for_whole_file` (:155) |
| US5.1 no docstring mechanics (conflict, version, unique, byte, retry, read-only, slug) | `test_us5_1_no_docstring_mechanics` (:174) |
| US5.2 no label syntax | `test_us5_2_no_label_syntax` (:180) |
| US5.3 under 2500 characters | `test_us5_3_body_under_length_budget` (:185) |

The shared invariants (ASCII text, line length, tool and parameter names, and no paths) are covered by `tests/test_prompts_invariants.py`, unchanged. `make check`: 3355 passed, 6 skipped.

## Architecture / ADR changes

- N/A. Section wording is not API (ADR 0025 decision 2), and the text follows Notion §8.1.

## Deviations from spec

- None from §8.1.
- Addendum decision 2 says the fallback is the line break before the line "for the last line". The body instead says "if none follows it, the line break before it". The two agree for every normal file, and the body's wording is also correct for a last line with no trailing break (an only line ending in a break is covered by the follows-it case). Only this section carries that detail.

## Look closely at

- In the alias and description paragraph, "rewriting the description wholesale with no fact to write" separates a description refreshed alongside a fact write, which rides on that call, from a standalone rewrite, which is a `write_file`.

## Follow-ups

- When the filing (AIE-1049) and forgetting (AIE-1053) sections land, check that their wording agrees with this section on aliases and on dropping a line.

## Adversarial review findings

- Code review A (correctness, spec fidelity): PASS, with NITs only. It confirmed every mechanical claim against `core.py`: dropping a middle line, a last line with or without a trailing break, or a sole line leaves no blank line. Applied: the spec and plan now describe the only-line case accurately. Flagged across issues: AIE-1049's filing body also names the alias-carrying tools, which addendum decision 1 assigns to this section.
- Code review B (coverage, docs): FAIL, round 1. The phrase pins were not tied to sentences, so swapping tools around (for example "add one fact ... use `write_file`") still passed. Fixed with sentence-anchored checks for US2.2, US2.3, US2.4, US3.2, US4.1 and US4.4, plus the extra negative terms "version", "read-only" and "slug", the stricter pin "empty `new_string`", and spec wording that records the "if none follows it" choice against the addendum's "for the last line". All five reviewer mutations now fail a test.
- Code review B, round 2: PASS. All eight reviewer mutations fail the intended test.
- Final spec-reviewer gate: PASS (19/19 criteria). Applied its NIT: the spec's settled-inputs bullet now carries "with no fact to write".
