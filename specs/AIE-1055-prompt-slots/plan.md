# Implementation Plan: Prompt layer skeleton and adopter slots

**Linear issue**: AIE-1055 | **Branch**: `AIE-1055-prompt-slots` | **Date**: 2026-10-05 | **Spec**: [spec.md](spec.md)

## Summary

New subpackage `src/wenchang/prompts/`. No change to any existing module.
Tests in five new files plus one fixture module. Docs: ARCHITECTURE.md,
README.md, glossary, ADR 0025.

## Technical Context

Python >= 3.12; pyright strict; ruff (E, F, I, UP, B, SIM, RUF), line length
100. Stdlib only (`dataclasses`, `typing`, `collections.abc`). No new
dependency, no packaging change (hatchling already packages every `.py`
under `src/wenchang`).

## Constitution Check

| Principle | Status |
| --------- | ------ |
| I. Tests-first | T1, T2 each test-writer then implementer |
| II. Tests not negotiable | No existing test touched |
| V. Storage via interface | Not touched |
| VI. Spec fidelity | §8.2 implemented; deviations (SoR optional, scope priority not in prompts) in ADR 0025 |
| VII. Architecture documented | ARCHITECTURE.md + ADR 0025 (T3) |
| VIII. Traceability | Test docstrings cite AIE-1055; no Linear IDs in `src/` |

## Module layout

```
src/wenchang/prompts/
  __init__.py          # re-exports PromptSlots, SECTION_ORDER, build_memory_prompt; __all__
  slots.py             # PromptSlots
  assemble.py          # SECTION_ORDER, SCOPE_GUIDANCE_HEADING, SEED_AREAS_HEADING,
                       # build_memory_prompt
  overview.py          # HEADING, BODY (prose below)
  systems_of_record.py # HEADING, PRINCIPLE (prose below; no BODY)
  applying_memory.py   # HEADING, BODY = ""
  remembering.py       # HEADING, BODY = ""
  privacy.py           # HEADING, BODY = ""
  filing.py            # HEADING, BODY = ""
  write_mechanics.py   # HEADING, BODY = ""
  curated_content.py   # HEADING, BODY = ""
  forgetting.py        # HEADING, BODY = ""
```

Every module has a one-line module docstring. Imports from `wenchang` are
only `wenchang.prompts.*` (absolute or relative). Section constants are
`Final[str]`. Prose is flush-left in a triple-quoted string starting
`"""\`, markdown, ASCII only, lines <= 100 columns.

## Headings (exact)

The first four are owned by this issue and pinned by tests; the other seven
are initial values their owning issues may retitle (tests pin only that all
eleven are non-empty and distinct).

| Module / constant | `HEADING` |
| ----------------- | --------- |
| `overview.HEADING` | `Memory` |
| `assemble.SCOPE_GUIDANCE_HEADING` | `Scopes` |
| `assemble.SEED_AREAS_HEADING` | `Seed areas` |
| `systems_of_record.HEADING` | `Systems of record` |
| `applying_memory.HEADING` | `Applying memory` |
| `remembering.HEADING` | `Deciding what to remember` |
| `privacy.HEADING` | `What never to store` |
| `filing.HEADING` | `Filing` |
| `write_mechanics.HEADING` | `Choosing a write tool` |
| `curated_content.HEADING` | `Curated content` |
| `forgetting.HEADING` | `Forgetting` |

## Owned prose (exact; implementer copies verbatim)

`overview.BODY`:

```
You have persistent memory: short markdown files that outlast this conversation, each addressed
by a scope, an area inside that scope, and a name. Call `get_memory_index()` at the start of
every session, before you answer from memory or write to it; it returns an index of the stored
files, with their descriptions and aliases. Areas are lowercase ASCII slugs, and you never type
a full address, only the scope, area, and name. Each file has a size limit, so when a subject
outgrows its file, split it into narrower files rather than letting one file bloat. The tools
only store and fetch text; the sections that follow say what is worth remembering, where it
goes, and when to ask first.
```

`systems_of_record.PRINCIPLE`:

```
Some information already has a canonical home in the product you work in; the list below
names those systems of record. Do not copy their contents into memory. Refer to the canonical
object by the name or ID it has there, and store only what that system does not hold: your
interpretation of it, how people use it, and corrections they have given you. If memory
disagrees with the system of record, do not let the two diverge silently: point out the
discrepancy to the user and ask which is right before you change memory.
```

## `slots.py`

```python
@dataclass(frozen=True)
class PromptSlots:
    scope_guidance: str
    seed_areas: str
    systems_of_record: str | None = None

    def __post_init__(self) -> None: ...
```

`__post_init__` order:

1. Type checks, in field order `scope_guidance`, `seed_areas`,
   `systems_of_record`, all before any value check. Real type via
   `issubclass(type(cast(object, v)), str)` (never `isinstance`, which a
   spoofed `__class__` fools; the `cast` keeps pyright strict quiet, as in
   `tools.py`). `systems_of_record` also accepts `type(v) is
   NoneType` (`v is None`). Messages:
   - `TypeError(f"{field} must be str, not {name}")`
   - `TypeError(f"systems_of_record must be str or None, not {name}")`
   where `name` is `type(v).__name__` read through a guard returning
   `"<unnamed>"` if reading it raises (normalized with `str.__str__`).
2. Per `str` field in field order: `value = str.strip(str.__str__(v))`
   (exact `str`, unaffected by subclass overrides); then
   - empty -> `ValueError(f"{field} must not be empty or whitespace-only")`
   - `value.encode("utf-8")` raising `UnicodeEncodeError` ->
     `ValueError(f"{field} must be encodable as UTF-8")` raised `from` that
     exception;
   - store with `object.__setattr__(self, field, value)`.

Equality and hashing are the dataclass defaults. Docstring (class): what
each slot holds, and the vocabulary contract: generic sections speak of
scope shape only as "shared scope", "private scope", and "the `system/`
area", so `scope_guidance` must say which of the adopter's scopes are
shared and which are private (plus ask-before-write, contradiction, and
containment rules and examples); `seed_areas` lists starting areas per
scope as lowercase ASCII slugs, marks which are curated `system/` areas
(read-only to the agent) and which are agent-writable, and presents the
list as extensible; `systems_of_record` is optional, and `None` omits the
whole systems-of-record section. Scope priority is not a slot: it is
`MemoryStore(scope_priority=...)`.

## `assemble.py`

```python
SECTION_ORDER: Final[tuple[str, ...]] = (
    "overview",
    "scope_guidance",
    "seed_areas",
    "systems_of_record",
    "applying_memory",
    "remembering",
    "privacy",
    "filing",
    "write_mechanics",
    "curated_content",
    "forgetting",
)
SCOPE_GUIDANCE_HEADING: Final[str] = "Scopes"
SEED_AREAS_HEADING: Final[str] = "Seed areas"


def build_memory_prompt(slots: PromptSlots, /) -> str: ...
```

- `issubclass(type(slots), PromptSlots)` false ->
  `TypeError(f"slots must be PromptSlots, not {name}")` (guarded name as
  above).
- A private `_SECTIONS: Mapping[str, Callable[[PromptSlots], tuple[str,
  str]]]` maps each id to a function returning `(heading, body)`. Generic
  ids read `module.HEADING` and `module.BODY` **at call time** (attribute
  lookup on the imported module object, so monkeypatching a module's
  `BODY` changes the output). `scope_guidance` -> `(SCOPE_GUIDANCE_HEADING,
  slots.scope_guidance)`; `seed_areas` -> `(SEED_AREAS_HEADING,
  slots.seed_areas)`; `systems_of_record` -> `(systems_of_record.HEADING,
  systems_of_record.PRINCIPLE.strip() + "\n\n" + slots.systems_of_record)`
  when the slot is a `str`, else body `""`.
- At import, if `tuple(_SECTIONS) != SECTION_ORDER`, raise `RuntimeError`
  (no bare `assert`). Defensive and untested by design: it can only fire
  on an edit to this module, which the assembly tests would catch anyway.
- Output: for each id in `SECTION_ORDER`, `body = body.strip()`; skip if
  `body == ""`; else part `f"## {heading}\n\n{body}"`. Return
  `"\n\n".join(parts) + "\n"`. No H1. Pure: no I/O.

## `__init__.py`

Module docstring; imports `PromptSlots` from `slots`, `SECTION_ORDER` and
`build_memory_prompt` from `assemble`; `__all__ = ["SECTION_ORDER",
"PromptSlots", "build_memory_prompt"]` (RUF022 order). Nothing added to
`wenchang/__init__.py`.

## Test fixture `tests/prompts_reference_adopter.py` (exact text)

Imported with a bare `from prompts_reference_adopter import ...` (`tests/`
has no `__init__.py`). Module docstring cites AIE-1055 and Notion §9 and
says it is illustrative adopter configuration, not library code. Constants:
`REFERENCE_SCOPE_GUIDANCE`, `REFERENCE_SEED_AREAS`,
`REFERENCE_SYSTEMS_OF_RECORD` (all `Final[str]`), `REFERENCE_SLOTS:
Final[PromptSlots]` built from them, and `REFERENCE_SCOPE_PRIORITY:
Final[tuple[str, ...]] = ("user", "project", "organization")`. Each blob
constant is written so it has no leading or trailing whitespace (e.g.
`"""\` ... text`"""` with the closing quotes on the last text line, or
`.strip()` applied in the constant).

`REFERENCE_SCOPE_GUIDANCE`:

```
There are three scopes: user, project, and organization. An organization contains projects,
and a user can belong to several organizations.

- user is a private scope. It belongs to the person you are talking with and follows them
  across organizations.
- project is a shared scope, visible to every member of the current project. Any member may
  write to it.
- organization is a shared scope, visible to every member of the organization. Only admins
  and owners may write to it.

Before saving a new fact to a shared scope (project or organization), ask the user first and
say which scope you intend to use. Writes to the private user scope need no ask.

If a new fact contradicts one already stored in a shared scope, do not overwrite it silently:
show the stored fact, say what conflicts with it, and ask which to keep.

Organization scope is readable by members who can access only some projects, so it holds only
project-agnostic facts. Never write a fact about one project there.

Scope test: scope a fact by who it is true for, not who said it. Would this still be true if a
different person opened this project? If yes, it belongs in project, or in organization if it
holds for every project; if no, it belongs in user. When in doubt, write narrow.

Examples:
- "I prefer charts with a dark background" goes in user.
- "This project's weekly report goes out on Mondays" goes in project.
- "Our fiscal year starts in February" goes in organization.
```

`REFERENCE_SEED_AREAS`:

```
Each scope starts with the areas below. They are a starting point, not a fixed list: create a
new area, named as a lowercase slug, whenever none of these fits.

- user: identity, preferences, workflows, people
- project: taxonomy, metrics, entities, conventions, glossary
- organization: business-context, vocabulary

Every scope also has a `system/` area. It holds curated content maintained for you and is
read-only. Every other area is agent-writable, subject to each scope's write rules under
Scopes.
```

`REFERENCE_SYSTEMS_OF_RECORD`:

```
- Event definitions live in the product's event catalog. Refer to an event by its catalog
  name; do not copy its definition into memory.
- Dashboards and cohorts are real objects with IDs. Refer to one by its name and ID, and store
  what it is used for and what people have said about it, never a copy of its contents.

Memory references and annotates these objects; it never mirrors them.
```

## Test files

- `tests/test_prompts_slots.py` — US1.
- `tests/test_prompts_assembly.py` — US2, US3, US6.
- `tests/test_prompts_overview.py` — US4.1.
- `tests/test_prompts_systems_of_record.py` — US4.2.
- `tests/test_prompts_invariants.py` — US5. Text set: for each discovered
  section module, every module attribute whose name is all-caps and whose
  value is a `str`; plus `assemble.SCOPE_GUIDANCE_HEADING` and
  `assemble.SEED_AREAS_HEADING`. Test IDs `module.CONSTANT`. Tool names
  from `wenchang.tools.TOOL_NAMES`; parameters from
  `inspect.signature(getattr(MemoryTools, tool)).parameters` minus `self`;
  agent-visible keys from `render_result` of a sample `MemoryFile`,
  `ListPage`, and `MemoryIndex` with one `CappedPrefix`, and
  `render_error` of a `ReplaceFactMatchError` and a
  `RestrictedScopeError(..., ROLE_REQUIRED, required_roles=...)`.

Every test module has `pytestmark = pytest.mark.unit` and a docstring
citing AIE-1055 and the US numbers it covers.

## Files

- `src/wenchang/prompts/*.py` (12 files)
- `tests/test_prompts_*.py` (5 files), `tests/prompts_reference_adopter.py`
- `ARCHITECTURE.md`, `README.md`, `docs/product/glossary.md`,
  `docs/adr/0025-prompt-layer-sections-and-slots.md`
