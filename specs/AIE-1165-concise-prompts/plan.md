# Implementation Plan: Conciseness pass over prompt sections and tool descriptions

**Linear issue**: AIE-1165 | **Branch**: `AIE-1165-concise-prompts` | **Spec**: [spec.md](spec.md)

## Summary

Prose-only change. Replace the nine generic section texts, the seven tool docstrings, the
three reference adopter slot blobs, and the `PromptSlots` class docstring with the exact
target texts below. No signature, constant name, heading, type, error, or behavior changes.
Tests first: test-writer repoints the phrase pins to the target text (section F), which makes
them fail against the current text; implementer then pastes the target text.

## Where shared tool mechanics live (hybrid)

- **Stated once, in `get_memory_index`**: what `scope`, `area`, and `name` mean (scope from
  this session, area inside it, name without `.md`), the entity segment being filled in, the
  slug rule ("Areas are lowercase ASCII slugs."), "The `system/` area is read-only.", and
  capped paging with `list_prefix(scope, area)`.
- **Per tool, self-contained**: each of the four mutating tools keeps one conflict sentence
  ("A version conflict is routine: ..."), and `write_file`, `append_line`, `replace_fact`,
  and `delete_file` each say what to pass as `expected_version`. `replace_fact` states its
  own `aliases`/`description` behavior (same wording as `append_line`), with no
  cross-reference. `read_file` keeps its read-side exception ("Any area may be read,
  including `system/`.").
- Reason: some hosts load tool schemas on demand (Claude Code loads MCP tool schemas through
  tool search), so a write tool's description can be shown without `get_memory_index`'s.
  The conflict rule is the one mechanic an agent needs at the moment a write fails.

## Constraints every target text was checked against

All texts below were machine-checked before this plan was written:
`tests/test_prompts_invariants.py` check functions (ASCII, <=100 columns, no Linear IDs, no
`.md`/`{`/"entity", real tool and parameter names in backticked calls, real snake_case
identifiers, no "organization"/"project", <=2500 chars); remembering's negative date and
metadata patterns, label set, and at-most-one fact line; curated content's US1.9
write-into-`system/` checker; privacy has no backticks or tool names; filing's forbidden
phrases (slug, lowercase, `list_prefix(scope)`, the three write tools); forgetting names
neither `write_file` nor `append_line` and has no "used to" phrasing; write_mechanics has none
of the banned mechanics terms (conflict, expected_version, version, unique, byte, ceiling,
retry, read-only, slug) and no label syntax; applying memory has at most one example marker;
systems of record keeps its five pinned words; every docstring's first line is one sentence
and every docstring line fits in 92 columns (100 minus the 8-space indent).

## Target texts (verbatim)

### A. Section bodies (`src/wenchang/prompts/<module>.py`)

Each constant is written as `NAME: Final[str] = """\` followed by the text below and a closing `"""` on its own line, so the value ends with exactly one newline. HEADING values do not change.

#### A1. `wenchang.prompts.overview.BODY` (heading "Memory")

```text
You have persistent memory: short markdown files that outlast this conversation, each addressed
by a scope, an area in that scope, and a name. Call `get_memory_index()` at the start of every
session, before you answer from memory or write to it. When a subject outgrows its file's size
limit, split it into narrower files.
```

#### A2. `wenchang.prompts.systems_of_record.PRINCIPLE` (heading "Systems of record")

```text
The systems of record listed below are the canonical home of their information. Never copy their
contents into memory. Refer to an object by its name or ID there, and store only what the system
lacks: your interpretation, how people use it, and corrections they give you. If memory disagrees
with a system of record, point out the discrepancy and ask the user which is right before you
change memory.
```

#### A3. `wenchang.prompts.applying_memory.BODY` (heading "Applying memory")

```text
Use a stored fact only if it changes the substance: what you conclude, recommend, or ask. A
detail that changes nothing reads as surveillance rather than attentiveness. Apply each fact at
the level recorded, no more broadly or certainly than its wording and confidence label support.
Never inflate a single passing mention into a trait: one late night before a deadline does not
make the user someone who always works late.
```

#### A4. `wenchang.prompts.remembering.BODY` (heading "Deciding what to remember")

```text
Give every fact line a confidence label for how you know it:

- `[stated]`: the user told you directly.
- `[observed]`: you saw it in a tool result, session data, or behavior.
- `[inferred]`: you concluded it from a pattern across several observations.

`[system]` marks curated content; never write a new `[system]` line. When you merge into or rewrite
a file, unchanged lines keep their labels; only new or changed lines get a fresh one. Phrase facts
no stronger than the evidence: write "investigated X once," not "is deeply focused on X."

Save a fact only if it would let a future session answer better, differently, or faster; otherwise
leave it out, even if true. This includes what you observe, reusable workflows, and findings, not
only what the user tells you. Skip transient content: instead of a one-off number, save the
definition or pattern behind it, if you know it.

When the user's own framing makes a fact's end date explicit, write the date into the fact line as
prose:

`- [stated] prefers JSON output, but only until the v3 migration completes on October 30.`

Never put an end date in metadata, add a per-fact timestamp, or guess an end date the user did not
state.

Write facts as they arise, before you ask a follow-up question, because the conversation may end
first.
```

#### A5. `wenchang.prompts.privacy.BODY` (heading "What never to store")

```text
The refusals below override the previous section, however useful a fact seems.

Refuse outright to store financial account numbers, health diagnoses, or anything indicating the
user is a minor: not in any file or scope, private included, even if the user states it directly
or asks you to remember it. Continue the task without it; you may tell the user it will not be kept.

Be stricter with other sensitive personal detail in a shared scope than in a private scope: a
slip there is disclosure to a team rather than a note to self, and no version history can undo
it. If unsure whether such a detail is safe for a shared scope, leave it out or write only its
non-sensitive part to a private scope. No tool filter checks for sensitive content, so a
successful write does not mean it was safe.
```

#### A6. `wenchang.prompts.filing.BODY` (heading "Filing")

```text
File each fact in the file that is about its subject, not whichever file happens to be open. Seed
areas are a starting shape; create files and areas as subjects need them.

Before creating a file, check the index's descriptions and aliases for one on the subject. If none
matches and the target area is listed under `capped`, call `list_prefix(scope, area)` for that area
only and check it the same way. If a match is ambiguous, read the top one or two candidates with
`read_file`, never the whole store. If a file on the subject exists, append to it or edit it instead
of creating a duplicate.

Descriptions and aliases are the entire search surface; there is no content search. On the same
write that records a fact, pass in `aliases` any new names the subject will be looked up by
(nicknames, acronyms, phrasings people use), and pass a new `description` if the fact changes what
it should say, so each write makes the next match more likely.
```

#### A7. `wenchang.prompts.write_mechanics.BODY` (heading "Choosing a write tool")

```text
Match the write to the change. Use `append_line` to add one fact to an existing file and
`replace_fact` to change one fact, quoting the existing line as `old_string` so surrounding lines
stay intact; this makes it mechanically impossible to disturb lines you were not editing. Use
`write_file` only for creating a file, restructuring many lines, dropping a name from `aliases`, or
rewriting the `description` with no fact to write. To drop one fact line, call `replace_fact` with
an empty `new_string` and the whole line as `old_string`, including the line break after it (or
before it, if none follows), so no blank line remains. Use `delete_file` only when the whole file
goes.
```

#### A8. `wenchang.prompts.curated_content.BODY` (heading "Curated content")

```text
The `system/` area holds curated content that a person maintains and replaces wholesale on each
refresh. It is read-only; never attempt to change it.

Correct a curated fact only when the user explicitly says it is wrong, never because of something
you observed or inferred. Record the correction as a new fact line, with its own label, in the
topical file of a writable area; in a shared scope, follow the Scopes section on asking first. Then
tell the user where you saved it. When a correction and a curated fact conflict, answer from the
correction. Because it lives outside `system/`, it survives refreshes.
```

#### A9. `wenchang.prompts.forgetting.BODY` (heading "Forgetting")

```text
Forgetting has two moves: drop one fact's line, or delete the whole file. Delete the file if the
fact was the file's only fact or the user means the whole file; if it is ambiguous which they mean,
ask before removing anything.

Removal is total: leave no note that the fact was ever true. Also drop each `[inferred]` line that
rested solely on it, delete any file derived solely from it, and remove description text or aliases
that exist only because of it. Keep anything with support of its own.

A fact whose stated end date has passed is a candidate for dropping, not to be removed
automatically: when you read it or during maintenance, drop it only if it no longer holds.

Never drop or delete anything in `system/`. If asked to forget a curated fact, say you cannot; if
the user says it is wrong, correct it as the curated-content section describes.
```

### B. Tool docstrings (`src/wenchang/tools.py`, `MemoryTools.<method>`)

Each docstring is the text below, opened with `"""` immediately followed by the first line, continuation lines indented 8 spaces in source (Python 3.13+ dedents `__doc__`), and the closing `"""` on its own line. Every source line stays within 100 columns. Line breaks inside a paragraph must fall exactly where shown, because some pins are matched against the raw `__doc__`.

#### B1. `MemoryTools.get_memory_index`

```text
Load the metadata index of every memory scope available in this session.

Call this first. Each entry gives a file's path, metadata, and version, without content.
A path has the form `scope/<entity>/area/name.md`; the other tools take `scope`, `area`,
and `name` (without `.md`), as in `read_file(scope, area, name)`, and the entity segment
is filled in for you. Areas are lowercase ASCII slugs. The `system/` area is read-only.
A prefix with more files than fit is listed under `capped` with the number omitted; page
it with `list_prefix(scope, area)`.
```

#### B2. `MemoryTools.read_file`

```text
Read one memory file: its content, metadata, and version.

Any area may be read, including `system/`.
```

#### B3. `MemoryTools.list_prefix`

```text
List the files in a scope or area, one page at a time, without content.

Each page returns entries with metadata and version, and a `next_cursor`; until it is
null, pass it back as `cursor` with the same `scope` and `area` for the next page.
```

#### B4. `MemoryTools.write_file`

```text
Create a memory file or replace one whole.

Pass `expected_version=None` to create a file, or the version you read to replace one.
`description` (one line) and `aliases` replace the stored values; they are not merged.
Content over the per-file byte ceiling is rejected with the current size and the limit;
shorten it and retry. A version conflict is routine: merge your change into the content it
returns and retry with its version.
```

#### B5. `MemoryTools.append_line`

```text
Add one fact line to the end of an existing memory file.

`line` is a single fact line with a leading bracketed label (`[stated]`, `[observed]`,
`[inferred]`, or `[system]`), as in `- [stated] Prefers tea`. Pass the version you
read as `expected_version`. The per-file byte ceiling applies to the result. Optional
`aliases` are added to the file's existing aliases and never removed (`write_file` replaces
the whole set); an optional one-line `description` replaces the stored one. A version
conflict is routine: merge your change into the content it returns and retry with its
version.
```

#### B6. `MemoryTools.replace_fact`

```text
Change one fact in a memory file by quoting the text to replace.

`old_string` must match the content exactly once; otherwise the error carries the current
content and version, so quote a unique span. `new_string` replaces it. Pass the
version you read as `expected_version`. The per-file byte ceiling applies to the result.
Optional `aliases` are added to the file's existing aliases and never removed (`write_file`
replaces the whole set); an optional one-line `description` replaces the stored one. A
version conflict is routine: merge your change into the content it returns and retry with
its version.
```

#### B7. `MemoryTools.delete_file`

```text
Delete a memory file.

Pass the version you read as `expected_version`. A version conflict is routine: retry with
the version it returns only if the file should still go.
```

### C. Reference adopter slots (`tests/prompts_reference_adopter.py`)

Each constant is written as `NAME: Final[str] = """\` followed by the text below with the closing `"""` directly after the last character (no trailing newline), as today.

#### C1. `REFERENCE_SCOPE_GUIDANCE`

```text
There are three scopes: user, project, and organization. An organization contains projects, and
a user can belong to several organizations.

- user is a private scope: it belongs to the person you are talking with and follows them
  across organizations.
- project is a shared scope, visible to every member of the current project; any member may
  write to it.
- organization is a shared scope, visible to every member of the organization; only admins and
  owners may write to it. Members who can access only some projects read it, so it holds only
  project-agnostic facts. Never write a fact about one project there.

Before saving a new fact to project or organization, ask the user and name the scope. Writes to
user need no ask. If a new fact contradicts one stored in a shared scope, show the stored fact,
say what conflicts, and ask which to keep.

Scope a fact by who it is true for, not who said it: if it would hold for a different person in
this project, use project, or organization if it holds for every project; otherwise use user.
When in doubt, write narrow. "I prefer charts with a dark background" goes in user; "This
project's weekly report goes out on Mondays" in project; "Our fiscal year starts in February"
in organization.
```

#### C2. `REFERENCE_SEED_AREAS`

```text
- user: identity, preferences, workflows, people
- project: taxonomy, metrics, entities, conventions, glossary
- organization: business-context, vocabulary

Every scope also has a `system/` area.
```

#### C3. `REFERENCE_SYSTEMS_OF_RECORD`

```text
- Event definitions live in the product's event catalog; refer to an event by its catalog name.
- Dashboards and cohorts are objects with IDs; refer to one by name and ID, and store what it is
  used for and what people have said about it.
```

### D. `PromptSlots` class docstring (`src/wenchang/prompts/slots.py`)

Replace the class docstring with exactly this (shown with its source indentation):

```python
    """Adopter-specific text inserted into the generic memory prompt.

    The generic sections refer to scope shape only as "shared scope",
    "private scope", and "the `system/` area"; these slots map that vocabulary
    onto the adopter's deployment. Slots state only deployment facts; the
    generic sections already say that areas are extensible, what the
    `system/` area means, and that systems of record are never copied.

    - ``scope_guidance``: which scopes exist, which are shared and which are
      private, who may write to each, and any ask-before-write,
      contradiction, containment, or scope-test rules, with examples.
    - ``seed_areas``: starting area names per scope, as lowercase ASCII
      slugs, and which scopes have a ``system/`` area.
    - ``systems_of_record``: optional; which systems hold canonical
      information and how to refer to their objects. None omits the whole
      systems-of-record section.

    Scope priority is not a slot; it is ``MemoryStore(scope_priority=...)``.
    Values are stored stripped as exact ``str``.
    """
```

### E. Docs (doc-updater)

- **ADR 0025 amendment.** Add decision 11, "Shared tool mechanics live in `get_memory_index`;
  conflict handling stays per tool", dated 2026-10-07, citing AIE-1165: the mechanics every
  tool shares (scope/area/name meaning, `.md` exclusion, entity filled in, slug rule,
  `system/` read-only, capped paging) are stated once in the `get_memory_index` docstring;
  each mutating tool keeps one self-contained version-conflict sentence and says what to pass
  as `expected_version`; `replace_fact` states its own `aliases`/`description` behavior.
  Rejected: (a) the overview section as the home (the invariant tests ban `.md` and "entity"
  in prompt text, and an adopter using `MemoryTools.tools()` without `build_memory_prompt`
  would lose the mechanics); (b) fully self-contained docstrings (about a 30% cut, below the
  40% target); (c) everything in `get_memory_index` including the conflict rule (a host with
  on-demand tool loading can show a write tool alone). Also record: the reference slots and
  the `PromptSlots` docstring now say slots state only deployment facts; the generic filing
  section is what presents seed areas as extensible, and the curated-content section is what
  says `system/` is read-only, so the seed-areas slot no longer repeats either (Section 8.2
  asks that seed areas be "presented to the agent as extensible"; the assembled prompt still
  does that, from generic text). Update decision 6's list of what docstrings cover so it
  matches. Keep the rest of the ADR unchanged.
- **ARCHITECTURE.md.** In the `tools` entry, after "each described by its docstring", add one
  sentence: the mechanics every tool shares are stated once, in the `get_memory_index`
  docstring, and each mutating tool's docstring keeps its own one-sentence version-conflict
  rule, since a host that loads tool schemas on demand may show it alone (link ADR 0025). In
  the `prompts` entry's "Division of labor" sentence, keep the meaning and add that slots
  state only deployment facts.
- **ADR 0022.** Decision 8 says the docstrings are part of the public contract and lists
  per-tool content this change moves. Add a dated note (2026-10-07, AIE-1165) under decision 8
  pointing to ADR 0025 decision 11 for where the shared mechanics now live; do not rewrite the
  original decision text.
- **ADR 0025 decision 6, "Dropping one fact" bullet.** Update: the write-mechanics section
  owns the line-break wording; forgetting says "drop" and defers to it.
- **README.md** "Adopter configuration": update the three snippet comments to
  `# Deployment facts only: which scopes exist, which are shared vs private,`
  `# who may write, and the ask-before-write, contradiction, containment,`
  `# and scope-test rules.` / `# Starting area names per scope.` /
  `# Optional; which systems hold canonical information. None omits the section.`
  and add one sentence to the paragraph below it: "Slots state only deployment facts: the
  generic sections already say that areas are extensible, what the `system/` area means, and
  that systems of record are never copied into memory."
- **review-pr.md** from the template, with the before/after table (section G, recomputed
  from the final source) and the criteria -> tests mapping with file:line.

### F. Test changes (test-writer)

Rules: never edit `tests/test_prompts_invariants.py`. Keep each test's intent: a pin per
rule, negative pins, and known-bad controls. The number of `def test_` functions per file
must not go down. Every changed or added test's docstring cites AIE-1165 (keep the original
issue and story ID too, e.g. "AIE-1051, US2.1; AIE-1165"). Phrase pins are matched against
the whitespace-collapsed text unless noted.

**F1. `tests/test_prompts_overview.py`**
- Rename `test_overview_body_is_four_to_six_sentences` to
  `test_overview_body_is_three_to_six_sentences`; assert `3 <= n <= 6`.
- Phrase list: drop "lowercase ASCII slug"; add "before you answer from memory or write to
  it" and "narrower files". Keep "`get_memory_index()`", "scope", "area", "name", "split".
- Add `test_overview_body_omits_tool_mechanics`: "slug" and "full address" are absent from
  the body (the `get_memory_index` docstring owns the slug rule and addressing).

**F2. `tests/test_prompts_systems_of_record.py`**: no change.

**F3. `tests/test_prompts_applying_memory.py`** phrase list becomes:
"changes the substance: what you conclude, recommend, or ask" (US2.2), "Use a stored fact only
if" (US2.3), "surveillance rather than attentiveness" (US2.4), "at the level recorded", "no
more broadly or certainly than its wording and confidence label support" (US2.5), "single
passing mention", "trait" (US2.6), "one late night before a deadline does not make the user
someone who always works late" (US2.7). `test_at_most_one_example` unchanged.

**F4. `tests/test_prompts_remembering.py`**
- Add "confidence label for how you know it" to the US2.3 list, and replace "said" with "told
  you"; keep the rest.
- US2.4 list: "curated", "marks curated content", "never write a new".
- US2.5 list: "unchanged lines keep their labels", "only new or changed lines get a fresh one".
- US3 list: "no stronger than the evidence", "evidence", the "investigated X once" pair.
- US4 list: "Save a fact only if it would let a future session answer", "better, differently,
  or faster", "otherwise leave it out, even if true", "what you observe", "workflows",
  "findings", "not only what the user tells you", "transient", "one-off number",
  "definition or pattern".
- US5.1-5.5 list: "end date", "into the fact line", "as prose", the October 30 example
  sentence (unchanged), "Never put an end date in metadata", "add a per-fact timestamp",
  "user's own framing", "end date explicit", "guess an end date the user did not state".
- US6 list: "Write facts as they arise", "before you ask a follow-up", "conversation may end".
- Add `test_body_leaves_privacy_override_to_privacy_section`: "override" and "refusals" are
  absent from the remembering body (the privacy section states the override once).
- All negative-pattern, label-set, and fact-line tests unchanged.

**F5. `tests/test_prompts_privacy.py`** phrase list becomes (ids may keep their story
prefixes): "The refusals below override the previous section" (US2.1), "Refuse outright to store" (US3.2), "however useful a fact
seems" (US2.1), "financial account numbers", "health diagnoses", "indicating the user is a
minor" (US3.1), "even if the user states it directly" (US3.2), "not in any file or scope,
private included" (US3.3), "asks you to remember it" (US3.3), "Continue the task", "will not
be kept" (US3.4), "shared scope", "private scope" (US4.1), "disclosure to a team rather than
a note to self", "version history" (US4.2), "unsure whether such a detail is safe",
"non-sensitive part" (US4.3), "No tool filter", "successful write does not mean it was safe"
(US5.1). Other tests unchanged.

**F6. `tests/test_prompts_filing.py`** phrase list becomes: "in the file that is about its subject",
"not whichever file happens to be open" (US2.1); "starting shape", "create files and areas as subjects
need them" (US2.2); "Before creating a file" (US3.1); "descriptions and aliases", "the
index's descriptions and aliases" (US3.2); "If one exists, append to it or edit it instead of creating a duplicate" (US3.3);
"ambiguous", "one or two", "`read_file`", "never the whole store" (US3.4); "If none matches",
"listed under `capped`", "`list_prefix(scope, area)`", "for that area only", "check it the
same way" (US3.5); "any new names the subject will be looked up by", "nicknames", "acronyms",
"phrasings" (US4.1); "`aliases`", "On the same write that records a fact, pass in `aliases`"
(US4.2); "entire search surface", "there is no content search", "next match more likely"
(US4.3); "pass a new `description` if the fact changes what it should say" (US4.4, moved here
from write mechanics). The US3.7 pins ("only when you create a file", "does not trigger it")
are removed: the check is scoped by "Before creating a file" (orchestrator decision 2).
`test_filing_body_omits_phrase` unchanged.

**F7. `tests/test_prompts_write_mechanics.py`**
- `test_us2_1_match_write_to_change`: unchanged ("Match the write to the change").
- `test_us2_2_*`: unchanged.
- `test_us2_3_replace_fact_changes_one_fact` list: "`replace_fact`", "`replace_fact` to change
  one fact", "quoting the existing line as `old_string`", "so surrounding lines stay intact".
- `test_us2_3_change_one_fact_sentence_names_replace_fact`: anchor "quoting the existing line".
- `test_us2_4_write_file_for_new_or_restructure` list: "`write_file`", "only for creating a
  file", "restructuring many lines". `test_us2_4_restructuring_sentence_names_write_file`:
  unchanged (anchor "restructuring many lines").
- `test_us2_5_mechanically_impossible`: unchanged.
- `test_us3_1_names_metadata_parameters`: unchanged.
- Replace `test_us3_2_metadata_on_same_call` with
  `test_us3_2_same_write_rule_lives_in_filing`: the single sentence of `filing.BODY`
  containing "pass in `aliases`" also contains "pass a new `description`" and "On the same
  write"; and "same call" and "same write" are absent from the write mechanics body.
- `test_us3_3_removal_phrases_present` list: "dropping a name from `aliases`", "rewriting the
  `description` with no fact to write". `test_us3_3_removing_alias_sentence_names_write_file`:
  anchor "dropping a name from `aliases`".
- Replace `test_us3_4_alias_sentence_names_all_write_tools` with
  `test_us3_4_every_write_tool_docstring_carries_aliases_and_description`, parametrized over
  `append_line`, `replace_fact`, `write_file`: the tool's docstring contains "`aliases`" and
  "`description`" (so adding a name never forces a full rewrite). This test passes on `main`
  too; it replaces a sentence-level pin whose subject moved to filing and the docstrings, and
  its docstring says so.
- `test_us4_2_drop_includes_line_break` list: "the line break after it", "or before it, if
  none follows".
- All other tests unchanged.

**F8. `tests/test_prompts_curated_content.py`** phrase list becomes: "`system/`", "curated",
"read-only", "never attempt", "a person maintains and replaces wholesale" (US1.2); "only when
the user explicitly says it is wrong", "observed or inferred", "never because of something
you observed or inferred" (US1.4); "new fact line", "with its own label", "topical file",
"writable area" (US1.5); "in a shared scope", "Scopes section", "asking first" (US1.6); "tell
the user where you saved it" (US1.7); "answer from the correction", "survives refreshes"
(US1.8). Add `test_body_leaves_label_set_to_remembering`: "`[system]`" is absent from the body
(the remembering section owns the label set). Checker tests unchanged.

**F9. `tests/test_prompts_forgetting.py`** phrase list becomes: "Forgetting has two moves: drop
one fact's line, or delete the whole file" (US2.1-US2.3), "whole file" (US2.3), "Delete the
file if the fact was the file's only fact" (US2.6),
"Removal is total", "leave no note that the fact was ever true" (US3.1, US3.2), "solely"
(US3.3), "`[inferred]`" (US3.4), "description text or aliases", "exist only because of it"
(US3.5), "ambiguous which they mean" (US4.1), "end date", "candidate", "not to be removed automatically",
"maintenance" (US5), "`system/`", "curated-content section", "Never drop or delete" (US6).
Add `test_forgetting_body_leaves_mechanics_to_write_section`: "line break", "`replace_fact`",
and "`delete_file`" are absent (write mechanics owns them). Other tests unchanged.

**F10. `tests/test_tools_descriptions.py`**
- `PHRASES` becomes:
  - get_memory_index: "capped", "list_prefix", "read_file(scope, area, name)",
    "list_prefix(scope, area)", "`scope`", "`area`", "`name`", ".md", "filled in",
    "Areas are lowercase ASCII slugs.", "The `system/` area is read-only."
  - read_file: "Any area may be read, including `system/`."
  - list_prefix: "scope", "area", "cursor", "next_cursor" (unchanged)
  - write_file: "expected_version=None", "the version you read", "routine", "byte ceiling",
    "current size and the limit", "description", "aliases", "not merged",
    "replace the stored values"
  - append_line: "routine", "expected_version", "byte ceiling", "single fact line",
    "leading bracketed label", "applies to the result", "[stated]", "[observed]",
    "[inferred]", "[system]"
  - replace_fact: "routine", "expected_version", "byte ceiling", "exactly once",
    "quote a unique span", "applies to the result"
  - delete_file: "routine", "expected_version", "only if the file should still go"
  The raw-`__doc__` match stays; every pinned phrase sits on one source line in the target
  text.
- `test_mutating_docstring_presents_conflict_as_merge_and_retry`: keep the name and
  `MUTATING_TOOLS` parametrization; assert "version conflict is routine" and "retry" in the
  whitespace-collapsed docstring.
  Its docstring notes that `delete_file` has no merge step (it retries only if the file should
  still go); the next test pins the merge wording for the other three.
- Add `test_merging_docstring_says_merge_and_retry`, parametrized over `write_file`,
  `append_line`, `replace_fact`: "merge your change into the content it returns and retry with
  its version" in the whitespace-collapsed docstring.
- `test_name_docstring_says_name_excludes_md`: no longer parametrized; checks
  `get_memory_index` only, same regex; docstring says the name rule is stated once there.
- `test_area_docstring_states_slug_rule`: no longer parametrized; checks `get_memory_index`
  only; docstring reworded the same way.
- Remove the now-unused `NAME_TOOLS` and `AREA_TOOLS` constants.
- Add `test_shared_mechanics_stated_once`: across the seven docstrings, "Areas are lowercase
  ASCII slugs.", ".md", and "is read-only" each appear in `get_memory_index` and in no other
  tool's docstring; "`scope` is one of the scopes" and "folder inside it" appear in no
  docstring.
- `METADATA_PHRASES` test, first-line test, entity test, and no-Linear-ID test unchanged.

**F11. `tests/prompts_reference_adopter.py`**: replace the three blobs with C1-C3 verbatim.

**F12. `tests/test_prompts_assembly.py`**
- `test_reference_scope_guidance_rules` pins: the unchanged "There are three scopes ..."
  sentence pair; "Scope a fact by who it is true for, not who said it"; "Before saving a new
  fact to project or organization, ask the user and name the scope."; "If a new fact
  contradicts one stored in a shared scope, show the stored fact, say what conflicts, and ask
  which to keep."; "Never write a fact about one project there."; "user is a private scope";
  "project is a shared scope"; "organization is a shared scope"; "When in doubt, write narrow."
- `test_reference_seed_areas_content`: keep the three line checks and "Every scope also has a
  `system/` area."; drop the "is read-only." and "not a fixed list" asserts (moved to the new
  negative test below).
- Add `test_reference_slots_state_only_deployment_facts`: seed areas contain none of
  "read-only", "slug", "not a fixed list", "agent-writable"; systems of record contain none of
  "copy", "mirror" (F14 removed a scope-guidance "slug" assert that could never fail).
- Other tests unchanged.

**F13. `tests/test_prompts_slots.py`**: add
`test_docstring_says_slots_state_only_deployment_facts`: the whitespace-collapsed
`PromptSlots.__doc__` contains "Slots state only deployment facts".

**F14. Code-review round 1 additions (AIE-1165).**
- remembering `test_body_describes_in_line_expiry`: replace the pins "Never put an end date in
  metadata", "add a per-fact timestamp", "guess an end date the user did not state" with the
  whole sentence "Never put an end date in metadata, add a per-fact timestamp, or guess an end
  date the user did not state." `test_body_states_save_criterion`: add "behind it, if you know
  it".
- privacy: replace the pin "asks you to remember it" with "even if the user states it directly
  or asks you to remember it".
- filing US3.3: the pin becomes "If a file on the subject exists, append to it or edit it
  instead of creating a duplicate".
- curated US1.8: add "When a correction and a curated fact conflict, answer from the
  correction".
- forgetting US5.2: the pin "not automatically" becomes "not to be removed automatically".
- tools descriptions: add "Pass the version you read as `expected_version`." to `PHRASES`
  for `delete_file`, `append_line`, and `replace_fact` only where it sits on one source line
  (it does for `delete_file`; check the others against B5/B6 and use the collapsed form in a
  separate assert if not).
- assembly `test_reference_slots_state_only_deployment_facts`: drop the scope-guidance "slug"
  assert (it could never fail).
- write mechanics `test_us3_4_*` docstring: describe the present state ("The filing section and
  the tool docstrings own this rule; this pins the docstring half.").

### G. Measurements (main vs this branch's source)

Chars of the stripped BODY/PRINCIPLE, the stripped reference blob, or
`inspect.cleandoc(__doc__)`; tokens are chars/4.

| Kind | Piece | Before chars | ~tok | After chars | ~tok | Cut |
|---|---|---:|---:|---:|---:|---:|
| section | `overview.BODY` | 688 | 172 | 322 | 80 | 53.2% |
| section | `systems_of_record.PRINCIPLE` | 522 | 130 | 400 | 100 | 23.4% |
| section | `applying_memory.BODY` | 627 | 157 | 423 | 106 | 32.5% |
| section | `remembering.BODY` | 1901 | 475 | 1292 | 323 | 32.0% |
| section | `privacy.BODY` | 1120 | 280 | 792 | 198 | 29.3% |
| section | `filing.BODY` | 1261 | 315 | 945 | 236 | 25.1% |
| section | `write_mechanics.BODY` | 1197 | 299 | 679 | 170 | 43.3% |
| section | `curated_content.BODY` | 1042 | 260 | 611 | 153 | 41.4% |
| section | `forgetting.BODY` | 1440 | 360 | 854 | 214 | 40.7% |
| slot | `REFERENCE_SCOPE_GUIDANCE` | 1458 | 364 | 1248 | 312 | 14.4% |
| slot | `REFERENCE_SEED_AREAS` | 504 | 126 | 195 | 49 | 61.3% |
| slot | `REFERENCE_SYSTEMS_OF_RECORD` | 391 | 98 | 239 | 60 | 38.9% |
| doc | `get_memory_index` | 599 | 150 | 553 | 138 | 7.7% |
| doc | `read_file` | 348 | 87 | 101 | 25 | 71.0% |
| doc | `list_prefix` | 400 | 100 | 241 | 60 | 39.8% |
| doc | `write_file` | 781 | 195 | 432 | 108 | 44.7% |
| doc | `append_line` | 911 | 228 | 586 | 146 | 35.7% |
| doc | `replace_fact` | 963 | 241 | 606 | 152 | 37.1% |
| doc | `delete_file` | 487 | 122 | 170 | 42 | 65.1% |
| **total** | Generic prompt text (9 bodies) | 9798 | 2450 | 6318 | 1580 | **35.5%** |
| **total** | Reference slots (3 blobs) | 2353 | 588 | 1682 | 420 | **28.5%** |
| **total** | Tool docstrings (7) | 4489 | 1122 | 2689 | 672 | **40.1%** |
assembled reference prompt after: 8228 2057
