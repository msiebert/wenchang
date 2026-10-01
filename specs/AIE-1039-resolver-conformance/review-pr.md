# PR Review: AIE-1039 — Resolver conformance suite

## What changed & why

Notion Section 10 says the library ships an executable conformance suite
for the resolver, and that passing it defines a correct resolver. This PR
adds the installed subpackage `wenchang.testing`, which exports
`ResolverConformance[C]`. It is a pytest mixin of twelve test methods. An
adopter subclasses it and supplies six fixtures: `resolver`,
`valid_credentials`, `invalid_credentials`, `policy`, `expected_scopes`,
and `known_roles`. The twelve methods cover every Section 10.1 clause, plus
the issue's path construction, `system/` read-only, and write-restriction
clauses. pytest becomes the optional extra `wenchang[testing]`. No existing
module changes.

Files: `pyproject.toml` (the `testing` extra), `uv.lock`,
`src/wenchang/testing/__init__.py`,
`src/wenchang/testing/resolver_conformance.py`, and three new test files.

## Acceptance criteria → tests

`ref` = `tests/test_resolver_conformance_reference.py`, `self` =
`tests/test_resolver_conformance_self.py`, `pkg` =
`tests/test_testing_package.py`. "All three reference classes" means
`TestSandboxResolverPermittedRole`, `TestSandboxResolverLackingRole`, and
`TestTokenResolver` in `ref`. Each runs the inherited suite method named.

| Acceptance criterion | Test(s) |
| -------------------- | ------- |
| US1.1 valid credentials → `Identity` granting `expected_scopes`, equal through `resolve_identity` | all three reference classes `::test_valid_credentials_resolve_to_identity` and `::test_valid_credentials_resolve_through_library_entry_point`; `self::test_conforming_resolver_passes_valid_credential_methods` |
| US1.2 raises on valid → `must not raise`, `RuntimeError` as `__context__` | `self::test_raising_on_valid_fails_with_context` |
| US1.3 `ResolutionFailure` on valid → `rejected valid credentials` with detail | `self::test_rejecting_valid_fails_with_detail` |
| US1.4 `None` → `expected Identity or ResolutionFailure` | `self::test_wrong_return_type_on_valid_fails_naming_type` |
| US1.5 no grants → `granted no scopes`, even for empty `expected_scopes` | `self::test_empty_identity_fails` (parametrized) |
| US1.6 scope mismatch → `granted scopes`, both sorted | `self::test_scope_mismatch_fails_listing_both_sets_sorted` |
| US1.7 patched `resolve_identity` returns another `Identity` | `self::test_entry_point_returning_different_identity_fails` |
| US1.8 patched `resolve_identity` raises for valid | `self::test_entry_point_raising_for_valid_fails` |
| US1.9 / FR-007 bad `expected_scopes` fixture | `self::test_expected_scopes_not_a_frozenset_fails`, `self::test_expected_scopes_with_non_str_members_fails` |
| US2.1 invalid → `ResolutionFailure` passes | `TestTokenResolver::test_invalid_credentials_return_resolution_failure`; `self::test_conforming_resolver_passes_invalid_credential_methods` |
| US2.2 raises on invalid → `must not raise`, names type, keeps context | `self::test_raising_on_invalid_fails_naming_exception` (parametrized over four exception types) |
| US2.3 `Identity` for invalid → `accepted invalid credentials` | `self::test_accepting_invalid_fails` |
| US2.4 `None` for invalid | `self::test_none_for_invalid_fails` |
| US2.5 permanent `ResolverFailureError`; acceptance checked before "DID NOT RAISE" | `TestTokenResolver::test_invalid_credentials_raise_permanent_resolver_failure_error`; `self::test_accepting_invalid_fails_permanent_error_method_first` |
| US2.6 `pytest.skip` in `invalid_credentials` skips exactly three | the two `TestSandboxResolver*` classes (three methods reported skipped); `ref::test_exactly_three_suite_methods_take_invalid_credentials` |
| US2.7 patched TRANSIENT error → `not permanent` | `self::test_transient_resolver_failure_fails` |
| US2.8 patched `resolve_identity` returns → `did not raise ResolverFailureError` | `self::test_entry_point_not_raising_for_invalid_fails` |
| US3.1 / US3.3 consistent results pass | all three reference classes `::test_valid_resolution_is_consistent`; `TestTokenResolver::test_invalid_resolution_is_consistent`; `self::test_conforming_resolver_passes_consistency_methods` |
| US3.2 differing call 2 or 3 → `different results` naming call | `self::test_inconsistent_valid_resolution_fails_naming_call` (parametrized) |
| US3.4 invalid accepted on call 2 | `self::test_invalid_accepted_on_second_call_fails` |
| US3.5 valid raising on call 2 | `self::test_valid_raising_on_second_call_fails` |
| US4.1 roles known | all three reference classes `::test_roles_are_known_to_scope_configuration`; `self::test_conforming_resolver_passes_roles_method` |
| US4.2 `"Admin"` vs `"admin"` → `not in known_roles` | `self::test_wrong_case_role_fails_naming_scope_and_role` |
| US4.3 `str` `known_roles` → `fixture known_roles` | `self::test_known_roles_as_str_fails` |
| US4.4 policy role unknown → `policy role` | `self::test_policy_role_unknown_fails_naming_scope_and_role` |
| US5.1 paths valid and round-trip | all three reference classes `::test_granted_scopes_build_valid_paths`; `self::test_conforming_resolver_passes_paths_method` |
| US5.2–5.5 patched path functions | `self::test_malformed_build_path_fails`, `::test_non_round_tripping_parse_fails`, `::test_invalid_prefix_fails`, `::test_prefix_for_other_scope_fails` |
| US6.1 `system/` read-only, own, foreign, and ungranted | all three reference classes `::test_system_area_is_read_only_in_every_scope`; `self::test_conforming_resolvers_pass_enforcement_methods` |
| US6.2 no-op / always-`NOT_GRANTED` | `self::test_system_area_fails_when_check_write_is_broken` |
| US7.1–7.2 own entity follows policy (admin → `None`, member → `ROLE_REQUIRED`) | `TestSandboxResolverPermittedRole` and `TestSandboxResolverLackingRole` `::test_own_entity_writes_follow_policy`; `self::test_conforming_resolvers_pass_enforcement_methods` (both identities) |
| US7.3 foreign entity → `NOT_GRANTED` | all three reference classes `::test_foreign_entity_writes_are_not_granted` |
| US7.4 ungranted scope (incl. restricted `team`) → `NOT_GRANTED` | all three reference classes `::test_ungranted_scope_writes_are_not_granted` |
| US7.5 patched `check_write` matrix (failing cells) | `self::test_write_restriction_matrix` (16 parametrized cells) |
| US7.6 wrong `required_roles` | `self::test_wrong_required_roles_fails` |
| US7.7 non-`RestrictedScopeError` names its type | `self::test_non_restriction_exception_names_its_type`; the `always_not_found` rows of the matrix |
| US8.1–8.2 Sandbox passes, three skipped | `TestSandboxResolverPermittedRole`, `TestSandboxResolverLackingRole` |
| US8.3 token resolver passes, none skipped | `TestTokenResolver`; `ref::test_token_resolver_accepts_only_the_known_token` |
| US9.1 importable, not collected | `pkg::test_resolver_conformance_is_importable_and_not_collected` |
| US9.2 / FR-005 `testing` extra | `pkg::test_pyproject_declares_testing_extra` |
| US9.3 / FR-005 no pytest or `wenchang.testing` import outside the package | `pkg::test_library_does_not_import_pytest_or_testing_package`, plus scanner checks `::test_import_scan_detects_forbidden_form` and `::test_import_scan_allows_other_imports` |
| US9.4 exactly twelve methods | `pkg::test_resolver_conformance_defines_exactly_the_planned_tests` |
| US9.5 / FR-006 no Linear IDs in shipped module | `pkg::test_testing_package_cites_no_linear_ids` |
| US9.6 library imports with pytest blocked | `pkg::test_library_imports_without_pytest` |
| US9.7 / FR-008 no pytest marks | `pkg::test_conformance_module_applies_no_pytest_marks`, plus scanner checks `::test_mark_scan_detects_marks` and `::test_mark_scan_allows_fixtures_and_fail` |
| US3.3 invalid-credential `detail` may differ between calls | `self::test_changing_failure_detail_is_consistent` |
| Review finding 1: a lying `__eq__` or overridden `role()` cannot pass (canonicalization) | `self::test_lying_eq_does_not_hide_inconsistency` (parametrized), `self::test_overridden_role_does_not_hide_unknown_stored_role` |
| Review finding 2: an `Identity` holding a non-`ScopeGrant` fails as `invalid Identity`, not `AttributeError` | `self::test_unvalidated_identity_fails_as_invalid` (parametrized over methods) |
| Review finding 3: a spoofed `__class__` fails as the wrong type | `self::test_spoofed_class_failure_is_wrong_type` |
| Review finding 4: right reason in the wrong scope fails; probes hit `team`, an ungranted scope, a foreign entity; the ungranted name avoids a granted scope | `self::test_right_reason_in_wrong_scope_fails` (parametrized), `::test_ungranted_method_probes_policy_restricted_scope`, `::test_system_method_probes_ungranted_and_foreign_entities`, `::test_ungranted_name_avoids_granted_scope` |
| Review finding 5: an unreadable class `__name__` does not escape and is reported as `<unnamed>` | `self::test_unreadable_class_name_does_not_escape`, `::test_unreadable_class_name_reported_as_unnamed` |
| FR-001 methods take only the six fixtures | `ref::test_suite_methods_take_only_contract_fixtures` |
| FR-002 contract checks call `resolver.resolve` directly | `self::test_raising_on_valid_fails_with_context` and `::test_raising_on_invalid_fails_naming_exception` (a masked raise would surface as `ResolverFailureError`, not `must not raise`) |
| FR-003 `pytest.fail` naming resolver and key phrase | the `_fails` helper in `self` asserts both for every failure test |
| FR-004 every clause covered | clause table in plan.md; the US1–US7 rows above |
| SC-001 references pass, every broken double fails | the `ref` reference classes plus every `self` failure test |

## Architecture / ADR changes

- New [ADR 0018](../../docs/adr/0018-resolver-conformance-suite.md). It
  records ten decisions from plan.md with their rejected alternatives,
  including decision 10, adversarial hardening.
  Three were human decisions approved at spec review on 2026-09-30: the
  required `known_roles` fixture, keeping the caught exception attached as
  context (contrasting ADR 0014's `from None`), and the required
  `expected_scopes` fixture.
- `ARCHITECTURE.md`:
  - The bird's-eye view mentions `testing`.
  - New **testing** module-map entry covering the fixtures and types, the
    twelve methods grouped by clause, failure reporting, the skip
    convention, dependencies, and the extra.
  - The diagram is unchanged. The prose says `testing` is outside the
    runtime layers.
  - New key invariant: pytest stays optional.
- `docs/product/glossary.md`: added **Conformance suite**, **Known
  roles**, and **Expected scopes**.
- `README.md`: unchanged. Its only install section is the contributor
  Quickstart (`make install` / `make check`), with no adopter install or
  usage section to extend. The module docstring and ARCHITECTURE.md show
  usage.

## Deviations from spec

- None from Notion.
- The US7.6 self-test (`test_wrong_required_roles_fails`) found that the
  `test_own_entity_writes_follow_policy` failure message left out its own
  key phrase. It read `... required ['x'], expected ['admin', 'owner']`.
  The message now reads `{name}: wrong required_roles for write to {path}:
  got [...], expected [...]`, and plan.md's template was corrected to
  match.
- An allowed skip, per the spec's Allow-test-changes line: the two
  `SandboxResolver` reference classes' `invalid_credentials` fixture calls
  `pytest.skip`. This skips exactly the three invalid-credential methods.
  `TestTokenResolver` runs them unskipped. The tests have no other `skip`
  or `xfail`.
- The adversarial hardening (ADR 0018 decision 10) came after spec review,
  from code-review findings 1–5. It adds the `invalid Identity` key phrase
  and the hostile-resolver self-tests. It changes no fixture, method name,
  or other key phrase, and it does not deviate from Notion: it makes the
  suite check what the library actually reads.

## Look closely at

- **The canonicalization step** (`_canonical` in `resolver_conformance.py`).
  `_resolve_valid` and the entry-point test rebuild every `Identity` as a
  base `Identity` of base `ScopeGrant`s from the stored `entity_id` and
  `role`. Check that no later comparison or read uses the resolver's
  original object, and that type tests use `issubclass(type(x), ...)`
  rather than `isinstance`.
- **The US7.5 matrix** (`MATRIX` in `self`). It omits the "passes" cells by
  design. Those cells are no-op/own/admin, always-`NOT_GRANTED` on
  foreign and ungranted, and always-`SYSTEM_READ_ONLY` on system. Check
  that each omitted cell really passes, and that the no-op/own/admin cell
  is why the member identity carries the own-entity proof. The system,
  foreign, and ungranted columns use only the admin identity because their
  outcome does not depend on role.
- **The packaging tests**, especially
  `test_library_imports_without_pytest`. Its subprocess sets
  `sys.modules["pytest"]` and `sys.modules["_pytest"]` to `None`, confirms
  the block works, and walks `pkgutil.walk_packages`. It asserts that
  `wenchang.core` was imported and `wenchang.testing` was skipped, so an
  empty walk cannot pass by accident. Check that the `ast` import scan
  covers every relative form.
- **The shipped module has no Linear IDs or marks.** The test docstrings
  under `tests/` cite AIE-1039, but `src/wenchang/testing/` must not, and
  `resolver_conformance.py` must have no `pytestmark` or `pytest.mark`.
- **Exception context.** In `_resolve_valid` and `_resolve_invalid`,
  `pytest.fail` runs inside the `except` block on purpose (ADR 0018
  decision 3). A later "cleanup" to `from None` breaks the `__context__`
  assertions in US1.2 and US2.2.

## Follow-ups

- The transport conformance suites (AIE-1045, AIE-1047) should reuse this
  shape: a mixin under `wenchang.testing`, required fixtures,
  `pytest.fail` with key phrases, and self-tests that patch module-level
  names.
- No real adopter has run the suite yet. The first production resolver
  will be its first real run.
