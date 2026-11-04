# PR Review: AIE-1321 — Fix "a"/"an" before product names

## What changed & why

Tool descriptions with a product set hard-coded "a" before the product, so a
vowel-initial name read "a Inkwell". In four first-line templates
(`_FIRST_LINE_TEMPLATES` in `src/wenchang/tools.py`) the "a" is now "one", so
no article ever precedes the product and every name reads correctly. Rephrasing
beats a vowel-letter heuristic (wrong for Uber, Hour, MCP, 8x8) and avoids a
public API change. Docstrings, the unbranded descriptions, and
`tool_schemas.json` are unchanged.

| Tool | Before (P) | After (P) |
| ---- | ---------- | --------- |
| list_prefix | List the files in a P memory scope or area, ... | List the files in one P memory scope or area, one page at a time, without content. |
| write_file | Create a P memory file or replace one whole. | Create one P memory file or replace one whole. |
| replace_fact | Change one fact in a P memory file by quoting the text to replace. | Change one fact in one P memory file by quoting the text to replace. |
| delete_file | Delete a P memory file. | Delete one P memory file. |

`get_memory_index`, `read_file`, `append_line` are unchanged.

## Acceptance criteria → tests

All tests are in `tests/test_tools_descriptions.py`.

| Acceptance criterion (Given/When/Then) | Test(s) |
| --------------------------------------- | ------- |
| AC1: product "Inkwell" → four exact first lines; no `\ban? Inkwell\b` | `test_inkwell_first_lines_are_exact_and_free_of_a_inkwell` |
| AC2: seven products (incl. "C++") → product occurs; no occurrence is preceded by a standalone "a"/"an" | `test_first_line_has_no_article_directly_before_product` |
| AC3: "Mixpanel" → pinned table updated, later lines equal docstring | `PINNED_FIRST_LINES`, `test_descriptions_with_product_pin_first_line_only` |
| AC4: no product → cleandoc'd docstrings; schema snapshot unchanged | `test_descriptions_without_product_are_cleandoc_docstrings`, `tool_schemas.json` snapshot |
| AC5: single insertion with mandatory "a" -> "one" substitution | `test_descriptions_first_line_is_single_insertion` |
| AC6: braces in product appear verbatim | `test_descriptions_insert_product_verbatim` |

`make check`: passed (ruff + pyright clean; 5894 passed, 18 skipped, 46 deselected).

## What adversarial review caught

- Spec review: AC5 originally allowed the old wording, which would have made
  the test vacuous; the substitution is now mandatory. The ADR edit list was
  vague; it now names each stale spot.
- Code review: the AC2 test checked only the first occurrence and missed
  non-word products, so it was hardened and "C++" added. A template comment
  was added so "a {product}" does not creep back. Stale ADR sentences now
  carry pointers to the AIE-1321 Note.

## Architecture / ADR changes

- [ADR 0026](../../docs/adr/0026-product-identity.md): dated "Note (AIE-1321,
  2026-11-02)" amendments to decision 4 (insertion rule, pinned list, rejected
  a/an heuristic) and Consequences. No new ADR: this is a wording change to
  0026's decision, and parallel issues are allocating ADR numbers.
- `ARCHITECTURE.md`, `tools` entry: states that four templates change "a" to
  "one" before the product.

## Deviations from spec

- None. This supersedes the AIE-1164 out-of-scope line "templates use a fixed
  'a'". The US5.4 invariant is restated (AC5); `Allow-test-changes:` in spec.md
  covers the changed pins and restated test. No test is removed.

## Look closely at

- The AC5 test: the "a" -> "one" substitution replaces the unsubstituted
  candidate at a boundary, so the old output must fail it.
- "one fact in one P memory file" (`replace_fact`) reads a little doubled;
  accepted for consistency with `read_file`'s "Read one P memory file".
- `src/wenchang/tools.py` must not cite an AIE id
  (`test_tools_module_cites_no_linear_ids`).
- Checked and left unchanged: `evals/agent.py:25` and
  `.claude/agents/wenchang-eval.md:9` say "a Mixpanel user", a literal
  consonant-initial string.

## Follow-ups

- Eval subject sees four reworded first lines under "Mixpanel". Low risk; an
  optional `/run-evals` pass is advisable but not required.
