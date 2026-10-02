# PR Review: AIE-1048 — Abstract transport client interface

## What changed & why

Notion Section 7 says tools call "an abstract client interface" that
"mirrors the core API", with an in-process implementation now and a remote
one later. This PR adds `wenchang.transport.TransportClient`, a
runtime-checkable, synchronous `Protocol` of seven methods. Six are exact
signature mirrors of `MemoryStore` (`read_file`, `write_file`,
`append_line`, `replace_fact`, `list_prefix`, `delete_file`); the seventh
is `get_memory_index(scope_map: Mapping[str, str]) -> MemoryIndex`. The
class docstring states the Section 10.2 error-parity contract. `core` gains
the index return types `CappedPrefix` and `MemoryIndex`, frozen and
type-hardened at construction. It is a contract only: nothing implements or
calls it, and no existing behavior changes.

Files: `src/wenchang/transport.py` (new), `src/wenchang/core.py`
(`CappedPrefix`, `MemoryIndex`), `tests/test_transport_protocol.py` and
`tests/test_core_index_types.py` (new).

## Acceptance criteria → tests

`tp` = `tests/test_transport_protocol.py`, `ix` =
`tests/test_core_index_types.py`.

| Acceptance criterion | Test(s) |
| -------------------- | ------- |
| US1.1 `TransportClient` exported, in `__all__` | `tp::test_transport_client_is_exported` (L148) |
| US1.2 public methods are exactly the seven | `tp::test_transport_client_declares_exactly_seven_methods` (L154) |
| US1.3 six ops mirror `MemoryStore` (`inspect.signature(..., eval_str=True)`) | `tp::test_method_signature_matches_memory_store` (L162, parametrized over six) |
| US1.4 `get_memory_index(self, scope_map: Mapping[str, str]) -> MemoryIndex` | `tp::test_get_memory_index_signature` (L172, against `_Ref` at L61) |
| US1.5 every method documented; class docstring names the error-parity references | `tp::test_method_has_docstring` (L180, parametrized over seven); `tp::test_class_docstring_states_error_parity` (L189, parametrized over `MemoryStore`, `wenchang.errors`, `ValueError`, `MetadataFormatError`, `UnicodeDecodeError`, `BackendUnavailableError`) |
| US2.1 full client passes `isinstance`; pyright accepts the assignment | `tp::test_full_client_is_a_transport_client` (L197); `_TYPED_CLIENT: TransportClient = _FullClient()` (L107) checked by `make typecheck` |
| US2.2 client missing any one method fails `isinstance` | `tp::test_client_missing_a_method_is_not_a_transport_client` (L206, parametrized over seven) |
| US2.3 `TransportClient()` raises `TypeError` | `tp::test_transport_client_cannot_be_instantiated` (L215) |
| US3.1 `CappedPrefix` fields, frozen | `ix::test_capped_prefix_fields_readable` (L118), `ix::test_capped_prefix_is_frozen` (L127) |
| US3.2 `omitted <= 0` or invalid prefix → `ValueError` | `ix::test_capped_prefix_rejects_non_positive_omitted` (L138), `ix::test_capped_prefix_rejects_invalid_prefix` (L145) |
| US3.3 `TypeError` first, `bool` rejected, real-type checks, subclasses normalized | `ix::test_capped_prefix_rejects_none_prefix` (L154), `::test_capped_prefix_rejects_bool_omitted` (L161), `::test_capped_prefix_rejects_non_int_omitted` (L168), `::test_capped_prefix_type_check_precedes_value_check` (L174), `::test_capped_prefix_normalizes_str_subclass` (L180), `::test_capped_prefix_normalizes_int_subclass` (L187), `::test_capped_prefix_rejects_lying_non_positive_int_subclass` (L194) |
| US3.3 normalization ignores overridden conversions; spoofed `__class__` rejected | `ix::test_capped_prefix_int_normalization_ignores_overridden_conversions` (L200), `::test_capped_prefix_str_normalization_ignores_overridden_str` (L209), `::test_capped_prefix_rejects_isinstance_spoofing_prefix` (L217) |
| US3.4 `MemoryIndex` fields, defaults `()`, frozen | `ix::test_memory_index_defaults_empty` (L228), `::test_memory_index_holds_entries_and_capped` (L237), `::test_memory_index_is_frozen` (L251) |
| US3.5 exact `tuple` fields, member types, duplicates | `ix::test_memory_index_rejects_list_entries` (L262), `::test_memory_index_rejects_list_capped` (L268), `::test_memory_index_rejects_tuple_subclass_entries` (L274), `::test_memory_index_rejects_tuple_subclass_capped` (L280), `::test_memory_index_rejects_non_file_entry_member` (L291), `::test_memory_index_rejects_non_capped_prefix_member` (L300), `::test_memory_index_rejects_duplicate_entry_paths` (L348), `::test_memory_index_rejects_duplicate_capped_prefixes` (L354), `::test_memory_index_accepts_distinct_members` (L360) |
| US3.5 members are exact types: spoofed `__class__` and subclasses rejected | `ix::test_memory_index_rejects_isinstance_spoofing_entry` (L306), `::test_memory_index_rejects_isinstance_spoofing_capped` (L314), `::test_memory_index_rejects_file_entry_subclass_member` (L322), `::test_memory_index_rejects_capped_prefix_subclass_member` (L329), `::test_memory_index_rejects_subclass_defeating_duplicate_detection` (L335) |
| US3.6 equal fields → equal and hash equal; differing → unequal | `ix::test_memory_index_equal_fields_equal_and_hash_equal` (L373), `::test_memory_index_differing_entries_unequal` (L383), `::test_memory_index_differing_capped_unequal` (L392), `::test_capped_prefix_equality_and_hash` (L401) |
| US4.1 transport imports only `core`/`file_format`/`version_token`, every import a top-level statement, no `TYPE_CHECKING` guard, no `__future__` | `tp::test_transport_module_imports_are_restricted` (L221; the top-level assertion is the `nested == []` check at L252) |
| US4.2 `core` does not import `transport` (regression guard) | `tp::test_core_does_not_import_transport` (L255) |
| US4.3 no `AIE-\d+` under `src/wenchang/` (regression guard) | `tp::test_library_cites_no_linear_ids` (L265) |

## Architecture / ADR changes

- New [ADR 0019](../../docs/adr/0019-transport-client-interface.md),
  recording the eight decisions from plan.md with rejected alternatives,
  the AIE-1044 → AIE-1046 rescoping of the index implementation, and the
  three orchestrator calls as pending human review.
- `ARCHITECTURE.md`:
  - Bird's-eye view: nine implemented modules, adding `transport` and the
    core index types.
  - **core**: `CappedPrefix` and `MemoryIndex` with their validation order
    and `entries` ordering semantics; `get_memory_index` stays *(planned)*
    for AIE-1046; links ADR 0019.
  - **transport**: no longer *(planned)*. Covers the protocol, the
    exact-mirror rule and its signature-equality test, error parity,
    identity-agnosticism with credentials bound at construction, its
    imports, and that nothing implements or calls it yet.
  - Diagram prose: "the tool and transport layers will call
    `resolve_identity`" corrected to the tool layer only; `file_format`
    noted as used by `transport`. The diagram itself is unchanged.
  - New key invariant: the transport mirrors core exactly.
- `docs/product/glossary.md`: added **Transport client** and **Capped
  prefix**; **Memory index** now names `core.MemoryIndex` and what an empty
  capped list means.
- `README.md`: unchanged; it already describes the tool layer as
  transport-agnostic and lists no modules.

## Deviations from spec

- None from Notion. Error parity reads Section 10.2's "every error"
  literally, including non-taxonomy exceptions.
- Milestone rescoping: the implementation of `MemoryStore.get_memory_index`
  (byte cap, ordering, `capped`), written on AIE-1044, moves to AIE-1046 so
  the in-process client can pass the index conformance cases. AIE-1044 is
  tools only. Recorded in ADR 0019's Context.

## Adversarial review findings

- **Spec review, 3 rounds**: tightened the error-parity wording (every
  exception type core raises for well-typed arguments, naming the
  non-taxonomy types); made the US1.4 signature test sound (a `_Ref` method
  with `collections.abc.Mapping`, not a module-level function or
  `typing.Mapping`); and specified the type hardening of the two new value
  types.
- **Code review**: found that `FileEntry` / `CappedPrefix` subclass members
  passed the real-type check and could defeat duplicate detection and
  equality. Members now must be exact types; spec US3.5 / FR-003 and plan
  decision 8 were updated, and ADR 0019 decision 8 records the rejected
  subclass-accepting design.
- **Coverage review**: 5 mutations survived the suite; tests were added
  until all 5 were killed. The added tests are among the spoofing,
  overridden-conversion, subclass-member, and module-level-import rows in
  the table above.

## Look closely at

- **The three orchestrator calls** made without escalation at spec review
  (ADR 0019, "Orchestrator decisions pending human review"). Confirm or
  change each; the ADR gets approval wording only after you sign off.
  1. Error parity binds every future remote transport: for well-typed
     arguments it must reproduce `ValueError`, `MetadataFormatError`, and
     `UnicodeDecodeError` exactly, and map its own failures to
     `BackendUnavailableError`.
  2. The index algorithm is built under AIE-1046, not AIE-1044.
  3. A remote client binds credentials at construction, never per call.
- **The signature-parity mechanism.** US1.3 compares
  `inspect.signature(..., eval_str=True)` objects, which only holds while
  `transport.py` has no `from __future__ import annotations` and imports
  its annotation types at module level; US4.1 guards both. `Mapping` must
  be `collections.abc.Mapping` (`typing.Mapping` does not compare equal).
  `runtime_checkable` checks presence only, so this test and pyright are
  the only signature guards.
- **The type hardening in `core.py`**, driven by the adversarial reviews
  above. Check the order in `CappedPrefix.__post_init__`: both `TypeError`
  checks (real type, so a spoofed `__class__` fails), then normalization
  via `str.__str__` / `int.__index__` with `object.__setattr__`, then the
  `ValueError` checks on the normalized values. In `MemoryIndex`, fields and
  members must be exact types (`type(x) is ...`): the exact-`tuple` check
  precedes member iteration, so a `tuple` subclass's `__iter__` is never
  called, and `FileEntry` / `CappedPrefix` subclasses are rejected because
  a lying `__getattribute__` or `__eq__` could defeat the duplicate checks
  and US3.6 equality. Messages read type names through `_type_name`, which
  falls back to `<unnamed>`. The `cast(object, ...)` calls exist to
  satisfy pyright strict on fields it believes are already typed.
- **Known gaps, by design**: a `CappedPrefix` built around `__post_init__`
  (via `object.__new__`) is not re-validated by `MemoryIndex`, and
  `FileEntry` contents, including a `str`-subclass `path`, are not
  validated (ADR 0019 Consequences).
- **Scope of hardening.** `MemoryFile`, `FileEntry`, and `ListPage` are
  deliberately not hardened; their remote correctness is an AIE-1045 parity
  case.

## Follow-ups

- AIE-1046: implement `MemoryStore.get_memory_index` and the in-process
  client; add the positive `isinstance(MemoryStore(...), TransportClient)`
  check if `MemoryStore` itself is the client. May extend `MemoryIndex`
  additively.
- AIE-1044: tools written against `TransportClient`, calling
  `scope.check_write` before every mutating call.
- AIE-1047 / AIE-1045: transport conformance harness and cases, including
  error parity (with the non-taxonomy types) and return-value parity for
  `MemoryFile`, `FileEntry`, and `ListPage`.
- Open assumption from spec review: methods are sync-only. If the host
  framework needs async tools, a separate async protocol is an additive
  change.
