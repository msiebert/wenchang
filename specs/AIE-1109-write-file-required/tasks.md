# Tasks: write_file required `source`

**Linear issue**: AIE-1109 | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

Each task runs test-writer (failing tests) → implementer (make them pass) →
`make check` green, in order.

## T1 — MemoryStore.write_file `source` and sources union

Add required keyword-only `source` to `write_file` per the plan.md
algorithm and error table; update all existing call sites.

Acceptance: spec US1.1–3, US2.1–4, US3.1–8. FR-001–FR-006. Files
`tests/test_core_write_file.py`, `tests/test_core_delete_file.py`.
