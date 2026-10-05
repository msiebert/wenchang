# Feature Specification: Prompt layer skeleton and adopter slots

**Linear issue**: AIE-1055 — Configurable slots: scope guidance, seed areas,
scope priority order, systems-of-record

**Feature Branch**: `AIE-1055-prompt-slots`

**Created**: 2026-10-05

**Status**: Draft

**Input**: Notion spec §8 (prompt layer), §8.2 (configurable slots), §9
(reference adopter configuration), §10.3 (prompt behavior is evaluated, not
unit-tested); milestone 4 design doc ("`wenchang.prompts`").

## Summary

Add the `wenchang.prompts` subpackage: the splicing mechanism that turns
library-owned section text plus three adopter-supplied text slots into one
markdown prompt. This issue creates every section module (final heading,
empty body for sections owned by AIE-1049..1054), writes the two pieces of
prose it owns (the overview and the generic systems-of-record principle),
defines `PromptSlots` and its validation, and documents that scope priority
order is configuration on `MemoryStore`, not prompt text.

Public API (`wenchang.prompts.__all__`): `PromptSlots`, `SECTION_ORDER`,
`build_memory_prompt`. Section modules are importable but not exported;
their wording is not API.

## Decisions settled before this spec (2026-10-05)

- `systems_of_record` is optional; when `None` the whole section (principle
  and list) is omitted. (Human decision.)
- Adopters cannot omit, reorder, or override generic sections; only the
  three slots are adopter-supplied. (Orchestrator default, flagged.)
- The overview section is owned by this issue. (Orchestrator default.)
- Scope priority order lives on `MemoryStore(scope_priority=...)` (already
  implemented); this issue adds no code for it, only docs.

## User stories and acceptance criteria

### US1 — PromptSlots validation (`tests/test_prompts_slots.py`)

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1.1 | three non-blank `str` values | `PromptSlots(scope_guidance=a, seed_areas=b, systems_of_record=c)` | constructs; each field equals the input `.strip()`ped |
| 1.2 | `systems_of_record` omitted, or passed as `None` | construct | field is `None` |
| 1.3 | `scope_guidance` or `seed_areas` whose real type is not `str` (`None`, `bytes`, `int`, an object whose `__class__` is spoofed to `str`) | construct | `TypeError("<field> must be str, not <TypeName>")` |
| 1.4 | `systems_of_record` whose real type is neither `str` nor `NoneType` (`bytes`, `int`, spoofed `__class__`) | construct | `TypeError("systems_of_record must be str or None, not <TypeName>")` |
| 1.5 | a `str` subclass value (with `__str__`/`strip` overridden to lie) | construct | stored value's type is exactly `str`, normalized via `str.__str__` then `str.strip` |
| 1.6 | `"  text\n"` | construct | stored as `"text"` |
| 1.7 | `""`, `"   "`, `"\n\t "` for any field (`systems_of_record` as a `str`) | construct | `ValueError("<field> must not be empty or whitespace-only")` |
| 1.8 | a value containing a lone surrogate (`"a\ud800b"`) | construct | `ValueError("<field> must be encodable as UTF-8")` with `__cause__` a `UnicodeEncodeError` |
| 1.9 | a wrong type in a later field and a blank earlier field | construct | `TypeError` (every type check runs, in field order, before any value check) |
| 1.10 | two bad fields of the same kind | construct | the error names the first in field order (`scope_guidance`, `seed_areas`, `systems_of_record`) |
| 1.11 | a constructed `PromptSlots` | assign to any field | `dataclasses.FrozenInstanceError` |
| 1.12 | two `PromptSlots` built from equal (post-strip) text | compare / hash | equal, equal hashes |
| 1.13 | `PromptSlots.__doc__` | read | states the vocabulary contract: contains `shared`, `private`, and `system/` |

### US2 — Section modules and SECTION_ORDER (`tests/test_prompts_assembly.py`)

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 2.1 | `wenchang.prompts` | import | `__all__ == ["PromptSlots", "SECTION_ORDER", "build_memory_prompt"]`, each resolvable |
| 2.2 | `SECTION_ORDER` | read | exactly `("overview", "scope_guidance", "seed_areas", "systems_of_record", "applying_memory", "remembering", "privacy", "filing", "write_mechanics", "curated_content", "forgetting")` |
| 2.3 | each id in `SECTION_ORDER` except `scope_guidance` and `seed_areas` | import `wenchang.prompts.<id>` | the module exists and has a non-empty `str` `HEADING`; `systems_of_record` has `PRINCIPLE` (no `BODY`), every other has `BODY` |
| 2.4 | all eleven headings (nine section `HEADING`s plus `assemble.SCOPE_GUIDANCE_HEADING`, `assemble.SEED_AREAS_HEADING`) | read | each non-empty and all distinct; exact values pinned only for the four this issue owns: `overview.HEADING == "Memory"`, `SCOPE_GUIDANCE_HEADING == "Scopes"`, `SEED_AREAS_HEADING == "Seed areas"`, `systems_of_record.HEADING == "Systems of record"` (later issues may retitle their own sections without touching shared tests) |

### US3 — build_memory_prompt (`tests/test_prompts_assembly.py`)

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 3.1 | valid slots | `build_memory_prompt(slots)` | returns an exact `str` |
| 3.2 | the same slots | call twice | identical output |
| 3.3 | a non-`PromptSlots` argument (`None`, a `dict`, an object spoofing `__class__`) | call | `TypeError("slots must be PromptSlots, not <TypeName>")` |
| 3.4 | slots passed by keyword | call | `TypeError` (positional-only) |
| 3.5 | every section body set non-empty (monkeypatched) and SoR slot present | call | output is exactly `"\n\n".join(f"## {heading}\n\n{body}" for each id in SECTION_ORDER) + "\n"`, bodies `.strip()`ped; each heading appears once as a `## ` line, in `SECTION_ORDER` order |
| 3.6 | a section module whose `BODY` is `""` or whitespace-only (monkeypatched) | call | that section's heading does not appear; no extra blank lines |
| 3.7 | valid slots | call | `slots.scope_guidance` appears verbatim directly under `## Scopes`; `slots.seed_areas` directly under `## Seed areas` |
| 3.8 | `systems_of_record="X"` | call | section body is `PRINCIPLE.strip() + "\n\n" + "X"` under `## Systems of record` |
| 3.9 | `systems_of_record=None` | call | neither the SoR heading nor any sentence of `PRINCIPLE` (split with the sentence splitter below) appears |
| 3.10 | any slots | call | output starts with `"## Memory\n\n"` (no H1), ends with exactly one `"\n"` (not `"\n\n"`) |
| 3.11 | section bodies changed at runtime (monkeypatch) | call | output reflects them (bodies are read at call time) |

Regex note: inside the US5 table, `\|` is markdown escaping for a table
pipe. The real patterns are `r"\bentit(y|ies)\b"` (5.4) and
`r"\b(organizations?|projects?)\b"` (5.7), both with `re.IGNORECASE`.

Sentence splitter (used by 3.9 and 4.1): collapse runs of whitespace to one
space, then `re.split(r"(?<=[.!?])\s+", text.strip())`, dropping empty items.

### US4 — Owned prose (`tests/test_prompts_overview.py`, `tests/test_prompts_systems_of_record.py`)

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 4.1 | `overview.BODY` | read | non-empty; 4-6 sentences; contains `` `get_memory_index()` ``, `scope`, `area`, `name`, `lowercase ASCII slug`, `split` |
| 4.2 | `systems_of_record.PRINCIPLE` | read | non-empty; contains `canonical`, `interpretation`, `correction`, `discrepancy`, `copy` |

### US5 — Text invariants (`tests/test_prompts_invariants.py`)

Parametrized over every module discovered under `wenchang.prompts` (via
`pkgutil.iter_modules`) except `assemble` and `slots`, and over every
module-level `str` constant whose name is all-caps (`HEADING`, `BODY`,
`PRINCIPLE`, and any later addition), plus the slot heading constants in
`assemble`. Empty strings pass trivially.

| # | Then |
| - | ---- |
| 5.1 | the discovered section modules are exactly the nine in plan.md (catches a stray or missing module) |
| 5.2 | every text is ASCII (`str.isascii()`) and every line is <= 100 characters |
| 5.3 | no file under `src/wenchang/prompts/` contains `AIE-\d+` |
| 5.4 | no text contains the substring `.md`, the substring `{`, a match of `\S+/\S+\.md`, or a match of `re.search(r"\bentit(y\|ies)\b", text, re.I)` (so "identity" is allowed); a bare `system/` is allowed |
| 5.5 | every match of ``re.finditer(r"`([a-z][a-z0-9_]*)\(([^`]*)\)`", text)`` has group 1 in `TOOL_NAMES`; its args are `[a.strip() for a in group2.split(",") if a.strip()]` (so `get_memory_index()` has none), and each arg is exactly `...` or matches `^([a-z_][a-z0-9_]*)(\s*=.*)?$` with group 1 a parameter name of `MemoryTools.<name>`, read from `inspect.signature` at test time (never hardcoded) |
| 5.6 | every match of ``re.finditer(r"`([a-z][a-z0-9]*(?:_[a-z0-9]+)+)`", text)`` (a whole backticked snake_case identifier with at least one `_`) is in the allowed set, computed at test time: `TOOL_NAMES`; every tool parameter name; every key of `render_result` for a sample `MemoryFile` and `ListPage` (full metadata, non-null `next_cursor`) and a `MemoryIndex` with one `CappedPrefix`; every key of `render_error` for a sample `ReplaceFactMatchError` and `RestrictedScopeError(..., ROLE_REQUIRED, required_roles=...)`; and the `.value` of every member of `RestrictionReason`, `NotFoundReason`, `TransientReason`, `ErrorCategory`, and `ConfidenceLabel` |
| 5.7 | no match of `re.search(r"\b(organizations?\|projects?)\b", text, re.I)` |
| 5.8 | every text is <= 2500 characters |
| 5.9 | every module under `wenchang.prompts` (including `__init__`, `assemble`, `slots`) imports from `wenchang` only `wenchang.prompts` submodules (ast scan; relative imports allowed) |

### US6 — Reference adopter fixture (`tests/prompts_reference_adopter.py`, used by `tests/test_prompts_assembly.py`)

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 6.1 | `REFERENCE_SLOTS` (§9 rendered as three blobs, text in plan.md; constants have no leading/trailing whitespace) | `build_memory_prompt(REFERENCE_SLOTS)` | succeeds; each `REFERENCE_SLOTS.<field>` appears verbatim directly under its heading |
| 6.2 | the fixture blobs | read | scope guidance contains the hierarchy sentence, the scope-test sentence, the ask-before-shared-write rule, the contradiction rule, and the containment rule; seed areas lists each scope's areas, marks `system` read-only, and says the list is extensible; systems of record names the event catalog, dashboards, cohorts |
| 6.3 | `REFERENCE_SLOTS` with `systems_of_record=None` (`dataclasses.replace`) | build | SoR section omitted |
| 6.4 | `REFERENCE_SCOPE_PRIORITY` (`("user", "project", "organization")`) | `MemoryStore(InMemoryStorage(), scope_priority=REFERENCE_SCOPE_PRIORITY)` | constructs; `scope_priority` property equals it |

### US7 — Docs

| # | Then |
| - | ---- |
| 7.1 | ARCHITECTURE.md: `prompts (planned)` bullet replaced with the implemented description (public names, `SECTION_ORDER`, slot validation, omit-empty rule, vocabulary contract, imports nothing from `wenchang` outside the package, scope priority on `MemoryStore`, docstrings own mechanics / prompt owns judgment); bird's-eye module count and the diagram note updated |
| 7.2 | `docs/product/glossary.md`: new "Prompt slots" entry (`prompts.PromptSlots`, the three slots, SoR optional); existing "Seed areas" and "Systems of record" entries cross-link to `PromptSlots`; "Scope priority" notes it is `MemoryStore(scope_priority=...)`, configuration not prompt text, default flat |
| 7.3 | README: adopter section showing `build_memory_prompt(PromptSlots(...))` and `MemoryStore(scope_priority=...)` with the §9 order |
| 7.4 | ADR 0025 "Prompt layer: generic section text and adopter slots" records the ten design decisions, the two 2026-10-05 decisions, and that the overview owns the "split rather than bloat" point (later sections refer to it rather than restating it) |
| 7.5 | No Linear IDs in `src/`; test docstrings cite AIE-1055 |

## Behavioral eval scenarios (input for a later harness, §10.3)

1. Session start, empty conversation: agent calls `get_memory_index()` before any other memory tool.
2. Reference adopter, user says "our fiscal year starts in February": agent asks before writing to the organization (shared) scope.
3. Reference adopter, user restates an event's definition that differs from the catalog: agent does not store a copy; it surfaces the discrepancy.
4. A subject's file nears the size limit: agent creates a narrower file instead of appending.
5. Slots with `systems_of_record=None`: no SoR guidance appears; agent behavior otherwise unchanged.

## Out of scope

- Prose for the seven generic sections owned by AIE-1049..1054.
- Any change to `tools.py`, `core.py`, or other existing modules.
- Adopter override/omission of generic sections.
- Policing slot content beyond type, blank, and UTF-8 checks.
