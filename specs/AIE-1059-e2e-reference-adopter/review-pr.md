# PR Review: AIE-1059 — End-to-end test over the Section 9 reference adopter

## What changed & why

Nothing exercised the whole stack the way an adopter would use it. This adds
one reference adopter fixture, `tests/reference_adopter.py`, that folds in the
old `tests/prompts_reference_adopter.py` (slot constants moved verbatim;
docstring and imports rewritten; git does not record a rename) and adds the write policy, identities, seed areas, and seed files
of Notion Section 9. `tests/test_reference_adopter_end_to_end.py` drives the
tools over `InProcessClient` and a real `MemoryStore` on `InMemoryStorage`:
startup index, per-scope lifecycle, session writes, `system/` read-only,
the organization write restriction, version conflict and retry, and the
capped index. `tests/test_reference_adopter_config.py` checks the fixture
itself and runs `ResolverConformance` for four identities.

No `src/` change. No library defect found: every end-to-end test passed on
the first run against the fixture.

Failing-first evidence: before the fixture existed, both new modules failed
collection with `ModuleNotFoundError: No module named 'reference_adopter'`.

`make check`: lint and typecheck clean; **3732 passed, 18 skipped** (main has
6; the 12 new skips are the invalid-credential cases of the four new
`ResolverConformance` subclasses, since `SandboxResolver` accepts every
credential).

## Acceptance criteria → tests

`C` = `tests/test_reference_adopter_config.py`, `E` =
`tests/test_reference_adopter_end_to_end.py`.

| # | Test(s) |
| - | ------- |
| 1.1 | `C::test_scopes_are_user_project_organization` |
| 1.2 | `C::test_only_organization_writes_are_restricted_to_admin_and_owner` |
| 1.3 | `C::test_store_factory_uses_reference_scope_priority` |
| 1.4 | `C::test_seed_areas_match_section_nine` |
| 1.5 | `C::test_seed_areas_slot_names_every_area_scope_and_system` |
| 1.6 | `C::test_scope_guidance_names_every_scope_and_organization_roles` |
| 1.7 | `C::test_seed_files_cover_every_scope_and_stay_in_known_areas` |
| 1.8 | `C::TestMemberIdentityConformance`, `TestAdminIdentityConformance`, `TestTravelerIdentityConformance`, `TestPartialIdentityConformance` |
| 1.9 | `C::test_ticking_clock_advances_by_step`, `::test_ticking_clock_rejects_naive_start`, `::test_ticking_clock_rejects_bad_step` (3 cases) |
| 2.1 | `E::test_us2_1_index_holds_exactly_the_seed_files` |
| 2.2 | `E::test_us2_2_index_orders_system_then_user_project_organization` |
| 2.3 | `E::test_us2_3_index_omits_another_users_file` |
| 2.4 | `E::test_us2_4_index_entries_carry_the_seed_source` |
| 3.1-3.7 | `E::test_us3_scope_lifecycle[user-member]`, `[project-member]`, `[organization-admin]` |
| 4.1 | `E::test_us4_1_index_reflects_session_writes_and_deletes` |
| 4.2 | `E::test_us4_2_admin_index_sees_shared_scopes_not_user_ada` |
| 4.3 | `E::test_us4_3_traveler_follows_the_user_across_organizations` |
| 4.4 | `E::test_us4_4_partial_member_reads_the_organization_scope` |
| 5.1, 5.3 | `E::test_us5_1_system_area_is_read_only_through_tools[{user-member,project-admin,organization-admin}-{write_file,append_line,replace_fact,delete_file}]` (12 cases, e.g. `[user-member-write_file]`) |
| 5.2, 5.3 | `E::test_us5_2_system_check_precedes_role_check` (4 tools) |
| 5.4 | `E::test_us5_4_transport_accepts_the_system_write_the_tools_reject` |
| 6.1, 6.3 | `E::test_us6_1_organization_writes_require_admin_or_owner` (4 tools) |
| 6.2 | `E::test_us6_2_members_can_read_the_restricted_scope` |
| 7.1 | `E::test_us7_1_stale_append_conflicts_with_current_content` |
| 7.2 | `E::test_us7_2_retry_with_the_returned_version_merges_both_lines` |
| 8.1 | `E::test_us8_1_capped_index_is_a_priority_prefix_of_the_uncapped_index` |
| 8.2 | `E::test_us8_2_capped_rows_name_every_omitted_area` |
| 8.3 | `E::test_us8_3_list_prefix_recovers_the_omitted_files` |
| 9.1 | All of the above run under `make check`, unit-marked, on `InMemoryStorage` and `InProcessClient` |
| 9.2 | `tests/test_prompts_assembly.py`, `tests/test_prompts_write_mechanics.py` (import change only) |

## Architecture / ADR changes

- No new ADR: no public API, module boundary, or storage change.
- `ARCHITECTURE.md`, `prompts` entry: names `tests/reference_adopter.py` and
  `tests/test_reference_adopter_end_to_end.py`.
- [ADR 0025](../../docs/adr/0025-prompt-layer-sections-and-slots.md)
  decision 10: text updated for the new module and its wider contents.
- [ADR 0026](../../docs/adr/0026-product-identity.md): path-only fix.
- `README.md`: link points at `tests/reference_adopter.py`.

## Deviations from spec

- None.

## Look closely at

- The fixture move: slot constants moved verbatim; docstring and imports
  rewritten; git does not record a rename, so diff the slot text against the
  deleted file. The two prompt tests change only their import (9.2).
- The US8 cap: the slack equals the smallest entry after `budget-b`, and
  `budget-a` is larger, so changing the index include loop's `break` to
  `continue` fails all three US8 tests (verified by hand, then reverted).
- The 12 new skips are the invalid-credential resolver cases; confirm that is
  acceptable for `SandboxResolver`.
- US5.4 pins that the transport accepts a `system/` write the tools reject,
  so enforcement stays a tool-layer concern.

## Follow-ups

- None.

## Spec review

Round 1 FAIL (2 blocking, 7 should-fix, 8 nits, all folded in). Round 2
PASS with 1 should-fix and 2 nits folded in.

## Code review

Two reviews PASS. Mutation testing caught 14 of 16 library mutations in the
new modules; the rest are caught elsewhere. Folded in: the US8 cap now
catches a skip-and-keep-filling index, readable parametrize ids, fixture
constants instead of literal paths and IDs, tier counts derived from the
seed files, and a second `list_prefix` page in 8.3.
