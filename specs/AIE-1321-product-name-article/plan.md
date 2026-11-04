# Implementation Plan: Correct article before the product name

**Linear issue**: AIE-1321 | **Branch**: `AIE-1321-product-name-article` | **Date**: 2026-11-02 | **Spec**: [spec.md](spec.md)

## Summary

Only the string values of four entries in `_FIRST_LINE_TEMPLATES`
(`src/wenchang/tools.py`) change: "a {product}" becomes "one {product}" for
`list_prefix`, `write_file`, `replace_fact`, `delete_file`. Tests:
`tests/test_tools_descriptions.py`. Docs: ADR 0026 amendment, ARCHITECTURE.md.

## Technical Context

Python >= 3.12; pyright strict; ruff 100 columns. No new imports, no
import-graph change.

## Interface

Unchanged: `tool_descriptions(product: str | None = None) -> Mapping[str, str]`,
`MemoryTools.descriptions()`, `tool_schemas(product)`. The import-time guard
`tuple(_FIRST_LINE_TEMPLATES) == TOOL_NAMES` and plain `{product}` replacement
are unchanged.

New templates (long ones keep implicit string concatenation, lines <= 100
columns):

- `list_prefix`: "List the files in one {product} memory scope or area, one page at a time, without content."
- `write_file`: "Create one {product} memory file or replace one whole."
- `replace_fact`: "Change one fact in one {product} memory file by quoting the text to replace."
- `delete_file`: "Delete one {product} memory file."

`get_memory_index`, `read_file`, `append_line` are unchanged.

## Constitution Check

| Principle | Status |
| --------- | ------ |
| I. Tests-first | T1 test-writer -> T2 implementer |
| II. Tests not negotiable | Pinned first lines change and US5.4 is restated (AC5); no test removed; `Allow-test-changes:` line in spec.md |
| Storage via interface only | Unchanged |
| Architecture changes documented | ADR 0026 amended (wording of its decision, no new decision); ARCHITECTURE.md sentence updated |

## Existing tests that change

In `tests/test_tools_descriptions.py`:

- `PINNED_FIRST_LINES`: four entries updated per the spec table.
- US5.4 test (`test_descriptions_first_line_is_single_insertion`):
  boundaries are `i in {0} | {j+1 : first[j] == " "}`. At each boundary, if
  `first[:i]` matches `(?<![^ ])a $`, the only candidate is
  `first[:i-2] + "one " + ins + first[i:]` (replacing, not adding to, the
  unreplaced candidate); otherwise `first[:i] + ins + first[i:]`. Add
  `"Inkwell"` to its products. Boundary and insertion computation still derive
  from the docstring at test time. It must fail against the current code; for
  `write_file` the only candidate is "Create one P memory file or replace one
  whole.".
- New tests: AC1 (exact four lines; no description matches `\ban? Inkwell\b`)
  and AC2 (parametrized over the seven products, including "C++"; assert the
  product occurs in the first line and no occurrence is preceded by a
  standalone "a"/"an", case-insensitive, using space and line-edge boundaries
  rather than `\b`).
- New and changed test docstrings cite AIE-1321 (existing AIE-1164 citations
  stay).
- US5.3 and US5.5 tests need no change beyond the pinned table.

## Docs

- `docs/adr/0026-product-identity.md`: add a dated "Note (AIE-1321,
  2026-11-02)" in the ADR's existing note style; do not silently rewrite.
  Amendment rather than a new ADR: a wording change to 0026's decision, and
  parallel issues are allocating ADR numbers. The note covers each stale spot:
  - ~89-93: the "one phrase inserted" rule and the "a Mixpanel scope or area"
    rationale (now: insertion plus "a" becomes "one" where one precedes the
    product).
  - ~98-105: the pinned list (four lines changed).
  - ~109-110: the rejected a/an heuristic line; keep the rejection and note
    the article is now avoided instead.
  - ~146-147: the Consequences "a Amplitude" remark.
- `ARCHITECTURE.md` (~1024-1027): add that four templates also change the "a"
  before the product to "one".
- `specs/AIE-1321-product-name-article/review-pr.md`.

## Eval impact

The four changed first lines are seen by the eval subject (`REFERENCE_PRODUCT`).
Optional `/run-evals` pass; not part of `make check`.

## Files

- `src/wenchang/tools.py`
- `tests/test_tools_descriptions.py`
- `docs/adr/0026-product-identity.md`, `ARCHITECTURE.md`
