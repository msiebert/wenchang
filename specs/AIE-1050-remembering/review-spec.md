# Spec Review: AIE-1050 — Deciding what to remember

## What & why

Writes the prompt section "Deciding what to remember" (position 6 of
`build_memory_prompt()`): the confidence labels and calibration rule, the
forward-looking write-worthiness test, in-line expiry, and writing as facts
arise. Without it the agent has the tools and the label syntax but no
judgment about what to save or how strongly to phrase it. Prose only: one
`BODY` constant, one test file.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | `remembering` | read | non-empty `BODY`, heading "Deciding what to remember", under 2500 chars |
| 2 | `BODY` | collect `[label]` tokens | set equals `ConfidenceLabel` values; stated/observed/inferred defined per §4; `[system]` is curated and never written by the agent; existing labels kept on merge |
| 3 | `BODY` | read | calibration rule with "investigated X once," not "is deeply focused on X." |
| 4 | `BODY` | read | "would remembering this change a future session?", better/different/faster, regardless of truth, at write time, observed facts and reusable workflows/findings, transient excluded in favor of the definition or pattern |
| 5 | `BODY` | read | in-line expiry with the exact JSON/v3/October 30 example, in prose in the fact line, not metadata, not a timestamp, never guessed; negative pin: no ISO date, clock time, 4-digit year, or `key:` metadata; at most one example fact line |
| 6 | `BODY` | read | write as facts arise, before a follow-up, because the conversation may end; refusals in the next section override |

Full table: spec.md US1-US6.

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| The exact `BODY` text lives in plan.md | Let implementer draft prose | Every sentence must trace to §8.1 / the issue; reviewing it at spec time is cheaper |
| Phrase pins on whitespace-collapsed text | Pin whole sentences | Re-wrapping must not break tests; tokens carry the criteria |
| Example line shown inline in backticks, labeled `[stated]` | No example; a fenced block | One example, as allowed; inline code keeps the fact syntax literal without a fence |
| Privacy pointer is one sentence ("refusals in the next section override this test") | Restate the refused categories | Addendum decision 7: privacy (AIE-1054) owns the list |
| Glossary "In-line expiry" after "Confidence label" | No glossary entry | New product term; glossary is topical, so placed beside labels |

## Files/modules to be touched

- `src/wenchang/prompts/remembering.py` (BODY)
- `tests/test_prompts_remembering.py` (new)
- `docs/product/glossary.md` (one entry)
- `specs/AIE-1050-remembering/`

## Open questions / assumptions

- None requiring a human. The `append_line` docstring still lists `[system]`
  without saying it is reserved; the prompt carries that rule (design doc
  §3.1 default).

## Risks

- Prose drifts from §8.1 in later edits: mitigated by phrase pins.
- "The refusals in the next section" is accurate once AIE-1054 fills
  `privacy.BODY`; if this merges first, the assembler skips the empty
  privacy section and the next section is filing until 1054 lands.
- The addendum says "alphabetically" for glossary entries; the glossary is
  ordered topically, so the entry goes after "Confidence label".
- Overlap with forgetting (lapsed expiry) and privacy: kept to one sentence
  each, per addendum decisions 5 and 7.

## Adversarial review

Round 1 (FAIL, 2 SHOULD-FIX, 6 NIT), all applied to the plan.md text:
- "you never write it" after `[system]` could be read as "never write
  curated content" (blocking curated corrections) and clashed with "labels
  are kept": now "you never write a new `[system]` line".
- "not a timestamp" contradicted a line that contains a date: now "you
  never add a per-fact timestamp" (§8.1 wording).
- NITs: "the user's behavior" narrowed to §4's "behavior"; "save that
  instead" softened to "save that when you know it, not the number" so the
  agent does not invent a definition; glossary entry text fixed in plan.md;
  merge-order note for the "next section" pointer added to Risks. Lowercase
  example kept (verbatim from the source); "October 30" has no year
  (verbatim; candidate note for forgetting work).

Round 2 (FAIL, 1 SHOULD-FIX, 2 NIT): "Add one only when" now pointed back at
"a per-fact timestamp"; changed to "State an end date only when". Summary
wording in spec.md aligned to "per-fact timestamp". Em dash in the glossary
entry kept (glossary house style; ASCII rule covers prompt text only).

Round 3: PASS, no findings.
