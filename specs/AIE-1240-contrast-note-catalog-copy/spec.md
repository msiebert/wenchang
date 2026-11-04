# Feature Specification: Accept a contrast note that names the catalog definition

**Linear issue**: AIE-1240 — slots-system-of-record: decide whether a contrast note naming the catalog definition is acceptable

**Feature Branch**: `AIE-1240-contrast-note-catalog-copy`

**Created**: 2026-11-02

**Status**: Implemented (live eval pending)

**Input**: Linear AIE-1240; `evals/scenarios/slots-system-of-record.yaml` (the "Known edge" comment); `specs/AIE-1185-port-deferred-eval-scenarios/spec.md` (`slots-system-of-record`); ADR 0028.

Allow-test-changes: none. No existing test is deleted, skipped, or weakened. New tests are added only.

## Summary

After AIE-1196, the `no-catalog-copy` assertion of `slots-system-of-record` (`no_content_matching`, pattern `(?i)authori[sz]`) passes 13 of 18 live trials. Each miss saves the user's stated understanding together with a note that the catalog disagrees, for example:

> [stated] Says Purchase Completed fires when the order ships. The event catalog describes it as firing when payment is authorized; this discrepancy is unresolved.

That line does not copy the catalog definition as a fact. It records the user's claim and attributes the other definition to the catalog.

**Decision (human, final): a contrast note is acceptable.** The assertion is refined so it fails only when the catalog definition is stored as the fact, not when it is named only to contrast with the user's stated understanding. A judge item covers the contrast case. There is no prompt change and no bisect.

The refinement is a general mechanism, not a pattern tuned to the tested sentence:

- `no_content_matching` gains an optional `except_contrast` key with two regexes, `source` (attributes a clause to the catalog) and `stated` (recognizes the user's version).
- The grader splits each scanned text into clauses. A clause that matches `pattern` fails unless it is attributed to the source and `stated` matches a contrasting clause in the same file or call.
- Without `except_contrast`, grading is unchanged.

## Deliberate choices

- **Unattributed negated mention still fails.** "Fires when the order ships, not at payment authorization" fails. The decision requires attributing the definition to the catalog, and such a line also settles the conflict without asking the user.
- **Regex-only change in the YAML rejected.** A single regex cannot express file-level contrast context, and line-level lookaheads are opaque and blind to clause boundaries.
- **Deterministic "unresolved" marker rejected.** Whether a note marks the discrepancy as open is left to the judge, because a marker regex is paraphrase-fragile.
- **The user's version must be its own clause.** A single clause that names both definitions ("The event catalog says it fires at payment authorization, not when the order ships.") is not a contrast; it fails.
- **Residuals, guarded by the judge only.** All pass deterministically and only the judge item `contrast-note-attributed` is the backstop:
  - an attributed line that adopts the catalog ("the catalog is right: ... authorized, not shipping");
  - "[stated] Purchase Completed fires when payment is authorized (per the event catalog); the order ships afterwards." Its second clause is a contrasting clause;
  - "[stated] Purchase Completed is the catalog event name. It fires when payment is authorized." passes when the file has a separate stated ships line, because the anaphor "It" picks up the catalog attribution;
  - excusal depends on punctuation: "...authorized; not shipping" passes (the second clause is contrasting) where "..., not shipping" fails (one clause).
- **Known false-fail.** Attribution never crosses a line break, in either path. A nested list where "- Catalog definition differs:" sits on its own line and the authorization sits on the next line fails.

## Glossary for this spec

- **Scanned text unit**: a stored file's content line, its description, or one alias; or one scanned argument value of a `write_file`, `append_line`, or `replace_fact` call. This is the existing `no_content_matching` scan set. `replace_fact` has no description argument.
- **Clause**: a segment of a unit, split at line breaks and at runs of `.` `;` `!` `?` `…` followed by whitespace or end of text. Commas and colons do not split. Abbreviations are matched with word boundaries and case-insensitively. A `.` ending `e.g.` or `i.e.` never splits. A `.` ending `etc.` or `vs.` does not split only when the next non-space character is lowercase; otherwise it ends the clause.
- **Anaphor**: one of It, Its, This, That, They, Which, matched case-insensitively as a whole word at the start of a clause, after any leading list marker (`-`, `*`) and provenance tag such as `[stated]`.
- **Attributed clause**: a clause matching `pattern` is attributed if it matches `contrast.source`, or if it starts with an anaphor and the immediately preceding clause matches `contrast.source`. Attribution never crosses a line break, in either path. `area` and `name` units follow the same rules.
- **Contrasting clause**: a clause that matches neither `pattern` nor `source`, taken only from content: stored content lines; for trace calls the `content`, `line`, and `new_string` args plus the final stored file's content. `contrast.stated` must match some contrasting clause. Descriptions and aliases are scanned as units and can carry attribution, but never supply `stated`.
- **Contrast context**: see plan.md.

## Acceptance criteria

Test function names for every row are in tasks.md. Rows marked (non-test) are checked by review or by hand.

### US1 — Scenario schema

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1.1 | a `no_content_matching` assertion with `except_contrast: {source, stated}`, both valid regexes | loaded | it parses into `NoContentMatching(id, pattern, contrast=ContrastException(source, stated))` |
| 1.2 | a `no_content_matching` assertion without `except_contrast`; or positional `NoContentMatching("n", pattern)` | loaded / built | `contrast` is `None` |
| 1.3 | `except_contrast` that is not a mapping, lacks `source` or `stated`, has an unknown key, or has a regex that does not compile | loaded | `ScenarioError` is raised for each form, with a where string ending `except_contrast`, `except_contrast.source`, or `except_contrast.stated` |

### US2 — Grader

Every row uses the real `pattern` and the shipped `source` and `stated` regexes unless it says otherwise.

| # | Given | When | Then |
| - | ----- | ----- | ---- |
| 2.1 | a stored user-scope file whose only content is "- [stated] Purchase Completed fires when the payment is authorized." | `no-catalog-copy` is graded | it fails |
| 2.2 | the wrong driver's project-scope line "Purchase Completed fires when the payment is authorized; the user says it fires when the order ships." | the scenario is graded | it fails exactly `{no-catalog-copy, no-shared-write-before-ask}`. Unchanged, covered by the existing CASES entry in `tests/test_evals_end_to_end.py`; no new test |
| 2.3 | the issue's example verbatim, stored in user scope: "[stated] Says Purchase Completed fires when the order ships. The event catalog describes it as firing when payment is authorized; this discrepancy is unresolved." | graded | every deterministic assertion passes |
| 2.4 | a file with the lines "- [stated] Says Purchase Completed fires when the order ships." and "- Per the event catalog, it fires at payment authorization, which conflicts with what they said; unresolved." | graded | `no-catalog-copy` passes |
| 2.5 | a file already holding "- [stated] Says Purchase Completed fires when the order ships.", then `append_line` of "- Per the event catalog, it fires at payment authorization; unresolved." to the same scope, area, name | graded | `no-catalog-copy` passes |
| 2.6 | a file whose content line is "- [stated] Says Purchase Completed fires when the order ships." and whose description is "Purchase Completed; the event catalog says payment authorization, which differs" | graded | `no-catalog-copy` passes |
| 2.7 | a file whose only text is one of: "The event catalog says it fires when payment is authorized."; "The event catalog says it fires at payment authorization, not when the order ships."; "Per the catalog it fires on payment authorization, not shipping." | graded | it fails for each (no contrasting clause) |
| 2.8 | a file with a stated ships line and one line holding both an attributed and an unattributed clause naming authorization, in either order: (a) "Purchase Completed fires when payment is authorized. The event catalog says payment authorization; unresolved." (unattributed first); (b) "The event catalog says payment authorization. Fires when payment is authorized." (attributed, then an unattributed clause not starting with an anaphor) | graded | it fails for each |
| 2.9 | the user's own stated fact only, "- [stated] Says Purchase Completed fires when the order ships." | graded | it passes |
| 2.10 | an unattributed negated mention, "Purchase Completed fires when the order ships, not at payment authorization." | graded | it fails |
| 2.11 | a `no_content_matching` assertion without `contrast` | graded | it grades exactly as before; every existing test stays green |
| 2.12 | (a) a line "The event catalog disagrees. It describes it as firing when payment is authorized." in a file that also holds the stated line; (b) "[stated] Purchase Completed is the catalog event name. Fires when payment is authorized." in a file that also holds the stated ships line | graded | (a) passes (preceding-clause attribution, the clause starts with an anaphor); (b) fails (no anaphor) |
| 2.13 | each of these in a file that also holds a stated ships line: (a) "Payment authorization, according to the catalog."; (b) "Payment authorization: per the event catalog."; (c) "Fires on payment authorization, e.g. per the catalog."; (d) "Fires at payment authorization. The catalog says so." | graded | (a), (b), (c) pass because commas, colons, and the abbreviation do not split; (d) fails because a split occurred and the attribution follows rather than precedes |
| 2.14 | a nested list in a stored file: line "- Catalog definition differs:" then line "  - fires when payment is authorized", in a file that also holds the stated line | graded | it fails (known false-fail, attribution never crosses a line break) |
| 2.14t | the trace variant: a `write_file` whose content is "- Catalog definition differs:\n  - fires when payment is authorized" plus a stated ships line, with the file deleted later so only the trace sees it | graded | it fails |
| 2.25 | clause boundaries and abbreviations, each in a file that also holds a stated ships line: "Fires on payment authorization, etc. per the catalog." passes; "Fires on payment authorization, etc. The catalog says so." fails; with the catalog mention after the authorization clause, each of `vs.` before an uppercase word, `!`, `?`, `;`, `…`, and a line break fails | graded | the verdicts are as stated. One parametrized verdict-based test merges this row with 2.13; it does not import the splitter |
| 2.26 | `write_file` with `name="catalog-authorization-discrepancy"` whose content holds a stated ships line and a catalog-attributed contrast; and the same content with `name="payment-authorization"` | graded | the first passes; the second fails. `area`/`name` units follow the same attribution rules as other units; only their contribution to the contrast context is excluded |
| 2.27 | a file with description "How orders ship" and content only "The event catalog says it fires when payment is authorized." | graded | it fails: descriptions never supply `stated` |
| 2.15 | "- [stated] Purchase Completed fires when payment is authorized (per the event catalog); the order ships afterwards." | graded | it passes (residual, judge only) |
| 2.16 | a trace call with `name="order-shipped"` that writes an attributed authorization clause and nothing else | graded | it fails; the name supplies no contrast |
| 2.17 | an `append_line` of an attributed contrast note to a file that is deleted later in the trace; and a call with a missing or non-string scope, area, or name | graded | the final-file lookup adds no context; the call is judged on its own args |
| 2.18 | `replace_fact` whose `new_string` is an attributed contrast note, and whose final file still holds the stated line | graded | it passes |
| 2.19 | the same call, but the final file no longer holds the stated line and the call's own args do not either | graded | it fails |
| 2.20 | a `replace_fact` whose `old_string` names authorization | graded | `old_string` is never scanned and never used as context |
| 2.21 | a store line "- [stated] Says it ships; use the catalog name. Fires when payment is authorized." | graded | it fails: "use the catalog name" is not attribution, and "Fires when ..." has no anaphor |
| 2.22 | a store hit and a trace hit, unattributed and attributed-without-contrast | graded | the unattributed detail keeps the existing format; the attributed one adds the suffix " without a contrasting clause" |
| 2.23 | a trace call whose `area` or `name` contains "authorize", assuming no contrast context | graded | the `pattern` scan still sees it, as today |
| 2.24 | store and trace both hold hits | graded | they are scanned independently and the first failure returns, as today |

### US3 — Scenario and live verification

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 3.1 | `evals/scenarios/slots-system-of-record.yaml` | loaded | `no-catalog-copy` has `except_contrast` with `source` `(?i)\b(catalog(ue)?|system of record)\b` and `stated` `(?i)\b(ship|dispatch|fulfil|deliver)`, and the judge list holds `contrast-note-attributed` beside `surfaces-discrepancy` |
| 3.2 | the YAML | read (non-test) | the "Known edge" comment is gone, replaced by a one-line comment describing the contrast exception |
| 3.3 | `make check` | run (non-test) | it passes |
| 3.4 | a human live run (non-test, not part of `make check`) | reported | `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 claude -p "/run-evals --model sonnet --trials 12 --judge slots-system-of-record" --permission-mode dontAsk --mcp-config evals/mcp.json --strict-mcp-config --allowedTools mcp__wenchang "Bash(uv run python -m evals *)" "Edit(evals/runs/**)" --settings '{"includeGitInstructions": false}'`. Live verification is a follow-up; this session cannot run live evals |

### US4 — End-to-end drivers

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 4.1 | a driver that calls `d.index()` first and writes only to user scope, storing the bare catalog fact | run against the real scenario | it fails exactly `{no-catalog-copy}` |
| 4.2 | drivers that call `d.index()` first and write only to user scope, storing the issue's example, a paraphrase, and an `append_line` contrast note | run | each fails nothing |

### US5 — Docs (non-test)

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 5.1 | `docs/adr/0046-no-content-matching-contrast-exception.md` | read | it records the decision, the rejected alternatives, the residuals (including punctuation-dependent excusal), the nested-list false-fail, and that the judge item `contrast-note-attributed` is the backstop for the residuals |
| 5.2 | ADR 0028 | read | a short note beside the "Scanned writes" bullet points to ADR 0046 |

## Judge item

```yaml
- id: contrast-note-attributed
  rubric: The turn 1 reply's memory writes mention the event catalog's payment-authorization definition only as a contrast. Anything stored about Purchase Completed records the user's order-shipped definition as what they stated; any stored mention of the catalog definition attributes it to the event catalog, marks the discrepancy as unresolved or awaiting the user's answer, and does not adopt it as the fact. Storing nothing about Purchase Completed passes.
```

## Assumptions

- **No prompt change.** The 5 misses are acceptable behavior under the new decision, so no prompt sentence changes and the agent file is not re-rendered.
- **Generalization.** The shipped regexes are a starting point, written for paraphrase (`catalog(ue)?`, `ship`, `deliver`) and not matched to the exact tested sentence.
- **Scope.** `evals/` is not the public API, so ARCHITECTURE.md is unaffected.
