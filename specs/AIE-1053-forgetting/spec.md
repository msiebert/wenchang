# Feature Specification: Forgetting section text

**Linear issue**: AIE-1053 — Forgetting

**Feature Branch**: `AIE-1053-forgetting`

**Created**: 2026-10-05

**Status**: Implemented

**Input**: Linear AIE-1053; Notion spec §8.1 (Forgetting paragraph); milestone 4
design doc (`wenchang.prompts`); wave 2 addendum cross-issue wording decisions
2, 5, and 6; ADR 0025; ADR 0012 (`delete_file`).

## Source text

Notion §8.1, verbatim:

> Forgetting. Two moves: drop one fact, or delete the whole file. Removal is
> total — no softened "used to think X" — and anything derived solely from the
> removed fact goes too. When it is ambiguous which the user means, ask.

Linear AIE-1053 adds: where a fact line states its own end date in prose
(in-line expiry, defined by AIE-1050), a lapsed fact is a candidate for the
drop-one-fact move, judged by the agent at read or maintenance time, never an
automatic deletion rule.

## Summary

Write `forgetting.BODY` in `src/wenchang/prompts/forgetting.py`, the last
section (position 11) of `build_memory_prompt()`, under the existing heading
"Forgetting". Add `tests/test_prompts_forgetting.py` pinning its load-bearing
tokens. No other source file changes.

## Settled wording (wave 2 addendum, binding)

- Decision 2: dropping one fact is `replace_fact` with the whole fact line as
  `old_string` and an empty `new_string`. The write-mechanics section
  (AIE-1051) owns the line-break detail; this section says "drop the line" and
  refers to the write-tool section in plain words, with no cross-reference
  syntax.
- Decision 5: a lapsed in-line expiry makes the fact a candidate for dropping,
  judged by the agent at read or maintenance time, never automatic. This
  section does not define in-line expiry.
- Decision 6: a `system/` fact is never dropped or edited (tool-enforced); the
  correction mechanics belong to the curated-content section (AIE-1052). This
  section refers to it in one sentence.
- Decision 3: labels are defined by AIE-1050; this section names `[inferred]`
  only as the label of a derived line, without redefining the set.
- Vocabulary contract: "fact", "fact line", "file", "the `system/` area"; no
  adopter scope names.

## User stories and acceptance criteria

All criteria are checked against `forgetting.BODY` with runs of whitespace
collapsed to one space (`re.sub(r"\s+", " ", BODY)`), so line wrapping does not
matter. "Contains" is a case-sensitive substring check unless stated.

### US1 — Section exists

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1.1 | `wenchang.prompts.forgetting` | read `BODY` | `BODY.strip() != ""` |
| 1.2 | `wenchang.prompts.forgetting` | read `HEADING` | `HEADING == "Forgetting"` |
| 1.3 | valid `PromptSlots` | `build_memory_prompt(slots)` | output ends with `"## Forgetting\n\n" + BODY.strip() + "\n"` (last section) |

### US2 — Exactly two moves

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 2.1 | `BODY` | read | contains `two moves` |
| 2.2 | `BODY` | read | contains `` `replace_fact` `` (drop one fact line) and the phrase `fact line` |
| 2.3 | `BODY` | read | contains `` `delete_file` `` (delete the whole file) and `whole file` |
| 2.4 | `BODY` | read | names no other write tool: does not contain `` `write_file` `` or `` `append_line` `` |
| 2.5 | `BODY` | read | refers to the write-tool section for the line-break detail in plain words: contains `write-tool section says how to take the line break` (unique to the line-break pointer) |
| 2.6 | `BODY` | read | contains `the file's only fact` (dropping a file's only fact is the delete-file move) |

### US3 — Removal is total

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 3.1 | `BODY` | read | contains `Removal is total` |
| 3.2 | `BODY` | read, lowercased | contains none of `used to`, `used-to`, `formerly`, `previously believed` (negative pin: the text never models softened phrasing, not even as a quoted example) |
| 3.3 | `BODY` | read | contains `solely` (anything derived solely from the removed fact goes too) |
| 3.4 | `BODY` | read | contains `` `[inferred]` `` (derived lines that rested only on the removed fact go too) |
| 3.5 | `BODY` | read | contains `description or alias` and `exists only because of the removed fact` (a description or alias that exists only because of the removed fact is updated too) |

### US4 — Ask when ambiguous

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 4.1 | `BODY` | read | contains `ambiguous` and the word `ask` (`re.search(r"\bask\b", ...)`) |

### US5 — Lapsed in-line expiry is a candidate, not automatic

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 5.1 | `BODY` | read | contains `end date` and `candidate` |
| 5.2 | `BODY` | read | contains `not automatically` (a stated end date makes a fact a candidate for removal, not automatically removable) |
| 5.3 | `BODY` | read | contains `maintenance` (judged at read or maintenance time) |

### US6 — Curated content

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 6.1 | `BODY` | read | contains `` `system/` `` and `curated-content section` |
| 6.2 | `BODY` | read | contains `Never drop or delete` (imperative refusal for the `system/` area) |

### US7 — Shared invariants (already enforced, no new test)

`tests/test_prompts_invariants.py` discovers `forgetting.BODY` and checks:
ASCII, lines <= 100 columns, <= 2500 characters, no Linear IDs, no paths /
`.md` / `{` / "entity", real tool names and parameters, no adopter scope names.
These must pass unchanged.

## Behavioral evaluation scenarios (Notion §10.3; not executed)

| # | Situation | Expected tool behavior |
| - | --------- | ---------------------- |
| E1 | User: "Forget that I prefer tabs." The file holding it has other facts. | `read_file`, then one `replace_fact` whose `old_string` is the whole tabs line and `new_string` is empty; no softened past-tense line is written. |
| E2 | User: "Forget everything about the Atlas migration." One file is about it alone. | `delete_file` on that file; no remnant elsewhere. |
| E3 | User: "Forget that." after a turn that touched one fact in a multi-fact file. | The agent asks whether the user means that fact or the whole file before calling any removal tool. |
| E4 | A fact says "on leave until 2026-09-30"; today is later; an `[inferred]` line rests only on it. | The agent judges that the fact no longer holds and drops it and the `[inferred]` line; a fact past its end date that other context shows still holds is left alone. |
| E5 | User asks to forget a fact that lives in the `system/` area. | No `replace_fact` or `delete_file` against `system/`; the agent tells the user it cannot remove curated content. Only if the user says the fact is wrong does it follow the curated-content correction path. |
| E6 | User asks to forget a nickname fact whose nickname was also added to the file's aliases. | The fact line is dropped and the alias is removed as the write-tool section describes, so the index no longer surfaces it. |

## Out of scope

- The line-break mechanics of dropping a line (AIE-1051, write mechanics).
- Defining in-line expiry or the confidence labels (AIE-1050).
- How a curated correction is written (AIE-1052, curated content).
- Any change to tool docstrings, `assemble.py`, shared tests, ARCHITECTURE.md,
  glossary, or ADRs; no new ADR (the text follows §8.1).
- Executing the behavioral scenarios.
