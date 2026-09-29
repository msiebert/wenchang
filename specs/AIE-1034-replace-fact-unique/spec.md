# Feature Specification: replace_fact — unique-span replacement with auto-reapply on conflict

**Linear issue**: AIE-1034 — https://linear.app/mixpanel/issue/AIE-1034/replace-fact

**Feature Branch**: `AIE-1034-replace-fact`

**Created**: 2026-09-28

**Status**: Draft

**Input**: Linear AIE-1034 and Notion "Agent Memory Library — Specification",
Section 5 (`replace_fact(path, old_string, new_string, expected_version)`
replaces one span; the match must be unique or the call is rejected with
current content and the match count; on version conflict the service
re-applies the replacement against the fresh version and escalates only on
a genuine overlap), Section 8.1 ("Write mechanics"), and Section 10.2
("Replace-fact matching"). Builds on `read_file` (AIE-1032), `write_file`
and `Storage.put_if_version` (AIE-1033, ADR 0008), and
`ReplaceFactMatchError` (AIE-1030).

## Summary

Add `MemoryStore.replace_fact`, which changes one span of a file's content
without the caller resending the rest of it:

- The anchor `old_string` must occur exactly once in the current content.
  Zero or several occurrences raise `ReplaceFactMatchError` with the
  current content, version, and match count.
- If the caller's `expected_version` is stale, the replacement is re-applied
  to the current content when the anchor still matches exactly once there.
  Only when it does not (the concurrent write touched the anchor) does the
  caller see `VersionConflictError`.
- Metadata is carried over from the stored file, with the caller's `source`
  added to `sources` and `last-updated` re-stamped from the store's clock.

No storage-layer change. Out of scope: `system/` read-only enforcement
(AIE-1040), role-gated scopes (AIE-1042), and agent-facing tool wording
(AIE-1044).

## User Scenarios & Testing *(mandatory)*

The "user" is a caller inside the library (transport layer, tests) changing
one fact line of an existing memory file.

### User Story 1 - Replace a uniquely matched span (Priority: P1)

**Acceptance Scenarios**:

1. **Given** a file at version `V` whose content contains `old` exactly
   once, **When** `replace_fact(path, old, new, V)` is called, **Then** it
   returns a `MemoryFile` with the path as given, content equal to the
   original with that one occurrence replaced by `new` and every other byte
   unchanged, and a new version `V2 != V`; and `read_file(path)` returns the
   same content, metadata, and `V2`.
2. **Given** a match at the start, the end, or spanning a line break, **When**
   replaced, **Then** only that span changes.
3. **Given** `new` is the empty string, **When** replaced, **Then** the span
   is deleted.
4. **Given** content and anchors with multi-byte unicode and `\r\n`, **When**
   replaced, **Then** the match and replacement are exact (no normalization).

---

### User Story 2 - Reject non-unique anchors with repair material (Priority: P1)

**Acceptance Scenarios**:

1. **Given** a file at `V` not containing `old`, **When**
   `replace_fact(path, old, new, V)` is called, **Then**
   `ReplaceFactMatchError` is raised with `path`, current `content`,
   `version == V`, `match_count == 0`; the file is unchanged.
2. **Given** a file at `V` containing `old` at `k >= 2` non-overlapping
   positions, **Then** `ReplaceFactMatchError` is raised with
   `match_count == k`; the file is unchanged.
3. **Given** occurrences of `old` that overlap (e.g. `"aa"` in `"aaa"`),
   **Then** every start position counts (`match_count == 2`) and the call is
   rejected.
4. **Given** `old_string == ""`, **When** `replace_fact` is called, **Then**
   `ValueError` is raised without consulting storage.

---

### User Story 3 - Stale versions are absorbed when the anchor survives (Priority: P1)

**Acceptance Scenarios**:

1. **Given** a caller holding `V`, and another writer has since replaced
   *a different line* (file now at `V2`, still containing `old` exactly
   once), **When** `replace_fact(path, old, new, V)` is called, **Then** it
   succeeds: the result keeps the other writer's change, has `old` replaced
   by `new`, and a version distinct from `V` and `V2`.
2. **Given** a caller holding `V`, and another writer has since changed or
   removed the anchor (file at `V2` has zero occurrences of `old`), **Then**
   `VersionConflictError` is raised with the content and version at `V2`;
   the file is unchanged.
3. **Given** a caller holding `V`, and another writer has since introduced a
   second occurrence of `old`, **Then** `VersionConflictError` is raised with
   the content and version at `V2`.
4. **Given** a write lands between `replace_fact`'s read and its
   conditional put (a race), **When** the anchor still matches uniquely in
   the new content, **Then** the replacement is re-applied to that content
   and succeeds; the racing write's change is preserved.
5. **Given** the conditional put keeps failing because other writers keep
   landing, **When** 3 attempts have failed, **Then** `VersionConflictError`
   is raised with the most recently read content and version.
6. **Given** a first `replace_fact` whose response was lost, **When** it is
   retried with the same `V` and `new` does not contain `old`, **Then**
   `VersionConflictError` is raised whose content equals what the first
   attempt wrote.

---

### User Story 4 - Metadata, size, and paths (Priority: P1)

**Acceptance Scenarios**:

1. **Given** a stored file with metadata `M`, and a store clock returning
   `T`, **When** a replacement with `source=S` succeeds, **Then** the
   returned and stored metadata equal `M` with `sources == M.sources | {S}`
   and `last_updated == T`; `description` and `aliases` are unchanged. A
   `source` already in `M.sources` leaves `sources` unchanged.
7. **Given** `source == ""`, **When** `replace_fact` is called, **Then**
   `ValueError` is raised without consulting storage.
2. **Given** a store with `max_file_bytes=L`, **When** the replaced content's
   UTF-8 encoding exceeds `L` bytes, **Then** `OversizeWriteError(path,
   size, L)` is raised with the resulting size and nothing is written;
   exactly `L` bytes succeeds.
3. **Given** a malformed path, **Then** `NotFoundError(INVALID_PATH)` is
   raised without consulting storage.
4. **Given** a well-formed path with no file (at the first read, or deleted
   between a failed put and the re-read), **Then**
   `NotFoundError(FILE_ABSENT)` is raised.
5. **Given** a clock returning a naive datetime, **Then** `ValueError` is
   raised and nothing is written.
6. **Given** storage raising `BackendUnavailableError`, or a stored object
   with corrupt metadata or non-UTF-8 bytes, **Then** the error propagates
   unchanged (`BackendUnavailableError`, `MetadataFormatError`,
   `UnicodeDecodeError`).

### Edge Cases

- `old == new` with a unique match is a normal write (new version,
  `last_updated` refreshed).
- An expected token no write produced is treated as stale, never parsed.
- A retried call whose `new` contains `old` re-applies on the retry and
  duplicates the change; see Assumptions.
- `system/` paths are writable here; AIE-1040 adds enforcement in front.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `MemoryStore.replace_fact(path, old_string, new_string,
  expected_version, *, source)` MUST replace the single occurrence of `old_string` in
  the current content with `new_string` and commit it with one conditional
  put, returning the stored `MemoryFile`.
- **FR-002**: Occurrences MUST be counted at every start index (overlaps
  included). With `expected_version` equal to the current version, a count
  other than 1 MUST raise `ReplaceFactMatchError(path, content, version,
  count)`.
- **FR-003**: With `expected_version` not equal to the current version, a
  count of exactly 1 MUST re-apply against the current content; any other
  count MUST raise `VersionConflictError(path, content, version)`.
- **FR-004**: A failed conditional put MUST re-read and repeat FR-003, up to
  3 attempts in total, then raise `VersionConflictError` with the last read
  content and version.
- **FR-005**: Metadata MUST be taken from the stored file (as read on the
  attempt that commits), with `source` added to `sources` and
  `last_updated` stamped from the store's clock.
- **FR-006**: The resulting content MUST be checked against
  `max_file_bytes` before the put, raising `OversizeWriteError`.
- **FR-007**: Invalid path → `NotFoundError(INVALID_PATH)`, and empty
  `old_string` or empty `source` → `ValueError`, all without consulting
  storage; absent file
  → `NotFoundError(FILE_ABSENT)`.

## Success Criteria *(mandatory)*

- **SC-001**: Every rejected call in the test corpus leaves the stored file
  and its version unchanged.
- **SC-002**: Every concurrent-write test in which the anchor survives ends
  with both writers' changes present.

## Assumptions

- "Genuine overlap" means the anchor no longer matches exactly once in the
  current content. Without the content at the caller's version (GCS object
  versioning is not assumed), this is the only overlap test available.
- A stale call escalates as `VersionConflictError`, not
  `ReplaceFactMatchError`: the caller's view is out of date, so the right
  move is to re-read and re-derive the edit, not adjust the anchor against
  content it has not seen.
- `expected_version` is a required `VersionToken`; there is no create mode.
- `source` is a required keyword-only argument beyond the Notion signature.
  `replace_fact` takes no metadata, so without it the calling surface could
  never be recorded in `sources` ("stamped at write time", Notion Section
  4). It is added to the set as-is, with no vocabulary check. Required
  rather than optional so no write path silently skips stamping; recorded
  in the ADR as a spec deviation.
- Retry safety holds only when `new_string` does not contain `old_string`.
  Otherwise a retried call re-applies. Accepted: it is detectable ordinary
  editing, the same cost the spec accepts for `append_line`.
- The retry budget (3) is an internal constant, not configurable.
