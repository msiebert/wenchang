# PR Review: AIE-1164 — Product identity in the prompt and tool descriptions

## What changed & why

Nothing in the assembled prompt or the tool descriptions said which product the memory serves, and an agent with many tools picks by each description's first line. The prompt gains a required `purpose` slot that opens section 1 ("Memory"); `MemoryTools` gains an optional session `product` and a `descriptions()` method that names the product in each tool description's first line. The docstrings stay static, so hosts register from `descriptions()` rather than `__doc__`. Generic section bodies, tool docstrings, and `SECTION_ORDER` are unchanged.

## What changed per module

- `src/wenchang/prompts/slots.py`: `purpose: str` added as the first, required field; it joins the existing type pass and value pass first in field order (same messages: `purpose must be str, not <type>`, `... must not be empty or whitespace-only`, `... must be encodable as UTF-8`). Docstring gains a ``purpose`` bullet.
- `src/wenchang/prompts/assemble.py`: the `overview` entry of `_SECTIONS` is `_overview`, which joins the non-empty parts `[slots.purpose, overview.BODY.strip()]` with `"\n\n"`, reading `BODY` at call time. Section 1 is therefore never omitted.
- `src/wenchang/tools.py`: keyword-only `product: str | None = None` on `MemoryTools.__init__` and `bind_tools`, validated by `_product()` after `source`; read-only `product` property; `descriptions()`; private `_FIRST_LINE_TEMPLATES` with an import-time guard that its keys equal `TOOL_NAMES`; `inspect` import; module docstring says descriptions come from `descriptions()`.
- `tests/prompts_reference_adopter.py`: `REFERENCE_PURPOSE` and `REFERENCE_SLOTS.purpose`.

## Public API change

- **Breaking:** `PromptSlots(purpose, scope_guidance, seed_areas, systems_of_record=None)`. Every construction site must pass `purpose`; positional callers shift by one.
- `MemoryTools(client, identity, policy, *, source, product=None)` and `bind_tools(client, resolver, credentials, policy, *, source, product=None)`. Additive. `product` is stripped to an exact one-line UTF-8 `str`; errors are plain `TypeError("product must be a str or None, not <type>")` / `ValueError("product must be non-empty" | "product must be one line" | "product must be encodable as UTF-8")`. In `bind_tools`, resolver failure still wins.
- `MemoryTools.descriptions() -> Mapping[str, str]`: a fresh `MappingProxyType` keyed by `TOOL_NAMES` in order. With `product=None` each value is `inspect.cleandoc` of the docstring; otherwise only the first line is replaced (plain `str.replace`, so braces are verbatim). No tool method takes `product`; `tools()` is unchanged.

## Pinned first lines (`product="Mixpanel"`)

| Tool | First line |
| ---- | ---------- |
| get_memory_index | Load the metadata index of every Mixpanel memory scope available in this session. |
| read_file | Read one Mixpanel memory file: its content, metadata, and version. |
| list_prefix | List the files in a Mixpanel memory scope or area, one page at a time, without content. |
| write_file | Create a Mixpanel memory file or replace one whole. |
| append_line | Add one fact line to the end of an existing Mixpanel memory file. |
| replace_fact | Change one fact in a Mixpanel memory file by quoting the text to replace. |
| delete_file | Delete a Mixpanel memory file. |

Each is the docstring's first line with one insertion: `"Mixpanel "` for six tools, `"Mixpanel memory "` for `list_prefix`.

## Assembled section 1, reference fixture

`build_memory_prompt(REFERENCE_SLOTS)` begins:

```markdown
## Memory

You have persistent memory of your work in Mixpanel: reference it and save to it with these
tools whenever you work with Mixpanel.

You have persistent memory: short markdown files that outlast this conversation, each addressed
by a scope, an area in that scope, and a name. Call `get_memory_index()` at the start of every
session, before you answer from memory or write to it. When a subject outgrows its file's size
limit, split it into narrower files.

## Scopes
```

## Acceptance criteria → tests

Paths are under `tests/`; line numbers are the `def` line.

| Acceptance criterion (Given/When/Then) | Test(s) |
| --------------------------------------- | ------- |
| US1.1 non-blank fields construct, stored stripped exact `str` | `test_prompts_slots.py:67` `test_non_blank_strings_construct_stripped`; `:173` `test_surrounding_whitespace_is_stripped` (parametrized over `FIELDS`, now including `purpose`) |
| US1.2 field names/order; only `systems_of_record` defaulted | `test_prompts_slots.py:85` `test_fields_in_order_and_only_systems_of_record_defaulted` |
| US1.3 positional `PromptSlots("p", "g", "s")` | `test_prompts_slots.py:96` `test_positional_construction_starts_with_purpose` |
| US1.4 `purpose` omitted → `TypeError` | `test_prompts_slots.py:107` `test_purpose_omitted_raises_type_error` |
| US1.5 non-`str` `purpose` → `TypeError` | `test_prompts_slots.py:136` `test_required_field_wrong_type_raises_type_error` |
| US1.6 lying `str` subclass → exact `str` | `test_prompts_slots.py:162` `test_str_subclass_normalized_to_exact_str` |
| US1.7 blank `purpose` → `ValueError` | `test_prompts_slots.py:181` `test_blank_field_raises_value_error` |
| US1.8 lone surrogate → `ValueError` from `UnicodeEncodeError` | `test_prompts_slots.py:189` `test_lone_surrogate_raises_value_error_from_unicode_error` |
| US1.9 later type error beats earlier bad `purpose` value | `test_prompts_slots.py:222` `test_type_checks_run_before_value_checks` |
| US1.10 `purpose` named first among same-kind errors | `test_prompts_slots.py:303` `test_first_bad_field_in_order_is_reported` |
| US1.11 assigning `purpose` → `FrozenInstanceError` | `test_prompts_slots.py:314` `test_assignment_raises_frozen_instance_error` |
| US1.12 equality/hash over stripped `purpose` | `test_prompts_slots.py:345` `test_purpose_whitespace_only_difference_is_equal_with_equal_hashes`; `:355` `test_different_purpose_is_not_equal` |
| US1.13 docstring `purpose` bullet before `scope_guidance`; deployment-facts sentence kept | `test_prompts_slots.py:377` `test_docstring_has_purpose_bullet_before_scope_guidance`; `:369` `test_docstring_says_slots_state_only_deployment_facts` |
| US2.1 output starts with heading, purpose, overview, `## Scopes` | `test_prompts_assembly.py:296` `test_build_starts_with_purpose_then_overview`; `:161` `test_build_returns_exact_str` |
| US2.2 headings, order, `SECTION_ORDER` unchanged; one `## Memory` | `test_prompts_assembly.py:309` `test_build_purpose_keeps_heading_order` |
| US2.3 blank `overview.BODY` keeps section 1 as `purpose` alone | `test_prompts_assembly.py:262` `test_build_blank_overview_keeps_memory_section_with_purpose`; `:242` `test_build_omits_blank_section` (other sections) |
| US2.4 `overview.BODY` read at call time | `test_prompts_assembly.py:381` `test_build_reads_bodies_at_call_time` |
| US2.5 full output equals per-section join | `test_prompts_assembly.py:215` `test_build_full_output_format` |
| US2.6 `overview.BODY` names no product; invariants unchanged | `test_prompts_assembly.py:285` `test_generic_text_names_no_product` (every generic BODY and the systems-of-record principle; "mixpanel", "acme"); `test_prompts_invariants.py` unchanged and passing |
| US3.1 `REFERENCE_PURPOSE` shape | `test_prompts_assembly.py:430` `test_reference_purpose_shape` |
| US3.2 `REFERENCE_SLOTS.purpose == REFERENCE_PURPOSE` | `test_prompts_assembly.py:404` `test_reference_slots_build_and_appear_under_headings` |
| US3.3 reference section 1 body | `test_prompts_assembly.py:387` (same test) |
| US4.1 `product` defaults to `None` | `test_tools.py:577` `test_product_defaults_to_none`; `:584` `test_product_none_is_stored_as_none` |
| US4.2 `product` stored; `bind_tools` forwards it | `test_tools.py:589` `test_product_is_stored_from_constructor`; `:594` `test_bind_tools_forwards_product` |
| US4.3 padded / lying-subclass (incl. one overriding `strip`) `product` → `"Mixpanel"` | `test_tools.py:624` `test_product_is_stripped_to_exact_str` |
| US4.4 non-`str` `product` → `TypeError` | `test_tools.py:639` `test_non_str_product_raises_type_error` |
| US4.5 blank `product` → `ValueError` | `test_tools.py:651` `test_blank_product_raises_value_error` |
| US4.6 any `splitlines` boundary → `ValueError` | `test_tools.py:661` `test_multiline_product_raises_value_error` |
| US4.7 lone surrogate → `ValueError` from `UnicodeEncodeError` | `test_tools.py:672` `test_unencodable_product_raises_value_error` |
| US4.8 `product` read-only | `test_tools.py:684` `test_product_is_read_only` |
| US4.9 `product` keyword-only | `test_tools.py:694` `test_product_is_keyword_only_on_memory_tools`; `:707` `test_product_is_keyword_only_on_bind_tools` |
| US4.10 no tool method takes `product`; `tools()` unchanged | `test_tools.py:721` `test_tool_methods_take_no_product_parameter`; `:726` `test_tools_mapping_unchanged_with_product` |
| US4.11 `source` error precedes `product` error | `test_tools.py:743` `test_source_error_precedes_product_error`; `:764` `test_bind_tools_resolver_error_precedes_product_error` (resolver failure wins in `bind_tools`) |
| US5.1 fresh read-only `MappingProxyType` in `TOOL_NAMES` order | `test_tools_descriptions.py:353` `test_descriptions_is_fresh_read_only_mapping_in_tool_order` |
| US5.2 no product → cleandoc'd docstrings | `test_tools_descriptions.py:369` `test_descriptions_without_product_are_cleandoc_docstrings` |
| US5.3 pinned first lines; later lines unchanged | `test_tools_descriptions.py:379` `test_descriptions_with_product_pin_first_line_only` |
| US5.4 single insertion at a word boundary | `test_tools_descriptions.py:393` `test_descriptions_first_line_is_single_insertion` ("Mixpanel", "Acme Analytics") |
| US5.5 product inserted verbatim (`"A{b}c"`) | `test_tools_descriptions.py:409` `test_descriptions_insert_product_verbatim` |
| US5.6 first line is one sentence | `test_tools_descriptions.py:419` `test_descriptions_first_line_is_one_sentence` |
| US5.7 tool docstrings unchanged | Existing AIE-1044/1151/1165 tests in `test_tools_descriptions.py` unchanged (diff only appends) and passing |
| US6.1 ADR 0026 | `docs/adr/0026-product-identity.md` decisions 1-6 and Consequences. Doc, no test |
| US6.2 ARCHITECTURE.md | `tools` and `prompts` entries. Doc, no test |
| US6.3 README adopter section | "Adopter configuration": `purpose` in the example, `bind_tools(..., product="Mixpanel")` and `descriptions()` registration. Doc, no test |
| US6.4 glossary | "Tool layer", "Prompt slots", new "Product" entry. Doc, no test |
| US6.5 ADR 0022/0025 dated notes | ADR 0022 decisions 2 and 8; ADR 0025 decisions 3 and 4 (the latter records that a blank `overview.BODY` no longer omits section 1). Doc, no test |

## `make check`

Passes: ruff format (295 files already formatted), ruff lint (all checks passed), pyright (0 errors, 0 warnings), pytest 3644 passed, 6 skipped, 41 deselected (main: 3533 passed).

## Existing tests changed and why

- Every `PromptSlots(...)` call gains `purpose`: `test_prompts_slots.py`, `test_prompts_assembly.py`, `test_prompts_filing.py`, `test_prompts_forgetting.py`, `prompts_reference_adopter.py`. Required by the breaking constructor.
- `test_prompts_slots.py` helpers (`FIELDS`, `REQUIRED_FIELDS`, `VALID`, `_make`, `_make_with`) gain `purpose` first, so the existing parametrized type, lying-subclass, strip, blank, surrogate, and frozen tests cover it (US1.5-1.8, US1.11); the order tests gain `purpose`-first cases (US1.9, US1.10).
- `test_prompts_assembly.py`:
  - `test_build_returns_exact_str`: section 1 expected as `"## Memory\n\n" + purpose + "\n\nOverview text.\n\n"`.
  - `test_build_full_output_format`: expected overview body is `SLOTS.purpose + "\n\n" + bodies["overview"]`.
  - `test_build_reads_bodies_at_call_time`: expected `sections["Memory"]` is `SLOTS.purpose + "\n\nReplacement overview."`.
  - `test_build_omits_blank_section`: parametrized over every section except `overview`, since section 1 is no longer omitted; the new `test_build_blank_overview_keeps_memory_section_with_purpose` covers that case.
  - `test_reference_slots_build_and_appear_under_headings`: includes `REFERENCE_PURPOSE` and checks it opens section 1.
- `tests/test_prompts_invariants.py` and the existing tool-docstring tests are unchanged.

## Architecture / ADR changes

- New [ADR 0026](../../docs/adr/0026-product-identity.md) (Accepted): `purpose` as a required first slot (vs optional, vs its own section); `product` on `MemoryTools` (vs a module function, vs templated docstrings); first-line-only templating, which keeps the AIE-1165 docstring budget and pins; hosts register from `descriptions()`; how this relates to AIE-1060's MCP `instructions`; the breaking constructor.
- [ADR 0022](../../docs/adr/0022-tool-layer.md) decisions 2 and 8, [ADR 0025](../../docs/adr/0025-prompt-layer-sections-and-slots.md) decisions 3 and 4: dated notes pointing to ADR 0026; the original text is unchanged.
- `ARCHITECTURE.md`: in `tools`, the constructor and `bind_tools` signatures, the `product` checks, and `descriptions()`. In `prompts`, four slots, the `PromptSlots` signature, and the purpose splice.
- `README.md`, `docs/product/glossary.md`: updated as listed for US6.3 and US6.4.

## Deviations from spec

- None.

## Look closely at

- **Breaking constructor.** `purpose` is first and has no default, so every adopter's `PromptSlots(...)` call breaks, and positional callers rebind silently if they happen to pass three strings. Confirm that's acceptable before 1.0.
- **Section 1 is never omitted.** For every other section, a blank body still drops the section. For overview it no longer does, because `purpose` is always non-blank. ADR 0025 decision 4 has a note about this.
- **The `list_prefix` template adds "memory".** That makes it the one first line that is not a pure product insertion. US5.4 pins it as `"P memory "`.
- **The article is always "a".** It is fixed, so a product starting with a vowel sound reads "a Acme ...". This is out of scope per spec.
- **`descriptions()` reads `MemoryTools`' docstrings, not `type(self)`'s.** A subclass that overrides a tool's docstring is not reflected.

## Follow-ups

- AIE-1060 (MCP server) registers tools from `descriptions()` and may pass `purpose` as MCP `instructions`.

## Adversarial review findings

Spec review: round 1 FAIL (6 SHOULD-FIX, 5 NIT; see review-spec.md), round 2 PASS.

Code review round 1:

- Reviewer A (correctness, spec fidelity): PASS, 4 NITs. Fixed: the
  `descriptions()` docstring now says it returns each tool's cleaned
  docstring and that a set product is named in each first line. Left: an
  import-time template-vs-docstring check (US5.4 test already guards drift);
  `python -OO` strips docstrings (repo-wide limitation); multi-fault product
  error precedence (matches `PromptSlots`).
- Reviewer B (coverage, docs): FAIL on one SHOULD-FIX: US2.6 had no guard.
  Fixed with `test_generic_text_names_no_product`. NITs fixed: a US4.3 case
  whose subclass also overrides `strip`; a test that a resolver failure wins
  over a bad `product` in `bind_tools`; the `tools.py` module docstring lists
  the optional product. NIT left: README wording "cleaned docstring" and
  hoisting `descriptions()` out of the example loop (README edit declined by
  the doc-updater as outside its configured scope; cosmetic).
