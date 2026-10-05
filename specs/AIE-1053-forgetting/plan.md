# Implementation Plan: Forgetting section text

**Linear issue**: AIE-1053 | **Branch**: `AIE-1053-forgetting` | **Date**: 2026-10-05 | **Spec**: [spec.md](spec.md)

## Summary

One constant changes: `BODY` in `src/wenchang/prompts/forgetting.py`. One new
test file: `tests/test_prompts_forgetting.py`. No docs outside this spec dir.

## Technical Context

Python >= 3.12; pyright strict; ruff line length 100. No new dependency, no
import change, no public API change (section wording is not API, ADR 0025
decision 2).

## Constitution Check

| Principle | Status |
| --------- | ------ |
| I. Tests-first | T1 test-writer (red against the empty `BODY`) then implementer |
| II. Tests not negotiable | No existing test touched; invariant tests must pass over the new body |
| VI. Spec fidelity | Text follows Notion §8.1 and the Linear issue; no deviation, so no ADR |
| VII. Architecture documented | No module boundary or API change; ARCHITECTURE.md unchanged |
| VIII. Traceability | Test docstrings cite AIE-1053; no Linear IDs in `src/` |

## Interface (unchanged shape)

```python
# src/wenchang/prompts/forgetting.py
"""Guidance on removing memory that is wrong or stale."""

from typing import Final

HEADING: Final[str] = "Forgetting"
BODY: Final[str] = """\
<prose below>
"""
```

Consumed by `wenchang.prompts.build_memory_prompt(slots, /)` as section id
`"forgetting"`, the last entry of `SECTION_ORDER`, rendered as
`## Forgetting\n\n{BODY.strip()}`. Tests import
`from wenchang.prompts import forgetting, build_memory_prompt, PromptSlots`.
`PromptSlots(scope_guidance="...", seed_areas="...")` with non-blank strings is
a valid argument.

## Target prose

Flush-left, ASCII, every line <= 100 columns, well under 2500 characters.
Implementer uses this text verbatim (rewrapping only if a line exceeds 100
columns).

```text
Forgetting has two moves: drop one fact, or delete the whole file. To drop one fact, call
`replace_fact` with the whole fact line as `old_string` and an empty `new_string`; the write-tool
section says how to take the line break with it. If that fact line is the file's only fact,
delete the file instead of leaving it empty. To remove a whole file, call `delete_file`. When it
is ambiguous whether the user means one fact or the whole file, ask before you remove anything.

Removal is total. Do not rewrite a removed fact as something once believed, and do not leave a
softened note that it was ever true. Anything derived solely from the removed fact goes too: drop
each `[inferred]` line that rested only on it, and delete a file whose only content was derived
from it. Keep anything that has support of its own. If a description or alias of the file that
held it exists only because of the removed fact, update it too, as the write-tool section
describes.

A fact line may state its own end date in prose. Once that date has passed, the fact is a
candidate for dropping, not automatically removable: when you read the file or during
maintenance, judge whether the fact still holds, and drop the line only if it no longer does.

Never drop or delete anything in the `system/` area. If the user asks you to forget a curated
fact, tell them you cannot remove it; if they say it is wrong, correct it as the curated-content
section describes.
```

Sentence trace:
- "two moves ... whole file" — §8.1 sentence 1.
- `replace_fact` / `delete_file` sentences — Linear content requirement; addendum
  decision 2 (line-break detail deferred to the write-tool section).
- "When it is ambiguous ... ask" — §8.1 sentence 3.
- "If that fact line is the file's only fact, delete the file instead" —
  dropping the last fact is in effect the delete-file move; an empty file with a
  description and aliases would leave a trace (§8.1 "Removal is total").
- "Removal is total ... ever true" — §8.1 sentence 2 (paraphrases "no
  softened 'used to think X'" without quoting the softened phrasing).
- "Anything derived solely ... support of its own" — §8.1 sentence 2; the
  `[inferred]` and derived-only-file cases are the Linear content requirement;
  the last sentence is the necessary converse of "solely".
- "a description or alias ... exists only because of the removed fact" — §8.1 "Removal is total": the
  description and aliases are the index's search surface; the write-tool
  section (AIE-1051) owns which tool removes an alias or rewrites a description.
- End-date paragraph — Linear issue text; addendum decision 5.
- `system/` paragraph — addendum decision 6 (imperative "Never"); the "tell them"
  clause covers a plain forget request on curated content, and the correction
  path is gated on the user saying the fact is wrong, as in AIE-1052.

## Test design (`tests/test_prompts_forgetting.py`)

- Module docstring cites AIE-1053; `pytestmark = pytest.mark.unit`; style follows
  `tests/test_prompts_overview.py`.
- Helper `_flat(text) = re.sub(r"\s+", " ", text)`.
- Non-empty body (US1.1), heading pin (US1.2), assembled-tail check (US1.3).
- Parametrized phrase pins over `_flat(BODY)` (US2.1-2.3, 2.5, 3.1, 3.3, 3.4,
  3.5, 4.1 `ambiguous`, 5.1-5.3, 6.1, 6.2).
- `\bask\b` regex pin (US4.1).
- Negative pins: other write tools absent (US2.4); softened phrasing absent,
  case-insensitive (US3.2).
- Each test docstring cites `AIE-1053` and the criterion number.
