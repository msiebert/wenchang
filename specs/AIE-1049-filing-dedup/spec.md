# Feature Specification: Filing and deduplication discipline

**Linear issue**: AIE-1049 — Filing and deduplication discipline

**Feature Branch**: `AIE-1049-filing-dedup`

**Created**: 2026-10-05

**Status**: Draft

**Input**: Linear AIE-1049: "Write the instruction text covering: a fact goes
in the file it's about, not whichever file is open (domain filing); before
creating a new file, scan loaded descriptions/aliases for an existing match
and prefer appending or editing over duplicating, reading one or two
candidates to confirm an ambiguous match (deduplication as a write-time
discipline, off the metadata index only); every write adds
nicknames/acronyms/phrasings the subject will later be looked up by (alias
upkeep). Reference: Notion §8.1."

## Source text (Notion)

§8.1, verbatim:

> Domain filing. A fact goes in the file that is about it, not whichever
> file happens to be open from earlier in the session. Seed areas are a
> starting shape; the agent creates its own files and areas as needed.
>
> Deduplication, as a write-time discipline. Body search is excluded
> deliberately: it would fan a read across every file in every scope on
> every write. Deduplication therefore runs off the metadata index already
> loaded at session start. Before creating a new file the agent scans
> loaded descriptions and aliases for an existing file on the subject, and
> prefers appending or editing to creating a duplicate. Where the index
> match is ambiguous it reads the top one or two candidates to confirm,
> never the whole store. This applies only at file creation; appends to a
> known file do not trigger it.
>
> Alias upkeep. Every write adds the nicknames, acronyms, and phrasings the
> subject will later be looked up by, so each write makes the next match
> more likely.

§4: "Metadata is the entire search surface. With no content search,
description and aliases are the only means by which a later mention finds
an existing file instead of spawning a duplicate."

## Summary

Fill `src/wenchang/prompts/filing.py` `BODY` (heading "Filing", section 8 of
`build_memory_prompt()`) with prose covering domain filing, deduplication at
file creation off the index, and alias upkeep. No other `src/` change. One
new test file, `tests/test_prompts_filing.py`, pins the load-bearing tokens.

Binding cross-issue decisions (wave 2 addendum):
- Decision 1: aliases ride on the same `append_line` / `replace_fact` call
  (or `write_file` when creating or restructuring); removing an alias is a
  `write_file`. This section states the rule and why; the write-tool
  section (AIE-1051) states which tool carries what. No tool mechanics
  beyond naming the call that carries `aliases` and that removing an alias
  is a `write_file`.
- Decision 4: if the relevant area is listed as capped in the index, one
  `list_prefix(scope, area)` on that area only, never the whole store.

## User stories and acceptance criteria

Phrase matching normalizes runs of whitespace to one space, so wrapping
never breaks a pin.

### US1 — Section present

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1.1 | `wenchang.prompts.filing` | imported | `HEADING == "Filing"`; `BODY.strip()` is non-empty |
| 1.2 | `BODY` | measured | `len(BODY) <= 2000` (well under the 2500 invariant); the shared invariant tests (ASCII, <= 100 cols, tool names) also apply |
| 1.3 | a valid `PromptSlots` | `build_memory_prompt(slots)` | output contains `"## Filing\n\n" + filing.BODY.strip()` |

### US2 — Domain filing

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 2.1 | `BODY` | read | says a fact goes in the file about its subject: contains `file that is about` and `not in whichever file` |
| 2.2 | `BODY` | read | says seed areas are a starting shape and the agent creates files and areas as needed: contains `starting shape` and `new files and areas` |
| 2.3 | `BODY` | read | does not restate the overview's slug rule: no `slug`, no `lowercase` |

### US3 — Deduplication at file creation, off the index

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 3.1 | `BODY` | read | dedup runs before creating a file: contains `Before you create a new file` |
| 3.2 | `BODY` | read | scans descriptions and aliases in the already-loaded index: contains `descriptions and aliases`, `the index you loaded`, `` `get_memory_index()` `` |
| 3.3 | `BODY` | read | prefers appending/editing to duplicating: contains `append to it or edit it` and `creating a duplicate` |
| 3.4 | `BODY` | read | ambiguous match: read one or two top candidates with `read_file`, never the whole store: contains `ambiguous`, `one or two`, `` `read_file` ``, `never the whole store` |
| 3.5 | `BODY` | read | no index match and the area is capped: one `list_prefix(scope, area)` on that area only: contains `If nothing there matches`, ``listed under `capped` in the index``, `` `list_prefix(scope, area)` ``, `that one area only`, `check its entries the same way` |
| 3.6 | `BODY` | read | never instructs a whole-scope listing: no `` `list_prefix(scope)` `` |
| 3.7 | `BODY` | read | dedup applies only at creation; appends to a known file do not trigger it: contains `only when you create a file` and `does not trigger it` |

### US4 — Alias upkeep

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 4.1 | `BODY` | read | every write carries any new names the subject will be looked up by: contains `Every write should carry any new names`, `nicknames`, `acronyms`, `phrasings` |
| 4.2 | `BODY` | read | aliases go on the same `append_line`/`replace_fact` call, or in `write_file` when creating or restructuring: contains `` `aliases` ``, `` `aliases` on the same `append_line` or `replace_fact` call ``, `` `append_line` ``, `` `replace_fact` ``, ``in `write_file` when you create or restructure`` |
| 4.3 | `BODY` | read | the reason: contains `entire search surface` |
| 4.4 | `BODY` | read | removing an alias is a `write_file`: contains ``Removing an alias is a `write_file` `` |

## Behavioral evaluation scenarios (Notion §10.3; not executed)

1. Mid-session the agent has been working in a file about one customer; the
   user mentions a fact about a different customer. Expected: the fact goes
   to that customer's file (appended, or a new file after the dedup check),
   not the open one.
2. The user says "the Q4 board deck is due Friday"; the index has a file
   whose aliases include "board deck". Expected: `append_line` to that
   file, no new file, no `read_file` of unrelated files.
3. The user mentions "Atlas"; two index entries plausibly match by
   description. Expected: `read_file` on at most two candidates, then
   append to the confirmed one, or create a new file if neither matches.
4. The target area appears under `capped` in the index and no loaded entry
   matches. Expected: `list_prefix(scope, area)` on that area only (paged
   with `cursor` if needed), never `list_prefix(scope)`, then decide.
5. The user calls a known subject by a new acronym while adding a fact.
   Expected: `append_line` with the acronym in `aliases` on the same call,
   not a separate `write_file`.

## Out of scope

- Any change outside `filing.BODY`, `tests/test_prompts_filing.py`, and this
  spec dir (no assembler, slots, invariant-test, ARCHITECTURE, ADR, or
  glossary change; "Aliases" is already in the glossary).
- Which write tool fits which change, conflict handling, fact-line syntax,
  labels, and description wording (AIE-1050, AIE-1051, tool docstrings).
- Scope choice and ask-before-write rules (adopter `scope_guidance` slot).
- Executed behavioral evaluation (§10.3).
