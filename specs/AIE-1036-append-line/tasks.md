# Tasks: append_line

**Linear issue**: AIE-1036 | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

Each task runs test-writer (failing tests) → implementer (make them pass) →
`make check` green, in order.

## T1 — MemoryStore.append_line

Add `append_line` to `MemoryStore` per the plan.md algorithm and error
table.

Acceptance: spec US1.1–7, US2.1–5, US3.1–7. New file
`tests/test_core_append_line.py`. FR-001–FR-007.
