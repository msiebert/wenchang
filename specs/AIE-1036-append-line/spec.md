# Feature Specification: append_line — version-guarded fact-line append

**Linear issue**: AIE-1036 — https://linear.app/mixpanel/issue/AIE-1036/append-line

**Feature Branch**: `AIE-1036-append-line`

**Created**: 2026-09-29

**Status**: Draft

**Input**: Linear AIE-1036 and Notion "Agent Memory Library — Specification",
Section 5 (`append_line(path, line)` adds a fact line), Section 5 "Error
taxonomy" (a retried unguarded append can duplicate a line), and Section
10.2 "Append commutativity". Builds on `replace_fact` (AIE-1034, ADR 0009),
which set the required-`source` stamping pattern, and on `parse_fact`
(AIE-1031).

**Change to the original design (human decision, 2026-09-29)**: Notion and
the Linear issue originally specified `append_line` with no version guard;
both were updated on 2026-09-29 to match this spec. This spec adds a required
`expected_version`, so every mutating call is version-guarded. A retried
append whose first attempt landed then fails its guard and degrades to a
`VersionConflictError`, as every other guarded call does. The duplicate-line
case is gone. The cost is that concurrent appends to one file no longer
commute transparently: the loser gets a conflict carrying the current
content and version, and retries. Recorded in ADR 0011.

## Summary

Add `MemoryStore.append_line(path, line, expected_version, *, source) ->
MemoryFile`, which adds one fact line to the end of an existing file, only
if the file is still at `expected_version`. There is no automatic re-apply
against a newer version. A stale token always surfaces to the caller, which
is what makes a retry safe.

Out of scope: `system/` read-only enforcement (AIE-1040), role-gated scopes
(AIE-1042), agent-facing tool wording (AIE-1044), and the transport
conformance cases (AIE-1045).

## User Scenarios & Testing *(mandatory)*

The "user" is a caller inside the library (the transport layer, tests)
adding one fact to a known file whose version it holds from `read_file`,
`list_prefix`, or a previous write.

### User Story 1 - Append at the current version (Priority: P1)

**Acceptance Scenarios**:

1. **Given** a file at version `V` whose content is `"- [stated] a\n"`,
   **When** `append_line(path, "- [observed] b", V, source="chat")` is
   called, **Then** the stored content is `"- [stated] a\n- [observed] b\n"`,
   and the returned `MemoryFile` has that content and a new version `V2 !=
   V`, which equals what `read_file` returns afterwards.
2. **Given** content with no trailing newline (`"- [stated] a"`), **When** a
   line is appended, **Then** the content is `"- [stated] a\n- [observed]
   b\n"`. A separator is inserted so the existing last line is not extended.
3. **Given** a file with empty content, **When** a line is appended, **Then**
   the content is exactly the line followed by `"\n"`.
4. **Given** content that includes non-fact lines (headings, blank lines),
   **When** a line is appended, **Then** every existing byte is preserved
   and the new line follows it.
5. **Given** metadata with `sources={"cli"}` and an old `last_updated`,
   **When** appended with `source="chat"`, **Then** `sources == {"cli",
   "chat"}`, `last_updated` equals the store clock's value, and
   `description` and `aliases` are unchanged.
6. **Given** a line is appended at `V` (returning `V2`) and the same line is
   then appended at `V2`, **Then** it appears twice. Deliberate repeats are
   allowed.
7. **Given** a line whose text contains unicode or markdown resembling
   fact-line syntax, **Then** it round-trips byte for byte.

---

### User Story 2 - Stale token and retry safety (Priority: P1)

**Acceptance Scenarios**:

1. **Given** a file at `V2` and a caller holding `V1`, **When**
   `append_line(path, line, V1, ...)` is called, **Then**
   `VersionConflictError(path, current_content, V2)` is raised and the file
   is unchanged. No re-apply is attempted.
2. **Given** an append at `V` succeeded, **When** the caller retries the
   identical call with `V`, **Then** `VersionConflictError` is raised, its
   content contains the line exactly once, and the file is unchanged.
3. **Given** two callers holding `V`, **When** both append different lines,
   **Then** the first succeeds and the second gets `VersionConflictError`
   with the first's line in its content. Retrying with the returned version
   succeeds, leaving both lines present exactly once.
4. **Given** the conditional write fails its precondition (another write
   landed between this call's read and its write, simulated by a storage
   wrapper), **Then** `VersionConflictError` is raised with the content and
   version current after the failure, and no second write is attempted.
5. **Given** the conditional write fails its precondition **but** the stored
   content and metadata already equal exactly what this call tried to write
   (its own write landed, and a backend-level retry saw the precondition
   fail), **Then** `append_line` returns success with the stored version and
   does not append again.

---

### User Story 3 - Validation and errors (Priority: P1)

**Acceptance Scenarios**:

1. **Given** a malformed path, **When** `append_line` is called, **Then**
   `NotFoundError(path, INVALID_PATH)` is raised without consulting storage.
2. **Given** a well-formed path with no object, **Then**
   `NotFoundError(path, FILE_ABSENT)` is raised and nothing is created.
3. **Given** a `line` that is not a single well-formed fact line (e.g.
   `""`, `"plain text"`, `"- [guess] x"`, `"- [stated] "`, `"- [stated]
   a\n- [stated] b"`, `"- [stated] a\n"`), **Then** `ValueError` is
   raised without consulting storage.
4. **Given** `source == ""`, **Then** `ValueError` is raised without
   consulting storage.
5. **Given** an append at the current version that would push the encoded
   content over `max_file_bytes`, **Then** `OversizeWriteError(path, size,
   limit)` is raised with the would-be size, and the file is unchanged. An
   append that lands exactly at the limit succeeds.
6. **Given** a stale token **and** an oversize line, **Then**
   `VersionConflictError` is raised. The version is checked first, since
   the size check is only meaningful against current content.
7. **Given** storage raising `BackendUnavailableError`, or an object with
   corrupt metadata (`MetadataFormatError`), **Then** it propagates
   unchanged.

### Edge Cases

- `\r` is not a line separator in this format (`parse_body` splits on `\n`
  only), so it is not rejected.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `MemoryStore.append_line(path, line, expected_version, *,
  source) -> MemoryFile` MUST append `line + "\n"` to the current content,
  inserting one `"\n"` first if the content is non-empty and does not end
  in `"\n"`.
- **FR-002**: It MUST commit only if the file is at `expected_version`, and
  otherwise raise `VersionConflictError` with the current content and
  version. It MUST NOT re-apply against a newer version.
- **FR-003**: When the conditional write fails its precondition, it MUST
  re-read. If the stored content and metadata equal exactly what it tried to
  write, it MUST return that as success. Otherwise it MUST raise
  `VersionConflictError`.
- **FR-004**: It MUST raise `NotFoundError(FILE_ABSENT)` for a missing file
  and never create one.
- **FR-005**: It MUST reject, before any storage call, a malformed path
  (`NotFoundError(INVALID_PATH)`), a `line` for which `parse_fact` returns
  `None`, and an empty `source` (both `ValueError`).
- **FR-006**: It MUST enforce `max_file_bytes` on the resulting content.
- **FR-007**: It MUST stamp `sources ∪ {source}` and `last_updated =
  clock()`, leaving other metadata unchanged, atomically with the content.

## Success Criteria *(mandatory)*

- **SC-001**: No sequence of retries of one logical append produces a
  duplicate line.
- **SC-002**: `make check` passes. No storage protocol change is needed.

## Assumptions

- A missing file is an error, not an implicit create: an appended-into-
  existence file would have no description or aliases, which are the only
  search surface (Notion Section 4). The agent creates files with
  `write_file`.
- `line` must be exactly one fact line (`parse_fact` is not `None`). The
  `[system]` label is not rejected here; label policy is prompt-layer.
- `source` is required and keyword-only, following ADR 0009.
- `expected_version` is a required positional parameter, placed as in
  `replace_fact`. It is never `None`, because append never creates.
