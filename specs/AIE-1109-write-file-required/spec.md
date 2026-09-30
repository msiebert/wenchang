# Feature Specification: write_file — required `source`, sources accumulate

**Linear issue**: AIE-1109 — https://linear.app/mixpanel/issue/AIE-1109/write-file-stamp-the-calling-surface-via-a-required-source-argument

**Feature Branch**: `AIE-1109-write-file-source`

**Created**: 2026-09-30

**Status**: Draft

**Input**: Linear AIE-1109 and Notion "Agent Memory Library — Specification",
Section 4 (`sources` is the "set of surface names that have written to this
file"; "whatever string the caller supplies is stamped as-is at write
time"). Follows the required-`source` pattern set by `replace_fact`
(AIE-1034, ADR 0009) and already adopted by `append_line` (AIE-1036,
ADR 0011).

## Summary

`write_file(path, content, metadata, expected_version)` currently stores
`metadata.sources` exactly as supplied. A replace whose caller does not carry
the existing set forward erases the file's write history, and nothing
guarantees the calling surface is recorded.

Add a required keyword-only `source: str` to `write_file`. The stored
`sources` becomes a union that only ever grows:

- create (`expected_version=None`): `metadata.sources ∪ {source}`
- replace: `stored.sources ∪ metadata.sources ∪ {source}`

A replace therefore reads the current object before its conditional write.

`append_line` already takes a required keyword-only `source` and unions it
into `sources` (AIE-1036); it needs no change. `replace_fact` is unchanged.

Out of scope: agent-facing tool wording (AIE-1044), transport conformance
cases (AIE-1045).

## User Scenarios & Testing *(mandatory)*

The "user" is a caller inside the library (the transport layer, tests)
creating or replacing a file on behalf of a named calling surface.

### User Story 1 - Create stamps the calling surface (Priority: P1)

**Acceptance Scenarios**:

1. **Given** no file at `path`, **When** `write_file(path, content,
   metadata(sources=frozenset()), None, source="chat")` is called, **Then**
   the stored and returned `sources == {"chat"}`.
2. **Given** no file at `path`, **When** called with
   `metadata.sources={"cli"}` and `source="chat"`, **Then** `sources ==
   {"cli", "chat"}`.
3. **Given** no file at `path`, **When** called with
   `metadata.sources={"chat"}` and `source="chat"`, **Then** `sources ==
   {"chat"}` (no duplication).

---

### User Story 2 - Replace accumulates history (Priority: P1)

**Acceptance Scenarios**:

1. **Given** a file at version `V` with stored `sources={"cli"}`, **When**
   `write_file(path, new_content, metadata(sources=frozenset()), V,
   source="chat")` is called, **Then** the stored and returned `sources ==
   {"cli", "chat"}`. The caller did not have to carry `"cli"` forward.
2. **Given** stored `sources={"cli"}`, **When** replaced with
   `metadata.sources={"api"}` and `source="chat"`, **Then** `sources ==
   {"cli", "api", "chat"}`.
3. **Given** stored `sources={"cli", "api"}`, **When** replaced with
   `metadata.sources={"cli"}` (omitting `"api"`) and `source="cli"`,
   **Then** `sources == {"cli", "api"}`. A caller cannot remove a source.
4. **Given** a replace at `V`, **Then** `description`, `aliases`, and content
   are taken from the caller exactly as before, `last_updated` equals the
   store clock's value, and the returned `MemoryFile` equals what
   `read_file` returns afterwards.

---

### User Story 3 - Validation and errors (Priority: P1)

**Acceptance Scenarios**:

1. **Given** `source == ""`, **When** `write_file` is called (create or
   replace), **Then** `ValueError` is raised without consulting storage.
2. **Given** `source` is omitted, **Then** the call is a `TypeError` (the
   argument is required and keyword-only; passing it positionally is also a
   `TypeError`).
3. **Given** a malformed path, **Then** `NotFoundError(INVALID_PATH)` is
   raised before the `source` check, without consulting storage (existing
   check order is preserved; `source` is checked second).
4. **Given** a file at `V2` and a replace with `V1`, **Then**
   `VersionConflictError(path, current_content, V2)` is raised and the file
   is unchanged.
5. **Given** a replace with a non-`None` `expected_version` and no object at
   `path`, **Then** `NotFoundError(FILE_ABSENT)` is raised and nothing is
   created.
6. **Given** another write lands between this call's read and its
   conditional write (simulated by a storage wrapper), **Then**
   `VersionConflictError` is raised carrying the content and version current
   after the failure, and the other writer's content is untouched.
7. **Given** a file at `V` whose stored metadata is corrupt, **When**
   replaced at `V`, **Then** `MetadataFormatError` propagates and the file
   is unchanged.
8. Existing `write_file` behavior (oversize rejection, create-conflict when
   the file already exists, backend-error propagation) is unchanged apart
   from the new argument.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `MemoryStore.write_file(path, content, metadata,
  expected_version, *, source)` MUST require `source` as a keyword-only
  `str`.
- **FR-002**: It MUST raise `ValueError` for `source == ""` before any
  storage call, after the path check and before the size check.
- **FR-003**: On create, it MUST store `metadata.sources ∪ {source}`.
- **FR-004**: On replace, it MUST read the current object and store
  `stored.sources ∪ metadata.sources ∪ {source}`, committing only if the
  file is still at `expected_version`.
- **FR-005**: On replace, a version mismatch seen at read time or at the
  conditional write MUST raise `VersionConflictError` with the current
  content and version; a missing file MUST raise `NotFoundError
  (FILE_ABSENT)`. There is no automatic re-apply.
- **FR-006**: All existing `write_file` call sites MUST pass `source`.

## Success Criteria *(mandatory)*

- **SC-001**: No `write_file` call can remove a name from a file's
  `sources`, and every successful call leaves its `source` in `sources`.
- **SC-002**: `make check` passes. No storage protocol change is needed.

## Assumptions

- Caller-supplied `metadata.sources` is still accepted and unioned in, rather
  than ignored or rejected, so `FileMetadata` keeps one shape for reads and
  writes and a caller migrating a file can seed its history. Recorded in
  ADR 0013.
- Corrupt stored metadata on replace propagates `MetadataFormatError`,
  matching `replace_fact` and `append_line`, rather than being silently
  overwritten (which would lose the history this issue protects).
- Existing tests that assert `sources` equals the caller-supplied set on a
  replace are updated to the union semantics; the issue requires it.
