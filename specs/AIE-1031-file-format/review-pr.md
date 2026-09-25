# PR Review: AIE-1031 — File format and metadata parse/serialize

## What changed & why

Adds `wenchang.file_format`, the pure conversion layer every later core
function (`read_file`, `write_file`, `append_line`, `replace_fact`,
`list_prefix`) will build on: `ConfidenceLabel`/`Fact` plus `parse_fact`/
`format_fact` for a single line, `BodyLine` plus `parse_body`/
`serialize_body` for a whole body, and `FileMetadata` plus
`metadata_to_map`/`metadata_from_map` for the four metadata fields as a
flat string map. No storage, size limit, or path handling — this issue is
conversion only, with no dependency on storage, transport, scope, or agent
frameworks. Metadata rides beside the body as GCS custom object metadata
rather than markdown frontmatter, and the body parser is lossless,
preserving non-fact lines verbatim so any stored body round-trips
byte-for-byte.

## Acceptance criteria → tests

| # | Given / When / Then | Test(s) |
| - | -------------------- | ------- |
| US1-1 | A stated fact line parses to a Fact with matching label and text | `test_parse_fact_activation_example` |
| US1-2 | Each of the four labels parses to a fact with the matching label | `test_parse_fact_each_label_matches` |
| US1-3 | A heading, blank line, and prose among fact lines parse to other lines in original position, text unchanged | `test_parse_body_mixed_content_returns_non_fact_lines_verbatim` |
| US1-4 | Bad label, uppercase, missing `- `, missing space, or no text after label parses as other, not a fact | `test_parse_fact_non_matching_lines_return_none` (+ `test_parse_fact_never_raises_for_str_without_newline`) |
| US1-5 | A confidence label and text format as `- [<label>] <text>` | `test_format_fact` |
| US1-6 | Fact text with a newline, or empty/whitespace-only text, is rejected at construction | `test_fact_construction_rejects_newline_in_text`, `test_fact_construction_rejects_empty_or_whitespace_only_text` |
| US2-1 | Any body string round-trips exactly through parse then serialize | `test_serialize_body_of_parse_body_round_trips` |
| US2-2 | Trailing newline presence/absence is preserved on round-trip | `test_parse_body_preserves_trailing_newline_presence` |
| US2-3 | The empty body round-trips to the empty body | `test_empty_body_round_trips_to_empty_string`, `test_parse_body_of_empty_string_is_single_empty_element` |
| US2-4 | Unicode, `\r\n` endings, consecutive blank lines, and near-miss fact syntax round-trip exactly | `test_serialize_body_of_parse_body_round_trips` (parametrized corpus incl. unicode/`\r\n`/near-miss cases) |
| US2-5 | A caller-built sequence of fact and other lines round-trips through serialize then parse | `test_serialize_body_of_caller_built_sequence_round_trips_to_same_tuple` |
| US2-6 | An other line containing a newline, or one that would itself parse as a fact, or an empty sequence, is rejected on serialize | `test_serialize_body_rejects_str_element_containing_newline`, `test_serialize_body_rejects_str_element_that_parses_as_fact`, `test_serialize_body_rejects_empty_sequence` |
| US3-1 | Metadata converts to a map with exactly the four keys, each a string value | `test_metadata_to_map_has_exactly_the_four_keys` |
| US3-2 | Any valid metadata round-trips through map conversion unchanged | `test_metadata_round_trips_through_map` |
| US3-3 | Aliases/sources with commas, quotes, brackets, unicode round-trip unchanged | `test_aliases_and_sources_with_special_characters_round_trip_unchanged` |
| US3-4 | Alias order is preserved on round-trip | `test_metadata_to_map_preserves_alias_order` |
| US3-5 | Sources supplied with duplicates appear once (set semantics) | `test_metadata_to_map_sources_deduplicated_and_sorted` |
| US3-6 | A timezone-aware last-updated round-trips to the same instant, encoded as UTC ISO 8601 | `test_last_updated_aware_round_trips_to_same_instant`, `test_last_updated_map_value_is_iso_utc_with_z_without_microseconds`, `test_last_updated_map_value_is_iso_utc_with_z_with_microseconds`, `test_last_updated_non_utc_offset_encodes_as_same_instant_in_utc` |
| US3-7 | A naive last-updated is rejected at construction | `test_naive_last_updated_raises_value_error_at_construction` |
| US3-8 | A description containing a newline is rejected at construction | `test_description_with_newline_or_cr_raises_value_error_at_construction` |
| US3-9 | A map missing any key, or with an undecodable value, is rejected with the offending key named | `test_metadata_from_map_missing_key_raises_with_key_named`, `test_metadata_from_map_undecodable_aliases_raises_with_aliases_key`, `test_metadata_from_map_undecodable_sources_raises_with_sources_key`, `test_metadata_from_map_non_iso_last_updated_raises_with_last_updated_key`, `test_metadata_from_map_naive_last_updated_raises_with_last_updated_key`, `test_metadata_from_map_description_with_newline_raises_with_description_key` |
| US3-10 | A map with extra keys beyond the four ignores them | `test_metadata_from_map_ignores_extra_keys` |
| US3-11 | Empty aliases and sources round-trip empty | `test_empty_aliases_and_sources_round_trip_empty` |
| Edge | Alias and source entries that are themselves empty strings round-trip unchanged | `test_empty_string_alias_and_source_round_trip_unchanged` |

## Architecture / ADR changes

- `ARCHITECTURE.md`: adds `file_format` to the module map as implemented
  (types, functions, dependency-free, used by `core` and `storage`);
  narrows the `core` *(planned)* entry to the API functions only; adds a
  key invariant that metadata rides beside the body, never inside it, and
  that the body parser is lossless.
- `docs/adr/0006-file-format-and-metadata-encoding.md` (new): records
  metadata-beside-body over frontmatter, the lenient/lossless body parser
  as a robustness property rather than a format extension, the canonical
  fact syntax, the metadata map encoding, and `file_format` as its own
  top-level module rather than inside `core`.
- `docs/product/glossary.md`: adds Body line and Metadata map entries.

## Deviations from spec

- See ADR 0006: metadata is read as living beside the stored object (GCS
  custom metadata) rather than as markdown frontmatter, reinterpreting the
  Linear issue's "raw markdown into metadata" wording per Notion Section 5.
  Confirmed with the human at the AIE-1031 spec checkpoint; not
  spec-contradicting.

## Look closely at

- `parse_body`/`serialize_body` tolerate non-fact lines for round-trip
  fidelity, but this is documented as a parser robustness property, not an
  extension of the supported format — worth confirming the module
  docstring and ADR 0006 read that way rather than implying multi-line-kind
  files are a supported feature.
- `metadata_from_map` raises `MetadataFormatError` (a `ValueError`
  subclass) rather than a taxonomy error from AIE-1030; confirm that's the
  intended boundary between data-integrity errors and agent-facing errors.
- `parse_body` splits on `"\n"` only, deliberately not using
  `str.splitlines` semantics — confirm the near-miss and `\r\n` test cases
  cover the cases that matter for the intended storage backend.

## Follow-ups

- AIE-1033 (`write_file`): decide whether to reject a body containing
  non-fact lines at write time.
- AIE-1051 (write-mechanics prompt text): present files as fact lines only,
  with no vocabulary for other line kinds. The constraint is already noted
  on the issue.
- AIE-1044 (tool layer definitions): tool descriptions follow the same
  facts-only rule.
- GCS's ~8 KB total custom metadata limit is not enforced by this issue;
  a future issue may want to surface it as a taxonomy error (e.g.
  `OversizeWriteError`) rather than a raw GCS failure.
