"""Self-tests proving the resolver conformance suite fails for broken resolvers.

Covers AIE-1039: US1.2-9, US2.2-4, US2.7-8, US3.2, US3.4-5, US4.2-4, US5.2-5, US6.2,
US7.5-7, FR-003, FR-007, and the failing half of SC-001. Each test calls a suite method
directly and expects pytest.fail with the key phrase and the resolver class name.
"""

import re
from collections.abc import Callable, Iterator

import pytest

from wenchang.errors import (
    ErrorCategory,
    NotFoundError,
    NotFoundReason,
    ResolverFailureError,
    RestrictedScopeError,
    RestrictionReason,
)
from wenchang.identity import Identity, IdentityResolver, ResolutionFailure, ScopeGrant
from wenchang.paths import PathParts, build_prefix, parse_path
from wenchang.scope import ScopePolicy, check_write
from wenchang.testing import ResolverConformance, resolver_conformance

pytestmark = pytest.mark.unit

ADMIN_IDENTITY = Identity(
    grants={"user": ScopeGrant("u-1", "owner"), "org": ScopeGrant("o-9", "admin")}
)
MEMBER_IDENTITY = Identity(
    grants={"user": ScopeGrant("u-1", "owner"), "org": ScopeGrant("o-9", "member")}
)
POLICY = ScopePolicy({"org": frozenset({"admin", "owner"}), "team": frozenset({"admin"})})
EXPECTED_SCOPES = frozenset({"user", "org"})
KNOWN_ROLES = frozenset({"owner", "admin", "member"})

VALID = "valid-token"
INVALID = "bogus-token"

SUITE = ResolverConformance[str]()


class TokenResolver:
    """Conforming: the known token resolves to `identity`, anything else fails."""

    def __init__(self, identity: Identity = ADMIN_IDENTITY) -> None:
        self.identity = identity

    def resolve(self, credentials: str) -> Identity | ResolutionFailure:
        if credentials == VALID:
            return self.identity
        return ResolutionFailure("unknown token")


class RaisesOnValid:
    """Raises RuntimeError for valid credentials."""

    def resolve(self, credentials: str) -> Identity | ResolutionFailure:
        raise RuntimeError("backend exploded")


class RaisesOnInvalid:
    """Resolves the known token and raises `exc_type` for anything else."""

    def __init__(self, exc_type: type[Exception]) -> None:
        self.exc_type = exc_type

    def resolve(self, credentials: str) -> Identity | ResolutionFailure:
        if credentials == VALID:
            return ADMIN_IDENTITY
        raise self.exc_type("bad token")


class RejectsValid:
    """Returns ResolutionFailure for every credential."""

    def resolve(self, credentials: str) -> Identity | ResolutionFailure:
        return ResolutionFailure("token expired at noon")


class ReturnsNone:
    """Returns None for every credential."""

    def resolve(self, credentials: str) -> Identity | ResolutionFailure:
        return None  # pyright: ignore[reportReturnType]


class AcceptsEverything:
    """Returns the reference identity for every credential."""

    def resolve(self, credentials: str) -> Identity | ResolutionFailure:
        return ADMIN_IDENTITY


class EmptyIdentity:
    """Returns an Identity with no grants."""

    def resolve(self, credentials: str) -> Identity | ResolutionFailure:
        return Identity(grants={})


class DropsScope:
    """Returns an Identity missing the org scope."""

    def resolve(self, credentials: str) -> Identity | ResolutionFailure:
        return Identity(grants={"user": ScopeGrant("u-1", "owner")})


class InconsistentOnValid:
    """Returns ADMIN_IDENTITY, except `other` on call number `bad_call`."""

    def __init__(self, bad_call: int, other: Identity) -> None:
        self.bad_call = bad_call
        self.other = other
        self.calls = 0

    def resolve(self, credentials: str) -> Identity | ResolutionFailure:
        self.calls += 1
        return self.other if self.calls == self.bad_call else ADMIN_IDENTITY


class RaisesOnSecondValid:
    """Succeeds on call 1, raises RuntimeError on call 2."""

    def __init__(self) -> None:
        self.calls = 0

    def resolve(self, credentials: str) -> Identity | ResolutionFailure:
        self.calls += 1
        if self.calls == 2:
            raise RuntimeError("flaky backend")
        return ADMIN_IDENTITY


class InconsistentOnInvalid:
    """Rejects on call 1, accepts on call 2."""

    def __init__(self) -> None:
        self.calls = 0

    def resolve(self, credentials: str) -> Identity | ResolutionFailure:
        self.calls += 1
        if self.calls == 1:
            return ResolutionFailure("unknown token")
        return ADMIN_IDENTITY


class WrongCaseRole:
    """Returns role "Admin" in org where known_roles holds "admin"."""

    def resolve(self, credentials: str) -> Identity | ResolutionFailure:
        return Identity(
            grants={"user": ScopeGrant("u-1", "owner"), "org": ScopeGrant("o-9", "Admin")}
        )


class TransientResolverFailure(ResolverFailureError):
    """A ResolverFailureError whose category is wrongly TRANSIENT."""

    category = ErrorCategory.TRANSIENT


def _conforming(identity: Identity = ADMIN_IDENTITY) -> IdentityResolver[str]:
    return TokenResolver(identity)


def _fails(call: Callable[[], None], phrase: str, name: str) -> BaseException:
    """Run call, require pytest.fail naming `name` and containing `phrase`; return it."""
    with pytest.raises(pytest.fail.Exception, match=re.escape(phrase)) as exc_info:
        call()
    message = str(exc_info.value)
    assert message.startswith(f"{name}: "), message
    return exc_info.value


# --- US1: valid credentials -------------------------------------------------


def _resolve_to_identity(
    resolver: IdentityResolver[str], expected_scopes: frozenset[str] = EXPECTED_SCOPES
) -> Callable[[], None]:
    return lambda: SUITE.test_valid_credentials_resolve_to_identity(
        resolver=resolver, valid_credentials=VALID, expected_scopes=expected_scopes
    )


def _through_entry_point(resolver: IdentityResolver[str]) -> Callable[[], None]:
    return lambda: SUITE.test_valid_credentials_resolve_through_library_entry_point(
        resolver=resolver, valid_credentials=VALID
    )


def test_conforming_resolver_passes_valid_credential_methods() -> None:
    """The conforming double passes the US1 methods, so failures below are the defect's.

    (AIE-1039, US1.1)
    """
    _resolve_to_identity(_conforming())()
    _through_entry_point(_conforming())()


def test_raising_on_valid_fails_with_context() -> None:
    """A resolver raising for valid credentials fails, not errors (AIE-1039, US1.2)."""
    exc = _fails(_resolve_to_identity(RaisesOnValid()), "must not raise", "RaisesOnValid")

    assert "RuntimeError" in str(exc)
    assert isinstance(exc.__context__, RuntimeError)


def test_rejecting_valid_fails_with_detail() -> None:
    """A ResolutionFailure for valid credentials fails and shows its detail (AIE-1039, US1.3)."""
    exc = _fails(_resolve_to_identity(RejectsValid()), "rejected valid credentials", "RejectsValid")

    assert "token expired at noon" in str(exc)


def test_wrong_return_type_on_valid_fails_naming_type() -> None:
    """A None result for valid credentials fails naming NoneType (AIE-1039, US1.4)."""
    exc = _fails(
        _resolve_to_identity(ReturnsNone()),
        "expected Identity or ResolutionFailure",
        "ReturnsNone",
    )

    assert "NoneType" in str(exc)


@pytest.mark.parametrize("expected", [EXPECTED_SCOPES, frozenset[str]()])
def test_empty_identity_fails(expected: frozenset[str]) -> None:
    """An Identity with no grants fails, even for empty expected_scopes (AIE-1039, US1.5)."""
    _fails(_resolve_to_identity(EmptyIdentity(), expected), "granted no scopes", "EmptyIdentity")


def test_scope_mismatch_fails_listing_both_sets_sorted() -> None:
    """Granted scopes differing from expected_scopes fail with both sorted (AIE-1039, US1.6)."""
    exc = _fails(_resolve_to_identity(DropsScope()), "granted scopes", "DropsScope")

    assert "['user']" in str(exc)
    assert "['org', 'user']" in str(exc)


def test_entry_point_returning_different_identity_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """resolve_identity returning another Identity fails (AIE-1039, US1.7)."""
    _through_entry_point(_conforming())()

    def fake_resolve_identity[C](resolver: IdentityResolver[C], credentials: C) -> Identity:
        return MEMBER_IDENTITY

    monkeypatch.setattr(resolver_conformance, "resolve_identity", fake_resolve_identity)

    _fails(_through_entry_point(_conforming()), "resolve_identity returned", "TokenResolver")


def test_entry_point_raising_for_valid_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """resolve_identity raising ResolverFailureError for valid credentials fails, not errors.

    (AIE-1039, US1.8)
    """

    def fake_resolve_identity[C](resolver: IdentityResolver[C], credentials: C) -> Identity:
        raise ResolverFailureError("patched")

    monkeypatch.setattr(resolver_conformance, "resolve_identity", fake_resolve_identity)

    exc = _fails(_through_entry_point(_conforming()), "resolve_identity raised", "TokenResolver")

    assert isinstance(exc.__context__, ResolverFailureError)


def test_expected_scopes_not_a_frozenset_fails() -> None:
    """A list expected_scopes fixture fails naming the fixture (AIE-1039, US1.9, FR-007)."""
    bad = ["user", "org"]
    _fails(
        _resolve_to_identity(_conforming(), bad),  # pyright: ignore[reportArgumentType]
        "fixture expected_scopes",
        "TokenResolver",
    )


def test_expected_scopes_with_non_str_members_fails() -> None:
    """A frozenset expected_scopes holding non-str fails (AIE-1039, US1.9, FR-007)."""
    bad = frozenset({"user", 1})
    _fails(
        _resolve_to_identity(_conforming(), bad),  # pyright: ignore[reportArgumentType]
        "fixture expected_scopes",
        "TokenResolver",
    )


# --- US2: invalid credentials -----------------------------------------------


def _return_failure(resolver: IdentityResolver[str]) -> Callable[[], None]:
    return lambda: SUITE.test_invalid_credentials_return_resolution_failure(
        resolver=resolver, invalid_credentials=INVALID
    )


def _permanent_error(resolver: IdentityResolver[str]) -> Callable[[], None]:
    return lambda: SUITE.test_invalid_credentials_raise_permanent_resolver_failure_error(
        resolver=resolver, invalid_credentials=INVALID
    )


def test_conforming_resolver_passes_invalid_credential_methods() -> None:
    """The conforming double passes the US2 methods (AIE-1039, US2.1, US2.5)."""
    _return_failure(_conforming())()
    _permanent_error(_conforming())()


@pytest.mark.parametrize("exc_type", [RuntimeError, ValueError, KeyError, TypeError])
def test_raising_on_invalid_fails_naming_exception(exc_type: type[Exception]) -> None:
    """Any exception for invalid credentials fails naming its type (AIE-1039, US2.2)."""
    exc = _fails(_return_failure(RaisesOnInvalid(exc_type)), "must not raise", "RaisesOnInvalid")

    assert exc_type.__name__ in str(exc)
    assert isinstance(exc.__context__, exc_type)


def test_accepting_invalid_fails() -> None:
    """An Identity for invalid credentials fails (AIE-1039, US2.3)."""
    _fails(
        _return_failure(AcceptsEverything()), "accepted invalid credentials", "AcceptsEverything"
    )


def test_accepting_invalid_fails_permanent_error_method_first() -> None:
    """The permanent-error method checks acceptance first, not pytest's DID NOT RAISE.

    (AIE-1039, US2.5, US2.3)
    """
    _fails(
        _permanent_error(AcceptsEverything()), "accepted invalid credentials", "AcceptsEverything"
    )


def test_none_for_invalid_fails() -> None:
    """A None result for invalid credentials fails (AIE-1039, US2.4)."""
    _fails(_return_failure(ReturnsNone()), "expected Identity or ResolutionFailure", "ReturnsNone")


def test_transient_resolver_failure_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """resolve_identity raising a TRANSIENT ResolverFailureError fails (AIE-1039, US2.7)."""

    def fake_resolve_identity[C](resolver: IdentityResolver[C], credentials: C) -> Identity:
        raise TransientResolverFailure("patched")

    monkeypatch.setattr(resolver_conformance, "resolve_identity", fake_resolve_identity)

    _fails(_permanent_error(_conforming()), "not permanent", "TokenResolver")


def test_entry_point_not_raising_for_invalid_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """resolve_identity returning an Identity for invalid credentials fails.

    (AIE-1039, US2.8)
    """

    def fake_resolve_identity[C](resolver: IdentityResolver[C], credentials: C) -> Identity:
        return ADMIN_IDENTITY

    monkeypatch.setattr(resolver_conformance, "resolve_identity", fake_resolve_identity)

    _fails(_permanent_error(_conforming()), "did not raise ResolverFailureError", "TokenResolver")


# --- US3: consistency -------------------------------------------------------


def _valid_consistent(resolver: IdentityResolver[str]) -> Callable[[], None]:
    return lambda: SUITE.test_valid_resolution_is_consistent(
        resolver=resolver, valid_credentials=VALID
    )


def _invalid_consistent(resolver: IdentityResolver[str]) -> Callable[[], None]:
    return lambda: SUITE.test_invalid_resolution_is_consistent(
        resolver=resolver, invalid_credentials=INVALID
    )


def test_conforming_resolver_passes_consistency_methods() -> None:
    """The conforming double passes both consistency methods (AIE-1039, US3.1, US3.3)."""
    _valid_consistent(_conforming())()
    _invalid_consistent(_conforming())()


@pytest.mark.parametrize("bad_call", [2, 3])
@pytest.mark.parametrize(
    "other",
    [
        Identity(grants={"user": ScopeGrant("u-2", "owner"), "org": ScopeGrant("o-9", "admin")}),
        MEMBER_IDENTITY,
        Identity(grants={"user": ScopeGrant("u-1", "owner")}),
    ],
    ids=["entity-id", "role", "scope"],
)
def test_inconsistent_valid_resolution_fails_naming_call(bad_call: int, other: Identity) -> None:
    """A differing second or third result fails naming the call (AIE-1039, US3.2)."""
    exc = _fails(
        _valid_consistent(InconsistentOnValid(bad_call, other)),
        "different results",
        "InconsistentOnValid",
    )

    assert f"on call {bad_call}" in str(exc)


def test_invalid_accepted_on_second_call_fails() -> None:
    """Rejecting on call 1 then accepting on call 2 fails on call 2 (AIE-1039, US3.4)."""
    exc = _fails(
        _invalid_consistent(InconsistentOnInvalid()),
        "accepted invalid credentials",
        "InconsistentOnInvalid",
    )

    assert "on call 2" in str(exc)


def test_valid_raising_on_second_call_fails() -> None:
    """Succeeding on call 1 then raising on call 2 fails on call 2 (AIE-1039, US3.5)."""
    exc = _fails(_valid_consistent(RaisesOnSecondValid()), "must not raise", "RaisesOnSecondValid")

    assert "on call 2" in str(exc)
    assert isinstance(exc.__context__, RuntimeError)


# --- US4: roles -------------------------------------------------------------


def _roles_known(
    resolver: IdentityResolver[str],
    known_roles: frozenset[str] = KNOWN_ROLES,
    policy: ScopePolicy = POLICY,
) -> Callable[[], None]:
    return lambda: SUITE.test_roles_are_known_to_scope_configuration(
        resolver=resolver, valid_credentials=VALID, known_roles=known_roles, policy=policy
    )


def test_conforming_resolver_passes_roles_method() -> None:
    """The conforming doubles pass the roles method (AIE-1039, US4.1)."""
    _roles_known(_conforming())()
    _roles_known(_conforming(MEMBER_IDENTITY))()


def test_wrong_case_role_fails_naming_scope_and_role() -> None:
    """Role "Admin" against known "admin" fails naming scope and role (AIE-1039, US4.2)."""
    exc = _fails(_roles_known(WrongCaseRole()), "not in known_roles", "WrongCaseRole")

    assert "'Admin'" in str(exc)
    assert "'org'" in str(exc)


def test_known_roles_as_str_fails() -> None:
    """A str known_roles fails naming the fixture, not a substring match (AIE-1039, US4.3).

    Also FR-007.
    """
    bad = "admin owner"
    _fails(
        _roles_known(_conforming(), bad),  # pyright: ignore[reportArgumentType]
        "fixture known_roles",
        "TokenResolver",
    )


def test_policy_role_unknown_fails_naming_scope_and_role() -> None:
    """A policy permitting "Admin" against known "admin" fails (AIE-1039, US4.4)."""
    policy = ScopePolicy({"org": frozenset({"Admin"})})

    exc = _fails(_roles_known(_conforming(), policy=policy), "policy role", "TokenResolver")

    assert "'Admin'" in str(exc)
    assert "'org'" in str(exc)


# --- US5: path construction -------------------------------------------------


def _paths(resolver: IdentityResolver[str]) -> Callable[[], None]:
    return lambda: SUITE.test_granted_scopes_build_valid_paths(
        resolver=resolver, valid_credentials=VALID
    )


def test_conforming_resolver_passes_paths_method() -> None:
    """The conforming double passes the path method (AIE-1039, US5.1)."""
    _paths(_conforming())()


def test_malformed_build_path_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """build_path returning a malformed path fails (AIE-1039, US5.2)."""

    def fake_build_path(scope: str, entity_id: str, area: str, name: str) -> str:
        return f"{scope}//{area}"

    monkeypatch.setattr(resolver_conformance, "build_path", fake_build_path)

    _fails(_paths(_conforming()), "invalid path", "TokenResolver")


def test_non_round_tripping_parse_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """parse_path returning a different name fails (AIE-1039, US5.3)."""

    def fake_parse_path(path: str) -> PathParts:
        parts = parse_path(path)
        return PathParts(parts.scope, parts.entity_id, parts.area, parts.name + "-renamed")

    monkeypatch.setattr(resolver_conformance, "parse_path", fake_parse_path)

    _fails(_paths(_conforming()), "does not round-trip", "TokenResolver")


def test_invalid_prefix_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """build_prefix returning "bad" fails (AIE-1039, US5.4)."""

    def fake_build_prefix(scope: str, entity_id: str | None = None, area: str | None = None) -> str:
        return "bad"

    monkeypatch.setattr(resolver_conformance, "build_prefix", fake_build_prefix)

    _fails(_paths(_conforming()), "invalid prefix", "TokenResolver")


def test_prefix_for_other_scope_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """build_prefix returning a valid prefix for another scope fails (AIE-1039, US5.5)."""

    def fake_build_prefix(scope: str, entity_id: str | None = None, area: str | None = None) -> str:
        return build_prefix("elsewhere", entity_id, area)

    monkeypatch.setattr(resolver_conformance, "build_prefix", fake_build_prefix)

    _fails(_paths(_conforming()), "not under prefix", "TokenResolver")


# --- US6 / US7: enforcement via patched check_write ------------------------


def _noop(path: str, identity: Identity, policy: ScopePolicy) -> None:
    return None


def _always_not_granted(path: str, identity: Identity, policy: ScopePolicy) -> None:
    raise RestrictedScopeError(path, parse_path(path).scope, RestrictionReason.NOT_GRANTED)


def _always_system_read_only(path: str, identity: Identity, policy: ScopePolicy) -> None:
    raise RestrictedScopeError(path, parse_path(path).scope, RestrictionReason.SYSTEM_READ_ONLY)


def _always_not_found(path: str, identity: Identity, policy: ScopePolicy) -> None:
    raise NotFoundError(path, NotFoundReason.INVALID_PATH)


def _always_role_required_x(path: str, identity: Identity, policy: ScopePolicy) -> None:
    raise RestrictedScopeError(
        path, parse_path(path).scope, RestrictionReason.ROLE_REQUIRED, frozenset({"x"})
    )


CheckWrite = Callable[[str, Identity, ScopePolicy], None]
SuiteCall = Callable[[IdentityResolver[str]], Callable[[], None]]


def _system(resolver: IdentityResolver[str]) -> Callable[[], None]:
    return lambda: SUITE.test_system_area_is_read_only_in_every_scope(
        resolver=resolver, valid_credentials=VALID, policy=POLICY
    )


def _own(resolver: IdentityResolver[str]) -> Callable[[], None]:
    return lambda: SUITE.test_own_entity_writes_follow_policy(
        resolver=resolver, valid_credentials=VALID, policy=POLICY
    )


def _foreign(resolver: IdentityResolver[str]) -> Callable[[], None]:
    return lambda: SUITE.test_foreign_entity_writes_are_not_granted(
        resolver=resolver, valid_credentials=VALID, policy=POLICY
    )


def _ungranted(resolver: IdentityResolver[str]) -> Callable[[], None]:
    return lambda: SUITE.test_ungranted_scope_writes_are_not_granted(
        resolver=resolver, valid_credentials=VALID, policy=POLICY
    )


def test_conforming_resolvers_pass_enforcement_methods() -> None:
    """Both conforming doubles pass every enforcement method unpatched.

    (AIE-1039, US6.1, US7.1-4)
    """
    for identity in (ADMIN_IDENTITY, MEMBER_IDENTITY):
        for method in (_system, _own, _foreign, _ungranted):
            method(_conforming(identity))()


@pytest.mark.parametrize(
    ("patch", "phrase"),
    [(_noop, "not rejected"), (_always_not_granted, "wrong reason")],
    ids=["no-op", "always-not-granted"],
)
def test_system_area_fails_when_check_write_is_broken(
    monkeypatch: pytest.MonkeyPatch, patch: CheckWrite, phrase: str
) -> None:
    """A no-op or always-NOT_GRANTED check_write fails the system/ test (AIE-1039, US6.2)."""
    monkeypatch.setattr(resolver_conformance, "check_write", patch)

    _fails(_system(_conforming()), phrase, "TokenResolver")


# Failing cells of the spec's US7.5 table; "passes" cells are omitted.
MATRIX: list[tuple[CheckWrite, SuiteCall, Identity, str]] = [
    (_noop, _system, ADMIN_IDENTITY, "not rejected"),
    (_noop, _own, MEMBER_IDENTITY, "not rejected"),
    (_noop, _foreign, ADMIN_IDENTITY, "not rejected"),
    (_noop, _ungranted, ADMIN_IDENTITY, "not rejected"),
    (_always_not_granted, _system, ADMIN_IDENTITY, "wrong reason"),
    (_always_not_granted, _own, ADMIN_IDENTITY, "unexpected outcome"),
    (_always_not_granted, _own, MEMBER_IDENTITY, "wrong reason"),
    (_always_system_read_only, _own, ADMIN_IDENTITY, "unexpected outcome"),
    (_always_system_read_only, _own, MEMBER_IDENTITY, "wrong reason"),
    (_always_system_read_only, _foreign, ADMIN_IDENTITY, "wrong reason"),
    (_always_system_read_only, _ungranted, ADMIN_IDENTITY, "wrong reason"),
    (_always_not_found, _system, ADMIN_IDENTITY, "wrong reason"),
    (_always_not_found, _own, ADMIN_IDENTITY, "unexpected outcome"),
    (_always_not_found, _own, MEMBER_IDENTITY, "wrong reason"),
    (_always_not_found, _foreign, ADMIN_IDENTITY, "wrong reason"),
    (_always_not_found, _ungranted, ADMIN_IDENTITY, "wrong reason"),
]


def _matrix_id(cell: tuple[CheckWrite, SuiteCall, Identity, str]) -> str:
    patch, method, identity, _ = cell
    role = identity.role("org")
    return f"{patch.__name__.lstrip('_')}-{method.__name__.lstrip('_')}-{role}"


@pytest.mark.parametrize(
    ("patch", "method", "identity", "phrase"), MATRIX, ids=[_matrix_id(c) for c in MATRIX]
)
def test_write_restriction_matrix(
    monkeypatch: pytest.MonkeyPatch,
    patch: CheckWrite,
    method: SuiteCall,
    identity: Identity,
    phrase: str,
) -> None:
    """Each failing cell of the patched-check_write table fails with its phrase.

    (AIE-1039, US7.5, US6.2, US7.7)
    """
    monkeypatch.setattr(resolver_conformance, "check_write", patch)

    exc = _fails(method(_conforming(identity)), phrase, "TokenResolver")

    if patch is not _noop:
        assert isinstance(exc.__context__, RestrictedScopeError | NotFoundError)


def test_wrong_required_roles_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """ROLE_REQUIRED with required_roles {"x"} for the member fails (AIE-1039, US7.6)."""
    monkeypatch.setattr(resolver_conformance, "check_write", _always_role_required_x)

    exc = _fails(_own(_conforming(MEMBER_IDENTITY)), "wrong required_roles", "TokenResolver")

    assert "['x']" in str(exc)
    assert "['admin', 'owner']" in str(exc)


@pytest.mark.parametrize("method", [_system, _own, _foreign, _ungranted])
def test_non_restriction_exception_names_its_type(
    monkeypatch: pytest.MonkeyPatch, method: SuiteCall
) -> None:
    """A non-RestrictedScopeError from check_write fails naming its type (AIE-1039, US7.7)."""
    monkeypatch.setattr(resolver_conformance, "check_write", _always_not_found)

    exc = _fails(method(_conforming(MEMBER_IDENTITY)), "NotFoundError", "TokenResolver")

    assert isinstance(exc.__context__, NotFoundError)


# --- Review findings: hostile resolvers and pinned behavior ----------------


class EqualToEverythingIdentity(Identity):
    """An Identity claiming equality with any object."""

    def __eq__(self, other: object) -> bool:
        return True

    __hash__ = Identity.__hash__


class EqualToEverythingGrant(ScopeGrant):
    """A ScopeGrant claiming equality with any object."""

    def __eq__(self, other: object) -> bool:
        return True

    __hash__ = ScopeGrant.__hash__


class ShiftingEntityBehindLyingEq:
    """Returns user entity u-0, u-1, u-2... in an Identity whose __eq__ is always True."""

    def __init__(self) -> None:
        self.calls = 0

    def resolve(self, credentials: str) -> Identity | ResolutionFailure:
        entity = f"u-{self.calls}"
        self.calls += 1
        return EqualToEverythingIdentity(
            grants={"user": ScopeGrant(entity, "owner"), "org": ScopeGrant("o-9", "admin")}
        )


class AlternatingRoleBehindLyingEq:
    """Alternates the org role admin/member in an Identity whose __eq__ is always True."""

    def __init__(self) -> None:
        self.calls = 0

    def resolve(self, credentials: str) -> Identity | ResolutionFailure:
        role = "admin" if self.calls % 2 == 0 else "member"
        self.calls += 1
        return EqualToEverythingIdentity(
            grants={"user": ScopeGrant("u-1", "owner"), "org": ScopeGrant("o-9", role)}
        )


class ShiftingEntityBehindLyingGrant:
    """Returns a plain Identity whose org grant lies about equality and shifts entity."""

    def __init__(self) -> None:
        self.calls = 0

    def resolve(self, credentials: str) -> Identity | ResolutionFailure:
        entity = f"o-{self.calls}"
        self.calls += 1
        return Identity(
            grants={
                "user": ScopeGrant("u-1", "owner"),
                "org": EqualToEverythingGrant(entity, "admin"),
            }
        )


class OwnerRoleIdentity(Identity):
    """An Identity whose role() reports "owner" whatever the stored grant says."""

    def role(self, scope: str) -> str:
        return "owner"


class RoleOverridingResolver:
    """Stores role "UNKNOWN" in org but reports "owner" through role()."""

    def resolve(self, credentials: str) -> Identity | ResolutionFailure:
        return OwnerRoleIdentity(
            grants={"user": ScopeGrant("u-1", "owner"), "org": ScopeGrant("o-9", "UNKNOWN")}
        )


class UnvalidatedIdentity(Identity):
    """An Identity that skips validation, so grants may hold anything."""

    def __post_init__(self) -> None:
        return None


class NonGrantResolver:
    """Returns an unvalidated Identity whose org grant is a str."""

    def resolve(self, credentials: str) -> Identity | ResolutionFailure:
        bad = {"user": ScopeGrant("u-1", "owner"), "org": "not-a-grant"}
        return UnvalidatedIdentity(grants=bad)  # pyright: ignore[reportArgumentType]


class SpoofedFailure:
    """Claims to be a ResolutionFailure through __class__, though type() says otherwise."""

    @property
    def __class__(self) -> type:  # pyright: ignore[reportIncompatibleMethodOverride]
        return ResolutionFailure

    detail = "spoofed"


class SpoofsFailureOnInvalid:
    """Resolves the known token; returns a spoofed ResolutionFailure otherwise."""

    def resolve(self, credentials: str) -> Identity | ResolutionFailure:
        if credentials == VALID:
            return ADMIN_IDENTITY
        return SpoofedFailure()  # pyright: ignore[reportReturnType]


class ChangingDetailOnInvalid:
    """Resolves the known token; rejects anything else with a per-call detail."""

    def __init__(self) -> None:
        self.calls = 0

    def resolve(self, credentials: str) -> Identity | ResolutionFailure:
        self.calls += 1
        if credentials == VALID:
            return ADMIN_IDENTITY
        return ResolutionFailure(f"rejected at call {self.calls}")


class RaisingNameMeta(type):
    """A metaclass whose classes raise on __name__ access."""

    @property
    def __name__(cls) -> str:  # pyright: ignore[reportIncompatibleVariableOverride]
        raise RuntimeError("no name for you")


class UnnamedTokenResolver(metaclass=RaisingNameMeta):
    """Conforming, but its class has no readable __name__."""

    def resolve(self, credentials: str) -> Identity | ResolutionFailure:
        if credentials == VALID:
            return ADMIN_IDENTITY
        return ResolutionFailure("unknown token")


class UnnamedRejectsValid(metaclass=RaisingNameMeta):
    """Rejects every credential; its class has no readable __name__."""

    def resolve(self, credentials: str) -> Identity | ResolutionFailure:
        return ResolutionFailure("token expired at noon")


@pytest.mark.parametrize(
    "resolver",
    [ShiftingEntityBehindLyingEq, AlternatingRoleBehindLyingEq, ShiftingEntityBehindLyingGrant],
    ids=["identity-eq-entity", "identity-eq-role", "grant-eq-entity"],
)
def test_lying_eq_does_not_hide_inconsistency(
    resolver: Callable[[], IdentityResolver[str]],
) -> None:
    """Results differing behind an always-True __eq__ still fail consistency.

    (AIE-1039, review finding 1)
    """
    instance = resolver()
    _fails(_valid_consistent(instance), "different results", type(instance).__name__)


def test_overridden_role_does_not_hide_unknown_stored_role() -> None:
    """A role() override cannot mask a stored role missing from known_roles.

    (AIE-1039, review finding 1)
    """
    exc = _fails(
        _roles_known(RoleOverridingResolver()), "not in known_roles", "RoleOverridingResolver"
    )

    assert "'UNKNOWN'" in str(exc)


VALID_CREDENTIAL_METHODS: list[SuiteCall] = [
    _resolve_to_identity,
    _through_entry_point,
    _valid_consistent,
    _roles_known,
    _paths,
    _system,
    _own,
    _foreign,
    _ungranted,
]


@pytest.mark.parametrize(
    "method",
    VALID_CREDENTIAL_METHODS,
    ids=[m.__name__.lstrip("_") for m in VALID_CREDENTIAL_METHODS],
)
def test_unvalidated_identity_fails_as_invalid(method: SuiteCall) -> None:
    """An Identity holding a non-ScopeGrant fails as invalid, not with AttributeError.

    (AIE-1039, review finding 2)
    """
    _fails(method(NonGrantResolver()), "invalid Identity", "NonGrantResolver")


def test_spoofed_class_failure_is_wrong_type() -> None:
    """An object spoofing __class__ as ResolutionFailure fails as the wrong type.

    (AIE-1039, review finding 3)
    """
    exc = _fails(
        _return_failure(SpoofsFailureOnInvalid()),
        "expected Identity or ResolutionFailure",
        "SpoofsFailureOnInvalid",
    )

    assert "SpoofedFailure" in str(exc)


def test_changing_failure_detail_is_consistent() -> None:
    """Rejections whose detail differs per call still count as consistent (AIE-1039, US3.3)."""
    _invalid_consistent(ChangingDetailOnInvalid())()


def _restriction_in_elsewhere(path: str, identity: Identity, policy: ScopePolicy) -> None:
    try:
        check_write(path, identity, policy)
    except RestrictedScopeError as exc:
        raise RestrictedScopeError(path, "elsewhere", exc.reason, exc.required_roles) from None


@pytest.mark.parametrize(
    ("method", "identity"),
    [(_own, MEMBER_IDENTITY), (_system, ADMIN_IDENTITY)],
    ids=["own", "system"],
)
def test_right_reason_in_wrong_scope_fails(
    monkeypatch: pytest.MonkeyPatch, method: SuiteCall, identity: Identity
) -> None:
    """The right reason reported for another scope fails naming that scope.

    (AIE-1039, review finding 4)
    """
    monkeypatch.setattr(resolver_conformance, "check_write", _restriction_in_elsewhere)

    exc = _fails(method(_conforming(identity)), "wrong reason", "TokenResolver")

    assert "'elsewhere'" in str(exc)


def _spy_paths(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    checked: list[str] = []

    def spy(path: str, identity: Identity, policy: ScopePolicy) -> None:
        checked.append(path)
        check_write(path, identity, policy)

    monkeypatch.setattr(resolver_conformance, "check_write", spy)
    return checked


def test_ungranted_method_probes_policy_restricted_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ungranted-scope method probes the policy's ungranted "team" scope.

    (AIE-1039, review finding 4)
    """
    checked = _spy_paths(monkeypatch)

    _ungranted(_conforming())()

    assert "team/conformance-entity/notes/conformance-probe.md" in checked, checked


def test_system_method_probes_ungranted_and_foreign_entities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The system/ method probes an ungranted scope and a foreign entity.

    (AIE-1039, review finding 4)
    """
    checked = _spy_paths(monkeypatch)

    _system(_conforming())()

    assert "conformance-ungranted/conformance-entity/system/conformance-probe.md" in checked, (
        checked
    )
    assert "org/o-9-other/system/conformance-probe.md" in checked, checked


def test_ungranted_name_avoids_granted_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    """A resolver granting "conformance-ungranted" still passes; another name is probed.

    (AIE-1039, review finding 4)
    """
    identity = Identity(
        grants={
            "user": ScopeGrant("u-1", "owner"),
            "org": ScopeGrant("o-9", "admin"),
            "conformance-ungranted": ScopeGrant("conformance-entity", "owner"),
        }
    )
    checked = _spy_paths(monkeypatch)

    _ungranted(_conforming(identity))()

    assert not any(p.startswith("conformance-ungranted/") for p in checked), checked


def test_unreadable_class_name_does_not_escape() -> None:
    """A resolver class whose __name__ raises is still tested (AIE-1039, review finding 5)."""
    _resolve_to_identity(UnnamedTokenResolver())()


def test_unreadable_class_name_reported_as_unnamed() -> None:
    """A broken resolver with an unreadable class name fails as "<unnamed>".

    (AIE-1039, review finding 5)
    """
    _fails(_resolve_to_identity(UnnamedRejectsValid()), "rejected valid credentials", "<unnamed>")


class SpoofedIdentity:
    """Claims to be an Identity through __class__, with valid-looking grants."""

    @property
    def __class__(self) -> type:  # pyright: ignore[reportIncompatibleMethodOverride]
        return Identity

    grants = ADMIN_IDENTITY.grants


class SpoofsIdentityOnValid:
    """Returns a spoofed Identity for every credential."""

    def resolve(self, credentials: str) -> Identity | ResolutionFailure:
        return SpoofedIdentity()  # pyright: ignore[reportReturnType]


class InvalidOnSecondValid:
    """Returns ADMIN_IDENTITY, except an Identity holding a non-ScopeGrant on call 2."""

    def __init__(self) -> None:
        self.calls = 0

    def resolve(self, credentials: str) -> Identity | ResolutionFailure:
        self.calls += 1
        if self.calls == 2:
            bad = {"user": ScopeGrant("u-1", "owner"), "org": "not-a-grant"}
            return UnvalidatedIdentity(grants=bad)  # pyright: ignore[reportArgumentType]
        return ADMIN_IDENTITY


class ContainsEverything(frozenset[str]):
    """A frozenset claiming to contain any value."""

    def __contains__(self, item: object) -> bool:
        return True


class StrSubclass(str):
    """A str subclass, which the fixture check must reject."""


class SpoofedFrozenset:
    """Claims to be a frozenset through __class__ and iterates like one of str."""

    @property
    def __class__(self) -> type:  # pyright: ignore[reportIncompatibleMethodOverride]
        return frozenset

    def __iter__(self) -> Iterator[str]:
        return iter(KNOWN_ROLES)

    def __contains__(self, item: object) -> bool:
        return item in KNOWN_ROLES


def test_entry_point_lying_eq_does_not_hide_different_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """resolve_identity returning different grants behind an always-True __eq__ fails.

    (AIE-1039, review finding 1)
    """

    def fake_resolve_identity[C](resolver: IdentityResolver[C], credentials: C) -> Identity:
        return EqualToEverythingIdentity(grants=dict(MEMBER_IDENTITY.grants))

    monkeypatch.setattr(resolver_conformance, "resolve_identity", fake_resolve_identity)

    _fails(_through_entry_point(_conforming()), "resolve_identity returned", "TokenResolver")


def test_spoofed_class_identity_is_wrong_type() -> None:
    """An object spoofing __class__ as Identity fails as the wrong type.

    (AIE-1039, review finding 3)
    """
    exc = _fails(
        _resolve_to_identity(SpoofsIdentityOnValid()),
        "expected Identity or ResolutionFailure",
        "SpoofsIdentityOnValid",
    )

    assert "SpoofedIdentity" in str(exc)


def test_invalid_identity_on_second_call_names_call() -> None:
    """An Identity turning invalid on call 2 fails as invalid naming the call.

    (AIE-1039, review finding 2)
    """
    exc = _fails(
        _valid_consistent(InvalidOnSecondValid()), "invalid Identity", "InvalidOnSecondValid"
    )

    assert "on call 2" in str(exc)


def test_known_roles_contains_override_does_not_hide_unknown_role() -> None:
    """A known_roles frozenset subclass claiming to contain everything cannot mask a role.

    (AIE-1039, review finding 6)
    """
    known = ContainsEverything(KNOWN_ROLES)

    _fails(_roles_known(WrongCaseRole(), known), "not in known_roles", "WrongCaseRole")


def test_known_roles_with_str_subclass_member_fails() -> None:
    """A known_roles member that is a str subclass fails naming the fixture.

    (AIE-1039, review finding 6)
    """
    known = frozenset({"owner", "admin", StrSubclass("member")})

    exc = _fails(_roles_known(_conforming(), known), "fixture known_roles", "TokenResolver")

    assert "frozenset containing StrSubclass" in str(exc)


def test_non_str_member_message_names_member_type() -> None:
    """A non-str fixture member is reported as "frozenset containing int".

    (AIE-1039, review finding 6)
    """
    bad = frozenset({"user", 1})

    exc = _fails(
        _resolve_to_identity(_conforming(), bad),  # pyright: ignore[reportArgumentType]
        "fixture expected_scopes",
        "TokenResolver",
    )

    assert "frozenset containing int" in str(exc)


def test_spoofed_class_known_roles_fails() -> None:
    """An object spoofing __class__ as frozenset fails as a fixture of the wrong type.

    (AIE-1039, review finding 6)
    """
    bad = SpoofedFrozenset()

    exc = _fails(
        _roles_known(_conforming(), bad),  # pyright: ignore[reportArgumentType]
        "fixture known_roles",
        "TokenResolver",
    )

    assert "SpoofedFrozenset" in str(exc)


def test_own_entity_unexpected_restriction_names_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unexpected RestrictedScopeError on an own-entity write reports its reason.

    (AIE-1039, review finding 4)
    """
    monkeypatch.setattr(resolver_conformance, "check_write", _always_not_granted)

    exc = _fails(_own(_conforming(ADMIN_IDENTITY)), "unexpected outcome", "TokenResolver")

    assert "RestrictedScopeError (not_granted)" in str(exc)
