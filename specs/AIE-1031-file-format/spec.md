# Feature Specification: File format and metadata — parse and serialize

**Linear issue**: AIE-1031 — https://linear.app/mixpanel/issue/AIE-1031/file-format-and-metadata-parse-and-serialize

**Feature Branch**: `AIE-1031-file-format`

**Created**: 2026-09-25

**Status**: Draft

**Input**: Linear AIE-1031 and Notion "Agent Memory Library — Specification",
Section 4 (File format and metadata), with Section 5 (GCS custom metadata
carries the four fields) and Section 10.2 (round-trip fidelity).

## Summary

Define the in-memory shape of a memory file and the two conversions every
later core function relies on:

- **Body**: the markdown content of a file ↔ a sequence of lines, where each
  line is either a *fact* (leading bracketed confidence label) or *other*
  markdown (headings, blank lines, prose) kept verbatim.
- **Metadata**: the four fixed fields (`description`, `aliases`, `sources`,
  `last-updated`) ↔ a flat string-to-string map, which is the shape of GCS
  custom object metadata. Metadata is stored beside the body, not inside it
  (Notion Section 5: metadata rides on the object, committed atomically with
  content).

This issue covers pure conversion only: no storage, no size limit, no
path handling. The core functions that use it (`read_file`, `write_file`,
`append_line`, `replace_fact`, `list_prefix`) are separate issues that
depend on this one.

## User Scenarios & Testing *(mandatory)*

The "user" is a caller inside the library: a core API function, the storage
layer, or a test. It needs to turn stored bytes into structured facts and
metadata and back without losing anything.

### User Story 1 - Recognize fact lines and their confidence (Priority: P1)

A caller reads a file body and gets each fact's confidence label and text,
with non-fact markdown preserved rather than rejected.

**Why this priority**: Confidence labels are the only per-line structure the
format has; every later editing function operates on fact lines.

**Independent Test**: Parse bodies containing each label, non-fact lines,
and near-miss syntax, and inspect the result.

**Acceptance Scenarios**:

1. **Given** the line `- [stated] activation means the second purchase`,
   **When** it is parsed, **Then** it is a fact with label *stated* and text
   `activation means the second purchase`.
2. **Given** lines using each of `[stated]`, `[observed]`, `[inferred]`,
   `[system]`, **When** parsed, **Then** each is a fact with the matching
   label.
3. **Given** a body containing a heading, a blank line, and a prose line
   alongside fact lines, **When** parsed, **Then** the non-fact lines are
   returned as *other* lines with their text unchanged, in their original
   positions.
4. **Given** a line whose bracketed label is not one of the four
   (`- [guessed] x`), is uppercase (`- [Stated] x`), lacks the leading
   `- ` (`[stated] x`), lacks the space after the label (`- [stated]x`), or
   has no text after the label (`- [stated]` or `- [stated] `), **When**
   parsed, **Then** it is an *other* line, not a fact.
5. **Given** a confidence label and fact text, **When** a fact line is
   formatted, **Then** the result is `- [<label>] <text>`.
6. **Given** fact text containing a newline, or text that is empty or only
   whitespace, **When** a fact is constructed, **Then** construction is
   rejected (such a fact could not be parsed back as a fact).

---

### User Story 2 - Body round-trips byte-for-byte (Priority: P1)

A caller that parses a body and serializes it again gets back exactly the
string it started with.

**Why this priority**: Notion Section 10.2 requires write-then-read
fidelity, including markdown that resembles the fact-line syntax; a lossy
parser would silently rewrite the agent's files.

**Independent Test**: For a corpus of bodies, `serialize(parse(body)) ==
body`.

**Acceptance Scenarios**:

1. **Given** any body string, **When** it is parsed and serialized,
   **Then** the result equals the original exactly.
2. **Given** bodies with and without a trailing newline, **When**
   round-tripped, **Then** the presence or absence of the trailing newline is
   preserved.
3. **Given** the empty body, **When** round-tripped, **Then** the result is
   the empty body.
4. **Given** a body with unicode text, `\r\n` line endings, consecutive
   blank lines, and near-miss fact syntax, **When** round-tripped, **Then**
   the result equals the original exactly.
5. **Given** a non-empty sequence of fact and other lines built by a caller,
   **When** serialized and parsed, **Then** the same sequence comes back.
6. **Given** a sequence containing an other line that contains a newline, or
   whose text would itself parse as a fact, **When** it is serialized,
   **Then** serialization is rejected (it could not round-trip).

---

### User Story 3 - Metadata round-trips through a string map (Priority: P1)

A caller converts file metadata to the flat string map stored with the
object and back, with every field intact.

**Why this priority**: `description` and `aliases` are the entire search
surface (Notion Section 4); if they are lost or corrupted in storage,
navigation breaks.

**Independent Test**: Convert metadata to a map and back and compare; parse
malformed maps and check rejection.

**Acceptance Scenarios**:

1. **Given** metadata with a description, aliases, sources, and a
   last-updated timestamp, **When** it is converted to a map, **Then** the
   map has exactly the keys `description`, `aliases`, `sources`,
   `last-updated`, each with a string value.
2. **Given** any valid metadata, **When** converted to a map and back,
   **Then** the result equals the original.
3. **Given** aliases or sources containing commas, quotes, brackets, or
   unicode, **When** round-tripped, **Then** each entry is unchanged.
4. **Given** aliases in a particular order, **When** round-tripped, **Then**
   the order is preserved.
5. **Given** sources supplied with duplicates, **When** metadata is
   constructed, **Then** each source appears once (sources are a set).
6. **Given** a timezone-aware last-updated timestamp, **When** round-tripped,
   **Then** the same instant comes back, and its map value is an ISO 8601
   string in UTC.
7. **Given** a naive (no timezone) last-updated timestamp, **When** metadata
   is constructed, **Then** construction is rejected.
8. **Given** a description containing a newline, **When** metadata is
   constructed, **Then** construction is rejected (the description is one
   line).
9. **Given** a map missing any of the four keys, or with a value that does
   not decode (aliases not a list of strings, last-updated not an ISO 8601
   timestamp with a timezone), **When** it is parsed, **Then** parsing is
   rejected with an error naming the offending key.
10. **Given** a map with extra keys beyond the four, **When** parsed,
    **Then** the extra keys are ignored.
11. **Given** empty aliases and empty sources, **When** round-tripped,
    **Then** both come back empty.

### Edge Cases

- A line that is only `- [stated]` followed by whitespace is *other*: fact
  text is everything after the single separating space and must contain at
  least one non-whitespace character. Text that begins with further spaces
  (`- [stated]   x`) is a fact whose text is `  x`, preserving round-trip.
- `\r` is not a line separator; in a `\r\n` body the `\r` stays at the end of
  the line's text. Only `\n` splits lines.
- A fact line whose text itself contains a bracketed label
  (`- [stated] [observed] x`) is a *stated* fact with text `[observed] x`.
- The empty body parses to a single empty other line; a body of `\n` parses
  to two empty other lines. An empty sequence is not a valid body to
  serialize.
- Leading indentation (`  - [stated] x`) is *other*; facts are top-level
  list items.
- Alias and source strings may be empty strings; the format does not police
  their content. Deciding what a valid source name is belongs to the caller.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The library MUST define exactly four confidence labels:
  stated, observed, inferred, system, rendered lowercase in brackets.
- **FR-002**: The library MUST parse a body into an ordered sequence of
  lines, each either a fact (label + text) or other (verbatim text).
- **FR-003**: Serializing a parsed body MUST reproduce the original string
  exactly, for every input string.
- **FR-004**: The library MUST define file metadata with exactly the four
  fields: description (single line), aliases (ordered list), sources (set),
  last-updated (timezone-aware timestamp).
- **FR-005**: The library MUST convert metadata to and from a flat
  string-to-string map with keys `description`, `aliases`, `sources`,
  `last-updated`, losslessly for all valid metadata.
- **FR-006**: Parsing a malformed metadata map MUST be rejected with an
  error that names the offending key.
- **FR-007**: The file format MUST have no dependency on storage, transport,
  scope, or agent frameworks.

### Key Entities

- **Confidence label**: stated / observed / inferred / system.
- **Fact**: a label plus single-line text.
- **Body line**: a fact, or any other markdown line kept verbatim.
- **File metadata**: description, aliases, sources, last-updated.
- **Metadata map**: the flat string map stored beside the body.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of a round-trip corpus (including unicode, `\r\n`,
  trailing/no trailing newline, empty, and near-miss syntax) survives body
  parse-then-serialize unchanged.
- **SC-002**: 100% of valid metadata survives map conversion and back
  unchanged.
- **SC-003**: Every malformed-map case is rejected with the offending key
  named; none is silently defaulted.

## Assumptions

- Metadata is stored as object custom metadata beside the body, not as
  frontmatter in the markdown (Notion Section 5). The issue's "raw markdown
  into metadata plus fact lines" is read as "stored object into metadata
  plus fact lines".
- Aliases and sources are encoded in the map as JSON arrays of strings;
  sources are written sorted so the encoding is deterministic.
- `last-updated` is encoded as ISO 8601 in UTC with a `Z` suffix and
  microsecond precision when present.
- A malformed metadata map is a data-integrity problem, not an agent-facing
  condition, so it raises a plain `ValueError` subclass rather than a
  taxonomy error from AIE-1030.
- Facts are `- ` list items at the start of a line, as in the Notion
  examples.
- Tolerating non-fact lines is a parser robustness property only, not part
  of the file format presented to the agent. The prompt layer and
  agent-facing tool descriptions describe a file as fact lines only and
  never mention headings, prose, or other line kinds. Module docstrings
  describe *other* lines as tolerated input, not as supported content.
- Validating that a whole body contains only facts, the size limit, and
  stamping `last-updated`/`sources` at write time belong to the core
  function issues (AIE-1033 onward).
