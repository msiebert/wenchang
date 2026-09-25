# Feature Specification: Error taxonomy definition

**Linear issue**: AIE-1030 — https://linear.app/mixpanel/issue/AIE-1030/error-taxonomy-definition

**Feature Branch**: `AIE-1030-error-taxonomy`

**Created**: 2026-09-24

**Status**: Draft

**Input**: Linear AIE-1030 and Notion "Agent Memory Library — Specification", Section 5 (Error taxonomy).

## Summary

Define the error vocabulary every core API function will raise. Errors are
grouped into three categories by what the caller should do next —
**recoverable** (fix and retry in the same turn, using the repair material
the error carries), **permanent** (stop, do not retry), and **transient**
(retry is appropriate). This issue defines the categories and the concrete
error kinds only; the core functions that raise them (`read_file`,
`write_file`, `replace_fact`, `append_line`, `list_prefix`, `delete_file`)
are separate issues that depend on this one.

## User Scenarios & Testing *(mandatory)*

The "user" is a caller of the core library: an agent tool layer, a transport
client, or a test. They must be able to decide what to do next from the
error alone.

### User Story 1 - Branch on category, not cause (Priority: P1)

A caller catches any library error and decides retry / repair / stop from
its category without knowing every concrete error kind.

**Why this priority**: The category is the whole point of the taxonomy; the
transport and tool layers are built on it.

**Independent Test**: Construct each concrete error kind and check its
category and that it is catchable as its category and as the library's base
error.

**Acceptance Scenarios**:

1. **Given** any concrete library error, **When** a caller inspects it,
   **Then** it reports exactly one of the three categories: recoverable,
   permanent, or transient.
2. **Given** any concrete library error, **When** a caller catches the
   library's base error type, **Then** the error is caught.
3. **Given** a version conflict, oversize write, replace-fact match failure,
   or not-found error, **When** a caller catches the recoverable category
   type, **Then** it is caught, and it is not caught by the permanent or
   transient category types.
4. **Given** a restricted-scope write or resolver failure, **When** a caller
   catches the permanent category type, **Then** it is caught, and it is not
   caught by the other category types.
5. **Given** a backend timeout or unavailability error, **When** a caller
   catches the transient category type, **Then** it is caught, and it is not
   caught by the other category types.

---

### User Story 2 - Recoverable errors carry repair material (Priority: P1)

A caller that receives a recoverable error has everything it needs to build
the corrected call without another read.

**Why this priority**: Without repair material the agent cannot self-correct
in the same turn, which is the defining property of the category.

**Independent Test**: Construct each recoverable error with known values and
read them back.

**Acceptance Scenarios**:

1. **Given** a version conflict raised with current content C and current
   version token V, **When** the caller reads the error, **Then** it exposes
   C and V unchanged.
2. **Given** an oversize write raised with size S and limit L, **When** the
   caller reads the error, **Then** it exposes S and L.
3. **Given** a replace-fact match failure with current content C, current
   version V, and match count 0, **When** the caller reads the error,
   **Then** it exposes C, V, and count 0, and its message tells the caller
   to widen/correct the anchor so it matches.
4. **Given** a replace-fact match failure with match count N ≥ 2, **When**
   the caller reads the error, **Then** it exposes N and its message tells
   the caller to narrow the anchor so it matches exactly one span.
5. **Given** a not-found error for path P because P is not a valid memory
   location, **When** the caller reads it, **Then** it exposes P and a
   reason of *invalid path*, and its message tells the caller to correct the
   path.
6. **Given** a not-found error for path P because P is a valid location with
   no file yet, **When** the caller reads it, **Then** it exposes P and a
   reason of *file does not exist yet*, and its message tells the caller it
   may create the file.
7. **Given** a version token, **When** it is carried by an error, **Then** it
   is the same opaque value that was supplied (no parsing or reformatting).

---

### User Story 3 - Wording tells the caller what to do next (Priority: P1)

Every error's message conveys the next action for its category, so an agent
reading only the message behaves correctly.

**Why this priority**: The Notion spec makes wording load-bearing: a
conflict worded as failure makes the agent abandon the write; a permanent
error worded ambiguously makes it loop.

**Independent Test**: Render each error's message and check for the
required guidance.

**Acceptance Scenarios**:

1. **Given** any recoverable error, **When** its message is rendered,
   **Then** it presents the situation as routine and instructs the caller to
   correct and retry in the same turn without asking the user, and it does
   not contain the words "fail", "failed", or "failure".
2. **Given** any permanent error, **When** its message is rendered, **Then**
   it states unambiguously that retrying will not succeed and the caller
   must not retry.
3. **Given** a restricted-scope write for scope S, **When** its message is
   rendered, **Then** it names S and the reason: either the `system/` area
   is read-only, or the scope is role-gated and the caller lacks the
   required role.
4. **Given** a resolver failure, **When** its message is rendered, **Then**
   it states memory is unavailable for this session and the caller should
   continue without memory.
5. **Given** any transient error, **When** its message is rendered, **Then**
   it states that retrying is appropriate, that version-guarded calls are
   safe to retry (a landed first attempt surfaces as a version conflict),
   and that a retried `append_line` may duplicate a line, which is removed
   by ordinary editing.
6. **Given** a transient error, **When** it is raised for a timeout vs. for
   backend unavailability, **Then** it exposes which of the two occurred.

### Edge Cases

- Content in repair material may be empty (a file whose body is empty) or
  contain arbitrary unicode; it is exposed unchanged.
- Oversize reporting when size equals limit is not an error case for this
  issue; the comparison rule belongs to `write_file`.
- A replace-fact match count of exactly 1 is success and never produces this
  error; constructing the error with count 1 is rejected.
- A negative size, limit, or match count is rejected at construction.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The library MUST define exactly three error categories:
  recoverable, permanent, transient.
- **FR-002**: The library MUST define one base error type from which every
  library error derives, and one type per category.
- **FR-003**: The library MUST define these concrete error kinds and
  categories: version conflict, oversize write, replace-fact match failure,
  not found (recoverable); restricted-scope write, resolver failure
  (permanent); backend timeout/unavailability (transient).
- **FR-004**: Each recoverable error MUST carry the repair material listed
  in User Story 2.
- **FR-005**: Each error's message MUST convey its category's next action as
  specified in User Story 3.
- **FR-006**: Version tokens carried by errors MUST be treated as opaque:
  stored and returned as given.
- **FR-007**: The error definitions MUST have no dependency on storage,
  transport, or agent frameworks.

### Key Entities

- **Error category**: one of recoverable / permanent / transient; the
  caller's next action.
- **Version token**: opaque value identifying one version of a file.
- **Not-found reason**: *invalid path* vs. *file does not exist yet*.
- **Restriction reason**: *`system/` read-only* vs. *role required*.
- **Transient reason**: *timeout* vs. *backend unavailable*.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of concrete error kinds report a category, and every
  kind listed in the Notion spec's Section 5 taxonomy exists.
- **SC-002**: For every recoverable kind, a caller can build its corrected
  call from the error's fields alone, with no additional read.
- **SC-003**: Every error's message passes its category's wording checks in
  User Story 3.

## Assumptions

- Errors are raised as exceptions; "returns current content" in the Notion
  spec is satisfied by the exception carrying it.
- Replace-fact match failure also carries the current version token (the
  Notion spec lists content and count), so the caller can retry with a
  version guard without re-reading.
- Version conflict carries content and version only, not metadata; the file
  metadata type does not exist yet (AIE-1031). Adding metadata is a later,
  additive change.
- "No such path" means the path does not resolve to a valid memory location
  (malformed, or outside any scope); "file does not exist yet" means a valid
  location with no file.
- Serialization of errors across a transport (error parity, Section 10.2) is
  out of scope; it belongs to the transport issues (AIE-1045/1048).
