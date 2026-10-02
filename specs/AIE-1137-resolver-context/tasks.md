# Tasks: clear exception context when resolve_identity re-raises

**Linear issue**: AIE-1137 | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

## T1 — Clear context on every ResolverFailureError

Test-writer adds the two tests in plan.md's Test layout. Today the context
test fails for rows 1 and 4. Row 3 already passes, and the traceback test is
a regression guard. The implementer then raises outside the `except` block,
as described under Mechanism in plan.md, and `make check` passes.

Acceptance: spec US1 rows 1–4. Covers FR-001, FR-002, SC-001, SC-002. Also
covers the docs: ADR 0014 update note and the ARCHITECTURE.md identity
clauses.
