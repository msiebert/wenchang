# PR Review: AIE-1322 — Conformance case for the file-count cap

## What changed & why

`FileQuotaExceededError` is part of the transport error-parity contract, but
the conformance suite never exercised it, so a remote transport that dropped
or reshaped it passed. `TransportConformance` gains an optional eighth
fixture, `max_files_per_entity` (default `None`, so existing adopter
subclasses are unaffected), and a case,
`test_create_at_file_cap_is_quota_exceeded`, that fills an entity to the cap
and asserts the next create raises core's exact error and stores nothing.
With the fixture `None` the case skips.

## Acceptance criteria → tests

All tests are in `tests/test_transport_conformance_self.py` unless noted.

| Acceptance criterion (Given/When/Then) | Test(s) |
| --------------------------------------- | ------- |
| US1.1 Conforming client over a capped store passes; fills to the cap, then the (N+1)th create raises | `test_file_cap_case_passes_for_conforming_clients`, `test_file_cap_case_passes_for_other_cap`, `test_file_cap_case_fills_second_scope_notes_then_overflows` |
| US1.2 Nothing is stored by the rejected create | `test_file_cap_case_passes_for_conforming_clients`, `test_file_cap_write_that_stores_fails_on_follow_up_read` |
| US1.3 Wrong error type fails | `test_file_cap_wrong_error_type_fails` |
| US1.4 Wrong `limit` or `path` fails | `test_file_cap_wrong_payload_fails` |
| US1.5 Wrong `str()` fails | `test_file_cap_wrong_message_fails` |
| US1.6 Wrong category fails | `test_file_cap_wrong_category_fails` |
| US1.7 Cap never enforced fails "did not raise" with fixture hint | `test_file_cap_not_enforced_fails_did_not_raise_with_hint`, `test_expect_error_quota_did_not_raise_hints_fixture`, `test_expect_error_other_types_get_no_quota_hint` |
| US1.8 Quota error before N files exist (fixture above real cap) fails with hint; other fill errors no hint; `BaseException` propagates | `test_file_cap_fixture_above_real_cap_fails_with_hint`, `test_file_cap_other_fill_error_has_no_hint`, `test_file_cap_fill_base_exception_propagates` |
| US1.9 Over-cap file stored then correct error raised fails | `test_file_cap_write_that_stores_fails_on_follow_up_read` |
| US2.1 Subclass without the fixture skips the case, writes nothing, collects fine | `test_file_cap_case_skips_without_fixture_and_writes_nothing`, `test_subclass_without_fixture_collects_and_skips_only_file_cap` |
| US2.2 Protocol case passes with no fixture | `test_protocol_case_passes_with_no_file_cap_fixture` |
| US2.3 Default is `None`, overridable, not a public suite method | `test_default_fixture_is_not_a_public_suite_method`, `test_subclass_fixture_overrides_default_and_runs_the_case` |
| US3.1, US3.2 `None` and ints at least 32 validate; `MIN_FILES_PER_ENTITY` is 32 | `test_check_files_per_entity_accepts`, `test_min_files_per_entity_is_32` |
| US3.3 `bool`, non-int, or below-minimum fails `fixture max_files_per_entity` in both cases | `test_check_files_per_entity_rejects`, `test_file_cap_case_rejects_bad_fixture_it_uses`, `test_file_cap_case_rejects_bad_client` |
| US3.4 Validated after `list_page_size`; protocol case takes eight fixtures | `test_file_cap_fixture_validated_after_list_page_size`, `test_every_case_takes_only_the_eight_fixtures` |
| US3.5 Cap below `list_page_size + 2` fails with the stated message; at the floor passes | `test_protocol_case_rejects_cap_below_page_floor`, `test_protocol_case_accepts_cap_at_page_floor` |
| US4.1 Reference and cached subclasses run the case unskipped | `tests/test_transport_conformance_reference.py::TestInProcessClient`, `tests/test_transport_conformance_cached.py` (capped store, fixture override), `tests/test_transport_conformance_cases_self.py::test_reference_client_passes_error_parity_case` |
| US4.2 Listed-cases check includes the new case | `tests/test_transport_conformance_reference.py::test_suite_public_methods_are_exactly_the_listed_cases` |

## Architecture / ADR changes

- New [ADR 0045](../../docs/adr/0045-conformance-file-cap-case.md): optional
  fixture with `None` default and skip.
- Supersedes in part ADR 0039 decision 8 and its "not caught by the
  conformance suite" consequence; amends ADR 0021 decision 7a and ADR 0023's
  "seven fixtures". One-line notes added to each.
- `ARCHITECTURE.md` testing entry: seven required plus one optional fixture,
  validation order, the `max(32, list_page_size + 2)` floor, 44 case methods,
  and the new case.
- `site-src/reference.md` conformance bullet now mentions the optional
  fixture; `site/` regenerated (`site/reference.md`, `site/reference.html`,
  `site/llms-full.txt`).

## Deviations from spec

None.

## Look closely at

- The `@pytest.fixture(name="max_files_per_entity")` default on an
  underscore-named method: confirm a subclass override wins and the default is
  not collected or public.
- The fill loop's handling of a quota error before the cap is reached: the
  hint should blame the fixture, not the client.
- The floor check lives in `test_client_satisfies_protocol`, not the new case,
  which does not take `list_page_size`.
- Fixture order: `max_files_per_entity` validates last, so existing failures
  report as before.

## Review

Adversarial spec review (2 rounds) caught the public-methods listing break,
the `list_page_size`-dependent floor, and required self-test edits. Post-build
correctness review found no bugs (2 NITs fixed). Spec-fidelity review PASS,
with review-pr.md accuracy fixes and NITs fixed.

## Follow-ups

None.
