# PR Review: AIE-1050 — Deciding what to remember

## What changed & why

`wenchang.prompts.remembering.BODY` now holds the "Deciding what to remember"
prose from Notion §8.1: the confidence labels and their §4 meanings (with
`[system]` reserved for curated content), the calibration rule, the
forward-looking write-worthiness test, in-line expiry stated in prose, writing
as facts arise, and a pointer that the next section's refusals override the
test. New `tests/test_prompts_remembering.py` pins each acceptance criterion;
the glossary gains an "In-line expiry" entry. No code outside `BODY` changes.

`make check`: 3365 passed, 6 skipped, 41 deselected.

## Acceptance criteria → tests

All tests are in `tests/test_prompts_remembering.py`.

| Acceptance criterion (Given/When/Then) | Test(s) |
| --------------------------------------- | ------- |
| US1.1 `BODY.strip()` is non-empty | `test_body_is_non_empty` (:32) |
| US1.2 `HEADING == "Deciding what to remember"` | `test_heading_is_unchanged` (:37) |
| US1.3 `len(BODY) < 2500` | `test_body_is_under_length_budget` (:42) |
| US2.1 bracketed label set equals `ConfidenceLabel` values | `test_body_label_set_matches_confidence_label_enum` (:47) |
| US2.2 names each label in code formatting | `test_body_names_each_label` (:54) |
| US2.3 defines stated / observed / inferred by evidence source | `test_body_defines_learned_labels` (:70) |
| US2.4 `[system]` curated, seeded, never written new | `test_body_reserves_system_label` (:76) |
| US2.5 existing labels kept on merge; only new or rewritten lines labeled | `test_body_preserves_labels_on_merge` (:82) |
| US3.1 "calibrated" and "evidence" | `test_body_calibrates_phrasing` (:95) |
| US3.2 exact "investigated X once" contrast | `test_body_calibrates_phrasing` (:95) |
| US4.1 "would remembering this change a future session?" | `test_body_states_save_criterion` (:116) |
| US4.2 "better, different, or faster", "regardless of", "true" | `test_body_states_save_criterion` (:116) |
| US4.3 applied at "write time" | `test_body_states_save_criterion` (:116) |
| US4.4 covers observed facts, workflows, findings | `test_body_states_save_criterion` (:116) |
| US4.5 transient / one-off number / the definition or pattern | `test_body_states_save_criterion` (:116) |
| US5.1 "end date", "in the fact line", "in prose" | `test_body_describes_in_line_expiry` (:137) |
| US5.2 exact JSON / v3 migration example | `test_body_describes_in_line_expiry` (:137) |
| US5.3 "not a metadata field", "per-fact timestamp" | `test_body_describes_in_line_expiry` (:137) |
| US5.4 "user's own framing", "never guess" | `test_body_describes_in_line_expiry` (:137) |
| US5.5 "still applies", "maintenance pass", "lapsed" | `test_body_describes_in_line_expiry` (:137) |
| US5.6 no ISO date, clock time, year, or metadata key (raw) | `test_body_has_no_machine_dates_or_metadata` (:143); positive control `test_negative_patterns_match_known_bad_sample` (:149) |
| US5.7 at most one example fact line (raw) | `test_body_has_at_most_one_example_fact_line` (:154); positive control `test_fact_line_pattern_counts_multiple_lines` (:159) |
| US6.1 "as facts arise", "mid-conversation", "before you ask a follow-up", "conversation may end" | `test_body_describes_write_timing` (:176) |
| US6.2 "refusals in the next section", "override" | `test_body_describes_write_timing` (:176) |

## Architecture / ADR changes

- N/A: section wording is not API (ADR 0025 decision 2), and the prose follows
  Notion §8.1 with no departure, so no `ARCHITECTURE.md` change or ADR.
- Glossary: added "In-line expiry" after "Confidence label" in
  `docs/product/glossary.md`.

## Deviations from spec

- None.

## Look closely at

- Fidelity of the exact `BODY` prose to Notion §8.1 (labels, calibration
  contrast, worthiness test, expiry, write timing).
- `[system]` wording: "you never write a new `[system]` line" versus the
  curated-correction flow in AIE-1052; confirm the "new" qualifier leaves room
  for that.
- "The refusals in the next section" relies on AIE-1054 filling
  `privacy.BODY`; until then the next rendered section is Filing, so the
  pointer is dangling in the interim.
- The example fact line is lowercase and subject-less
  (`- [stated] prefers JSON output, ...`), kept verbatim from the source.

## Follow-ups

- The `append_line` docstring still lists `[system]` as a label without saying
  it is reserved (candidate docstring change, design doc §3.1).
- "October 30" in the example carries no year (verbatim source, and US5.6
  forbids years); worth a note for the forgetting work (AIE-1053) on how
  year-less end dates are judged as lapsed.

## Adversarial review findings

(filled in after code review)
