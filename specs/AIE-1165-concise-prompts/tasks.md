# Tasks: Conciseness pass over prompt sections and tool descriptions

**Linear issue**: AIE-1165 | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

T1-T3 test-writer work touches disjoint files and runs in parallel; implementer work follows
once all three have failing tests.

## T1 — Section pins (test-writer), section text (implementer)

Criteria US1.1-1.9, US4.1-4.3. test-writer applies plan.md F1-F9 to the nine
`tests/test_prompts_<section>.py` files and confirms each changed pin fails against `main`
text for the right reason. implementer sets the nine bodies to plan.md A1-A9.

## T2 — Docstring pins (test-writer), docstrings (implementer)

Criteria US2.1-2.9, US4.1-4.3. test-writer applies plan.md F10 to
`tests/test_tools_descriptions.py`. implementer sets the seven docstrings to plan.md B1-B7.

## T3 — Reference slots and slot guidance

Criteria US3.1-3.5, US4.1-4.3. test-writer applies plan.md F12-F13, confirms the new tests
fail against the current fixture and docstring, then applies F11 (the fixture is test data).
implementer sets the `PromptSlots` docstring to plan.md D.

## T4 — Docs (doc-updater)

Criteria US3.6, US5.1, US5.1a, US5.2, US5.3. ADR 0025 decision 11 and the decision 6
"Dropping one fact" bullet, the dated note on ADR 0022 decision 8, ARCHITECTURE.md `tools` and `prompts`
entries, README, and review-pr.md with the recomputed measurement table, per plan.md E.

## Gate

`make -C /Users/marksiebert/p/github/wenchang-wt/AIE-1165 check` green after T1-T3 and after
T4.
