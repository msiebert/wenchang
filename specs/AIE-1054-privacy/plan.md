# Implementation Plan: Privacy refusal categories

**Linear issue**: AIE-1054 | **Branch**: `AIE-1054-privacy` | **Date**: 2026-10-05 | **Spec**: [spec.md](spec.md)

## Summary

One constant: `wenchang.prompts.privacy.BODY`. One new test file:
`tests/test_prompts_privacy.py`. No other source, test, or doc file
changes.

## Technical Context

Python >= 3.12; pyright strict; ruff line length 100. No new dependencies,
no import changes in `src/`.

## Constitution Check

| Principle | Status |
| --------- | ------ |
| I. Tests-first | T1 test-writer (fails against `BODY = ""`) -> implementer |
| II. Tests not negotiable | No existing test touched |
| VI. Spec fidelity | Text follows Notion §8.1 Privacy; no deviation, so no ADR |
| VII. Architecture documented | No public API, boundary, or storage change; ADR 0025 decision 2 says section wording is not API |
| VIII. Traceability | Test docstrings cite AIE-1054 |

## Interface (what tests may rely on)

- Module: `wenchang.prompts.privacy` (import as `from wenchang.prompts import privacy`).
- `privacy.HEADING: Final[str] == "What never to store"` (unchanged).
- `privacy.BODY: Final[str]`: flush-left triple-quoted string (`"""\`),
  markdown, ASCII only, lines <= 100 columns, under 2500 characters (target
  about 1100). Read at call time by `build_memory_prompt` as section
  `privacy`.
- `wenchang.tools.TOOL_NAMES`: the set of tool names, used by the negative
  pin.
- Pinned tokens (match after `re.sub(r"\s+", " ", BODY)`):
  - US2.1: `veto before`, `worth remembering`
  - US3.1: `financial account numbers`, `health diagnoses`,
    `indicating the user is a minor`
  - US3.2: `no matter how directly`
  - US3.3: `no scope`, `even when the user asks`
  - US3.4: `Continue the task`, `will not be kept`
  - US4.1: `shared scope`, `private scope`
  - US4.2: `disclosure to a team`, `note to self`, `version history`
  - US4.3: `unsure whether a sensitive detail is safe`, `non-sensitive part`
  - US5.1: `judgment`, `No tool filter`
- Negative pins:
  - US5.2: for every `t` in `TOOL_NAMES`, `re.search(rf"\b{t}\b", BODY)` is
    `None`; `"`" not in BODY`.
  - US5.3: none of `team scope`, `personal scope`, `public scope`,
    `user scope` (case-insensitive) appears.

## Proposed BODY text

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

Traceability of each sentence:

- Veto and ordering: addendum decision 7; design doc section order. The
  veto is limited to what this section refuses, so it does not contradict
  the graduated paragraph.
- Three categories, "refused outright", "no matter how directly": §8.1
  sentence 1. "or willingly" comes from the orchestrator content
  requirements and is redundant with "even when the user asks".
- Nowhere, no scope, even when asked, and what to do instead: Linear
  content requirements, a necessary consequence of "refused outright".
- Scope graduation and its reason: §8.1 sentence 2. "the store keeps no
  version history" places that clause on the whole store, so it is not
  read as a shared-only property.
- Unsure-in-shared rule: orchestrator content requirements for this issue
  ("when unsure in a shared scope, do not write, or write the non-sensitive
  part to the private scope"), applying "tighter in shared scopes". It is
  limited to sensitive detail so it does not read as a general filing rule.
- Judgment and no filter, no false comfort: §8.1 sentences 3-4 ("a filter
  catching only some cases would overstate its coverage").

## Files

- `src/wenchang/prompts/privacy.py` (`BODY` only)
- `tests/test_prompts_privacy.py` (new)
- `specs/AIE-1054-privacy/`
