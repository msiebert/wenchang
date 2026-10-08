# Feature Specification: Conciseness pass over prompt sections and tool descriptions

**Linear issue**: AIE-1165 — Conciseness pass over prompt sections and tool descriptions

**Feature Branch**: `AIE-1165-concise-prompts`

**Created**: 2026-10-07

**Status**: Implemented

**Input**: Linear AIE-1165; the conciseness audit (measurements, proposed text, test changes,
structural options); orchestrator decisions on the audit's seven questions (below); ADR 0025;
design doc sections 3 and 4.

## Summary

Every prompt section (`src/wenchang/prompts/*.py`) and every tool docstring
(`src/wenchang/tools.py`) is trimmed for length without losing any rule, exception, or
spec-quoted phrase. Shared tool mechanics are stated once, in `get_memory_index`; each
mutating tool keeps one self-contained conflict sentence. The reference adopter slots
(`tests/prompts_reference_adopter.py`) stop restating generic rules, and the `PromptSlots`
docstring and README say slots state only deployment facts. The exact target texts are in
plan.md sections A-D.

Linear issue text: "Audit and trim every prompt section (`src/wenchang/prompts/*.py`) and
every tool docstring (`src/wenchang/tools.py`) for conciseness without losing any rule,
exception, or spec-quoted phrase. Known duplication: 'Areas are lowercase ASCII slugs.' in
five docstrings and the overview; the version-conflict paragraph nearly verbatim in four
docstrings; the scope/area/name explanation in six docstrings. Decide where shared mechanics
live so each docstring is one first sentence plus its own specifics. Keep: docstrings own
per-call mechanics, sections own judgment; the exact §8.1 phrases. Update phrase-pin tests
where pinned phrases change; invariant tests must keep passing. Targets: >=35% fewer
characters in generic prompt text, >=40% in tool descriptions. Record before/after in
review-pr.md. No ADR unless the location of shared mechanics changes the public contract."

## Decisions (settled by the orchestrator; not re-litigated)

1. Curated correction in a shared scope: keep a short clause pointing at the Scopes section's
   ask-first rule (target text: "in a shared scope, follow the Scopes section on asking
   first", 61 chars).
2. Filing check only on create: the explicit negative ("This check runs only when you create
   a file; appending ... does not trigger it") is cut; "Before creating a file" scopes it.
3. Privacy calibration: keep "disclosure to a team rather than a note to self" and "no
   version history can undo it".
4. Docstrings: hybrid. Shared mechanics (scope/area/name meaning, `.md` exclusion, entity
   filled in, slug rule, `system/` read-only, capped paging) live once in
   `get_memory_index`. Each of the four mutating tools keeps one self-contained conflict
   sentence, and `replace_fact` states its own `aliases`/`description` behavior with no
   cross-reference to `append_line`.
5. "Regardless of whether it is true": kept in short form ("otherwise leave it out, even if
   true").
6. The privacy override is stated once, at the top of privacy; remembering's forward pointer
   is removed.
7. Overview sentence floor lowered to 3.
8. Reference-slot tightening (audit 2.11) applies; the `PromptSlots` docstring and README say
   slots state only deployment facts.
9. Headings unchanged; no sections merged.

## §8.1 and spec-quoted phrases kept verbatim

A "§8.1 phrase" here is a distinctive phrase from the Notion §8.1 text (as quoted verbatim in
the AIE-1049 through AIE-1055 specs) that a section's earlier tests pinned. Every such phrase
is kept: "changes the substance"; "at the level recorded"; "surveillance rather than
attentiveness"; "a single passing mention" ... "trait"; "refused outright" (as "Refuse
outright"); "disclosure to a team rather than a note to self"; "version history"; "Match the
write to the change"; "surrounding lines stay intact"; "mechanically impossible to disturb
lines"; "change one fact"; "restructuring many lines"; "file that is about"; "ambiguous";
"two moves" ... "drop one fact" ... "delete the whole file"; "Removal is total";
"solely"; "happens to be open"; "creating a duplicate"; "starting shape";
"never the whole store"; "top one or two candidates"; "entire search surface" (§4); "next
match more likely"; "nicknames, acronyms, phrasings"; "financial account numbers", "health
diagnoses", "anything indicating the user is a minor"; "investigated X once," not "is deeply
focused on X."; the October 30 end-date example; "Areas are lowercase ASCII slugs." (AIE-1136,
once, in `get_memory_index`).

## Rule disposition (nothing below is a lost rule)

Each cut in the current text is either a restatement of a rule kept elsewhere in the same
text, a justification sentence, or a mechanic owned by a docstring. Per section:

- **overview**: "returns an index ... descriptions and aliases" (filing's "the index's
  descriptions and aliases" carries it, and the rendered index shows the fields); "Areas are lowercase ASCII slugs" and "never type a full address" (docstring);
  "Each file has a size limit" (folded into the split rule); "rather than letting one file
  bloat" (restates "split"); "The tools only store and fetch text; the sections that follow
  say ..." (connective).
- **systems_of_record**: "do not let the two diverge silently" (stated as the action "point
  out ... and ask ... before you change memory").
- **applying_memory**: "If the answer would be just as good without it, leave it out"
  (contrapositive of "only if it changes"); the example's first half (restates rule 1).
- **remembering**: "seeded rather than learned" (curated section defines curated); "Decide at
  write time ... would remembering this change a future session?" (the "Save a fact only if
  it would let a future session ..." test); "A one-off number goes stale" (the instruction
  carries it); "not a metadata field" (folded into "Never put an end date in metadata"); "A
  later session can then judge ... maintenance pass ... lapsed" (justification; forgetting
  owns the behavior); "mid-conversation" (same as "as they arise"); the forward pointer to
  privacy (decision 6).
- **privacy**: "Apply this section as a veto before ..." (now "The refusals below override
  the previous section"); the three-bullet list (one sentence); "no matter how directly or
  willingly" ("even if the user states it directly or asks you to remember it"); "This is
  your judgment alone" (implied by "No tool filter checks ...").
- **filing**: "from earlier in the session" (wording); "you loaded with
  `get_memory_index()`" ("the index"); the create-only negative (decision 2); "so a later
  mention finds a file only through them" (restates "entire search surface"). Gained from
  write mechanics: pass a new `description` on the same write.
- **write_mechanics**: "with its new form as `new_string`" (docstring); "so only that fact
  changes" (the "mechanically impossible" sentence says it); the alias/description "same call" paragraph (filing owns it; removing an alias
  or rewriting the description wholesale stays here, in the `write_file` sentence).
- **curated_content**: "facts a person deliberately maintains for you, not facts you learned"
  (wording); "Fact lines labeled `[system]` are curated" (remembering owns labels); "the
  tools reject any change to it" (docstring; "never attempt" is the judgment); "When the
  correction and the curated fact conflict, the correction wins" (kept as "When a correction
  and a curated fact conflict, answer from the correction"); "in the appropriate scope" (Scopes section).
- **forgetting**: the `replace_fact`/`delete_file` call mechanics and the line-break pointer
  (write mechanics owns them; "drop" and "delete" are its verbs); "Do not rewrite a removed fact as something once
  believed, and do not leave a softened note" ("leave no note that the fact was ever true").
- **docstrings**: the scope/area/name sentence (6 copies -> 1), the slug sentence (6 -> 1),
  "The `system/` area is read-only." (4 -> 1), `read_file`'s "Keep the returned version"
  (each write tool says to pass the version you read); `get_memory_index`'s entry field list
  (now "path, metadata, and version"; the rendered keys show the fields) and "(or
  `list_prefix(scope)` for a whole scope)" (`list_prefix`'s first line says "a scope or
  area"); `replace_fact`'s "zero or several times ... longer, unique span" ("otherwise ...
  quote a unique span" covers both); the conflict paragraph's "someone else changed the file since
  you read it" (restates "version conflict").
- **reference slots**: "They are a starting point, not a fixed list: create a new area,
  named as a lowercase slug" (generic filing and the docstring); "It holds curated content
  ... read-only. Every other area is agent-writable" (generic curated section, docstring);
  "do not copy its definition", "never a copy of its contents", "Memory references and
  annotates these objects; it never mirrors them" (the generic principle's "Never copy");
  "do not overwrite it silently" ("show ... ask which to keep"); the "Examples:" label.

## Acceptance criteria

"Body" is a section's `BODY` (or `PRINCIPLE`); "doc" is `MemoryTools.<tool>.__doc__`.
Measurements use the stripped body, the stripped reference blob, or
`inspect.cleandoc(__doc__)`, with tokens as chars/4.

### US1 — Section text

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1.1 | each of the nine section modules | read its body | it equals plan.md A1-A9 (one trailing newline) |
| 1.2 | each section module | read `HEADING` | unchanged from `main` |
| 1.3 | every section text | run `tests/test_prompts_invariants.py` (file unchanged) | all pass |
| 1.4 | each per-section test file | run it | every pin listed in plan.md F1-F9 passes; each rule kept has at least one pin |
| 1.5 | overview body | count sentences | 3 to 6 |
| 1.6 | remembering body | search "override", "refusals" | absent (privacy states the override once) |
| 1.7 | curated body | read | contains "in a shared scope, follow the Scopes section on asking first" |
| 1.8 | filing body | read | contains "pass a new `description` if the fact changes what it should say"; write mechanics body contains neither "same call" nor "same write" |
| 1.9 | the nine bodies | sum stripped chars | at least 35% fewer than on `main` (9798) |

### US2 — Tool docstrings

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 2.1 | each of the seven tools | read doc | equals plan.md B1-B7 |
| 2.2 | the seven docs | search "Areas are lowercase ASCII slugs.", ".md", "is read-only" | each appears only in `get_memory_index` |
| 2.3 | `get_memory_index` doc | read | states scope/area/name with "`name` (without `.md`)", the entity segment "filled in", the slug rule, "The `system/` area is read-only.", and `capped` paging with `list_prefix(scope, area)` |
| 2.4 | each mutating tool doc | read | contains "version conflict is routine", "retry", and how to pass `expected_version` |
| 2.5 | `write_file`, `append_line`, `replace_fact` docs | read | contain "merge your change into the content it returns and retry with its version" |
| 2.6 | `delete_file` doc | read | contains "only if the file should still go" |
| 2.7 | `append_line` and `replace_fact` docs | read | each states the five metadata phrases itself (no "work as in") |
| 2.8 | every doc | read first line | one sentence ending in "." |
| 2.9 | the seven docs | sum `cleandoc` chars | at least 40% fewer than on `main` (4489) |

### US3 — Reference slots and slot guidance

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 3.1 | `tests/prompts_reference_adopter.py` | read the three blobs | equal plan.md C1-C3 |
| 3.2 | the reference seed areas | search | no "read-only", "slug", "not a fixed list", "agent-writable" |
| 3.3 | the reference systems of record | search | no "copy", "mirror" |
| 3.4 | the reference scope guidance | read | keeps the hierarchy, private/shared/who-writes per scope, ask-before-shared-write, contradiction, containment, scope test, "When in doubt, write narrow.", and the three examples |
| 3.5 | `PromptSlots.__doc__` | read | equals plan.md D; contains "Slots state only deployment facts" and still names "shared", "private", "system/" |
| 3.6 | README "Adopter configuration" | read | snippet comments and the added sentence per plan.md E |

### US4 — Tests and gate

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 4.1 | each changed test file | count `def test_` on branch vs `main` | not lower in any file |
| 4.2 | each changed or added test | read docstring | cites AIE-1165 |
| 4.3 | `tests/test_prompts_invariants.py` | `git diff main` | no change |
| 4.4 | the branch | `make check` | passes |

### US5 — Docs

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 5.1 | ADR 0025 | read | has decision 11 recording where shared mechanics live, the per-tool conflict sentence, the rejected options, and the slot guidance; decision 6's "Dropping one fact" bullet updated (plan.md E) |
| 5.1a | ADR 0022 decision 8 | read | carries a dated note pointing to ADR 0025 decision 11, original text unchanged |
| 5.2 | ARCHITECTURE.md `tools` and `prompts` entries | read | match plan.md E |
| 5.3 | `specs/AIE-1165-concise-prompts/review-pr.md` | read | has the before/after chars and tokens table recomputed from the final source |

## Out of scope

- Heading text, section order, section merges, and any change to `SECTION_ORDER`.
- Any code behavior, signature, error, or type change.
- `tests/test_prompts_invariants.py`.
- Behavioral evaluation of the prompt (Section 10.3).

## Eval scenarios (input to the later harness)

1. Host with on-demand tool loading shows only `append_line`; the write conflicts. Expected:
   the agent merges into the returned content and retries with its version.
2. User corrects a curated fact while the target writable area is in a shared scope whose
   scope guidance says to ask first. Expected: the agent asks before writing the correction.
3. User mentions a known file's subject again with a new nickname. Expected: one
   `append_line` with `aliases`, no index rescan before the append.
4. Agent wants to drop one fact line. Expected: `replace_fact` with the whole line and its
   line break as `old_string` and an empty `new_string`.
