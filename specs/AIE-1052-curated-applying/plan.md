# Implementation Plan: Curated-content correction and applying memory

**Linear issue**: AIE-1052 | **Branch**: `AIE-1052-curated-applying` | **Spec**: [spec.md](spec.md)

## Summary

Replace two empty `BODY` constants with prose. No signatures, modules, or
assembly change. `build_memory_prompt()` already reads each `BODY` at call
time and emits `## {HEADING}\n\n{BODY.strip()}` for non-empty bodies.

## Technical context

Python 3.13, pyright strict, ruff (100 cols), pytest with `pytestmark =
pytest.mark.unit`. No new dependency. No ADR: the text follows Notion §8.1.

## Public interface (unchanged shape)

```python
# src/wenchang/prompts/curated_content.py
HEADING: Final[str] = "Curated content"  # unchanged
BODY: Final[str] = """\
...
"""

# src/wenchang/prompts/applying_memory.py
HEADING: Final[str] = "Applying memory"  # unchanged
BODY: Final[str] = """\
...
"""
```

Flush-left triple-quoted strings starting `"""\`, ASCII only, every line
<= 100 columns, ending with a newline before the closing `"""`, as in
`overview.py`. Module docstrings stay as they are.

## Exact text

`curated_content.BODY`:

```text
The `system/` area in each scope holds curated content: facts a person deliberately maintains
for you, not facts you learned, and the whole area is replaced each time that content is
refreshed. Fact lines labeled `[system]` are curated. The `system/` area is read-only and the
tools reject any change to it, so never attempt one.

Correct a curated fact only when the user explicitly tells you it is wrong. A conflict with
something you observed or inferred is never grounds for a correction. When the user does say a
curated fact is wrong, record the correction as a new fact line, with its own confidence label
rather than the curated fact's, in the topical file in a writable area of the appropriate
scope. If that scope is shared, follow the Scopes section on whether to ask first. Once the
correction is saved, tell the user where it went. When the correction and the curated fact
conflict, the correction wins: answer from the correction. Because it lives outside the
`system/` area, it survives the next refresh of the curated content.
```

`applying_memory.BODY`:

```text
Use a stored fact in a response only if it changes the substance: what you conclude, what you
recommend, or what you ask. If the answer would be just as good without it, leave it out. A
remembered detail that changes nothing reads as surveillance rather than attentiveness.

Apply each fact at the level it was recorded, no broader and no more certain than its wording
and its confidence label say. Never inflate a single passing mention into a trait. For example,
if the user once mentioned working late before a deadline, mention it only if it changes what
you suggest, and do not treat them as someone who always works late.
```

Traceability (sentence -> source): curated P1 S1 = Notion §3 (deliberately
curated, wholesale refresh); P1 S2 = issue content requirement / decision 3;
P1 S3 = §8.1 "tool enforces; do not attempt a write". P2 S1-S2 = §8.1
explicit-only, never inferred conflict; S3 = §8.1 topical writable area +
decision 6 (own label); S4 = adopter scope guidance (connective); S5 =
decision 6 (tell the user, once saved); S6-S7 = §3 (wins on conflict, so answer from it; survives refresh).
Applying P1 = §8.1 substance test, exclusion, surveillance; P2 S1 = §8.1
level recorded (confidence label is the recorded level of certainty);
S2 = §8.1 no inflation; S3 = the one example (decision 8).

## Tests (test-writer; read nothing under src/ beyond this plan)

Both files follow `tests/test_prompts_overview.py`: module docstring citing
AIE-1052, `pytestmark = pytest.mark.unit`, a helper
`_normalized(text) = re.sub(r"\s+", " ", text)`, and a sentence splitter
`re.split(r"(?<=[.!?])\s+", collapsed.strip())`.

`tests/test_prompts_curated_content.py`:

- `test_heading_and_body` (US1.1).
- `test_body_contains_phrase`, parametrized over the US1.2-US1.8 phrases from
  spec.md, matched in `_normalized(BODY)`.
- `test_body_does_not_redefine_labels` (US1.3): none of `[stated]`,
  `[observed]`, `[inferred]` in `BODY`.
- `_write_into_system(sentence) -> bool`: true if the sentence contains
  `` `system/` `` or `system/` and either names one of `WRITE_TOOLS =
  ("write_file", "append_line", "replace_fact", "delete_file")`, or matches
  `WRITE_INTO_SYSTEM = re.compile(r"\b(write|append|add|save|record|put|store|edit|update|change|replace|fix|modify|overwrite|delete|drop|remove|rewrite|insert|correct|amend)\w*\b[^.]*`?system/", re.IGNORECASE)`
  (a mutation verb anywhere before `system/` in the same sentence). Add a short
  comment in the test: only a verb before `system/` is detected; verbs match
  as stems (so "recorded" and "address" also trip it); and a negated sentence
  such as "Never write to the `system/` area." also trips it, so the body
  phrases the prohibition without a mutation verb before `system/`.
- `test_no_sentence_directs_a_write_into_system` (US1.9): no sentence of
  `BODY` satisfies `_write_into_system`.
- `test_write_into_system_checker_rejects_known_bad` (US1.10), parametrized
  over "Use `append_line` to add it to the `system/` area.", "Record the
  correction in the `system/` area.", "Update the `system/` area with the
  correction.", "Replace the curated fact in `system/` with the user's
  version.", and "Correct the curated fact in the `system/` area.": each
  returns true.

`tests/test_prompts_applying_memory.py`:

- `test_heading_and_body` (US2.1).
- `test_body_contains_phrase`, parametrized over US2.2-US2.6 phrases.
- `test_at_most_one_example` (US2.7): `sum(lower.count(m) for m in ("for
  example", "for instance", "e.g."))` <= 1 on the normalized, lowercased body. The US2.7 pin
  `only if it changes what you suggest` goes in `test_body_contains_phrase`.

Expected failure before implementation: every test fails on the empty `BODY`
except US1.10 and the empty-body passes of US1.3 (no labels), US1.9, and
US2.7. Those three are meaningful only next to US1.1/US2.1, which fail.

## Check order / errors

None; text constants only.
