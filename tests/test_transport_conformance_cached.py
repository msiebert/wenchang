"""Transport conformance run against InProcessClient over a MemoryStore with an
index cache.

Covers AIE-1293, US8.4. An autouse fixture turns any pytest.skip call inside an
inherited case into a failure.
"""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import NoReturn

import pytest

from wenchang.core import MemoryStore
from wenchang.index_cache import IndexCache, InMemoryIndexCache
from wenchang.storage.memory import InMemoryStorage
from wenchang.testing import TransportConformance
from wenchang.transport import InProcessClient, TransportClient

pytestmark = pytest.mark.unit

MAX_FILE_BYTES = 256
INDEX_MAX_BYTES = 4096
SCOPE_PRIORITY = ("user", "org")
LIST_PAGE_SIZE = 2


class _Ticking:
    """A clock returning a strictly later aware datetime on each call."""

    def __init__(self) -> None:
        self._n = 0

    def __call__(self) -> datetime:
        self._n += 1
        return datetime(2024, 1, 1, tzinfo=UTC) + timedelta(microseconds=self._n)


def _fail_on_skip(reason: str = "", **_: object) -> NoReturn:
    pytest.fail(f"conformance case skipped: {reason}")


class TestCachedInProcessClient(TransportConformance):
    """InProcessClient over a MemoryStore with an IndexCache passes every suite
    case, none skipped (AIE-1293, US8.4).
    """

    @pytest.fixture(autouse=True)
    def _no_skips(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Turns a pytest.skip call in a case into a failure (AIE-1293, US8.4)."""
        monkeypatch.setattr(pytest, "skip", _fail_on_skip)

    @pytest.fixture
    def client(self) -> TransportClient:
        cache = InMemoryIndexCache()
        return InProcessClient(
            MemoryStore(
                InMemoryStorage(),
                clock=_Ticking(),
                max_file_bytes=MAX_FILE_BYTES,
                index_max_bytes=INDEX_MAX_BYTES,
                scope_priority=SCOPE_PRIORITY,
                list_page_size=LIST_PAGE_SIZE,
                index_cache=IndexCache(get=cache.get, set=cache.set, ttl=timedelta(minutes=5)),
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
        return MAX_FILE_BYTES

    @pytest.fixture
    def index_max_bytes(self) -> int:
        return INDEX_MAX_BYTES

    @pytest.fixture
    def scope_priority(self) -> tuple[str, ...]:
        return SCOPE_PRIORITY

    @pytest.fixture
    def list_page_size(self) -> int:
        return LIST_PAGE_SIZE
