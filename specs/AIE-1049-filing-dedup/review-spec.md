# Spec Review: AIE-1049 — Filing and deduplication discipline

## What & why

The "Filing" section of the memory prompt is empty. This fills it with the
Notion §8.1 rules for where a fact goes: in the file about its subject;
before creating a file, check the index (descriptions and aliases) for an
existing one and append or edit instead; and on every write, add the names
the subject will later be looked up by as aliases, because metadata is the
only search surface.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| US1 | `filing` module | imported / assembled | heading "Filing"; body non-empty, <= 2000 chars; appears under `## Filing` in `build_memory_prompt()` |
| US2 | body | read | domain filing; seed areas are a starting shape; no restated slug rule |
| US3 | body | read | dedup before creating a file, off the index's descriptions and aliases; one or two `read_file` candidates when ambiguous, never the whole store; if nothing in the index matches and the area is capped -> `list_prefix(scope, area)` on that area only, never `list_prefix(scope)`; appends to a known file do not trigger it |
| US4 | body | read | every write carries any new nicknames/acronyms/phrasings as `aliases` on the same write that records the fact (no write tool named; AIE-1051 owns which call); reason: entire search surface (alias removal is AIE-1051's) |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| Exact prose fixed in plan.md | Let implementer draft | Prose is the deliverable; reviewers check it at the spec stage |
| Pin tokens, not sentences, after whitespace normalization | Pin the whole body | Wording can evolve without test churn; load-bearing rules stay pinned |
| Body budget 2000 chars in this test | Rely on the 2500 invariant only | Brief asks for "well under 2500" |
| Name no write tool; say aliases ride on the same write | Name the calls; explain union/replace semantics | Addendum decision 1 and orchestrator decision: which call, and mechanics, belong to AIE-1051 and the docstrings |
| Capped area: one `list_prefix(scope, area)` | Forbid listing entirely | Addendum decision 4; matches the `get_memory_index` docstring |

## Files/modules to be touched

- `src/wenchang/prompts/filing.py` (`BODY` only)
- `tests/test_prompts_filing.py` (new)
- `specs/AIE-1049-filing-dedup/`

## Open questions / assumptions

- Resolved (orchestrator decision, 2026-10-05): AIE-1051 owns the
  alias-removal rule. "Removing an alias is a `write_file`." was removed
  from this section and criterion US4.4 withdrawn. A follow-up decision the
  same day also gave AIE-1051 the which-call rule: this section now says
  "on the same write that records the fact" and names no write tool.

## Risks

- Overlap with AIE-1051 (write mechanics) on aliases; mitigated by addendum
  decision 1 wording.

## Adversarial review

Round 2 (PASS, 3 NIT): stale summary rows in this file and the decision 1
boundary sentence in spec.md; all applied.

Round 1 (FAIL, 3 SHOULD-FIX, 3 NIT):
- SHOULD-FIX: tool list and removal sentence duplicate AIE-1051 (decision 1
  "neither restates the other"). Partly applied: added decision 1's
  qualifier so `write_file` is "when you create or restructure a file", not
  a peer of the same-call tools. Kept the tool names and removal sentence
  because the orchestrator's content requirements name them explicitly;
  recorded under Open questions.
- SHOULD-FIX: the capped-area listing ran even after an index match. Fixed:
  gated on "If nothing there matches"; pin 3.5 extended.
- SHOULD-FIX: alias sentence descriptive and over-literal ("every write
  adds names"). Fixed: "Every write should carry any new names ..."; pin
  4.1 updated.
- NITs applied: "the index you loaded with `get_memory_index()`" (no
  re-call implied; pin 3.2 updated); "finds a file" (antecedent); "Put
  each fact in the file".
