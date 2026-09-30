# Tasks: write-restriction enforcement for role-gated scopes

**Linear issue**: AIE-1042 | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

Each task runs test-writer (failing tests), then implementer (make them
pass), then a green `make check`, in order. AIE-1040, AIE-1041, and AIE-1043
must have landed first.

## T1 — RestrictedScopeError role set and NOT_GRANTED

Change `RestrictedScopeError` to take `required_roles: frozenset[str] |
None` and add `RestrictionReason.NOT_GRANTED`, following the error tables in
plan.md.

Acceptance: spec US5.1–5, in `tests/test_errors.py`. The existing
`required_role` and two-member `RestrictionReason` expectations are updated
to the new spec text. Only the changes enumerated in the spec's
Allow-test-changes line are permitted: the factory update, the new
`NOT_GRANTED` factory with id `restricted_scope_not_granted` in both `ids`
lists, the `required_roles` switch in three tests, and the three-member enum
test. Nothing else in the file changes. Covers FR-008.

## T2 — ScopePolicy and check_write_allowed

Add `ScopePolicy` and `check_write_allowed` to `src/wenchang/scope.py`,
following the interface and algorithm in plan.md.

Acceptance: spec US1.1–9, US2.1–4, US3.1–6, and US4.1 for
`check_write_allowed`, in new `tests/test_scope_write_restriction.py`.
Covers FR-001–FR-004, FR-006, FR-007.

## T3 — check_write composite and check order

Add `check_write`, which runs the AIE-1040 `check_not_system`, then
`check_write_allowed`.

Acceptance: spec US4.1–5, in `tests/test_scope_write_restriction.py`. The
US4.4 table is the parametrized case list, run against both functions, with
the SC-001 property asserted on every row that returns `None`. Covers FR-005
and SC-001. FR-009 has no new test. AIE-1040's FR-006 import-boundary test
and the unchanged core tests cover it.
