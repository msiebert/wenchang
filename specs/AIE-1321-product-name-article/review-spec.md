# Spec Review: AIE-1321 — Fix "a"/"an" before product names

## What & why

Generated tool descriptions hard-code "a" before the adopter's product name,
so a vowel-initial name reads "a Inkwell". Four of the seven first-line
templates are affected. We rephrase those four to use "one", so no article
ever precedes the product and every name is correct.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | product "Inkwell" | descriptions rendered | four affected first lines are exactly the new strings; no description matches `\ban? Inkwell\b` |
| 2 | Inkwell, Uber, Hour, MCP, Mixpanel, Acme Analytics, C++ | rendered | product occurs; no occurrence is preceded by a standalone "a"/"an" |
| 3 | "Mixpanel" | rendered | pinned table updated (4 changed, 3 unchanged from the previous table); later lines equal docstring |
| 4 | no product | rendered | docstrings and `tool_schemas.json` snapshot unchanged |
| 5 | Mixpanel, Acme Analytics, Inkwell | rendered | single-insertion invariant holds, with a mandatory "a" -> "one" substitution replacing the unsubstituted candidate; fails on current code |
| 6 | product with braces | rendered | appears verbatim |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| Replace "a" with "one" in the four templates | Vowel-letter heuristic; adopter-supplied article; product after the noun; "one" in docstrings too | Heuristic fails on Uber/Hour/MCP/8x8; article param is an API change for a cosmetic bug; reorder departs from ADR 0026; docstring change hits snapshot and AIE-1165 pins |
| Amend ADR 0026, no new ADR | New ADR | Wording change to 0026's decision; parallel issues are allocating ADR numbers |

## Files/modules to be touched

- `src/wenchang/tools.py` (four template strings)
- `tests/test_tools_descriptions.py`
- `docs/adr/0026-product-identity.md`, `ARCHITECTURE.md`

## Open questions / assumptions

- Assumes "one" reads acceptably in the tool-selection first line; each tool acts on exactly one file or scope.
- Docstrings keep "a memory file"; unbranded text is unaffected.

## Risks

- Existing tests change (pinned lines, US5.4 restated); none removed (`Allow-test-changes:` in spec.md).
- Eval subject sees four reworded first lines (REFERENCE_PRODUCT "Mixpanel"); low risk, optional `/run-evals`.
