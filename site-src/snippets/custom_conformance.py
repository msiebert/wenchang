from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import pytest

from wenchang.core import MemoryStore
from wenchang.identity import Identity, IdentityResolver, ResolutionFailure, ScopeGrant
from wenchang.scope import ScopePolicy
from wenchang.storage.memory import InMemoryStorage
from wenchang.testing import ResolverConformance, TransportConformance
from wenchang.transport import InProcessClient, TransportClient

POLICY = ScopePolicy({"org": frozenset({"admin", "owner"})})


class MyResolver:
    def resolve(self, credentials: str) -> Identity | ResolutionFailure:
        if credentials != "good-token":
            return ResolutionFailure("unknown token")
        return Identity(
            grants={"user": ScopeGrant("u-1", "owner"), "org": ScopeGrant("o-9", "admin")}
        )


class TestMyResolver(ResolverConformance[str]):
    @pytest.fixture
    def resolver(self) -> IdentityResolver[str]:
        return MyResolver()

    @pytest.fixture
    def valid_credentials(self) -> str:
        return "good-token"

    @pytest.fixture
    def invalid_credentials(self) -> str:
        return "bad-token"

    @pytest.fixture
    def policy(self) -> ScopePolicy:
        return POLICY

    @pytest.fixture
    def expected_scopes(self) -> frozenset[str]:
        return frozenset({"user", "org"})

    @pytest.fixture
    def known_roles(self) -> frozenset[str]:
        return frozenset({"owner", "admin", "member"})


class _Ticking:
    """A clock whose every call is strictly later than the last."""

    def __init__(self) -> None:
        self._n = 0

    def __call__(self) -> datetime:
        self._n += 1
        return datetime(2024, 1, 1, tzinfo=UTC) + timedelta(microseconds=self._n)


class TestMyClient(TransportConformance):
    @pytest.fixture
    def client(self) -> TransportClient:
        return InProcessClient(
            MemoryStore(
                InMemoryStorage(),
                clock=_Ticking(),
                max_file_bytes=256,
                index_max_bytes=4096,
                scope_priority=("user", "org"),
                list_page_size=2,
            )
        )

    @pytest.fixture
    def source(self) -> str:
        return "conformance"

    @pytest.fixture
    def scope_map(self) -> Mapping[str, str]:
        return {"user": "u-1", "org": "o-9"}

    @pytest.fixture
    def max_file_bytes(self) -> int:
        return 256

    @pytest.fixture
    def index_max_bytes(self) -> int:
        return 4096

    @pytest.fixture
    def scope_priority(self) -> tuple[str, ...]:
        return ("user", "org")

    @pytest.fixture
    def list_page_size(self) -> int:
        return 2
