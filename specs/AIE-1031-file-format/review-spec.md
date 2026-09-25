# Spec Review: AIE-1031 — File format and metadata: parse and serialize

## What & why

A pure `wenchang.file_format` module that turns a stored file into
structured parts and back: the markdown **body** ↔ lines (each a
confidence-labeled fact like `- [stated] …`, or any other markdown kept
verbatim), and the four **metadata** fields ↔ the flat string map stored as
GCS object metadata. Every later file operation (`read_file`, `write_file`,
`replace_fact`, `append_line`, `list_prefix`) builds on it, and it must not
lose a byte.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | `- [stated] x` (and each of the 4 labels) | parsed | fact with that label, text `x` |
| 2 | wrong/uppercase label, no `- `, no space, empty text, indented | parsed | kept as an *other* line, not a fact |
| 3 | headings, blanks, prose among facts | parsed | kept verbatim, in position |
| 4 | fact text with a newline or only whitespace | constructed | rejected |
| 5 | **any** body string (unicode, `\r\n`, no trailing newline, empty) | parsed then serialized | identical bytes |
| 6 | caller-built line sequence | serialized then parsed | same sequence; other lines containing `\n` or that look like facts rejected |
| 7 | metadata | to map | exactly keys `description`, `aliases`, `sources`, `last-updated`, all strings |
| 8 | any valid metadata (commas/quotes/unicode in aliases) | to map and back | equal; alias order kept; sources deduped |
| 9 | naive timestamp, or description with a newline | constructed | rejected |
| 10 | map missing a key or with an undecodable value | parsed | `MetadataFormatError` naming the key; extra keys ignored |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| Metadata stored **beside** the body (GCS custom metadata), not in the markdown | YAML frontmatter in the body | Notion §5 says metadata rides on the object, committed atomically; the issue's "raw markdown → metadata" wording is read as "stored object → metadata" |
| **Lenient, lossless** body parser: non-fact lines kept | Reject any non-fact line | §10.2 requires byte-for-byte round-trip. Robustness only: prompts and tool descriptions present files as facts only and never mention other line kinds |
| Facts are `- [label] text` exactly: lowercase, top-level list item | Accept `[label]` without `- `, any case | One canonical form keeps parsing unambiguous and round-trip exact |
| `aliases`/`sources` as JSON arrays; `last-updated` as ISO 8601 UTC `Z` | Comma-joined strings | Aliases can contain commas; JSON is lossless |
| `sources` is a `frozenset`, written sorted | Ordered tuple | Notion calls it a set; sorting makes the stored form deterministic |
| Malformed map → `MetadataFormatError(ValueError)` | A taxonomy error from AIE-1030 | It's corrupted data, not something an agent can repair |
| Top-level `wenchang.file_format` module | Inside the planned `core` package | Storage and core both need it; keeps it dependency-free |

## Files/modules to be touched

- `src/wenchang/file_format.py` (new), `tests/test_file_format.py` (new)
- `ARCHITECTURE.md`, a new ADR in `docs/adr/`, possibly `docs/product/glossary.md`

## Open questions / assumptions

- **Please confirm: metadata as object metadata, not frontmatter.** This is
  the main decision. Frontmatter would change the parser, the size-limit
  math, and the storage contract.
- Body validation (e.g. "only facts allowed"), the 16 KB limit, and stamping
  `last-updated`/`sources` on write are left to AIE-1033 and later issues.

## Risks

- If `write_file` later decides to require facts only, it enforces that on
  top of this parser, so nothing here changes.
- The GCS JSON API limits the total size of custom metadata (about 8 KB).
  Very long alias lists could reach it. This issue doesn't enforce that limit.
