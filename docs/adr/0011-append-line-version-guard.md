# 0011. append_line version guard

Date: 2026-09-29

## Status

Accepted

## Context

AIE-1036 delivers `append_line`, the fifth core API function. Notion
Section 5 originally specified `append_line(path, line)` with no version
guard, on the rationale in Section 10.2 ("append commutativity") that
appends at different offsets commute and so don't need one. That design
has a duplicate-on-retry problem: if a caller's append lands but the
response is lost (timeout, connection drop), a naive retry re-appends the
same line, and nothing in an unguarded call can tell the retry from a new,
deliberate append. Every other mutating call in `core` (`write_file`,
`replace_fact`) is already version-guarded (ADR 0008 note; ADR 0009); an
unguarded `append_line` would be the one exception to that pattern.

This was raised and resolved at the spec checkpoint on 2026-09-29. Notion
(Sections 5, 10.2, 11) and the Linear issue were both updated to specify a
required `expected_version`, matching the spec in
`specs/AIE-1036-append-line/spec.md`.

## Decision

- **`append_line` takes a required `expected_version`, guarding every
  mutating call in `core`.** A stale token raises
  `VersionConflictError(path, current_content, current_version)`
  immediately, carrying the file's current state so the caller can decide
  whether to retry.
- **No automatic re-apply on a stale token, unlike `replace_fact`.**
  `replace_fact` re-applies a unique anchor match against a newer version
  because doing so is safe: matching the same anchor again produces the
  same edit. Re-applying an append is never safe the same way — an append
  always succeeds against any content, so re-applying after a stale-token
  failure would duplicate a line that already landed on a previous attempt.
  The guard therefore always surfaces to the caller rather than absorbing
  a concurrent write.
- **A landed-write check after a precondition failure.** The GCS client
  retries conditional uploads on its own (timeout, dropped response), so a
  `PreconditionFailedError` from `put_if_version` doesn't necessarily mean
  someone else won the race — it can mean this call's own write landed and
  a subsequent backend-level retry of the same upload saw the file already
  at the new generation. `append_line` re-reads on precondition failure; if
  the stored bytes and metadata equal exactly what it tried to write, it
  returns that as success instead of raising, and does not write again. If
  they differ, or the object is now gone, it raises `VersionConflictError`
  or `NotFoundError(FILE_ABSENT)` as usual.
- **A missing file raises `NotFoundError(FILE_ABSENT)` and is never
  created.** A file created by an append would have no `description` or
  `aliases`, the only search surface (Notion Section 4); files are created
  only by `write_file`.
- **`line` must parse as exactly one fact line (`parse_fact(line) is not
  None`).** Empty strings, plain prose, an unrecognized label, or more
  than one line all raise `ValueError` before storage is consulted, as does
  an empty `source`.
- **A `"\n"` separator is inserted when the existing content is non-empty
  and doesn't already end in one**, so the append never extends the
  previous last line.

## Consequences

Concurrent appends to the same file no longer commute transparently: when
two callers hold the same version and both append, the first lands and the
second gets `VersionConflictError` carrying the first's line, and must
retry with the returned version. This is the cost of making every write
guarded — no sequence of retries of one logical append can produce a
duplicate line (spec SC-001), at the price of a conflict-and-retry turn for
genuinely concurrent appends. Agent-facing tool wording (AIE-1044) must
present that conflict as routine, the same as any other `VersionConflictError`,
not as an unusual failure. The Section 10.2 "append commutativity"
conformance case (AIE-1045) becomes "concurrent appends: one lands, the
other conflicts and lands on retry."

No `Storage` protocol change is needed — `append_line` is built entirely
from existing `get` / `put_if_version`, the same shape as `write_file`.

**Alternatives rejected:**

- **Unguarded append (the original Notion design).** Simplest for the
  caller and lets concurrent appends commute, but a retried append that
  landed once can duplicate a line with no way for `core` to detect it.
  Rejected because retry safety was judged more important than that
  convenience, especially since transport-layer retries (timeouts) are
  expected to be common.
- **Optional `expected_version`.** Would let some callers opt out of the
  guard, reintroducing the duplicate-on-retry problem for anyone who
  didn't have a version handy, and would make `append_line` the only
  mutating call with an inconsistent guarantee. Rejected in favor of making
  it required, matching `write_file` and `replace_fact`.
- **An internal compare-and-swap retry loop inside `append_line` itself**
  (read-modify-write in a loop until the conditional put succeeds, as
  `replace_fact` effectively does for its anchor re-apply). Rejected
  because it reintroduces exactly the commutativity assumption being
  removed — the loop would silently re-append against a newer version,
  duplicating a line whenever the caller's own earlier attempt had already
  landed. Surfacing the conflict is what makes the caller's retry
  distinguishable from a duplicate.
