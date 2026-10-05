# Implementation Plan: Write mechanics prose

**Linear issue**: AIE-1051 | **Branch**: `AIE-1051-write-mechanics` | **Date**: 2026-10-05 | **Spec**: [spec.md](spec.md)

## Summary

One constant changes: `BODY` in `src/wenchang/prompts/write_mechanics.py`.
One new test file: `tests/test_prompts_write_mechanics.py`. No docs, ADR, or
glossary change (the section follows Notion §8.1 and introduces no new term).

## Technical Context

Python >= 3.12; pyright strict; ruff line length 100. No new dependencies.
`wenchang.prompts` imports nothing from `wenchang` outside the package.

## Constitution Check

| Principle | Status |
| --------- | ------ |
| I. Tests-first | T1 test-writer, then implementer |
| II. Tests not negotiable | No existing test touched |
| Storage via interface only | Unchanged |
| Architecture changes documented | None needed: section wording is not API (ADR 0025 decision 2) and the text follows §8.1 |

## Interface

Module `wenchang.prompts.write_mechanics` (existing):

- `HEADING: Final[str] = "Choosing a write tool"` (unchanged).
- `BODY: Final[str]`: flush-left triple-quoted string (`"""\` then text, a
  trailing newline before the closing quotes), as in `overview.py`. ASCII,
  lines <= 100 columns, under 2500 characters.

Tests import `from wenchang.prompts import build_memory_prompt, write_mechanics`
and `from prompts_reference_adopter import REFERENCE_SLOTS` (the form
`tests/test_prompts_assembly.py` uses).

Whitespace normalization for phrase pins: `re.sub(r"\s+", " ", BODY)`.
Sentence splitting for 3.3 and 3.4: on the normalized body,
`re.split(r"(?<=[.!?])\s+", text.strip())`.

## Exact BODY text

```text
Match the write to the change. To add one fact to an existing file, use `append_line`. To
change one fact, use `replace_fact` and quote the existing line as `old_string`, with its new
form as `new_string`, so only that fact changes and the surrounding lines stay intact. Reserve
`write_file` for creating a new file or restructuring many lines. Writing this way makes it
mechanically impossible to disturb lines you were not editing.

When a write introduces a new name for the subject, pass that name in `aliases` on the same
call: `append_line`, `replace_fact`, or the `write_file` that creates or restructures the file.
When a fact changes what the file's one-line `description` should say, pass the new
`description` on the same call too, so adding a name or refreshing the description never forces
a full rewrite. Removing an alias, or rewriting the description wholesale with no fact to write,
is a `write_file`.

To drop one fact line, call `replace_fact` with the whole line as `old_string`, including the
line break that follows it (if none follows it, the line break before it), and an empty
`new_string`, so no blank line is left behind. Use `delete_file` only when the whole file goes.
```

Traceability (every sentence to the Linear text, §8.1, or addendum
decisions 1 and 2):

| Sentence | Source |
| -------- | ------ |
| Match the write to the change | §8.1 |
| `append_line` to add one fact | §8.1, Linear; "existing file" because the tool appends to an existing file and new files go to `write_file` |
| `replace_fact`, quote the existing line, surrounding lines intact | §8.1, Linear |
| `write_file` for a new file or restructuring many lines | §8.1, Linear |
| mechanically impossible to disturb lines you were not editing | §8.1, Linear |
| new name as `aliases` on the same call (`append_line`, `replace_fact`, or the creating/restructuring `write_file`) | addendum decision 1, ADR 0024 |
| changed `description` on the same call, so added metadata never forces a full rewrite | addendum decision 1, ADR 0024 consequences |
| removing an alias or rewriting the description wholesale is `write_file` | addendum decision 1 |
| drop one fact line: whole line plus the break after it (if none, the one before it), empty `new_string` | addendum decision 2; "if none follows it" also covers a last line with no trailing break; an only line ending in a break is covered by the follows-it case |
| `delete_file` only when the whole file goes | addendum decision 2 split (judgment in forgetting) |

"Rewriting the description wholesale with no fact to write" is stated in
the body so the agent sees the distinction: a description refreshed to
reflect the fact being written rides on that call.

## Files

- `src/wenchang/prompts/write_mechanics.py`
- `tests/test_prompts_write_mechanics.py`
- `specs/AIE-1051-write-mechanics/`
