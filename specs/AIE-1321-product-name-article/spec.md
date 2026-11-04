# Feature Specification: Correct article before the product name in tool descriptions

**Linear issue**: AIE-1321 | **Branch**: `AIE-1321-product-name-article` | **Date**: 2026-11-02

Allow-test-changes: AIE-1321 changes the pinned first lines and restates the US5.4 single-insertion invariant in tests/test_tools_descriptions.py; no test is removed.

## Problem

`MemoryTools.descriptions()` (AIE-1164, ADR 0026) folds the adopter's product
into each tool's first line using `_FIRST_LINE_TEMPLATES` in
`src/wenchang/tools.py`. Four templates put a hard-coded "a" directly before
`{product}`, so a vowel-initial name renders "a Inkwell". The other three
templates do not put an article before the product ("every", "one", and "an
existing", where "an" precedes "existing").

## Decision

Rephrase: in `list_prefix`, `write_file`, `replace_fact`, and `delete_file`,
replace the "a" before `{product}` with "one". No article ever directly
precedes the product, so the text is correct for any name. It matches
`read_file`'s existing "Read one {product} memory file", and each of these
tools acts on exactly one file or scope.

Rejected: a vowel-letter heuristic (wrong for "Uber", "Unix", "Hour", "MCP",
"8x8", "X"); letting the adopter pass an article (public API change for a
cosmetic issue); moving the product after the noun, "a memory file in P"
(larger rewrite, departs from ADR 0026's insertion pattern); changing the
docstrings to "one" too (alters unbranded descriptions, the `tool_schemas`
snapshot, and AIE-1165 phrase pins for no gain).

First lines with product `P` (changed tools only; the other three are
unchanged):

| Tool | First line |
| ---- | ---------- |
| list_prefix | List the files in one P memory scope or area, one page at a time, without content. |
| write_file | Create one P memory file or replace one whole. |
| replace_fact | Change one fact in one P memory file by quoting the text to replace. |
| delete_file | Delete one P memory file. |

Docstrings are unchanged (they still say "a memory file"; no product there, so
no article problem).

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | product `"Inkwell"` | `tool_descriptions` / `MemoryTools.descriptions()` | first lines of the four tools are exactly the strings above with `P="Inkwell"`; no description matches the regex `\ban? Inkwell\b` |
| 2 | product in `("Inkwell", "Uber", "Hour", "MCP", "Mixpanel", "Acme Analytics", "C++")` | rendered | in every tool's first line the product occurs, and no occurrence of it is preceded by a standalone "a" or "an" (case-insensitive; space and line-edge boundaries, not `\b`) |
| 3 | product `"Mixpanel"` | rendered | each first line equals the updated pinned table (four changed, three unchanged from the previous pinned table); every later line equals the cleandoc'd docstring's (US5.3 holds) |
| 4 | product `None` | rendered | descriptions equal the cleandoc'd docstrings; `tests/snapshots/tool_schemas.json` unchanged |
| 5 | product `"Mixpanel"`, `"Acme Analytics"`, or `"Inkwell"` | rendered | US5.4 restated, substitution mandatory (see below) |
| 6 | product containing braces | rendered | appears verbatim (US5.5 holds) |

AC5 detail. Boundaries are `i in {0} | {j+1 : first[j] == " "}`, so `first[:i]`
ends with a space (or is empty). At each boundary, if `first[:i]` matches
`(?<![^ ])a $` (standalone word "a" plus space at the end), the ONLY candidate
for that boundary is `first[:i-2] + "one " + insertion + first[i:]`; it
replaces the unreplaced candidate rather than being added alongside it.
Otherwise the candidate is `first[:i] + insertion + first[i:]`. The insertion
is `"P "` for six tools and `"P memory "` for `list_prefix`. This test must
fail against the current code; for `write_file` the only candidate is
"Create one P memory file or replace one whole.".

## Out of scope

- Any public API change: `tool_descriptions(product)`, `MemoryTools.descriptions()`,
  and `tool_schemas(product)` keep their signatures.
- Docstrings, the prompt sections and slots (they do not interpolate the
  product), `tool_schemas.json`, and `site/` (both render the no-product text).
- Supersedes the AIE-1164 out-of-scope line "A/an article selection before the
  product name (templates use a fixed 'a')": the fixed "a" is removed instead.

## Notes

- `evals/agent.py:25` and `.claude/agents/wenchang-eval.md:9` say "a Mixpanel
  user": a literal, consonant-initial string, checked and left unchanged.
- Evals use `REFERENCE_PRODUCT="Mixpanel"`, so the eval subject sees the four
  changed first lines. Low risk; an optional `/run-evals` pass is advisable.
