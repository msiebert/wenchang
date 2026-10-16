# Tasks: A changed fact states only what is true now (AIE-1183)

Tests come first. `make check` must be green after each commit.

## Commit 1: held-out evidence

- [ ] T1, test-writer: add the `CASES` rows and drivers for the four new
  scenarios, update the `write-correct-seeded-fact` fail set, and update
  `CORPUS` (plan §1.1-§1.6).
- [ ] T2, implementer: write the five YAML edits (plan §1.1-§1.5), then run
  `make check`.
- [ ] T3, lead: commit.

## Commit 2: prompt edit

- [ ] T4, test-writer: update the prose pins and the header test (plan
  §2.3).
- [ ] T5, implementer: edit `forgetting.py` and `write_mechanics.py`, update
  the two headers, re-render the agent file, run `make check`, and report
  the sha256 (plan §2.1, §2.2, §2.4, §2.5).
- [ ] T6, doc-updater: update `review-pr.md`.
- [ ] T7, lead: commit, push, and update PR #38's title and body.

## Human

- [ ] T8: run the baseline at main and the live gate after #39 merges, then
  fill in `review-pr.md`.
