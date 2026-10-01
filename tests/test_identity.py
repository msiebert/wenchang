"""Tests for the identity value types, the resolver protocol, resolve_identity,
and SandboxResolver.

Covers AIE-1043, US1, US2.1-4, US2.7-9, US3, and US4 (FR-001 to FR-006, SC-001).
"""

import copy
import dataclasses
import pickle
from collections.abc import ItemsView, Iterator, Mapping

import pytest

from wenchang.errors import (
    BackendUnavailableError,
    ErrorCategory,
    PermanentError,
    ResolverFailureError,
    TransientReason,
    WenchangError,
)
from wenchang.identity import (
    Identity,
    IdentityResolver,
    ResolutionFailure,
    SandboxResolver,
    ScopeGrant,
    resolve_identity,
)

pytestmark = pytest.mark.unit

REJECTED_SEGMENTS = (
    "",
    ".",
    "..",
    "/",
    "a/b",
    "a\\b",
    "a\x00b",
    "\x7f",
    "\x85",
)


def _grants() -> dict[str, ScopeGrant]:
    return {"user": ScopeGrant("u-1", "owner"), "org": ScopeGrant("o-9", "member")}


def _identity() -> Identity:
    return Identity(_grants())


def test_identity_exposes_scope_map_role_and_entity_id() -> None:
    """scope_map, role, and entity_id reflect the grants (AIE-1043, US1.1)."""
    identity = _identity()

    assert identity.scope_map == {"user": "u-1", "org": "o-9"}
    assert identity.role("org") == "member"
    assert identity.role("user") == "owner"
    assert identity.entity_id("user") == "u-1"
    assert identity.entity_id("org") == "o-9"


def test_identity_copies_grants_on_construction() -> None:
    """Mutating the source dict after construction leaves the Identity unchanged
    (AIE-1043, US1.2).
    """
    grants = _grants()
    identity = Identity(grants)

    grants["team"] = ScopeGrant("t-3", "admin")
    grants["user"] = ScopeGrant("u-2", "guest")
    del grants["org"]

    assert identity == _identity()
    assert identity.scope_map == {"user": "u-1", "org": "o-9"}
    assert identity.role("user") == "owner"


def test_mutating_scope_map_result_leaves_identity_unchanged() -> None:
    """scope_map returns a fresh dict whose mutation does not affect the Identity
    (AIE-1043, US1.3).
    """
    identity = _identity()

    scope_map = identity.scope_map
    scope_map["user"] = "u-2"
    scope_map["team"] = "t-3"

    assert identity.scope_map == {"user": "u-1", "org": "o-9"}
    assert identity.entity_id("user") == "u-1"


def test_grants_item_assignment_raises_type_error() -> None:
    """identity.grants is read-only: item assignment raises TypeError (AIE-1043, US1.3)."""
    identity = _identity()

    with pytest.raises(TypeError):
        identity.grants["team"] = ScopeGrant("t-3", "admin")  # pyright: ignore[reportIndexIssue]

    assert identity == _identity()


def test_identity_fields_are_frozen() -> None:
    """Identity is immutable: rebinding grants raises FrozenInstanceError
    (AIE-1043, US1.3, FR-002).
    """
    identity = _identity()

    with pytest.raises(dataclasses.FrozenInstanceError):
        identity.grants = {}  # pyright: ignore[reportAttributeAccessIssue]


def test_scope_grant_fields_are_frozen() -> None:
    """ScopeGrant is immutable: assigning a field raises FrozenInstanceError
    (AIE-1043, FR-001).
    """
    grant = ScopeGrant("u-1", "owner")

    with pytest.raises(dataclasses.FrozenInstanceError):
        grant.role = "admin"  # pyright: ignore[reportAttributeAccessIssue]


def test_equal_grants_in_any_order_are_equal_and_hash_equal() -> None:
    """Identities from equal grants in different insertion orders compare and
    hash equal (AIE-1043, US1.4).
    """
    forward = Identity({"user": ScopeGrant("u-1", "owner"), "org": ScopeGrant("o-9", "member")})
    reverse = Identity({"org": ScopeGrant("o-9", "member"), "user": ScopeGrant("u-1", "owner")})

    assert forward == reverse
    assert hash(forward) == hash(reverse)
    assert len({forward, reverse}) == 1


@pytest.mark.parametrize(
    "other",
    [
        {"user": ScopeGrant("u-2", "owner"), "org": ScopeGrant("o-9", "member")},
        {"user": ScopeGrant("u-1", "admin"), "org": ScopeGrant("o-9", "member")},
        {"person": ScopeGrant("u-1", "owner"), "org": ScopeGrant("o-9", "member")},
        {"user": ScopeGrant("u-1", "owner")},
    ],
    ids=["different-entity-id", "different-role", "different-scope-name", "missing-scope"],
)
def test_different_grants_compare_unequal(other: dict[str, ScopeGrant]) -> None:
    """A different entity ID, role, or scope name makes Identities unequal
    (AIE-1043, US1.4).
    """
    assert _identity() != Identity(other)


def test_scope_grants_equal_and_hash_by_value() -> None:
    """ScopeGrant compares and hashes by value (AIE-1043, US1.4, FR-001)."""
    assert ScopeGrant("u-1", "owner") == ScopeGrant("u-1", "owner")
    assert hash(ScopeGrant("u-1", "owner")) == hash(ScopeGrant("u-1", "owner"))
    assert ScopeGrant("u-1", "owner") != ScopeGrant("u-1", "member")


def test_empty_grants_build_identity_with_empty_scope_map() -> None:
    """An Identity with no grants is valid and has an empty scope_map
    (AIE-1043, US1.5).
    """
    identity = Identity({})

    assert identity.scope_map == {}
    assert identity == Identity({})
    assert hash(identity) == hash(Identity({}))


def test_role_for_ungranted_scope_raises_key_error() -> None:
    """role() for a scope with no grant raises KeyError (AIE-1043, US1.6)."""
    with pytest.raises(KeyError):
        _identity().role("team")


def test_entity_id_for_ungranted_scope_raises_key_error() -> None:
    """entity_id() for a scope with no grant raises KeyError (AIE-1043, US1.6)."""
    with pytest.raises(KeyError):
        _identity().entity_id("team")


def test_lookups_on_empty_identity_raise_key_error() -> None:
    """role() and entity_id() on an Identity with no grants raise KeyError
    (AIE-1043, US1.6).
    """
    identity = Identity({})

    with pytest.raises(KeyError):
        identity.role("user")
    with pytest.raises(KeyError):
        identity.entity_id("user")


@pytest.mark.parametrize("grants", [_grants(), {}], ids=["two-scopes", "empty"])
def test_identity_round_trips_through_pickle(grants: dict[str, ScopeGrant]) -> None:
    """pickle.dumps/loads yields an equal Identity (AIE-1043, US1.7)."""
    identity = Identity(grants)

    restored = pickle.loads(pickle.dumps(identity))

    assert isinstance(restored, Identity)
    assert restored == identity
    assert hash(restored) == hash(identity)


@pytest.mark.parametrize("grants", [_grants(), {}], ids=["two-scopes", "empty"])
def test_identity_round_trips_through_deepcopy(grants: dict[str, ScopeGrant]) -> None:
    """copy.deepcopy yields an equal Identity (AIE-1043, US1.7)."""
    identity = Identity(grants)

    copied = copy.deepcopy(identity)

    assert isinstance(copied, Identity)
    assert copied == identity
    assert copied.scope_map == identity.scope_map


def test_round_tripped_identity_grants_stay_read_only() -> None:
    """An Identity restored from pickle still rejects item assignment on grants
    (AIE-1043, US1.7, FR-002).
    """
    restored = pickle.loads(pickle.dumps(_identity()))
    assert isinstance(restored, Identity)

    with pytest.raises(TypeError):
        restored.grants["team"] = ScopeGrant("t-3", "admin")  # pyright: ignore[reportIndexIssue]


@pytest.mark.parametrize("entity_id", REJECTED_SEGMENTS)
def test_scope_grant_rejects_invalid_entity_id(entity_id: str) -> None:
    """An entity_id failing the segment rule raises ValueError (AIE-1043, US2.1)."""
    with pytest.raises(ValueError):
        ScopeGrant(entity_id, "owner")


def test_scope_grant_rejects_empty_role() -> None:
    """An empty role raises ValueError (AIE-1043, US2.2)."""
    with pytest.raises(ValueError):
        ScopeGrant("u-1", "")


def test_scope_grant_accepts_valid_values() -> None:
    """A valid entity_id and non-empty role build a ScopeGrant (AIE-1043, US2.1, US2.2)."""
    grant = ScopeGrant("u-1", "owner")

    assert grant.entity_id == "u-1"
    assert grant.role == "owner"


@pytest.mark.parametrize("scope", REJECTED_SEGMENTS)
def test_identity_rejects_invalid_scope_name(scope: str) -> None:
    """A scope name failing the segment rule raises ValueError (AIE-1043, US2.3)."""
    with pytest.raises(ValueError):
        Identity({scope: ScopeGrant("u-1", "owner")})


def test_identity_rejects_invalid_scope_name_among_valid_ones() -> None:
    """One invalid scope name among valid ones still raises ValueError
    (AIE-1043, US2.3).
    """
    with pytest.raises(ValueError):
        Identity({"user": ScopeGrant("u-1", "owner"), "a/b": ScopeGrant("o-9", "member")})


def test_resolution_failure_rejects_empty_detail() -> None:
    """An empty detail raises ValueError (AIE-1043, US2.4)."""
    with pytest.raises(ValueError):
        ResolutionFailure("")


def test_resolution_failure_keeps_detail() -> None:
    """A non-empty detail builds a ResolutionFailure holding it (AIE-1043, US2.4, FR-003)."""
    assert ResolutionFailure("token expired").detail == "token expired"


@pytest.mark.parametrize("bad", [1, None], ids=["int", "none"])
def test_scope_grant_rejects_non_str_entity_id(bad: object) -> None:
    """A non-str entity_id raises TypeError (AIE-1043, US2.7)."""
    with pytest.raises(TypeError):
        ScopeGrant(bad, "owner")  # pyright: ignore[reportArgumentType]


@pytest.mark.parametrize("bad", [1, None], ids=["int", "none"])
def test_scope_grant_rejects_non_str_role(bad: object) -> None:
    """A non-str role raises TypeError (AIE-1043, US2.7)."""
    with pytest.raises(TypeError):
        ScopeGrant("u-1", bad)  # pyright: ignore[reportArgumentType]


def test_scope_grant_type_check_precedes_value_check() -> None:
    """A non-str entity_id with an empty role raises TypeError, not ValueError
    (AIE-1043, US2.7, FR-001).
    """
    with pytest.raises(TypeError):
        ScopeGrant(None, "")  # pyright: ignore[reportArgumentType]


def test_identity_rejects_non_str_scope_key() -> None:
    """A non-str grants key raises TypeError (AIE-1043, US2.8)."""
    with pytest.raises(TypeError):
        Identity({1: ScopeGrant("u-1", "owner")})  # pyright: ignore[reportArgumentType]


@pytest.mark.parametrize(
    "bad_value",
    ["u-1", ("u-1", "owner"), None],
    ids=["str", "tuple", "none"],
)
def test_identity_rejects_non_scope_grant_value(bad_value: object) -> None:
    """A grants value that is not a ScopeGrant raises TypeError (AIE-1043, US2.9)."""
    with pytest.raises(TypeError):
        Identity({"user": bad_value})  # pyright: ignore[reportArgumentType]


class _FixedResolver:
    """Returns one preset result and records the credentials it was given."""

    def __init__(self, result: Identity | ResolutionFailure) -> None:
        self._result = result
        self.received: list[object] = []

    def resolve(self, credentials: object) -> Identity | ResolutionFailure:
        self.received.append(credentials)
        return self._result


class _RaisingResolver:
    """Raises a preset exception from resolve."""

    def __init__(self, exc: BaseException) -> None:
        self.exc = exc

    def resolve(self, credentials: object) -> Identity | ResolutionFailure:
        raise self.exc


class _NoneResolver:
    """Violates the protocol by returning None."""

    def resolve(self, credentials: object) -> Identity | ResolutionFailure:
        return None  # pyright: ignore[reportReturnType]


class _WrongTypeResolver:
    """Violates the protocol by returning an arbitrary value."""

    def __init__(self, value: object) -> None:
        self._value = value

    def resolve(self, credentials: object) -> Identity | ResolutionFailure:
        return self._value  # pyright: ignore[reportReturnType]


class _NoResolveMethod:
    """Has no resolve method, so it is not an IdentityResolver."""

    def lookup(self, credentials: object) -> Identity:
        return _identity()


SECRET = "secret-token-xyz"
SECRET_CREDENTIALS = "cred-secret-abc"
GUIDANCE_PREFIX = "Identity could not be resolved"


def test_resolve_identity_returns_the_resolvers_identity_object() -> None:
    """resolve_identity returns the resolver's Identity object itself
    (AIE-1043, US3.1).
    """
    identity = _identity()
    resolver = _FixedResolver(identity)

    result = resolve_identity(resolver, "creds")

    assert result is identity


@pytest.mark.parametrize(
    "credentials",
    [None, "token-abc", {"token": "abc", "tenant": 3}, object()],
    ids=["none", "str", "dict", "object"],
)
def test_resolve_identity_passes_credentials_unchanged(credentials: object) -> None:
    """The resolver receives the exact credentials object passed in (AIE-1043, US3.1)."""
    resolver = _FixedResolver(_identity())

    resolve_identity(resolver, credentials)

    assert len(resolver.received) == 1
    assert resolver.received[0] is credentials


def test_resolution_failure_becomes_permanent_resolver_failure_error() -> None:
    """A returned ResolutionFailure raises a permanent ResolverFailureError whose
    detail begins with the failure detail (AIE-1043, US3.2).
    """
    resolver = _FixedResolver(ResolutionFailure("token expired"))

    with pytest.raises(ResolverFailureError) as excinfo:
        resolve_identity(resolver, SECRET_CREDENTIALS)

    err = excinfo.value
    assert err.detail.startswith("token expired")
    assert err.category is ErrorCategory.PERMANENT
    assert isinstance(err, PermanentError)
    assert SECRET_CREDENTIALS not in str(err)


def test_raising_resolver_becomes_resolver_failure_error_without_secret() -> None:
    """A resolver raising an Exception yields a ResolverFailureError naming the
    resolver class and exception type, without the exception message or
    credentials (AIE-1043, US3.3).
    """
    resolver = _RaisingResolver(RuntimeError(SECRET))

    with pytest.raises(ResolverFailureError) as excinfo:
        resolve_identity(resolver, SECRET_CREDENTIALS)

    err = excinfo.value
    assert err.detail.startswith("Resolver _RaisingResolver raised RuntimeError.")
    assert "_RaisingResolver" in str(err)
    assert "RuntimeError" in str(err)
    assert SECRET not in str(err)
    assert SECRET not in err.detail
    assert SECRET_CREDENTIALS not in str(err)
    assert err.category is ErrorCategory.PERMANENT


def test_raising_resolver_error_is_not_chained() -> None:
    """The converted error is raised from None: no __cause__ and the context is
    suppressed (AIE-1043, US3.3).
    """
    resolver = _RaisingResolver(RuntimeError(SECRET))

    with pytest.raises(ResolverFailureError) as excinfo:
        resolve_identity(resolver, "creds")

    assert excinfo.value.__cause__ is None
    assert excinfo.value.__suppress_context__ is True


def test_none_returning_resolver_becomes_resolver_failure_error() -> None:
    """A resolver returning None yields a ResolverFailureError naming the resolver
    class and the returned type (AIE-1043, US3.4).
    """
    with pytest.raises(ResolverFailureError) as excinfo:
        resolve_identity(_NoneResolver(), "creds")

    err = excinfo.value
    assert err.detail.startswith(
        "Resolver _NoneResolver returned NoneType, not Identity or ResolutionFailure."
    )
    assert err.category is ErrorCategory.PERMANENT


@pytest.mark.parametrize(
    ("value", "type_name"),
    [
        ({"user": "u-1"}, "dict"),
        (ScopeGrant("u-1", "owner"), "ScopeGrant"),
        (SECRET, "str"),
    ],
    ids=["dict", "scope-grant", "str"],
)
def test_wrongly_typed_return_becomes_resolver_failure_error(value: object, type_name: str) -> None:
    """A resolver returning a non-Identity, non-ResolutionFailure value yields a
    ResolverFailureError naming the resolver class and the returned type
    (AIE-1043, US3.4).
    """
    with pytest.raises(ResolverFailureError) as excinfo:
        resolve_identity(_WrongTypeResolver(value), SECRET_CREDENTIALS)

    err = excinfo.value
    assert err.detail.startswith(
        f"Resolver _WrongTypeResolver returned {type_name}, not Identity or ResolutionFailure."
    )
    assert SECRET not in str(err)
    assert SECRET_CREDENTIALS not in str(err)


def test_keyboard_interrupt_propagates_unchanged() -> None:
    """A KeyboardInterrupt raised by the resolver propagates as the same object
    (AIE-1043, US3.5).
    """
    interrupt = KeyboardInterrupt()
    resolver = _RaisingResolver(interrupt)

    with pytest.raises(KeyboardInterrupt) as excinfo:
        resolve_identity(resolver, "creds")

    assert excinfo.value is interrupt


def test_system_exit_propagates_unchanged() -> None:
    """A SystemExit raised by the resolver propagates as the same object
    (AIE-1043, US3.5).
    """
    exit_exc = SystemExit(3)
    resolver = _RaisingResolver(exit_exc)

    with pytest.raises(SystemExit) as excinfo:
        resolve_identity(resolver, "creds")

    assert excinfo.value is exit_exc


def test_raised_resolver_failure_error_is_replaced_not_passed_through() -> None:
    """A resolver raising ResolverFailureError("x") yields a new
    ResolverFailureError naming the resolver class and exception type, without
    reusing the original detail (AIE-1043, US3.6).
    """
    original = ResolverFailureError("x")
    resolver = _RaisingResolver(original)

    with pytest.raises(ResolverFailureError) as excinfo:
        resolve_identity(resolver, "creds")

    err = excinfo.value
    assert err is not original
    assert err.detail.startswith("Resolver _RaisingResolver raised ResolverFailureError.")
    assert not err.detail.startswith("x ")
    assert original.detail not in err.detail
    assert err.detail.count(GUIDANCE_PREFIX) == 1
    assert err.__cause__ is None
    assert err.__suppress_context__ is True


def test_raised_wenchang_error_is_converted_without_its_detail() -> None:
    """A resolver raising another WenchangError yields a new ResolverFailureError
    naming the resolver class and exception type, without the original detail
    (AIE-1043, US3.6).
    """
    original = BackendUnavailableError(TransientReason.UNAVAILABLE, SECRET)
    assert isinstance(original, WenchangError)
    resolver = _RaisingResolver(original)

    with pytest.raises(ResolverFailureError) as excinfo:
        resolve_identity(resolver, "creds")

    err = excinfo.value
    assert err.detail.startswith("Resolver _RaisingResolver raised BackendUnavailableError.")
    assert SECRET not in str(err)
    assert err.category is ErrorCategory.PERMANENT
    assert err.__cause__ is None
    assert err.__suppress_context__ is True


@pytest.mark.parametrize(
    "credentials",
    [None, "token-abc", {"token": "abc"}, object()],
    ids=["none", "str", "dict", "object"],
)
def test_sandbox_resolver_returns_configured_identity_for_any_credentials(
    credentials: object,
) -> None:
    """SandboxResolver.resolve returns the configured Identity for any credentials
    (AIE-1043, US4.1).
    """
    identity = _identity()
    resolver = SandboxResolver(identity)

    assert resolver.resolve(credentials) is identity


def test_sandbox_resolver_returns_same_identity_every_time() -> None:
    """Repeated calls to SandboxResolver.resolve all return the configured Identity
    (AIE-1043, US4.1).
    """
    identity = Identity({})
    resolver = SandboxResolver(identity)

    results = [resolver.resolve(c) for c in (None, "a", "a", {"k": 1}, object())]

    assert all(result is identity for result in results)


def test_sandbox_resolver_is_an_identity_resolver() -> None:
    """SandboxResolver satisfies the runtime-checkable IdentityResolver protocol
    (AIE-1043, US4.2).
    """
    candidate: object = SandboxResolver(_identity())

    assert isinstance(candidate, IdentityResolver)


def test_object_without_resolve_is_not_an_identity_resolver() -> None:
    """Objects with no resolve method are not IdentityResolvers (AIE-1043, US4.2)."""
    plain: object = object()
    other: object = _NoResolveMethod()

    assert not isinstance(plain, IdentityResolver)
    assert not isinstance(other, IdentityResolver)


def test_sandbox_resolver_satisfies_protocol_for_any_credential_type() -> None:
    """SandboxResolver is statically assignable to IdentityResolver for any
    credential type (AIE-1043, US4.2, FR-004).
    """
    identity = _identity()
    for_str: IdentityResolver[str] = SandboxResolver(identity)
    for_dict: IdentityResolver[dict[str, int]] = SandboxResolver(identity)

    assert for_str.resolve("token") is identity
    assert for_dict.resolve({"tenant": 1}) is identity


@pytest.mark.parametrize(
    "credentials",
    [None, "token-abc", {"token": "abc"}, object()],
    ids=["none", "str", "dict", "object"],
)
def test_resolve_identity_with_sandbox_resolver_returns_configured_identity(
    credentials: object,
) -> None:
    """resolve_identity with a SandboxResolver returns the configured Identity
    (AIE-1043, US4.3).
    """
    identity = _identity()

    assert resolve_identity(SandboxResolver(identity), credentials) is identity


class _ItemsLyingDict(dict[str, ScopeGrant]):
    """A dict whose items() reports a valid grant while its content is invalid."""

    def items(self) -> ItemsView[str, ScopeGrant]:  # pyright: ignore[reportIncompatibleMethodOverride]
        return {"user": ScopeGrant("u-1", "owner")}.items()


class _ItemsLyingMapping(Mapping[str, ScopeGrant]):
    """A Mapping whose items() reports a valid grant but whose lookup does not."""

    def __getitem__(self, key: str) -> ScopeGrant:
        return "not-a-grant"  # pyright: ignore[reportReturnType]

    def __iter__(self) -> Iterator[str]:
        return iter(["user"])

    def __len__(self) -> int:
        return 1

    def items(self) -> ItemsView[str, ScopeGrant]:
        return {"user": ScopeGrant("u-1", "owner")}.items()


def test_identity_validates_dict_content_not_items_view() -> None:
    """A dict subclass whose items() hides an invalid scope name still raises
    ValueError at construction (AIE-1043, review finding 1).
    """
    grants = _ItemsLyingDict({"a/b": ScopeGrant("u-1", "owner")})

    with pytest.raises(ValueError):
        Identity(grants)


def test_identity_validates_mapping_lookup_not_items_view() -> None:
    """A Mapping whose items() hides a non-ScopeGrant value still raises
    TypeError at construction (AIE-1043, review finding 1).
    """
    with pytest.raises(TypeError):
        Identity(_ItemsLyingMapping())


class _EvilStr(str):
    """A str subclass that defeats substring and formatting checks."""

    def __contains__(self, key: object) -> bool:
        return False

    def __format__(self, format_spec: str) -> str:
        return "../../other"


class _PlainStr(str):
    """A str subclass with no overrides."""


def test_identity_rejects_evil_str_scope_name() -> None:
    """A str-subclass scope name overriding __contains__ and __format__ is
    still checked by its real value and raises ValueError (AIE-1043, review finding 2).
    """
    with pytest.raises(ValueError):
        Identity({_EvilStr("a/b"): ScopeGrant("u-1", "owner")})


def test_scope_grant_rejects_evil_str_entity_id() -> None:
    """A str-subclass entity_id overriding __contains__ and __format__ is still
    checked by its real value and raises ValueError (AIE-1043, review finding 2).
    """
    with pytest.raises(ValueError):
        ScopeGrant(_EvilStr("a/b"), "member")


def test_identity_accepts_plain_str_subclass_key_and_stores_exact_str() -> None:
    """A benign str-subclass scope name is accepted and stored as an exact str
    (AIE-1043, review finding 2).
    """
    identity = Identity({_PlainStr("user"): ScopeGrant("u-1", "owner")})

    assert type(next(iter(identity.grants))) is str
    assert identity == Identity({"user": ScopeGrant("u-1", "owner")})
    assert identity.entity_id("user") == "u-1"


class _ClassRaises:
    """An object whose __class__ lookup raises, defeating isinstance fallbacks."""

    @property
    def __class__(self) -> type:  # pyright: ignore[reportIncompatibleVariableOverride, reportIncompatibleMethodOverride]
        raise RuntimeError(SECRET)


class _FormatRaises(str):
    """A str subclass whose formatting raises."""

    def __format__(self, format_spec: str) -> str:
        raise RuntimeError(SECRET)


def test_return_with_raising_class_lookup_becomes_resolver_failure_error() -> None:
    """A returned object whose __class__ raises yields ResolverFailureError, not
    the resolver's own exception (AIE-1043, review finding 3).
    """
    resolver = _WrongTypeResolver(_ClassRaises())

    with pytest.raises(ResolverFailureError) as excinfo:
        resolve_identity(resolver, "creds")

    assert "_WrongTypeResolver" in excinfo.value.detail
    assert SECRET not in str(excinfo.value)


def test_failure_detail_with_raising_format_becomes_resolver_failure_error() -> None:
    """A ResolutionFailure whose detail raises on formatting yields a
    ResolverFailureError naming the resolver class (AIE-1043, review finding 3).
    """
    failure = ResolutionFailure(_FormatRaises("token expired"))
    # Reinstate the raising detail in case construction normalizes it.
    object.__setattr__(failure, "detail", _FormatRaises("token expired"))
    resolver = _FixedResolver(failure)

    with pytest.raises(ResolverFailureError) as excinfo:
        resolve_identity(resolver, "creds")

    assert "_FixedResolver" in excinfo.value.detail
    assert SECRET not in str(excinfo.value)


@pytest.mark.parametrize("bad", [None, 1, b"x"], ids=["none", "int", "bytes"])
def test_resolution_failure_rejects_non_str_detail(bad: object) -> None:
    """A non-str detail raises TypeError (AIE-1043, review finding 4)."""
    with pytest.raises(TypeError):
        ResolutionFailure(bad)  # pyright: ignore[reportArgumentType]


class _SubIdentity(Identity):
    """An Identity subclass for round-trip tests."""


def test_identity_subclass_round_trips_through_pickle() -> None:
    """Pickling an Identity subclass restores the subclass (AIE-1043, review finding 5)."""
    original = _SubIdentity(_grants())

    restored = pickle.loads(pickle.dumps(original))

    assert type(restored) is _SubIdentity
    assert restored == original


def test_identity_subclass_round_trips_through_deepcopy() -> None:
    """Deep-copying an Identity subclass keeps the subclass (AIE-1043, review finding 5)."""
    original = _SubIdentity(_grants())

    copied = copy.deepcopy(original)

    assert type(copied) is _SubIdentity
    assert copied == original


class _ScopeGrantImpostor:
    """Claims to be a ScopeGrant through __class__ while its real type is not."""

    entity_id = "u-1"
    role = "owner"

    @property
    def __class__(self) -> type:  # pyright: ignore[reportIncompatibleVariableOverride, reportIncompatibleMethodOverride]
        return ScopeGrant


def test_identity_rejects_value_spoofing_scope_grant_class() -> None:
    """A grants value whose __class__ reports ScopeGrant but whose real type is
    not ScopeGrant raises TypeError (AIE-1043, US2.9).
    """
    impostor = _ScopeGrantImpostor()
    assert isinstance(impostor, ScopeGrant)
    assert type(impostor) is not ScopeGrant

    with pytest.raises(TypeError):
        Identity({"user": impostor})  # pyright: ignore[reportArgumentType]


class _DistinctStr(str):
    """A str subclass whose instances are equal and hash only by identity."""

    def __eq__(self, other: object) -> bool:
        return self is other

    def __ne__(self, other: object) -> bool:
        return self is not other

    def __hash__(self) -> int:
        return id(self)


def test_identity_rejects_keys_colliding_after_normalization() -> None:
    """Two distinct keys that both normalize to "user" raise ValueError rather
    than dropping a grant (AIE-1043, US2.12).
    """
    first = _DistinctStr("user")
    second = _DistinctStr("user")
    grants: dict[str, ScopeGrant] = {
        first: ScopeGrant("u-1", "owner"),
        second: ScopeGrant("u-2", "guest"),
    }
    assert len(grants) == 2

    with pytest.raises(ValueError):
        Identity(grants)


class _NameRaisingMeta(type):
    """A metaclass whose classes raise when their __name__ is read."""

    @property
    def __name__(self) -> str:  # pyright: ignore[reportIncompatibleVariableOverride]
        raise RuntimeError(SECRET)


class _UnnamedWrongTypeResolver(metaclass=_NameRaisingMeta):
    """Returns a wrong-typed value; its class name cannot be read."""

    def resolve(self, credentials: object) -> Identity | ResolutionFailure:
        return {"user": "u-1"}  # pyright: ignore[reportReturnType]


class _UnnamedValue(metaclass=_NameRaisingMeta):
    """A value whose type name cannot be read."""


def test_resolver_with_raising_type_name_becomes_resolver_failure_error() -> None:
    """A wrong-type return from a resolver whose class __name__ raises still
    yields ResolverFailureError, not the metaclass's error (AIE-1043, US3.4).
    """
    with pytest.raises(ResolverFailureError) as excinfo:
        resolve_identity(_UnnamedWrongTypeResolver(), "creds")

    err = excinfo.value
    assert err.detail.startswith(
        "Resolver <unnamed> returned dict, not Identity or ResolutionFailure."
    )
    assert SECRET not in str(err)


def test_return_with_raising_type_name_reports_unnamed() -> None:
    """A returned object whose type's __name__ raises yields ResolverFailureError
    naming the type "<unnamed>" (AIE-1043, US3.4).
    """
    with pytest.raises(ResolverFailureError) as excinfo:
        resolve_identity(_WrongTypeResolver(_UnnamedValue()), "creds")

    err = excinfo.value
    assert err.detail.startswith(
        "Resolver _WrongTypeResolver returned <unnamed>, not Identity or ResolutionFailure."
    )
    assert SECRET not in str(err)
