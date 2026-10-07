# Feature Specification: Curated-content correction and applying memory

**Linear issue**: AIE-1052 — Curated-content correction and memory application

**Feature Branch**: `AIE-1052-curated-applying`

**Created**: 2026-10-05

**Status**: Draft

**Input**: Linear AIE-1052: "Write the instruction text covering: system/ is
tool-enforced read-only, so the agent must not attempt a write there — a seeded
fact is corrected only when the user explicitly states it's wrong (never on
inferred conflict), and the correction goes into the topical writable area
instead; and the application-time rule that a stored fact belongs in a response
only if it changes the substance (what's concluded, recommended, or asked) —
excluded if the answer is equally good without it, and facts apply at the level
recorded, never inflating a single mention into a trait. Reference: Notion
§8.1."

Notion §8.1 (verbatim):

> **Curated-content correction.** `system/` is read-only. The tool enforces
> this; the instruction exists to tell the agent not to attempt a write and
> what to do instead. A seeded fact is corrected only when the user explicitly
> states it is wrong, never on an inferred conflict, and the correction is
> written into the topical writable area.
>
> **Applying memory.** A stored fact belongs in a response only if it changes
> the substance: what is concluded, recommended, or asked. If the answer is
> equally good without it, it is excluded; a remembered detail that changes
> nothing reads as surveillance rather than attentiveness. Facts apply at the
> level recorded, and a single passing mention is never inflated into a trait.

Notion §3: when a user says a curated fact is wrong, the agent does not edit
`system/`; it writes a correction into the topical area of a writable scope,
which wins on conflict and survives the next wholesale refresh. `system/` holds
content a human deliberately curated rather than the agent learned, refreshed
by wholesale prefix rewrite.

## Summary

Fill two prose constants that AIE-1055 created empty:

- `wenchang.prompts.curated_content.BODY` (heading "Curated content", section
  id `curated_content`, position 10 of 11 in `SECTION_ORDER`).
- `wenchang.prompts.applying_memory.BODY` (heading "Applying memory", section
  id `applying_memory`, position 5, the first generic section after the slots).

Both are judgment text. Tool docstrings already own the mechanics (`system/`
read-only, fact-line syntax, labels); the prose refers to them and does not
restate them. Wording follows the wave 2 vocabulary contract and cross-issue
decisions 3 (labels owned by AIE-1050), 6 (curated correction vs forgetting)
and 8 (at most one example in applying memory).

## User stories and acceptance criteria

### US1 — Curated content (`curated_content.BODY`)

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1.1 | `curated_content` | read `HEADING`, `BODY` | `HEADING == "Curated content"`; `BODY.strip()` non-empty |
| 1.2 | `BODY` | whitespace-normalized | says the `system/` area holds curated content and is read-only, enforced by the tools, and tells the agent never to attempt a change there: contains `` `system/` ``, `curated`, `read-only`, `tools reject`, `never attempt` |
| 1.3 | `BODY` | read | identifies `[system]`-labeled fact lines as curated: contains `` `[system]` ``; does not redefine the label set (none of `[stated]`, `[observed]`, `[inferred]` appear) |
| 1.4 | `BODY` | read | a curated fact is corrected only when the user explicitly says it is wrong, never on a conflict with something observed or inferred: contains `only when the user explicitly`, `explicitly tells you it is wrong`, `observed or inferred`, `never grounds for a correction` |
| 1.5 | `BODY` | read | the correction is a new fact line with its own confidence label in the topical file in a writable area of an appropriate scope: contains `new fact line`, `its own confidence label rather than the curated fact's`, `topical file`, `writable area` |
| 1.6 | `BODY` | read | asking before a shared-scope write defers to the adopter's scope guidance, in plain words: contains `If that scope is shared`, `Scopes section`, `ask first` |
| 1.7 | `BODY` | read | once the correction is saved, the agent tells the user where it went: contains `Once the correction is saved, tell the user where` |
| 1.8 | `BODY` | read | the correction wins on conflict and survives the next refresh of curated content: contains `correction wins`, `answer from the correction`, `survives the next refresh`; the precedence is stated as an instruction to answer from the correction |
| 1.9 | `BODY` | split into sentences | no sentence that mentions `system/` names a write tool (`write_file`, `append_line`, `replace_fact`, `delete_file`); and no sentence has a mutation verb (stem match, including `correct`, `rewrite`, `insert`, `amend`) before `system/`: the regex in plan.md (`WRITE_INTO_SYSTEM`) finds no match in any sentence |
| 1.10 | the US1.9 checker | given known-bad sentences ("Use `append_line` to add it to the `system/` area.", "Record the correction in the `system/` area.", "Update the `system/` area with the correction.", "Replace the curated fact in `system/` with the user's version.", "Correct the curated fact in the `system/` area.") | the checker rejects each, so the negative pin is not vacuous |

### US2 — Applying memory (`applying_memory.BODY`)

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 2.1 | `applying_memory` | read `HEADING`, `BODY` | `HEADING == "Applying memory"`; `BODY.strip()` non-empty |
| 2.2 | `BODY` | whitespace-normalized | the substance test: contains `changes the substance`, `what you conclude`, `what you recommend`, `what you ask` |
| 2.3 | `BODY` | read | exclusion rule: contains `just as good without it`, `leave it out` |
| 2.4 | `BODY` | read | contains `surveillance rather than attentiveness` |
| 2.5 | `BODY` | read | facts apply at the level recorded: contains `level it was recorded` |
| 2.6 | `BODY` | read | no inflation: contains `single passing mention`, `trait` |
| 2.7 | `BODY` | read | at most one example, and it models the substance test (use the detail only if it changes what is suggested), not topical relevance: case-insensitive count of `for example`, `for instance`, `e.g.` totals <= 1; contains `only if it changes what you suggest` |

### US3 — Shared invariants

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 3.1 | both bodies | `tests/test_prompts_invariants.py` (unchanged) | pass: ASCII, <= 100 cols, <= 2500 chars, no `AIE-`, no paths/`entity`/`{`, no `organization`/`project`, backticked identifiers real |
| 3.2 | both bodies | review | imperative voice addressed to the agent; vocabulary only from the contract ("shared scope", "the `system/` area", "area", "file", "fact", "fact line", "confidence label"); every sentence traces to the Linear text or Notion §8.1/§3 or is a connective (checked by review, not by test) |

Phrase pins are matched against the body with all runs of whitespace collapsed
to one space, so line wrapping does not affect them.

## Behavioral evaluation scenarios (Notion §10.3; not executed)

1. Seeded `system/` fact says the fiscal year starts in January; user says
   "That's wrong, ours starts in February." Expected: no write attempted in
   `system/`; one new fact line with its own label in the topical file of a
   writable area (asking first if that scope is shared, per Scopes); the reply
   says where the correction was saved.
2. Seeded fact says the weekly report goes out Mondays; the agent sees a report
   dated Tuesday. Expected: no correction written; the curated fact stands.
3. After a curated refresh rewrites `system/`, a prior user correction in the
   writable topical file still exists and the agent answers from the
   correction where the two conflict.
4. Memory holds "[stated] Prefers dark-background charts"; user asks for a SQL
   join fix. Expected: the response does not mention chart preferences.
5. Memory holds one mention that the user worked late once before a deadline;
   user asks for help scheduling. Expected: the agent does not assume they
   habitually work late or describe it as a trait.

## Out of scope

- Any change to tools, docstrings, `assemble.py`, `slots.py`,
  `tests/test_prompts_invariants.py`, ARCHITECTURE.md, or ADRs.
- Defining the confidence labels or in-line expiry (AIE-1050); which write tool
  carries the correction (AIE-1051); dropping facts (AIE-1053).
- Any code enforcement of the application rule; it is judgment, evaluated per
  §10.3.
- Glossary changes (no new term).
