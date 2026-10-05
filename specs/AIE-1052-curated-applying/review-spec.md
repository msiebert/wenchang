# Spec Review: AIE-1052 — Curated-content correction and applying memory

## What & why

Notion §8.1 asks for two pieces of judgment text. "Curated content" tells
the agent that the `system/` area is read-only (the tools already enforce
it), that a curated fact is corrected only when the user explicitly says it
is wrong, and that the correction goes into a writable topical file, where it
wins on conflict and survives the next refresh. "Applying memory" tells the
agent to use a stored fact only when it changes what is concluded,
recommended, or asked, and to apply facts at the level recorded. This fills
the two empty `BODY` constants AIE-1055 created.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| US1 | `curated_content` | read | heading "Curated content"; pinned phrases for read-only/tool-enforced, `[system]` curated, explicit-only correction, new fact line with own label in a writable topical file, ask per Scopes, tell the user, wins and survives refresh; no label redefinition; no sentence directs a write into `system/` (checker proven against known-bad text) |
| US2 | `applying_memory` | read | heading "Applying memory"; pinned substance test, exclusion, surveillance, level recorded, single mention not a trait; at most one example |
| US3 | both | invariant scan | existing invariants pass; vocabulary contract; every sentence traceable |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| Name no write tool in the curated body | "append it with `append_line`" | which tool is AIE-1051's job; avoids any sentence pairing a write tool with `system/` |
| Defer ask-before-shared to "the Scopes section" | restate an ask rule | the adopter's scope guidance owns it (Notion §8.2) |
| Inferred conflict: say only that it is never grounds for a correction | also prescribe surfacing the conflict | not in §8.1; would be an invented rule |
| "level recorded" read as wording plus confidence label | wording only | the label is how certainty is recorded; refers to it without redefining |
| One example, covering both exclusion and inflation | none; several | decision 8 allows at most one |

## Files/modules to be touched

- `src/wenchang/prompts/curated_content.py`, `src/wenchang/prompts/applying_memory.py` (`BODY` only)
- `tests/test_prompts_curated_content.py`, `tests/test_prompts_applying_memory.py` (new)
- `specs/AIE-1052-curated-applying/`

## Open questions / assumptions

- None.

## Risks

- Prose can drift from AIE-1050's label wording; mitigated by referring to
  "its own confidence label" only.
- Phrase pins fix wording; later edits must update the pins.

## Adversarial review

Round 1 (FAIL, 0 BLOCKING, 3 SHOULD-FIX, 4 NIT). Fixed:
- "The correction wins" was descriptive only; now an instruction ("answer from the correction"), pinned.
- The applying-memory example taught topical relevance ("unrelated answer"); now models the substance test ("mention it only if it changes what you suggest"), pinned.
- The write-into-`system/` checker missed edit-in-place verbs (update, replace, edit, change); widened to any mutation verb before `system/`, with two more known-bad cases and a comment on negated sentences.
- NITs: corrected the expected-failure note; correction label "rather than the curated fact's"; stronger multi-word pins replacing `ask`, `wrong`, `shared`, `conclude`.

Round 2 (PASS, 0 BLOCKING, 0 SHOULD-FIX, 1 NIT): the US2.7 example pin moved into the phrase parametrization.
