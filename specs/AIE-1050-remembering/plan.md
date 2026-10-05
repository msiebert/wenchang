# Implementation Plan: Deciding what to remember

**Linear issue**: AIE-1050 | **Branch**: `AIE-1050-remembering` | **Date**: 2026-10-05 | **Spec**: [spec.md](spec.md)

## Summary

One constant changes: `wenchang.prompts.remembering.BODY`. One new test
file: `tests/test_prompts_remembering.py`. Glossary entry
"In-line expiry" placed after "Confidence label" in
`docs/product/glossary.md` (one hunk).

## Technical Context

Python >= 3.12; pyright strict; ruff line length 100. No new dependencies;
no import changes in `src/`.

## Constitution Check

| Principle | Status |
| --------- | ------ |
| I. Tests-first | T1 test-writer, then implementer |
| II. Tests not negotiable | No existing test touched; shared invariants keep running over the new body |
| Storage via interface only | Unaffected (prose only) |
| Architecture changes documented | None needed: wording is not API (ADR 0025 decision 2); no departure from Section 8.1 |

## Interface (for test-writer; do not read `src/`)

```python
# src/wenchang/prompts/remembering.py (unchanged shape)
from typing import Final

HEADING: Final[str] = "Deciding what to remember"
BODY: Final[str] = """\
...exact text below...
"""

# label enum used by the label-set test
from wenchang.file_format import ConfidenceLabel  # StrEnum: stated, observed, inferred, system
from wenchang.prompts import remembering
```

`build_memory_prompt` emits this section as `## Deciding what to remember`
followed by `BODY.strip()`.

## Exact BODY text

The implementer writes `BODY` as a flush-left triple-quoted string starting
`"""\` followed by exactly these lines (each <= 100 columns, ASCII), ending
with a trailing newline before the closing `"""`:

```text
Every fact line carries a confidence label that says how you know it:

- `[stated]`: the user said it to you directly.
- `[observed]`: you saw it in a tool result, session data, or behavior.
- `[inferred]`: you concluded it from a pattern across several observations.

`[system]` marks curated content, seeded rather than learned; you never write a new `[system]`
line. When you merge into an existing file, lines that already carry a label keep it; only new
or rewritten lines get a fresh one. Keep your phrasing calibrated to the evidence: write
"investigated X once," not "is deeply focused on X."

Decide at write time, and look forward: would remembering this change a future session? If it
would let you give a better, different, or faster answer next time, save it; if not, leave it
out, regardless of whether it is true. This covers more than what the user tells you directly:
facts you observe during work, and workflows and findings you could reuse, count too. Leave out
transient content. A one-off number goes stale; its durable form is the definition or pattern
behind it, so save that when you know it, not the number.

When a durable fact has a knowable end date, state that end date in the fact line itself, in
prose, as part of the sentence:

`- [stated] prefers JSON output, but only until the v3 migration completes on October 30.`

The end date is ordinary fact text: it is not a metadata field, and you never add a per-fact
timestamp. State an end date only when the user's own framing in this conversation makes the end
condition explicit; never guess an expiry the user did not imply. A later session can then judge
whether the fact still applies, and a maintenance pass can see what has lapsed.

Write as facts arise, mid-conversation, before you ask a follow-up question, because the
conversation may end first. The refusals in the next section override this test: never write
what they forbid, however worth remembering it seems.
```

## Test design

`tests/test_prompts_remembering.py`, style of `tests/test_prompts_overview.py`,
`pytestmark = pytest.mark.unit`, every docstring citing AIE-1050 and the
criterion id. A helper `_flat(text) = re.sub(r"\s+", " ", text)` collapses
whitespace for phrase pins (so re-wrapping the prose does not break tests).
Phrase pins are parametrized lists per user story (US2.2-2.5, US3, US4,
US5.1-5.5, US6). US2.1 compares
`set(re.findall(r"\[([a-z]+)\]", BODY))` with
`{label.value for label in ConfidenceLabel}`. US5.6 and US5.7 run on the raw
body; each negative regex also gets a positive control asserting it matches
a known-bad sample (e.g. `- [stated] prefers JSON (expires: 2026-10-30)`), so
the negative pins are not vacuous.

## Glossary entry (exact)

Insert directly after the "Confidence label" entry in `docs/product/glossary.md`
(the glossary is topical, not alphabetical; this is its topical place):

```text
- **In-line expiry** — a durable fact's knowable end date, stated in prose
  inside the fact line itself; not a metadata field and not a per-fact
  timestamp. Written only when the user's own framing makes the end
  condition explicit.
```

## Files

- `src/wenchang/prompts/remembering.py` (BODY only)
- `tests/test_prompts_remembering.py` (new)
- `docs/product/glossary.md` (one entry)
- `specs/AIE-1050-remembering/`
