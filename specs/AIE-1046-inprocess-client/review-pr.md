# PR Review: AIE-1046 — In-process transport client and memory index

## What changed & why

Notion §7 wants an in-process transport that calls core directly, and §5
wants `get_memory_index`, the session bootstrap that merges metadata across
every scope under a 64 KB byte cap; ADR 0019 assigned the index
implementation here so the in-process client has something to forward to.
`core` gains `MemoryStore.get_memory_index`, two construction settings
(`index_max_bytes`, `scope_priority`), the public cost function
`index_entry_bytes`, and `INDEX_SYSTEM_AREA`. `transport` gains
`InProcessClient`, a pure pass-through; `MemoryStore` now satisfies
`TransportClient` on its own too. No existing test changed.

## Acceptance criteria → tests

Files: `B` = `tests/test_core_index_bytes.py`, `G` =
`tests/test_core_get_memory_index.py`, `T` =
`tests/test_transport_inprocess.py`, `I` =
`tests/integration/test_gcs_memory_index.py`. Line numbers are the `def`.

| Acceptance criterion (Given/When/Then) | Test(s) |
| --------------------------------------- | ------- |
| US1.1 files in two mapped scopes → exactly those, equal to `list_prefix` entries, `capped == ()` | G:294 `test_index_merges_files_across_scopes_equal_to_list_prefix_entries` |
| US1.2 other entity / other scope → absent | G:313 `test_index_excludes_other_entities_and_scopes` |
| US1.3 `list_page_size=2`, five files → all five | G:329 `test_index_drains_every_page`; I:89 (GCS) |
| US1.4 empty map, every-method-raises storage → `MemoryIndex()` | G:346 `test_index_with_empty_scope_map_never_consults_storage` |
| US1.5 scope with no files → contributes nothing | G:355 `test_index_scope_with_no_files_contributes_nothing` |
| US1.6 malformed key skipped; malformed-first page with size 1 still drains | G:369 `test_index_skips_malformed_keys`; G:383 `test_index_drain_does_not_stop_on_an_empty_page` |
| US1.7 corrupt metadata / `BackendUnavailableError` propagate unwrapped | G:402 `test_index_propagates_metadata_format_error`; G:437 `test_index_propagates_backend_unavailable_error_unwrapped` |
| US1.8 storage `get` raises → index succeeds | G:450 `test_index_never_reads_bodies` |
| US1.9 `u-1` does not match `u-10` | G:464 `test_index_prefix_is_segment_aligned` |
| US1.10 unrenderable `last-updated` → `MetadataFormatError("last-updated")`, at any cap | B:76 `test_unrenderable_last_updated_raises_metadata_format_error`; G:419 `test_index_unrenderable_entry_raises_regardless_of_cap` |
| US1.11 lone surrogate: path/description 3 bytes, alias/source 6-byte escape | B:94, B:100, B:105, B:114 `test_lone_surrogate_in_{path,description}_counts_three_bytes`, `test_lone_surrogate_in_{alias,source}_counts_its_json_escape` |
| US1.12 subclass overriding `list_prefix` → index unchanged | G:478 `test_index_drains_through_base_list_prefix_not_subclass_override` |
| US2.1 `system/` first by recency, rest one flat recency tier | G:503 `test_index_orders_system_first_then_flat_recency` |
| US2.2 `("org","user")` reorders non-system only | G:521 `test_index_scope_priority_applies_only_to_non_system_entries` |
| US2.3 unlisted scopes one trailing tier, by recency not name | G:540 `test_index_unlisted_scopes_form_one_trailing_recency_tier` |
| US2.4 ties by full path, not fan-out order; 1 µs difference orders newest first | G:560 `test_index_breaks_timestamp_ties_by_path_ascending`; G:579 `test_index_tiebreak_uses_full_path_not_fan_out_order`; G:593 `test_index_orders_one_microsecond_difference_newest_first` |
| US2.5 priority scope absent from map ignored | G:610 `test_index_ignores_priority_scopes_absent_from_scope_map` |
| US2.6 only the area segment decides the `system/` tier | G:630 `test_index_system_tier_is_decided_by_area_segment_only` |
| US3.1 reference entry 85; `é` alias 93; `é` description 86; version counts; default 64 KiB | B:48 `test_reference_entry_costs_85_bytes`; B:54 `test_non_ascii_alias_counts_its_json_escape`; B:60 `test_non_ascii_description_counts_utf8_bytes`; B:65 `test_version_length_counts`; B:71 `test_default_index_max_bytes_is_64_kib` |
| US3.2 cap == total → all included | G:667 `test_index_cap_is_inclusive` |
| US3.3 cap one short → last omitted, its area prefix count 1 | G:682 `test_index_cap_one_byte_short_omits_last_entry`; I:107 (GCS) |
| US3.4 stop at first miss though a later entry fits | G:697 `test_index_inclusion_stops_at_first_miss` |
| US3.5 `capped` sorted by prefix with counts | G:717 `test_index_capped_is_sorted_by_prefix_with_counts` |
| US3.6 cap below first entry → `entries == ()` | G:743 `test_index_cap_smaller_than_first_entry_omits_everything` |
| US3.7 `index_max_bytes <= 0` → `ValueError`; default 65536 | G:763 `test_memory_store_rejects_non_positive_index_max_bytes`; G:771 `test_default_index_max_bytes_is_64_kib` |
| US3.8 `capped` size not charged | G:779 `test_index_capped_section_size_is_not_counted` |
| US4.1 read-only `scope_priority` / `index_max_bytes` properties | G:803 `test_scope_priority_and_index_max_bytes_are_read_only_properties` |
| US4.2 `scope_priority` validation and order (bare and empty `str`/`bytes`/`bytearray` rejected) | G:845 `test_scope_priority_rejects_non_sequence_or_bare_string` (incl. `empty-str`, `empty-bytes`, `empty-bytearray` cases); G:854 `..._rejects_non_str_member`; G:861 `..._type_errors_precede_value_errors`; G:873 `..._invalid_entry_checked_before_duplicate`; G:879 `..._rejects_duplicate`; G:885 `..._normalizes_str_subclass_members` |
| US4.3 list accepted, copied to tuple | G:893 `test_scope_priority_list_is_copied_to_tuple` |
| US4.4 non-`Mapping` / spoofed `__class__` → `TypeError`, storage untouched | G:911 `test_scope_map_must_be_a_real_mapping`; G:845 (spoofed `Sequence`) |
| US4.5 `scope_map` validation order and messages | G:1024 `test_scope_map_items_must_be_pairs`; G:921 `test_scope_map_non_str_value_raises_type_error_before_value_errors`; G:931 `..._non_str_key_raises_type_error`; G:939 `..._key_type_checked_before_value_type`; G:952 `..._value_errors_follow_sorted_scope_order`; G:963 `..._values_validated_before_any_storage_call`; G:973 `..._duplicate_detected_after_normalization`; G:985 `..._prefix_built_from_normalized_values`; G:997 `..._invalid_entity_id_raises_value_error`; G:1005 `..._duplicate_scope_raises_value_error`; G:1035 `..._items_is_read_exactly_once`; G:1048 `..._str_subclass_keys_and_values_are_normalized` |
| US4.6 iteration order does not matter | G:1061 `test_index_is_independent_of_scope_map_iteration_order` |
| US4.7 `True` / `1.5` cap accepted | G:1084 `test_index_max_bytes_accepts_non_int_positive_values` |
| US5.1 client and store are `TransportClient`; exported | T:176 `test_client_and_store_are_transport_clients`; T:187 `test_in_process_client_is_exported` |
| US5.2 six methods return the store's object with same args; `delete_file` returns `None`, even if the store returns a value | T:193 `test_value_methods_forward_unchanged`; T:210 `test_delete_file_forwards_and_returns_none`; T:233 `test_delete_file_returns_none_even_if_store_returns_a_value` |
| US5.3 exceptions propagate as the same object, no added cause/context | T:252 `test_exceptions_propagate_unchanged` |
| US5.4 end-to-end equals direct store | T:293 `test_end_to_end_matches_direct_store` |
| US5.5 non-store → `TypeError` (even if its type's `__name__` raises); subclass accepted; spoofed class rejected | T:305 `test_non_store_is_rejected`; T:313 `test_store_subclass_is_accepted`; T:328 `test_spoofed_class_is_rejected`; T:346 `test_non_store_with_raising_type_name_is_rejected_with_type_error` |
| US5.6 signatures equal the protocol's | T:355 `test_client_signature_matches_protocol`; T:365 `test_store_get_memory_index_signature_matches_protocol` |
| US6.1 `transport` imports only `core`/`file_format`/`version_token`; `core` not `transport` | T:372 `test_transport_module_imports_are_restricted`; T:410 `test_core_does_not_import_transport` |
| US6.2 `core` does not import `scope`; `INDEX_SYSTEM_AREA == scope.SYSTEM_AREA` | B:119 `test_index_system_area_matches_scope`; existing `tests/test_scope_system.py:339` `test_core_does_not_import_scope` |
| US6.3 no `AIE-\d+` under `src/wenchang/` | T:417 `test_library_cites_no_linear_ids` |
| SC-002 fan-out and cap on `GcsStorage` (fake-gcs-server) | I:89 `test_get_memory_index_drains_every_page_and_orders_by_recency`; I:107 `test_get_memory_index_caps_last_entry_one_byte_under_total` |

## Architecture / ADR changes

- New [ADR 0020](../../docs/adr/0020-memory-index-and-in-process-client.md):
  decisions 1–11 (settings, entry cost, stop-at-first-miss, area-level
  `capped`, tiering, tiebreak and integer key, validation order, base-method
  drain, `INDEX_SYSTEM_AREA`, `ValueError` not `NotFoundError`,
  `InProcessClient`, integration coverage), the four pending orchestrator
  decisions, and an "Adversarial review" note.
- `ARCHITECTURE.md`: bird's-eye (all seven core operations implemented,
  `InProcessClient` exists); `core` entry (new settings and their
  validation order, `get_memory_index` algorithm including item-shape check
  and up-front sizing, `index_entry_bytes`, `INDEX_SYSTEM_AREA`);
  `transport` entry (`InProcessClient`, `delete_file` always `None`,
  guarded type name, `MemoryStore` satisfies the protocol); diagram prose;
  new index-cap invariant; transport invariant now says seven operations.
- [ADR 0019](../../docs/adr/0019-transport-client-interface.md): the
  pending index-location item notes it is realized by ADR 0020 (still
  pending review).
- [ADR 0010](../../docs/adr/0010-list-prefix-pagination.md): Update
  paragraph pointing the deferred index fan-out at ADR 0020.
- `docs/product/glossary.md`: Memory index (cost rule, inclusive prefix
  cap), Capped prefix (area prefixes), new Scope priority and In-process
  client entries.

## Deviations from spec

- None from the Notion spec. Four refinements fill places where §5 is
  silent; they are orchestrator decisions recorded in ADR 0020 as pending
  your review:
  1. **Byte accounting**: an entry costs the UTF-8 bytes of path +
     canonical `metadata_to_map` rendering + version (`index_entry_bytes`).
  2. **Stop at the first miss**: `entries` is an exact prefix of the order.
  3. **Unlisted scopes form one trailing tier**, by recency.
  4. **`capped` prefixes are areas** (`scope/entity/area/`).

## Adversarial review findings

**Spec review** (three rounds, before building). Findings that changed the
design:

- **`str` as `Sequence[str]`**: `scope_priority="user"` would have become
  four one-letter tiers; bare `str`/`bytes`/`bytearray` are now a
  `TypeError` (decision 6a).
- **Storage-untouched probes**: "raises before storage" claims were only
  asserted on outcomes; the validation tests now use a storage whose every
  method raises `AssertionError`, and the never-reads-bodies case a storage
  whose `get` raises.
- **Validation order**: mixed bad inputs were ambiguous; all `TypeError`s
  now precede any `ValueError`, `items()` is read once, and value checks
  run in sorted scope order, with exact messages pinned (US4.2, US4.5).
- **Surrogates and `OverflowError`**: a lone surrogate passes
  `is_valid_segment` but crashed `encode("utf-8")`, and an extreme stored
  timestamp parsed but overflowed on re-render; now `surrogatepass` and a
  `MetadataFormatError` conversion (US1.10, US1.11).
- **Float sort key**: `datetime.timestamp()` loses microseconds for
  far-future dates and creates false ties; the key is now an exact integer
  microsecond offset (US2.4).

**Code review** (after implementation). Each finding was fixed with a test:

- **Cap-dependent raise**: entries were sized lazily during the inclusion
  walk, so an unrenderable `last-updated` past the cap never raised. Every
  ordered entry is now sized first (G:419).
- **Item shape**: a `Mapping` whose `items()` yields non-pairs (e.g. the
  2-char string `"ab"`) escaped as an unpacking error. Each item must now be
  exactly a 2-`tuple`, else `TypeError("scope_map items must be (str, str)
  pairs")`, checked before the key/value types (G:1024).
- **`delete_file` passthrough**: `InProcessClient.delete_file` returned
  whatever a store subclass returned; it now always returns `None` (T:233).
- **Unguarded type name**: `InProcessClient`'s `TypeError` read
  `type(store).__name__` directly; it now uses a guarded helper that falls
  back to `<unnamed>` (T:346).

**Coverage review** (mutation testing). 48 mutants. 5 real survivors were
killed with new tests: full-path tiebreak (G:579), key checked before value
(G:939), validation before any storage call (G:963), observable
normalization (G:973, G:985), and empty `str`/`bytes`/`bytearray`
`scope_priority` (G:845). 3 survivors are equivalent mutants.

## Look closely at

- **The four orchestrator calls above.** Confirm or override; each is
  reversible, and ADR 0020's pending section is updated either way.
- **Validation order** in `MemoryStore.__init__` and `get_memory_index`
  (`src/wenchang/core.py`): every `TypeError` first, item shape before
  key/value type. Note in `__init__` the `scope_priority` type checks run
  before the existing positivity checks, and its `ValueError` checks after
  them.
- **Base-method drain**: `MemoryStore.list_prefix(self, prefix, cursor)`
  rather than `self.list_prefix`, looping on `next_cursor is None` only
  (decision 6b, US1.6, US1.12).
- **Exact-integer recency key**:
  `(last_updated - _EPOCH) // timedelta(microseconds=1)` in `sort_key`.
- **Up-front sizing**: one unrenderable file anywhere in the mapped scopes
  now fails the whole index, at every cap.

## Follow-ups

- AIE-1047 / AIE-1045: transport conformance harness and cases, including
  the §10.2 index-behavior cases, run against `InProcessClient`.
- AIE-1044: tool layer, including the `get_memory_index` tool and how it
  renders entries relative to `index_entry_bytes`.
- Possible: move `SYSTEM_AREA` to `paths` so `core` and `scope` share one
  constant instead of `INDEX_SYSTEM_AREA` pinned by a test.
