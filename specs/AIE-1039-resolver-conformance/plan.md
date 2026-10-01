# Implementation Plan: Resolver conformance suite

**Linear issue**: AIE-1039 | **Branch**: `AIE-1039-resolver-conformance` | **Date**: 2026-09-30 | **Spec**: [spec.md](spec.md)

## Summary

Add `src/wenchang/testing/` with `__init__.py` and
`resolver_conformance.py`, exporting the generic pytest mixin
`ResolverConformance[C]`. Add the `testing` optional extra to
`pyproject.toml`. Add three test files: reference runs, self-tests that the
suite bites, and packaging checks. No existing module changes.

## Technical Context

Python ≥ 3.12 (PEP 695 generics); pytest; pyright strict over `src/` and
`tests/`; ruff (line length 100). `wenchang.testing.resolver_conformance`
imports `pytest`, `wenchang.errors`, `wenchang.identity`, `wenchang.paths`,
and `wenchang.scope`. Nothing in the library imports `wenchang.testing`.

**Dependencies, all merged first.** The suite exercises every public name
the four siblings add:

- AIE-1043: `Identity`, `ScopeGrant`, `ResolutionFailure`,
  `IdentityResolver`, `resolve_identity`, `SandboxResolver`.
- AIE-1041: `PathParts`, `build_path`, `build_prefix`, `parse_path`.
- AIE-1040: `SYSTEM_AREA`.
- AIE-1042: `ScopePolicy`, `check_write`, `RestrictionReason.NOT_GRANTED`,
  `RestrictedScopeError.required_roles`.

**Verified in a scratch project with the repo's pytest 9 and pyright
strict:** a `Test...` subclass of a PEP 695 generic mixin
(`class TestX(Mixin[str])`) is collected and runs its inherited methods. A
fixture method that calls `pytest.skip` skips every test requesting it,
and pyright accepts it with a non-`None` return annotation because
`pytest.skip` is `NoReturn`. Calling a mixin method directly inside
`pytest.raises(pytest.fail.Exception)` catches a `pytest.fail`, and
`pytest.fail.Exception` type-checks.

## Constitution Check

| Principle | Status |
| --------- | ------ |
| I. Tests-first | T1–T3 each test-writer → implementer. The reference and self-tests are written first against the interface below |
| II. Tests not negotiable | No existing test changes |
| IV. Strict typing | Mixin generic in `C`. Every fixture parameter annotated. `cast(object, ...)` widening and `issubclass(type(...), ...)` checks as in `resolve_identity` |
| V. Storage only through interface | No storage access |
| VI. Spec fidelity | Implements Sections 10 and 10.1. `known_roles` makes the "roles the configuration references" clause checkable, recorded in ADR 0018 |
| VII. Architecture documented | New public subpackage and packaging extra → ARCHITECTURE.md + ADR 0018 |
| VIII. Traceability | Test docstrings cite AIE-1039. The shipped module cites no Linear IDs |
| IX. Small PR | One new subpackage, one `pyproject.toml` entry, three test files |

**Decisions to record in ADR 0018:**

1. **The suite ships inside the installed package as `wenchang.testing`.**
   Adopters run it against their own resolver, so it cannot live under
   `tests/`, which is not installed. The storage suite
   (`tests/storage_conformance.py`) stays in `tests/` because storage is not
   an adopter surface. Rejected: a separate `wenchang-testing` distribution,
   which adds a second version to keep in lockstep for one module. Also
   rejected: a pytest plugin entry point that auto-registers fixtures, which
   would load into every adopter test session and hide the contract.
2. **pytest is an optional extra, `wenchang[testing]`, imported at the top
   of the suite module.** Only `wenchang.testing` imports it, and the
   library never imports `wenchang.testing`, so `import wenchang` works
   without pytest. Rejected: a pytest-free suite of plain `assert`s. An
   installed module is not assertion-rewritten, so a bare `assert` fails
   with no message, and `python -O` strips it. It also cannot skip. Also
   rejected: a `unittest.TestCase` base, which has no fixtures and diverges
   from the storage-suite precedent.
3. **Violations are reported with `pytest.fail(message)`, never `assert`.**
   Each message names the resolver class and a fixed key phrase, so an
   adopter sees what broke and self-tests can match it. A caught exception
   is not suppressed, so pytest shows it as context. This differs from ADR
   0014's `from None`: here the adopter is debugging their own resolver with
   their own test credentials (human decision, 2026-09-30).
4. **Contract: a generic mixin plus six required fixtures.** `resolver`,
   `valid_credentials`, `invalid_credentials`, `policy`, `expected_scopes`,
   `known_roles`. Generic in `C` so an adopter's `IdentityResolver[MyCreds]`
   types cleanly. A missing fixture is a pytest collection error, which
   forces an explicit choice. Rejected: an optional `expected_scopes`
   (non-empty alone passes a resolver that drops a scope). Also rejected: a
   `has_invalid_credentials` class flag. A resolver that accepts everything
   has its `invalid_credentials` fixture call `pytest.skip`, which is
   idiomatic and adds no knob.
5. **Decidability means every granted role, and every role the policy
   permits, is in `known_roles`.** Section 10.1 wants roles "the adopter's
   scope configuration references". `ScopePolicy` lists only roles
   permitted to write, so it cannot say whether `"member"` is a real role or
   a typo of one. The adopter supplies the full set (human decision). The
   policy side catches a typo such as `"Admin"` in the policy against a
   resolver's `"admin"`, which would leave the scope unwritable by anyone.
   A known role the policy never mentions, such as `member`, is legitimate.
   Rejected: requiring the role to be in `permitted_roles`, which would
   demand every caller can write. Also rejected: asserting only that the
   role is non-empty, which `ScopeGrant` already guarantees. Both fixtures
   are checked to be `frozenset`s of `str` first, since a `str`
   `known_roles` would turn `in` into a substring test.
6. **Consistency is three resolves of the same credentials object,
   compared by value.** Invalid credentials must give a `ResolutionFailure`
   every time, with any `detail`. Rejected: resolving a deep copy, since
   credentials may hold uncopyable handles. Also rejected: comparing
   failure details, which may carry timestamps.
7. **The suite calls `resolver.resolve` directly for contract checks and
   `resolve_identity` only for the conversion check.** `resolve_identity`
   converts a raise into `ResolverFailureError`, which would hide the one
   violation Section 10.1 calls a crash.
8. **The path and enforcement tests run the adopter's identity and policy
   end-to-end, though a valid `Identity` cannot fail them.** They are in the
   suite because the issue names them, and they catch a library regression
   in the adopter's configuration. The self-tests prove they can fail by
   patching the module-level names they call.
9. **Self-tests call mixin methods directly and expect
   `pytest.fail.Exception`.** Rejected: `pytester` subprocess runs, which
   are slower and need the plugin enabled. The reference runs already
   exercise collection and skipping end to end.
10. **Adversarial hardening: the suite judges the values the library
    reads, not the resolver's own objects.** Code review found that a
    resolver returning an `Identity` or `ScopeGrant` subclass with a lying
    `__eq__`, or an overridden `role()` or `entity_id()`, passed all twelve
    methods. So:
    - `_resolve_valid` canonicalizes the result to a base `Identity` built
      from base `ScopeGrant`s, reading the stored grants' attributes:
      `Identity({s: ScopeGrant(g.entity_id, g.role) for s, g in
      result.grants.items()})`. Any `Exception` while doing so fails with
      `invalid Identity`. The entry-point test canonicalizes the
      `resolve_identity` result the same way. Every later comparison and
      read uses the canonical value, which is exactly what the library's own
      checks read.
    - Type tests use `issubclass(type(result), ...)`, not `isinstance`,
      matching `resolve_identity`, so an overridden `__class__` cannot
      pass.
    - Resolver and exception type names go through `_name`, which falls
      back to `"<unnamed>"` if `__name__` raises, like
      `identity._type_name`.
    - `_check_fixture` returns a plain `frozenset` of exact `str` members
      and names the offending member's type.
    Rejected: trusting the returned objects' own methods, which lets a
    resolver report one identity to the suite and another to the library.

## Public interface

### `pyproject.toml`

```toml
[project.optional-dependencies]
testing = ["pytest>=8.3"]
```

The implementer runs `uv lock` after the edit so `uv.lock` records the
extra. The dev group keeps its own `pytest` entry.

### `src/wenchang/testing/__init__.py`

```python
"""Conformance suites adopters run against their implementations.

Requires the `testing` extra: `pip install "wenchang[testing]"`.
"""

from wenchang.testing.resolver_conformance import ResolverConformance

__all__ = ["ResolverConformance"]
```

### `src/wenchang/testing/resolver_conformance.py`

Module docstring (user-facing; no Linear IDs), in substance:

```python
"""Conformance suite for IdentityResolver implementations.

Subclass ResolverConformance in a test module, with a class name starting
with "Test", and supply these fixtures:

    resolver             the IdentityResolver under test
    valid_credentials    credentials it must accept
    invalid_credentials  credentials it must reject; call pytest.skip if it
                         accepts every credential
    policy               your ScopePolicy
    expected_scopes      frozenset of scope names valid_credentials must grant
    known_roles          frozenset of every role your resolver may return

Example:

    class TestMyResolver(ResolverConformance[MyCreds]):
        @pytest.fixture
        def resolver(self) -> IdentityResolver[MyCreds]:
            return MyResolver()
        ...

Passing every test defines a conforming resolver.
"""
```

The module and class carry no pytest marks: no `pytestmark` and no
`@pytest.mark...`. Callers mark their own `Test` subclass, so an adopter
running `--strict-markers` never hits an unregistered mark.

Imports are module-level names, not qualified access, so the self-tests
can patch them with `monkeypatch.setattr(resolver_conformance, name, ...)`:

```python
from typing import cast

import pytest

from wenchang.errors import (
    ErrorCategory,
    RestrictedScopeError,
    RestrictionReason,
    ResolverFailureError,
)
from wenchang.identity import Identity, IdentityResolver, ResolutionFailure
from wenchang.paths import (
    PathParts,
    build_path,
    build_prefix,
    is_valid_path,
    is_valid_prefix,
    parse_path,
)
from wenchang.scope import SYSTEM_AREA, ScopePolicy, check_write
```

Private constants: `_PROBE_AREA = "notes"`, `_PROBE_NAME =
"conformance-probe"`, `_CONSISTENCY_CALLS = 3`,
`_UNGRANTED_SCOPE = "conformance-ungranted"`,
`_UNGRANTED_ENTITY = "conformance-entity"`.

```python
class ResolverConformance[C]:
    """Tests every IdentityResolver must pass. Subclass with a Test* name and supply fixtures."""

    def test_valid_credentials_resolve_to_identity(
        self, resolver: IdentityResolver[C], valid_credentials: C, expected_scopes: frozenset[str]
    ) -> None:
        """Valid credentials resolve to an Identity granting exactly expected_scopes."""

    def test_valid_credentials_resolve_through_library_entry_point(
        self, resolver: IdentityResolver[C], valid_credentials: C
    ) -> None:
        """resolve_identity returns an Identity equal to the resolver's own result."""

    def test_invalid_credentials_return_resolution_failure(
        self, resolver: IdentityResolver[C], invalid_credentials: C
    ) -> None:
        """Invalid credentials return a ResolutionFailure; the resolver does not raise."""

    def test_invalid_credentials_raise_permanent_resolver_failure_error(
        self, resolver: IdentityResolver[C], invalid_credentials: C
    ) -> None:
        """resolve_identity turns the failure into a permanent ResolverFailureError."""

    def test_valid_resolution_is_consistent(
        self, resolver: IdentityResolver[C], valid_credentials: C
    ) -> None:
        """Repeated resolution of the same credentials gives equal identities."""

    def test_invalid_resolution_is_consistent(
        self, resolver: IdentityResolver[C], invalid_credentials: C
    ) -> None:
        """Repeated resolution of invalid credentials fails every time."""

    def test_roles_are_known_to_scope_configuration(
        self,
        resolver: IdentityResolver[C],
        valid_credentials: C,
        known_roles: frozenset[str],
        policy: ScopePolicy,
    ) -> None:
        """Every granted role, and every role the policy permits, is in known_roles."""

    def test_granted_scopes_build_valid_paths(
        self, resolver: IdentityResolver[C], valid_credentials: C
    ) -> None:
        """Every granted scope and entity ID builds a valid, round-tripping path and prefix."""

    def test_system_area_is_read_only_in_every_scope(
        self, resolver: IdentityResolver[C], valid_credentials: C, policy: ScopePolicy
    ) -> None:
        """Writes to system/ are rejected in every scope, granted or not, whatever the role."""

    def test_own_entity_writes_follow_policy(
        self, resolver: IdentityResolver[C], valid_credentials: C, policy: ScopePolicy
    ) -> None:
        """A write under the caller's own entity succeeds or needs a role, as the policy says."""

    def test_foreign_entity_writes_are_not_granted(
        self, resolver: IdentityResolver[C], valid_credentials: C, policy: ScopePolicy
    ) -> None:
        """A write under another entity ID in a granted scope is not granted."""

    def test_ungranted_scope_writes_are_not_granted(
        self, resolver: IdentityResolver[C], valid_credentials: C, policy: ScopePolicy
    ) -> None:
        """A write in a scope the identity has no grant for is not granted."""
```

These twelve methods are the whole suite. The class defines no fixtures,
attributes, or `__init__`. `name` below is `_name(type(resolver))`.

### Private helpers

```python
def _resolve_valid[C](
    resolver: IdentityResolver[C], credentials: C, call: int | None = None
) -> Identity:
    """Resolve credentials that must succeed, failing the test on any violation."""


def _resolve_invalid[C](
    resolver: IdentityResolver[C], credentials: C, call: int | None = None
) -> ResolutionFailure:
    """Resolve credentials that must be rejected, failing the test on any violation."""


def _check_fixture(name: str, fixture: str, value: object) -> frozenset[str]:
    """Return a plain frozenset copy of value if it is a frozenset of exact str, else fail."""


def _canonical(name: str, result: Identity, call: int | None = None) -> Identity:
    """Rebuild result as a base Identity of base ScopeGrants, failing with "invalid Identity"."""


def _name(t: type) -> str:
    """t.__name__, or "<unnamed>" if reading it raises."""


def _expect_restriction(
    name: str,
    path: str,
    identity: Identity,
    policy: ScopePolicy,
    reason: RestrictionReason,
    scope: str,
) -> RestrictedScopeError:
    """Run check_write, failing unless it raises RestrictedScopeError with this reason and scope."""


def _ungranted_scope(identity: Identity) -> str:
    """_UNGRANTED_SCOPE, with "-x" appended until it names no granted scope."""
```

Both resolve helpers bind `result = cast(object,
resolver.resolve(credentials))` inside `try: ... except Exception as exc:`,
as `resolve_identity` does. A plain `result: object = ...` annotation is
narrowed to the call's return type and fails `reportUnnecessaryIsInstance`.
They classify the result with `issubclass(type(result), Identity)` and
`issubclass(type(result), ResolutionFailure)`, as `resolve_identity` does.
`_resolve_valid` returns `_canonical(name, result, call)`, never the
resolver's own object. `BaseException`s that are not `Exception`s
propagate. When `call` is set, every failure message from the helper ends
with ` on call {call}`.

`_canonical` evaluates `Identity({s: ScopeGrant(g.entity_id, g.role) for
s, g in result.grants.items()})` inside `try: ... except Exception`, failing
with `invalid Identity` and the exception type. The rebuilt value uses only
base classes and re-runs the library's validation.

`_check_fixture` takes `value: object` so its type checks are not reported
as unnecessary. It requires `issubclass(type(value), frozenset)` and
`type(item) is str` for every member, and returns `frozenset(str(i) for i
in value)`, a plain `frozenset`. It fails with `{name}: fixture {fixture}
must be a frozenset of str, got {type}`, where `type` is the value's type
or, for a bad member, `frozenset containing {member type}`.

`_expect_restriction` runs `check_write` in `try`. `RestrictedScopeError`
with the wrong `reason` or `scope` → fail (`wrong reason`). Any other
`Exception` → fail (`wrong reason`) naming its type. No exception → fail
(`not rejected`). A `RestrictedScopeError` with the right reason and scope
is returned.

### Test algorithms

| Method | Checks, in order |
| ------ | ---------------- |
| `valid_credentials_resolve_to_identity` | `expected = _check_fixture(name, "expected_scopes", expected_scopes)`. `identity = _resolve_valid(...)`. Empty grants → fail. `set(identity.grants) != expected` → fail |
| `valid_credentials_resolve_through_library_entry_point` | `expected = _resolve_valid(...)`. Then `try: actual = resolve_identity(resolver, creds)`. `except ResolverFailureError as exc` → fail (`resolve_identity raised`). `_canonical(name, actual) != expected` → fail (`resolve_identity returned`) |
| `invalid_credentials_return_resolution_failure` | `_resolve_invalid(...)` |
| `invalid_..._permanent_resolver_failure_error` | `_resolve_invalid(...)` first. Then `try: resolve_identity(...)`. `except ResolverFailureError as exc`: `exc.category is not ErrorCategory.PERMANENT` → fail (`not permanent`). No exception → fail (`did not raise ResolverFailureError`). Never uses `pytest.raises`, whose own message names no resolver |
| `valid_resolution_is_consistent` | `first = _resolve_valid(..., call=1)`. For `n` in 2..3, `_resolve_valid(..., call=n) != first` → fail (`different results`) naming `n` |
| `invalid_resolution_is_consistent` | `_resolve_invalid(..., call=n)` for `n` in 1..3 |
| `roles_are_known_to_scope_configuration` | `known = _check_fixture(name, "known_roles", known_roles)`. For each granted scope, sorted: `identity.role(s) not in known` → fail (`not in known_roles`). Then for each `(s, roles)` in `sorted(policy.write_roles.items())`, each role in `sorted(roles)`: role not in `known` → fail (`policy role`) |
| `granted_scopes_build_valid_paths` | for each `(s, e)`: `p = build_path(s, e, _PROBE_AREA, _PROBE_NAME)`. `not is_valid_path(p)` → fail. `parse_path(p) != PathParts(s, e, _PROBE_AREA, _PROBE_NAME)` → fail (`does not round-trip`). `q = build_prefix(s, e)`. `not is_valid_prefix(q)` → fail (`invalid prefix`). `not p.startswith(q)` → fail (`not under prefix`) |
| `system_area_is_read_only_in_every_scope` | for each `(s, e)`, for `eid in (e, e + "-other")`: `_expect_restriction(build_path(s, eid, SYSTEM_AREA, _PROBE_NAME), ..., SYSTEM_READ_ONLY, s)`. Then `u = _ungranted_scope(identity)`: `_expect_restriction(build_path(u, _UNGRANTED_ENTITY, SYSTEM_AREA, _PROBE_NAME), ..., SYSTEM_READ_ONLY, u)` |
| `own_entity_writes_follow_policy` | for each `(s, e)`: `permitted = policy.permitted_roles(s)`. If `permitted is None or role in permitted`, `check_write` must return `None`. Any `Exception` → fail (`unexpected outcome`) naming its type, plus its reason for a `RestrictedScopeError`. Else `_expect_restriction(..., ROLE_REQUIRED, s)` and `err.required_roles != permitted` → fail (`wrong required_roles`) |
| `foreign_entity_writes_are_not_granted` | for each `(s, e)`: `_expect_restriction(build_path(s, e + "-other", _PROBE_AREA, _PROBE_NAME), ..., NOT_GRANTED, s)` |
| `ungranted_scope_writes_are_not_granted` | for `s` in `{_ungranted_scope(identity)} ∪ (set(policy.write_roles) - set(identity.grants))`, sorted: `_expect_restriction(build_path(s, _UNGRANTED_ENTITY, _PROBE_AREA, _PROBE_NAME), ..., NOT_GRANTED, s)` |

`e + "-other"` is always a valid segment different from `e`. Iteration
over grants is `sorted(identity.grants.items())`, so failures are
deterministic.

### Failure messages

Every message starts with `f"{name}: "` except where noted, and contains
the key phrase. Tests match only the key phrase.

| Condition | Key phrase | Message |
| --------- | ---------- | ------- |
| resolve raised, valid or invalid | `must not raise` | `{name}: resolve raised {type(exc).__name__}; a resolver must not raise, return ResolutionFailure instead` |
| `ResolutionFailure` for valid | `rejected valid credentials` | `{name}: rejected valid credentials: {detail}` |
| wrong return type | `expected Identity or ResolutionFailure` | `{name}: resolve returned {type}, expected Identity or ResolutionFailure` |
| no grants | `granted no scopes` | `{name}: granted no scopes for valid credentials` |
| scope mismatch | `granted scopes` | `{name}: granted scopes {sorted(actual)}, expected {sorted(expected)}` |
| `Identity` cannot be rebuilt from its grants | `invalid Identity` | `{name}: returned an invalid Identity: rebuilding it raised {type}` |
| entry point mismatch | `resolve_identity returned` | `{name}: resolve_identity returned a different Identity than resolve` |
| entry point raised for valid | `resolve_identity raised` | `{name}: resolve_identity raised {type(exc).__name__} for valid credentials` |
| `Identity` for invalid | `accepted invalid credentials` | `{name}: accepted invalid credentials` |
| not permanent | `not permanent` | `{name}: resolution failure category is {c}, not permanent` |
| entry point did not raise for invalid | `did not raise ResolverFailureError` | `{name}: resolve_identity did not raise ResolverFailureError for invalid credentials` |
| inconsistent | `different results` | `{name}: different results for identical credentials on call {n}` |
| any resolve-helper violation with `call` set | per row above, plus `on call {n}` | as above, suffixed ` on call {n}` |
| fixture wrong type | `fixture {fixture}` | `{name}: fixture {fixture} must be a frozenset of str, got {type}` |
| unknown role | `not in known_roles` | `{name}: role {role!r} in scope {s!r} is not in known_roles` |
| policy role unknown | `policy role` | `{name}: policy role {role!r} for scope {s!r} is not in known_roles` |
| path invalid | `invalid path` | `{name}: scope {s!r} built invalid path {p!r}` |
| path parse mismatch | `does not round-trip` | `{name}: path {p!r} does not round-trip, parsed as {parts}` |
| prefix invalid | `invalid prefix` | `{name}: scope {s!r} built invalid prefix {q!r}` |
| path outside prefix | `not under prefix` | `{name}: path {p!r} is not under prefix {q!r}` |
| check did not raise | `not rejected` | `{name}: write to {path} was not rejected ({reason})` |
| other reason, scope, or exception type | `wrong reason` | `{name}: write to {path} raised {actual}, wrong reason, expected {reason}`, where `actual` is the reason or the exception type name |
| own-entity outcome where `None` expected | `unexpected outcome` | `{name}: write to {path} as {role!r}: unexpected outcome {actual}, expected None`, where `actual` names the exception type, plus its reason for a `RestrictedScopeError` |
| required_roles mismatch | `wrong required_roles` | `{name}: wrong required_roles for write to {path}: got {actual}, expected {sorted(permitted)}` |

Clause coverage:

| Clause | Test methods |
| ------ | ------------ |
| 10.1 map and role per scope for valid credentials | `valid_credentials_resolve_to_identity`, `..._through_library_entry_point` |
| 10.1 never raises, returns failure | `invalid_credentials_return_resolution_failure` |
| 10.1 library converts to permanent error | `invalid_..._permanent_resolver_failure_error` |
| 10.1 consistent within a session | `valid_resolution_is_consistent`, `invalid_resolution_is_consistent` |
| 10.1 roles the configuration references | `roles_are_known_to_scope_configuration`, `own_entity_writes_follow_policy` |
| AIE-1039 path construction | `granted_scopes_build_valid_paths` |
| AIE-1039 system/ read-only | `system_area_is_read_only_in_every_scope` |
| AIE-1039 write restriction | `own_entity_writes_follow_policy`, `foreign_entity_writes_are_not_granted`, `ungranted_scope_writes_are_not_granted` |

## Test layout

All three files carry `pytestmark = pytest.mark.unit` and a module
docstring citing AIE-1039. Each test docstring cites AIE-1039 and its
scenario ID, e.g. `(AIE-1039, US2.2)`.

- `tests/test_resolver_conformance_reference.py` (US8):
  - `TestSandboxResolverPermittedRole(ResolverConformance[object])`: role
    `admin` in `org`. `invalid_credentials` calls
    `pytest.skip("SandboxResolver accepts every credential")`.
  - `TestSandboxResolverLackingRole(ResolverConformance[object])`: role
    `member` in `org`, otherwise the same.
  - `TestTokenResolver(ResolverConformance[str])`: a local `TokenResolver`
    mapping `"valid-token"` to the reference identity and any other string
    to `ResolutionFailure("unknown token")`. `invalid_credentials` is
    `"bogus-token"`.
  - Fixtures are methods on each class returning the spec's reference
    values, including the policy's restricted but ungranted `team` scope.
    Shared values are module constants.
- `tests/test_resolver_conformance_self.py` (US1–US7 failure cases): builds
  `suite = ResolverConformance[str]()` and calls each method with keyword
  arguments inside `pytest.raises(pytest.fail.Exception, match=<key
  phrase>)`. Broken doubles, each a small local class typed
  `IdentityResolver[str]`: raises on valid, raises on invalid, returns
  `ResolutionFailure` for valid, returns `None` (with `# pyright:
  ignore[reportReturnType]`), accepts invalid, empty identity, wrong
  scopes, inconsistent (a counter selecting a different identity on call
  2), raises-on-call-2 for valid credentials (US3.5),
  inconsistent-on-invalid (fails on call 1, returns an identity on call 2),
  and wrong-case role (`"Admin"`). US1.9 and US4.3 pass a `list` and a
  `str` for the frozenset fixtures, with a narrow `# pyright:
  ignore[reportArgumentType]`. US4.4 passes a policy permitting `"Admin"`.
  - Two conforming token resolvers are used: the reference identity (role
    `admin` in `org`) and the member identity, so the `ROLE_REQUIRED`
    branch is exercised.
  - US1.7–8, US2.7–8, US5.2–5, US6.2, and US7.5–7 use
    `monkeypatch.setattr(resolver_conformance, name, replacement)` on
    `resolve_identity`, `build_path`, `build_prefix`, `parse_path`, or
    `check_write`, with a conforming resolver. Each replacement is a local
    `def` whose full signature matches the real function, not a `lambda`,
    which pyright strict reports as `reportUnknownLambdaType`. The US7.5
    matrix is a parametrized table of (replacement, identity, method,
    phrase), omitting the "passes" cells. The system, foreign, and
    ungranted columns use the admin identity. Their outcome does not
    depend on the role, so one identity suffices. Only the own-entity
    column runs both identities. Patched `check_write` doubles
    raise with `scope=parse_path(path).scope`.
  - US2.7 raises a local `ResolverFailureError` subclass overriding
    `category = ErrorCategory.TRANSIENT`.
  - US1.2 and US2.2 use a double raising `RuntimeError` and assert
    `isinstance(exc_info.value.__context__, RuntimeError)`, so a later
    change to `from None` is caught.
  - Each self-test also confirms the same method passes for the conforming
    token resolver, so a failure is attributable to the defect.
- `tests/test_testing_package.py` (US9):
  - Imports `wenchang.testing.ResolverConformance` and checks the name
    prefix. Reads `pyproject.toml` with `tomllib` for the extra.
  - Parses every `.py` under `src/wenchang/` outside `testing/` with `ast`.
    It asserts no `pytest` / `_pytest` import and no import of
    `wenchang.testing` in any form: `Import` of `wenchang.testing`,
    `ImportFrom` with `module == "wenchang"` naming `testing`, `module`
    starting with `wenchang.testing`, and relative `ImportFrom`
    (`level >= 1`) whose `module` is `testing` or starts with `testing.`,
    or that names `testing` with `module is None`.
  - Runs a `subprocess.run([sys.executable, "-c", script], check=False)`
    whose script sets `sys.modules["pytest"] = None`, walks
    `pkgutil.walk_packages(wenchang.__path__, "wenchang.")`, skips names
    starting with `wenchang.testing`, and imports the rest. Asserts return
    code 0 (US9.6).
  - Scans every file under `src/wenchang/testing/` for `AIE-\d+` (US9.5),
    and parses `resolver_conformance.py` with `ast` for any `pytestmark`
    assignment or `pytest.mark` attribute (US9.7).
  - Asserts the sorted `test_*` names of `ResolverConformance` equal the
    twelve method names above.

## Project Structure

```text
specs/AIE-1039-resolver-conformance/   spec.md plan.md tasks.md review-spec.md
pyproject.toml                         # testing extra
uv.lock                                # regenerated by uv lock
src/wenchang/testing/__init__.py       # new
src/wenchang/testing/resolver_conformance.py  # new
tests/test_resolver_conformance_reference.py  # new
tests/test_resolver_conformance_self.py       # new
tests/test_testing_package.py                 # new
ARCHITECTURE.md                        # testing entry, adopter surface
docs/adr/0018-resolver-conformance-suite.md
```

## Complexity Tracking

None.
