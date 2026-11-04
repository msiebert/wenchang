# Tasks: Correct article before the product name

**Linear issue**: AIE-1321 | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

## T1 — Tests

test-writer (`tests/**`): in `tests/test_tools_descriptions.py`, update
`PINNED_FIRST_LINES` (four lines), restate the US5.4 single-insertion test per
AC5 (mandatory "a" -> "one" substitution) and add `"Inkwell"` to its
products, add the AC1 and AC2 tests. New and changed test docstrings cite
AIE-1321 (keep existing AIE-1164 citations). Confirm they fail against current
code. Do not remove any test.

## T2 — Templates

implementer (`src/**`): change the four `_FIRST_LINE_TEMPLATES` entries in
`src/wenchang/tools.py` per plan.md. Add no AIE id to `src/wenchang/tools.py`
(`test_tools_module_cites_no_linear_ids` bans it). `make check` green. Commits
are prefixed "AIE-1321:".

## T3 — Docs

doc-updater: add a dated "Note (AIE-1321, 2026-11-02)" to ADR 0026 covering
lines ~89-93, ~98-105, ~109-110, ~146-147 (see plan.md), update the
ARCHITECTURE.md sentence (~1024-1027), write review-pr.md.
