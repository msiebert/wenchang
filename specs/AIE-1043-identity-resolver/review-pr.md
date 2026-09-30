# PR Review: AIE-1043 — identity resolver interface

## What changed & why

The library has no notion of users or roles (Notion Section 6). It asks an
adopter-injected resolver who the caller is. New `src/wenchang/identity.py`
adds the value types (`ScopeGrant`, `Identity`, `ResolutionFailure`), the
generic runtime-checkable `IdentityResolver[C]` protocol, `resolve_identity`
(the library's one call into a resolver, turning every failure into a
permanent `ResolverFailureError` raised `from None`), and `SandboxResolver`.
`paths.is_valid_segment` becomes public and rejects `/`, so identity values
use the same segment rule as paths. Nothing calls `identity` yet.

An adversarial code review then hardened the module against hostile
resolver output: `Identity` validates and stores a single snapshot of the
caller's mapping, every `str` value is normalized to an exact `str`,
grant values are type-tested with `issubclass(type(grant), ScopeGrant)`,
keys colliding after normalization raise `ValueError`,
`ResolutionFailure` rejects a non-`str` detail, `resolve_identity`
type-tests with `issubclass(type(result), ...)`, guards failure-message
construction, and reads type names through a `_type_name` helper with an
`<unnamed>` fallback, and `__reduce__` preserves subclasses. Each finding has a
regression test (ADR 0014, decision 9).

## Acceptance criteria → tests

Tests are in `tests/test_identity.py` unless marked `test_paths.py`.

| Acceptance criterion (Given/When/Then) | Test(s) |
| --------------------------------------- | ------- |
| US1.1 grants → `scope_map`, `role`, `entity_id` | `test_identity_exposes_scope_map_role_and_entity_id` |
| US1.2 mutating the source dict leaves `Identity` unchanged | `test_identity_copies_grants_on_construction` |
| US1.3 mutating `scope_map` result is harmless; `grants[...] =` raises `TypeError` | `test_mutating_scope_map_result_leaves_identity_unchanged`, `test_grants_item_assignment_raises_type_error`, `test_identity_fields_are_frozen`, `test_scope_grant_fields_are_frozen` |
| US1.4 equal grants in any order are equal and hash equal; differences unequal | `test_equal_grants_in_any_order_are_equal_and_hash_equal`, `test_different_grants_compare_unequal`, `test_scope_grants_equal_and_hash_by_value` |
| US1.5 empty grants are valid, `scope_map == {}` | `test_empty_grants_build_identity_with_empty_scope_map` |
| US1.6 `role` / `entity_id` for an ungranted scope raise `KeyError` | `test_role_for_ungranted_scope_raises_key_error`, `test_entity_id_for_ungranted_scope_raises_key_error`, `test_lookups_on_empty_identity_raise_key_error` |
| US1.7 `pickle` and `copy.deepcopy` round-trip | `test_identity_round_trips_through_pickle`, `test_identity_round_trips_through_deepcopy`, `test_round_tripped_identity_grants_stay_read_only` |
| US2.1 rejected-segment `entity_id` raises `ValueError` | `test_scope_grant_rejects_invalid_entity_id`, `test_scope_grant_accepts_valid_values` |
| US2.2 empty `role` raises `ValueError` | `test_scope_grant_rejects_empty_role` |
| US2.3 rejected-segment scope name raises `ValueError` | `test_identity_rejects_invalid_scope_name`, `test_identity_rejects_invalid_scope_name_among_valid_ones` |
| US2.4 empty `detail` raises `ValueError` | `test_resolution_failure_rejects_empty_detail`, `test_resolution_failure_keeps_detail` |
| US2.5 `is_valid_segment` rejects / accepts the listed values, never raises | `test_paths.py`: `test_invalid_segments_rejected`, `test_valid_segments_accepted`, `test_is_valid_segment_never_raises_on_arbitrary_input` |
| US2.6 `"a/b"` is rejected | `test_paths.py`: `test_segment_containing_slash_rejected` |
| US2.7 non-`str` `entity_id` / `role` raise `TypeError` | `test_scope_grant_rejects_non_str_entity_id`, `test_scope_grant_rejects_non_str_role`, `test_scope_grant_type_check_precedes_value_check` |
| US2.8 non-`str` grants key raises `TypeError` | `test_identity_rejects_non_str_scope_key` |
| US2.9 non-`ScopeGrant` value raises `TypeError` | `test_identity_rejects_non_scope_grant_value` |
| US3.1 returned `Identity` is the same object; credentials passed unchanged | `test_resolve_identity_returns_the_resolvers_identity_object`, `test_resolve_identity_passes_credentials_unchanged` |
| US3.2 `ResolutionFailure("token expired")` → permanent `ResolverFailureError` | `test_resolution_failure_becomes_permanent_resolver_failure_error` |
| US3.3 raising resolver → error naming class and type, no secret, `from None` | `test_raising_resolver_becomes_resolver_failure_error_without_secret`, `test_raising_resolver_error_is_not_chained` |
| US3.4 wrongly typed return (e.g. `None`) → error naming class and returned type | `test_none_returning_resolver_becomes_resolver_failure_error`, `test_wrongly_typed_return_becomes_resolver_failure_error` |
| US3.5 non-`Exception` `BaseException` propagates unchanged | `test_keyboard_interrupt_propagates_unchanged`, `test_system_exit_propagates_unchanged` |
| US3.6 raised `WenchangError` is replaced, its detail not reused | `test_raised_resolver_failure_error_is_replaced_not_passed_through`, `test_raised_wenchang_error_is_converted_without_its_detail` |
| US4.1 `SandboxResolver` returns its identity for any credentials | `test_sandbox_resolver_returns_configured_identity_for_any_credentials`, `test_sandbox_resolver_returns_same_identity_every_time` |
| US4.2 `SandboxResolver` is an `IdentityResolver`; an object without `resolve` is not | `test_sandbox_resolver_is_an_identity_resolver`, `test_object_without_resolve_is_not_an_identity_resolver`, `test_sandbox_resolver_satisfies_protocol_for_any_credential_type` |
| US4.3 `resolve_identity` with a `SandboxResolver` returns its identity | `test_resolve_identity_with_sandbox_resolver_returns_configured_identity` |
| FR-007 `is_valid_path` / `is_valid_prefix` unchanged | existing `test_paths.py` tests, unmodified |
| **Review hardening** | |
| US2.11 a `Mapping` whose views disagree is validated on one snapshot | `test_identity_validates_dict_content_not_items_view`, `test_identity_validates_mapping_lookup_not_items_view` |
| US2.10 / FR-008 `str` subclasses are checked by real value and stored as exact `str` | `test_identity_rejects_evil_str_scope_name`, `test_scope_grant_rejects_evil_str_entity_id`, `test_identity_accepts_plain_str_subclass_key_and_stores_exact_str` |
| US3.4 raising `__class__` or `detail.__format__` still yields `ResolverFailureError` | `test_return_with_raising_class_lookup_becomes_resolver_failure_error`, `test_failure_detail_with_raising_format_becomes_resolver_failure_error` |
| US2.4 / FR-003 non-`str` `detail` raises `TypeError` | `test_resolution_failure_rejects_non_str_detail` (parametrized: none, int, bytes) |
| US2.9 a value spoofing `__class__` as `ScopeGrant` raises `TypeError` | `test_identity_rejects_value_spoofing_scope_grant_class` |
| US2.12 keys colliding after normalization raise `ValueError` | `test_identity_rejects_keys_colliding_after_normalization` |
| US3.4 a raising type `__name__` still yields `ResolverFailureError`, reported as `<unnamed>` | `test_resolver_with_raising_type_name_becomes_resolver_failure_error`, `test_return_with_raising_type_name_reports_unnamed` |
| US1.7 `Identity` subclass survives `pickle` / `deepcopy` | `test_identity_subclass_round_trips_through_pickle`, `test_identity_subclass_round_trips_through_deepcopy` |

## Architecture / ADR changes

- New [ADR 0014](../../docs/adr/0014-identity-resolver.md) recording the
  nine plan decisions (one grant per scope, returned failure, defensive
  catch `from None`, segment validation with runtime type checks, generic
  contravariant protocol, shipped `SandboxResolver`, separate `identity`
  and `scope` modules, `MappingProxyType` + `__reduce__`, adversarial
  hardening), with the three human decisions marked approved at spec
  review.
- `ARCHITECTURE.md`: bird's-eye view now counts seven modules; the
  **paths** entry documents public `is_valid_segment`; the planned
  "scope / identity" entry is split into an implemented **identity** entry
  and a planned **scope** entry; the diagram adds `identity` beside `core`
  with no arrow; new key invariant on identity validation, credentials, and
  unchained permanent failure.
- `docs/product/glossary.md`: new entries for identity resolver, identity,
  scope grant, resolution failure, and sandbox resolver; role updated.

## Deviations from spec

- None from the Notion spec. The defensive catch of a raising or
  wrongly-returning resolver goes beyond Section 10.1 and is recorded in
  ADR 0014, decision 3.
- Against plan.md: the plan said `result: object = resolver.resolve(...)`
  widens the result for pyright. It does not (pyright narrows on
  assignment), so the code uses `result = cast(object, ...)`. plan.md is
  corrected.

## Look closely at

- **Contravariance inference.** `IdentityResolver[C]` uses PEP 695 syntax,
  so `C`'s variance is inferred. It comes out contravariant only because `C`
  appears solely in the `resolve` parameter.
  `test_sandbox_resolver_satisfies_protocol_for_any_credential_type` is the
  static check: it assigns `SandboxResolver` to `IdentityResolver[str]` and
  `IdentityResolver[dict[str, int]]`. A future use of `C` in a return type
  would silently change the variance.
- **`from None` and `__context__`.** `raise ... from None` sets
  `__cause__ = None` and `__suppress_context__ = True`, so tracebacks omit
  the original exception. `__context__` still references it, so a logger
  that walks `__context__` explicitly could still reach the secret-bearing
  message. The tests deliberately do not assert `__context__ is None`.
- **The `/` rule has no effect on `is_valid_path` / `is_valid_prefix`.**
  Both split on `/` before calling `is_valid_segment`, so no segment they
  pass can contain one. The new check matters only for unsplit identity
  values. The existing path tests pass unmodified.
- **The single-snapshot rule.** `Identity.__post_init__` calls
  `dict(grants)` once and never reads the caller's mapping again; all
  validation runs on that snapshot and the same snapshot is stored. Any
  future edit that re-reads `self.grants` before the `object.__setattr__`
  reopens the view-disagreement bypass.
- **Guarded failure-message construction.** In `resolve_identity`, the
  `ResolverFailureError` for a returned `ResolutionFailure` is built inside
  `try`/`except Exception` with a fallback message, so a hostile `detail`
  or `__format__` cannot escape. Every type name in `resolve_identity`
  (the resolver's class, a raised exception's type, a wrongly typed
  return's type) goes through `_type_name` (`<unnamed>` fallback). Check
  that the fallback cannot itself raise and that nothing
  resolver-controlled is formatted outside a guard.

## Follow-ups

- AIE-1041 (path construction) depends on public `is_valid_segment` and
  builds paths from `Identity`.
- AIE-1040 / AIE-1042 (`system/` read-only, role-gated writes) will consume
  `Identity` in the planned `scope` module.
- AIE-1039 (resolver conformance suite) will use `SandboxResolver` as its
  known-good reference.
- Wiring `resolve_identity` into transport and tools, out of scope here.
- The raised-exception branch's `_type_name(type(exc))` (an exception
  class whose metaclass makes `__name__` raise) has no dedicated test.
- Candidate follow-up issue on the shared segment rule
  (`paths.is_valid_segment`), which currently accepts inputs that are
  risky downstream: lone surrogates (valid `str`, but fail UTF-8 encoding
  at the storage layer); bidi-control and zero-width characters (not `Cc`,
  so visually spoofable names pass); very long values that push an object
  name past GCS's 1024-byte limit; and NFC vs NFD forms of the same text,
  which are treated as distinct segments.
