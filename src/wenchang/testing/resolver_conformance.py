"""Conformance suite for IdentityResolver implementations.

Requires the `testing` extra: `pip install "wenchang[testing]"`.

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

The suite applies no pytest marks; mark your own subclass if needed.
Passing every test defines a conforming resolver.
"""

from typing import cast

import pytest

from wenchang.errors import (
    ErrorCategory,
    ResolverFailureError,
    RestrictedScopeError,
    RestrictionReason,
)
from wenchang.identity import (
    Identity,
    IdentityResolver,
    ResolutionFailure,
    ScopeGrant,
    resolve_identity,
)
from wenchang.paths import (
    PathParts,
    build_path,
    build_prefix,
    is_valid_path,
    is_valid_prefix,
    parse_path,
)
from wenchang.scope import SYSTEM_AREA, ScopePolicy, check_write

_PROBE_AREA = "notes"
_PROBE_NAME = "conformance-probe"
_CONSISTENCY_CALLS = 3
_UNGRANTED_SCOPE = "conformance-ungranted"
_UNGRANTED_ENTITY = "conformance-entity"


def _name(t: type) -> str:
    """t.__name__, or "<unnamed>" if reading it raises."""
    # A metaclass may make __name__ raise or return a str subclass.
    try:
        return str.__str__(t.__name__)
    except Exception:
        return "<unnamed>"


def _suffix(call: int | None) -> str:
    return "" if call is None else f" on call {call}"


def _canonical(name: str, result: Identity, call: int | None = None) -> Identity:
    """Rebuild result as a base Identity of base ScopeGrants, failing with "invalid Identity".

    Reading only stored attributes means subclass overrides of __eq__, role(),
    or entity_id() cannot change what the suite checks.
    """
    try:
        return Identity({s: ScopeGrant(g.entity_id, g.role) for s, g in result.grants.items()})
    except Exception as exc:
        # Raised inside the handler so pytest shows the original exception as context.
        pytest.fail(
            f"{name}: returned an invalid Identity: rebuilding it raised "
            f"{_name(type(exc))}{_suffix(call)}"
        )


def _resolve_valid[C](
    resolver: IdentityResolver[C], credentials: C, call: int | None = None
) -> Identity:
    """Resolve credentials that must succeed, failing the test on any violation."""
    name = _name(type(resolver))
    suffix = _suffix(call)
    try:
        # Widened because resolvers may be untyped and return anything.
        result = cast(object, resolver.resolve(credentials))
    except Exception as exc:
        # Raised inside the handler so pytest shows the resolver's exception as context.
        pytest.fail(
            f"{name}: resolve raised {_name(type(exc))}; a resolver must not raise, "
            f"return ResolutionFailure instead{suffix}"
        )
    # type() rather than isinstance, which consults a resolver-controlled __class__.
    result_type = type(result)
    if issubclass(result_type, Identity):
        return _canonical(name, cast(Identity, result), call)
    if issubclass(result_type, ResolutionFailure):
        detail = cast(ResolutionFailure, result).detail
        pytest.fail(f"{name}: rejected valid credentials: {detail}{suffix}")
    pytest.fail(
        f"{name}: resolve returned {_name(result_type)}, "
        f"expected Identity or ResolutionFailure{suffix}"
    )


def _resolve_invalid[C](
    resolver: IdentityResolver[C], credentials: C, call: int | None = None
) -> ResolutionFailure:
    """Resolve credentials that must be rejected, failing the test on any violation."""
    name = _name(type(resolver))
    suffix = _suffix(call)
    try:
        # Widened because resolvers may be untyped and return anything.
        result = cast(object, resolver.resolve(credentials))
    except Exception as exc:
        # Raised inside the handler so pytest shows the resolver's exception as context.
        pytest.fail(
            f"{name}: resolve raised {_name(type(exc))}; a resolver must not raise, "
            f"return ResolutionFailure instead{suffix}"
        )
    # type() rather than isinstance, which consults a resolver-controlled __class__.
    result_type = type(result)
    if issubclass(result_type, ResolutionFailure):
        return cast(ResolutionFailure, result)
    if issubclass(result_type, Identity):
        pytest.fail(f"{name}: accepted invalid credentials{suffix}")
    pytest.fail(
        f"{name}: resolve returned {_name(result_type)}, "
        f"expected Identity or ResolutionFailure{suffix}"
    )


def _check_fixture(name: str, fixture: str, value: object) -> frozenset[str]:
    """Return a plain frozenset copy of value if it is a frozenset of exact str, else fail."""
    type_name = _name(type(value))
    if issubclass(type(value), frozenset):
        members = cast(frozenset[object], value)
        bad = [item for item in members if type(item) is not str]
        if not bad:
            return frozenset(str.__str__(cast(str, item)) for item in members)
        type_name = f"frozenset containing {_name(type(bad[0]))}"
    pytest.fail(f"{name}: fixture {fixture} must be a frozenset of str, got {type_name}")


def _expect_restriction(
    name: str,
    path: str,
    identity: Identity,
    policy: ScopePolicy,
    reason: RestrictionReason,
    scope: str,
) -> RestrictedScopeError:
    """Run check_write, failing unless it raises RestrictedScopeError with this reason and scope."""
    try:
        check_write(path, identity, policy)
    except RestrictedScopeError as exc:
        if exc.reason is reason and exc.scope == scope:
            return exc
        actual = str(exc.reason) if exc.scope == scope else f"{exc.reason} in scope {exc.scope!r}"
        pytest.fail(f"{name}: write to {path} raised {actual}, wrong reason, expected {reason}")
    except Exception as exc:
        pytest.fail(
            f"{name}: write to {path} raised {_name(type(exc))}, wrong reason, expected {reason}"
        )
    pytest.fail(f"{name}: write to {path} was not rejected ({reason})")


def _ungranted_scope(identity: Identity) -> str:
    """_UNGRANTED_SCOPE, with "-x" appended until it names no granted scope."""
    scope = _UNGRANTED_SCOPE
    while scope in identity.grants:
        scope += "-x"
    return scope


class ResolverConformance[C]:
    """Tests every IdentityResolver must pass. Subclass with a Test* name and supply fixtures."""

    def test_valid_credentials_resolve_to_identity(
        self, resolver: IdentityResolver[C], valid_credentials: C, expected_scopes: frozenset[str]
    ) -> None:
        """Valid credentials resolve to an Identity granting exactly expected_scopes."""
        name = _name(type(resolver))
        expected = _check_fixture(name, "expected_scopes", expected_scopes)
        identity = _resolve_valid(resolver, valid_credentials)
        if not identity.grants:
            pytest.fail(f"{name}: granted no scopes for valid credentials")
        actual = frozenset(identity.grants)
        if actual != expected:
            pytest.fail(f"{name}: granted scopes {sorted(actual)}, expected {sorted(expected)}")

    def test_valid_credentials_resolve_through_library_entry_point(
        self, resolver: IdentityResolver[C], valid_credentials: C
    ) -> None:
        """resolve_identity returns an Identity equal to the resolver's own result."""
        name = _name(type(resolver))
        expected = _resolve_valid(resolver, valid_credentials)
        try:
            actual = resolve_identity(resolver, valid_credentials)
        except ResolverFailureError as exc:
            pytest.fail(f"{name}: resolve_identity raised {_name(type(exc))} for valid credentials")
        if _canonical(name, actual) != expected:
            pytest.fail(f"{name}: resolve_identity returned a different Identity than resolve")

    def test_invalid_credentials_return_resolution_failure(
        self, resolver: IdentityResolver[C], invalid_credentials: C
    ) -> None:
        """Invalid credentials return a ResolutionFailure; the resolver does not raise."""
        _resolve_invalid(resolver, invalid_credentials)

    def test_invalid_credentials_raise_permanent_resolver_failure_error(
        self, resolver: IdentityResolver[C], invalid_credentials: C
    ) -> None:
        """resolve_identity turns the failure into a permanent ResolverFailureError."""
        name = _name(type(resolver))
        _resolve_invalid(resolver, invalid_credentials)
        try:
            resolve_identity(resolver, invalid_credentials)
        except ResolverFailureError as exc:
            if exc.category is not ErrorCategory.PERMANENT:
                pytest.fail(f"{name}: resolution failure category is {exc.category}, not permanent")
            return
        pytest.fail(
            f"{name}: resolve_identity did not raise ResolverFailureError for invalid credentials"
        )

    def test_valid_resolution_is_consistent(
        self, resolver: IdentityResolver[C], valid_credentials: C
    ) -> None:
        """Repeated resolution of the same credentials gives equal identities."""
        name = _name(type(resolver))
        first = _resolve_valid(resolver, valid_credentials, call=1)
        for call in range(2, _CONSISTENCY_CALLS + 1):
            if _resolve_valid(resolver, valid_credentials, call=call) != first:
                pytest.fail(f"{name}: different results for identical credentials on call {call}")

    def test_invalid_resolution_is_consistent(
        self, resolver: IdentityResolver[C], invalid_credentials: C
    ) -> None:
        """Repeated resolution of invalid credentials fails every time."""
        for call in range(1, _CONSISTENCY_CALLS + 1):
            _resolve_invalid(resolver, invalid_credentials, call=call)

    def test_roles_are_known_to_scope_configuration(
        self,
        resolver: IdentityResolver[C],
        valid_credentials: C,
        known_roles: frozenset[str],
        policy: ScopePolicy,
    ) -> None:
        """Every granted role, and every role the policy permits, is in known_roles."""
        name = _name(type(resolver))
        known = _check_fixture(name, "known_roles", known_roles)
        identity = _resolve_valid(resolver, valid_credentials)
        for scope in sorted(identity.grants):
            role = identity.role(scope)
            if role not in known:
                pytest.fail(f"{name}: role {role!r} in scope {scope!r} is not in known_roles")
        for scope, roles in sorted(policy.write_roles.items()):
            for role in sorted(roles):
                if role not in known:
                    pytest.fail(
                        f"{name}: policy role {role!r} for scope {scope!r} is not in known_roles"
                    )

    def test_granted_scopes_build_valid_paths(
        self, resolver: IdentityResolver[C], valid_credentials: C
    ) -> None:
        """Every granted scope and entity ID builds a valid, round-tripping path and prefix."""
        name = _name(type(resolver))
        identity = _resolve_valid(resolver, valid_credentials)
        for scope in sorted(identity.grants):
            entity_id = identity.entity_id(scope)
            path = build_path(scope, entity_id, _PROBE_AREA, _PROBE_NAME)
            if not is_valid_path(path):
                pytest.fail(f"{name}: scope {scope!r} built invalid path {path!r}")
            parts = parse_path(path)
            if parts != PathParts(scope, entity_id, _PROBE_AREA, _PROBE_NAME):
                pytest.fail(f"{name}: path {path!r} does not round-trip, parsed as {parts}")
            prefix = build_prefix(scope, entity_id)
            if not is_valid_prefix(prefix):
                pytest.fail(f"{name}: scope {scope!r} built invalid prefix {prefix!r}")
            if not path.startswith(prefix):
                pytest.fail(f"{name}: path {path!r} is not under prefix {prefix!r}")

    def test_system_area_is_read_only_in_every_scope(
        self, resolver: IdentityResolver[C], valid_credentials: C, policy: ScopePolicy
    ) -> None:
        """Writes to system/ are rejected in every scope, granted or not, whatever the role."""
        name = _name(type(resolver))
        identity = _resolve_valid(resolver, valid_credentials)
        read_only = RestrictionReason.SYSTEM_READ_ONLY
        for scope in sorted(identity.grants):
            entity_id = identity.entity_id(scope)
            for target in (entity_id, entity_id + "-other"):
                path = build_path(scope, target, SYSTEM_AREA, _PROBE_NAME)
                _expect_restriction(name, path, identity, policy, read_only, scope)
        ungranted = _ungranted_scope(identity)
        path = build_path(ungranted, _UNGRANTED_ENTITY, SYSTEM_AREA, _PROBE_NAME)
        _expect_restriction(name, path, identity, policy, read_only, ungranted)

    def test_own_entity_writes_follow_policy(
        self, resolver: IdentityResolver[C], valid_credentials: C, policy: ScopePolicy
    ) -> None:
        """A write under the caller's own entity succeeds or needs a role, as the policy says."""
        name = _name(type(resolver))
        identity = _resolve_valid(resolver, valid_credentials)
        for scope in sorted(identity.grants):
            grant = identity.grants[scope]
            path = build_path(scope, grant.entity_id, _PROBE_AREA, _PROBE_NAME)
            permitted = policy.permitted_roles(scope)
            if permitted is None or grant.role in permitted:
                try:
                    check_write(path, identity, policy)
                except Exception as exc:
                    outcome = _name(type(exc))
                    if isinstance(exc, RestrictedScopeError):
                        outcome += f" ({exc.reason})"
                    pytest.fail(
                        f"{name}: write to {path} as {grant.role!r}: "
                        f"unexpected outcome {outcome}, expected None"
                    )
                continue
            err = _expect_restriction(
                name, path, identity, policy, RestrictionReason.ROLE_REQUIRED, scope
            )
            if err.required_roles != permitted:
                actual = sorted(err.required_roles or ())
                pytest.fail(
                    f"{name}: wrong required_roles for write to {path}: "
                    f"got {actual}, expected {sorted(permitted)}"
                )

    def test_foreign_entity_writes_are_not_granted(
        self, resolver: IdentityResolver[C], valid_credentials: C, policy: ScopePolicy
    ) -> None:
        """A write under another entity ID in a granted scope is not granted."""
        name = _name(type(resolver))
        identity = _resolve_valid(resolver, valid_credentials)
        for scope in sorted(identity.grants):
            path = build_path(scope, identity.entity_id(scope) + "-other", _PROBE_AREA, _PROBE_NAME)
            _expect_restriction(name, path, identity, policy, RestrictionReason.NOT_GRANTED, scope)

    def test_ungranted_scope_writes_are_not_granted(
        self, resolver: IdentityResolver[C], valid_credentials: C, policy: ScopePolicy
    ) -> None:
        """A write in a scope the identity has no grant for is not granted."""
        name = _name(type(resolver))
        identity = _resolve_valid(resolver, valid_credentials)
        scopes = {_ungranted_scope(identity)} | (set(policy.write_roles) - set(identity.grants))
        for scope in sorted(scopes):
            path = build_path(scope, _UNGRANTED_ENTITY, _PROBE_AREA, _PROBE_NAME)
            _expect_restriction(name, path, identity, policy, RestrictionReason.NOT_GRANTED, scope)
