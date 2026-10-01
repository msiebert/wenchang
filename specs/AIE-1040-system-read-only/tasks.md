# Tasks: Read-only enforcement for the system/ area

**Linear issue**: AIE-1040 | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

Each task runs test-writer (failing tests), then implementer (make them
pass), then a green `make check`, in order.

## T1 — scope module with the system/ check

Precondition: AIE-1041 (`paths.parse_path`) and AIE-1043 are on the base
branch. If `parse_path` is absent, stop and report; do not inline a parser.

Add `src/wenchang/scope.py` with `SYSTEM_AREA`, `is_system_path`, and
`check_not_system`, following the error table and algorithm in plan.md. Do
not change `core`, `paths`, or `errors`, and do not call the check from
`MemoryStore`.

Acceptance: spec US1.1–5, US2.1–3, US3.1–2, US4.1, and the Edge Cases
equivalence. New file `tests/test_scope_system.py`. No existing test file
changes. Covers FR-001–FR-006.

## T2 — Docs

doc-updater:

- Updates the ARCHITECTURE.md `scope / identity` entry.
- Changes the diagram's enforcement edge to `tools --> scope` and moves the
  `scope` node out of the Core subgraph.
- Rewords the `system/` invariant to: exact equality of the area segment with
  `system`, in `scope.check_not_system`; core deliberately does not apply it
  so seeding can rewrite `system/`.
- Writes `docs/adr/0016-system-read-only-enforcement.md` from the decisions
  listed in plan.md.
