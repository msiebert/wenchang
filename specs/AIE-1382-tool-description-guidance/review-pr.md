# PR Review: AIE-1382 — Core memory guidance in MCP tool descriptions and the index result

## What changed & why

Claude Desktop and claude.ai drop the MCP `instructions` field, and Claude Code
reportedly truncates instructions and tool descriptions, so models on those
clients never saw the memory rules. The `get_memory_index` MCP result now
appends the full memory prompt as a second text block, and short behavioral
preambles from the new `wenchang.prompts.tool_guidance` are prefixed to the
descriptions of `get_memory_index` (purpose plus call-first) and `write_file`,
`append_line`, `replace_fact` (scope pointer, confidence labels, save now,
refusals). Served descriptions are capped at `MAX_TOOL_DESCRIPTION_CHARS = 2000`,
checked before registration. Always on; `instructions`, the resource, and the
non-MCP API are unchanged.

## Acceptance criteria → tests

| Acceptance criterion (Given/When/Then) | Test(s) |
| --------------------------------------- | ------- |
| AC1: `tools/list` has purpose, call-first, and rules sentence on the index tool; scope pointer, labels, never-`[system]`, save-now, refusals on the write tools; the other three equal `tool_descriptions(product)` | `test_tool_guidance.py`: `test_index_preamble_with_slots_is_purpose_then_call_first`, `test_call_first_sentence_says_to_call_first_and_points_at_rules`, `test_write_preamble_names_the_scope_rules_source`, `test_write_preamble_gives_the_confidence_labels`, `test_write_preamble_says_to_save_as_facts_arise`, `test_write_preamble_lists_what_never_to_store`, `test_write_preamble_is_shared_by_the_write_tools`; `test_mcp_server.py`: `test_descriptions_equal_tool_descriptions`, `test_register_serves_descriptions_for_given_slots`, `test_mcp_tool_descriptions_is_read_only` |
| AC2: preamble, blank line, then existing text verbatim | `test_mcp_server.py`: `test_mcp_tool_descriptions_compose_preamble_and_mechanics`, `test_description_first_lines_name_the_product`, `test_mcp_tool_descriptions_bad_product_matches_tool_descriptions` |
| AC3: every description at most 2000, under 1600 with `REFERENCE_SLOTS` | `test_mcp_server.py`: `test_max_tool_description_chars_is_2000`, `test_served_descriptions_fit_the_limit_with_headroom`, `test_generic_slotless_descriptions_fit_the_limit`; `test_tool_guidance.py`: `test_write_preamble_is_short` |
| AC4: over-long purpose raises `ValueError` naming tool, length, limit; nothing registered | `test_mcp_server.py`: `test_register_rejects_overlong_description`, `test_prefixed_overlong_message_names_the_unprefixed_tool`, `test_build_server_rejects_overlong_description` |
| AC5: successful `get_memory_index` has two blocks (payload, prompt); `structured_content` and `on_call` payload unchanged | `test_mcp_server.py`: `test_successful_index_call_appends_the_prompt_block`, `test_index_observer_payload_is_unchanged`, `test_prefixed_index_call_appends_the_prompt_block` |
| AC6: failed index call and other tools keep one block | `test_mcp_server.py`: `test_failed_index_call_has_one_block`, `test_resolution_failure_index_call_has_one_block`, `test_other_tools_return_one_block_on_success` |
| AC7: `instructions` and the resource are byte-identical | Existing `test_mcp_server.py` instructions and resource tests, unchanged |
| AC8: different slots give different index descriptions; `slots=None` is generic with no purpose | `test_tool_guidance.py`: `test_index_preamble_without_slots_is_generic`, `test_index_preamble_follows_the_slots_given`, `test_write_preamble_holds_no_adopter_text`, `test_preambles_ignore_scope_guidance_seed_areas_and_systems_of_record`; `test_mcp_server.py`: `test_mcp_tool_descriptions_default_arguments` |
| AC9: `tool_descriptions` and `MemoryTools.descriptions()` unchanged | `test_mcp_server.py`: `test_tool_descriptions_and_memory_tools_descriptions_are_unchanged`; `test_evals_server.py`: `test_tool_surface_is_memory_tools_plus_harness` |
| AC10: stdio server lists guided descriptions and returns the prompt as the second block | `test_mcp_stdio.py`: `test_stdio_server_serves_tools_instructions_and_calls` |
| AC11: `make check` passes | Run before merge |
| AC12: docs consistent | ADR 0048, `ARCHITECTURE.md` (this change); README, site, CHANGELOG handled separately |

Also updated per `Allow-test-changes` (not weakened):
`test_module_exports_and_keyword_only_parameters`, `test_register_on_adopter_server`,
`test_mcp_all_is_unchanged`, and `NON_SECTION_MODULES` in
`test_prompts_invariants.py`. The eval server (`evals/server.py`) now passes
`slots=REFERENCE_SLOTS`, so it serves the reference purpose in the index description.

## Architecture / ADR changes

- New [ADR 0048](../../docs/adr/0048-guidance-in-tool-descriptions-and-index-result.md).
- `ARCHITECTURE.md`: prompts section (`tool_guidance` module, not a section),
  mcp section (`register_memory_tools` `slots`, served descriptions, index
  result block, startup length check), and the `evals.server` entry.
- `docs/product/glossary.md`: Host adapter entry mentions the index result block.
  No new term.

## Deviations from spec

- None.

## Look closely at

- The write preamble against `remembering.py` and `privacy.py`: it must not
  contradict them, and nothing ties the wording to them except tests.
- Length failure mode: a long `purpose` now fails `register_memory_tools` and
  `build_server` at startup. Check the message and that nothing is registered.
- `register_memory_tools` trusts that `prompt` matches `slots`; a mismatch is
  not checked.
- Clients that also inject `instructions` see the rules twice, and each index
  call returns about 2.8k more tokens.
- Edits to existing tests (listed above) are contract updates only.

## Follow-ups

- Live `/run-evals` pass after merge to measure call-first and label compliance
  on a client that drops instructions (not a gate).
- Revisit if clients start delivering `instructions` reliably; the preambles and
  second block could then be dropped.
