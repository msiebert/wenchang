# Tasks: replace_fact

**Linear issue**: AIE-1034 | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

Each task runs test-writer (failing tests) → implementer (make them pass) →
`make check` green, in order. No task runs in parallel with another.

## T1 — replace_fact at the current version

Add `MemoryStore.replace_fact` per plan.md steps 1–3 and 4, with step 3c
exercised only for `expected_version` equal to the stored version.

Acceptance: spec US1.1–4, US2.1–4, US4.1–7, edge case `old == new`. New
file `tests/test_core_replace_fact.py`. FR-001, FR-002, FR-005, FR-006,
FR-007.

## T2 — Stale versions and races

Stale-token re-apply, overlap escalation, and the 3-attempt put loop
(plan.md step 3c "otherwise", 3f retry, step 4).

Acceptance: spec US3.1–6, US4.4 (deleted between failed put and re-read),
edge case "unrecognized token is treated as stale". In
`tests/test_core_replace_fact.py`. FR-003, FR-004.
