# Spec Review: AIE-1054 — Privacy refusal categories

## What & why

Fills the empty `privacy` section of the memory prompt ("What never to
store"). It tells the agent that financial account numbers, health
diagnoses, and anything indicating the user is a minor are never written,
however directly stated; that other sensitive detail is held to a tighter
standard in shared scopes, because a slip there is disclosure to a team
with no version history to unwind it; and that this is the agent's own
judgment because no tool filter checks content (Notion §8.1, design
principle 2).

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| US1 | `privacy` module | read | body non-empty; heading "What never to store"; ASCII, <= 100 cols, <= 2500 chars |
| US2 | body | read | it is a veto that runs before the write-worthiness test |
| US3 | body | read | the three categories, "no matter how directly", in no scope, even when asked; continue the task, may say it will not be kept |
| US4 | body | read | "shared scope"/"private scope"; disclosure to a team vs note to self, no version history; unsure in shared -> do not write, or only the non-sensitive part to a private scope |
| US5 | body | read | "judgment", "No tool filter"; names no tool, no backticks; no off-contract scope terms |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| Prompt-only; no classifier | Tool-layer filter for account numbers etc. | §8.1: detection over free-form markdown is not exact; a partial filter overstates coverage |
| Name no tools | "do not call `write_file`/`append_line`..." | Pure judgment section; the veto covers every write path, so listing tools invites gaps |
| Refusal covers private scopes too | Allow refused categories in a private scope | §8.1 "refused outright"; Linear "however directly stated" |
| Unsure in shared -> nothing, or non-sensitive part to a private scope | Ask the user each time | Linear content requirements; avoids inventing an ask rule |
| No ADR | ADR for the section | Wording is not API (ADR 0025 decision 2); no deviation from §8.1 |

## Files/modules to be touched

- `src/wenchang/prompts/privacy.py` (`BODY` only)
- `tests/test_prompts_privacy.py` (new)

## Open questions / assumptions

- None requiring a human. The text says "a private scope" (not "the"),
  since an adopter may have more than one.

## Adversarial review

- Round 1 (FAIL): the opening veto sentence read as vetoing the whole
  section, contradicting the graduated paragraph (now limited to what the
  section refuses, and imperative); "in no scope, private scopes included"
  was a near double negative with a loose antecedent (now "Write such
  information nowhere: no file, no scope, not even a private one");
  spec.md allowed either/or pins that plan.md did not (now exact tokens).
  NITs applied: "the store keeps no version history" so it is not read as
  shared-only; stronger `veto before` pin; eval scenarios 3 and 5
  aligned with the refused categories. Noted: "previous section" points
  at whichever non-empty section precedes privacy until the remembering
  body lands (empty sections are omitted).
- Round 2 (PASS): all pins and invariants re-verified mechanically
  (1103 chars, longest line 94 columns); two cosmetic NITs, no change.

## Risks

- Graduation depends on the adopter's `scope_guidance` saying which scopes
  are shared or private (ADR 0025 decision 7); the library cannot check it.
- Tests pin vocabulary, not behavior; behavior is covered only by the
  evaluation scenarios in spec.md.
