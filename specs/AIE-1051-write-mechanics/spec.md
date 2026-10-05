# Feature Specification: Write mechanics prose

**Linear issue**: AIE-1051 — Write mechanics: append vs. replace-fact vs. full-file write

**Feature Branch**: `AIE-1051-write-mechanics`

**Created**: 2026-10-05

**Status**: Draft

**Input**: Linear AIE-1051; Notion §8.1 "Write mechanics"; milestone 4 brief,
design doc, and wave 2 addendum (vocabulary contract, cross-issue wording
decisions 1 and 2); ADR 0024 (aliases/description on `append_line` and
`replace_fact`); ADR 0025 (prompt layer).

## Summary

Write the body of the `write_mechanics` prompt section (heading "Choosing a
write tool", position 9 of `SECTION_ORDER`): which write tool fits which
change. The only source change is `wenchang.prompts.write_mechanics.BODY`.

Linear issue text: "Write the instruction text on matching the write
operation to the change: append_line to add a fact, replace_fact (quoting
the existing line) to change one fact so only that fact changes and
surrounding lines stay intact, and full-file write reserved for new files or
restructuring many lines — making it mechanically impossible to disturb lines
the agent wasn't editing."

Notion §8.1, verbatim: "Write mechanics. Match the write to the change.
Append to add a fact. Replace-fact to change one fact, quoting the existing
line so only that fact changes and surrounding lines stay intact. Reserve
full-file write for new files or restructuring many lines. This makes it
mechanically impossible to disturb lines the agent was not editing."

## Settled inputs (not re-litigated here)

- `append_line` and `replace_fact` take optional `aliases` (unioned, never
  removed) and `description` (replaces) (ADR 0024). Only `write_file`
  removes an alias.
- Addendum decision 1: a new name for the subject rides as `aliases` on the
  same `append_line`/`replace_fact` call (or in the `write_file` that creates
  or restructures the file); removing an alias or rewriting the description
  wholesale with no fact to write is a `write_file`. The filing section owns why
  aliases matter; this section says only which call carries them.
- Addendum decision 2: dropping one fact is `replace_fact` with the whole
  line as `old_string`, including the line break after it, and an empty
  `new_string`. The addendum gives the fallback as "for the last line, the
  one before it"; this section says "if none follows it, the one before it",
  which agrees for normal files and also covers a last line with no trailing
  break. This section is the only place that mechanical detail lives; the forgetting section owns when
  to drop versus delete.
- Docstrings own per-call mechanics: version conflicts, the unique-anchor
  rule, the byte ceiling, the label syntax, `system/` being read-only, and
  the slug rule. The body does not restate them. "Quote the existing line"
  is allowed because the choice of tool depends on it.

## User stories and acceptance criteria

All criteria are tested in `tests/test_prompts_write_mechanics.py`. "Body"
means `write_mechanics.BODY` with every run of whitespace collapsed to one
space (so line wrapping never breaks a pin).

### US1 — Section shape

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1.1 | `write_mechanics.BODY` | read | `BODY.strip() != ""` |
| 1.2 | `write_mechanics.HEADING` | read | equals `"Choosing a write tool"` |
| 1.3 | `build_memory_prompt(REFERENCE_SLOTS)` | call | output contains `"## Choosing a write tool\n\n" + BODY.strip()` |

### US2 — Matching the tool to the change (Linear text, §8.1)

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 2.1 | body | read | contains `Match the write to the change` |
| 2.2 | body | read | contains `` `append_line` ``, `add one fact`, and `existing file`; the one sentence containing `add one fact` names `` `append_line` `` |
| 2.3 | body | read | contains `` `replace_fact` ``, `change one fact`, `quote the existing line`, and `surrounding lines stay intact`; the one sentence containing `change one fact` names `` `replace_fact` `` |
| 2.4 | body | read | contains `` `write_file` ``, `new file`, and `restructuring many lines`; the one sentence containing `restructuring many lines` names `` `write_file` `` |
| 2.5 | body | read | contains `mechanically impossible to disturb lines you were not editing` |

### US3 — Metadata rides on the fact write (addendum decision 1)

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 3.1 | body | read | contains `` `aliases` `` and `` `description` `` |
| 3.2 | body | read | the one sentence containing ``pass that name in `aliases` `` and the one sentence containing ``pass the new `description` `` each contain `same call` (the alias and description go on the same `append_line`, `replace_fact`, or creating/restructuring `write_file` call) |
| 3.3 | body | read | contains `Removing an alias` and `rewriting the description wholesale with no fact to write`, and the sentence containing `Removing an alias` names `` `write_file` `` |
| 3.4 | body | read | the sentence containing ``pass that name in `aliases` `` names `` `append_line` ``, `` `replace_fact` ``, and `` `write_file` `` |

### US4 — Dropping one fact line (addendum decision 2)

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 4.1 | body | read | contains `drop one fact line`, `` `old_string` ``, and ``empty `new_string` ``; the one sentence containing `drop one fact line` names `` `replace_fact` `` |
| 4.2 | body | read | contains `line break that follows it` and `the line break before it` |
| 4.3 | body | read | contains `no blank line` |
| 4.4 | body | read | the one sentence containing `` `delete_file` `` contains `only when the whole file goes` |

### US5 — Judgment only, not docstring mechanics (negative pins)

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 5.1 | body, lowercased | read | contains none of `conflict`, `expected_version`, `version`, `unique`, `byte`, `ceiling`, `retry`, `read-only`, `slug` |
| 5.2 | body | read | contains none of `[stated]`, `[observed]`, `[inferred]`, `[system]` (label syntax belongs to the docstring and the remembering section) |
| 5.3 | `write_mechanics.BODY` | read | `len(BODY) < 2500` (the shared invariant enforces `<= 2500`) |

The shared invariant test (`tests/test_prompts_invariants.py`) already
covers ASCII, line length, tool and parameter names, and paths for this body
without edits.

## Behavioral eval scenarios (input for a later harness, §10.3)

1. User mentions a new preference about a subject with an existing file:
   agent calls `append_line` on that file, never `write_file`.
2. User corrects one existing fact: agent calls `replace_fact` quoting that
   line; every other line of the file is byte-identical afterward.
3. A fact introduces a nickname ("call it Atlas"): agent passes `aliases`
   on the same `append_line`/`replace_fact` call; no separate `write_file`.
4. User says one fact is no longer true and the file holds other facts:
   agent calls `replace_fact` with the whole line plus its line break as
   `old_string` and `new_string=""`; no blank line remains.
5. A subject has no file yet: agent creates it with `write_file`, not
   `append_line`.

## Out of scope

- When to drop versus delete, and asking when ambiguous (forgetting).
- Why aliases matter and which names to add (filing).
- Labels and what makes a fact worth writing (remembering).
- Any change to tools, docstrings, `assemble.py`, `slots.py`, shared tests,
  ARCHITECTURE.md, or ADRs.
