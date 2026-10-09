"""Thread-safety of InMemoryStorage (AIE-1060, US6.1 to US6.3, US6.6, US6.7).

The MCP adapter runs tool calls concurrently on worker threads, so the
in-memory fake must keep compare-and-swap and token uniqueness under
concurrency, as GCS does. The races are made deterministic: US6.1 and US6.3
slow the private object map's lookup so every thread reaches the version
check before any writes; US6.2 shrinks the interpreter switch interval.
"""

import sys
import threading
import time
from collections.abc import Callable, Iterator
from typing import cast

import pytest

from wenchang.storage import PreconditionFailedError
from wenchang.storage.memory import InMemoryStorage
from wenchang.version_token import VersionToken

pytestmark = pytest.mark.unit

THREADS = 8
KEY = "user/u-1/notes/today.md"


class _SlowDict(dict[str, object]):
    """A dict whose get sleeps after reading, widening any check-then-act window."""

    def get(self, key: str, default: object = None) -> object:  # type: ignore[override]
        value = super().get(key, default)
        time.sleep(0.005)
        return value


def _slow(storage: InMemoryStorage) -> None:
    # Deliberately reaches into the private map to make the race deterministic.
    slow = _SlowDict(storage._objects)  # pyright: ignore[reportPrivateUsage]
    storage._objects = slow  # pyright: ignore[reportPrivateUsage, reportAttributeAccessIssue]


_NOT_RUN: object = object()


def _race(count: int, attempt: Callable[[int], object]) -> list[object]:
    """Run attempt(i) on count threads released together; return results or exceptions."""
    barrier = threading.Barrier(count, timeout=30)
    results: list[object] = [_NOT_RUN] * count

    def run(i: int) -> None:
        barrier.wait()
        try:
            results[i] = attempt(i)
        except Exception as exc:
            results[i] = exc

    threads = [threading.Thread(target=run, args=(i,)) for i in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not any(t.is_alive() for t in threads)
    assert _NOT_RUN not in results
    return results


@pytest.fixture
def tiny_switch_interval() -> Iterator[None]:
    saved = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        yield
    finally:
        sys.setswitchinterval(saved)


def test_concurrent_create_has_one_winner() -> None:
    """Of concurrent put_if_version(expected=None) calls on one key, exactly
    one succeeds and the rest raise PreconditionFailedError (AIE-1060, US6.1).
    """
    storage = InMemoryStorage()
    _slow(storage)

    results = _race(THREADS, lambda i: storage.put_if_version(KEY, f"v{i}".encode(), {}, None))

    winners = [r for r in results if isinstance(r, str)]
    losers = [r for r in results if isinstance(r, PreconditionFailedError)]
    assert len(winners) == 1
    assert len(losers) == THREADS - 1


@pytest.mark.usefixtures("tiny_switch_interval")
def test_concurrent_puts_mint_distinct_tokens() -> None:
    """Concurrent put calls to distinct keys never mint the same token, over
    20 rounds at a tiny switch interval (AIE-1060, US6.2).
    """
    for _ in range(20):
        storage = InMemoryStorage()

        def puts(i: int, storage: InMemoryStorage = storage) -> list[VersionToken]:
            return [storage.put(f"k/{i}/{j}", b"x", {}) for j in range(50)]

        results = _race(THREADS, puts)

        tokens = [token for r in results for token in cast(list[VersionToken], r)]
        assert len(tokens) == THREADS * 50
        assert len(set(tokens)) == THREADS * 50


def test_concurrent_update_has_one_winner() -> None:
    """Of concurrent put_if_version(expected=v) calls, exactly one succeeds and
    the stored version is the one it returned (AIE-1060, US6.3).
    """
    storage = InMemoryStorage()
    v = storage.put(KEY, b"original", {})
    _slow(storage)

    results = _race(THREADS, lambda i: storage.put_if_version(KEY, f"v{i}".encode(), {}, v))

    winners = [r for r in results if isinstance(r, str)]
    losers = [r for r in results if isinstance(r, PreconditionFailedError)]
    assert len(winners) == 1
    assert len(losers) == THREADS - 1
    stored = storage.get(KEY)
    assert stored is not None
    assert stored.version == winners[0]


def test_concurrent_delete_has_one_winner() -> None:
    """Of concurrent delete_if_version(v) calls, exactly one deletes and the
    rest raise PreconditionFailedError (AIE-1060, US6.6).
    """
    storage = InMemoryStorage()
    v = storage.put(KEY, b"original", {})
    _slow(storage)

    results = _race(THREADS, lambda i: storage.delete_if_version(KEY, v))

    winners = [r for r in results if r is None]
    losers = [r for r in results if isinstance(r, PreconditionFailedError)]
    assert len(winners) == 1, results
    assert len(losers) == THREADS - 1, results
    assert storage.get(KEY) is None


@pytest.mark.usefixtures("tiny_switch_interval")
def test_list_page_during_concurrent_puts_never_raises() -> None:
    """list_page never fails while other threads put, over many listings at a
    tiny switch interval (AIE-1060, US6.7).
    """
    storage = InMemoryStorage()
    stop = threading.Event()
    errors: list[BaseException] = []

    def writer() -> None:
        i = 0
        while not stop.is_set():
            storage.put(f"p/{i}", b"x", {})
            i += 1

    def lister() -> None:
        try:
            for _ in range(300):
                storage.list_page("p/", None, 10_000)
        except BaseException as exc:
            errors.append(exc)

    writer_thread = threading.Thread(target=writer)
    writer_thread.start()
    listers = [threading.Thread(target=lister) for _ in range(4)]
    for t in listers:
        t.start()
    for t in listers:
        t.join(timeout=30)
    stop.set()
    writer_thread.join(timeout=30)

    assert not any(t.is_alive() for t in [writer_thread, *listers])
    assert errors == []
