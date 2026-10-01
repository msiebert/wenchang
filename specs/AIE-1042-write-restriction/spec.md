# Feature Specification: write-restriction enforcement for role-gated scopes

**Linear issue**: AIE-1042 — https://linear.app/mixpanel/issue/AIE-1042/write-restriction-enforcement-for-role-gated-scopes

**Feature Branch**: `AIE-1042-write-restriction`

**Created**: 2026-09-30

**Status**: Draft

**Input**: Linear AIE-1042 ("writes are rejected unless the caller's resolved
role for that scope permits writing; reads are unaffected") and Notion "Agent
Memory Library — Specification", Section 3 (write-restriction is the only
scope property the library understands; no scope name is special-cased),
Section 5 (restricted-scope write is permanent and names the scope and the
reason), Section 6 (tool code uses the resolver's fields to check write
eligibility), Section 9 (the reference adopter restricts organization writes
to admin *or* owner), and Section 10.1 (the resolver returns the roles the
scope configuration references). Builds on `Identity` (AIE-1043, ADR 0014),
`parse_path` (AIE-1041, ADR 0015), and the `system/` check (AIE-1040, ADR
0016) in the same `scope` module.

Allow-test-changes: this issue renames `required_role` to `required_roles`
(a set) and adds `RestrictionReason.NOT_GRANTED`, so exactly these
`tests/test_errors.py` changes are permitted. Each is an update to the new
spec text. No test is deleted, skipped, or loosened. Recorded in ADR 0017.
Line numbers are as of commit `9361de3`.

1. `PERMANENT_ERROR_FACTORIES` (~line 50): the `ROLE_REQUIRED` factory's
   `required_role="admin"` becomes `required_roles=frozenset({"admin"})`.
   A third `RestrictedScopeError` factory is inserted after it:
   `RestrictedScopeError("team/t-1/notes/a.md", "team",
   RestrictionReason.NOT_GRANTED)`.
2. The two `ids=[...]` lists for `PERMANENT_ERROR_FACTORIES` (~lines 300 and
   318) become `["restricted_scope_system", "restricted_scope_role",
   "restricted_scope_not_granted", "resolver_failure"]`, matching the
   factory order.
3. `test_restriction_reason_has_exactly_two_members` (~line 287) is renamed
   `test_restriction_reason_has_exactly_three_members`. It expects
   `{"system_read_only", "role_required", "not_granted"}` and length 3.
4. `test_restricted_scope_error_exposes_attributes_unchanged` (~line 335)
   passes `required_roles=frozenset({"admin"})` and asserts
   `err.required_roles == frozenset({"admin"})`.
5. `test_restricted_scope_error_required_role_defaults_to_none` (~line 350)
   is renamed `..._required_roles_defaults_to_none` and asserts
   `err.required_roles is None`.
6. `test_restricted_scope_error_role_required_names_scope_and_role` (~line
   371) passes `required_roles=frozenset({"admin"})`. Its assertions are
   unchanged.
7. Each changed docstring cites both AIE-1030 and AIE-1042.

One change is also permitted in `tests/test_scope_system.py`. After the
rename, the assertion `getattr(err, "required_role", None) is None` (~line
135) is vacuous, so it becomes `err.required_roles is None`. That test's
docstring gains AIE-1042.

No other existing test changes. In particular,
`test_restricted_scope_error_role_required_without_required_role_rejected`
(~line 385) is unchanged, since it omits the role argument and still expects
`ValueError`. `test_restricted_scope_error_system_read_only_names_scope_and_reason`
and `TAXONOMY_KIND_CATEGORIES` are also untouched. No test is deleted or
skipped. New tests for US5 are additions.

## Summary

Add to `src/wenchang/scope.py` the adopter's scope configuration,
`ScopePolicy`, and two pure checks the future tool layer calls before any
mutating call: `check_write_allowed` (grant and role) and `check_write` (the
`system/` check, then `check_write_allowed`). Change
`RestrictedScopeError` to carry a set of permitted roles and add a
`NOT_GRANTED` reason for a write outside the caller's resolved scope or
entity.

Out of scope: wiring the checks into the tool layer (AIE-1044), the resolver
conformance suite (AIE-1039), any check on reads or listing, and any change
to `MemoryStore`, which stays unchecked so the seeding job and admin tooling
can write through core.

## User Scenarios & Testing *(mandatory)*

The "user" is the future tool layer, which holds an `Identity` from
`resolve_identity` and an adopter-supplied `ScopePolicy`, and an adopter
declaring which scopes are write-restricted.

Fixtures used below: `policy = ScopePolicy({"org": frozenset({"admin",
"owner"}), "team": frozenset({"admin"})})`, and `identity` with grants `{"user": ScopeGrant("u-1",
"member"), "org": ScopeGrant("o-9", "member"), "project": ScopeGrant("p-3",
"member")}`.

### User Story 1 - Declare write-restricted scopes (Priority: P1)

**Acceptance Scenarios**:

1. **Given** `policy`, **Then** `is_write_restricted("org")` is true,
   `permitted_roles("org")` is `frozenset({"admin", "owner"})`,
   `permitted_roles("team")` is `frozenset({"admin"})`,
   `is_write_restricted("project")` is false, and
   `permitted_roles("project")` is `None`.
2. **Given** a policy built from a dict, **When** the caller mutates that
   dict afterwards, **Then** the policy is unchanged, and assigning to
   `policy.write_roles[...]` raises `TypeError`.
3. **Given** a scope name that is not a valid path segment (`""`, `"."`,
   `".."`, containing `/`, `\`, or a control character), **When**
   `ScopePolicy` is built, **Then** `ValueError` is raised.
4. **Given** an empty role set, or a role set containing `""`, **When**
   `ScopePolicy` is built, **Then** `ValueError` is raised. The emptiness
   check runs on the normalized copy of the set, so a `frozenset` subclass
   whose `__len__` reports members it doesn't have is also rejected.
5. **Given** two policies built from equal mappings in any insertion order,
   **Then** they compare equal and hash equal. `ScopePolicy({})` is valid and
   restricts nothing.
6. **Given** any scope name, including `"system"`, `"org"`, or
   `"organization"`, **Then** the policy treats it exactly as any other name.
7. **Given** a wrongly typed argument, **When** `ScopePolicy` is built,
   **Then** `TypeError` is raised. The cases are:
   - `write_roles` is not a `Mapping`, e.g. a list of pairs.
   - A key is not a `str`.
   - A value is not a `frozenset`, e.g. `"admin"`, `["admin"]`, or
     `{"admin"}`.
   - A role is not a `str`, e.g. `frozenset({1})`.

   A plain `str` value is rejected rather than read as a set of characters.
   The checks run in the order given in plan.md, so an entry that fails
   several of them raises the first.
8. **Given** `ScopePolicy({"Org": frozenset({"admin"})})` and `identity`,
   **When** `check_write_allowed("org/o-9/notes/a.md", ...)` is called,
   **Then** it returns `None`. Policy keys match the path's scope by exact
   string equality, so a key that matches no scope restricts nothing.
9. **Given** `policy`, **When** it is round-tripped through `pickle` or
   copied with `copy.deepcopy`, **Then** the result equals `policy`.

---

### User Story 2 - Enforce role-gated writes (Priority: P1)

**Acceptance Scenarios**:

1. **Given** `identity` (role `member` in `org`), **When**
   `check_write_allowed("org/o-9/notes/a.md", identity, policy)` is called,
   **Then** `RestrictedScopeError` is raised with `path` the given path,
   `scope == "org"`, `reason == ROLE_REQUIRED`, `required_roles ==
   frozenset({"admin", "owner"})`, permanent category, and a message naming
   `org`, `admin`, and `owner`. With the caller's role in `org` set to
   `role-zq9` instead, the message does not contain `role-zq9`.
2. **Given** an identity whose role in `org` is `admin`, or `owner`, **When**
   the same call is made, **Then** it returns `None`.
3. **Given** `identity`, **When** `check_write_allowed` is called for
   `project/p-3/notes/a.md` or `user/u-1/prefs/a.md` (scopes absent from the
   policy), **Then** it returns `None` for any granted role.
4. **Given** a policy restricting `org` to `{"admin"}` and an identity with
   role `Admin` in `org`, **Then** `ROLE_REQUIRED` is raised. Roles compare
   by exact string equality.

---

### User Story 3 - Reject writes outside the resolved identity (Priority: P1)

**Acceptance Scenarios**:

1. **Given** `identity` (no grant for `team`, which `policy` restricts),
   **When** `check_write_allowed("team/t-1/notes/a.md", identity, policy)` is
   called, **Then** `RestrictedScopeError` is raised with `scope == "team"`,
   `reason == NOT_GRANTED`, `required_roles is None`, permanent category.
   The same holds for an ungranted scope absent from the policy, e.g.
   `club/c-1/notes/a.md`.
2. **Given** `identity` (entity `p-3` in `project`), **When**
   `check_write_allowed("project/p-4/notes/a.md", ...)` is called, **Then**
   `RestrictedScopeError` with `reason == NOT_GRANTED` and `scope ==
   "project"` is raised, even though `project` is unrestricted.
3. **Given** an entity mismatch in a restricted scope where the role would
   also fail (`org/o-8/...`, role `member`), **Then** `NOT_GRANTED` is
   raised, not `ROLE_REQUIRED`.
4. **Given** grants `{"org": ScopeGrant("own-entity-7f3", "role-zq9")}`,
   **When** `org/o-8/notes/a.md` is checked, **Then** the `NOT_GRANTED`
   message contains the path and `org`. It contains neither `own-entity-7f3`
   nor `role-zq9`.
5. **Given** an identity with grants for `project` only, **When**
   `check_write_allowed("org/o-9/notes/a.md", ...)` is called for restricted
   `org`, **Then** `NOT_GRANTED` is raised with `required_roles is None`, not
   `ROLE_REQUIRED`.
6. **Given** `Identity({})`, **When** any valid path is checked, e.g.
   `project/p-3/notes/a.md`, **Then** `NOT_GRANTED` is raised.

---

### User Story 4 - One composite entry point and check order (Priority: P1)

**Acceptance Scenarios**:

1. **Given** a malformed path (e.g. `"org/o-9/notes"`, `"org/o-9/notes/a.txt"`,
   `""`), **When** `check_write_allowed` or `check_write` is called, **Then**
   `NotFoundError(path, INVALID_PATH)` is raised.
2. **Given** a path in the `system` area of a scope the caller is granted and
   permitted in (e.g. `project/p-3/system/a.md`), **When** `check_write` is
   called, **Then** `RestrictedScopeError` with `reason == SYSTEM_READ_ONLY`
   is raised. `check_write_allowed` alone returns `None` for that path.
3. **Given** a path in the `system` area of a scope the caller is not granted,
   **When** `check_write` is called, **Then** `SYSTEM_READ_ONLY` is raised
   (system wins over not-granted).
4. **Given** `identity` and `policy`, **When** each path below is checked,
   **Then** each function raises the listed error or returns `None`. The
   rule is that the first applicable error wins, in the order invalid path,
   then `system/`, then not granted, then role. These rows are the
   parametrized case list for the test.

   | Path | Conditions that apply | `check_write` | `check_write_allowed` |
   | ---- | --------------------- | ------------- | --------------------- |
   | `team/t-1/system/a.txt` | invalid, system, not granted, role | `INVALID_PATH` | `INVALID_PATH` |
   | `org/o-8/system/a.txt` | invalid, system, not granted, role | `INVALID_PATH` | `INVALID_PATH` |
   | `team/t-1/notes` | invalid (3 segments), not granted | `INVALID_PATH` | `INVALID_PATH` |
   | `org/o-9/system` | invalid (3 segments) | `INVALID_PATH` | `INVALID_PATH` |
   | `team/t-1/system/a.md` | system, not granted (scope), role | `SYSTEM_READ_ONLY` | `NOT_GRANTED` |
   | `org/o-8/system/a.md` | system, not granted (entity), role | `SYSTEM_READ_ONLY` | `NOT_GRANTED` |
   | `org/o-9/system/a.md` | system, role | `SYSTEM_READ_ONLY` | `ROLE_REQUIRED` |
   | `project/p-3/system/a.md` | system | `SYSTEM_READ_ONLY` | `None` |
   | `team/t-1/notes/a.md` | not granted (scope), role | `NOT_GRANTED` | `NOT_GRANTED` |
   | `org/o-8/notes/a.md` | not granted (entity), role | `NOT_GRANTED` | `NOT_GRANTED` |
   | `project/p-4/notes/a.md` | not granted (entity) | `NOT_GRANTED` | `NOT_GRANTED` |
   | `org/o-9/notes/a.md` | role | `ROLE_REQUIRED` | `ROLE_REQUIRED` |
   | `project/p-3/notes/a.md` | none | `None` | `None` |
   | `org/o-9/notes/a.md`, identity with grants for `project` only | restricted scope not granted | `NOT_GRANTED` | `NOT_GRANTED` |
   | `project/p-3/notes/a.md`, `Identity({})` | no grants | `NOT_GRANTED` | `NOT_GRANTED` |

   Rows without an identity note use `identity`. For every row returning
   `None`, the test also asserts the SC-001 property: the path's scope is in
   `identity.grants`, with the same entity ID, and the scope is either
   unrestricted or the caller's role is permitted. `INVALID_PATH` means `NotFoundError(path, NotFoundReason.INVALID_PATH)`.
   The other names are `RestrictedScopeError` with that `reason` and `scope`
   equal to the path's first segment.
5. **Given** a path that passes every check, **When** `check_write` is
   called, **Then** it returns `None`.
6. **Given** a non-`str` path, e.g. `None`, `b"org/o-9/notes/a.md"`, or a
   `pathlib.PurePosixPath`, **When** `check_write` or `check_write_allowed`
   is called, **Then** `TypeError` is raised.
7. **Given** a `str` subclass path whose `split` or `__ne__` is overridden to
   lie, e.g. to report the caller's own entity ID or a non-`system` area,
   **When** either check is called, **Then** it gives the same result as for
   the equal plain `str`. Both functions normalize the path to an exact
   `str` with `str.__str__` before any parsing. The error's `path` attribute
   is that exact `str`.

---

### User Story 5 - Error type carries a role set (Priority: P1)

**Acceptance Scenarios**:

1. **Given** `RestrictedScopeError(path, scope, ROLE_REQUIRED,
   required_roles=frozenset({"owner", "editor", "admin", "viewer",
   "billing"}))`, **Then** `required_roles` is that set and the message lists
   the roles sorted: `admin, billing, editor, owner, viewer`. Five roles make
   a correct result by accident of set iteration order vanishingly unlikely.
2. **Given** `ROLE_REQUIRED` with `required_roles` `None` or empty, **Then**
   `ValueError` is raised. **Given** any reason with `required_roles` not
   `None` and not a `frozenset`, e.g. a leftover positional
   `RestrictedScopeError(p, s, ROLE_REQUIRED, "admin")` or a `set`, **Then**
   `TypeError` is raised. The type is checked by real type
   (`issubclass(type(x), frozenset)`), so an object spoofing `__class__` is
   rejected. **Given** a `frozenset` with a non-`str` member, e.g.
   `frozenset({1})`, **Then** `TypeError` is raised. The type checks run
   before the `ValueError` checks.
3. **Given** `SYSTEM_READ_ONLY` or `NOT_GRANTED` with `required_roles` not
   `None`, **Then** `ValueError` is raised. Omitted, it defaults to `None`.
4. **Given** `RestrictionReason`, **Then** it has exactly `SYSTEM_READ_ONLY`,
   `ROLE_REQUIRED`, and `NOT_GRANTED` (value `"not_granted"`).
5. **Given** any reason, **Then** the error is permanent and its message ends
   with the permanent guidance and says not to retry.

### Edge Cases

- A policy may name a scope the identity has no grant for. A write there is
  `NOT_GRANTED`, never `ROLE_REQUIRED` (US3.1, US3.5).
- An identity with no grants can write nothing (US3.6).
- Scope-name matching fails open. A policy key that differs from the
  resolver's scope name, by spelling, case, or Unicode form, restricts
  nothing (US1.8). The adopter must use the resolver's exact scope names.
- A restricted scope is decidable only if the resolver returns a role for it
  (Section 10.1). An ungranted scope is `NOT_GRANTED`, so no case is left
  undecided.
- The checks never consult storage or the resolver. They take an
  already-resolved `Identity`.
- Reads and listing are never checked, including reads of scopes or entities
  the caller is not granted.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `ScopePolicy(write_roles)` MUST be an immutable, hashable value,
  equal by content, that copies its mapping. It MUST reject wrongly typed
  input with `TypeError`: a non-`Mapping`, a non-`str` scope name, a
  non-`frozenset` role set, or a non-`str` role. It MUST reject invalid scope
  names, empty role sets, and empty role strings with `ValueError`. The
  checks run in the order fixed in plan.md. It MUST round-trip through
  `pickle` and `copy.deepcopy`. Policy keys MUST match scopes by exact string
  equality.
- **FR-002**: A scope absent from `write_roles` MUST be unrestricted: any
  granted role may write.
- **FR-003**: `check_write_allowed` MUST raise `RestrictedScopeError(NOT_GRANTED)`
  when the path's scope is not granted or its entity ID differs from the
  caller's entity ID for that scope.
- **FR-004**: `check_write_allowed` MUST raise
  `RestrictedScopeError(ROLE_REQUIRED, required_roles=...)` when the scope is
  restricted and the caller's role is not in its permitted set.
- **FR-005**: `check_write` MUST run the AIE-1040 `system/` check, then
  `check_write_allowed`, raising the first applicable error in the order
  invalid path → `system/` → not granted → role. Both functions MUST reject a
  non-`str` path with `TypeError`. They MUST normalize a `str` path,
  including a subclass, to an exact `str` with `str.__str__` before any
  parsing.
- **FR-006**: A malformed path MUST raise `NotFoundError(path, INVALID_PATH)`.
- **FR-007**: No library code MUST special-case any scope name.
- **FR-008**: `RestrictedScopeError` MUST take `required_roles: frozenset[str]
  | None`, required and non-empty for `ROLE_REQUIRED` and `None` otherwise.
  A value that is not a `frozenset` by real type, or that has a non-`str`
  member, MUST raise `TypeError`. `RestrictionReason` MUST
  gain `NOT_GRANTED`.
- **FR-009**: `MemoryStore` and all read operations MUST be unchanged. No
  new test verifies this. It is covered by AIE-1040's FR-006 import-boundary
  test (`wenchang.core` does not import `wenchang.scope`) and by the
  existing core tests passing unchanged.

## Success Criteria *(mandatory)*

- **SC-001**: For any `str` input, including subclasses, no write path
  accepted by `check_write` lies outside the
  caller's granted scope and entity, in `system/`, or in a restricted scope
  without a permitted role. This is verified by the US4.4 table and its
  per-row property assertion.
- **SC-002**: `make check` passes.

## Assumptions

- The tool layer (AIE-1044) calls `check_write` before every mutating call
  (`write_file`, `append_line`, `replace_fact`, `delete_file`). This issue
  only provides the function.
- A caller may write only under its own entity ID in each granted scope.
  Section 6 says the resolver's fields build the path prefix, so any other
  entity ID is outside the resolved identity.
- A not-granted write is permanent, not recoverable. Retrying the same call
  cannot succeed, and the agent has no legitimate path into another entity.
- The two not-granted sub-cases share one reason and one message. The agent's
  next action is the same, and distinguishing them would reveal the caller's
  entity ID in a message about a path it got wrong.
- Roles are opaque, case-sensitive strings. There is no role hierarchy: an
  adopter lists every permitted role explicitly.
- `ScopePolicy` is supplied by the adopter at startup alongside the
  resolver. How it is loaded (code, config file) is the adopter's concern.
