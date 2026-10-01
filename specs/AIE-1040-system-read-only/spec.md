# Feature Specification: Read-only enforcement for the system/ area

**Linear issue**: AIE-1040 — https://linear.app/mixpanel/issue/AIE-1040/read-only-enforcement-for-system-slash-area

**Feature Branch**: `AIE-1040-system-read-only`

**Created**: 2026-09-30

**Status**: Draft

**Input**: Linear AIE-1040 ("Enforce that the system slash area is read-only
for all callers regardless of role: any write attempt targeting a path under
system slash is rejected") and Notion "Agent Memory Library — Specification":

- Section 3: "Within any scope, the area named `system/` is read-only to the
  agent, enforced at the tool layer. [...] Rejecting a write to a `system/`
  prefix is an exact string check, so it is hard-enforced rather than
  instructed. It is refreshed by wholesale prefix rewrite. The seeding job
  owns the entire prefix and replaces it end to end."
- Section 5 error taxonomy: restricted-scope write is permanent and "names the
  scope and the reason: `system/` is read-only".
- Section 1 principle 2: "Enforce at the tool layer where the check is exact
  (a byte count, a path prefix)."

Builds on `parse_path` (AIE-1041, ADR 0015) and the existing
`RestrictedScopeError` / `RestrictionReason.SYSTEM_READ_ONLY` in
`wenchang.errors`.

## Summary

Add a new module `wenchang.scope` with `SYSTEM_AREA`, `is_system_path(path)`,
and `check_not_system(path)`. `check_not_system` is the guard every mutating
agent-facing tool calls before touching core. It raises
`RestrictedScopeError(path, scope, SYSTEM_READ_ONLY)` when the path's area
segment is exactly `"system"`. It takes no identity, so no role can bypass it.

The check is called by the tool layer directly or through AIE-1042's
`check_write`. It is deliberately **not** wired into `MemoryStore`. The
seeding job refreshes `system/` by writing through core, so core must keep
accepting `system/` paths. Wiring the check into the tools is AIE-1044.

Human decisions (2026-09-30): malformed-path validation runs before the
system check, and no `is_system_prefix` predicate is added.

Out of scope: role-gated write restriction (AIE-1042), wiring into the tool
layer (AIE-1044), the resolver conformance suite (AIE-1039), a seeding job or
prefix-level rewrite API, and any change to `MemoryStore`, `paths`, or
`errors`.

## User Scenarios & Testing *(mandatory)*

The "user" is the future tool layer, which receives an agent-supplied path
and must refuse a write to curated content before calling core.

### User Story 1 - Reject a write to system/ (Priority: P1)

**Acceptance Scenarios**:

1. **Given** `"user/u_42/system/policy.md"`, **When** `check_not_system` is
   called, **Then** it raises `RestrictedScopeError` with `path` equal to the
   input, `scope == "user"`, `reason is RestrictionReason.SYSTEM_READ_ONLY`,
   `category is ErrorCategory.PERMANENT`, and
   `getattr(err, "required_role", None) is None and getattr(err,
   "required_roles", None) is None`, and `is_system_path(path)` is True.
2. **Given** a `system` area under any scope and entity ID (e.g.
   `"org/o_1/system/x.md"`, `"team/t 9/system/café.md"`,
   `"system/e/system/x.md"`), **Then** it raises `RestrictedScopeError` whose
   `scope` is that path's first segment, and `is_system_path(path)` is True.
3. **Given** any valid last segment under `system` (e.g.
   `"u/e/system/..md"`, `"u/e/system/a.md.md"`), **Then** it raises
   `RestrictedScopeError`. The name does not matter. And
   `is_system_path(path)` is True.
4. **Given** the error from scenario 1, **Then** its message names the scope
   and says the `system/` area is read-only (the existing
   `RestrictedScopeError` wording, unchanged).
5. **Given** the signature of `check_not_system`, **Then** its only parameter
   is `path`. There is no identity or role argument, so no caller can be
   exempted.

---

### User Story 2 - Allow every other valid path (Priority: P1)

**Acceptance Scenarios**:

1. **Given** `"user/u_42/preferences/editor.md"`, **When** `check_not_system`
   is called, **Then** it returns `None`, and `is_system_path` is False.
2. **Given** an area that only resembles `system` (`"systems"`, `"System"`,
   `"SYSTEM"`, `"system2"`, `"_system"`, `"system "`, `" system"`, `"sys"`,
   `"ѕystem"` with a Cyrillic `ѕ`, fullwidth `"ｓｙｓｔｅｍ"`,
   `"system​"` with a zero-width space suffix, `"system "` with a
   trailing no-break space, and `"systeḿ"` with a combining mark), **Then**
   `check_not_system` returns `None` and `is_system_path` is False. The match
   is exact, with no case folding or Unicode normalization.
3. **Given** `"system"` in a position other than the area (`"system/e/a/x.md"`,
   `"u/system/a/x.md"`, `"u/e/a/system.md"`), **Then** `check_not_system`
   returns `None` and `is_system_path` is False.

---

### User Story 3 - Malformed paths (Priority: P1)

**Acceptance Scenarios**:

1. **Given** any string where `is_valid_path` is False (every entry of
   `MALFORMED_STRUCTURE_PATHS`, `DOT_SEGMENT_PATHS`, `CONTROL_CHAR_PATHS`,
   `WRONG_SEGMENT_COUNT_PATHS`, and `BAD_NAME_PATHS` in `tests/test_paths.py`,
   plus `"u/e/system/x.txt"`, `"u/e/system/"`, `"u/e/system/sub/x.md"`,
   `"u/e/sys/tem/x.md"`, `"/u/e/system/x.md"`, and `"u/e/system/x.md/"`),
   **When** `check_not_system` is called, **Then** it raises `NotFoundError`
   with `reason is NotFoundReason.INVALID_PATH` and `path` equal to the input.
   It never raises `RestrictedScopeError` or `ValueError` for a malformed
   path.
2. **Given** the same strings plus `"\x00\x00\x00"`, `"a" * 10000`, and
   `"///"`, **When** `is_system_path` is called, **Then** it returns False and
   never raises. `"😀/😀/😀/😀.md"` is a valid path that is not system:
   `is_system_path` is False and `check_not_system` returns `None`.

---

### User Story 4 - Core stays writable for seeding (Priority: P1)

**Acceptance Scenarios**:

1. **Given** a `MemoryStore` over `InMemoryStorage` and
   `"org/o_1/system/policy.md"`, **Then** `write_file` creates it,
   `write_file` with the returned version replaces it, `append_line` and
   `replace_fact` succeed, and `delete_file` with the current version removes
   it. None raises `RestrictedScopeError`. Core performs no `system/` check.

### Edge Cases

- A scope literally named `"system"` is not restricted. Section 3 restricts
  the *area* named `system/` within any scope, not a scope.
- The check reads no storage and has no side effects. Calling it twice gives
  the same result.
- Reads and listings of `system/` are unaffected. Nothing in this issue
  restricts them.
- For every path used in US1–US3, `check_not_system` raises
  `RestrictedScopeError` iff `is_system_path` is True.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `wenchang.scope` MUST export `SYSTEM_AREA: Final = "system"`.
- **FR-002**: `is_system_path(path) -> bool` MUST return True iff
  `is_valid_path(path)` and the third segment equals `SYSTEM_AREA` exactly.
  It MUST NOT raise for any `str` input.
- **FR-003**: `check_not_system(path) -> None` MUST raise
  `NotFoundError(path, INVALID_PATH)` if `not is_valid_path(path)`, else
  raise `RestrictedScopeError(path, scope, SYSTEM_READ_ONLY)` if the area is
  `SYSTEM_AREA`, else return `None`.
- **FR-004**: `check_not_system` MUST take no identity, role, or bypass
  argument.
- **FR-005**: `MemoryStore` MUST NOT call the check. Its behavior for
  `system/` paths is unchanged.
- **FR-006**: `wenchang.scope` MUST NOT import `wenchang.core` or
  `wenchang.storage`, and `wenchang.core` MUST NOT import `wenchang.scope`.

## Success Criteria *(mandatory)*

- **SC-001**: For every valid path, `check_not_system` rejects it iff its area
  is exactly `"system"`.
- **SC-002**: `make check` passes. No existing test changes.

## Assumptions

- Malformed-path validation runs before the system check, so
  `"u/e/system/x.txt"` is `NotFoundError(INVALID_PATH)`. The tool layer gets
  the same error core would give, and a corrected path then hits the
  permanent rejection.
- `is_system_path` returns False for malformed paths rather than raising. It
  is a predicate like `is_valid_path`. Only `check_not_system` raises.
- No prefix-level predicate (`is_system_prefix`) is added. No agent-facing
  operation writes by prefix today, and the seeding job's prefix rewrite runs
  through core, which is unrestricted.
- This issue delivers the check and its tests only. Until AIE-1044 wires it
  into the tools, nothing in the library calls it.
