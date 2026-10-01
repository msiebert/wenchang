# Tasks: Resolver conformance suite

**Linear issue**: AIE-1039 | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

Each task runs test-writer (failing tests), then implementer (make them
pass), then a green `make check`, in order.

**Merge preconditions.** AIE-1043, AIE-1041, AIE-1040, and AIE-1042 are all
merged to `main`, and this branch is based on that `main`. Check before T1
that these names import: `wenchang.identity.SandboxResolver`,
`wenchang.paths.parse_path`, `wenchang.scope.SYSTEM_AREA`,
`wenchang.scope.check_write`, and `wenchang.errors.RestrictionReason.NOT_GRANTED`.
If any is missing, stop and report. Do not stub them.

## T1 — Package skeleton and testing extra

Add the `testing` optional extra to `pyproject.toml` and run `uv lock`.
Create `src/wenchang/testing/__init__.py` and
`src/wenchang/testing/resolver_conformance.py` with the module docstring and
an empty `ResolverConformance[C]` class, following plan.md.

Acceptance: spec US9.1–3 and US9.5–7, in new
`tests/test_testing_package.py`. Covers FR-005, FR-006, and FR-008. US9.4
is written in T2.

## T2 — Suite methods and reference runs

Add the twelve test methods and the private helpers to
`ResolverConformance`, following the algorithm and message tables in
plan.md.

Acceptance: spec US1.1, US2.1, US2.5–6, US3.1, US3.3, US4.1, US5.1, US6.1,
US7.1–4, US8.1–3, in new `tests/test_resolver_conformance_reference.py`,
plus US9.4 in `tests/test_testing_package.py`. Covers FR-001, FR-002,
FR-004, FR-007, and SC-001's passing half. The reference policy includes
the restricted, ungranted `team` scope. Until the methods exist, the reference
subclasses collect no tests, so the US9.4 method-name test is T2's red
test.

## T3 — Self-tests: the suite bites

Test-writer only, unless a self-test exposes a suite defect, which the
implementer then fixes in `resolver_conformance.py`.

Acceptance: spec US1.2–11, US2.2–4, US2.7–8, US3.2, US3.4–6, US4.2–4,
US5.2–5, US6.2, US7.5–7, in new `tests/test_resolver_conformance_self.py`.
The US7.5 matrix is one parametrized test over its failing cells. Covers
FR-003, FR-007, and SC-001's failing half.

## T4 — Docs

doc-updater adds a `testing` entry to ARCHITECTURE.md, as an adopter-facing
module that depends on `identity`, `paths`, `scope`, and `errors` and that
nothing in the library imports. It notes the `wenchang[testing]` extra. It
writes `docs/adr/0018-resolver-conformance-suite.md` from the decisions in
plan.md, and drafts `review-pr.md`.
