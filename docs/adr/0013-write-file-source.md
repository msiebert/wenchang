# 0013. write_file: required source, sources as a union

Date: 2026-09-30

## Status

Accepted

## Context

AIE-1109 closes the gap ADR 0009 left open: `write_file` accepted
`metadata.sources` exactly as the caller supplied it, so a replace whose
caller didn't carry the existing set forward silently erased the file's
write history, and no write through `write_file` was guaranteed to record
the calling surface. `replace_fact` (ADR 0009) and `append_line` (ADR 0011)
already require a keyword-only `source` and union it into `sources`;
`write_file` was the one write path left without that guarantee.

## Decision

- **`write_file` gains a required keyword-only `source: str`**, matching
  the pattern `replace_fact` and `append_line` already use. An empty
  `source` raises `ValueError`, checked after the path check and before the
  size check, without consulting storage — the same position and repair
  posture as `replace_fact`'s `old_string == ""` check.
- **Stored `sources` is a union, not a replacement, and only ever grows.**
  On create: `metadata.sources ∪ {source}`. On replace:
  `stored.sources ∪ metadata.sources ∪ {source}`. A caller never has to
  carry forward sources it doesn't know about, and can't remove one another
  write recorded.
  - **Rejected: ignore caller-supplied `metadata.sources`, store only
    `{source}` (on create) or `stored.sources | {source}` (on replace).**
    Simpler, but a caller migrating a file (e.g. backfilling history from
    another system) would have its `sources` silently dropped — surprising
    and unrecoverable.
  - **Rejected: reject a non-empty `metadata.sources` outright.** Would
    split `FileMetadata`'s shape by call site (the field means something
    different depending on which function is writing it) and blocks the
    migration use case above.
  - Unioning keeps one shape for `FileMetadata.sources` across every read
    and write path, and lets a caller seed history without the library
    treating that as an error. Approved by the human at spec review on
    2026-09-30.
- **Replace reads the current object before its conditional put.** A blind
  put has no stored `sources` to union with, so it would fall back to
  treating `metadata.sources | {source}` as the full set, reintroducing the
  exact history loss this issue exists to fix. The extra read is the same
  shape `replace_fact` and `append_line` already pay.
  - **Rejected: a blind conditional put, unioning only the caller's
    `metadata.sources` and `source`.** Cheaper (no extra read) but can't
    satisfy FR-004's `stored.sources ∪ metadata.sources ∪ source`.
- **Corrupt stored metadata on replace propagates `MetadataFormatError`
  and leaves the file unchanged**, rather than being overwritten. This
  matches `replace_fact` and `append_line`, both of which already read and
  parse stored metadata before writing. Overwriting a corrupt-metadata file
  would lose exactly the history this issue is trying to protect; repairing
  such a file now requires `delete_file` followed by a fresh create, not a
  `write_file` replace. Approved by the human at spec review on 2026-09-30.
- **`replace_fact` and `append_line` are unchanged**; both already require
  `source` and union it into `sources` (ADR 0009, ADR 0011).

## Consequences

Every replace through `write_file` costs one extra `Storage.get` before the
conditional put, the same cost `replace_fact` and `append_line` already
carry. No caller can ever remove a name from `sources` via `write_file` —
by design (SC-001) — so correcting a wrongly-recorded source requires
`delete_file` plus a fresh create, not a `write_file` call. No storage
protocol change was needed. This closes the parity gap ADR 0009 deferred to
this issue; `write_file`, `replace_fact`, and `append_line` now all require
`source` and union it into `sources` the same way.
