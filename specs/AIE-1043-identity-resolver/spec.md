# Feature Specification: identity resolver interface

**Linear issue**: AIE-1043 — https://linear.app/mixpanel/issue/AIE-1043/identity-resolver-interface

**Feature Branch**: `AIE-1043-identity-resolver`

**Created**: 2026-09-30

**Status**: Draft

**Input**: Linear AIE-1043 and Notion "Agent Memory Library — Specification",
Section 6 (the library has no notion of users, organizations, or roles; it
consumes an injected resolver that turns caller credentials into a map of
scope name to entity ID plus the caller's role per scope; a sandbox resolver
returns hardcoded constants, a production resolver performs a real
permission check) and Section 10.1 "Resolver conformance" (never raises on
bad credentials, returns a resolution failure the library converts into the
permanent-category error; consistent within a session).

## Summary

Add `src/wenchang/identity.py` with the identity value types (`ScopeGrant`,
`Identity`, `ResolutionFailure`), the `IdentityResolver` protocol, the
library's single entry point `resolve_identity`, and `SandboxResolver`, the
reference implementation that returns a fixed `Identity` for any
credentials. `paths.is_valid_segment` becomes public and rejects `/`, so
identity validation uses the same segment rule as paths.

Out of scope: path construction (`build_path` / `build_prefix` /
`parse_path`, AIE-1041), `system/` read-only enforcement (AIE-1040),
role-gated write restriction (AIE-1042), the resolver conformance suite
(AIE-1039), any production resolver, and wiring the resolver into
`MemoryStore`, transport, or tools.

## User Scenarios & Testing *(mandatory)*

The "user" is library code (the future tool layer, later milestone issues)
and an adopter writing a resolver.

### User Story 1 - Represent a resolved identity (Priority: P1)

**Acceptance Scenarios**:

1. **Given** grants `{"user": ScopeGrant("u-1", "owner"), "org": ScopeGrant("o-9", "member")}`,
   **When** an `Identity` is built, **Then** `scope_map` is
   `{"user": "u-1", "org": "o-9"}`, `role("org")` is `"member"`, and
   `entity_id("user")` is `"u-1"`.
2. **Given** an `Identity` built from a dict, **When** the caller mutates that
   dict afterwards, **Then** the `Identity` is unchanged.
3. **Given** an `Identity`, **When** the caller mutates the dict returned by
   `scope_map`, **Then** the `Identity` is unchanged. Assigning to
   `identity.grants[...]` raises `TypeError`.
4. **Given** two `Identity` values built from equal grants (in any insertion
   order), **Then** they compare equal and hash equal. Different entity IDs,
   roles, or scope names compare unequal.
5. **Given** empty grants, **Then** an `Identity` is built and `scope_map` is
   `{}`.
6. **Given** an `Identity`, **When** `role(s)` or `entity_id(s)` is called for
   a scope `s` it has no grant for, **Then** `KeyError` is raised.
7. **Given** an `Identity`, **When** it is round-tripped through
   `pickle.dumps` / `pickle.loads` or copied with `copy.deepcopy`, **Then** the
   result is an `Identity` equal to the original. For an instance of a
   module-level `Identity` subclass, the result has the same subclass type.

---

### User Story 2 - Reject malformed identity values (Priority: P1)

**Acceptance Scenarios**:

1. **Given** an `entity_id` that is one of the US2.5 rejected values, **When**
   `ScopeGrant` is built, **Then** `ValueError` is raised.
2. **Given** `role == ""`, **When** `ScopeGrant` is built, **Then**
   `ValueError` is raised.
3. **Given** each of the US2.5 rejected values used as a scope name, **When**
   `Identity` is built, **Then** `ValueError` is raised.
4. **Given** `detail == ""`, **When** `ResolutionFailure` is built, **Then**
   `ValueError` is raised. **Given** a non-`str` `detail` (e.g. `1` or
   `None`), **Then** `TypeError` is raised.
5. **Given** each of `""`, `"."`, `".."`, `"/"`, `"a/b"`, `"a\\b"`,
   `"a\x00b"`, `"\x7f"`, `"\x85"`, **When** `paths.is_valid_segment` is
   called, **Then** it returns False. **Given** each of `"u-1"`, `"a.b"`,
   `"..."`, `"é"`, `"a b"`, **Then** it returns True. It never raises.
6. **Given** `"a/b"`, **When** `is_valid_segment` is called, **Then** it
   returns False.
7. **Given** a `ScopeGrant` whose `entity_id` or `role` is not a `str` (e.g.
   `1` or `None`), **When** it is built, **Then** `TypeError` is raised.
8. **Given** grants with a non-`str` key (e.g. `{1: ScopeGrant("u-1",
   "owner")}`), or `grants` that is not a `Mapping` (e.g. a list of pairs),
   **When** `Identity` is built, **Then** `TypeError` is raised.
9. **Given** grants with a value that is not a `ScopeGrant` (e.g. `{"user":
   "u-1"}` or `{"user": ("u-1", "owner")}`), **When** `Identity` is built,
   **Then** `TypeError` is raised.
10. **Given** a `str` subclass that overrides methods such as `__eq__`,
    `__hash__`, `__str__`, or `split`, with underlying value `"a/b"`, used as
    a scope name, `entity_id`, or `role`, or as a `ResolutionFailure` detail,
    **Then** validation applies to the underlying value, so `"a/b"` is
    rejected with `ValueError`. **Given** such a subclass with a valid
    underlying value, **Then** the stored value has `type(v) is str` and
    equals the underlying value.
11. **Given** a `Mapping` whose `items()` yields valid pairs but whose
    `keys()` and `__getitem__` yield an invalid scope name or a non-`ScopeGrant`
    value, **When** `Identity` is built, **Then** the invalid value is
    rejected. The mapping is read once, and exactly what was validated is
    stored.
12. **Given** grants with two distinct keys that normalize to the same plain
    string (e.g. `"a"` and a `str` subclass `"a"` with a different hash),
    **When** `Identity` is built, **Then** `ValueError` is raised rather than
    one grant being silently dropped.

---

### User Story 3 - Resolve through the library entry point (Priority: P1)

**Acceptance Scenarios**:

1. **Given** a resolver returning an `Identity`, **When**
   `resolve_identity(resolver, creds)` is called, **Then** it returns that
   same `Identity` object, and the resolver received `creds` unchanged.
2. **Given** a resolver returning `ResolutionFailure("token expired")`,
   **Then** `ResolverFailureError` is raised whose `detail` begins with
   `"token expired"` and whose category is permanent.
3. **Given** a resolver that raises an exception whose message contains a
   secret, **Then** `ResolverFailureError` is raised, its message names the
   resolver class and the exception type, and it does not contain the secret.
   Its `__cause__` is `None` and its `__suppress_context__` is `True`, so
   standard traceback rendering omits the original exception. `__context__`
   still references it per Python semantics. Tests MUST NOT assert
   `__context__ is None`.
4. **Given** a resolver that returns something other than an `Identity` or
   `ResolutionFailure` (e.g. `None`), **Then** `ResolverFailureError` is
   raised naming the resolver class and the returned type. **Given** a
   returned object whose `__class__` property raises, or whose type's
   `__name__` raises or is a `str` subclass overriding `__format__`, **Then**
   `ResolverFailureError` is still raised and no exception from that object
   escapes. **Given** a returned `ResolutionFailure` subclass whose `detail`
   cannot be read or formatted, **Then** `ResolverFailureError` is raised
   whose detail begins with `"Resolver {name} returned an invalid
   ResolutionFailure."`.
5. **Given** a resolver that raises `KeyboardInterrupt` (a `BaseException`
   that is not an `Exception`), **Then** it propagates unchanged.
6. **Given** a resolver that raises `ResolverFailureError("x")` or any other
   `WenchangError`, **Then** a new `ResolverFailureError` naming the resolver
   class and exception type is raised. The original is not passed through and
   its detail is not reused.

---

### User Story 4 - Sandbox resolver (Priority: P1)

**Acceptance Scenarios**:

1. **Given** `SandboxResolver(identity)`, **When** `resolve` is called with
   any credentials (`None`, a string, a dict, an arbitrary object), **Then**
   it returns `identity` every time.
2. **Given** a `SandboxResolver`, **Then** `isinstance(resolver,
   IdentityResolver)` is true, and an object with no `resolve` method is not.
3. **Given** a `SandboxResolver`, **When** passed to `resolve_identity`,
   **Then** it returns the configured identity.

### Edge Cases

- An `Identity` with no grants is valid. It gives the caller no scope, and
  any later path construction against it fails at that layer.
- Credentials are opaque to the library. `resolve_identity` never inspects,
  stores, logs, or includes them in any error.
- Roles are opaque adopter-defined strings. Nothing in this issue interprets
  them.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `ScopeGrant(entity_id, role)` MUST be an immutable value. It
  rejects a non-`str` `entity_id` or `role` with `TypeError`, and an
  `entity_id` failing `is_valid_segment` or an empty `role` with `ValueError`.
- **FR-002**: `Identity(grants)` MUST be an immutable, hashable value, equal by
  content, that copies `grants` on construction. It rejects a non-`str` key or
  a non-`ScopeGrant` value with `TypeError`, and a scope name failing
  `is_valid_segment` or colliding after normalization with `ValueError`. It
  reads `grants` once into a snapshot and validates and stores that snapshot.
  It exposes `scope_map`, `role(scope)`, and `entity_id(scope)`, and
  round-trips through `pickle` and `copy.deepcopy`, preserving its subclass.
- **FR-003**: `ResolutionFailure(detail)` MUST reject a non-`str` `detail`
  with `TypeError` and an empty `detail` with `ValueError`.
- **FR-004**: `IdentityResolver` MUST be a runtime-checkable protocol, generic
  in the credentials type, with one method `resolve(credentials) -> Identity |
  ResolutionFailure`.
- **FR-005**: `resolve_identity` MUST return a resolver's `Identity`
  unchanged, and MUST convert a `ResolutionFailure`, a raised `Exception`, or
  a wrongly typed return into `ResolverFailureError`. It MUST NOT put
  credentials or a raised exception's message into the error, and MUST NOT
  chain the raised exception (`from None`).
- **FR-006**: `SandboxResolver(identity).resolve(credentials)` MUST return
  `identity` for every input and never fail.
- **FR-007**: `paths.is_valid_segment` MUST be public. It returns False for
  `""`, `"."`, `".."`, and any string containing `/`, a backslash, or a
  Unicode `Cc` character, and True otherwise. It never raises.
  `is_valid_path` and `is_valid_prefix` behave exactly as before.
- **FR-008**: Every `str` field and scope name MUST be normalized to an exact
  `str` via `str.__str__(value)` before validation and storage, so a `str`
  subclass cannot defeat validation.

## Success Criteria *(mandatory)*

- **SC-001**: No resolver behavior reaches a caller of `resolve_identity` as
  anything other than an `Identity` or a `ResolverFailureError`, except a
  non-`Exception` `BaseException`. That includes raising, and a returned
  object whose `__class__`, type name, or `__format__` raises.
- **SC-002**: `make check` passes.

## Assumptions

- A resolution failure is always permanent. A production resolver whose own
  auth backend is briefly down still reports `ResolutionFailure`. There is no
  transient resolver outcome (human decision, recorded in plan.md).
- Every granted scope carries exactly one role. A scope with "no role" is
  expressed by the adopter choosing a role string for it.
- The sandbox resolver's "hardcoded constants" are supplied by the adopter at
  construction rather than baked into the library, since the library has no
  notion of which scopes exist.
- Rejecting `/` in `is_valid_segment` closes the only key-splicing vector.
  `.` and `..` are already rejected as whole segments, and storage keys have
  no traversal semantics.
- Session consistency (identical credentials → identical identity) is a
  resolver contract checked by the AIE-1039 conformance suite. The library
  does not cache or verify it.
