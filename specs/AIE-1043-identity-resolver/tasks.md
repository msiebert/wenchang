# Tasks: identity resolver interface

**Linear issue**: AIE-1043 | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

Each task runs test-writer (failing tests), then implementer (make them
pass), then a green `make check`, in order.

## T1 — Segment check and identity value types

Make `paths.is_valid_segment` public (also rejecting `/`), and add
`ScopeGrant`, `Identity`, and `ResolutionFailure` to the new
`src/wenchang/identity.py`, following plan.md.

Acceptance: spec US1.1–7, US2.1–12. Segment cases in `tests/test_paths.py`,
the rest in new `tests/test_identity.py`. Covers FR-001–FR-003 and FR-007.

## T2 — Resolver protocol, entry point, and sandbox resolver

Add `IdentityResolver`, `resolve_identity`, and `SandboxResolver` to
`src/wenchang/identity.py`, following the outcome table and algorithm in
plan.md.

Acceptance: spec US3.1–6, US4.1–3, in `tests/test_identity.py`. Covers
FR-004–FR-006 and SC-001.
