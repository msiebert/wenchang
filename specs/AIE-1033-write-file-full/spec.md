# Feature Specification: write_file — full-file replace with version guard and size ceiling

**Linear issue**: AIE-1033 — https://linear.app/mixpanel/issue/AIE-1033/write-file

**Feature Branch**: `AIE-1033-write-file`

**Created**: 2026-09-28

**Status**: Draft

**Input**: Linear AIE-1033 and Notion "Agent Memory Library — Specification",
Section 5 (`write_file(path, content, metadata, expected_version)` is a
full-file replace; content and metadata commit atomically or not at all;
optimistic locking with one version token per file; a version conflict is
routine and returns current content and version; oversize writes are
rejected against a configurable per-file byte ceiling, default 16 KB,
returning size and limit), Section 4 (`last-updated` is refreshed on any
write), and Section 10.2 (atomicity, conflict semantics, enforcement).
Builds on the storage layer and `read_file` from AIE-1032 (ADR 0007).

## Summary

Add `MemoryStore.write_file`, the second core API function, and the
conditional write the storage layer needs to support it:

- **Storage layer**: a conditional put that commits only if the object's
  current version matches an expected token, or — when no token is given —
  only if no object exists yet. On mismatch it reports a precondition
  failure and writes nothing. Both implementations (in-memory fake, GCS)
  pass the same conformance cases.
- **`write_file`**: validates the path, enforces the byte ceiling, and
  conditionally replaces the whole file. On a stale token it raises the
  recoverable `VersionConflictError` carrying current content and version.

Out of scope: `system/` read-only enforcement (AIE-1040), role-gated scope
enforcement (AIE-1042), `append_line`, `replace_fact`, `delete_file`, and
the agent-facing tool wording (AIE-1044).

## User Scenarios & Testing *(mandatory)*

The "user" is a caller inside the library — the transport layer, a later
core function, or a test — replacing a memory file's whole content and
metadata.

### User Story 1 - Create a new file (Priority: P1)

A caller writes a file that does not exist yet, passing no expected
version, and gets back the stored file with its first version token.

**Why this priority**: Every file starts here; without it the store stays
empty.

**Independent Test**: Call `write_file` with `expected_version=None` at an
empty path, then `read_file` it.

**Acceptance Scenarios**:

1. **Given** no file at a valid path, **When** `write_file(path, C, M,
   None)` is called, **Then** it returns a `MemoryFile` with the path as
   given, content `C`, the stored metadata, and a version token; and a
   subsequent `read_file(path)` returns the same content, metadata, and
   token.
2. **Given** a file already exists at the path, **When** `write_file(path,
   C, M, None)` is called, **Then** `VersionConflictError` is raised with
   the existing file's content and version, and the existing file is
   unchanged.

---

### User Story 2 - Replace an existing file under a version guard (Priority: P1)

A caller that read a file at version `V` replaces it wholesale, passing
`V`. If nobody wrote in between, the replace lands; if someone did, the
caller gets the current state to merge from.

**Why this priority**: This is the optimistic-locking contract every
mutating call depends on (Notion Section 5, "Concurrency").

**Independent Test**: Write, read, write again with the read token; then
write with a stale token and inspect the error.

**Acceptance Scenarios**:

1. **Given** a file at version `V`, **When** `write_file(path, C2, M2, V)`
   is called, **Then** it returns a new token `V2 != V`, and `read_file`
   returns `C2`, the stored metadata for `M2`, and `V2`.
2. **Given** a file written at `V`, then again at `V2`, **When**
   `write_file(path, C3, M3, V)` is called with the stale `V`, **Then**
   `VersionConflictError` is raised with `path` as given, `content` equal
   to the content stored at `V2`, and `version == V2`; and the file is
   unchanged.
3. **Given** a `VersionConflictError` carrying version `Vc`, **When** the
   caller retries `write_file(path, C, M, Vc)`, **Then** the write
   succeeds.
4. **Given** a well-formed path with no file, **When** `write_file` is
   called with a non-`None` expected version, **Then** `NotFoundError`
   with reason `FILE_ABSENT` is raised and nothing is written.
5. **Given** an expected version token that no write ever produced (any
   opaque string, including a non-numeric one), **When** `write_file` is
   called on an existing file, **Then** `VersionConflictError` is raised
   with the current content and version — never a parse error.
6. **Given** a successful write whose response was lost, **When** the
   caller retries with the same expected version, **Then**
   `VersionConflictError` is raised whose content equals what the first
   attempt wrote (retry safety, Notion Section 5 "Transient").

---

### User Story 3 - Content and metadata commit together (Priority: P1)

A reader never observes one write's content with another write's
metadata, and a rejected write changes nothing.

**Why this priority**: Constitution / Notion Section 10.2 "Atomicity".

**Acceptance Scenarios**:

1. **Given** a file written with `(C1, M1)` then `(C2, M2)`, **When** it is
   read, **Then** it returns `C2` with metadata for `M2` — never a mix.
2. **Given** any rejected `write_file` (invalid path, oversize, version
   conflict, file absent), **Then** a following `read_file` returns exactly
   what it returned before the attempt, including the same version token.
3. **Given** content containing unicode, `\r\n`, fact-line-like markdown,
   no trailing newline, or the empty string, and metadata with unicode,
   commas, quotes, and brackets in aliases and sources, **When** it is
   written and read back, **Then** content is byte-for-byte equal and
   `description`, `aliases`, and `sources` are equal.

---

### User Story 4 - Oversize writes are rejected with repair material (Priority: P1)

A caller that writes content over the per-file byte ceiling is told the
size and the limit so it can split the file.

**Why this priority**: The ceiling guarantees a read fits in one response
(Notion Section 5, "Size limit").

**Acceptance Scenarios**:

1. **Given** a store with the default ceiling, **When** content whose UTF-8
   encoding is exactly 16384 bytes is written, **Then** the write succeeds.
2. **Given** a store with the default ceiling, **When** content whose UTF-8
   encoding is 16385 bytes is written, **Then** `OversizeWriteError` is
   raised with `path`, `size == 16385`, `limit == 16384`, and storage is not
   written.
3. **Given** content of multi-byte characters, **Then** size is counted in
   UTF-8 bytes, not characters (e.g. 5462 `"€"` = 16386 bytes is rejected).
4. **Given** a store constructed with `max_file_bytes=100`, **When** 101
   bytes are written, **Then** `OversizeWriteError` reports `limit == 100`;
   100 bytes succeed.
5. **Given** `max_file_bytes` of `0` or a negative number, **When** a
   `MemoryStore` is constructed, **Then** `ValueError` is raised.
6. **Given** an oversize write whose expected version is also stale,
   **Then** `OversizeWriteError` is raised (size is checked before storage
   is consulted).

---

### User Story 5 - last-updated is refreshed by the write (Priority: P2)

Every write stamps the file-level `last-updated` itself, so the field is
reliable for index ordering (Notion Sections 4 and 5).

**Acceptance Scenarios**:

1. **Given** a `MemoryStore` constructed with a clock returning `T` (a
   timezone-aware datetime), **When** `write_file` is called with metadata
   whose `last_updated` is `T0 != T`, **Then** the stored and returned
   metadata have `last_updated == T`, and `description`, `aliases`, and
   `sources` are exactly as supplied.
2. **Given** a `MemoryStore` constructed without a clock, **When** a file
   is written, **Then** `last_updated` is timezone-aware UTC within the
   bounds of the call.
3. **Given** a clock returning a naive datetime, **When** `write_file` is
   called, **Then** `ValueError` is raised and nothing is written.

---

### User Story 6 - Invalid paths and backend failures (Priority: P2)

**Acceptance Scenarios**:

1. **Given** a malformed path (per the AIE-1032 path rule), **When**
   `write_file` is called, **Then** `NotFoundError` with reason
   `INVALID_PATH` is raised and storage is not consulted.
2. **Given** storage raising `BackendUnavailableError` on the conditional
   put or on the follow-up fetch after a precondition failure, **Then** it
   propagates unchanged.
3. **Given** the GCS implementation, **When** the upload fails its
   generation precondition, **Then** the storage layer reports a
   precondition failure (not a GCS exception); timeouts and unavailability
   map to `BackendUnavailableError` as for `get`.

---

### User Story 7 - The fake and GCS agree on conditional put (Priority: P1)

**Acceptance Scenarios** (storage conformance, run against both):

1. **Given** no object at a key, **When** a conditional put with expected
   `None` is made, **Then** it returns a token and a get returns the
   object.
2. **Given** an object at a key, **When** a conditional put with expected
   `None` is made, **Then** `PreconditionFailedError` is raised and the
   object is unchanged.
3. **Given** an object at version `V`, **When** a conditional put with `V`
   is made, **Then** it returns a new token and a get returns the new bytes
   and metadata together.
4. **Given** an object at version `V2` (after `V`), **When** a conditional
   put with `V` is made, **Then** `PreconditionFailedError` is raised and
   the object is unchanged.
5. **Given** no object at a key, **When** a conditional put with a
   non-`None` token is made, **Then** `PreconditionFailedError` is raised
   and no object is created.
6. **Given** a token string no put produced (including a non-numeric one),
   **When** a conditional put uses it, **Then** `PreconditionFailedError`
   is raised.

### Edge Cases

- `system/` paths are writable in this issue; read-only enforcement is
  AIE-1040 and will be added in front of this call.
- The byte ceiling applies to content only. Metadata is not counted.
- Empty content is valid.
- A conflict fetch that finds the file deleted since the failed put raises
  `NotFoundError(FILE_ABSENT)`.
- A conflict fetch whose stored object is corrupt propagates
  `MetadataFormatError` / `UnicodeDecodeError` as `read_file` does.
- The path in the result and in errors is the caller's string, unchanged.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The storage protocol MUST provide a conditional put
  `put_if_version(key, data, metadata, expected)` where `expected` is a
  `VersionToken` (commit only if the current version equals it) or `None`
  (commit only if no object exists), raising `PreconditionFailedError` on
  mismatch and writing nothing.
- **FR-002**: The in-memory and GCS implementations MUST pass one shared
  conformance suite for the conditional put, including unrecognized and
  non-numeric tokens.
- **FR-003**: `MemoryStore.write_file(path, content, metadata,
  expected_version)` MUST replace content and metadata in one storage
  write and return the stored `MemoryFile`.
- **FR-004**: On precondition failure, `write_file` MUST fetch the current
  object and raise `VersionConflictError(path, current_content,
  current_version)`, or `NotFoundError(FILE_ABSENT)` if it is absent.
- **FR-005**: `write_file` MUST raise `NotFoundError(INVALID_PATH)` for a
  malformed path without consulting storage.
- **FR-006**: `write_file` MUST raise `OversizeWriteError(path, size,
  limit)` when the content's UTF-8 byte length exceeds the store's
  ceiling, without consulting storage. The ceiling MUST default to 16384
  bytes and be configurable per `MemoryStore`; a non-positive value MUST be
  rejected at construction.
- **FR-007**: `write_file` MUST set `last_updated` from the store's clock,
  overriding the caller's value; the clock MUST default to current UTC and
  be injectable.
- **FR-008**: No module other than the GCS storage implementation MUST
  import or call the GCS client library, or parse a version token.

### Key Entities

- **Conditional put**: bytes, metadata map, expected token or `None`.
- **Precondition failure**: storage-level signal, not a taxonomy error.
- **Byte ceiling**: per-`MemoryStore` integer, default 16384.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of conditional-put conformance cases pass against both
  the in-memory fake and GCS (fake-gcs-server).
- **SC-002**: Every rejected write in the test corpus leaves the stored file
  and its token unchanged.
- **SC-003**: The size boundary is exact: limit bytes accepted, limit + 1
  rejected, for both the default and a configured ceiling.

## Assumptions

- `expected_version=None` means "create; the file must not exist." Creating
  a file is the one mutating call with no token to hold, and GCS expresses
  it natively (`ifGenerationMatch=0`).
- A non-`None` token against an absent file is `FILE_ABSENT`, not a
  conflict: there is no current content to return, and the correction is
  to create the file.
- `OversizeWriteError.size` is the attempted write's byte size, matching
  the error's existing wording from AIE-1030.
- `last-updated` is stamped by the core layer because every write path
  (`write_file`, and later `append_line` and `replace_fact`) goes through
  it; callers cannot forget to refresh it. `sources` is stored as supplied;
  stamping the calling surface belongs to the tool layer.
- An unrecognized token is treated as a mismatch, not rejected as
  malformed — callers may not parse tokens, so the library cannot ask them
  to supply well-formed ones.
