# PR Review: AIE-1055 — Prompt layer skeleton and adopter slots

## What changed & why

Milestone 4 needs a place for the prompt text that sits on top of the
tools (Notion §8). This PR adds that place, the new subpackage
`src/wenchang/prompts/`, so AIE-1049..1054 can then write their sections in
parallel, each editing one module. Public API (`__all__`): `SECTION_ORDER`,
`PromptSlots`, and `build_memory_prompt(slots, /) -> str`.

- `PromptSlots(scope_guidance, seed_areas, systems_of_record=None)` is a
  frozen dataclass holding the three adopter text blobs from §8.2. All type
  checks run before any value check, in field order. A non-`str` real type
  raises `TypeError`. Values are normalized to an exact stripped `str`. A
  blank or non-UTF-8 value raises `ValueError`.
- Nine section modules, each holding `Final[str]` constants. `overview`
  (`HEADING`, `BODY`) and `systems_of_record` (`HEADING`, `PRINCIPLE`) carry
  the prose this issue owns. `applying_memory`, `remembering`, `privacy`,
  `filing`, `write_mechanics`, `curated_content`, and `forgetting` have
  their headings and an empty `BODY`.
- `build_memory_prompt` renders each section in the fixed `SECTION_ORDER`
  as `## {heading}\n\n{body}`, joined by blank lines and ending in one
  newline, with no H1. Empty bodies are omitted. When
  `systems_of_record` is `None`, the whole systems-of-record section
  (principle included) is omitted.
- Scope priority gets no new code: it is already
  `MemoryStore(scope_priority=...)`. This PR documents it.
- The §9 reference adopter ships as a test fixture,
  `tests/prompts_reference_adopter.py`.

No existing module or test changed. `prompts` imports nothing from
`wenchang` outside its own package.

## Acceptance criteria → tests

`s` = `tests/test_prompts_slots.py`, `a` = `tests/test_prompts_assembly.py`,
`o` = `tests/test_prompts_overview.py`, `r` =
`tests/test_prompts_systems_of_record.py`, `i` =
`tests/test_prompts_invariants.py`. Line numbers are as of commit
`e873dfe`. Every test docstring cites AIE-1055 and its US number.

`make check`: lint and typecheck clean; 3093 passed, 6 skipped (the
pre-existing resolver-conformance skips).

| Acceptance criterion | Test(s) |
| -------------------- | ------- |
| US1.1 three non-blank `str` values construct, stored stripped | `s:58::test_three_non_blank_strings_construct_stripped` |
| US1.2 `systems_of_record` omitted or `None` → `None` | `s:70::test_systems_of_record_omitted_is_none`, `s:76::test_systems_of_record_none_is_none` |
| US1.3 required field of wrong real type → `TypeError("<field> must be str, not <T>")` | `s:92::test_required_field_wrong_type_raises_type_error` (`None`, `bytes`, `int`, spoofed `__class__` × both required fields) |
| US1.4 `systems_of_record` neither `str` nor `None` → `TypeError` | `s:108::test_systems_of_record_wrong_type_raises_type_error` (`bytes`, `int`, spoofed) |
| US1.5 lying `str` subclass stored as exact `str` via `str.__str__` + `str.strip` | `s:116::test_str_subclass_normalized_to_exact_str` |
| US1.6 `"  text\n"` → `"text"` | `s:127::test_surrounding_whitespace_is_stripped` |
| US1.7 empty / whitespace-only → `ValueError` | `s:135::test_blank_field_raises_value_error` (3 blanks × 3 fields) |
| US1.8 lone surrogate → `ValueError` from `UnicodeEncodeError` | `s:143::test_lone_surrogate_raises_value_error_from_unicode_error` |
| US1.9 all type checks before any value check | `s:165::test_type_checks_run_before_value_checks` |
| US1.10 first bad field in field order is named | `s:211::test_first_bad_field_in_order_is_reported` |
| US1.11 frozen | `s:222::test_assignment_raises_frozen_instance_error` |
| US1.12 equal post-strip text → equal, equal hashes | `s:229::test_equal_post_strip_text_is_equal_with_equal_hashes`, `s:237::test_equal_text_without_systems_of_record_is_equal_with_equal_hashes` |
| US1.13 docstring states vocabulary contract (`shared`, `private`, `system/`) | `s:248::test_docstring_states_vocabulary_contract` |
| US2.1 `__all__` is the three names, each resolvable | `a:108::test_public_all` (RUF022 order; see Deviations) |
| US2.2 `SECTION_ORDER` is the exact tuple | `a:117::test_section_order` |
| US2.3 each generic module has a non-empty `HEADING`; SoR has `PRINCIPLE`, no `BODY`; others have `BODY` | `a:125::test_section_module_shape` |
| US2.4 eleven headings non-empty and distinct; four owned values pinned | `a:140::test_headings_distinct_and_owned_values_pinned` |
| US3.1 returns an exact `str` | `a:157::test_build_returns_exact_str` |
| US3.2 deterministic | `a:176::test_build_is_deterministic` |
| US3.3 non-`PromptSlots` → `TypeError("slots must be PromptSlots, not <T>")` | `a:194::test_build_rejects_non_prompt_slots` (`None`, `dict`, spoofed) |
| US3.4 positional-only | `a:200::test_build_slots_is_positional_only` |
| US3.5 full output format with every body set | `a:208::test_build_full_output_format` |
| US3.6 blank body omits its section, no extra blank lines | `a:233::test_build_omits_blank_section` (empty / whitespace × every `BODY` module) |
| US3.7 slot text verbatim directly under `## Scopes` / `## Seed areas` | `a:252::test_build_slot_text_under_headings` |
| US3.8 SoR body = `PRINCIPLE.strip()` + blank line + slot | `a:264::test_build_systems_of_record_body` |
| US3.9 `systems_of_record=None` → no SoR heading, no sentence of `PRINCIPLE` | `a:273::test_build_omits_systems_of_record_when_none` |
| US3.10 starts `## Memory\n\n`, no H1, ends in exactly one `\n` | `a:289::test_build_starts_with_memory_and_ends_with_one_newline` |
| US3.11 bodies read at call time | `a:302::test_build_reads_bodies_at_call_time` |
| US4.1 overview: non-empty, 4-6 sentences, required phrases | `o:20::test_overview_body_is_four_to_six_sentences`, `o:30::test_overview_body_contains_phrase` |
| US4.2 SoR principle: non-empty, required words | `r:13::test_principle_is_non_empty`, `r:21::test_principle_contains_word` |
| US5.1 discovered section modules are exactly the nine | `i:140::test_discovered_section_modules`, `i:146::test_text_set_covers_every_section` |
| US5.2 ASCII, lines <= 100 | `i:153::test_text_is_ascii_with_short_lines` |
| US5.3 no `AIE-\d+` under `src/wenchang/prompts/` | `i:160::test_no_linear_ids_in_prompt_sources` |
| US5.4 no `.md`, `{`, `x/y.md` path, or entity/entities | `i:168::test_text_has_no_paths_braces_or_entity` |
| US5.5 backticked calls use real tool and parameter names (`inspect.signature`) | `i:177::test_text_tool_calls_use_real_names_and_parameters` |
| US5.6 backticked snake_case identifiers are agent-visible | `i:194::test_text_snake_case_identifiers_are_agent_visible`, `i:202::test_allowed_identifier_set_is_populated` |
| US5.7 no organization(s) / project(s) | `i:212::test_text_has_no_adopter_scope_names` |
| US5.8 each text <= 2500 chars | `i:218::test_text_length_limit` |
| US5.9 imports from `wenchang` confined to `wenchang.prompts` | `i:240::test_prompts_import_only_prompts_from_wenchang`, `i:257::test_prompt_files_include_package_modules` |
| US6.1 `REFERENCE_SLOTS` builds, each blob verbatim under its heading | `a:324::test_reference_slots_build_and_appear_under_headings` |
| US6.2 fixture blobs carry the §9 rules, areas, and systems | `a:343::test_reference_scope_guidance_rules`, `a:364::test_reference_seed_areas_content`, `a:378::test_reference_systems_of_record_content` |
| US6.3 `systems_of_record=None` omits SoR | `a:386::test_reference_slots_without_systems_of_record` |
| US6.4 `REFERENCE_SCOPE_PRIORITY` configures `MemoryStore` | `a:398::test_reference_scope_priority_configures_memory_store` |
| US7.1 ARCHITECTURE.md | `ARCHITECTURE.md`: Bird's-eye view (module count, planned note), Module map **prompts** entry, diagram note paragraph |
| US7.2 glossary | `docs/product/glossary.md`: new **Prompt slots**; **Seed areas**, **Systems of record**, **Scope priority** updated |
| US7.3 README adopter section | `README.md`: **Adopter configuration** |
| US7.4 ADR 0025 | `docs/adr/0025-prompt-layer-sections-and-slots.md`: decisions 1-10, the 2026-10-05 decisions in Context and decisions 3-4, overview owning "split rather than bloat" in decision 6 |
| US7.5 no Linear IDs in `src/`; test docstrings cite AIE-1055 | `i:160` (prompts package); `grep -rE "AIE-[0-9]+" src` finds nothing; every new test docstring cites AIE-1055 |

## Architecture / ADR changes

- New [ADR 0025](../../docs/adr/0025-prompt-layer-sections-and-slots.md),
  "Prompt layer: generic section text and adopter slots". Context quotes
  Notion §8's opening and §8.2 verbatim. It records ten decisions:
  1. one `Final[str]` module per section, not one file and not `.md`
     resources
  2. a three-name public API, with section wording not API
  3. the `PromptSlots` validation and the optional `systems_of_record`
  4. a fixed `SECTION_ORDER` that adopters can't change, with
     pre-declared empty sections and the omit-empty rule
  5. scope priority on `MemoryStore`
  6. docstrings own mechanics and the prompt owns judgment, with the
     contradiction risks listed
  7. the vocabulary contract
  8. the unit-test scope
  9. ASCII and the 2500-char budget
  10. the §9 fixture as test code
- `ARCHITECTURE.md` changes:
  - The **prompts** entry now describes the implemented package: public
    names, `SECTION_ORDER`, slot validation, the omit-empty rule, the
    vocabulary contract, the import rule, the docstring/prompt division,
    and scope priority on `MemoryStore`.
  - The bird's-eye view now counts eleven implemented modules plus
    `testing`. The only planned piece left is the remote transport.
  - The diagram note no longer calls `prompts` planned. The mermaid
    diagram is unchanged.
- `docs/product/glossary.md`: new **Prompt slots** entry. **Seed areas**
  and **Systems of record** now point to their slots, and **Scope
  priority** names `MemoryStore(scope_priority=...)`.
- `README.md`: new **Adopter configuration** section with a
  `build_memory_prompt(PromptSlots(...))` plus `MemoryStore(...,
  scope_priority=("user", "project", "organization"))` example.

## Deviations from spec

- **`systems_of_record` is optional** (human decision, 2026-10-05). §8.2
  presents it as one of the blobs. `None` omits the principle and the list
  together. See ADR 0025 decision 3.
- **Scope priority is not in `PromptSlots`.** §8.2 lists it among the
  slots but calls it "configuration, not prompt text". It stays on
  `MemoryStore(scope_priority=...)` so there is one source of truth. See
  ADR 0025 decision 5.
- **`__all__` order.** Spec US2.1 lists `["PromptSlots", "SECTION_ORDER",
  "build_memory_prompt"]`. The shipped order is `["SECTION_ORDER",
  "PromptSlots", "build_memory_prompt"]` because ruff's RUF022 requires the
  sorted order. `a:108` pins the shipped order. The set of names is
  unchanged.

## Decisions to confirm

- **Adopters can't omit, reorder, or override generic sections.** This is
  the orchestrator's default, pending your confirmation (ADR 0025 decision
  4).
- **The overview section belongs to AIE-1055.** This is also the
  orchestrator's default; no milestone issue owned it.

## Adversarial review findings

## Look closely at

- **The owned prose.** This is the text the agent will actually read.
  `overview.BODY` (`src/wenchang/prompts/overview.py`):

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

  `systems_of_record.PRINCIPLE` (`src/wenchang/prompts/systems_of_record.py`):

  ```
  Some information already has a canonical home in the product you work in; the list below
  names those systems of record. Do not copy their contents into memory. Refer to the canonical
  object by the name or ID it has there, and store only what that system does not hold: your
  interpretation of it, how people use it, and corrections they have given you. If memory
  disagrees with the system of record, do not let the two diverge silently: point out the
  discrepancy to the user and ask which is right before you change memory.
  ```

  Questions: does the overview's "split rather than bloat" sentence say
  enough for later sections to refer to it? Is "ask which is right before
  you change memory" the right default for a discrepancy?
- **Fixture fidelity to §9** (`tests/prompts_reference_adopter.py`). The
  three blobs are rewritten from §9 into agent-facing prose, so wording
  was added. In particular, check:
  - the containment reason "readable by members who can access only some
    projects"
  - the "Scope test" paragraph and its three examples
  - the seed-area lists per scope
  - the event-catalog, dashboard, and cohort bullets

  Tests pin the hierarchy, scope-test, ask, contradiction, and containment
  sentences, so any edit will need the matching test updated.
- **The invariant regexes** (`i:168`-`i:218`):
  - `\bentit(y|ies)\b` allows "identity".
  - `\b(organizations?|projects?)\b` applies only to section text, not
    slots.
  - The tool-call regex ``` `name(args)` ``` accepts only bare parameter
    names, `name=...`, or `...` as arguments.
  - The snake_case regex catches only identifiers that contain at least
    one `_`, so a single-word backticked token like `` `scope` `` is not
    checked.

  Are any of these too loose, or too strict for the prose AIE-1049..1054
  will write?

## Follow-ups

- AIE-1049..1054: write the seven empty section bodies. Each issue touches
  only its own module and test file.
- Optionally add a line to the `append_line` docstring saying `[system]`
  marks curated content and is not for agent writes, so the docstring
  agrees with the `remembering` section.
- An eval harness (§10.3) for the behavioral scenarios listed in
  `spec.md`: index first, ask before a shared write, systems-of-record
  discrepancy, split near the size limit, and no systems-of-record
  section.
