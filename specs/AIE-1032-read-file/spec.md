# Feature Specification: read_file and the storage layer it reads through

**Linear issue**: AIE-1032 — https://linear.app/mixpanel/issue/AIE-1032/read-file

**Feature Branch**: `AIE-1032-read-file`

**Created**: 2026-09-25

**Status**: Draft

**Input**: Linear AIE-1032 and Notion "Agent Memory Library — Specification",
Section 5 (Core library API: `read_file(path)` returns content, metadata, and
version token; GCS generation backs the opaque token; error taxonomy "Not
found" distinguishes an invalid path from a file that does not exist yet),
with Section 3 (path layout) and Section 10.2 (round-trip fidelity, token
opacity). Storage layer per ADR 0003.

## Summary

Deliver the first core API function, `read_file(path)`, and the internal
storage layer every core function goes through:

- **Storage layer** (ADR 0003): a narrow protocol mirroring GCS object
  semantics — an object is bytes plus a flat string metadata map plus a
  generation that changes on every write — with two implementations: an
  in-memory fake for unit tests and a GCS implementation. This issue gives
  the protocol exactly two operations, *get* and unconditional *put*. *Put*
  exists so tests (and the next issue, `write_file`) can place objects;
  generation-match preconditions on *put* are added by AIE-1033.
- **`read_file(path)`**: validates the path, fetches the object, and returns
  the file's content, its four metadata fields, and an opaque version token.

Out of scope: `write_file` and all other core functions, preconditions /
version conflicts, size limits, scope resolution and authorization, and
listing.

## User Scenarios & Testing *(mandatory)*

The "user" is a caller inside the library — the transport layer, a later
core function, or a test — that needs a memory file's current state and a
token proving which version it saw.

### User Story 1 - Read an existing file (Priority: P1)

A caller reads a file at a valid path and gets back its content, metadata,
and version token.

**Why this priority**: Every read-modify-write flow in the library starts
here; without it there is nothing to hand back on a version conflict and
nothing for the agent to edit.

**Independent Test**: Place an object through the storage layer, call
`read_file`, and compare every returned field.

**Acceptance Scenarios**:

1. **Given** a file stored at a valid path with body `B` and metadata `M`,
   **When** `read_file(path)` is called, **Then** it returns content equal
   to `B`, metadata equal to `M`, the path as given, and a version token.
2. **Given** a stored body containing unicode, `\r\n` line endings, a
   trailing newline or none, markdown resembling fact-line syntax, or the
   empty string, **When** it is read, **Then** the returned content equals
   the stored body exactly.
3. **Given** metadata whose aliases and sources contain commas, quotes,
   brackets, or unicode, and a timezone-aware last-updated timestamp,
   **When** the file is read, **Then** each metadata field equals what was
   stored.
4. **Given** a file that has not changed between two reads, **When** it is
   read twice, **Then** both reads return equal version tokens.
5. **Given** a file that is read, then overwritten, then read again, **When**
   the two version tokens are compared for equality, **Then** they differ,
   and the second read returns the new content and metadata.
6. **Given** a version token returned by `read_file`, **Then** it is a
   `VersionToken` (an opaque string); callers are not given any integer or
   ordering over it.

---

### User Story 2 - Missing files and invalid paths are distinguishable (Priority: P1)

A caller that reads a path where nothing exists learns whether the path
itself is wrong or the file simply hasn't been created yet, because the
corrections differ (Notion Section 5: correct the path, or create the file).

**Why this priority**: The agent's next move depends on it; conflating the
two makes the agent either create files at nonsense paths or give up on a
file it should create.

**Independent Test**: Call `read_file` on malformed paths and on
well-formed paths with no object, and inspect the error.

**Acceptance Scenarios**:

1. **Given** a well-formed path with no object stored at it, **When** it is
   read, **Then** `NotFoundError` is raised with reason `FILE_ABSENT` and
   the path as given.
2. **Given** a malformed path, **When** it is read, **Then**
   `NotFoundError` is raised with reason `INVALID_PATH` and the path as
   given, and storage is not consulted.
3. Malformed paths include: the empty string; a leading or trailing `/`; an
   empty segment (`a//b`); a `.` or `..` segment; a segment containing a
   backslash or a control character; fewer or more than four segments; and a
   final segment that does not end in `.md` or is exactly `.md`.
4. **Given** a well-formed path such as `user/u_42/preferences/editor.md`,
   **When** it is validated, **Then** it is accepted; unicode and spaces
   within segments are allowed.
5. **Given** a stored object at `user/u_42/preferences/editor.md`, **When**
   `user/u_42/preferences/Editor.md` is read, **Then** `FILE_ABSENT` is
   raised (paths are case-sensitive).

---

### User Story 3 - Storage failures surface in the right category (Priority: P2)

A caller whose read fails because the backend is slow or unreachable gets a
transient error it can retry; a stored object that is corrupt is not
disguised as a routine condition.

**Why this priority**: The error category is what tells the agent what to
do next (Notion Section 5); a mis-categorized failure makes it loop or give
up wrongly.

**Independent Test**: Use a storage stub that raises, and store corrupt
objects in the fake, then call `read_file`.

**Acceptance Scenarios**:

1. **Given** storage that raises `BackendUnavailableError` (timeout or
   unavailable), **When** `read_file` is called, **Then** the same error
   propagates unchanged.
2. **Given** the GCS implementation, **When** the underlying client call
   times out, **Then** it raises `BackendUnavailableError` with reason
   `TIMEOUT`; **when** it fails with a server-unavailable / internal error /
   connection failure, **Then** it raises `BackendUnavailableError` with
   reason `UNAVAILABLE`.
3. **Given** a stored object whose metadata map is missing a field or
   malformed, **When** it is read, **Then** `MetadataFormatError` (from
   AIE-1031) propagates, naming the offending key.
4. **Given** a stored object whose bytes are not valid UTF-8, **When** it is
   read, **Then** a `ValueError` is raised (not a `WenchangError`).

---

### User Story 4 - The fake and GCS behave identically (Priority: P1)

A test author can trust that behavior verified against the in-memory fake
holds against GCS.

**Why this priority**: Constitution Principle V — the fake must match GCS
semantics exactly, or unit tests stop predicting production.

**Independent Test**: A single storage conformance suite, run against the
fake in unit tests and against the GCS implementation in integration tests
(fake-gcs-server).

**Acceptance Scenarios**:

1. **Given** a key with no object, **When** it is fetched, **Then** the
   result is "absent" (not an error).
2. **Given** bytes and a metadata map put at a key, **When** the key is
   fetched, **Then** the same bytes and the same map come back, including
   non-ASCII bytes and unicode metadata values.
3. **Given** a put, **Then** it returns a version token, and a subsequent
   fetch reports that same token.
4. **Given** two successive puts to one key, **Then** the second token
   differs from the first, and a fetch returns the second put's bytes and
   metadata together (never the second's bytes with the first's metadata).
5. **Given** puts to two different keys, **Then** each fetch returns its own
   object; a key is not a prefix match (`a/b.md` does not return `a/b.md.bak`).
6. **Given** a metadata map returned by a fetch, **When** the caller mutates
   it, **Then** a later fetch is unaffected (the fake does not leak internal
   state).

### Edge Cases

- A path is validated only syntactically. Whether its first segment names a
  configured scope, or the caller may see that scope, belongs to the
  identity/scope issues (AIE-1039..1043); an unknown scope at a well-formed
  path is `FILE_ABSENT`.
- `system/` paths are readable; read-only enforcement applies to writes
  only.
- The path returned in the result and in errors is the caller's string,
  unchanged.
- Empty content with valid metadata is a valid file.
- A storage implementation returning metadata with extra keys: extras are
  ignored (as `metadata_from_map` already does).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The library MUST define an internal storage protocol with
  operations *get(key)* → object or absent, and *put(key, data, metadata)* →
  version token, where an object is bytes, a flat string-to-string metadata
  map, and a version token.
- **FR-002**: The library MUST provide an in-memory storage implementation
  and a GCS storage implementation of that protocol, both passing one shared
  conformance suite.
- **FR-003**: Each put MUST produce a new version token, distinct from every
  earlier token for that key, committed atomically with its bytes and
  metadata.
- **FR-004**: The GCS implementation MUST derive the version token from the
  object generation and MUST map timeouts and server/connection
  unavailability to `BackendUnavailableError` with the matching reason.
- **FR-005**: `read_file(path)` MUST return the path, content (decoded
  UTF-8 text, exact), metadata (`FileMetadata`), and version token.
- **FR-006**: `read_file` MUST raise `NotFoundError(INVALID_PATH)` for a
  malformed path without consulting storage, and
  `NotFoundError(FILE_ABSENT)` for a well-formed path with no object.
- **FR-007**: A well-formed path MUST be exactly
  `{scope}/{entity_id}/{area}/{name}.md`: four non-empty segments separated
  by `/`, none equal to `.` or `..`, none containing `\` or a control
  character, the last ending in `.md` with a non-empty stem.
- **FR-008**: No module other than the GCS storage implementation MUST
  import or call the GCS client library.

### Key Entities

- **Stored object**: bytes, metadata map, version token — the storage
  layer's unit.
- **Storage**: the protocol; in-memory and GCS implementations.
- **Memory file (read result)**: path, content, metadata, version token.
- **Memory path**: `{scope}/{entity_id}/{area}/{name}.md`, relative to the
  storage root.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of the storage conformance cases pass against both the
  in-memory fake and the GCS implementation (via fake-gcs-server).
- **SC-002**: 100% of a round-trip corpus (unicode, `\r\n`, trailing/no
  trailing newline, empty, fact-like markdown) reads back byte-for-byte.
- **SC-003**: Every malformed-path case yields `INVALID_PATH`; every
  well-formed missing path yields `FILE_ABSENT`; none is confused.

## Assumptions

- The storage root (`{root}` in the Notion path layout) is the storage
  instance itself — for GCS, one bucket. Paths given to `read_file` are
  relative to it. A key prefix within a bucket can be added later without
  changing callers.
- Paths have exactly one area segment, matching the Notion layout. Nested
  areas are not supported by this validator.
- The storage protocol speaks `VersionToken` directly; only the GCS
  implementation converts it to and from a generation number. No other
  code parses a token.
- Corrupt stored objects (malformed metadata map, non-UTF-8 bytes) are
  data-integrity failures, not agent-facing conditions, and surface as
  `ValueError` subclasses rather than taxonomy errors — consistent with
  ADR 0006.
- GCS failures other than timeout/unavailable (e.g. permission denied,
  bucket missing) are configuration errors and propagate uncategorized.
- `read_file` performs no scope or role check; reads are not restricted by
  the Notion spec.
- Generation-match preconditions on *put* and the version-conflict path are
  AIE-1033's scope.
