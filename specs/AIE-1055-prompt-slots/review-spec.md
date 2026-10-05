# Spec Review: AIE-1055 — Prompt layer skeleton and adopter slots

## What & why

Notion §8 says the library ships the instruction text that makes markdown
files work as memory, with adopter-specific pieces in named slots. This adds
`wenchang.prompts`: `PromptSlots` (scope guidance, seed areas, optional
systems of record), `SECTION_ORDER`, and `build_memory_prompt(slots)`, which
splices library sections and slots into one markdown prompt. It creates
every section module up front (empty bodies for AIE-1049..1054, so those
issues each touch one file), writes the overview and the generic
systems-of-record principle, and ships the §9 reference adopter config as a
test fixture. Scope priority stays on `MemoryStore(scope_priority=...)`.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| US1 | slot values | `PromptSlots(...)` | real-type `str` checks (`TypeError`), `str.__str__` + strip, blank or lone-surrogate -> `ValueError`; SoR may be `None`; frozen; all type checks before value checks |
| US2 | the package | import | `__all__` is the three names; exact `SECTION_ORDER`; nine section modules; all eleven headings non-empty and distinct, exact values pinned for the four this issue owns |
| US3 | slots | `build_memory_prompt(slots)` | `## heading\n\nbody` per non-empty section in order, joined by blank lines, one trailing `\n`, no H1; SoR = principle + list, omitted when `None`; `TypeError` on non-`PromptSlots`; positional-only |
| US4 | overview, SoR principle | read | pinned tokens (`get_memory_index()`, slug, split; canonical, interpretation, correction, discrepancy) |
| US5 | every section text | invariant scan | ASCII, <=100 cols, <=2500 chars, no `AIE-`, no paths/`entity`, tool names and parameter names real (read via `inspect.signature`), no `organization`/`project`, imports only within the package |
| US6 | §9 fixture | build | succeeds, blobs verbatim, rules present, SoR omittable, scope priority constructs a `MemoryStore` |
| US7 | docs | read | ARCHITECTURE prompts entry, glossary "Prompt slots", README adopter section, ADR 0025 |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| Subpackage, one `Final[str]` module per section | one `prompts.py`; `.md` resources | parallel issues never collide; pyright/ruff see the text |
| All section modules created now with empty bodies; assembler omits empty | each issue appends to `SECTION_ORDER` | zero shared-file conflicts; merge order cannot decide prompt order |
| `systems_of_record` optional (human, 2026-10-05) | required | adopters without a product catalog; `None` drops principle too |
| No adopter override of generic sections (orchestrator default) | omit/override API | generic text is the library's contract |
| Scope priority not in prompts | slot field | one source of truth on `MemoryStore` |
| Section bodies read at call time | snapshot at import | lets tests exercise ordering/omission before bodies land |
| Invariant test reads tool params at test time | hardcoded list | stays correct when AIE-1151 adds `aliases`/`description` |

## Files/modules to be touched

- `src/wenchang/prompts/` (12 new files)
- `tests/test_prompts_{slots,assembly,overview,systems_of_record,invariants}.py`, `tests/prompts_reference_adopter.py`
- `ARCHITECTURE.md`, `README.md`, `docs/product/glossary.md`, `docs/adr/0025-prompt-layer-sections-and-slots.md`

## Open questions / assumptions

- None beyond the 2026-10-05 decisions above.

## Risks

- Until AIE-1049..1054 land, the assembled prompt on main is overview + slots only.
- The vocabulary contract (adopter names shared vs private scopes) is documented, not checkable.

## Adversarial review

Round 1 (FAIL, 0 BLOCKING, 8 SHOULD-FIX, 5 NIT). Fixed:
- Shared-test merge surface: dropped the empty-`BODY` pins for AIE-1049..1054; exact headings pinned only for the four this issue owns.
- Pinned the sentence splitter, the tool-call regex (empty args and `...` allowed), the backticked-identifier regex, and word-boundary regexes for `entity`, `organization`, `project` (so "identity" is allowed).
- Widened the allowed identifier set to error reason / category / label enum values so later prose like `role_required` is legal.
- Fixture: added the explicit hierarchy sentence; seed-area writability now defers to each scope's write rules; blobs compared post-strip.
- Overview: "returns an index of the stored files" (the index can be capped).
- NITs: `cast(object, v)` for pyright; import-time `RuntimeError` noted as defensive; glossary changes made specific; ADR records that the overview owns "split rather than bloat".


Round 2 (FAIL, 1 BLOCKING, 2 SHOULD-FIX). Fixed: re-wrapped an overview line that was 106 columns; added a note that `\|` in the US5 table is markdown escaping and gave the real regexes; corrected the stale US2 row in this summary.

Round 3: PASS, no findings.
