# Feature Specification: delete_file — version-guarded file removal

**Linear issue**: AIE-1037 — https://linear.app/mixpanel/issue/AIE-1037/delete-file

**Feature Branch**: `AIE-1037-delete-file`

**Created**: 2026-09-29

**Status**: Draft

**Input**: Linear AIE-1037 and Notion "Agent Memory Library — Specification",
Section 5 (`delete_file(path, expected_version)`; "every mutating call
carries an expected version token; a stale token fails the call"), Section 5
"Error taxonomy" (version conflict and not-found are recoverable; retry
safety comes from the version guard), and Section 8.1 "Forgetting" (delete
the whole file). Builds on `append_line` (AIE-1036, ADR 0011).

Allow-test-changes: `TestGcsStorage` skips the shared stale-token delete
conformance test (US4.2), because fake-gcs-server does not enforce
`ifGenerationMatch` on DELETE. The human approved this on 2026-09-29. The test
still runs against `InMemoryStorage`, and
`test_delete_if_version_precondition_failed_raises_precondition_failed_error`
in `tests/test_storage_gcs_errors.py` covers the GCS precondition mapping.
Recorded in ADR 0012.

## Summary

Add `MemoryStore.delete_file(path, expected_version) -> None`, which removes
the file at `path` only if it is still at `expected_version`. The `Storage`
protocol has no delete today, so this adds
`Storage.delete_if_version(key, expected)` to the protocol and to both
implementations (in-memory fake and GCS, via `if_generation_match`).

Out of scope: `system/` read-only enforcement (AIE-1040), role-gated scopes
(AIE-1042), agent-facing tool wording (AIE-1044), and the transport
conformance cases (AIE-1045).

## User Scenarios & Testing *(mandatory)*

The "user" is a caller inside the library (the transport layer, tests)
removing a file whose version it holds from `read_file`, `list_prefix`, or a
previous write.

### User Story 1 - Delete at the current version (Priority: P1)

**Acceptance Scenarios**:

1. **Given** a file at version `V`, **When** `delete_file(path, V)` is
   called, **Then** it returns `None`, `read_file(path)` then raises
   `NotFoundError(path, FILE_ABSENT)`, and `list_prefix` no longer returns
   the file.
2. **Given** two files under one prefix, **When** one is deleted, **Then**
   the other is unchanged (content, metadata, version).
3. **Given** a file was deleted, **When** `write_file(path, ..., None)` is
   called, **Then** the file is created again (the path is reusable).

---

### User Story 2 - Stale token and retry safety (Priority: P1)

**Acceptance Scenarios**:

1. **Given** a file at `V2` and a caller holding `V1`, **When**
   `delete_file(path, V1)` is called, **Then**
   `VersionConflictError(path, current_content, V2)` is raised and the file
   is unchanged.
2. **Given** `delete_file(path, V)` succeeded, **When** the caller retries
   the identical call, **Then** `NotFoundError(path, FILE_ABSENT)` is raised
   and nothing else changes.
3. **Given** the conditional delete fails its precondition because another
   write landed between this call's read and its delete (simulated by a
   storage wrapper), **Then** `VersionConflictError` is raised with the
   content and version current after the failure, and the file still
   exists.
4. **Given** the conditional delete fails its precondition and the file is
   now absent (another caller deleted it, or this call's own delete landed
   and a backend-level retry saw it gone), **Then**
   `NotFoundError(path, FILE_ABSENT)` is raised.

---

### User Story 3 - Validation and errors (Priority: P1)

**Acceptance Scenarios**:

1. **Given** a malformed path, **When** `delete_file` is called, **Then**
   `NotFoundError(path, INVALID_PATH)` is raised without consulting storage.
2. **Given** a well-formed path with no object, **Then**
   `NotFoundError(path, FILE_ABSENT)` is raised.
3. **Given** storage raising `BackendUnavailableError`, **Then** it
   propagates unchanged.

---

### User Story 4 - Storage `delete_if_version` (Priority: P1)

Run by the shared `StorageConformance` suite against `InMemoryStorage` (unit)
and `GcsStorage` (integration, fake-gcs-server).

**Acceptance Scenarios**:

1. **Given** an object at token `T`, **When** `delete_if_version(key, T)`,
   **Then** it returns `None` and `get(key)` is `None`.
2. **Given** an object at token `T2`, **When** `delete_if_version(key, T1)`
   with `T1 != T2`, **Then** `PreconditionFailedError` is raised and the
   object is unchanged.
3. **Given** no object at `key`, **When** `delete_if_version(key, T)`,
   **Then** `PreconditionFailedError` is raised.
4. **Given** a deleted key, **When** `put_if_version(key, ..., None)`,
   **Then** it succeeds (create-if-absent works after delete).
5. **Given** two keys, **When** one is deleted, **Then** `get` and
   `list_page` still return the other, and no longer list the deleted one.
6. (GCS only) **Given** a token that is not a canonical positive decimal,
   **Then** `PreconditionFailedError` is raised with no client call; a GCS
   timeout or unavailability maps to `BackendUnavailableError`.

### Edge Cases

- Deleting leaves no tombstone. A later `write_file` at `None` creates a
  fresh file, and its version is never equal to a pre-delete token passed
  by a caller (GCS generations and the fake's counter are both monotonic).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `MemoryStore.delete_file(path, expected_version) -> None` MUST
  remove the file only if it is at `expected_version`.
- **FR-002**: It MUST reject a malformed path with
  `NotFoundError(INVALID_PATH)` before any storage call.
- **FR-003**: On a stale token it MUST raise `VersionConflictError` with the
  current content and version, and leave the file in place.
- **FR-004**: On a missing file, including after a precondition failure, it
  MUST raise `NotFoundError(FILE_ABSENT)`.
- **FR-005**: The `Storage` protocol MUST gain
  `delete_if_version(key, expected: VersionToken) -> None`, raising
  `PreconditionFailedError` when the object is absent or at a different
  version, implemented by `InMemoryStorage` and `GcsStorage`.
- **FR-006**: `BackendUnavailableError` MUST propagate unchanged.

## Success Criteria *(mandatory)*

- **SC-001**: No stale-token delete removes a file.
- **SC-002**: `make check` and `make test-integration` pass.

## Assumptions

- `delete_file` takes no `source` argument: nothing remains to stamp.
- Returns `None`. There is no version to hand back for a file that no longer
  exists.
- `FILE_ABSENT` from `delete_file` means the file is gone, whoever removed
  it. The library can't tell a landed-then-retried delete from someone else's
  delete, and the end state is the same, so it doesn't try.
- `expected_version` is required and never `None`.
