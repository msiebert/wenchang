# Feature Specification: Product identity in the prompt and tool descriptions

**Linear issue**: AIE-1164 | **Branch**: `AIE-1164-product-identity` | **Date**: 2026-10-07

## Problem

Nothing in the assembled memory prompt or the tool descriptions says which
product the memory serves. An agent with many tools selects by the first line
of each description, and "Add one fact line to the end of an existing memory
file" does not say it is Mixpanel memory. An adopter must be able to say, in
effect: "You have memory tools for Mixpanel. Reference and save memories with
them when you work with Mixpanel."

Two surfaces, two mechanisms:

1. **System prompt**: a required `purpose` slot on `PromptSlots`, spliced as
   the opening lines of the overview section ("Memory", section 1), before the
   generic overview text.
2. **Tool descriptions**: docstrings are static, so the product cannot live in
   them. `MemoryTools` gains an optional `product` and a `descriptions()`
   method returning each docstring with the product folded into its first
   line. Hosts register tools from `descriptions()` rather than `__doc__`.

## User stories and acceptance criteria

### US1 — `purpose` slot on `PromptSlots`

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1.1 | non-blank `purpose`, `scope_guidance`, `seed_areas`, `systems_of_record` | `PromptSlots(...)` | constructs; each stored `.strip()`ped as exact `str`; `purpose` stored `"text"` from `"  text\n"` |
| 1.2 | `PromptSlots` fields | `dataclasses.fields(PromptSlots)` | names are, in order, `purpose`, `scope_guidance`, `seed_areas`, `systems_of_record`; only `systems_of_record` has a default (`None`) |
| 1.3 | positional construction | `PromptSlots("p", "g", "s")` | `purpose == "p"`, `scope_guidance == "g"`, `seed_areas == "s"`, `systems_of_record is None` |
| 1.4 | `purpose` omitted | `PromptSlots(scope_guidance="g", seed_areas="s")` | `TypeError` (missing required argument) |
| 1.5 | `purpose` whose real type is not `str` (`None`, `bytes`, `int`, an object spoofing `__class__ = str`) | construct | `TypeError("purpose must be str, not <type>")` |
| 1.6 | `purpose` a lying `str` subclass | construct | stored as exact `str` via `str.__str__` then `str.strip` |
| 1.7 | `purpose` empty or whitespace-only | construct | `ValueError("purpose must not be empty or whitespace-only")` |
| 1.8 | `purpose` with a lone surrogate | construct | `ValueError("purpose must be encodable as UTF-8")` with `__cause__` a `UnicodeEncodeError` |
| 1.9 | bad `purpose` value and a later wrong type (e.g. `purpose="  "`, `seed_areas=42`) | construct | the type error wins: `TypeError("seed_areas must be str, not int")` |
| 1.10 | two bad fields of the same kind, `purpose` first (wrong types; blank values; surrogates) | construct | `purpose` is named |
| 1.11 | a constructed `PromptSlots` | assign `purpose` | `dataclasses.FrozenInstanceError` |
| 1.12 | two slots differing only by surrounding whitespace in `purpose` | compare | equal, equal hashes; differing `purpose` text → not equal |
| 1.13 | the class docstring | read | has a ``purpose`` bullet containing "naming the product and when to use memory", listed before ``scope_guidance``; still says "Slots state only deployment facts" (both matched on whitespace-collapsed text) |

### US2 — `purpose` opens the overview section

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 2.1 | any `PromptSlots` | `build_memory_prompt(slots)` | output starts `"## Memory\n\n" + slots.purpose + "\n\n" + overview.BODY.strip() + "\n\n## Scopes"` |
| 2.2 | any slots | build | heading lines and section order are unchanged; `SECTION_ORDER` is unchanged; `"## Memory"` appears once |
| 2.3 | `overview.BODY` blank (monkeypatched) | build | the "Memory" section is still present with body exactly `slots.purpose`; no `"\n\n\n"` |
| 2.4 | `overview.BODY` monkeypatched after import | build | section 1 body is `purpose + "\n\n" + new BODY.strip()` (read at call time) |
| 2.5 | every generic section body monkeypatched non-empty | build | full output equals the per-section join with section 1 body `purpose + "\n\n" + overview body` |
| 2.6 | `overview.BODY` | read | contains no product name; `tests/test_prompts_invariants.py` is unchanged and passes |

### US3 — reference adopter fixture

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 3.1 | `tests/prompts_reference_adopter.py` | import | exports `REFERENCE_PURPOSE: Final[str]`, ASCII, every line ≤100 columns, 1-2 sentences, naming "Mixpanel" |
| 3.2 | `REFERENCE_SLOTS` | read | `REFERENCE_SLOTS.purpose == REFERENCE_PURPOSE` |
| 3.3 | `build_memory_prompt(REFERENCE_SLOTS)` | build | section "Memory" body is `REFERENCE_PURPOSE + "\n\n" + overview.BODY.strip()` |

### US4 — `product` on `MemoryTools` and `bind_tools`

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 4.1 | no `product` argument | `MemoryTools(client, identity, policy, source=s)` | `tools.product is None` |
| 4.2 | `product="Mixpanel"` | construct, or `bind_tools(..., source=s, product="Mixpanel")` | `tools.product == "Mixpanel"`; `bind_tools` without `product` gives `None` |
| 4.3 | `product="  Mixpanel \n"` or a lying `str` subclass | construct | stored as exact `str` `"Mixpanel"` (`str.__str__` then `str.strip`) |
| 4.4 | `product` whose real type is not `str` and not `None` (`int`, `bytes`, `__class__`-spoofing object) | construct | `TypeError("product must be a str or None, not <type>")` |
| 4.5 | `product` empty or whitespace-only | construct | `ValueError("product must be non-empty")` |
| 4.6 | `product` containing any `str.splitlines` boundary inside the stripped text (`\n`, `\r`, `\r\n`, `\x0b`, `\x0c`, `\x1c`, `\x1d`, `\x1e`, `\x85`, `\u2028`, `\u2029`) | construct | `ValueError("product must be one line")` |
| 4.7 | `product` with a lone surrogate | construct | `ValueError("product must be encodable as UTF-8")` with `__cause__` a `UnicodeEncodeError` |
| 4.8 | a constructed `MemoryTools` | assign `product` | `AttributeError` (read-only property) |
| 4.9 | `product` passed positionally | `MemoryTools(c, i, p, "s", "X")` or `bind_tools(c, r, cr, p, "X")` | `TypeError` (keyword-only) |
| 4.10 | `MemoryTools` tool methods | `inspect.signature` | no tool method has a `product` parameter; `tools()` is unchanged |
| 4.11 | a bad `source` and a bad `product` together | construct | the `source` error is raised (argument order) |

### US5 — `descriptions()`

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 5.1 | any `MemoryTools` | `descriptions()` | a `types.MappingProxyType`, keys `list(TOOL_NAMES)` in order, fresh on each call, read-only |
| 5.2 | `product is None` | `descriptions()` | each value equals `inspect.cleandoc(getattr(MemoryTools, name).__doc__)` |
| 5.3 | `product="Mixpanel"` | `descriptions()` | each value's first line equals the pinned form below; every line after the first equals the cleandoc'd docstring's |
| 5.4 | any product `P` | `descriptions()` | each first line equals the docstring's first line with exactly one insertion at a word boundary: `"P "` for six tools, `"P memory "` for `list_prefix` only |
| 5.5 | `product="A{b}c"` | `descriptions()` | product appears verbatim (no format interpretation) |
| 5.6 | `product="Mixpanel"` | `descriptions()` | each first line is one sentence ending in `.`, with no `". "` |
| 5.7 | `MemoryTools` tool docstrings | read | unchanged (existing AIE-1044/1151/1165 tests unchanged and passing) |

Pinned first lines with `product="Mixpanel"`:

| Tool | First line |
| ---- | ---------- |
| get_memory_index | Load the metadata index of every Mixpanel memory scope available in this session. |
| read_file | Read one Mixpanel memory file: its content, metadata, and version. |
| list_prefix | List the files in a Mixpanel memory scope or area, one page at a time, without content. |
| write_file | Create a Mixpanel memory file or replace one whole. |
| append_line | Add one fact line to the end of an existing Mixpanel memory file. |
| replace_fact | Change one fact in a Mixpanel memory file by quoting the text to replace. |
| delete_file | Delete a Mixpanel memory file. |

### US6 — documentation

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 6.1 | ADR 0026 | read | records: purpose as a required first slot (vs optional, vs its own section); product on `MemoryTools` (vs a module function, vs templating docstrings); first-line-only templating so the AIE-1165 docstring budget and pins stand; hosts register from `descriptions()`; relation to AIE-1060's MCP `instructions`; the breaking `PromptSlots` constructor change |
| 6.2 | ARCHITECTURE.md | read | `prompts` entry shows `PromptSlots(purpose, scope_guidance, seed_areas, systems_of_record=None)` and the purpose splice, and says four slots (not three); `tools` entry shows `product` and `descriptions()` and says descriptions come from `descriptions()` rather than "each described by its docstring" |
| 6.3 | README adopter section | read | example shows `PromptSlots(purpose=..., ...)`, `bind_tools(..., product="Mixpanel")`, and registering from `tools.descriptions()` |
| 6.4 | glossary | read | "Prompt slots" says four slots with `purpose` required; "Tool layer" says the description the agent sees comes from `descriptions()` |
| 6.5 | ADRs 0022 and 0025 | read | a dated note pointing to ADR 0026 where they state the constructor shape or the descriptions source; the ADR 0025 note also records that a blank `overview.BODY` no longer omits section 1 |

## Out of scope

- A host adapter or MCP server (AIE-1060). This issue provides `descriptions()`;
  AIE-1060 consumes it, and may pass `purpose` text as MCP `instructions`.
- Any change to the tool docstrings, the generic section bodies, or `SECTION_ORDER`.
- A/an article selection before the product name (templates use a fixed "a").
- Putting the product into tool results, errors, paths, or the `source` stamp.
