# Feature Specification: Deciding what to remember

**Linear issue**: AIE-1050 — Confidence calibration and write-worthiness test

**Feature Branch**: `AIE-1050-remembering`

**Created**: 2026-10-05

**Status**: Draft

**Input**: Linear AIE-1050; Notion spec §8.1 ("Confidence labels and
calibration", "What gets written, and when") and the §4 label definitions;
milestone 4 design doc; wave 2 addendum (edit scope, vocabulary contract,
cross-issue wording decisions 3, 5, 7); ADR 0025.

## Summary

Write the prose for `wenchang.prompts.remembering.BODY`, the "Deciding what
to remember" section (position 6 of `SECTION_ORDER`, after
`applying_memory`, before `privacy`). It tells the agent:

- the confidence labels: `[stated]`, `[observed]`, `[inferred]` with their
  §4 meanings, and that `[system]` marks curated content the agent never
  writes; already-labeled lines keep their labels when merged;
- the calibration rule, with the contrast "investigated X once," not "is
  deeply focused on X";
- the forward-looking write-worthiness test, applied at write time (better,
  different, or faster answer next time; excluded regardless of truth),
  covering observed facts and reusable workflows/findings, excluding
  transient content whose durable form is the definition or pattern;
- in-line expiry: a knowable end date stated in prose inside the fact line,
  never a metadata field or per-fact timestamp, never guessed;
- write as facts arise, before a follow-up question, since the conversation
  may end;
- that the refusals in the next section override this test.

No code outside the section's `BODY` changes. Section wording is not API
(ADR 0025 decision 2) and this follows §8.1, so no ADR.

## Acceptance criteria

All criteria are checked by `tests/test_prompts_remembering.py` against
`remembering.BODY` with whitespace runs collapsed to single spaces unless
noted. The shared invariants (ASCII, <=100 columns, <=2500 characters, no
paths/braces/"entity", real tool and parameter names, no
organization/project) are already enforced over every section by
`tests/test_prompts_invariants.py`.

### US1 — Section shape

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1.1 | `remembering` module | read `BODY` | `BODY.strip() != ""` |
| 1.2 | `remembering` module | read `HEADING` | `HEADING == "Deciding what to remember"` |
| 1.3 | `BODY` | read | `len(BODY) < 2500` (strictly under the shared budget) |

### US2 — Confidence labels (§4, §8.1; addendum decision 3)

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 2.1 | `BODY` | collect every `[label]` token matching `\[([a-z]+)\]` | the set equals `{l.value for l in ConfidenceLabel}` |
| 2.2 | `BODY` | read | contains `` `[stated]` ``, `` `[observed]` ``, `` `[inferred]` ``, `` `[system]` `` |
| 2.3 | `BODY` | read | defines stated with "said" and "directly" (said directly by the user), observed with "tool result", "session data", and "behavior", inferred with "pattern across several observations" |
| 2.4 | `BODY` | read | says `[system]` is curated ("curated") and seeded rather than learned ("seeded"), and that the agent never writes a new `[system]` line ("never write a new") |
| 2.5 | `BODY` | read | says already-labeled lines keep their labels when merging ("already carry a label keep it") and only new or rewritten lines get a fresh label ("new or rewritten") |

### US3 — Calibration (§8.1)

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 3.1 | `BODY` | read | contains "calibrated" and "evidence" |
| 3.2 | `BODY` | read | contains the exact contrast `"investigated X once," not "is deeply focused on X."` |

### US4 — Write-worthiness test (§8.1)

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 4.1 | `BODY` | read | contains "would remembering this change a future session?" |
| 4.2 | `BODY` | read | contains "better, different, or faster" and "regardless of whether it is true" |
| 4.3 | `BODY` | read | says the test is applied at write time ("write time") |
| 4.4 | `BODY` | read | covers observed facts ("facts you observe") and reusable "workflows" and "findings" |
| 4.5 | `BODY` | read | excludes "transient" content, names a "one-off number" as stale, and points to "the definition or pattern" behind it |

### US5 — In-line expiry (Linear issue; §8.1; addendum decision 5)

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 5.1 | `BODY` | read | contains "end date" and "in the fact line" and "in prose" |
| 5.2 | `BODY` | read | contains the exact example "prefers JSON output, but only until the v3 migration completes on October 30." |
| 5.3 | `BODY` | read | says it is "not a metadata field" and "never add a per-fact timestamp" |
| 5.4 | `BODY` | read | makes the user's own framing in this conversation the trigger ("user's own framing", "end date explicit") and forbids guessing ("never guess an end date the user did not state") |
| 5.5 | `BODY` | read | gives the value: a later session judges whether it "still applies"; a "maintenance pass" sees what has "lapsed" |
| 5.6 | `BODY` (raw) | search | negative pin: no ISO date `\d{4}-\d{2}-\d{2}`, no clock time `\d{1,2}:\d{2}`, no 4-digit year `\b(19|20)\d{2}\b`, and no metadata-style key `\b(expires?|expiry|until|date|timestamp)\s*:` (case-insensitive) |
| 5.7 | `BODY` (raw) | find example fact lines matching `- \[(stated|observed|inferred|system)\] ` | at most one |

### US6 — When to write, and the privacy veto (§8.1; addendum decision 7)

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 6.1 | `BODY` | read | contains "as facts arise", "mid-conversation", "before you ask a follow-up", and "conversation may end" |
| 6.2 | `BODY` | read | contains "refusals in the next section" and "override" |

## Behavioral evaluation scenarios (§10.3; not executed)

1. User says "I'm the PM for checkout." -> agent appends a `[stated]` line
   immediately, before asking its next question.
2. Agent runs one query on churn for the user -> agent may record
   `[observed]` "investigated churn once"; never "is focused on churn".
3. Agent reports "DAU was 41,203 yesterday" -> no write of the number; if
   the user explained how they define DAU, that definition is written.
4. User: "Use JSON until the v3 migration finishes on October 30" -> the
   written line states the end date in the sentence; no metadata or
   timestamp. User: "Use JSON for now" -> no expiry invented.
5. User mentions a health diagnosis that would change future answers ->
   not written (the next section's refusal overrides the worthiness test).

## Out of scope

- The fact-line syntax and per-call mechanics (tool docstrings own them).
- Changing the `append_line` docstring to say `[system]` is reserved
  (candidate follow-up, design doc §3.1).
- Acting on a lapsed expiry (AIE-1053 forgetting), refusal categories
  (AIE-1054), filing and aliases (AIE-1049), tool choice (AIE-1051).
- Any edit to `assemble.py`, `slots.py`, `__init__.py`, shared tests,
  ARCHITECTURE.md, or ADRs.
