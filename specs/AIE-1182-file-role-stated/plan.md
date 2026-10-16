# Plan: File a fact the user states inside a question

**Linear issue**: AIE-1182 | **Spec**: [spec.md](spec.md)

Consistent with Notion §8.1; no ADR per ADR 0025 §4.

## Public interface

No interface change. `wenchang.prompts.remembering.HEADING` and `BODY` keep
their names and types; `build_memory_prompt` and section order are unchanged.
No ARCHITECTURE.md change.

## A. Prompt text (`src/wenchang/prompts/remembering.py`, implementer)

Two edits to `BODY`. Neither names a fact type. Stay within the 2500-character
budget and 100 columns.

1. Replace the final paragraph (the branch's current write-timing sentence plus
   the narrow role sentence) with:

```
Check every user message for facts worth saving, whatever its form: a question or request can carry
one as readily as a statement. Write facts as they arise, before you answer or ask a follow-up
question, because the conversation may end first. Save a fact then; do not offer to save it later.
When a fact needs the user's go-ahead first, ask in that same reply instead.
```

2. Append to the save-criterion paragraph, leaving its existing sentences
   verbatim: "What the user mentions about themselves or how they work while asking
   for something else counts as much as what they set out to tell you."

What to save and where stays with the save criterion, the scope guidance and its
ask rule, and the privacy override.

## B. Tests (`tests/test_prompts_remembering.py`, test-writer)

Pin only load-bearing terms (ADR 0025 §8). Docstrings cite `AIE-1182, USx.y`.

- Update `test_body_describes_write_timing`: "before you ask a follow-up"
  becomes "before you answer or ask a follow-up".
- Remove `test_body_covers_incidental_role_mentions`,
  `test_incidental_role_rule_sits_in_write_timing_paragraph`, and
  `test_assembled_prompt_carries_incidental_role_rule`; they pin rejected text.
- US1.1: the full new final paragraph in `_flat(remembering.BODY)`, plus
  parametrized phrases: "Check every user message for facts worth saving",
  "whatever its form", "a question or request can carry one", "before you answer
  or ask a follow-up", "do not offer to save it later", "ask in that same
  reply".
- US1.2: split raw `remembering.BODY` on `"\n\n"`; one paragraph contains
  "Check every user message" at an earlier index than "Write facts as they
  arise".
- US1.3: `build_memory_prompt(REFERENCE_SLOTS)` (from
  `evals.reference_adopter`); the text between `## Deciding what to remember`
  and the next `\n## ` contains, after `_flat`, "Check every user message for
  facts worth saving".
- US1.4: the new final paragraph and the appended sentence contain no backtick
  or bracket.
- US1.5: the appended sentence is present in the save-criterion paragraph (the
  paragraph containing "Save a fact only if").

US2.2 is covered by existing invariants. Confirm the new tests fail against the
branch's pre-edit prompt because the phrases are absent.

## C. Scenario headers (`evals/scenarios/`, implementer)

Grep for "before you ask a follow-up" under `evals/scenarios` and update the
quoted text to the new timing sentence (`remembering-stated-role` at least).
Turns and assertions unchanged.

## D. Agent file (implementer)

After A, run `uv run python -m evals render-agent` from the worktree to
regenerate `.claude/agents/wenchang-eval.md`, then record its sha256 for
review-pr.md.

## E. Held-out scenarios and guards (T2 and T5, before any prompt edit)

The five scenarios in spec US5. implementer writes the yaml, each with a
`# Prompt:` header citing existing sentences only, index-first, durable facts.
test-writer writes a correct and a wrong scripted driver per scenario in
`tests/test_evals_end_to_end.py` with exact fail sets, and adds the 5 ids to the
CORPUS set in the corpus-set test.

The US6 guards edit existing scenarios (stricter, not weakened). implementer
edits the yaml; test-writer gives each scripted driver an exact fail set and
adds wrong-driver rows that misfile to `user` where needed.

## F. Docs (doc-updater)

`specs/AIE-1182-file-role-stated/review-pr.md` from the template, with live-eval
slots for US4, including the main baseline step (spec 4.6).

## Gate

`make -C /Users/marksiebert/p/github/wenchang-AIE-1182 check` green. The PR
stays gated on the human live run (US4).
