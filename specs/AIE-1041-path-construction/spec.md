# Feature Specification: Path construction from scope and entity ID

**Linear issue**: AIE-1041 — https://linear.app/mixpanel/issue/AIE-1041/path-construction-from-scope-and-entity-id

**Feature Branch**: `AIE-1041-path-construction`

**Created**: 2026-09-30

**Status**: Draft

**Input**: Linear AIE-1041 ("turn a resolved scope name and entity ID into a
storage path, following the layout root/scope name/entity ID/area/name.md")
and Notion "Agent Memory Library — Specification", Section 3: "Storage is
path-based, one flat prefix per scope:
`{root}/{scope_name}/{entity_id}/{area}/{name}.md`. Read, Write, and List do
not branch on which scope they are touching. A scope is a path component, not
a code path." Section 3 also makes the `system/` area read-only, enforced at
the tool layer; that enforcement is AIE-1040, and this issue only makes the
area segment extractable.

## Summary

Add three pure functions and one value type to `wenchang.paths`:
`build_path(scope, entity_id, area, name)`, `build_prefix(scope, entity_id,
area)`, `parse_path(path) -> PathParts`, and `PathParts`. `build_path` and
`parse_path` are exact inverses over every path `is_valid_path` accepts.

`{root}` never appears in a built path. The storage root is the storage
instance (ARCHITECTURE.md, "The storage root is the storage instance"), so
paths stay relative to it, matching `is_valid_path`.

Out of scope: the identity resolver and `Identity` type (AIE-1043), write
restriction and `system/` enforcement (AIE-1040, AIE-1042), the resolver
conformance suite (AIE-1039), and any change to `is_valid_path` or
`is_valid_prefix` semantics.

## User Scenarios & Testing *(mandatory)*

The "user" is a caller inside the library: the future tool layer, the scope
enforcement module, and the resolver conformance suite. It holds a scope name
and an entity ID taken from a resolved identity, plus an area and file name.

### User Story 1 - Build a file path (Priority: P1)

**Acceptance Scenarios**:

1. **Given** scope `"user"`, entity ID `"u_42"`, area `"preferences"`, and
   name `"editor"`, **When** `build_path` is called, **Then** it returns
   `"user/u_42/preferences/editor.md"`.
2. **Given** any four inputs that `build_path` accepts, **Then** the result
   satisfies `is_valid_path`.
3. **Given** a scope, entity ID, or area that is empty, `"."`, `".."`, or
   contains `"/"`, a backslash, or a Unicode Cc character (e.g. `\t`, `\n`,
   `\x00`, `\x7f`), **When** `build_path` is called, **Then** `ValueError`
   is raised and its message names the offending argument. Characters
   outside Cc, such as U+200B and U+2028, are accepted.
4. **Given** a name that is empty or contains `"/"`, a backslash, or a
   Unicode Cc character (e.g. `\t`, `\n`, `\x00`, `\x7f`), **Then**
   `ValueError` naming `name` is raised. Characters outside Cc, such as
   U+200B and U+2028, are accepted.
5. **Given** a name that is `"."`, `".."`, or already ends in `".md"` (e.g.
   `"notes.md"`), **Then** `build_path` accepts it and appends `".md"`
   unconditionally (`"notes.md"` yields `".../notes.md.md"`).
6. **Given** more than one invalid argument, **Then** the error names the
   first in parameter order: `scope`, `entity_id`, `area`, `name`.
7. **Given** Unicode, spaces, or mixed case in any argument (e.g.
   `"p 1"`, `"café"`), **Then** the inputs are used verbatim, with no
   normalization or case folding. For example, `build_path("u", "e", "a",
   "café")` (decomposed "café") returns `"u/e/a/café.md"`
   unchanged, not its NFC form `"u/e/a/café.md"`.

---

### User Story 2 - Build a listing prefix (Priority: P1)

**Acceptance Scenarios**:

1. **Given** only a scope `"user"`, **When** `build_prefix` is called,
   **Then** it returns `"user/"`.
2. **Given** scope and entity ID, **Then** it returns `"user/u_42/"`.
3. **Given** scope, entity ID, and area, **Then** it returns
   `"user/u_42/preferences/"`.
4. **Given** `area` not `None` and `entity_id` `None`, **Then**
   `ValueError("area requires entity_id")` is raised. This check runs before
   any segment validation, so it applies even when `scope` or `area` is
   invalid.
5. **Given** any supplied argument that is not a valid segment (including
   `""`, which is not treated as "omitted"), **Then** `ValueError` naming
   that argument is raised.
6. **Given** any inputs `build_prefix` accepts, **Then** the result
   satisfies `is_valid_prefix`, and every path from `build_path` with the
   same leading arguments starts with it.
7. **Given** more than one invalid supplied argument, **Then** the error
   names the first in order `scope`, `entity_id`, `area`.

---

### User Story 3 - Parse a path into its parts (Priority: P1)

**Acceptance Scenarios**:

1. **Given** `"user/u_42/preferences/editor.md"`, **When** `parse_path` is
   called, **Then** it returns `PathParts(scope="user", entity_id="u_42",
   area="preferences", name="editor")`.
2. **Given** any string where `is_valid_path` is False (every malformed case
   in `tests/test_paths.py`), **Then** `parse_path` raises `ValueError`.
3. **Given** `"s/e/system/x.md"`, **Then** `parse_path(...).area` is
   `"system"`, so enforcement can check the area without re-splitting.
4. **Given** `"u/e/a/..md"` or `"u/e/a/b.md.md"`, **Then** `name` is `"."`
   or `"b.md"` respectively (only the final `".md"` is stripped).

---

### User Story 4 - Round trip (Priority: P1)

**Acceptance Scenarios**:

1. **Given** any four arguments `build_path` accepts, **Then**
   `parse_path(build_path(s, e, a, n)) == PathParts(s, e, a, n)`.
2. **Given** any path `p` with `is_valid_path(p)`, **Then**
   `build_path(**dataclasses.asdict(parse_path(p))) == p`.

### Edge Cases

- A name of `".md"` is accepted and yields a last segment of `".md.md"`.
- `PathParts` is frozen and compares by value.
- `PathParts` does no validation. `PathParts("", "", "", "")` constructs.
  Only `parse_path` guarantees valid fields.
- `build_path` performs no authorization and no scope-name lookup: `"system"`
  as a scope or area is accepted like any other segment.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `build_path(scope, entity_id, area, name) -> str` MUST return
  `f"{scope}/{entity_id}/{area}/{name}.md"` and raise `ValueError` naming the
  first invalid argument.
- **FR-002**: `build_prefix(scope, entity_id=None, area=None) -> str` MUST
  return the 1-3 segment prefix ending in `/`, and raise `ValueError` for an
  invalid segment or an `area` without an `entity_id`.
- **FR-003**: `parse_path(path) -> PathParts` MUST split a valid path into
  its four parts with `name` excluding the final `".md"`, and raise
  `ValueError` iff `not is_valid_path(path)`.
- **FR-004**: The two round-trip laws in User Story 4 MUST hold.
- **FR-005**: Every successful `build_path` result MUST satisfy
  `is_valid_path`, and every successful `build_prefix` result MUST satisfy
  `is_valid_prefix`.
- **FR-006**: `wenchang.paths` MUST stay dependency-free: no import of
  `identity`, `storage`, or `core`.
- **FR-007**: For arguments of their annotated types, the only exception
  these functions raise is `ValueError`. `parse_path` raises it for any `str`
  rejected by `is_valid_path`, including the never-raises inputs in
  `tests/test_paths.py`.

## Success Criteria *(mandatory)*

- **SC-001**: No caller outside `wenchang.paths` needs to format or split a
  memory path by hand.
- **SC-002**: `make check` passes. Existing `tests/test_paths.py` cases are
  unchanged.

## Assumptions

- Errors are `ValueError`, not `NotFoundError(INVALID_PATH)`. These are
  programmer-facing helpers. `core` keeps reporting malformed agent-supplied
  paths as `NotFoundError` through `is_valid_path`.
- A name ending in `".md"` is accepted rather than rejected. Rejecting it
  would break the second round-trip law, because `is_valid_path` accepts
  `"u/e/a/b.md.md"`, whose stem is `"b.md"`.
- The name rule is "non-empty, and `name + ".md"` is a valid segment". This
  admits `"."` and `".."` as names, because `"..md"` and `"...md"` are valid
  last segments today. It is the exact rule under which both laws hold.
- A stem of `"."` or `".."` yields the literal filename `"..md"` or
  `"...md"`, with no traversal meaning. Storage keys are flat strings: GCS
  object names, and a plain string match in the in-memory fake. `"."` and
  `".."` are already rejected as whole segments. The only way to splice
  extra segments is a `"/"` inside a segment, and the shared
  `is_valid_segment` rejects that.
- Segments are validated with the public `is_valid_segment` from AIE-1043,
  which lands first and rejects `"/"` along with the existing rule.
- There is no identity-aware helper. Callers write
  `build_path(scope, identity.entity_id(scope), area, name)`.
