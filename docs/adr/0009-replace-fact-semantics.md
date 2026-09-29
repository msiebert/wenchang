# 0009. replace_fact semantics

Date: 2026-09-29

## Status

Accepted

## Context

AIE-1034 delivers `replace_fact`, the third core API function: it changes
one span of a file's content — identified by an anchor string, not an
offset — without the caller resending the rest of the file. The Notion spec
(Section 5, "Replace-fact matching") requires the anchor to be unique, and
says a version conflict is re-applied against fresh content unless the
conflicting write "genuinely overlaps" the edit, escalating only then. Both
terms need an operational definition beyond a literal reading, and the
signature needs a way to stamp `sources` even though `replace_fact` takes
no metadata argument. All points below were raised and resolved at the spec
checkpoint on 2026-09-29, building on `read_file` (AIE-1032), `write_file`
and `Storage.put_if_version` (AIE-1033, ADR 0008), and `ReplaceFactMatchError`
(AIE-1030).

## Decision

- **"Genuine overlap" means the anchor no longer matches exactly once in
  the current content.** `replace_fact` has only the content at the
  caller's stale version and the content at the version it just read; it
  never has the anchor's original surrounding context to diff against.
  Testing the anchor against current content is exact and cheap. Rejected
  alternative: a three-way diff against the base content at the caller's
  version, which is unavailable without GCS object versioning (not
  assumed) and adds a second mechanism alongside the anchor check for no
  clear benefit.
- **Match-count errors split by whether the caller's `expected_version`
  is current or stale.** At the caller's own version, a count other than 1
  raises `ReplaceFactMatchError(path, content, version, count)` — the
  caller's view of the file is accurate, so the anchor itself is wrong. At
  a stale version, a non-unique match raises `VersionConflictError(path,
  content, version)` instead — the caller's view is out of date, so the
  right move is to re-read and re-derive the edit, not adjust an anchor
  against content it never saw. Rejected alternative: always raise
  `ReplaceFactMatchError` regardless of which version is stale, which would
  hand a stale caller repair material (current content) indistinguishable
  from the case where its own read was current, hiding that a concurrent
  write happened at all. Raised and approved by the human at spec review.
- **The conditional put is guarded on the version just read, not the
  caller's `expected_version`.** Re-applying an edit against fresh content
  means committing relative to that fresh content's own version; using the
  caller's original token there would just reproduce the same conflict.
  The caller's token only ever decides which error a non-unique match
  raises (the decision above).
- **Occurrences are counted at every start index, overlaps included** (so
  `"aa"` in `"aaa"` counts as 2, not 1). Rejected alternative: `str.count`,
  which reports non-overlapping matches and would call `"aa"` in `"aaa"`
  unique — an ambiguous case that shouldn't look unique.
- **`old_string == ""` raises `ValueError`, without consulting storage.**
  An empty anchor matches everywhere; there is no anchor to repair, so
  `ReplaceFactMatchError`'s repair material (current content and count)
  would not help the caller the way it does for a real mismatch.
- **The retry budget is 3 attempts, an internal constant.** Bounded
  contention handling with no caller-visible knob; no caller needs to tune
  it yet. Attempts exhausted raises `VersionConflictError` with the
  content and version read on the last attempt.
- **Metadata is taken from the object read on the attempt that commits**,
  with `source` unioned into `sources` and `last_updated` stamped from the
  store's injectable clock (a naive datetime is rejected by `FileMetadata`'s
  own validation, per ADR 0008). There is no `metadata` parameter:
  `replace_fact`'s signature is fixed by the Notion spec to
  `(path, old_string, new_string, expected_version)`, and `description` /
  `aliases` edits go through `write_file`.
- **A required keyword-only `source: str` is added beyond the Notion
  signature, unioned into `sources`.** Notion says `sources` is "stamped at
  write time" with the calling surface, but `replace_fact` takes no
  metadata argument at all — without an explicit parameter, a
  `replace_fact` write could never be recorded in `sources`, silently
  breaking that guarantee for every call through this path. Made required
  rather than optional so no write path can silently skip stamping; an
  empty `source` raises `ValueError` without consulting storage, for the
  same reason as an empty `old_string`. This is a deviation from the
  Notion signature, raised by the human at spec review. `write_file`'s own
  parity here (it currently accepts `sources` as supplied, per ADR 0008) is
  tracked separately in AIE-1109; `append_line` (AIE-1036) should follow
  the same required-`source` pattern established here.

## Consequences

`replace_fact` is testable end-to-end against `InMemoryStorage`
(`tests/test_core_replace_fact.py`), including the retry loop via a small
wrapper storage that injects a race between `get` and `put_if_version`. No
storage-layer or error-module change was needed: `replace_fact` uses
`Storage.get`, `Storage.put_if_version`, and the existing
`ReplaceFactMatchError`, `VersionConflictError`, `OversizeWriteError`, and
`NotFoundError`.

One accepted risk: retry is not idempotent when `new_string` contains
`old_string`. If a first attempt's conditional put actually lands but its
response is lost, a caller who retries with the same `expected_version` and
a `new_string` containing `old_string` will find the anchor still matches
once in the now-current content and will re-apply the edit a second time,
duplicating the change. This is accepted as ordinary, detectable editing —
the same cost the spec already accepts for `append_line`'s lack of a
version guard — rather than solved with e.g. an idempotency key, which
`replace_fact`'s signature has no room for.

`system/` read-only enforcement (AIE-1040) and role-gated scope enforcement
(AIE-1042) remain out of scope; `system/` paths are writable by
`replace_fact` until those land, as they already are for `write_file`.
