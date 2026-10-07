# PR Review: AIE-1054 — Privacy refusal categories

## What changed & why

`wenchang.prompts.privacy.BODY` was empty and now holds the prose for the
"What never to store" section (position 7 of `SECTION_ORDER`). It tells the
agent three things. Financial account numbers, health diagnoses, and
anything indicating the user is a minor are refused in every scope, however
directly they are stated. Other sensitive detail gets stricter handling in
shared scopes. And this is the agent's own judgment, because no tool filter
checks content (Notion §8.1, design principle 2). Files:
`src/wenchang/prompts/privacy.py` (`BODY` only) and the new
`tests/test_prompts_privacy.py`. No other source or test file changed.

## Acceptance criteria → tests

All tests are in `tests/test_prompts_privacy.py`. Line numbers are as of
commit `d4b318f`. Phrase checks run on `BODY` with whitespace collapsed.
Every test docstring cites AIE-1054.

`make check` at `d4b318f`: lint and typecheck clean; 3332 passed, 6
skipped, 41 deselected.

| Acceptance criterion | Test(s) |
| -------------------- | ------- |
| US1.1 `BODY.strip()` non-empty | `test_privacy_body_is_non_empty` (L20) |
| US1.2 `HEADING == "What never to store"` | `test_privacy_heading` (L25) |
| US1.3 ASCII, lines <= 100 columns, `len(BODY) <= 2500` | `test_privacy_body_format` (L30); also `tests/test_prompts_invariants.py` |
| US2.1 veto before write-worthiness | `test_privacy_body_contains_phrase` (L64): `US2.1-veto-before`, `US2.1-worth-remembering` |
| US3.1 the three categories | L64: `US3.1-financial`, `US3.1-health`, `US3.1-minor` |
| US3.2 however directly stated | L64: `US3.2-no-matter-how-directly` |
| US3.3 every scope, even when asked | L64: `US3.3-no-scope`, `US3.3-even-when-asked` |
| US3.4 what to do instead | L64: `US3.4-continue-task`, `US3.4-will-not-be-kept` |
| US4.1 shared vs private scope | L64: `US4.1-shared-scope`, `US4.1-private-scope` |
| US4.2 the reason for graduation | L64: `US4.2-disclosure`, `US4.2-note-to-self`, `US4.2-version-history` |
| US4.3 unsure-in-shared rule | L64: `US4.3-unsure-sensitive-detail`, `US4.3-non-sensitive-part` |
| US5.1 judgment, not a filter | L64: `US5.1-judgment`, `US5.1-no-tool-filter` |
| US5.2 names no tool from `TOOL_NAMES`, no backtick | `test_privacy_body_names_no_tools` (L69) |
| US5.3 no off-contract scope terms | `test_privacy_body_avoids_noncanonical_scope_terms` (L79; `team scope`, `personal scope`, `public scope`, `user scope`) |

## Architecture / ADR changes

- N/A. No public API, module boundary, or storage semantics changed. ADR
  0025 decision 2 says section wording is not API and needs no ADR unless
  it deviates from the spec, and this text does not deviate from Notion
  §8.1. No new product term was introduced, so `ARCHITECTURE.md`, `docs/adr/`,
  and `docs/product/glossary.md` are unchanged.

## Deviations from spec

- None.

## Look closely at

- **The prose itself**, in full:

  ```text
  Apply this section as a veto before the previous section's test of what is worth remembering:
  if it refuses something, do not write it, however useful it seems.

  Three categories are refused outright, no matter how directly or willingly the user states
  them:

  - financial account numbers;
  - health diagnoses;
  - anything indicating the user is a minor.

  Write such information nowhere: no file, no scope, not even a private one, even when the user
  asks you to remember it. Continue the task without storing it; you may tell the user it will
  not be kept.

  For other sensitive personal detail, be stricter in a shared scope than in a private scope. A
  slip in a shared scope is disclosure to a team rather than a note to self, and the store keeps
  no version history to unwind it. When you are unsure whether a sensitive detail is safe to
  write to a shared scope, do not write it there: leave it out, or write only its non-sensitive
  part to a private scope.

  This is your judgment alone. No tool filter checks what you write for sensitive content, so a
  write that succeeds tells you nothing about whether it was safe to make.
  ```

- **"The previous section" dangles for now.** It means "Deciding what to
  remember" (`remembering`), and that body stays empty on main until
  AIE-1050 lands. `build_memory_prompt` drops sections with empty bodies, so
  until then the reference falls on whichever non-empty section comes before
  this one. That is not "Applying memory" either: `applying_memory.BODY` is
  also empty on main. In practice it is "Systems of record" when that slot
  is supplied, and otherwise "Seed areas". The wording is right once
  AIE-1050 merges, but a prompt assembled before that reads slightly off.
- **The refusal covers private scopes too.** "not even a private one" is
  on purpose: §8.1 says "refused outright", so the categories are not
  allowed in a private scope either. Only the graduated paragraph treats
  private scopes as looser.
- **"or willingly"** is not in §8.1. It comes from the orchestrator's
  content requirements and repeats "even when the user asks".
- **Tests pin vocabulary only.** They check that key phrases are present
  and that tool names and off-contract terms are absent, not that the agent
  behaves correctly (ADR 0025 decision 8). Behavior is covered only by the
  five evaluation scenarios in `spec.md`, which nothing runs yet.

## Adversarial review findings

- Reviewer A (correctness and spec fidelity), round 1: FAIL on one
  SHOULD-FIX. The unsure-in-shared sentence said "whether something
  belongs in a shared scope", which read as a general filing rule that
  could block legitimate shared writes. It is now limited to "a sensitive
  detail" (commit `d4b318f`), and the US4.3 pin tightened to
  `unsure whether a sensitive detail is safe`. The reviewer also suggested
  dropping the private-scope redirect as untraced to the Linear text; it
  stays because the orchestrator's content requirements for this issue
  ask for it. NITs not applied: "or willingly" (orchestrator requirement),
  "you may tell the user" (connective).
- Reviewer B (tests and docs), round 1: PASS. NITs: capitalized pins
  (`Continue the task`, `No tool filter`) are case-sensitive; generic
  single-word pins; this section was a placeholder. The US4.3 pin was
  tightened as part of the fix above.
- Reviewer A, round 2: PASS. Final `spec-reviewer` gate: PASS, 14/14
  criteria, no BLOCKING or SHOULD-FIX.

## Follow-ups

- AIE-1050 ("Deciding what to remember") could add a forward pointer such
  as "subject to the refusals in the next section", so the veto ordering
  is stated from both sides.
- The eval harness (Notion §10.3) should run the five behavioral scenarios
  in `specs/AIE-1054-privacy/spec.md`.
