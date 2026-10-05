# PR Review: AIE-1052 — Curated-content correction and applying memory

## What changed & why

Notion §8.1 asks for two pieces of judgment text, and this fills the two
empty `BODY` constants AIE-1055 created. `curated_content.BODY` (section 10,
"Curated content") says the `system/` area is curated and tool-enforced
read-only, so the agent never attempts a change there. A curated fact is
corrected only when the user explicitly says it is wrong, never on an
observed or inferred conflict. The correction is a new fact line, with its
own confidence label, in the topical file of a writable area (asking first
per the Scopes section if the scope is shared), and once it is saved the
agent tells the user where it went. The correction wins on conflict and
survives the next refresh. `applying_memory.BODY` (section 5, "Applying memory") sets the
substance test: use a stored fact only if it changes what is concluded,
recommended, or asked. It also says to apply facts at the level recorded and
never to inflate a single mention into a trait, with one example.

## Acceptance criteria → tests

| Acceptance criterion (Given/When/Then) | Test(s) |
| --------------------------------------- | ------- |
| US1.1 heading "Curated content", body non-empty | `tests/test_prompts_curated_content.py:44` `test_heading_and_body` |
| US1.2-US1.8 (incl. US1.3 positive) pinned phrases (read-only/tools reject/never attempt; `[system]`; explicit-only, never on observed or inferred conflict; new fact line with own label rather than the curated fact's, topical file, writable area; shared -> Scopes section, ask first; once saved, tell the user where; correction wins, answer from it, survives the next refresh) | `tests/test_prompts_curated_content.py:83` `test_body_contains_phrase` (21 params) |
| US1.3 no label redefinition | `tests/test_prompts_curated_content.py:88` `test_body_does_not_redefine_labels` |
| US1.9 no sentence directs a write into `system/` | `tests/test_prompts_curated_content.py:94` `test_no_sentence_directs_a_write_into_system` |
| US1.10 checker rejects known-bad sentences | `tests/test_prompts_curated_content.py:112` `test_write_into_system_checker_rejects_known_bad` (5 params) |
| US2.1 heading "Applying memory", body non-empty | `tests/test_prompts_applying_memory.py:21` `test_heading_and_body` |
| US2.2-US2.7 pinned phrases (substance, what you conclude/recommend/ask, just as good without it, surveillance rather than attentiveness, level recorded, single passing mention, trait, example models the substance test) | `tests/test_prompts_applying_memory.py:49` `test_body_contains_phrase` (11 params) |
| US2.7 at most one example | `tests/test_prompts_applying_memory.py:54` `test_at_most_one_example` |
| US3.1 shared invariants | `tests/test_prompts_invariants.py` (unchanged, parametrized over every section) |
| US3.2 voice, vocabulary, traceability | review only; see plan.md "Traceability" |

`make check`: 3347 passed, 6 skipped, 41 deselected.

## Architecture / ADR changes

- N/A. Section wording is not API (ADR 0025); no deviation from Notion §8.1.

## Deviations from spec

- None.

## Look closely at

- `src/wenchang/prompts/curated_content.py`: the prohibition is worded "the
  tools reject any change to it, so never attempt one". No write tool is
  named anywhere in the body, and the test's mutation-verb checker would flag
  a sentence like "Never write to the `system/` area." The checker detects
  only a mutation verb before `system/`, by stem.
- "Follow the Scopes section": the `scope_guidance` slot is required and
  non-empty (`PromptSlots` rejects blank), so the "Scopes" section always
  exists in the assembled prompt.
- "Apply each fact at the level it was recorded, no broader and no more
  certain than its wording and its confidence label say": this reads §8.1's
  "level recorded" as both generality and certainty.

## Follow-ups

- Behavioral eval scenarios for both sections are listed in spec.md (§10.3),
  for a later eval harness.

## Adversarial review findings

Spec review: round 1 FAIL (3 SHOULD-FIX: precedence stated but not
instructed, now "answer from the correction"; example taught topical
relevance, now models the substance test; write-into-`system/` checker missed
edit-in-place verbs, widened), round 2 PASS.

Code review round 1:
- Reviewer A (correctness): PASS, 3 NITs. Taken: "Once the correction is
  saved, tell the user where it went" (nothing to report if the user declines
  a shared-scope ask). Declined: adding "the user's statement settles which
  fact to keep" (not in §8.1; the deferral is limited to whether to ask), and
  narrowing "level recorded" to generality only (certainty reading is
  disclosed above).
- Reviewer B (tests/docs): FAIL, 1 SHOULD-FIX: the checker missed `correct`,
  `rewrite`, `insert`, `amend`; added, with a fifth known-bad case. NITs
  taken: checker comment explains verb-before and stem matching; `what you
  recommend` pin; review-pr wording. Noted: pins cannot catch a rule weakened
  by an added clause; left to review and eval scenario 2.

Code review round 2: Reviewer A PASS, Reviewer B PASS (no findings beyond a
cosmetic rewrap, fixed).

Final gate (spec-reviewer): PASS. Taken: US1.9 now asserts the body has
more than one sentence, so the negative pin always has text to scan.
Declined: rewording "the Scopes section" (the `scope_guidance` slot is
required, so the section always renders) and "Correct a curated fact"
(the next sentences make clear the correction is a new fact line outside
`system/`).
