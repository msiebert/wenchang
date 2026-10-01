"""Reference runs of the resolver conformance suite.

Covers AIE-1039, US8.1 through US8.3, and through the inherited suite methods
US1.1, US2.1, US2.5, US2.6, US3.1, US3.3, US4.1, US5.1, US6.1, and US7.1
through US7.4.
"""

import inspect

import pytest

from wenchang.identity import (
    Identity,
    IdentityResolver,
    ResolutionFailure,
    SandboxResolver,
    ScopeGrant,
)
from wenchang.scope import ScopePolicy
from wenchang.testing import ResolverConformance

pytestmark = pytest.mark.unit

ADMIN_IDENTITY = Identity(
    grants={"user": ScopeGrant("u-1", "owner"), "org": ScopeGrant("o-9", "admin")}
)
MEMBER_IDENTITY = Identity(
    grants={"user": ScopeGrant("u-1", "owner"), "org": ScopeGrant("o-9", "member")}
)
# `team` is restricted but never granted, so the ungranted-scope test has a policy scope to check.
POLICY = ScopePolicy({"org": frozenset({"admin", "owner"}), "team": frozenset({"admin"})})
EXPECTED_SCOPES = frozenset({"user", "org"})
KNOWN_ROLES = frozenset({"owner", "admin", "member"})

VALID_TOKEN = "valid-token"
INVALID_TOKEN = "bogus-token"

CONTRACT_FIXTURES = frozenset(
    {
        "resolver",
        "valid_credentials",
        "invalid_credentials",
        "policy",
        "expected_scopes",
        "known_roles",
    }
)


class TokenResolver:
    """Resolves one known token to the reference identity and rejects everything else."""

    def resolve(self, credentials: str) -> Identity | ResolutionFailure:
        if credentials == VALID_TOKEN:
            return ADMIN_IDENTITY
        return ResolutionFailure("unknown token")


class TestSandboxResolverPermittedRole(ResolverConformance[object]):
    """SandboxResolver with role admin in org passes, invalid-credential tests skip.

    AIE-1039, US8.1, US2.6, US7.1.
    """

    @pytest.fixture
    def resolver(self) -> IdentityResolver[object]:
        return SandboxResolver(ADMIN_IDENTITY)

    @pytest.fixture
    def valid_credentials(self) -> object:
        return object()

    @pytest.fixture
    def invalid_credentials(self) -> object:
        pytest.skip("SandboxResolver accepts every credential")

    @pytest.fixture
    def policy(self) -> ScopePolicy:
        return POLICY

    @pytest.fixture
    def expected_scopes(self) -> frozenset[str]:
        return EXPECTED_SCOPES

    @pytest.fixture
    def known_roles(self) -> frozenset[str]:
        return KNOWN_ROLES


class TestSandboxResolverLackingRole(ResolverConformance[object]):
    """SandboxResolver with role member in org passes, invalid-credential tests skip.

    AIE-1039, US8.2, US2.6, US7.2.
    """

    @pytest.fixture
    def resolver(self) -> IdentityResolver[object]:
        return SandboxResolver(MEMBER_IDENTITY)

    @pytest.fixture
    def valid_credentials(self) -> object:
        return object()

    @pytest.fixture
    def invalid_credentials(self) -> object:
        pytest.skip("SandboxResolver accepts every credential")

    @pytest.fixture
    def policy(self) -> ScopePolicy:
        return POLICY

    @pytest.fixture
    def expected_scopes(self) -> frozenset[str]:
        return EXPECTED_SCOPES

    @pytest.fixture
    def known_roles(self) -> frozenset[str]:
        return KNOWN_ROLES


class TestTokenResolver(ResolverConformance[str]):
    """A token-lookup resolver passes every test with none skipped.

    AIE-1039, US8.3, US1.1, US2.1, US2.5, US3.1, US3.3, US4.1, US5.1, US6.1, US7.1, US7.3, US7.4.
    """

    @pytest.fixture
    def resolver(self) -> IdentityResolver[str]:
        return TokenResolver()

    @pytest.fixture
    def valid_credentials(self) -> str:
        return VALID_TOKEN

    @pytest.fixture
    def invalid_credentials(self) -> str:
        return INVALID_TOKEN

    @pytest.fixture
    def policy(self) -> ScopePolicy:
        return POLICY

    @pytest.fixture
    def expected_scopes(self) -> frozenset[str]:
        return EXPECTED_SCOPES

    @pytest.fixture
    def known_roles(self) -> frozenset[str]:
        return KNOWN_ROLES


def _suite_methods() -> dict[str, inspect.Signature]:
    return {
        name: inspect.signature(member)
        for name, member in vars(ResolverConformance).items()
        if name.startswith("test_") and callable(member)
    }


def _fixture_params(signature: inspect.Signature) -> set[str]:
    return {name for name in signature.parameters if name != "self"}


def test_token_resolver_accepts_only_the_known_token() -> None:
    """The local TokenResolver behaves as the reference run assumes (AIE-1039, US8.3)."""
    resolver = TokenResolver()

    assert resolver.resolve(VALID_TOKEN) == ADMIN_IDENTITY
    assert resolver.resolve(INVALID_TOKEN) == ResolutionFailure("unknown token")


def test_suite_methods_take_only_contract_fixtures() -> None:
    """Every suite method requests only the six contract fixtures (AIE-1039, FR-001)."""
    methods = _suite_methods()
    assert methods, "ResolverConformance defines no test_* methods"

    extra = {
        name: sorted(_fixture_params(sig) - CONTRACT_FIXTURES)
        for name, sig in methods.items()
        if _fixture_params(sig) - CONTRACT_FIXTURES
    }

    assert extra == {}


def test_exactly_three_suite_methods_take_invalid_credentials() -> None:
    """Exactly three suite methods take invalid_credentials (AIE-1039, US8.1, US2.6)."""
    takers = sorted(
        name for name, sig in _suite_methods().items() if "invalid_credentials" in sig.parameters
    )

    assert takers == [
        "test_invalid_credentials_raise_permanent_resolver_failure_error",
        "test_invalid_credentials_return_resolution_failure",
        "test_invalid_resolution_is_consistent",
    ]
