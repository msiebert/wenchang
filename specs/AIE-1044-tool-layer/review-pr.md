# PR Review: AIE-1044 — Tool layer

## What changed & why

Notion Section 7 asks for a thin, transport-agnostic tool layer that calls
an abstract client and "format[s] the response". Section 6 says tool code
never touches a credential and "uses the returned fields to build the path
prefix". Section 3 enforces `system/` read-only at the tool layer, and
Section 5 wants version conflicts described to the agent as routine. This
PR adds `wenchang.tools`:

- `MemoryTools`, one per session, holding a resolved identity, the
  adopter's policy, a `TransportClient`, and the surface name. Its seven
  methods are the tools.
- `bind_tools`, the only function that handles credentials.
- `TOOL_NAMES` and `tools()`, which let a host decorate the tools.
- `render_result` and `render_error`, the JSON-safe agent-facing form,
  including the repair material `str(err)` omits.

Tools are scope-relative and take `(scope, area, name)`. The tool checks
that the scope is granted, builds the path under the caller's own entity,
and, for mutations, runs `scope.check_write` on that path before the
client sees it. `wenchang.errors` gains the recoverable
`InvalidArgumentError` for every rejected agent argument. That covers the
core `ValueError` cases ADR 0010 deferred to this layer: `line` and
`old_string` are pre-validated by the tool, and a bad `cursor` is
converted. This is the first code that enforces ADRs 0016 and 0017 on the
agent path.

Files: `src/wenchang/tools.py` (new), `src/wenchang/errors.py`
(`InvalidArgumentError`). New tests: `tests/test_tools.py`,
`tests/test_tools_descriptions.py`, `tests/test_tools_render.py`,
`tests/test_tools_end_to_end.py`, `tests/test_errors_invalid_argument.py`.
No existing test changed.

## Acceptance criteria → tests

`t` = `tests/test_tools.py`, `d` = `tests/test_tools_descriptions.py`,
`r` = `tests/test_tools_render.py`, `e` = `tests/test_tools_end_to_end.py`,
`ia` = `tests/test_errors_invalid_argument.py`. Every test docstring cites
AIE-1044 and its scenario ID. Line numbers are as of commit `263076e`.

`make check` at `263076e`: lint and typecheck clean; 1968 passed,
6 skipped (the pre-existing resolver-conformance skips), 39 deselected
(integration).

| Acceptance criterion | Test(s) |
| -------------------- | ------- |
| US1.1 four read-only properties | `t::test_constructor_exposes_read_only_properties` (L400) |
| US1.2 empty / non-`str` `source` → `ValueError` / `TypeError`; subclass stored as `str` | `t::test_empty_source_raises_value_error` (L416), `::test_non_str_source_raises_type_error` (L423), `::test_str_subclass_source_is_stored_as_exact_str` (L429) |
| US1.3 non-client, non-`Identity`, non-`ScopePolicy` (incl. spoofed `__class__`) → `TypeError` | `t::test_non_client_raises_type_error` (L437), `::test_non_identity_raises_type_error` (L448), `::test_non_policy_raises_type_error` (L461) |
| US1.4 `bind_tools` returns `MemoryTools` with the resolved identity | `t::test_bind_tools_resolves_identity` (L469) |
| US1.5 resolution failure → permanent `ResolverFailureError`, no client call | `t::test_bind_tools_resolution_failure_is_permanent_and_never_calls_client` (L484) |
| US1.6 raising resolver → no secret in message | `t::test_bind_tools_raising_resolver_does_not_leak_message` (L498) |
| US1.7 credentials not retained (weakref + `gc.collect()`) | `t::test_bind_tools_does_not_retain_credentials` (L511) |
| US2.1 `read_file` builds own path, returns client object, no `check_write`; `system/` readable | `t::test_read_file_builds_own_path_and_returns_client_result` (L529), `::test_read_file_may_read_system_area` (L545) |
| US2.2 `list_prefix` builds entity / area prefix, positional args | `t::test_list_prefix_scope_only_passes_entity_prefix_positionally` (L554), `::test_list_prefix_with_area_and_cursor_passes_both_positionally` (L567) |
| US2.3 `get_memory_index()` passes a map built from `grants` (an overridden `scope_map` is ignored), takes no parameters | `t::test_get_memory_index_passes_scope_map` (L583), `::test_get_memory_index_scope_map_comes_from_grants` (L598, `_LyingScopeMapIdentity`), `::test_get_memory_index_takes_no_parameters` (L613) |
| US2.4 client errors from `read_file` propagate as the same object | `t::test_read_file_errors_propagate_unchanged` (L630) |
| US2.5 / US3.3 / US4.6 ungranted scope → `InvalidArgumentError("scope")` with exact detail, no `__cause__`, no `check_write` or client call | `t::test_ungranted_scope_is_invalid_argument` (L643, all six scope-taking tools) |
| US2.6 / US3.5 / US4.6 invalid `area` / `name` → named argument, chained from builder `ValueError` | `t::test_invalid_area_is_invalid_argument` (L657), `::test_invalid_name_is_invalid_argument` (L670) |
| US2.7 `name="a.md"` → `.../a.md.md` | `t::test_name_ending_in_md_gets_md_appended` (L681) |
| US2.8 / US3.10 wrong-type segment or cursor → `InvalidArgumentError`; guarded type name | `t::test_wrong_type_segment_is_invalid_argument` (L703), `::test_none_area_is_invalid_argument_for_file_tools` (L718), `::test_wrong_type_cursor_is_invalid_argument` (L725), `::test_unreadable_type_name_reports_unnamed` (L734) |
| US2.8 lying `str`-subclass segments normalized; exact-`str` path | `t::test_lying_str_segments_are_normalized` (L744) |
| US2.8 / US3.11 lone-surrogate segment → `InvalidArgumentError` chained from `UnicodeEncodeError` | `t::test_unencodable_segment_is_invalid_argument` (L767) |
| US2.9 `Identity.entity_id()` / `scope_map` overrides cannot redirect | `t::test_identity_entity_id_override_cannot_redirect` (L780, `read_file` and `write_file`), `::test_get_memory_index_scope_map_comes_from_grants` (L598) |
| US3.0 check order: segments → grant → path → `check_write` → arguments → client; same path object | `t::test_mutating_tool_checks_then_forwards_same_path_object` (L801), `::test_segment_checks_precede_grant_check` (L816), `::test_grant_check_precedes_path_building` (L827), `::test_path_building_precedes_check_write` (L837), `::test_check_write_precedes_argument_validation` (L855) |
| US3.1 exact forwarded call with `source=`; placeholder metadata | `t::test_mutating_tool_forwards_exact_call` (L866), `::test_write_file_metadata_uses_placeholder_and_tuple_aliases` (L881) |
| US3.2 `system/` → `RestrictedScopeError(SYSTEM_READ_ONLY)`, no client call | `t::test_system_area_is_read_only` (L894) |
| US3.4 `member` → `ROLE_REQUIRED` with roles; `owner` forwarded | `t::test_member_cannot_write_role_gated_scope` (L907), `::test_owner_can_write_role_gated_scope` (L921) |
| US3.6 client taxonomy errors propagate as the same object | `t::test_client_errors_propagate_from_mutating_tools` (L942) |
| US3.7 `expected_version=None` forwarded; list aliases → tuple | `t::test_write_file_none_version_creates` (L954), `::test_write_file_metadata_uses_placeholder_and_tuple_aliases` (L881) |
| US3.8 `description`: every `str.splitlines` boundary, unencodable, `system/` precedence, subclass | `t::test_description_with_newline_is_invalid_argument` (L962, `\n` and `\r`, rejected by `FileMetadata`, `__cause__` is its `ValueError`), `::test_description_with_line_boundary_is_invalid_argument` (L993, ` `, ` `, `\x85`, `\x0b`, `\x0c`, `\x1c`, `\x1d`, `\x1e`, rejected by the tool itself), `::test_unencodable_description_is_invalid_argument` (L971), `::test_bad_description_in_system_area_is_restricted` (L980), `::test_str_subclass_description_is_normalized` (L1002) |
| US3.9 malformed `aliases`; member detail; unencodable member; real-type `Sequence` check; subclass members normalized | `t::test_malformed_aliases_are_invalid_argument` (L1016), `::test_non_str_alias_member_detail` (L1023), `::test_unencodable_alias_member_is_invalid_argument` (L1033, chained from `UnicodeEncodeError`), `::test_class_spoofing_aliases_is_invalid_argument` (L1042, `_ListSpoof`), `::test_str_subclass_alias_members_are_normalized` (L1049) |
| US3.10 one wrong-type rule, exact detail, no `TypeError`; subclasses forwarded as `str` | `t::test_wrong_type_argument_is_invalid_argument` (L1075), `::test_wrong_type_content_detail_sentence` (L1087), `::test_str_subclass_arguments_are_forwarded_as_exact_str` (L1107), `::test_str_subclass_cursor_is_forwarded_as_exact_str` (L1121) |
| US3.11 unencodable `content` / `line` / `new_string` | `t::test_unencodable_text_is_invalid_argument` (L1138) |
| US4.1 client `list_prefix` `ValueError` → `cursor` only when a cursor was passed | `t::test_list_prefix_value_error_becomes_cursor_argument` (L1151), `::test_list_prefix_unreadable_value_error_becomes_cursor_argument` (L1168), `::test_list_prefix_value_error_without_cursor_propagates` (L1183) |
| US4.2 tool pre-validates `line` (`parse_fact`) and `old_string` (non-empty); client `ValueError` propagates | `t::test_non_fact_line_is_rejected_before_client_call` (L1216), `::test_empty_old_string_is_rejected_before_client_call` (L1225), `::test_client_value_error_for_valid_argument_propagates` (L1197, `append_line` and `replace_fact`) |
| US4.3 `MetadataFormatError` / `UnicodeDecodeError` pass through every tool | `t::test_data_integrity_errors_pass_through` (L1240) |
| US4.4 `InvalidArgumentError` class: category, `argument`, `detail`, `str`, empty / non-`str` / subclass `argument` | `ia::test_invalid_argument_error_is_recoverable` (L27), `::test_invalid_argument_error_is_wenchang_error` (L39), `::test_invalid_argument_error_exposes_argument` (L45), `::test_invalid_argument_error_detail_is_composed_sentence` (L51), `::test_invalid_argument_error_str_is_detail_then_guidance` (L57), `::test_invalid_argument_error_rejects_empty_argument` (L69), `::test_invalid_argument_error_rejects_non_str_argument` (L76), `::test_invalid_argument_error_normalizes_str_subclass_argument` (L82) |
| US4.5 `ValueError` from every other client call propagates unchanged | `t::test_unconverted_value_error_propagates` (L1256, `read_file`, `delete_file`, `write_file`, `get_memory_index`), `::test_client_value_error_for_valid_argument_propagates` (L1197, `append_line`, `replace_fact`), `::test_list_prefix_value_error_without_cursor_propagates` (L1183, cursor-less `list_prefix`) |
| US5.1 `TOOL_NAMES` fixed tuple | `d::test_tool_names_are_fixed_tuple` (L164) |
| US5.2 `tools()` bound methods in order; fresh, read-only | `d::test_tools_mapping_holds_bound_methods_in_order` (L170), `::test_tools_mapping_is_fresh_and_read_only` (L184) |
| US5.3 first docstring line is one sentence | `d::test_docstring_first_line_is_one_sentence` (L198) |
| US5.4–5.6, US5.8 pinned phrases (routine, byte ceiling, labels, exactly once, not merged, `system/` read-only, `capped`, index-path mapping) | `d::test_docstring_contains_pinned_phrase` (L211), `::test_mutating_docstring_presents_conflict_as_merge_and_retry` (L219), `::test_name_docstring_says_name_excludes_md` (L231), `::test_get_memory_index_docstring_explains_entity_segment` (L242) |
| US5.7 no `AIE-\d+` in `tools.py` | `d::test_tools_module_cites_no_linear_ids` (L252) |
| US6.1 restricted, module-level imports | `t::test_tools_module_imports_are_restricted` (L1296) |
| US6.2 lower layers don't import `tools` | `t::test_lower_layers_do_not_import_tools` (L1320) |
| US6.3 runtime dependencies unchanged | `t::test_runtime_dependencies_are_unchanged` (L1330) |
| US7.1 `MemoryFile` rendering | `r::test_render_memory_file` (L84), `::test_render_memory_file_with_empty_content` (L106) |
| US7.2 `ListPage` with / without cursor | `r::test_render_list_page_with_cursor` (L117), `::test_render_list_page_without_cursor` (L137) |
| US7.3 `MemoryIndex` capped rows (area-, entity-, scope-level); empty index | `r::test_render_memory_index_with_capped_prefixes` (L145), `::test_render_empty_memory_index` (L169) |
| US7.4 `None` → `{"ok": True}` | `r::test_render_none` (L177) |
| US7.5 unsupported value → `TypeError` | `r::test_render_unsupported_value_raises_type_error` (L190) |
| US7.5a malformed entry path → `None` segments; non-JSON-safe `aliases` / `sources` members dropped | `r::test_render_malformed_entry_path_renders_none_segments` (L196), `::test_render_memory_file_drops_non_str_metadata_members` (L534), `::test_render_list_page_drops_non_str_metadata_members` (L548) |
| US7.6–7.7 repair material for conflict, oversize, match | `r::test_render_version_conflict_error` (L226), `::test_render_oversize_write_error` (L236), `::test_render_replace_fact_match_error` (L246) |
| US7.8 `NotFoundError`, `BackendUnavailableError` reasons | `r::test_render_not_found_error` (L257), `::test_render_backend_unavailable_error` (L268) |
| US7.9 `RestrictedScopeError` with / without `required_roles` | `r::test_render_restricted_scope_role_required` (L275), `::test_render_restricted_scope_without_roles` (L304) |
| US7.10 `InvalidArgumentError`; `ResolverFailureError` minimal | `r::test_render_invalid_argument_error` (L313), `::test_render_resolver_failure_error` (L321) |
| US7.11 data-integrity → `internal` with `str(exc)`; others → `"internal error"` | `r::test_render_data_integrity_errors` (L340), `::test_render_other_exceptions_use_fixed_message` (L353) |
| US7.12 hostile `__str__` / `__name__`, bad `category`, non-JSON-safe payload never raise | `r::test_hostile_str_on_wenchang_error_falls_back` (L402), `::test_hostile_str_on_data_integrity_error_falls_back` (L426), `::test_hostile_str_on_other_exception_never_raises` (L434), `::test_hostile_type_name_on_other_exception_falls_back` (L442), `::test_hostile_type_name_on_wenchang_error_falls_back` (L451), `::test_render_error_never_raises_on_hostile_wenchang_error` (L508) |
| FR-001 exports | `d::test_tools_mapping_holds_bound_methods_in_order` (L170) and every `t` / `r` test importing `MemoryTools`, `bind_tools`, `TOOL_NAMES`, `render_result`, `render_error` |
| FR-002 `check_write` before every mutating call, never on reads | US2.1–2.3, US3.0, US3.2, US3.4 rows |
| FR-003 forwarding and unchanged results | US2.1–2.4, US3.1, US3.6 rows |
| FR-004 `InvalidArgumentError` and its four source groups | US4.4 (class); US4.1 (a); US2.6, US3.8 (b); US2.8, US3.8, US3.9, US3.11 (c); US2.5, US3.8, US3.9, US3.10, US4.2 (d) rows |
| FR-005 credentials only in `bind_tools`, not retained | US1.4–1.7 rows |
| FR-006 docstrings | US5.3–5.8 rows |
| FR-007 no runtime dependency | US6.3 row |
| FR-008 grant check and grant-read entity ID | US2.3, US2.5, US2.9 rows |
| FR-009 rendering | US7.1–7.12 rows |
| SC-001 every scenario cited; `make check` green | docstrings above; `make check` |
| SC-002 end to end over `MemoryStore(InMemoryStorage())`: lifecycle, three rejections, `scope_map`, `sources`, `last_updated`, all rendered and `json.dumps`-safe | `e::test_store_client_satisfies_transport_client` (L109), `e::test_end_to_end_lifecycle` (L114), `e::test_end_to_end_rejections` (L179) |

## Architecture / ADR changes

- New [ADR 0022](../../docs/adr/0022-tool-layer.md) records plan.md
  decisions 1–13 with their rejected alternatives, human decisions 1c and
  2a, the three orchestrator calls as pending review, and the two open
  points from the code review.
- [ADR 0016](../../docs/adr/0016-system-read-only-enforcement.md) and
  [ADR 0017](../../docs/adr/0017-write-restriction-enforcement.md) each get
  an "Update (2026-10-02)" in Consequences: the tool layer exists and its
  tests cover the check-before-call obligation. ADR 0017's update also
  records read scoping as decided: own entity only.
- `ARCHITECTURE.md`:
  - Bird's-eye view: ten implemented modules, with `tools` calling
    `identity`, `scope`, and the transport.
  - **tools**: no longer *(planned)*. Covers per-session `MemoryTools`,
    `bind_tools`, scope-relative signatures, the index scope map built from
    grants, own-entity reads, the check order, the `InvalidArgumentError`
    sources (pre-validations and the one client conversion) and
    pass-throughs, `TOOL_NAMES` / `tools()`, rendering shapes, the
    JSON-safe value rule and the `internal` rule, and framework-agnosticism.
  - **errors**: `InvalidArgumentError` added to the recoverable kinds, and
    to the taxonomy section along with `render_error`.
  - **paths**: notes that the tool layer converts builder `ValueError`s.
  - **transport**: notes that `tools` calls it.
  - Diagram prose: `tools --> scope` and `tools --> transport` are now
    live; `tools` uses `paths`, `file_format`, and `identity` (via
    `bind_tools`). The diagram itself is unchanged.
  - New key invariants: every mutating tool checks the write before the
    transport sees it, and the agent never has to type an entity ID. The
    write-check invariant notes that tools scope reads to the caller's own
    entity.
- `docs/product/glossary.md`: added **Tool layer**, **Session binding**,
  and **Scope-relative address**. **Not granted** notes it is unreachable
  through the tools, and **Recoverable error** names
  `InvalidArgumentError`.

## Deviations from spec

- **`InvalidArgumentError` goes beyond Section 5's list of recoverable
  kinds.** It is a new kind, used only by the tool layer, for agent
  arguments core would reject with an uncategorized `ValueError` and for
  the tool's own argument checks. Core and transport error parity are
  unaffected. Recorded in ADR 0022, decisions 5 and 12, and Consequences.
- **Section 7's "ships as its own server instance" is read as
  framework-dependent and deferred to AIE-1060.** This PR is
  framework-agnostic: no server object and no dependency, with `tools()`,
  `render_result`, and `render_error` provided for a host adapter. Recorded
  in ADR 0022, decisions 1 and 12.

### Human decisions (2026-10-02)

1. **1c, scope-relative tools.** Tools take `(scope, area, name)` and build
   the path from `identity.grants[scope].entity_id`. The agent never types
   an entity ID, `NOT_GRANTED` becomes unreachable through the tools, and
   reads are scoped to the caller's own entity, which decides ADR 0017's
   open point.
2. **2a, tool-layer rendering helpers.** `render_result` and
   `render_error` carry the repair material to the agent, and a host
   adapter calls them.

### Orchestrator calls pending review

Confirm or change each; ADR 0022 decision 12 gets approval wording after
you sign off.

3. Section 7's server object is deferred to AIE-1060.
4. The byte-ceiling number is not in the docstrings, which state only
   that a per-file ceiling applies. The number reaches the agent through
   `OversizeWriteError.limit` (rendered) and prompt text.
5. `InvalidArgumentError` is added to the taxonomy as a recoverable kind.

The spec checkpoint also flagged two smaller calls: one `MemoryTools` per
session with identity resolved once, and `write_file` exposing only
`description` and `aliases`.

## Adversarial review findings

Spec review, 3 rounds:

- **Path normalization and ADR 0017's obligation.** ADR 0017 decision 11
  requires storage to receive the exact `str` the check validated. The
  spec now normalizes every segment once with `str.__str__` before the
  grant lookup, and US3.0 asserts that the path `check_write` saw `is` the
  path the client received.
- **`aliases` corruption.** `FileMetadata` validates neither the container
  nor its members. A bare `str` (a `Sequence` of characters) or a
  non-`str` member would be stored and make every later read and listing
  of that prefix raise `MetadataFormatError`. US3.9 now rejects both as
  `InvalidArgumentError("aliases")`.
- **`InvalidArgumentError` detail semantics.** `detail` now holds the
  composed sentence (`Argument {argument} is invalid: ...`), as every other
  `WenchangError` does, and `argument` is type-checked and normalized. The
  ungranted-scope detail is pinned exactly and lists the available scopes.
- **How the agent learns entity IDs.** The original path-taking tools
  required the agent to type entity IDs. This was escalated, and the human
  chose 1c (scope-relative tools).
- **Formatting.** `str(err)` drops the repair material Section 5's
  merge-and-retry loop needs. This was escalated, and the human chose 2a
  (rendering helpers).
- **Wrong-type rule.** Wrongly typed agent arguments raised an
  uncategorized `TypeError`, and a lone surrogate could reach core as a
  `UnicodeEncodeError` that a per-argument conversion would blame on the
  wrong argument. This was unified into one rule (US3.10, US3.11): always
  `InvalidArgumentError` naming the argument, with UTF-8 checked up front.
- **`render_error` robustness.** It now accepts any `Exception` and never
  raises. Type name and message are read through guards; data-integrity
  errors render as `internal` with their message; other off-contract
  exceptions render the fixed `"internal error"` so internals don't leak.

Code review:

- **`scope_map` was overridable.** `get_memory_index` read
  `identity.scope_map`, which an `Identity` subclass can override to index
  another entity. It now builds the map from `grants` (US2.3), matching
  how paths read `grants[scope].entity_id`.
- **Conversions blamed the agent too broadly.** Every client `ValueError`
  from `append_line` and `replace_fact`, and from `list_prefix` even with
  no cursor, became an agent-argument error. The tool now pre-validates
  `line` (`parse_fact`) and `old_string` (non-empty) itself, converts
  `list_prefix` only when a cursor was passed, and lets every other
  `ValueError` propagate (US4.1, US4.2, US4.5, FR-004(a)).
- **Rendering could still raise.** A `WenchangError` subclass with a
  missing or non-`ErrorCategory` `category`, a non-JSON-safe payload
  value, or hostile `aliases` / `sources` members could make
  `render_error` / `render_result` raise or emit non-JSON. The bad `category` now falls back
  to the internal rendering, bad fields and members are dropped, and
  `_json_value` accepts only exact `str`, non-`bool` `int`, `Enum`
  members, and `frozenset`s of `str` (US7.5a, US7.12, FR-009).
- **`aliases` gaps.** Members weren't UTF-8-checked, and the `Sequence`
  check used the spoofable `isinstance`. Both are fixed (US3.9).
- **`description` line boundaries.** Only `\n` / `\r` were rejected, so
  `\x85`, `\u2028`, `\x0b`, and the other `str.splitlines` boundaries got
  through. All are rejected now (US3.8): the tool itself rejects `\x0b`,
  `\x0c`, `\x1c`–`\x1e`, `\x85`, ` `, and ` ` before the client
  call, while `\n` and `\r` are still rejected by `FileMetadata` and
  surface as `InvalidArgumentError("description")` chained from its
  `ValueError`.
- **Open, recorded in ADR 0022 Consequences:** lookalike `system` areas
  (`System`, Cyrillic `ѕ`, zero-width `Cf` characters) are writable because
  `paths` and `scope` compare exactly. This is a policy question for you.
  Separately, `resolve_identity`'s `from None` leaves the original
  exception, and its credentials frame, reachable as `__context__`.

Gate review:

- **`render_result` hardened.** A `path`, `content`, `version`,
  `description`, or `next_cursor` that is not an exact `str` is dropped
  from the output instead of raising, so `render_result` never raises for
  any value of a supported type and its output is always
  JSON-serializable (US7.5a new scenario, FR-009, plan decision 11,
  ARCHITECTURE.md, ADR 0022 decision 11).
- **US7.12 assertions tightened** in the `render_error` tests.
- **Doc fixes.** The internal fallback is documented as applying when
  `category` is not an `ErrorCategory` member (it said `Enum` member,
  which the code doesn't accept) in spec.md, plan.md, ARCHITECTURE.md,
  and ADR 0022; spec status set to implemented, code-reviewed
  2026-10-02; an unwrapped line in ADR 0022 decision 9 rewrapped.
- **Merge dependency.** ADRs 0020 and 0021 come from the AIE-1046 and
  AIE-1047 branches; those must land before this PR merges.

## Look closely at

- **The orchestrator calls above**, especially whether `InvalidArgumentError`
  should be part of the public taxonomy rather than tool-layer-only.
- **The lookalike-`system` policy question** (ADR 0022 Consequences). One
  option is NFKC/casefold rejection of lookalike areas in the tool layer;
  the other is rejecting `Cf` characters in `paths`. Either changes what an
  agent can write; neither is in this PR.
- **Check order in each mutating tool** (`tools.py`, `write_file`,
  `append_line`, `replace_fact`, `delete_file`). `_path` runs, then
  `check_write`, then argument validation (including the `line` /
  `old_string` pre-validation), then the client call. The ordering is what
  makes a `system/` write with a bad description raise
  `RestrictedScopeError`, not `InvalidArgumentError`.
- **The one remaining client conversion** (`list_prefix` with a cursor).
  `MetadataFormatError` and `UnicodeDecodeError` are re-raised by real
  type. Confirm nothing else wraps a client call.
- **`_entity` and `get_memory_index`** read `identity.grants` directly and
  never call `Identity.entity_id()` or `scope_map`. For writes,
  `check_write` (which also reads the grant) would catch a redirected path
  as `NOT_GRANTED`. Reads, listing, and the index are never checked,
  though, so for them this is the only guard against an `Identity`
  subclass redirecting to another entity.
- **`render_error`'s `internal` rule.** An off-contract exception's message
  is hidden from the agent, so a host must log the original itself. This
  depends on ADR 0019 decision 7: a client that leaks a transport-library
  exception gives the agent "internal error" instead of a transient error.
- **The scope-relative API's ripple effects.** Milestone 4 prompt text and
  the AIE-1059 / AIE-1060 issue text still describe path-taking tools.
- **Docstrings** are the agent-facing contract, and the phrase tests are
  brittle on purpose.

## Follow-ups

- After rebasing on AIE-1046, switch `tests/test_tools_end_to_end.py` from
  the tests-only `_StoreClient` to `InProcessClient`, which exercises real
  index semantics through `get_memory_index`.
- Update the milestone-4 issues (prompt text) and the AIE-1059 / AIE-1060
  issue text for scope-relative `(scope, area, name)` tools.
- AIE-1060: the host server object and adapter (Section 7 "ships as its own
  server instance"), built on `tools()`, `render_result`, and
  `render_error`, with its smoke test.
- Decide the lookalike-`system` policy (tool-layer NFKC/casefold rejection
  or `Cf` rejection in `paths`), then file an issue if either is adopted.
- `identity`: stop `resolve_identity`'s `ResolverFailureError` carrying
  the resolver's exception as `__context__`, so error reporters can't reach
  the credentials frame.
- After human review, update ADR 0022 decision 12 with approval wording
  for the orchestrator calls.
