# PR Review: AIE-1197 — Assert the index was consulted in non-privacy eval scenarios

## What changed & why

39 eval scenarios gain a `tool_called get_memory_index` assertion (`index-called`). The three two-session recall scenarios also gain `index-called-in-session-2`, scoped to session 2. This pairs each lookup with the `index_read_first` ordering check, which passes vacuously when a session makes no memory calls. The five `privacy-*` refusal scenarios are excluded, and the four AIE-1185 scenarios are unchanged. No grader or prompt change.

## Acceptance criteria → tests

| Acceptance criterion | Test(s) |
| -------------------- | ------- |
| AC1: every non-privacy scenario asserts the index was called | `tests/test_evals_scenario.py::test_non_privacy_scenarios_assert_the_index_was_called` |
| AC2: privacy scenarios do not require the index; they are exactly the five known | `test_privacy_scenarios_do_not_require_the_index`, `test_privacy_scenarios_are_the_five_known` (same file) |
| AC3: index-called assertions are named by session | `test_index_called_assertions_are_named_by_session` (same file) |
| AC4: a correct driver passes every assertion | `tests/test_evals_end_to_end.py::test_correct_driver_passes_every_assertion` |
| AC5: a wrong driver fails exactly the listed assertions (only the recall-across-sessions set gains `index-called-in-session-2`) | `test_wrong_driver_fails_exactly_the_listed_assertions` (same file) |
| AC6: a session with no memory calls fails `index-called` | `test_session_without_memory_calls_fails_index_called` (same file) |
| AC7, AC8: docs updated | ADR 0028 note; AIE-1170 spec row 4.1 and plan.md |
| AC9: historical runs not newly failed | Historical scan below |
| AC10: `make check` passes | 4610 passed |

## Historical scan

Scanned merged run dirs (shards and preflight excluded as duplicates or ungraded): aie1182-n6 138, aie1183-n6 138, aie1184-n6 108, aie1185-n3 30, aie1185-r2-n6 120, aie1185-fix-n6 108, baseline-main-n3 33, regression-20261014-225317-sonnet 54, regression-20261014-231845-sonnet-merged 54. That is 783 non-privacy trials.

Method: per trial, find the sessions in `trace.json` with a `get_memory_index` call and compare them with the required sessions (1, or 1 and 2 for the recall pair). Pass is read from `grade.json` `passed`.

Result: one trial lacks a required call, aie1185-fix-n6 `applying-relevant-only` trial 2 (0 calls). It already failed (`index-called` and `read-seed`, both added by AIE-1185). Newly failing: 0 in every run.

## Architecture / ADR changes

- One sentence added to the ADR 0028 note. No new ADR, no `ARCHITECTURE.md` change.

## Deviations from spec

- None.

## Look closely at

- The privacy exclusion rationale: a refusal that touches no memory is correct there, so requiring the index would fail good behavior.
- `test_privacy_scenarios_are_the_five_known` forces an explicit decision whenever a new `privacy-*` scenario is added.

## Follow-ups

- None.
