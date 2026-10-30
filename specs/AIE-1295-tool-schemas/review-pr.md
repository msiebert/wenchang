# PR Review: AIE-1295 — Export tool input/output schemas

## What changed & why

Adopters were hand-copying each tool's argument and result shapes into their ToolDefs, so the copies drifted. A new module, `wenchang.schemas`, exports JSON Schema (draft 2020-12) dicts: `tool_schemas(product=None)` gives a `ToolSchema(name, description, input, output, error)` per tool, and `error_schema()` gives the shared error payload schema. Inputs are derived from the `MemoryTools` signatures, and outputs are chosen by return annotation from shapes declared once. A committed snapshot plus validation of real renders fail when a signature or rendered shape changes without the schema. No runtime dependency is added (`jsonschema`/`types-jsonschema` are dev-only). `render_*`, the tool signatures, and `wenchang.mcp` are unchanged. `make check` is green (5510 passed).

## Acceptance criteria → tests

| Acceptance criterion | Test(s) |
| --- | --- |
| US1.1 keys are `TOOL_NAMES` in order; `name` matches key | `test_keys_are_tool_names_in_order` |
| US1.2 descriptions equal `tool_descriptions(product)`; invalid product raises the same | `test_descriptions_equal_tool_descriptions`, `test_default_product_matches_no_product`, `test_invalid_product_raises_what_tool_descriptions_raises` |
| US1.3 valid draft 2020-12, JSON-serializable | `test_every_schema_is_valid_and_json_serializable` |
| US1.4 equal to committed snapshot, property order pinned | `test_schemas_match_committed_snapshot` |
| US1.5 fresh objects per call | `test_each_call_returns_fresh_objects` |
| US1.6 every `ToolSchema.error == error_schema()` | `test_tool_error_equals_error_schema` |
| US2.1 input mirrors signature (order, required, defaults) | `test_input_mirrors_signature` |
| US2.2 MCP-registered input schemas match the export | `test_registered_input_schemas_match_export` (tests/test_schemas_mcp.py) |
| US2.3 signature change fails the snapshot | follows from US2.1 + US1.4 (no separate test) |
| US3.1 / 3.1a successful and edge results validate | `test_successful_calls_validate`, `test_edge_results_validate` |
| US3.2 multi-page listing with string `next_cursor` | `test_paged_listing_validates` |
| US3.3 capped index (entity- and area-level) | `test_capped_index_validates` |
| US3.4 unparseable path renders null location | `test_unparseable_path_validates` |
| US3.5 rendered key union equals declared properties | `test_rendered_keys_cover_declared_properties` |
| US3.6 schemas are closed and complete | `test_read_file_output_is_closed_and_complete` |
| US4.1 every wenchang error class has a fixture | `test_every_error_class_has_a_fixture` |
| US4.2 each fixture validates | `test_error_fixture_validates` |
| US4.3 internal errors validate as `internal` | `test_internal_errors_validate` |
| US4.4 error key union equals declared properties | `test_error_keys_cover_declared_properties` |
| US4.5 `category`/`reason` enums follow the error enums | `test_error_enums_follow_the_error_enums` |
| US4.6 real tool failures validate | `test_real_tool_failures_validate` |
| FR-002 unmapped parameter/default raises `TypeError`; nullable NewType default derives | `test_unmapped_parameter_raises`, `test_nullable_newtype_default_derives` |
| FR-003 unmapped return annotation raises `TypeError` | `test_unmapped_return_raises` |
| US5 documented | ADR 0042, ARCHITECTURE.md, README snippet, `site-src/reference.md` (review by reading) |

All tests are in `tests/test_schemas.py` unless noted.

## Architecture / ADR changes

- New [`docs/adr/0042-exported-tool-schemas.md`](../../docs/adr/0042-exported-tool-schemas.md): JSON Schema not pydantic, derivation sources, flat error schema, on-contract and adopter-subclass stances, drift guards, follow-ups.
- `ARCHITECTURE.md`: new `schemas` module-map entry, a pointer from the `tools` entry, and the module count and layering notes below the diagram.
- Also in this PR, written separately: a "Tool schemas" section in `site-src/reference.md` (with regenerated `site/`) and a short `tool_schemas()` example in README's adopter section.

## Deviations from spec

- None.

## Look closely at

- `src/wenchang/schemas.py` `_type_schema`: the closed type map and the `inspect.unwrap` past the observer decorator. Is `TypeError` the right failure for an unmapped type?
- Error schema stance: one flat schema, so an adopter `WenchangError` subclass with its own fields fails validation (documented, ADR 0042 decision 6).
- Every field is marked required even though `render_result` drops wrong-typed fields from an off-contract client (ADR 0042 decision 7).
- `tests/snapshots/tool_schemas.json` is hand-written from plan.md. Check that it matches the plan's exact schemas.

## Follow-ups

- A pydantic model generator built from this export.
- Advertise each tool's `outputSchema` from the MCP adapter.
