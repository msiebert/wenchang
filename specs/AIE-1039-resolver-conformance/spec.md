# Feature Specification: Resolver conformance suite

**Linear issue**: AIE-1039 — https://linear.app/mixpanel/issue/AIE-1039/resolver-conformance-suite

**Feature Branch**: `AIE-1039-resolver-conformance`

**Created**: 2026-09-30

**Status**: Draft

**Input**: Linear AIE-1039 ("Build an exhaustive conformance suite that any
identity resolver implementation must pass, covering scope map and role
resolution, path construction correctness, write-restriction enforcement,
and system slash area read-only enforcement") and Notion "Agent Memory
Library — Specification":

- Section 10: "An adopter implements two interfaces: the identity resolver
  (Section 6) and the transport client (Section 7). The library ships an
  executable conformance suite for each. Passing defines a correct
  implementation."
- Section 10.1: the resolver returns a scope-name-to-entity-ID map and a role
  per scope for valid credentials; never raises on bad credentials, returning
  a resolution failure the library converts into the permanent-category
  error; is consistent within a session; and returns roles the adopter's
  scope configuration references, so write-restriction checks are decidable.

Builds on `Identity`, `IdentityResolver`, `resolve_identity`, and
`SandboxResolver` (AIE-1043, ADR 0014), `build_path` / `build_prefix` /
`parse_path` (AIE-1041, ADR 0015), `check_not_system` (AIE-1040, ADR 0016),
and `ScopePolicy` / `check_write` (AIE-1042, ADR 0017).

Allow-test-changes: the `invalid_credentials` fixture of the two
`SandboxResolver` reference subclasses in
`tests/test_resolver_conformance_reference.py` calls `pytest.skip`, because
`SandboxResolver` accepts every credential by design (US2.6). This skips
exactly the three invalid-credential suite methods in those two classes. It
is the documented adopter convention for an accept-everything resolver, not
a weakened test. The token-lookup reference class runs those methods
unskipped. No other `skip` or `xfail` is permitted.

## Summary

Add a new installed subpackage `wenchang.testing` exporting
`ResolverConformance[C]`, a pytest mixin class of test methods. An adopter
subclasses it as `class TestMyResolver(ResolverConformance[MyCreds])` and
supplies six fixtures: `resolver`, `valid_credentials`,
`invalid_credentials`, `policy`, `expected_scopes`, and `known_roles`.
Passing every test defines a conforming resolver. pytest becomes an
optional extra, `wenchang[testing]`, and nothing else in the package imports
it.

The repo runs the suite against `SandboxResolver` (two policy
configurations) and against a token-lookup test resolver, and self-tests
that the suite fails for deliberately broken resolvers.

Out of scope: the transport conformance suite (AIE-1045, AIE-1047), any
production resolver, wiring the resolver or checks into `MemoryStore` or the
tool layer (AIE-1044), and any change to `identity`, `paths`, `scope`, or
`errors`.

## User Scenarios & Testing *(mandatory)*

The "user" is an adopter who has written an `IdentityResolver` and a
`ScopePolicy` and wants to know whether they are correct. "The suite" means
a `Test...` subclass of `ResolverConformance` with the six fixtures
supplied. "Fails" means the test method calls `pytest.fail` with a message
naming the resolver class and containing the key phrase in plan.md.

Reference fixtures used below: `identity` with grants `{"user":
ScopeGrant("u-1", "owner"), "org": ScopeGrant("o-9", "admin")}`, `policy =
ScopePolicy({"org": frozenset({"admin", "owner"}), "team":
frozenset({"admin"})})`, `expected_scopes = frozenset({"user", "org"})`,
`known_roles = frozenset({"owner", "admin", "member"})`. `team` is
restricted but not granted, so the ungranted-scope test has a policy scope
to check. The "member identity" is the same with role `member` in `org`.

### User Story 1 - Valid credentials resolve to an identity (Priority: P1)

**Acceptance Scenarios**:

1. **Given** a resolver returning `identity` for `valid_credentials`,
   **When** `test_valid_credentials_resolve_to_identity` runs, **Then** it
   passes: the result is an `Identity`, its granted scopes equal
   `expected_scopes`, and `resolve_identity` returns an equal `Identity`.
2. **Given** a resolver that raises `RuntimeError` for valid credentials,
   **Then** the test fails (key phrase `must not raise`), rather than
   erroring. The raised `pytest.fail.Exception` has that `RuntimeError` as
   its `__context__`.
3. **Given** a resolver returning `ResolutionFailure` for valid credentials,
   **Then** the test fails (`rejected valid credentials`) and the message
   includes the failure's detail.
4. **Given** a resolver returning something other than `Identity` or
   `ResolutionFailure` (e.g. `None`), **Then** the test fails (`expected
   Identity or ResolutionFailure`) naming the returned type.
5. **Given** a resolver returning an `Identity` with no grants, **Then** the
   test fails (`granted no scopes`), even if `expected_scopes` is empty.
6. **Given** a resolver whose granted scopes differ from `expected_scopes`,
   **Then** the test fails (`granted scopes`) listing both sets sorted.
7. **Given** `resolve_identity` patched to return a different `Identity`
   (self-test only), **When**
   `test_valid_credentials_resolve_through_library_entry_point` runs,
   **Then** it fails (`resolve_identity returned`).
8. **Given** `resolve_identity` patched to raise `ResolverFailureError`
   (self-test only), **Then** the same test fails (`resolve_identity
   raised`), rather than erroring.
9. **Given** an `expected_scopes` fixture that is not a `frozenset` of
   exact `str` (e.g. a list, or a frozenset holding a `str` subclass),
   **Then** the test fails (`fixture expected_scopes`) naming the offending
   type.
10. **Given** a resolver returning an `Identity` subclass whose `grants`
    cannot be read or rebuilt into a base `Identity` (e.g. reading it
    raises), **Then** the test fails (`invalid Identity`).
11. **Given** a resolver returning an `Identity` or `ScopeGrant` subclass
    that overrides `__eq__`, `role()`, or `entity_id()` to report different
    values than its stored grants, **Then** every test judges the stored
    grants, which is what the library's own checks read. For example, a
    subclass whose `role("org")` returns `"admin"` over a stored role of
    `"Admin"` fails `test_roles_are_known_to_scope_configuration` (`not in
    known_roles`).

---

### User Story 2 - Bad credentials degrade cleanly (Priority: P1)

**Acceptance Scenarios**:

1. **Given** a resolver returning `ResolutionFailure` for
   `invalid_credentials`, **When**
   `test_invalid_credentials_return_resolution_failure` runs, **Then** it
   passes.
2. **Given** a resolver that raises any `Exception` for invalid credentials,
   **Then** the test fails (`must not raise`) naming the exception type.
   For a `RuntimeError`, the raised `pytest.fail.Exception` has it as its
   `__context__`.
3. **Given** a resolver returning an `Identity` for invalid credentials,
   **Then** the test fails (`accepted invalid credentials`).
4. **Given** a resolver returning `None` for invalid credentials, **Then**
   the test fails (`expected Identity or ResolutionFailure`).
5. **Given** a conforming resolver, **When**
   `test_invalid_credentials_raise_permanent_resolver_failure_error` runs,
   **Then** `resolve_identity` raises `ResolverFailureError` whose category
   is `PERMANENT`, and the test passes. The test first checks the resolver
   with the same rule as US2.1–4, so a resolver accepting invalid
   credentials fails with `accepted invalid credentials`, not pytest's own
   "DID NOT RAISE".
6. **Given** an `invalid_credentials` fixture that calls `pytest.skip`
   (a resolver that accepts every credential, such as `SandboxResolver`),
   **Then** every test that takes `invalid_credentials` is reported skipped,
   and every other test still runs.
7. **Given** `resolve_identity` patched to raise a `ResolverFailureError`
   subclass whose category is `TRANSIENT` (self-test only), **When**
   `test_invalid_credentials_raise_permanent_resolver_failure_error` runs,
   **Then** it fails (`not permanent`).
8. **Given** `resolve_identity` patched to return an `Identity` (self-test
   only), **Then** the same test fails (`did not raise
   ResolverFailureError`).

---

### User Story 3 - Consistent within a session (Priority: P1)

**Acceptance Scenarios**:

1. **Given** a resolver returning equal `Identity` values on repeated calls,
   **When** `test_valid_resolution_is_consistent` runs, **Then** it passes.
   It resolves the same `valid_credentials` object three times and compares
   by value.
2. **Given** a resolver whose second or third result differs (a different
   entity ID, role, or scope), **Then** the test fails (`different results`)
   naming the call number.
3. **Given** a resolver returning `ResolutionFailure` for invalid
   credentials on every call, **When** `test_invalid_resolution_is_consistent`
   runs, **Then** it passes, whatever each failure's `detail` says.
4. **Given** a resolver that rejects invalid credentials on the first call
   but returns an `Identity` on call 2, **Then** the test fails (`accepted
   invalid credentials`) and the message contains `on call 2`.
5. **Given** a resolver that succeeds on call 1 and raises on call 2 for
   valid credentials, **Then** the test fails (`must not raise`) and the
   message contains `on call 2`.
6. **Given** a resolver returning `Identity` subclasses whose `__eq__`
   always returns True, but whose stored grants differ on call 2, **Then**
   `test_valid_resolution_is_consistent` fails (`different results`). The
   comparison is between canonical base `Identity` values.

---

### User Story 4 - Roles are decidable (Priority: P1)

**Acceptance Scenarios**:

1. **Given** a resolver whose role in every granted scope is in
   `known_roles`, and a policy whose every permitted role is in
   `known_roles`, **When** `test_roles_are_known_to_scope_configuration`
   runs, **Then** it passes.
2. **Given** a resolver returning role `"Admin"` when `known_roles` holds
   `"admin"`, **Then** the test fails (`not in known_roles`) naming the
   scope and role. Roles compare by exact string equality.
3. **Given** a `known_roles` fixture that is not a `frozenset` of `str`
   (e.g. the string `"admin owner"`, where `in` would be a substring test),
   **Then** the test fails (`fixture known_roles`).
4. **Given** a policy permitting `"Admin"` in `org` while `known_roles` and
   the resolver use `"admin"`, **Then** the test fails (`policy role`)
   naming the scope and role. Such a scope is unwritable by every caller,
   which is the undecidable case Section 10.1 names.

---

### User Story 5 - Path construction (Priority: P1)

**Acceptance Scenarios**:

1. **Given** a conforming resolver, **When**
   `test_granted_scopes_build_valid_paths` runs, **Then** for every granted
   scope `s` with entity ID `e`: `build_path(s, e, "notes",
   "conformance-probe")` satisfies `is_valid_path`, `parse_path` of it
   equals `PathParts(s, e, "notes", "conformance-probe")`, `build_prefix(s,
   e)` satisfies `is_valid_prefix`, and the path starts with that prefix.
2. **Given** the module's `build_path` replaced by one returning a malformed
   path (self-test only), **Then** the test fails (`invalid path`).
3. **Given** the module's `parse_path` patched to return `PathParts` with a
   different name (self-test only), **Then** the test fails (`does not
   round-trip`).
4. **Given** the module's `build_prefix` patched to return `"bad"`
   (self-test only), **Then** the test fails (`invalid prefix`).
5. **Given** the module's `build_prefix` patched to return a valid prefix
   for another scope (self-test only), **Then** the test fails (`not under
   prefix`).

---

### User Story 6 - system/ is read-only (Priority: P1)

**Acceptance Scenarios**:

1. **Given** a conforming resolver and `policy`, **When**
   `test_system_area_is_read_only_in_every_scope` runs, **Then** for every
   granted scope `s`, `check_write` on `s/<own entity>/system/...` and on
   `s/<foreign entity>/system/...` raises `RestrictedScopeError` with
   `reason SYSTEM_READ_ONLY` and `scope == s`, whatever the caller's role.
   The same holds for a `system/` path in an ungranted scope, which pins
   that the `system/` check precedes the not-granted check.
2. **Given** the module's `check_write` replaced by a no-op (self-test
   only), **Then** the test fails (`not rejected`). Replaced by one that
   always raises `NOT_GRANTED`, it fails (`wrong reason`).

---

### User Story 7 - Write restriction (Priority: P1)

**Acceptance Scenarios**:

1. **Given** `identity` and `policy` (role `admin` in restricted `org`),
   **When** `test_own_entity_writes_follow_policy` runs, **Then** it passes:
   `check_write` on `org/o-9/notes/...` and `user/u-1/notes/...` returns
   `None`.
2. **Given** role `member` in `org`, **Then** the test still passes:
   `check_write` on `org/o-9/notes/...` raises `ROLE_REQUIRED` with
   `required_roles == policy.permitted_roles("org")`, which is the expected
   outcome. The test asserts the outcome the policy predicts, not that every
   write succeeds.
3. **Given** a conforming resolver, **When**
   `test_foreign_entity_writes_are_not_granted` runs, **Then** for every
   granted scope, a `notes` path under a different entity ID raises
   `NOT_GRANTED`.
4. **Given** a conforming resolver, **When**
   `test_ungranted_scope_writes_are_not_granted` runs, **Then** a `notes`
   path in a scope name absent from the grants, and in every
   policy-restricted scope absent from the grants, raises `NOT_GRANTED`.
5. **Given** the module's `check_write` patched (self-tests only), with the
   reference identity (`admin` in `org`) or the member identity, **Then**
   each test gives exactly this outcome. "Passes" cells are not self-tests.
   Each patched function raises with `scope` equal to the path's first
   segment.

   | Patch | system | own, admin | own, member | foreign | ungranted |
   | ----- | ------ | ---------- | ----------- | ------- | --------- |
   | no-op | `not rejected` | passes | `not rejected` | `not rejected` | `not rejected` |
   | always `NOT_GRANTED` | `wrong reason` | `unexpected outcome` | `wrong reason` | passes | passes |
   | always `SYSTEM_READ_ONLY` | passes | `unexpected outcome` | `wrong reason` | `wrong reason` | `wrong reason` |
   | always `NotFoundError(INVALID_PATH)` | `wrong reason` | `unexpected outcome` | `wrong reason` | `wrong reason` | `wrong reason` |

   The own-entity test iterates scopes sorted, so `org` is checked before
   `user`.
6. **Given** the member identity and `check_write` patched to raise
   `ROLE_REQUIRED` with `required_roles=frozenset({"x"})` (self-test only),
   **Then** `test_own_entity_writes_follow_policy` fails (`wrong
   required_roles`).
7. **Given** `check_write` patched to raise an `Exception` that is not a
   `RestrictedScopeError`, **Then** each test that expects a restriction
   fails (`wrong reason`) naming the exception type, and the own-entity
   test fails (`unexpected outcome`) where it expects `None`. Neither
   errors. The last row of the US7.5 table covers this.

---

### User Story 8 - Reference runs (Priority: P1)

**Acceptance Scenarios**:

1. **Given** `SandboxResolver(identity)` with role `admin` in `org` and
   `policy`, **When** the suite runs, **Then** every test passes except the
   three taking `invalid_credentials`, which are skipped.
2. **Given** the same with role `member` in `org`, **Then** the same result.
3. **Given** a token-lookup resolver (a known token → `identity`, anything
   else → `ResolutionFailure`), **Then** every test passes and none is
   skipped.

---

### User Story 9 - Packaging (Priority: P1)

**Acceptance Scenarios**:

1. **Given** the installed package, **Then** `from wenchang.testing import
   ResolverConformance` works, and its name does not start with `Test`, so
   pytest does not collect the mixin itself.
2. **Given** `pyproject.toml`, **Then** `[project.optional-dependencies]`
   has a `testing` extra requiring `pytest`.
3. **Given** every module under `src/wenchang/` outside
   `src/wenchang/testing/`, **Then** none imports `pytest` or `_pytest`,
   and none imports `wenchang.testing` in any form: `import
   wenchang.testing`, `from wenchang import testing`, `from wenchang.testing
   import ...`, or the relative `from . import testing` / `from .testing
   import ...`.
4. **Given** `ResolverConformance`, **Then** its `test_*` method names are
   exactly the twelve listed in plan.md.
5. **Given** every file under `src/wenchang/testing/`, **Then** none matches
   the regex `AIE-\d+`.
6. **Given** a subprocess where `sys.modules["pytest"] = None`, **When**
   every module of `wenchang` outside `wenchang.testing` is imported via
   `pkgutil.walk_packages`, **Then** every import succeeds.
7. **Given** `src/wenchang/testing/resolver_conformance.py`, **Then** it
   applies no pytest marks: no `pytestmark` and no `pytest.mark` decorator.
   Adopters mark their own `Test` subclass, so `--strict-markers` never
   trips on an unregistered mark.

### Edge Cases

- User Stories 5–7 cannot fail for a resolver that passes User Story 1,
  because `Identity` validates every segment (ADR 0014) and the scope checks
  are pure (ADR 0017). They run the adopter's own identity and policy
  end-to-end, and they fail if the library regresses. The self-tests prove
  they can fail by patching the functions the suite calls.
- An adopter who needs several credential shapes parametrizes their own
  `valid_credentials` fixture. Each parameter runs the whole suite.
- The suite never inspects or logs credentials. Failure messages name the
  resolver class and exception type. The original exception stays attached
  as implicit context, so pytest shows it for debugging (human decision).
- A `check_write` exception that is not a `RestrictedScopeError` is a suite
  failure, not a test error.
- A resolver can return a subclass of `Identity` or `ScopeGrant` that lies
  through its methods. The library's checks read the stored grants'
  attributes, so the suite rebuilds and judges those, and the lie cannot
  pass the suite while the library sees something else.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `wenchang.testing` MUST export `ResolverConformance`, generic
  in the credentials type, whose test methods take only the six fixtures
  named in plan.md.
- **FR-002**: The suite MUST call `resolver.resolve` directly to check the
  contract, so a raising resolver fails the suite instead of being masked by
  `resolve_identity`.
- **FR-003**: The suite MUST report every contract violation with
  `pytest.fail(message)`, never a bare `assert`, and each message MUST name
  the resolver class and contain the key phrase in plan.md.
- **FR-004**: The suite MUST cover every Section 10.1 clause and every
  AIE-1039 clause, one test method or more each, per the table in plan.md.
- **FR-005**: `pyproject.toml` MUST declare `testing = ["pytest>=8.3"]` under
  `[project.optional-dependencies]`. No module outside `wenchang.testing`
  may import pytest.
- **FR-006**: The shipped module MUST NOT cite Linear IDs (US9.5). Test
  docstrings under `tests/` MUST cite AIE-1039.
- **FR-007**: The suite MUST validate `expected_scopes` and `known_roles` as
  `frozenset`s of `str` before using them.
- **FR-008**: The shipped module MUST apply no pytest marks (US9.7).
- **FR-009**: The suite MUST judge a canonical base `Identity` rebuilt from
  the stored grants' attributes, never the resolver's returned object. It
  MUST classify results with `issubclass(type(x), ...)`, and MUST read type
  names with a fallback of `"<unnamed>"` if `__name__` raises.

## Success Criteria *(mandatory)*

- **SC-001**: `SandboxResolver` and the token-lookup resolver pass the
  suite, and each broken resolver in the self-tests fails at least one
  named test.
- **SC-002**: `make check` passes.

## Assumptions

- "Consistent within a session" is tested by resolving the same credentials
  object three times. The suite has no notion of a session boundary, so a
  pytest test is the session.
- Consistency for invalid credentials means every call returns a
  `ResolutionFailure`. `detail` may differ between calls, e.g. a timestamp.
- "Roles the configuration references" needs a set the suite can check
  against, which `ScopePolicy` does not hold: it lists only roles permitted
  to write. The adopter supplies `known_roles`, every role their resolver
  may return. The suite checks both sides against it: every granted role,
  and every role the policy permits. A role absent from the policy, such as
  `member`, is legitimate.
- `expected_scopes` is required. "Non-empty" alone would pass a resolver
  that silently drops a scope.
- The suite never mutates the resolver or policy, and never touches
  storage.
