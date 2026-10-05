# Implementation Plan: Filing and deduplication discipline

**Linear issue**: AIE-1049 | **Branch**: `AIE-1049-filing-dedup` | **Date**: 2026-10-05 | **Spec**: [spec.md](spec.md)

## Summary

One constant changes: `wenchang.prompts.filing.BODY`. One new test file:
`tests/test_prompts_filing.py`. No ARCHITECTURE, ADR, or glossary change:
section wording is not API (ADR 0025 decision 2) and the text follows
Notion §8.1 without deviation.

## Technical Context

Python >= 3.12; pyright strict; ruff (line length 100). No dependency or
packaging change.

## Constitution Check

| Principle | Status |
| --------- | ------ |
| I. Tests-first | T1: test-writer, then implementer |
| II. Tests not negotiable | No existing test touched |
| V. Storage via interface | Not touched |
| VI. Spec fidelity | Every sentence traces to §8.1, §4, or the Linear text |
| VII. Architecture documented | No boundary or API change |
| VIII. Traceability | Test docstrings cite AIE-1049; no Linear IDs in `src/` |

## Interface

Module `wenchang.prompts.filing` (unchanged shape):

```python
HEADING: Final[str] = "Filing"
BODY: Final[str] = """\
...prose below...
"""
```

Consumed by `wenchang.prompts.build_memory_prompt(slots, /)`, which emits
`"## Filing\n\n" + filing.BODY.strip()` as section 8 of `SECTION_ORDER`.
`PromptSlots(scope_guidance: str, seed_areas: str, systems_of_record: str |
None = None)` from `wenchang.prompts` builds a valid slots value for tests.

## `BODY` text (exact)

Flush-left, starts `"""\`, ends with a newline before the closing quotes,
ASCII, every line <= 100 columns:

```text
Put each fact in the file that is about its subject, not in whichever file happens to be open
from earlier in the session. The seed areas are a starting shape: create new files and areas as
subjects need them.

Before you create a new file, check whether one already exists on the subject. Scan the
descriptions and aliases in the index you loaded with `get_memory_index()`. If nothing there
matches and the area you would file into is listed under `capped` in the index, call
`list_prefix(scope, area)` for that one area only and check its entries the same way. When a
match is ambiguous, read the top one or two candidates with `read_file` to confirm, never the
whole store. If a file on the subject exists, append to it or edit it instead of creating a
duplicate. This check runs only when you create a file; appending to a file you already know
does not trigger it.

Every write should carry any new names the subject will later be looked up by: nicknames,
acronyms, and the phrasings people use for it. Pass them as `aliases` on the same `append_line`
or `replace_fact` call that writes the fact, or in `write_file` when you create or restructure a
file. Descriptions and aliases are the entire search surface: there is no content search, so a
later mention finds a file only through them, and each write should make the next match more
likely. Removing an alias is a `write_file`.
```

Traceability:
- Paragraph 1: §8.1 Domain filing.
- Paragraph 2: §8.1 Deduplication ("already loaded at session start" ->
  "the index you loaded"); capped-area sentence is addendum decision 4,
  gated on no index match (consistent with the `get_memory_index` docstring).
- Paragraph 3: §8.1 Alias upkeep, scoped to new names per addendum
  decision 1 ("when a write introduces a name"); "entire search surface" /
  "no content search" from §4; the same-call sentence (with decision 1's
  `write_file` qualifier) and the removal sentence are addendum decision 1,
  both explicitly required by the orchestrator's content requirements.

## Tests (`tests/test_prompts_filing.py`)

Style follows `tests/test_prompts_overview.py`: `pytestmark =
pytest.mark.unit`; a helper `_normalized(text)` collapsing `\s+` to one
space; every test docstring starts `AIE-1049, USx.y:`.

- `test_filing_heading` (US1.1): `filing.HEADING == "Filing"`.
- `test_filing_body_non_empty` (US1.1).
- `test_filing_body_length` (US1.2): `len(filing.BODY) <= 2000`.
- `test_filing_section_in_assembled_prompt` (US1.3): with
  `PromptSlots(scope_guidance="Scopes text.", seed_areas="Seed text.")`,
  `"## Filing\n\n" + filing.BODY.strip()` is in `build_memory_prompt(slots)`.
- `test_filing_body_contains_phrase` parametrized with ids per criterion
  over the "contains" phrases of US2.1, 2.2, 3.1-3.5, 3.7, 4.1-4.4, matched
  against the normalized body.
- `test_filing_body_omits_phrase` parametrized over US2.3 (`slug`,
  `lowercase`, case-insensitive) and US3.6 (`` `list_prefix(scope)` ``).
