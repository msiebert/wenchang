"""Caller identity: the value a resolver returns and the types it is built from.

Scope names and entity IDs follow the path segment rule, so an Identity can
never produce a traversal or malformed memory path.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol, Self, cast, runtime_checkable

from wenchang.errors import ResolverFailureError
from wenchang.paths import is_valid_segment


def _require_str(name: str, value: object) -> str:
    # Resolvers may be untyped adopter code, so field types are checked at runtime.
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a str, not {type(value).__name__}")
    # An exact str, so overridden str-subclass methods cannot mislead validation.
    return str.__str__(value)


@dataclass(frozen=True)
class ScopeGrant:
    """The caller's entity ID and role within one scope."""

    entity_id: str
    role: str

    def __post_init__(self) -> None:
        entity_id = _require_str("entity_id", self.entity_id)
        role = _require_str("role", self.role)
        object.__setattr__(self, "entity_id", entity_id)
        object.__setattr__(self, "role", role)
        if not is_valid_segment(entity_id):
            raise ValueError(f"entity_id {entity_id!r} is not a valid path segment")
        if role == "":
            raise ValueError("role must be non-empty")


@dataclass(frozen=True)
class Identity:
    """What a resolver returns: the caller's grant in each scope it can reach."""

    grants: Mapping[str, ScopeGrant]

    def __post_init__(self) -> None:
        if not isinstance(self.grants, Mapping):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError("grants must be a Mapping")
        # Validated and stored once, so the caller's mapping is never re-read.
        raw = dict(cast(Mapping[object, object], self.grants))
        snapshot: dict[str, ScopeGrant] = {}
        for raw_scope, grant in raw.items():
            scope = _require_str("scope name", raw_scope)
            if not is_valid_segment(scope):
                raise ValueError(f"scope name {scope!r} is not a valid path segment")
            # type() rather than isinstance, which consults a spoofable __class__.
            if not issubclass(type(grant), ScopeGrant):
                raise TypeError(
                    f"grant for scope {scope!r} must be a ScopeGrant, not {type(grant).__name__}"
                )
            if scope in snapshot:
                raise ValueError(f"duplicate scope after normalization: {scope!r}")
            snapshot[scope] = cast(ScopeGrant, grant)
        object.__setattr__(self, "grants", MappingProxyType(snapshot))

    def __hash__(self) -> int:
        return hash(frozenset(self.grants.items()))

    def __reduce__(self) -> tuple[type[Self], tuple[dict[str, ScopeGrant]]]:
        return (type(self), (dict(self.grants),))

    @property
    def scope_map(self) -> dict[str, str]:
        """Scope name → entity ID, as a new dict on each call."""
        return {scope: grant.entity_id for scope, grant in self.grants.items()}

    def entity_id(self, scope: str) -> str:
        """The caller's entity ID in `scope`. Raises KeyError if not granted."""
        return self.grants[scope].entity_id

    def role(self, scope: str) -> str:
        """The caller's role in `scope`. Raises KeyError if not granted."""
        return self.grants[scope].role


@dataclass(frozen=True)
class ResolutionFailure:
    """A resolver's report that credentials could not be resolved.

    `detail` is shown to the agent and must never contain credentials.
    """

    detail: str

    def __post_init__(self) -> None:
        detail = _require_str("detail", self.detail)
        object.__setattr__(self, "detail", detail)
        if detail == "":
            raise ValueError("detail must be non-empty")


@runtime_checkable
class IdentityResolver[C](Protocol):
    """Turns caller credentials into an Identity. Injected by the adopter.

    isinstance checks only that a resolve attribute exists.
    """

    def resolve(self, credentials: C) -> Identity | ResolutionFailure:
        """Resolve `credentials`.

        Must not raise: report bad or unverifiable credentials as a
        ResolutionFailure. Identical credentials must give an equal result
        within a session.
        """
        ...


def _type_name(t: type) -> str:
    # A metaclass may make __name__ raise or return a str subclass.
    try:
        return str.__str__(t.__name__)
    except Exception:
        return "<unnamed>"


def resolve_identity[C](resolver: IdentityResolver[C], credentials: C) -> Identity:
    """Resolve `credentials` with `resolver`, raising ResolverFailureError on failure."""
    name = _type_name(type(resolver))
    result: object = None
    raised: ResolverFailureError | None = None
    try:
        # Widened because resolvers may be untyped and return anything.
        result = cast(object, resolver.resolve(credentials))
    except Exception as exc:
        # The exception message may carry credentials, so only its type is reported.
        raised = ResolverFailureError(f"Resolver {name} raised {_type_name(type(exc))}.")
    # Raised outside the except block so the original exception isn't kept as __context__.
    if raised is not None:
        raise raised from None
    # type() rather than isinstance, which consults a resolver-controlled __class__.
    result_type = type(result)
    if issubclass(result_type, Identity):
        return cast(Identity, result)
    if issubclass(result_type, ResolutionFailure):
        try:
            error = ResolverFailureError(cast(ResolutionFailure, result).detail)
        except Exception:
            error = ResolverFailureError(f"Resolver {name} returned an invalid ResolutionFailure.")
        raise error from None
    raise ResolverFailureError(
        f"Resolver {name} returned {_type_name(result_type)}, not Identity or ResolutionFailure."
    ) from None


class SandboxResolver:
    """Returns one fixed Identity for any credentials. For sandboxes and tests."""

    def __init__(self, identity: Identity) -> None:
        self._identity = identity

    def resolve(self, credentials: object) -> Identity:
        """Return the configured Identity, ignoring `credentials`."""
        return self._identity
