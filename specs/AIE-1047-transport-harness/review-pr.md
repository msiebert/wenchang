# PR Review: AIE-1047 — Shared transport conformance harness

## What changed & why

Notion §10/§10.2 require an executable transport conformance suite that
runs identically against any `TransportClient` and holds the in-process
and remote transports behaviorally indistinguishable. This adds
`wenchang.testing.TransportConformance` (new
`src/wenchang/testing/transport_conformance.py`, re-exported from
`wenchang.testing`): a pytest mixin with seven required fixtures, five
baseline cases, and the public helpers AIE-1045 will build the exhaustive
§10.2 cases from (`require_fresh`, `sentinel_path`, `without_sentinel`,
`sentinel_entry_bytes`, `probe_path`, `expect_error`, `canonical_*`,
`check_*`). Tokens are never compared, only handed back; `last_updated` is
round-tripped only between two server-stamped results. The repo runs the
suite against `InProcessClient` with a ticking clock, and self-tests drive
a deliberately broken client through each case. No existing module
changes. Branch is based on `AIE-1046-inprocess-client`; the PR targets
that branch until it merges.

## Acceptance criteria → tests

Line numbers are as of this draft. `self` =
`tests/test_transport_conformance_self.py`, `ref` =
`tests/test_transport_conformance_reference.py`, `pkg` =
`tests/test_testing_package.py`. Every US4 test also runs the same case
against the reference client and the forwarding wrapper first
(`_reference_passes`, self:1193), which is US4.10.

| Acceptance criterion (Given/When/Then) | Test(s) |
| --------------------------------------- | ------- |
| US1.1 Reference fixtures → all five baseline cases pass, none skipped | ref:48 `TestInProcessClient`; ref:92 `test_ticking_clock_strictly_increases`; self:1327 `test_forwarding_wrapper_satisfies_every_case` |
| US1.2 Non-`TransportClient` client → every case fails `fixture client` naming the type | self:1598 `test_non_client_fails_every_case` |
| US1.3 Bad fixture → `fixture <name>`; first bad in fixed order reported; protocol case takes all seven | self:1615 `test_protocol_case_rejects_bad_fixture`; self:1655 `test_protocol_case_reports_earlier_bad_fixture`; self:1682 `test_stateful_case_rejects_bad_fixture_it_uses`; self:1692 `test_every_case_takes_only_the_seven_fixtures` |
| US1.4 Shared stateful client → second of two different stateful cases fails `not isolated` naming the sentinel | self:1521 `test_shared_client_second_case_not_isolated` (all 12 ordered pairs); self:1065 `test_require_fresh_twice_is_not_isolated` |
| US1.5 Missing fixture → collection error | self:2240 `test_subclass_missing_fixture_reports_fixture_error` (pytester: subclass without `source` → 4 fixture errors) |
| US1.6 `sentinel_path`, `without_sentinel` (entries and index incl. `CappedPrefix`), `sentinel_entry_bytes` | self:321 `test_sentinel_path_is_first_scope_own_entity`; self:338, 350, 357 `test_without_sentinel_*`; self:402, 413, 422, 435, 446 `test_sentinel_entry_bytes_*`; self:289 `test_constants_match_spec` |
| US2.0 Every non-fixture message is `name: label: phrase` | Enforced by every `_case_fails` match (self:1172, anchored `^{client}: {label}: `); self:309 `test_probe_path_unmapped_scope_fails`; self:851 `test_canonical_file_bad_field_fails` |
| US2.1 `expect_error`: return on match; `did not raise` (+ max_file_bytes hint); `wrong error type` (subclass, spoof); `wrong category`; `wrong payload` (missing, unreadable, StrEnum vs `str`, `str` subclass, value, 80-char reprs); `BaseException` propagates | self:460, 492, 506, 544, 557, 603, 626, 639, 655, 670, 686, 709 `test_expect_error_*` |
| US2.2 `harness misuse` category rule; exact `message` incl. unreadable; positional-only leading params | self:471, 487, 573, 591, 725, 736, 749 `test_expect_error_*` |
| US2.3 `canonical_file` deep exact types, order, `wrong result type` / `bad field`, version shape only | self:765, 786, 851, 856 `test_canonical_file_*` |
| US2.4 `canonical_entry` / `canonical_page` / `canonical_index` | self:865, 878, 901 `test_canonical_entry_*`; self:906, 919, 952, 957 `test_canonical_page_*`; self:966, 981, 1012 `test_canonical_index_*` |
| US2.5 `probe_path` builds the path; unmapped scope fails `probe scope` | self:299 `test_probe_path_builds_path_in_scope`; self:309 `test_probe_path_unmapped_scope_fails` |
| US2.6 Token `ast` rule passes on the module; flags listed violations; allows exemptions | pkg:440 `test_transport_conformance_never_operates_on_version_tokens`; pkg:459 `test_version_scan_flags_misuse`; pkg:464 `test_version_scan_reports_line_numbers`; pkg:480 `test_version_scan_allows_exemptions` |
| US2.7 `require_fresh`: writes sentinel as specified; fits `MIN_FILE_BYTES`; `not isolated`; `sentinel write failed`; wrong read error | self:1039, 1058, 1065, 1079, 1093, 1104 `test_require_fresh_*` |
| US2.8 `_call` → `unexpected error`; `without_sentinel` canonicalizes first | self:1020 `test_call_returns_result`; self:1025 `test_call_exception_is_unexpected_error`; self:380, 387, 395 `test_without_sentinel_*`; self:435 `test_sentinel_entry_bytes_listing_error_is_unexpected` |
| US3.1 `test_client_satisfies_protocol` | ref:48 (inherited); self:1615, 1627 `test_protocol_case_*` |
| US3.2 `test_write_then_read_round_trips` | ref:48 (inherited); self:1377 and following (US4.1–4.4) |
| US3.3 `test_returned_token_is_accepted` | ref:48 (inherited); self:1505 |
| US3.4 `test_read_absent_is_not_found` | ref:48 (inherited); self:1453 |
| US3.5 `test_oversize_write_is_rejected` | ref:48 (inherited); self:1465, 1485 |
| US4.1 `read_file(P)` returns a `dict` → `wrong result type` | self:1377 `test_round_trip_bad_read_fails[dict]`; self:1387 `test_round_trip_dict_read_names_dict`; self:1402 `test_round_trip_dict_reader_still_raises_for_absent` |
| US4.2 `list` aliases / naive `last_updated` / empty version → `bad field` | self:1377 `[aliases-list]`, `[last-updated-naive]`, `[version-empty]` |
| US4.3 Dropped alias / altered newline / different `last_updated` / wrong path → `round trip` | self:1377 `[drops-alias]`, `[strips-newline]`, `[doubles-newline]`, `[other-last-updated]`, `[wrong-path]` |
| US4.4 Both results strip `source` → `source not stamped` naming the write result | self:1412 `test_round_trip_source_not_stamped_fails` |
| US4.5 Absent read raises `KeyError` / spoof / plain-`str` reason / overridden category | self:1453 `test_read_absent_wrong_error_fails[key-error, class-spoof, plain-str-reason, category-override]` |
| US4.6 Oversize accepted / `NotFoundError` instead / wrong `size` | self:1465 `test_oversize_accepted_fails_did_not_raise`; self:1485 `test_oversize_wrong_error_fails[not-found, wrong-size]` |
| US4.7 Client forgets its own token → `token not accepted` | self:1505 `test_forgotten_token_fails_token_not_accepted[write, append]` |
| US4.8 Shared client → `not isolated`; sentinel write fails → `sentinel write failed`; `write_file(P)` `RuntimeError` → `unexpected error` | self:1521 `test_shared_client_second_case_not_isolated`; self:1535 `test_sentinel_write_failure_fails_every_stateful_case`; self:1546 `test_round_trip_write_runtime_error_is_unexpected` |
| US4.8a Protocol case with one bad fixture / two bad → earlier named | self:1615 `test_protocol_case_rejects_bad_fixture`; self:1627 `test_protocol_case_rejects_bad_client`; self:1655 `test_protocol_case_reports_earlier_bad_fixture` |
| US4.9 `expect_error` misuse and `wrong message` | self:725 `test_expect_error_category_misuse_fails`; self:573 `test_expect_error_wrong_message_fails` |
| US4.10 Each broken-client case passes for the reference client | `_reference_passes` (self:1166) called by every US4 test; self:1327 |
| US5.1 Both suites exported; `TransportConformance` not `Test`-prefixed | pkg:374 `test_transport_conformance_is_exported_and_not_collected` |
| US5.2 Allowed imports only; no marks; no Linear IDs; import guard unchanged | pkg:381, 406, 423 (import scan and its self-tests); pkg:428 `test_transport_conformance_applies_no_pytest_marks`; pkg:435 `test_transport_conformance_cites_no_linear_ids`; existing pkg:204, 237 unchanged |
| US5.3 `test_*` names are exactly the five | ref:101 `test_suite_public_methods_are_exactly_the_five_baseline_cases` |
| US5.4 Token rule scan | pkg:444, 459, 464, 480 (as US2.6); pkg:473 `test_version_scan_flags_method_calls_and_f_strings` |
| FR-003 (post-review) Malformed client values fail, never error: unreadable fields; raising `__class__`; flaky tzinfo; duplicate `scope_map` keys; duplicate index paths; `NoneType` named in not-isolated | self:1772 `test_canonical_file_unreadable_field_fails`; self:1804 `test_round_trip_unreadable_read_field_fails`; self:1824 `test_check_client_raising_class_fails_as_fixture_client`; self:1834 `test_raising_class_client_fails_every_case`; self:1863 `test_round_trip_flaky_offset_fails_not_raises`; self:1881 `test_round_trip_same_instant_other_offset_passes` (guard); self:1914, 1926 `test_*_duplicate_items_*`; self:1936 `test_without_sentinel_duplicate_index_paths_fails`; self:1958 `test_require_fresh_non_raising_read_names_returned_type` |
| Mutation survivors killed (coverage review) | self:1995 `test_oversize_write_that_stores_fails_on_follow_up_read`; self:2005 `test_oversize_limit_one_byte_high_fails_did_not_raise`; `[changes-description]` row; self:2043 `test_round_trip_strips_fixture_source_fails[conformance,s0]`; self:2074 `test_protocol_case_non_callable_method_fails[none,int]`; BAD_INDEXES `capped-prefix-int`, `capped-omitted-bool`, `capped-omitted-str`; self:2123 `test_token_case_dict_result_fails[rewrite,append]`; self:2135 `test_without_sentinel_capped_list_fails`; self:2142 `test_without_sentinel_keeps_lookalike_capped_prefix`; self:2162 `test_expect_error_unreadable_category_fails`; self:2181 `test_protocol_case_rejects_unreadable_scope_map`; self:2190 `test_without_sentinel_raising_iterable_is_unexpected` |

Line numbers before the FR-003 row are from the first draft and may have
shifted by the later additions; names are stable. `make check` is the
gate (2038 passed at the last run).

## Architecture / ADR changes

- New [ADR 0021](../../docs/adr/0021-transport-conformance-harness.md):
  decisions 1–10 (with 7a) and their rejected alternatives, the human's
  enforcement decision (option (a), 2026-10-02), and the six-round
  adversarial spec review.
- [ADR 0019](../../docs/adr/0019-transport-client-interface.md): update
  paragraph amending decision 6 so a remote server must not enforce scope
  at the transport; the tool layer is the only enforcement point.
- `ARCHITECTURE.md`: bird's-eye view now names both suites; the `testing`
  entry gains `TransportConformance` (fixtures, order, `MIN_FILE_BYTES`,
  baseline cases, helpers, message form, token and `last_updated` rules,
  deep exact-type readers, isolation sentinel, writable-scope and clock
  contracts, imports); the `transport` entry says the suite exists with
  baseline cases and exhaustive cases are planned; the diagram notes list
  the transport suite's dependencies; new key invariant "Conformance never
  compares tokens".
- `docs/product/glossary.md`: new "Transport conformance suite" and
  "Conformance sentinel"; "Conformance suite" points to the former.

## Deviations from spec

- One deviation from Notion, **decided by the human on 2026-10-02 as
  option (a)**: §10.2's enforcement bullets ("`system/` prefix writes
  rejected; write-restricted scopes rejected for callers lacking the
  role") conflict with an identity-agnostic transport whose in-process
  client accepts such writes. The transport suite asserts a `system/`
  write is accepted at the transport; `system/` read-only and role
  restriction are enforced only in the tool layer and tested by the
  tool-layer and resolver suites; a remote server must not enforce scope
  at the transport. Recorded in ADR 0021; ADR 0019 decision 6 is amended
  by an update paragraph. AIE-1045 adds
  `test_system_area_write_is_accepted_at_transport`. The harness needed
  no code change.
- Token opacity is read strictly: "never compares" includes equality, so
  the suite cannot check `write.version == read.version`. Tokens are
  checked only by shape and by handing them back.
- Small plan-vs-code differences: the module does not import
  `version_token` (plan listed it as allowed; the import scan permits but
  does not require it), and the protocol case also fails if reading a
  method attribute raises. Neither changes behavior the spec describes.

## Adversarial review findings

Six rounds of adversarial spec review ran before implementation. Each
finding below changed the spec:

1. **Isolation probe that couldn't fire.** A single isolation case gets its
   own fixture call, so it never sees sharing. Now `require_fresh` runs at
   the start of every stateful case.
2. **Token `==`.** The round trip compared write and read tokens,
   contradicting §10.2. Removed; tokens are handed back instead, and an
   `ast` scan pins the rule.
3. **`last_updated` dropped.** An earlier fix for clock comparison dropped
   the field, leaving "all four metadata fields" at three. Restored as a
   comparison between two server-stamped results.
4. **Weak `expect_error`.** `isinstance` and `!=` let subclasses, spoofed
   `__class__`, and plain-`str` reasons pass. Now exact type, a category
   rule, optional exact message, and exact-typed payload.
5. **Hard-coded `source`.** Now the `source` fixture, with the seed source
   chosen to differ from it.
6. **Shallow readers.** Top-level type checks let `list` aliases or naive
   datetimes through. Now deep exact-type canonical readers (the parity
   case ADR 0019 deferred).
7. **ADR collision.** AIE-1044 had reserved 0021; this issue takes 0021
   and AIE-1044 moves to 0022.
8. **Writability contract.** A sentinel under an unmapped entity could be
   rejected by a scope-enforcing server. Moved under the first mapped
   scope's own entity, with the fixture contract that every mapped scope
   is writable.
9. **Path-scoped broken clients.** Self-test clients that misbehaved for
   every path broke the sentinel write first, so the case under test never
   fired. Now they misbehave only for the probe paths `P` and `Q`.
10. **Label in messages.** Messages didn't say which call fired, so a
    self-test could not tell `require_fresh` from the case. Now every
    message is `name: label: phrase` and self-tests match the probe path.

After implementation, an adversarial **code review** found that malformed
client values (a `MemoryFile` built via `object.__new__` missing fields, a
client whose `__class__` property raises, a tzinfo that raises on its
second call, a `scope_map` whose `items()` repeats a key, an index with
duplicate paths) made a case ERROR with a raw exception instead of FAIL,
against FR-003. All were fixed: guarded field reads, a method walk and
guarded `isinstance` in `check_client`, UTC normalization inside the
`last_updated` guard, duplicate-key rejection, and `_call` around the
index rebuild. A **coverage review** ran 40 mutants: all 17 requested were
killed; 14 real survivors (oversize follow-up read, limit+1, description
field, seed logic, callable check, `CappedPrefix` field types, token-case
result canonicalization, capped-list guard, lookalike capped prefix, and
three unreadable-value guards) were killed by added tests; 3 were
equivalent.

## Look closely at

- **Token rule scope.** The `ast` scan (pkg:352 `find_version_misuse`)
  exempts any call on the name `client` and `type()`. A case that binds
  the client to another name, or extracts a token into a variable not
  ending in `version`, escapes the scan; the convention that every case
  parameter is named `client` is load-bearing.
- **Fixture contract that isn't checked.** Writability of every mapped
  scope and strictly increasing `last_updated` are stated in the module
  docstring but not validated; a violating adopter sees a `sentinel write
  failed` or (later) an ordering failure rather than a `fixture` error.
- **Exact-type binding for remote clients.** Deep exact-type readers fail
  a remote client returning `list` aliases or a `str` subclass even when
  values are equal. Intended by §10.2, but a real cost for remote
  decoders.
- **`without_sentinel` on an index** removes any `CappedPrefix` ending in
  `/conformance-sentinel/`, across every scope, not just the first. Only
  the first scope ever holds a sentinel, so this is equivalent today.
- **`expect_error` reads `category` only when one is expected**, so a
  non-taxonomy error's attributes are never touched beyond the payload.

## Follow-ups

- **AIE-1045**: the exhaustive §10.2 cases on this mixin (index fan-out,
  ordering, cap and `capped`; concurrency as sequential interleavings;
  full error parity incl. non-taxonomy errors; pagination), using
  `without_sentinel` / `sentinel_entry_bytes`, checking
  `VersionConflictError.version` only by handing it back, and
  `test_system_area_write_is_accepted_at_transport` (option (a)).
- **AIE-1044** (tool layer) records its decisions as ADR 0022.
- `specs/AIE-1047-transport-harness/review-spec.md` still says the sentinel
  lives under "an unmapped entity" in its summary; the decision table and
  the spec say the caller's own entity. Stale wording only.
