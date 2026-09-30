"""Write restrictions enforced at the tool layer.

The tool layer calls `check_write` before every mutating call; it runs
`check_not_system`, then `check_write_allowed`. The `system/` area of every
scope holds curated content and is read-only. `check_write_allowed` checks
the path's form and the caller's grant and role, but not the system/ area.
`MemoryStore` applies none of these, so the seeding job and admin tooling can
write `system/` and restricted scopes through core.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Self, cast

from wenchang.errors import NotFoundError, NotFoundReason, RestrictedScopeError, RestrictionReason
from wenchang.identity import Identity
from wenchang.paths import is_valid_path, is_valid_segment, parse_path

SYSTEM_AREA: Final = "system"


def _exact_path(path: str) -> str:
    # Callers may be untyped, so the path type is checked at runtime.
    if not isinstance(path, str):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise TypeError("path must be str")
    # An exact str, so overridden str-subclass methods cannot mislead the checks.
    return str.__str__(path)


def is_system_path(path: str) -> bool:
    """Return True iff path is a valid memory path whose area is exactly `system`.

    Never raises; returns False for a non-str.
    """
    if not isinstance(path, str):  # pyright: ignore[reportUnnecessaryIsInstance]
        return False
    path = str.__str__(path)
    return is_valid_path(path) and parse_path(path).area == SYSTEM_AREA


def check_not_system(path: str) -> None:
    """Reject a write to the read-only `system/` area of any scope.

    Raises NotFoundError(INVALID_PATH) for a malformed path, and
    RestrictedScopeError(SYSTEM_READ_ONLY) naming the path's scope if its
    area is `system`. Raises TypeError for a non-str path.
    """
    path = _exact_path(path)
    try:
        parts = parse_path(path)
    except ValueError:
        raise NotFoundError(path, NotFoundReason.INVALID_PATH) from None
    if parts.area == SYSTEM_AREA:
        raise RestrictedScopeError(path, parts.scope, RestrictionReason.SYSTEM_READ_ONLY)


def _validated_roles(scope: str, roles: object) -> frozenset[str]:
    # type() rather than isinstance, which consults a spoofable __class__.
    if not issubclass(type(roles), frozenset):
        raise TypeError(f"roles for scope {scope!r} must be a frozenset")
    # A real frozenset copy, so an overridden __len__ or __iter__ cannot mislead the checks.
    members = frozenset(cast(frozenset[object], roles))
    if len(members) == 0:
        raise ValueError(f"scope {scope!r} has no permitted roles")
    if not all(isinstance(role, str) for role in members):
        raise TypeError(f"roles for scope {scope!r} must be str")
    # Exact strs, so overridden str-subclass methods cannot mislead matching.
    normalized = frozenset(str.__str__(cast(str, role)) for role in members)
    if "" in normalized:
        raise ValueError(f"scope {scope!r} has an empty role")
    return normalized


@dataclass(frozen=True)
class ScopePolicy:
    """The adopter's scope configuration: permitted writer roles per restricted scope.

    A scope absent from `write_roles` is unrestricted. Scope names match the
    resolver's grant keys by exact string equality; a key that matches no
    resolver scope restricts nothing.
    """

    write_roles: Mapping[str, frozenset[str]]

    def __post_init__(self) -> None:
        # Policies may come from config files, so input types are checked at runtime.
        if not isinstance(self.write_roles, Mapping):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError("write_roles must be a Mapping")
        # Validated and stored once, so the caller's mapping is never re-read.
        items: list[tuple[object, object]] = list(
            cast(Mapping[object, object], self.write_roles).items()
        )
        snapshot: dict[str, frozenset[str]] = {}
        for raw_scope, roles in items:
            if not isinstance(raw_scope, str):
                raise TypeError(f"scope name must be a str: {raw_scope!r}")
            scope = str.__str__(raw_scope)
            if not is_valid_segment(scope):
                raise ValueError(f"invalid scope: {scope!r}")
            normalized = _validated_roles(scope, roles)
            if scope in snapshot:
                raise ValueError(f"duplicate scope after normalization: {scope!r}")
            snapshot[scope] = normalized
        object.__setattr__(self, "write_roles", MappingProxyType(snapshot))

    def __hash__(self) -> int:
        return hash(frozenset(self.write_roles.items()))

    def __reduce__(self) -> tuple[type[Self], tuple[dict[str, frozenset[str]]]]:
        return (type(self), (dict(self.write_roles),))

    def is_write_restricted(self, scope: str) -> bool:
        """True iff `scope` has an entry in `write_roles`."""
        return scope in self.write_roles

    def permitted_roles(self, scope: str) -> frozenset[str] | None:
        """The roles permitted to write `scope`, or None if it is unrestricted."""
        return self.write_roles.get(scope)


def check_write_allowed(path: str, identity: Identity, policy: ScopePolicy) -> None:
    """Raise unless `identity` may write `path` under `policy`.

    Checks that the path is well formed, that it lies under the caller's own
    entity in a granted scope, and that the caller's role there is permitted.
    Does not check the system/ area. Tool code must call check_write instead.
    """
    path = _exact_path(path)
    try:
        parts = parse_path(path)
    except ValueError:
        raise NotFoundError(path, NotFoundReason.INVALID_PATH) from None
    grant = identity.grants.get(parts.scope)
    if grant is None or grant.entity_id != parts.entity_id:
        raise RestrictedScopeError(path, parts.scope, RestrictionReason.NOT_GRANTED)
    permitted = policy.permitted_roles(parts.scope)
    if permitted is not None and grant.role not in permitted:
        raise RestrictedScopeError(
            path, parts.scope, RestrictionReason.ROLE_REQUIRED, required_roles=permitted
        )


def check_write(path: str, identity: Identity, policy: ScopePolicy) -> None:
    """Raise unless a mutating call on `path` may proceed.

    The tool layer calls this before every mutating call. Runs the system/
    check, then check_write_allowed, on the same exact str.
    """
    path = _exact_path(path)
    check_not_system(path)
    check_write_allowed(path, identity, policy)
