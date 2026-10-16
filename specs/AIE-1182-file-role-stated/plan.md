# Plan: File a fact the user states inside a question

**Linear issue**: AIE-1182 | **Spec**: [spec.md](spec.md)

Consistent with Notion §8.1; no ADR per ADR 0025 §4.

## Public interface

No interface change. `wenchang.prompts.remembering.HEADING` and `BODY` keep
their names and types; `build_memory_prompt` and section order are unchanged.
No ARCHITECTURE.md change.

## A. Prompt text (`src/wenchang/prompts/remembering.py`, implementer)

Replace the final paragraph of `BODY`. The base is the branch's current final
paragraph (write-timing sentence plus the narrow role sentence):

```
Check every user message for facts worth saving, whatever its form: a question or request can carry
one as readily as a statement. Write facts as they arise, before you answer or ask a follow-up
question, because the conversation may end first.
```

It names no fact type, so it covers preferences, constraints, ownership, tools,
and project facts alike. What to save and where stays with the save criterion,
the scope guidance and its ask rule, and the privacy override. Stay within the
2500-character budget and 100 columns.

## B. Tests (`tests/test_prompts_remembering.py`, test-writer)

Pin only load-bearing terms (ADR 0025 §8). Docstrings cite `AIE-1182, USx.y`.

- Update `test_body_describes_write_timing`: "before you ask a follow-up"
  becomes "before you answer or ask a follow-up".
- Remove `test_body_covers_incidental_role_mentions`,
  `test_incidental_role_rule_sits_in_write_timing_paragraph`, and
  `test_assembled_prompt_carries_incidental_role_rule`; they pin rejected text.
- US1.1: parametrized phrases in `_flat(remembering.BODY)`: "Check every user
  message for facts worth saving", "whatever its form", "a question or request
  can carry one", "before you answer or ask a follow-up".
- US1.2: split raw `remembering.BODY` on `"\n\n"`; one paragraph contains
  "Check every user message" at an earlier index than "Write facts as they
  arise".
- US1.3: `build_memory_prompt(REFERENCE_SLOTS)` (from
  `evals.reference_adopter`); the text between `## Deciding what to remember`
  and the next `\n## ` contains, after `_flat`, "Check every user message for
  facts worth saving".

US1.4 and US2.2 are covered by existing invariants; no new test. Confirm the new
tests fail against the branch's pre-edit prompt because the phrases are absent.

## C. Scenario headers (`evals/scenarios/`, implementer)

Grep for "before you ask a follow-up" under `evals/scenarios` and update the
quoted text to the new timing sentence (`remembering-stated-role` at least).
Turns and assertions unchanged.

## D. Agent file (implementer)

After A, run `uv run python -m evals render-agent` from the worktree to
regenerate `.claude/agents/wenchang-eval.md`, then record its sha256 for
review-pr.md.

## E. Held-out scenarios (T2, before any prompt edit)

The four scenarios in spec US5. implementer writes the yaml, each with a
`# Prompt:` header citing existing sentences, index-first, durable facts.
test-writer writes a correct and a wrong scripted driver per scenario in
`tests/test_evals_end_to_end.py` with exact fail sets, and adds the 4 ids to the
CORPUS set in the corpus-set test.

## F. Docs (doc-updater)

`specs/AIE-1182-file-role-stated/review-pr.md` from the template, with live-eval
slots for US4.

## Gate

`make -C /Users/marksiebert/p/github/wenchang-AIE-1182 check` green. The PR
stays gated on the human live run (US4).
