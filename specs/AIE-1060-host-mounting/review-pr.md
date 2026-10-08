# PR Review: AIE-1060: Host-mounting smoke test (MCP server adapter)

## What changed & why

ADR 0022 deferred Section 7's server object to this issue. This PR adds it as
`wenchang.mcp`, behind the optional `wenchang[mcp]` extra (`mcp>=2.2,<3`, the
official package, whose FastMCP is now called `MCPServer`).

- **`register_memory_tools`** adds the seven memory tools and the prompt
  resource to an adopter's server.
- **`build_server`** builds a server with the memory prompt as its
  `instructions`.
- **Tool calls.** Every call reads the caller's credentials, binds that
  caller's own `MemoryTools`, forwards the call, and returns the rendered
  result. An optional `on_call` observer sees each call.
- **Descriptions** come from a new public
  `wenchang.tools.tool_descriptions(product)`.
- **Thread safety.** MCP runs tool calls concurrently, so `InMemoryStorage`
  is now thread-safe.
- **Smoke test.** A real MCP client checks what a host sees: names,
  descriptions, schemas, instructions, and the resource.

## Acceptance criteria → tests

`server` below is `tests/test_mcp_server.py`.

| Acceptance criterion | Test(s) |
| -------------------- | ------- |
| US1.1 `tool_descriptions` exported with its signature | `test_tools_descriptions.py::test_tool_descriptions_is_exported_with_signature` |
| US1.2 no product: fresh read-only mapping of cleandoc'd docstrings | `::test_tool_descriptions_without_product_are_cleandoc_docstrings` |
| US1.3 product: independent expectation | `::test_tool_descriptions_with_product_match_independent_expectation` |
| US1.4 bad product: same error as `MemoryTools` | `::test_tool_descriptions_rejects_products_like_memory_tools` |
| US1.5 `descriptions()` delegates | `::test_descriptions_delegates_to_tool_descriptions` |
| US1.6 missing docstring gives `""` | `::test_tool_descriptions_missing_docstring_is_empty` |
| US1.7 existing tests unchanged | `test_tools_descriptions.py` (all pre-existing tests unmodified) |
| US2.1 `mcp` is an extra plus dev only | `test_mcp_packaging.py::test_mcp_is_an_optional_and_dev_dependency_only` |
| US2.2 core never imports `mcp` | `::test_core_modules_do_not_import_mcp` |
| US2.3 clear `ImportError` without the extra | `::test_import_without_extra_names_the_extra` |
| US3.1 exports; keyword-only parameters | `server::test_module_exports_and_keyword_only_parameters` |
| US3.2 seven names | `::test_lists_the_seven_tool_names` |
| US3.3 prefix | `::test_prefix_applies_to_every_tool_name` |
| US3.4 descriptions equal `tool_descriptions` | `::test_descriptions_equal_tool_descriptions` (4 cases) |
| US3.5 product in first line | `::test_description_first_lines_name_the_product` |
| US3.6 schema properties and required set mirror the methods | `::test_input_schemas_mirror_memory_tools_signatures` |
| US3.7 schema types pinned | `::test_input_schema_types_are_pinned` (6 tools) |
| US3.8 prefix rule | `::test_bad_prefix_is_rejected`, `::test_good_prefix_is_accepted` |
| US3.9 non-`str` prefix | `::test_non_str_prefix_is_a_type_error` |
| US3.10 bad product | `::test_bad_product_matches_tool_descriptions` |
| US3.11 empty descriptions fail startup | `::test_empty_descriptions_fail_startup` |
| US3.12 missing description fails startup | `::test_missing_description_fails_startup` |
| US3.13 real `python -OO` fails startup | `::test_python_oo_fails_startup` |
| US3.14 up-front validation, no server created | `::test_build_server_validates_up_front` (7 rows) |
| US3.15 register on an adopter server | `::test_register_on_adopter_server` |
| US3.16 bad prompt; server gains nothing | `::test_register_rejects_bad_prompt` |
| US3.17 register validates like `build_server`; server type | `::test_register_validates_like_build_server`, `::test_register_rejects_non_server` |
| US3.18 collisions; nothing registered | `::test_register_rejects_colliding_tool`, `::test_register_rejects_colliding_prefixed_tool`, `::test_register_twice_is_rejected` |
| US3.19 instructions warning | `::test_register_warns_when_instructions_lack_prompt`, `::test_register_does_not_warn_when_instructions_contain_prompt` |
| US3.20 `memory_instructions` | `::test_memory_instructions_is_the_prompt` |
| US4.1, 4.2 instructions in legacy and discover modes | `::test_instructions_are_the_prompt` |
| US4.3 resource listed | `::test_prompt_resource_is_listed` |
| US4.4 resource serves the prompt | `::test_prompt_resource_serves_the_prompt` |
| US4.5 prompt built once | `::test_prompt_is_built_once` |
| US4.6 bad slots | `::test_bad_slots_is_a_type_error` |
| US5.1 round trip equals `render_result` | `::test_write_then_read_round_trip` |
| US5.2 delete renders ok | `::test_delete_renders_ok` |
| US5.3 per-caller isolation | `::test_each_caller_sees_only_their_own_files` |
| US5.4 bind per call | `::test_every_call_binds_its_own_tools` |
| US5.5 `system/` write is permanent | `::test_system_write_is_rendered_permanent` |
| US5.6 missing file is recoverable | `::test_missing_file_is_rendered_recoverable` |
| US5.7 credential failure leaks nothing, including in logs | `::test_credential_extraction_failure_leaks_nothing` |
| US5.8 `ResolutionFailure` | `::test_resolution_failure_is_rendered` |
| US5.9 off-contract error is internal and logged | `::test_off_contract_error_is_internal_and_logged` |
| US5.10 source stamped | `::test_source_is_stamped` |
| US5.11 prefixed forwarding | `::test_prefixed_tool_forwards` |
| US5.12 schema-invalid arguments | `::test_schema_invalid_arguments_bypass_rendering` |
| US5.13 `area="null"` pre-parse (mcp quirk) | `::test_null_area_is_pre_parsed_to_none` |
| US5.14 `description="null"` pre-parse (mcp quirk) | `::test_null_description_is_pre_parsed_to_no_change` |
| US5.15 `area="[1]"` schema error | `::test_list_shaped_area_is_a_schema_error` |
| US6.1 concurrent create: one winner | `test_storage_memory_threads.py::test_concurrent_create_has_one_winner` |
| US6.2 distinct tokens under concurrent puts | `::test_concurrent_puts_mint_distinct_tokens` |
| US6.3 concurrent update: one winner | `::test_concurrent_update_has_one_winner` |
| US6.4 concurrent MCP writes: one winner, conflicts carry the winner's version | `server::test_concurrent_writes_at_one_version_have_one_winner` |
| US6.5 concurrent MCP creates: distinct versions | `server::test_concurrent_creates_mint_distinct_versions` |
| US7.1 `ToolCallRecord` shape; no aliasing | `::test_tool_call_record_shape`, `::test_record_result_does_not_alias_structured_content` |
| US7.2 record for a successful prefixed call | `::test_record_for_successful_prefixed_call` |
| US7.3 records for failures | `::test_records_for_failed_calls` |
| US7.4 no record for schema-rejected calls | `::test_schema_rejected_call_produces_no_record` |
| US7.5 failing observer | `::test_failing_observer_does_not_reach_client` |
| US7.6 default `None` | `::test_no_observer_by_default` |
| US8.1 stdio | `test_mcp_stdio.py::test_stdio_server_serves_tools_instructions_and_calls` |
| US9.1 to US9.7 docs | ADR 0027; notes in ADRs 0003, 0022, and 0026; ARCHITECTURE.md; README; glossary (reviewed by hand) |

## Architecture / ADR changes

- **[ADR 0027](../../docs/adr/0027-mcp-host-adapter.md)** is new and covers
  the MCP host adapter.
- **Dated notes** were added to ADR 0003 (thread-safe fake), ADR 0022
  (decisions 2, 12, and 13), and ADR 0026 (decisions 3, 5, and 6).
- **ARCHITECTURE.md** gains a new `mcp` module entry and `mcp --> tools` and
  `mcp --> prompts` diagram edges. The `tools` entry now covers
  `tool_descriptions`, the `storage` entry covers thread safety, and the
  overview mentions the optional extra.
- **README** gains a "Serving over MCP" section. The glossary gains "Host
  adapter" and updates "Tool layer" and "Session binding".

## Deviations from spec

- **No gRPC client.** This deviates from the issue text: a real MCP client
  drives the smoke test (ADR 0027 decision 12).
- **Identity is resolved per call, not once per session.** This supersedes
  ADR 0022 decision 2 at the MCP surface (ADR 0027 decision 5).
- **MCP schema validation runs before ADR 0022 decision 13**, and MCP
  pre-parses `"null"` (ADR 0027 decision 11).
- **Process: T4 to T8 landed in one commit.** The implementation was drafted
  before the server tests, then moved aside. The full test file failed on
  the skeleton with the missing symbols, and the module was then restored.
  US8.1 passed on first run because it needed no new code, as planned.

## Look closely at

- **`src/wenchang/mcp.py` collision check.** It reads
  `server._tool_manager` and `server._resource_manager`, which are private
  `mcp` attributes, pinned by `<3`.
- **Wrapper annotations.** `ctx` must be annotated `Context[Any, Any]`
  directly. A `type` alias made `MCPServer` expose `ctx` in every schema, and
  the US3.6 test caught it.
- **Race tests.** The lock is proven by US6.1 to US6.3. Before the lock,
  8 of 8 concurrent creates and updates won, and 399 of 400 tokens were
  distinct. US6.4 and US6.5 are end-to-end smoke checks only.
- **US5.13 and US5.14** pin an `mcp` quirk. They are expected to fail if
  `mcp` stops pre-parsing `"null"`.

## Follow-ups

- Set `ToolAnnotations` (`readOnlyHint`, `destructiveHint`) on the seven
  tools.
- Verify `GcsStorage` and its `google-cloud-storage` client under concurrent
  MCP calls.
- Revisit the collision check when lifting the `mcp<3` bound.
