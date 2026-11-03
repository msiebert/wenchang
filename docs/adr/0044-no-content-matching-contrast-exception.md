# 0044. `no_content_matching` contrast exception

Date: 2026-11-02

## Status

Accepted. Amends [ADR 0028](0028-behavioral-eval-harness.md) (the scan rules of
`no_content_matching`).

## Context

`slots-system-of-record` asserts `no-catalog-copy` with `no_content_matching`
and pattern `(?i)authori[sz]`, so the agent does not copy the event
catalog's definition into memory. After AIE-1196 it passed 13 of 18 live
trials. Each miss stored the user's stated definition together with a note
that the catalog disagrees, for example "[stated] Says Purchase Completed
fires when the order ships. The event catalog describes it as firing when
payment is authorized; this discrepancy is unresolved." That is not a copy
of the catalog definition as a fact. The human decided a contrast note is
acceptable. The assertion must fail only when the catalog definition is
stored as the fact.

## Decision

`no_content_matching` takes an optional `except_contrast: {source, stated}`,
two regexes. Without it, grading is unchanged. With it:

1. Each scanned text unit is split into clauses at line breaks and at
   `.` `;` `!` `?` `…` followed by whitespace or end of text. Commas and
   colons do not split. `e.g.` and `i.e.` never split; `etc.` and `vs.` split
   only before a non-lowercase word.
2. A clause matching `pattern` is attributed if it matches `source`, or if it
   starts with an anaphor (It, Its, This, That, They, Which) and the preceding
   clause on the same line matches `source`.
3. An unattributed hit fails. An attributed hit passes only if `stated`
   matches a contrasting clause: a clause matching neither `pattern` nor
   `source`, taken from content only (stored content lines; for trace calls
   `content`, `line`, `new_string`, and the final stored file's content).
   Descriptions, aliases, `area`, and `name` are scanned as units but never
   supply `stated`.
4. The contrast context is per file or per call, never pooled across files.

The shipped scenario uses `source` `(?i)\b(catalog(ue)?|system of record)\b`
and `stated` `(?i)\b(ship|dispatch|fulfil|deliver)`, and gains the judge item
`contrast-note-attributed`. The prompt does not change.

Rejected alternatives:

- **Regex-only change in the YAML.** A single regex cannot express file-level
  contrast context, and line-level lookaheads are opaque and blind to clause
  boundaries.
- **A deterministic "unresolved" marker.** Whether a note marks the
  discrepancy as open is paraphrase-fragile, so it is left to the judge.
- **Accepting any negated mention.** "Fires when the order ships, not at
  payment authorization" still fails: the decision requires attributing the
  definition to the catalog, and such a line settles the conflict without
  asking the user.
- **A prompt change or bisect.** The misses are acceptable behavior.

## Consequences

- **Residuals are judge-only.** These pass deterministically and only
  `contrast-note-attributed` is the backstop:
  - an attributed line that adopts the catalog ("the catalog is right: ...
    authorized, not shipping");
  - "[stated] Purchase Completed fires when payment is authorized (per the
    event catalog); the order ships afterwards.", whose second clause is
    contrasting;
  - "[stated] Purchase Completed is the catalog event name. It fires when
    payment is authorized." with a separate stated ships line, because the
    anaphor "It" picks up the attribution.
- **Excusal depends on punctuation.** "...authorized; not shipping" passes
  because the second clause is contrasting, where "..., not shipping" fails
  as a single clause.
- **Nested-list false-fail.** Attribution never crosses a line break, so
  "- Catalog definition differs:" on one line and the authorization on the
  next fails.
- A live run of `slots-system-of-record` is the human follow-up that checks
  the miss rate and the judge item.
