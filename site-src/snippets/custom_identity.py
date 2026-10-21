from collections.abc import Mapping
from dataclasses import dataclass

from wenchang.identity import Identity, ResolutionFailure, ScopeGrant, resolve_identity
from wenchang.scope import ScopePolicy


@dataclass(frozen=True)
class Session:
    user_id: str
    project_id: str
    org_id: str
    org_role: str  # "member", "admin", or "owner"


class TokenResolver:
    """Maps a bearer token to an Identity. Must not raise."""

    def __init__(self, sessions: Mapping[str, Session]) -> None:
        self._sessions = sessions

    def resolve(self, credentials: str | None) -> Identity | ResolutionFailure:
        session = self._sessions.get(credentials or "")
        if session is None:
            return ResolutionFailure("Unknown or missing credential.")
        return Identity(
            grants={
                "user": ScopeGrant(session.user_id, "owner"),
                "project": ScopeGrant(session.project_id, "member"),
                "organization": ScopeGrant(session.org_id, session.org_role),
            }
        )


# Only admins and owners may write the organization scope; user and project are open.
policy = ScopePolicy({"organization": frozenset({"admin", "owner"})})

resolver = TokenResolver({"tok-ada": Session("u-ada", "p-checkout", "o-acme", "member")})
identity = resolve_identity(resolver, "tok-ada")
print(identity.scope_map)  # {'user': 'u-ada', 'project': 'p-checkout', 'organization': 'o-acme'}
print(policy.permitted_roles("organization"), policy.permitted_roles("user"))
