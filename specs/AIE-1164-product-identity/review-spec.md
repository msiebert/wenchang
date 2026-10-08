# Spec Review: AIE-1164 — Product identity in the prompt and tool descriptions

## What & why

Nothing in the memory prompt or the tool descriptions says which product the
memory belongs to, so an agent with many tools can't tell from a first line
that `append_line` is Mixpanel memory. This adds a required `purpose` slot
that opens the prompt's "Memory" section, and an optional `product` on
`MemoryTools` with a `descriptions()` method that names the product in each
tool description's first line. Docstrings stay as they are.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| US1 | `PromptSlots(purpose, scope_guidance, seed_areas, systems_of_record=None)` | constructed | `purpose` is required and validated like the other required slots, first in check order |
| US2 | any slots | `build_memory_prompt` | section 1 is `## Memory`, then `purpose`, a blank line, and `overview.BODY`; order unchanged |
| US3 | reference fixture | build | `REFERENCE_PURPOSE` opens section 1 |
| US4 | `MemoryTools(..., product=...)` / `bind_tools(..., product=...)` | constructed | `None` or a one-line non-empty `str`; read-only `product` |
| US5 | `descriptions()` | called | docstrings unchanged without product; with product, only the first line changes, per pinned templates |
| US6 | docs | read | ADR 0026, ARCHITECTURE, README, glossary updated |

Full Given/When/Then in [spec.md](spec.md).

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| `purpose` is a required first field of `PromptSlots` | optional slot; its own section | Every adopter has a product; a separate section would push the product below the generic overview, and optional means some prompts never say it |
| Purpose is spliced into the overview section body | new `SECTION_ORDER` entry | Keeps the "Memory" heading as the single opening and `SECTION_ORDER` stable |
| `product` on `MemoryTools`, `descriptions()` method | module function taking a product; templating the docstrings | The session object already carries adopter config (`source`); docstrings are static and pinned by AIE-1165 |
| Only the first line is templated | product in every paragraph | The first line is what hosts show for selection; the rest keeps the AIE-1165 budget and phrase pins |
| Strict single-insertion fidelity check | "remove `{product}` and compare" | Two docstring first lines need wording the simple removal can't match; templates chosen so each is the docstring line plus one inserted phrase (`list_prefix` adds "memory") |
| `product` also checked for UTF-8 encodability | type/empty/one-line only | Same rule as every `PromptSlots` field; a lone surrogate would break a JSON or MCP host |
| Fixed article "a" before the product | a/an heuristic | Pronunciation-dependent; out of scope, noted in ADR 0026 |

## Files/modules to be touched

- `src/wenchang/prompts/slots.py`, `src/wenchang/prompts/assemble.py`, `src/wenchang/tools.py`
- `tests/test_prompts_slots.py`, `tests/test_prompts_assembly.py`, `tests/prompts_reference_adopter.py`, `tests/test_prompts_filing.py`, `tests/test_prompts_forgetting.py`, `tests/test_tools.py`, `tests/test_tools_descriptions.py`
- `docs/adr/0026-product-identity.md` (new), ADR 0022/0025 notes, `ARCHITECTURE.md`, `README.md`, `docs/product/glossary.md`

## Open questions / assumptions

- No host adapter exists in `src/`; "the in-process mount and the MCP server
  use `descriptions()`" is satisfied by README guidance now and by AIE-1060
  later.
- Existing assembly tests that expected section 1 to be `overview.BODY` alone
  are updated to expect the splice; the overview case of the blank-section
  omission test moves to a new test (section 1 cannot be omitted now).

## Risks

- Breaking constructor change: any adopter code calling `PromptSlots` without
  `purpose` fails with `TypeError`. Pre-1.0, recorded in ADR 0026.
- Product names that take "an" read slightly off in four templates.

## Adversarial review

Round 1 — FAIL (6 SHOULD-FIX, 5 NIT), all fixed:

- Two template literals exceeded 100 columns (ruff E501); plan shows them
  split by implicit concatenation.
- The list of existing assembly tests the splice changes was incomplete;
  plan.md now names all five, plus the `test_prompts_slots.py` helpers that
  gain `purpose` so existing parametrized tests cover it.
- The strict insertion check was imprecise; plan.md now defines boundaries,
  insertion strings, and two test products.
- Literal U+2028/U+2029 in the spec table replaced with escapes.
- Stale "three slots" / "each described by its docstring" statements in the
  glossary and ARCHITECTURE.md added to US6.2/US6.4.
- NITs: whitespace-collapsed docstring match; ADR 0025 note records that a
  blank overview no longer omits section 1; `REFERENCE_PURPOSE` in the
  stripped-blob check; `bind_tools` resolver-before-product order stated in
  ADR 0026; US5.6 scoped to "Mixpanel".

Round 2 — PASS. Confirmed the test-change list is complete, the strict
insertion check holds for all seven tools against the live docstrings (run
for "Mixpanel" and "Acme Analytics"), template lines ≤97 columns, and no
literal line separators. One SHOULD-FIX (plan.md table split by a section)
fixed.
