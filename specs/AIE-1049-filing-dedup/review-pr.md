# PR Review: AIE-1049 — Filing and deduplication discipline

## What changed & why

The "Filing" section of `build_memory_prompt()` (section 8) was empty. It
now carries the Notion §8.1 filing rules: put a fact in the file about its
subject; before creating a file, check the loaded index's descriptions and
aliases (one `list_prefix(scope, area)` if that area is capped and nothing
matched; read at most one or two candidates when ambiguous) and append or
edit instead of duplicating; and carry new lookup names as `aliases` on the
same write, because metadata is the entire search surface. Only
`filing.BODY` changes in `src/`; `tests/test_prompts_filing.py` is new.

## Acceptance criteria → tests

All in `tests/test_prompts_filing.py`. `make check`: 3344 passed, 6 skipped.

| Acceptance criterion (Given/When/Then) | Test(s) |
| --------------------------------------- | ------- |
| US1.1 heading "Filing", body non-empty | `test_filing_heading` :19, `test_filing_body_non_empty` :24 |
| US1.2 body <= 2000 chars (ASCII / cols / tool names via shared invariants) | `test_filing_body_length` :29; `tests/test_prompts_invariants.py` |
| US1.3 body appears under `## Filing` in the assembled prompt | `test_filing_section_in_assembled_prompt` :34 |
| US2.1 domain filing | `test_filing_body_contains_phrase[US2.1-*]` :44-45 |
| US2.2 seed areas are a starting shape | `[US2.2-*]` :46-47 |
| US2.3 no restated slug rule | `test_filing_body_omits_phrase[US2.3-*]` :92-93 |
| US3.1 dedup before creating a file | `[US3.1-*]` :48 |
| US3.2 scan descriptions and aliases in the loaded index | `[US3.2-*]` :49-51 |
| US3.3 append or edit instead of duplicating | `[US3.3-*]` :52-53 |
| US3.4 ambiguous: one or two `read_file`, never the whole store | `[US3.4-*]` :54-57 |
| US3.5 no match + capped area: `list_prefix(scope, area)` on that area only, check its entries the same way | `[US3.5-*]` :58-62 |
| US3.6 never `list_prefix(scope)` | `test_filing_body_omits_phrase[US3.6-*]` :94 |
| US3.7 only at file creation; appends do not trigger it | `[US3.7-*]` :63-64 |
| US4.1 every write carries new nicknames/acronyms/phrasings | `[US4.1-*]` :65-68 |
| US4.2 `aliases` on the same `append_line`/`replace_fact`, or in `write_file` on create/restructure | `[US4.2-*]` :69-79 |
| US4.3 entire search surface | `[US4.3-*]` :80 |
| US4.4 removing an alias is a `write_file` | `[US4.4-*]` :81 |

## Architecture / ADR changes

- N/A. Section wording is not API (ADR 0025 decision 2); no deviation from
  Notion §8.1.

## Deviations from spec

- None.

## Look closely at

- The full `BODY` prose in `src/wenchang/prompts/filing.py`.
- Overlap with AIE-1051: both sections say removing an alias is a
  `write_file`. Kept here per the orchestrator's content requirements; drop
  it from one section at merge if the assembled prompt reads as repetitive.

## Follow-ups

- Behavioral evaluation scenarios in spec.md, for the §10.3 eval harness.

## Adversarial review findings

Spec rounds: see review-spec.md (round 1 FAIL: capped listing ungated,
descriptive alias sentence, 1051 overlap; round 2 PASS).

Code round 1:
- Reviewer A (correctness/fidelity): PASS, 4 NITs. Applied: the capped-area
  listing now says to "check its entries the same way"; tighter pins for
  US3.3 ("creating a duplicate"). Not applied: spelling out that a
  restructuring `write_file` must resend the aliases to keep (replace
  semantics belong to the `write_file` docstring and AIE-1051); the
  weak-match-plus-capped-area edge case is left to evaluation.
- Reviewer B (tests/docs): FAIL, 1 SHOULD-FIX. The US4.2 pin "same" did not
  tie `aliases` to the same call; replaced with
  "`aliases` on the same `append_line` or `replace_fact` call". Also
  strengthened the US3.5 pin to "listed under `capped` in the index".
  Confirmed no ARCHITECTURE/ADR/glossary change is needed.
- Round 2: reviewer B PASS (2 NITs on spec.md row 4.2 formatting, applied).
- Final gate (spec-reviewer): PASS, 17/17 criteria, 3 NITs (1051 overlap
  already flagged; US3.6 negative pin is token-exact; eval scenario 4 cites
  `cursor` paging, owned by the docstring). No change.
