"""Reference run of the transport conformance suite against InProcessClient.

Covers AIE-1047, US1.1 and US1.5, and through the inherited suite methods
US3.1 through US3.5. pytest itself checks that the reference subclass
collects exactly the five baseline cases and skips none; a missing fixture
surfaces as a collection error (US1.5).
"""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import pytest

from wenchang.core import MemoryStore
from wenchang.storage.memory import InMemoryStorage
from wenchang.testing import TransportConformance
from wenchang.transport import InProcessClient, TransportClient

pytestmark = pytest.mark.unit

MAX_FILE_BYTES = 256
INDEX_MAX_BYTES = 4096
SCOPE_PRIORITY = ("user", "org")
LIST_PAGE_SIZE = 2

BASELINE_CASES = frozenset(
    {
        "test_client_satisfies_protocol",
        "test_write_then_read_round_trips",
        "test_returned_token_is_accepted",
        "test_read_absent_is_not_found",
        "test_oversize_write_is_rejected",
    }
)


class _Ticking:
    """A clock returning a strictly later aware datetime on each call."""

    def __init__(self) -> None:
        self._n = 0

    def __call__(self) -> datetime:
        self._n += 1
        return datetime(2024, 1, 1, tzinfo=UTC) + timedelta(microseconds=self._n)


class TestInProcessClient(TransportConformance):
    """InProcessClient over a fresh MemoryStore passes every baseline case, none skipped.

    AIE-1047, US1.1, US3.1, US3.2, US3.3, US3.4, US3.5.
    """

    @pytest.fixture
    def client(self) -> TransportClient:
        return InProcessClient(
            MemoryStore(
                InMemoryStorage(),
                clock=_Ticking(),
                max_file_bytes=MAX_FILE_BYTES,
                index_max_bytes=INDEX_MAX_BYTES,
                scope_priority=SCOPE_PRIORITY,
                list_page_size=LIST_PAGE_SIZE,
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


def test_ticking_clock_strictly_increases() -> None:
    """The reference clock stamps strictly increasing aware datetimes (AIE-1047, US1.1)."""
    clock = _Ticking()
    first, second = clock(), clock()

    assert first.utcoffset() is not None
    assert first < second


def test_suite_public_methods_are_exactly_the_five_baseline_cases() -> None:
    """The suite's public callables are exactly the five baseline cases (AIE-1047, US5.3)."""
    public = {
        name
        for name, value in vars(TransportConformance).items()
        if callable(value) and not name.startswith("_")
    }

    assert public == BASELINE_CASES
