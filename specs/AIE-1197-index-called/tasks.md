# Tasks: AIE-1197

- [x] T1 (test-writer) Failing corpus tests for AC1 to AC3 in
  `tests/test_evals_scenario.py`; failing zero-call end-to-end test for AC6
  in `tests/test_evals_end_to_end.py`; add `index-called-in-session-2` to
  the `recall-across-sessions` / `recall_wrong` entry of `CASES` (AC5).
- [x] T2 (implementer) Add the assertions to the 39 scenarios in
  `evals/scenarios/`; `make check` green.
- [x] T3 (doc-updater) ADR 0028 note, AIE-1170 spec 4.1, AIE-1170 plan.md
  (AC7, AC8); write review-pr.md (AC9).
- [x] T4 Adversarial code review (two reviewers); route fixes.
- [x] T5 (lead) `make check`; commit, push, open PR.
