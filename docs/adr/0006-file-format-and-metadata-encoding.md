# 0006. File format and metadata encoding

Date: 2026-09-25

## Status

Accepted

## Context

The Notion spec's Section 4 defines a memory file as markdown fact lines
plus four metadata fields, Section 5 says metadata rides as GCS custom
object metadata, and Section 10.2 requires write-then-read fidelity.
AIE-1031 turns that into the pure conversion functions every later core
function depends on: no storage, no size limit, no path handling. Several
points needed a decision or diverge from a literal reading of the spec
text.

## Decision

- **Metadata is stored beside the body as object custom metadata, not as
  YAML frontmatter in the markdown.** The Linear issue's wording, "raw
  markdown into metadata plus fact lines," reads literally as parsing
  frontmatter out of the markdown body. Notion Section 5 instead describes
  metadata riding on the stored object, committed atomically with content.
  This ADR reads the issue as "stored object into metadata plus fact
  lines"; the markdown body carries fact lines only. Confirmed with the
  human at the AIE-1031 spec checkpoint. Rejected alternative: YAML
  frontmatter embedded in the body, which would require the body parser to
  strip and reconstruct a frontmatter block and would duplicate metadata
  across two storage locations.
- **The body parser is lenient and lossless: non-fact lines are kept
  verbatim so any body round-trips byte-for-byte** (`serialize_body(parse_body(s))
  == s` for every string `s`), per Notion Section 10.2. This is a
  robustness property of the parser only, not an extension of the
  supported file format — the intended format is fact lines only. The
  prompt layer and agent-facing tool descriptions present a file as fact
  lines only and never mention headings, prose, or other line kinds (human
  decision; noted on AIE-1051 and relevant to AIE-1044). Whether
  `write_file` rejects a body containing non-fact lines is decided in that
  issue, not here. Rejected alternative: rejecting non-fact lines at parse
  time, which would make `parse_body` unsafe to call on arbitrary stored
  content and would break round-trip fidelity for any file with content
  outside the fact-line format.
- **Canonical fact syntax is `- [<label>] <text>`**, label one of the four
  lowercase confidence labels, as a top-level (non-indented) list item; a
  body is split into lines on `"\n"` only, never on other characters
  `str.splitlines` treats as line boundaries, so `\r` before a `\n` stays
  attached to the preceding line's text and near-miss syntax (wrong case,
  missing space, indentation) is tolerated as an *other* line rather than
  rejected.
- **Metadata map encoding**: `aliases` and `sources` are JSON arrays of
  strings; `aliases` preserves caller order, `sources` is written sorted
  (set semantics — duplicates collapse, order is not meaningful).
  `last-updated` is ISO 8601 in UTC with a `Z` suffix, including
  microseconds when present. A malformed map (missing key, undecodable
  value, or a `last-updated` without a UTC offset) raises
  `MetadataFormatError`, a `ValueError` subclass naming the offending key —
  a data-integrity problem, not an agent-facing condition, so it is not
  part of the AIE-1030 error taxonomy.
- **`file_format` is a top-level module, not folded into `core`.** It has
  no dependency on storage, transport, scope, or agent frameworks (FR-007)
  and is used by both `core` and `storage`; keeping it separate lets
  `storage` depend on it without depending on `core`.

## Consequences

Round-tripping is guaranteed for any body a caller hands in, including
content that doesn't fit the intended fact-line format, which makes
`file_format` safe to use defensively when reading files written before a
format change or by a caller outside the agent-facing tools. The tradeoff
is that `parse_body`/`serialize_body` alone cannot enforce "facts only" —
that validation, if wanted, belongs to `write_file` (AIE-1044). GCS limits
total custom metadata to about 8 KB per object; this issue does not
enforce that limit, so a caller with a very large description, alias list,
or source set can produce a map that GCS rejects at write time. `core` and
`storage` now have a shared, dependency-free vocabulary (`Fact`,
`BodyLine`, `FileMetadata`) to build on without either depending on the
other for it.
