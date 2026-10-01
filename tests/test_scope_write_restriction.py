"""Tests for role-gated write restriction in wenchang.scope.

Covers AIE-1042, US1 through US4: ScopePolicy, check_write_allowed, and
check_write, including the check order invalid path, system/, not granted,
then role.
"""

import copy
import pickle
import re
from collections.abc import Callable

import pytest

from wenchang.errors import (
    ErrorCategory,
    NotFoundError,
    NotFoundReason,
    RestrictedScopeError,
    RestrictionReason,
)
from wenchang.identity import Identity, ScopeGrant
from wenchang.paths import parse_path
from wenchang.scope import (
    ScopePolicy,
    check_not_system,
    check_write,
    check_write_allowed,
    is_system_path,
)

pytestmark = pytest.mark.unit

CheckFn = Callable[[str, Identity, ScopePolicy], None]

ORG_ROLES = frozenset({"admin", "owner"})
TEAM_ROLES = frozenset({"admin"})

POLICY = ScopePolicy({"org": ORG_ROLES, "team": TEAM_ROLES})


def _grants(org_role: str = "member") -> dict[str, ScopeGrant]:
    return {
        "user": ScopeGrant("u-1", "member"),
        "org": ScopeGrant("o-9", org_role),
        "project": ScopeGrant("p-3", "member"),
    }


IDENTITY = Identity(_grants())
PROJECT_ONLY_IDENTITY = Identity({"project": ScopeGrant("p-3", "member")})
EMPTY_IDENTITY = Identity({})


def _identity_with_org_role(role: str) -> Identity:
    return Identity(_grants(org_role=role))


BOTH_CHECKS: list[tuple[str, CheckFn]] = [
    ("check_write_allowed", check_write_allowed),
    ("check_write", check_write),
]
BOTH_CHECK_IDS = [name for name, _ in BOTH_CHECKS]


def _raise_restricted(fn: CheckFn, path: str, identity: Identity) -> RestrictedScopeError:
    with pytest.raises(RestrictedScopeError) as exc_info:
        fn(path, identity, POLICY)
    return exc_info.value


# --- US1: ScopePolicy ---------------------------------------------------------


def test_policy_reports_restricted_scopes_and_roles() -> None:
    """Listed scopes are restricted with their role sets; absent scopes are
    unrestricted with no role set. (AIE-1042, US1.1)"""
    assert POLICY.is_write_restricted("org") is True
    assert POLICY.permitted_roles("org") == frozenset({"admin", "owner"})
    assert POLICY.is_write_restricted("team") is True
    assert POLICY.permitted_roles("team") == frozenset({"admin"})
    assert POLICY.is_write_restricted("project") is False
    assert POLICY.permitted_roles("project") is None


def test_policy_copies_source_dict() -> None:
    """Mutating the dict a policy was built from leaves the policy unchanged.
    (AIE-1042, US1.2)"""
    source = {"org": frozenset({"admin"})}
    policy = ScopePolicy(source)
    source["org"] = frozenset({"member"})
    source["project"] = frozenset({"admin"})
    del source["org"]
    assert policy.permitted_roles("org") == frozenset({"admin"})
    assert policy.is_write_restricted("project") is False
    assert dict(policy.write_roles) == {"org": frozenset({"admin"})}


def test_policy_write_roles_is_read_only() -> None:
    """Assigning to policy.write_roles[...] raises TypeError. (AIE-1042, US1.2)"""
    policy = ScopePolicy({"org": frozenset({"admin"})})
    with pytest.raises(TypeError):
        policy.write_roles["project"] = frozenset({"admin"})  # pyright: ignore[reportIndexIssue]
    assert policy.is_write_restricted("project") is False


@pytest.mark.parametrize(
    "scope",
    ["", ".", "..", "a/b", "/", "a\\b", "\\", "a\x00b", "a\nb", "\x1f", "\t"],
    ids=[
        "empty",
        "dot",
        "dotdot",
        "slash",
        "bare_slash",
        "backslash",
        "bare_backslash",
        "nul",
        "newline",
        "unit_sep",
        "tab",
    ],
)
def test_policy_rejects_invalid_scope_name(scope: str) -> None:
    """A scope name that is not a valid path segment raises ValueError.
    (AIE-1042, US1.3)"""
    with pytest.raises(ValueError, match=r"^invalid scope"):
        ScopePolicy({scope: frozenset({"admin"})})


@pytest.mark.parametrize(
    ("roles", "prefix"),
    [
        (frozenset[str](), "scope 'org' has no permitted roles"),
        (frozenset({""}), "scope 'org' has an empty role"),
        (frozenset({"admin", ""}), "scope 'org' has an empty role"),
    ],
    ids=["empty_set", "only_empty_role", "empty_role_among_others"],
)
def test_policy_rejects_empty_roles(roles: frozenset[str], prefix: str) -> None:
    """An empty role set, or a set containing "", raises ValueError.
    (AIE-1042, US1.4)"""
    with pytest.raises(ValueError, match="^" + re.escape(prefix)):
        ScopePolicy({"org": roles})


def test_policy_equality_ignores_insertion_order() -> None:
    """Policies from equal mappings in different insertion orders compare and
    hash equal. (AIE-1042, US1.5)"""
    first = ScopePolicy({"org": ORG_ROLES, "team": TEAM_ROLES})
    second = ScopePolicy({"team": frozenset({"admin"}), "org": frozenset({"owner", "admin"})})
    assert first == second
    assert hash(first) == hash(second)
    assert first != ScopePolicy({"org": ORG_ROLES})
    assert first != ScopePolicy({"org": frozenset({"admin"}), "team": TEAM_ROLES})


def test_empty_policy_restricts_nothing() -> None:
    """ScopePolicy({}) is valid and restricts nothing. (AIE-1042, US1.5)"""
    policy = ScopePolicy({})
    assert policy == ScopePolicy({})
    assert hash(policy) == hash(ScopePolicy({}))
    for scope in ("org", "team", "project", "system"):
        assert policy.is_write_restricted(scope) is False
        assert policy.permitted_roles(scope) is None
    assert check_write_allowed("org/o-9/notes/a.md", IDENTITY, policy) is None


@pytest.mark.parametrize("scope", ["system", "org", "organization", "zz-plain"])
def test_policy_treats_every_scope_name_alike(scope: str) -> None:
    """No scope name is special-cased: restricted, it gates by role; absent,
    it is unrestricted. (AIE-1042, US1.6)"""
    path = f"{scope}/e-1/notes/a.md"
    restricted = ScopePolicy({scope: frozenset({"admin"})})
    assert restricted.is_write_restricted(scope) is True
    assert restricted.permitted_roles(scope) == frozenset({"admin"})

    member = Identity({scope: ScopeGrant("e-1", "member")})
    admin = Identity({scope: ScopeGrant("e-1", "admin")})

    with pytest.raises(RestrictedScopeError) as exc_info:
        check_write_allowed(path, member, restricted)
    assert exc_info.value.reason is RestrictionReason.ROLE_REQUIRED
    assert exc_info.value.scope == scope
    assert exc_info.value.required_roles == frozenset({"admin"})

    assert check_write_allowed(path, admin, restricted) is None
    assert check_write_allowed(path, member, ScopePolicy({})) is None
    assert check_write(path, admin, restricted) is None
    assert check_write(path, member, ScopePolicy({})) is None


# Each row: (write_roles, expected exception type, expected message prefix).
# Rows after the first block pin the check order from plan.md.
BAD_POLICY_INPUTS: list[tuple[object, type[Exception], str]] = [
    ([("org", frozenset({"admin"}))], TypeError, "write_roles must be a Mapping"),
    (None, TypeError, "write_roles must be a Mapping"),
    ("org", TypeError, "write_roles must be a Mapping"),
    ({1: frozenset({"admin"})}, TypeError, "scope name must be a str"),
    ({None: frozenset({"admin"})}, TypeError, "scope name must be a str"),
    ({"org": "admin"}, TypeError, "roles for scope 'org' must be a frozenset"),
    ({"org": ["admin"]}, TypeError, "roles for scope 'org' must be a frozenset"),
    ({"org": {"admin"}}, TypeError, "roles for scope 'org' must be a frozenset"),
    ({"org": None}, TypeError, "roles for scope 'org' must be a frozenset"),
    ({"org": frozenset({1})}, TypeError, "roles for scope 'org' must be str"),
    ({"org": frozenset({"admin", None})}, TypeError, "roles for scope 'org' must be str"),
    # Check 2 before check 4: a non-str key with a non-frozenset value.
    ({1: "admin"}, TypeError, "scope name must be a str"),
    # Check 3 before check 4: an invalid name with a str value.
    ({"": "admin"}, ValueError, "invalid scope"),
    # Check 4 before check 5: an empty str is not an empty role set.
    ({"org": ""}, TypeError, "roles for scope 'org' must be a frozenset"),
    # Check 4 before check 5: an empty list.
    ({"org": []}, TypeError, "roles for scope 'org' must be a frozenset"),
    # Check 6 before check 7: a non-str role alongside "".
    ({"org": frozenset({1, ""})}, TypeError, "roles for scope 'org' must be str"),
    # One entry's checks all run before the next entry's.
    (
        {"org": frozenset({1}), "": frozenset({"admin"})},
        TypeError,
        "roles for scope 'org' must be str",
    ),
    (
        {"org": frozenset[str](), 1: frozenset({"admin"})},
        ValueError,
        "scope 'org' has no permitted roles",
    ),
    ({"a/b": frozenset({1}), "org": "admin"}, ValueError, "invalid scope"),
]

BAD_POLICY_IDS = [
    "list_of_pairs",
    "none_mapping",
    "str_mapping",
    "int_key",
    "none_key",
    "str_value",
    "list_value",
    "set_value",
    "none_value",
    "int_role",
    "none_role",
    "order_key_type_before_value_type",
    "order_scope_value_before_value_type",
    "order_value_type_before_empty_str",
    "order_value_type_before_empty_list",
    "order_role_type_before_empty_role",
    "order_first_entry_role_type_before_second_entry",
    "order_first_entry_empty_before_second_key_type",
    "order_first_entry_scope_before_its_roles",
]


@pytest.mark.parametrize(
    ("write_roles", "exc_type", "prefix"), BAD_POLICY_INPUTS, ids=BAD_POLICY_IDS
)
def test_policy_rejects_wrongly_typed_input(
    write_roles: object, exc_type: type[Exception], prefix: str
) -> None:
    """Wrongly typed input raises TypeError, and a multiply-bad input raises
    the first failing check in plan.md's order. (AIE-1042, US1.7)"""
    with pytest.raises(exc_type, match="^" + re.escape(prefix)) as exc_info:
        ScopePolicy(write_roles)  # pyright: ignore[reportArgumentType]
    assert type(exc_info.value) is exc_type


@pytest.mark.parametrize("key", ["Org", "ORG", "org ", " org", "orgs", "o", chr(0xFF4F) + "rg"])
def test_policy_key_matches_scope_exactly(key: str) -> None:
    """A policy key differing from the path's scope restricts nothing: matching
    is exact string equality. (AIE-1042, US1.8)"""
    policy = ScopePolicy({key: frozenset({"admin"})})
    assert policy.is_write_restricted("org") is False
    assert policy.permitted_roles("org") is None
    assert check_write_allowed("org/o-9/notes/a.md", IDENTITY, policy) is None


def test_policy_pickle_round_trip() -> None:
    """A policy round-trips through pickle equal to the original.
    (AIE-1042, US1.9)"""
    restored = pickle.loads(pickle.dumps(POLICY))
    assert isinstance(restored, ScopePolicy)
    assert restored == POLICY
    assert hash(restored) == hash(POLICY)
    assert restored.permitted_roles("org") == ORG_ROLES
    with pytest.raises(TypeError):
        restored.write_roles["project"] = frozenset({"admin"})  # pyright: ignore[reportIndexIssue]


def test_policy_deepcopy_round_trip() -> None:
    """copy.deepcopy of a policy equals the original. (AIE-1042, US1.9)"""
    copied = copy.deepcopy(POLICY)
    assert isinstance(copied, ScopePolicy)
    assert copied == POLICY
    assert hash(copied) == hash(POLICY)
    assert copied.permitted_roles("team") == TEAM_ROLES


# --- US2: role-gated writes ---------------------------------------------------


def test_member_denied_in_restricted_org() -> None:
    """Role member in restricted org raises permanent ROLE_REQUIRED carrying
    the permitted roles and naming org, admin, and owner. (AIE-1042, US2.1)"""
    path = "org/o-9/notes/a.md"
    err = _raise_restricted(check_write_allowed, path, IDENTITY)
    assert err.path == path
    assert err.scope == "org"
    assert err.reason is RestrictionReason.ROLE_REQUIRED
    assert err.required_roles == frozenset({"admin", "owner"})
    assert err.category is ErrorCategory.PERMANENT
    message = str(err)
    assert path in message
    assert "org" in message
    assert "admin, owner" in message


def test_role_required_message_omits_caller_role() -> None:
    """The ROLE_REQUIRED message does not reveal the caller's own role.
    (AIE-1042, US2.1)"""
    err = _raise_restricted(
        check_write_allowed, "org/o-9/notes/a.md", _identity_with_org_role("role-zq9")
    )
    assert err.reason is RestrictionReason.ROLE_REQUIRED
    assert "role-zq9" not in str(err)


@pytest.mark.parametrize("role", ["admin", "owner"])
def test_permitted_role_allowed_in_restricted_org(role: str) -> None:
    """Role admin or owner in org may write org. (AIE-1042, US2.2)"""
    assert check_write_allowed("org/o-9/notes/a.md", _identity_with_org_role(role), POLICY) is None


@pytest.mark.parametrize("role", ["member", "guest", "admin", "role-zq9"])
@pytest.mark.parametrize(
    ("scope", "entity_id", "path"),
    [("project", "p-3", "project/p-3/notes/a.md"), ("user", "u-1", "user/u-1/prefs/a.md")],
    ids=["project", "user"],
)
def test_unrestricted_scope_allows_any_granted_role(
    scope: str, entity_id: str, path: str, role: str
) -> None:
    """A scope absent from the policy accepts any granted role.
    (AIE-1042, US2.3)"""
    grants = _grants()
    grants[scope] = ScopeGrant(entity_id, role)
    assert check_write_allowed(path, Identity(grants), POLICY) is None


@pytest.mark.parametrize("role", ["Admin", "ADMIN", "admin ", " admin"])
def test_role_match_is_exact(role: str) -> None:
    """Roles compare by exact string equality, so Admin is not admin.
    (AIE-1042, US2.4)"""
    policy = ScopePolicy({"org": frozenset({"admin"})})
    with pytest.raises(RestrictedScopeError) as exc_info:
        check_write_allowed("org/o-9/notes/a.md", _identity_with_org_role(role), policy)
    assert exc_info.value.reason is RestrictionReason.ROLE_REQUIRED
    assert exc_info.value.required_roles == frozenset({"admin"})


# --- US3: writes outside the resolved identity ----------------------------------


@pytest.mark.parametrize(
    ("path", "scope"),
    [("team/t-1/notes/a.md", "team"), ("club/c-1/notes/a.md", "club")],
    ids=["restricted_team", "unrestricted_club"],
)
def test_ungranted_scope_not_granted(path: str, scope: str) -> None:
    """A scope the identity has no grant for raises permanent NOT_GRANTED with
    no role set, whether or not the policy restricts it. (AIE-1042, US3.1)"""
    err = _raise_restricted(check_write_allowed, path, IDENTITY)
    assert err.path == path
    assert err.scope == scope
    assert err.reason is RestrictionReason.NOT_GRANTED
    assert err.required_roles is None
    assert err.category is ErrorCategory.PERMANENT


def test_entity_mismatch_in_unrestricted_scope_not_granted() -> None:
    """Another entity in unrestricted project raises NOT_GRANTED.
    (AIE-1042, US3.2)"""
    path = "project/p-4/notes/a.md"
    err = _raise_restricted(check_write_allowed, path, IDENTITY)
    assert err.path == path
    assert err.scope == "project"
    assert err.reason is RestrictionReason.NOT_GRANTED
    assert err.required_roles is None


@pytest.mark.parametrize("role", ["member", "admin", "owner"])
def test_entity_mismatch_in_restricted_scope_not_granted(role: str) -> None:
    """Another entity in restricted org raises NOT_GRANTED, not ROLE_REQUIRED,
    regardless of role. (AIE-1042, US3.3)"""
    err = _raise_restricted(
        check_write_allowed, "org/o-8/notes/a.md", _identity_with_org_role(role)
    )
    assert err.scope == "org"
    assert err.reason is RestrictionReason.NOT_GRANTED
    assert err.required_roles is None


def test_not_granted_message_omits_caller_entity_and_role() -> None:
    """The NOT_GRANTED message names the path and scope but not the caller's
    own entity ID or role. (AIE-1042, US3.4)"""
    path = "org/o-8/notes/a.md"
    identity = Identity({"org": ScopeGrant("own-entity-7f3", "role-zq9")})
    err = _raise_restricted(check_write_allowed, path, identity)
    assert err.reason is RestrictionReason.NOT_GRANTED
    message = str(err)
    assert path in message
    assert "org" in message
    assert "own-entity-7f3" not in message
    assert "role-zq9" not in message


def test_restricted_scope_without_grant_not_granted() -> None:
    """Restricted org with no org grant raises NOT_GRANTED with no role set,
    not ROLE_REQUIRED. (AIE-1042, US3.5)"""
    err = _raise_restricted(check_write_allowed, "org/o-9/notes/a.md", PROJECT_ONLY_IDENTITY)
    assert err.scope == "org"
    assert err.reason is RestrictionReason.NOT_GRANTED
    assert err.required_roles is None


@pytest.mark.parametrize(
    "path",
    ["project/p-3/notes/a.md", "user/u-1/prefs/a.md", "org/o-9/notes/a.md", "team/t-1/notes/a.md"],
)
def test_empty_identity_not_granted(path: str) -> None:
    """Identity({}) can write nothing: every valid path is NOT_GRANTED.
    (AIE-1042, US3.6)"""
    err = _raise_restricted(check_write_allowed, path, EMPTY_IDENTITY)
    assert err.scope == path.split("/")[0]
    assert err.reason is RestrictionReason.NOT_GRANTED
    assert err.required_roles is None


# --- US4: composite entry point and check order --------------------------------


MALFORMED_PATHS = [
    "org/o-9/notes",
    "org/o-9/notes/a.txt",
    "",
    "project/p-3/notes/a.md/",
    "/project/p-3/notes/a.md",
    "project/p-3/notes/sub/a.md",
    "project/../notes/a.md",
    "team/t-1/notes/a.md\n",
]


@pytest.mark.parametrize("path", MALFORMED_PATHS)
@pytest.mark.parametrize(("fn_name", "fn"), BOTH_CHECKS, ids=BOTH_CHECK_IDS)
def test_malformed_path_invalid_path(fn_name: str, fn: CheckFn, path: str) -> None:
    """A malformed path raises NotFoundError(INVALID_PATH) from either check,
    never RestrictedScopeError. (AIE-1042, US4.1)"""
    try:
        fn(path, IDENTITY, POLICY)
    except NotFoundError as err:
        assert err.path == path
        assert err.reason is NotFoundReason.INVALID_PATH
    except RestrictedScopeError as err:
        pytest.fail(f"{fn_name}: expected NotFoundError, got RestrictedScopeError: {err}")
    else:
        pytest.fail(f"{fn_name}: expected NotFoundError, got no exception")


def test_check_write_rejects_granted_system_area() -> None:
    """check_write rejects the system area of a granted, permitted scope, which
    check_write_allowed alone accepts. (AIE-1042, US4.2)"""
    path = "project/p-3/system/a.md"
    err = _raise_restricted(check_write, path, IDENTITY)
    assert err.path == path
    assert err.scope == "project"
    assert err.reason is RestrictionReason.SYSTEM_READ_ONLY
    assert err.required_roles is None
    assert check_write_allowed(path, IDENTITY, POLICY) is None


@pytest.mark.parametrize(
    ("path", "scope"),
    [
        ("team/t-1/system/a.md", "team"),
        ("org/o-8/system/a.md", "org"),
        ("club/c-1/system/a.md", "club"),
    ],
)
def test_check_write_system_wins_over_not_granted(path: str, scope: str) -> None:
    """In an ungranted scope or entity, check_write raises SYSTEM_READ_ONLY,
    not NOT_GRANTED. (AIE-1042, US4.3)"""
    err = _raise_restricted(check_write, path, IDENTITY)
    assert err.scope == scope
    assert err.reason is RestrictionReason.SYSTEM_READ_ONLY


Expected = NotFoundReason | RestrictionReason | None

INVALID = NotFoundReason.INVALID_PATH
SYSTEM = RestrictionReason.SYSTEM_READ_ONLY
NOT_GRANTED = RestrictionReason.NOT_GRANTED
ROLE = RestrictionReason.ROLE_REQUIRED

# Spec US4.4, verbatim: (path, identity, check_write result, check_write_allowed result).
PRECEDENCE_TABLE: list[tuple[str, str, Identity, Expected, Expected]] = [
    ("team/t-1/system/a.txt", "identity", IDENTITY, INVALID, INVALID),
    ("org/o-8/system/a.txt", "identity", IDENTITY, INVALID, INVALID),
    ("team/t-1/notes", "identity", IDENTITY, INVALID, INVALID),
    ("org/o-9/system", "identity", IDENTITY, INVALID, INVALID),
    ("team/t-1/system/a.md", "identity", IDENTITY, SYSTEM, NOT_GRANTED),
    ("org/o-8/system/a.md", "identity", IDENTITY, SYSTEM, NOT_GRANTED),
    ("org/o-9/system/a.md", "identity", IDENTITY, SYSTEM, ROLE),
    ("project/p-3/system/a.md", "identity", IDENTITY, SYSTEM, None),
    ("team/t-1/notes/a.md", "identity", IDENTITY, NOT_GRANTED, NOT_GRANTED),
    ("org/o-8/notes/a.md", "identity", IDENTITY, NOT_GRANTED, NOT_GRANTED),
    ("project/p-4/notes/a.md", "identity", IDENTITY, NOT_GRANTED, NOT_GRANTED),
    ("org/o-9/notes/a.md", "identity", IDENTITY, ROLE, ROLE),
    ("project/p-3/notes/a.md", "identity", IDENTITY, None, None),
    ("org/o-9/notes/a.md", "project_only", PROJECT_ONLY_IDENTITY, NOT_GRANTED, NOT_GRANTED),
    ("project/p-3/notes/a.md", "empty", EMPTY_IDENTITY, NOT_GRANTED, NOT_GRANTED),
]

PRECEDENCE_CASES: list[tuple[str, CheckFn, str, Identity, Expected]] = []
PRECEDENCE_IDS: list[str] = []
for _row, (_path, _label, _identity, _cw, _cwa) in enumerate(PRECEDENCE_TABLE, start=1):
    PRECEDENCE_CASES.append(("check_write", check_write, _path, _identity, _cw))
    PRECEDENCE_IDS.append(f"row{_row:02d}-check_write-{_label}-{_path}")
    PRECEDENCE_CASES.append(("check_write_allowed", check_write_allowed, _path, _identity, _cwa))
    PRECEDENCE_IDS.append(f"row{_row:02d}-check_write_allowed-{_label}-{_path}")


def test_precedence_table_shape() -> None:
    """The precedence case list has all 15 spec rows, each run against both
    functions. (AIE-1042, US4.4)"""
    assert len(PRECEDENCE_TABLE) == 15
    assert len(PRECEDENCE_CASES) == 30


def _assert_sc001(fn_name: str, path: str, identity: Identity) -> None:
    parts = parse_path(path)
    grant = identity.grants.get(parts.scope)
    assert grant is not None, "accepted path's scope must be granted"
    assert grant.entity_id == parts.entity_id, "accepted path must be the caller's own entity"
    permitted = POLICY.permitted_roles(parts.scope)
    assert permitted is None or grant.role in permitted, "accepted role must be permitted"
    if fn_name == "check_write":
        assert not is_system_path(path), "check_write must not accept a system/ path"


@pytest.mark.parametrize(
    ("fn_name", "fn", "path", "identity", "expected"), PRECEDENCE_CASES, ids=PRECEDENCE_IDS
)
def test_check_precedence(
    fn_name: str, fn: CheckFn, path: str, identity: Identity, expected: Expected
) -> None:
    """The first applicable error wins, in the order invalid path, system/,
    not granted, role; every accepted row satisfies SC-001. (AIE-1042, US4.4)"""
    if expected is None:
        assert fn(path, identity, POLICY) is None
        _assert_sc001(fn_name, path, identity)
    elif isinstance(expected, NotFoundReason):
        with pytest.raises(NotFoundError) as nf_info:
            fn(path, identity, POLICY)
        assert nf_info.value.path == path
        assert nf_info.value.reason is expected
    else:
        with pytest.raises(RestrictedScopeError) as rs_info:
            fn(path, identity, POLICY)
        err = rs_info.value
        assert err.path == path
        assert err.scope == path.split("/")[0]
        assert err.reason is expected
        if expected is RestrictionReason.ROLE_REQUIRED:
            assert err.required_roles == POLICY.permitted_roles(err.scope)
        else:
            assert err.required_roles is None


@pytest.mark.parametrize(
    ("path", "identity"),
    [
        ("project/p-3/notes/a.md", IDENTITY),
        ("user/u-1/prefs/a.md", IDENTITY),
        ("org/o-9/notes/a.md", _identity_with_org_role("admin")),
        ("org/o-9/notes/a.md", _identity_with_org_role("owner")),
    ],
    ids=["project", "user", "org_admin", "org_owner"],
)
def test_check_write_allows_fully_permitted_path(path: str, identity: Identity) -> None:
    """A path passing every check is accepted by check_write.
    (AIE-1042, US4.5)"""
    assert check_write(path, identity, POLICY) is None
    _assert_sc001("check_write", path, identity)


# --- Hostile inputs -----------------------------------------------------------


class _NeOnly(str):
    """A str whose != is always False."""

    def __ne__(self, other: object) -> bool:
        return False


class _NeOnlySplitPath(str):
    """A path whose split() yields _NeOnly segments."""

    def split(self, sep: str | None = None, maxsplit: int = -1) -> list[str]:  # pyright: ignore[reportIncompatibleMethodOverride]
        return [_NeOnly(part) for part in str(self).split(sep, maxsplit)]


class _SwitchingSplitPath(str):
    """A path whose split() reports a notes/ area twice, then a system/ area."""

    def __init__(self, _value: str) -> None:
        super().__init__()
        self.calls = 0

    def split(self, sep: str | None = None, maxsplit: int = -1) -> list[str]:  # pyright: ignore[reportIncompatibleMethodOverride]
        self.calls += 1
        if self.calls <= 2:
            return ["project", "p-3", "notes", "a.md"]
        return ["project", "p-3", "system", "a.md"]


class _BenignPath(str):
    """A str subclass that overrides nothing."""


@pytest.mark.parametrize(("fn_name", "fn"), BOTH_CHECKS, ids=BOTH_CHECK_IDS)
def test_str_subclass_cannot_bypass_entity_check(fn_name: str, fn: CheckFn) -> None:
    """A path str subclass whose segments lie under != still raises
    NOT_GRANTED for another entity. (AIE-1042, review finding 1)"""
    path = _NeOnlySplitPath("project/p-999/notes/a.md")
    with pytest.raises(RestrictedScopeError) as exc_info:
        fn(path, PROJECT_ONLY_IDENTITY, ScopePolicy({}))
    assert exc_info.value.reason is RestrictionReason.NOT_GRANTED, fn_name


def test_str_subclass_cannot_bypass_system_check() -> None:
    """A path str subclass whose split() changes between calls cannot slip a
    system/ write past check_write. (AIE-1042, review finding 1)"""
    path = _SwitchingSplitPath("project/p-3/system/a.md")
    with pytest.raises(RestrictedScopeError) as exc_info:
        check_write(path, PROJECT_ONLY_IDENTITY, ScopePolicy({}))
    assert exc_info.value.reason in (
        RestrictionReason.SYSTEM_READ_ONLY,
        RestrictionReason.NOT_GRANTED,
    )


@pytest.mark.parametrize(
    "make_path",
    [_SwitchingSplitPath, _NeOnlySplitPath],
    ids=["stateful_split", "ne_always_false_segments"],
)
def test_str_subclass_cannot_bypass_check_not_system(make_path: Callable[[str], str]) -> None:
    """A hostile path str subclass passed straight to check_not_system still
    raises rather than returning None. (AIE-1042, review finding 1)"""
    path = make_path("project/p-3/system/a.md")
    with pytest.raises((RestrictedScopeError, NotFoundError)):
        check_not_system(path)


def test_check_not_system_rejects_none_path() -> None:
    """check_not_system(None) raises TypeError. (AIE-1042, review finding 1)"""
    with pytest.raises(TypeError, match="path must be str"):
        check_not_system(None)  # pyright: ignore[reportArgumentType]


def _outcome(fn: CheckFn, path: str, identity: Identity) -> tuple[object, ...]:
    try:
        fn(path, identity, POLICY)
    except NotFoundError as err:
        return ("not_found", err.path, err.reason)
    except RestrictedScopeError as err:
        return ("restricted", err.path, err.scope, err.reason, err.required_roles, str(err))
    return ("allowed",)


@pytest.mark.parametrize(
    ("fn_name", "fn", "path", "identity", "expected"), PRECEDENCE_CASES, ids=PRECEDENCE_IDS
)
def test_benign_str_subclass_behaves_like_str(
    fn_name: str, fn: CheckFn, path: str, identity: Identity, expected: Expected
) -> None:
    """A str subclass that overrides nothing gets exactly the plain str's
    outcome. (AIE-1042, review finding 1)"""
    assert _outcome(fn, _BenignPath(path), identity) == _outcome(fn, path, identity), fn_name


@pytest.mark.parametrize("path", [None, b"x", 5], ids=["none", "bytes", "int"])
@pytest.mark.parametrize(("fn_name", "fn"), BOTH_CHECKS, ids=BOTH_CHECK_IDS)
def test_non_str_path_raises_type_error(fn_name: str, fn: CheckFn, path: object) -> None:
    """A non-str path raises TypeError. (AIE-1042, review finding 1)"""
    with pytest.raises(TypeError):
        fn(path, IDENTITY, POLICY)  # pyright: ignore[reportArgumentType]


class _LyingFrozenSet(frozenset[str]):
    """An empty frozenset that reports a length of 1."""

    def __len__(self) -> int:
        return 1


def test_policy_rejects_empty_role_set_that_lies_about_len() -> None:
    """An empty role set whose __len__ lies still raises ValueError.
    (AIE-1042, review finding 3)"""
    with pytest.raises(ValueError):
        ScopePolicy({"org": _LyingFrozenSet()})
