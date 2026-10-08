# Tasks: End-to-end test against the reference adopter configuration

**Linear issue**: AIE-1059 | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

Tests are the deliverable here, so "failing first" means: each new test
module is written and run before its fixture support exists, and fails on
the missing import or symbol, not on a syntax error.

## T1 — Reference adopter fixture and config tests (US1, US9.2)

- Write `tests/test_reference_adopter_config.py` (US1.1–1.9, four
  conformance subclasses). Run it; it fails on
  `ModuleNotFoundError: reference_adopter`.
- `git mv tests/prompts_reference_adopter.py tests/reference_adopter.py`;
  update the two prompt-test imports (US9.2); add the plan.md interface,
  including all four identities and the eight seed files.
- Run the config tests and the prompt tests; all pass. `make check` green.
  Commit.

## T2 — Bootstrap, per-scope lifecycle, scope properties (US2, US3, US4)

- Write US2, US3 (parametrized per scope, file `reference-e2e`), and US4.1
  through US4.4 in `tests/test_reference_adopter_end_to_end.py`. Run
  against T1's fixture. Any failure here is a library or fixture defect:
  fix the fixture, or stop and report a library defect.
- `make check` green. Commit.

## T3 — Enforcement and conflict (US5, US6, US7)

- Add US5.1 through US5.4 (system/ read-only at the tool layer, precedence
  over the role check, transport accepts the rejected path), US6 (role
  gate), US7 (shared-scope conflict with exact content). Run. `make check`
  green. Commit.

## T4 — Capped index under reference priority (US8)

- Add US8.1 through US8.3 with the two-store replay in plan.md. Run.
  `make check` green. Commit.

## T5 — Docs and review artifact (US9.1)

- README link, ADR 0025 decision 10 sentence, ADR 0026 path,
  ARCHITECTURE.md sentence (plan.md), `review-pr.md` with the criterion ->
  test table. `make check` green. Commit.
