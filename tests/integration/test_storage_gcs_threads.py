"""Thread-safety of one shared google.cloud.storage Client, Bucket, and
GcsStorage against a fake-gcs-server emulator (AIE-1316, AC1 to AC6).

The MCP adapter shares one client across worker threads. These tests stress
that sharing at a tiny interpreter switch interval and assert correctness only,
never timing. fake-gcs-server ignores ifGenerationMatch on DELETE, so no
one-winner concurrent delete is tested.
"""

import datetime
import re
import sys
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from google.auth.credentials import AnonymousCredentials, Credentials
from google.cloud.storage import Bucket, Client  # pyright: ignore[reportMissingTypeStubs]

from wenchang.core import MemoryStore
from wenchang.file_format import FileMetadata
from wenchang.storage import PreconditionFailedError
from wenchang.storage.gcs import GcsStorage
from wenchang.transport import InProcessClient
from wenchang.version_token import VersionToken

pytestmark = pytest.mark.integration

THREADS = 16
ROUNDS = 5
FRESH_CLIENTS = 10


@pytest.fixture
def tiny_switch_interval() -> Iterator[None]:
    saved = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        yield
    finally:
        sys.setswitchinterval(saved)


def _client(host: str, credentials: Credentials | None = None) -> Client:
    return Client(
        project="test",
        credentials=credentials or AnonymousCredentials(),
        client_options={"api_endpoint": host},
    )


def _cleanup(bucket: Bucket) -> None:
    try:
        for blob in bucket.list_blobs():  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            blob.delete()  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        bucket.delete()  # pyright: ignore[reportUnknownMemberType]
    except Exception:
        pass  # best-effort cleanup; the emulator's data is ephemeral anyway


@pytest.fixture
def bucket(storage_emulator_host: str) -> Iterator[Bucket]:
    client = _client(storage_emulator_host)
    try:
        created = client.create_bucket(f"wenchang-test-{uuid.uuid4().hex}")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        try:
            yield created  # pyright: ignore[reportUnknownVariableType]
        finally:
            _cleanup(created)  # pyright: ignore[reportUnknownArgumentType]
    finally:
        client.close()


def _run(count: int, worker: Callable[[int], object]) -> list[Any]:
    """Run worker(i) on count daemon threads released together by a barrier.

    Returns the results in thread order; asserts no thread hangs past one
    shared deadline and re-raises the first worker exception, keeping its
    traceback.
    """
    barrier = threading.Barrier(count, timeout=30)
    results: list[Any] = [None] * count
    errors: list[BaseException] = []

    def run(i: int) -> None:
        try:
            barrier.wait()
            results[i] = worker(i)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(i,), daemon=True) for i in range(count)]
    for t in threads:
        t.start()
    deadline = time.monotonic() + 60
    for t in threads:
        t.join(max(0.0, deadline - time.monotonic()))
    assert not any(t.is_alive() for t in threads)
    if len(errors) == 1:
        raise errors[0]
    if errors:
        raise BaseExceptionGroup("worker threads raised", errors)
    return results


def _race(
    attempt: Callable[[int], VersionToken],
) -> tuple[list[tuple[int, VersionToken]], list[int]]:
    """Run attempt(i) on THREADS threads; return (winners, loser indexes).

    Any exception other than PreconditionFailedError fails the test.
    """

    def worker(i: int) -> tuple[bool, VersionToken | None]:
        try:
            return True, attempt(i)
        except PreconditionFailedError:
            return False, None

    results = _run(THREADS, worker)
    winners = [(i, tok) for i, (won, tok) in enumerate(results) if won and tok is not None]
    losers = [i for i, (won, _) in enumerate(results) if not won]
    return winners, losers


@pytest.mark.usefixtures("tiny_switch_interval")
def test_mixed_operations_on_shared_storage_stay_isolated(bucket: Bucket) -> None:
    """16 threads sharing one GcsStorage run put/get/put_if_version/get/list_page
    on their own prefix; every read returns that thread's own bytes, metadata,
    and token, listings show exactly its keys, and deleting them removes them
    (AIE-1316, AC1).
    """
    storage = GcsStorage(bucket)
    run_id = uuid.uuid4().hex

    def worker(i: int) -> None:
        prefix = f"user/{run_id}-{i}/"
        keys: list[str] = []
        for r in range(ROUNDS):
            key = f"{prefix}k{r}.md"
            keys.append(key)
            data = f"t{i}-r{r}-a".encode()
            token = storage.put(key, data, {"owner": str(i), "round": str(r)})
            got = storage.get(key)
            assert got is not None
            assert got.data == data
            assert dict(got.metadata) == {"owner": str(i), "round": str(r)}
            assert got.version == token

            data2 = f"t{i}-r{r}-b".encode()
            token2 = storage.put_if_version(key, data2, {"owner": str(i), "round": "u"}, token)
            got2 = storage.get(key)
            assert got2 is not None
            assert got2.data == data2
            assert dict(got2.metadata) == {"owner": str(i), "round": "u"}
            assert got2.version == token2

            listed = storage.list_page(prefix, None, 1000)
            assert [o.key for o in listed] == sorted(keys)
            assert all(dict(o.metadata)["owner"] == str(i) for o in listed)
        for key in keys:
            current = storage.get(key)
            assert current is not None
            storage.delete_if_version(key, current.version)
            assert storage.get(key) is None
        assert storage.list_page(prefix, None, 1000) == []

    _run(THREADS, worker)


@pytest.mark.usefixtures("tiny_switch_interval")
def test_concurrent_create_has_exactly_one_winner(bucket: Bucket) -> None:
    """16 threads put_if_version(expected=None) on one new key: exactly one gets
    a token, the rest raise PreconditionFailedError, and the stored object is
    the winner's, over 5 rounds (AIE-1316, AC2). The one-winner property is
    enforced by the server (fake-gcs-server's conditional upload); the test
    checks that the shared client delivers each conditional request intact and
    maps the 412 correctly under concurrency.
    """
    storage = GcsStorage(bucket)
    run_id = uuid.uuid4().hex
    for r in range(ROUNDS):
        key = f"user/{run_id}/create-{r}.md"

        winners, losers = _race(
            lambda i, key=key: storage.put_if_version(key, f"w{i}".encode(), {}, None)
        )

        assert len(winners) == 1
        assert len(losers) == THREADS - 1
        winner_index, token = winners[0]
        stored = storage.get(key)
        assert stored is not None
        assert stored.data == f"w{winner_index}".encode()
        assert stored.version == token


@pytest.mark.usefixtures("tiny_switch_interval")
def test_concurrent_update_has_exactly_one_winner(bucket: Bucket) -> None:
    """16 threads put_if_version(expected=v) on one existing key: exactly one
    wins, the rest raise PreconditionFailedError, and the stored object is the
    winner's, over 5 rounds (AIE-1316, AC3).
    """
    storage = GcsStorage(bucket)
    run_id = uuid.uuid4().hex
    for r in range(ROUNDS):
        key = f"user/{run_id}/update-{r}.md"
        v = storage.put(key, b"original", {})

        winners, losers = _race(
            lambda i, key=key, v=v: storage.put_if_version(key, f"w{i}".encode(), {}, v)
        )

        assert len(winners) == 1
        assert len(losers) == THREADS - 1
        winner_index, token = winners[0]
        stored = storage.get(key)
        assert stored is not None
        assert stored.data == f"w{winner_index}".encode()
        assert stored.version == token


@pytest.mark.usefixtures("tiny_switch_interval")
def test_first_use_of_fresh_client_from_many_threads_succeeds(
    storage_emulator_host: str,
) -> None:
    """16 threads making their first calls through a client that has made no
    request all succeed and read back their own write, over 10 fresh clients;
    a smoke test, as the lazy-session race is benign (AIE-1316, AC4).
    """
    setup_client = _client(storage_emulator_host)
    bucket_name = f"wenchang-test-{uuid.uuid4().hex}"
    setup_bucket = setup_client.create_bucket(bucket_name)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    try:
        for trial in range(FRESH_CLIENTS):
            fresh = _client(storage_emulator_host)
            try:
                storage = GcsStorage(fresh.bucket(bucket_name))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]

                def worker(i: int, trial: int = trial, storage: GcsStorage = storage) -> None:
                    key = f"user/trial-{trial}/t{i}.md"
                    data = f"t{trial}-{i}".encode()
                    token = storage.put(key, data, {})
                    got = storage.get(key)
                    assert got is not None
                    assert got.data == data
                    assert got.version == token

                _run(THREADS, worker)
            finally:
                fresh.close()
    finally:
        try:
            _cleanup(setup_bucket)  # pyright: ignore[reportUnknownArgumentType]
        finally:
            setup_client.close()


@pytest.mark.usefixtures("tiny_switch_interval")
def test_concurrent_writes_through_memory_store_all_appear_in_index(bucket: Bucket) -> None:
    """16 threads write distinct files through InProcessClient and MemoryStore
    over a shared GcsStorage; the memory index then lists every file
    (AIE-1316, AC5).
    """
    client = InProcessClient(MemoryStore(GcsStorage(bucket)))
    user_id = f"u-{uuid.uuid4().hex}"
    now = datetime.datetime.now(datetime.UTC)
    metadata = FileMetadata(description="d", aliases=(), sources=frozenset({"t"}), last_updated=now)

    def worker(i: int) -> None:
        for r in range(ROUNDS):
            client.write_file(
                f"user/{user_id}/notes/t{i}-r{r}.md",
                f"- [stated] t{i} r{r}\n",
                metadata,
                None,
                source="threads",
            )

    _run(THREADS, worker)

    index = client.get_memory_index({"user": user_id})

    expected = {f"user/{user_id}/notes/t{i}-r{r}.md" for i in range(THREADS) for r in range(ROUNDS)}
    assert {entry.path for entry in index.entries} == expected
    assert index.capped == ()


class _AlwaysRefreshingCredentials(Credentials):
    """Credentials inside google-auth's refresh window on every request, so
    every request refreshes; records each applied Authorization header and the
    maximum number of refreshes in flight at once.
    """

    def __init__(self) -> None:
        super().__init__()  # pyright: ignore[reportUnknownMemberType]
        self._lock = threading.Lock()
        self.refreshes = 0
        self.inflight = 0
        self.max_inflight = 0
        self.headers: list[str | None] = []

    def refresh(self, request: Any) -> None:
        with self._lock:
            self.refreshes += 1
            n = self.refreshes
            self.inflight += 1
            self.max_inflight = max(self.max_inflight, self.inflight)
        try:
            time.sleep(0.01)
            self.token = f"tok-{n}"
            self.expiry = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
        finally:
            with self._lock:
                self.inflight -= 1

    def apply(self, headers: Any, token: str | None = None) -> None:
        super().apply(headers, token)  # pyright: ignore[reportUnknownMemberType]
        with self._lock:
            self.headers.append(headers.get("authorization"))


@pytest.mark.usefixtures("tiny_switch_interval")
def test_concurrent_credential_refresh_serves_valid_headers(storage_emulator_host: str) -> None:
    """With credentials that refresh on every request, 16 threads doing put
    then get through one shared GcsStorage raise nothing, read back their own
    writes, trigger several refreshes that overlap in time (more than one in flight at
    once), and every request carries a valid Bearer header (AIE-1316, AC6).
    """
    setup_client = _client(storage_emulator_host)
    shared: Client | None = None
    bucket_name = f"wenchang-test-{uuid.uuid4().hex}"
    setup_bucket = setup_client.create_bucket(bucket_name)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    creds = _AlwaysRefreshingCredentials()
    run_id = uuid.uuid4().hex

    def worker(i: int) -> None:
        for r in range(ROUNDS):
            key = f"user/{run_id}-{i}/k{r}.md"
            data = f"t{i}-r{r}".encode()
            token = storage.put(key, data, {})
            got = storage.get(key)
            assert got is not None
            assert got.data == data
            assert got.version == token

    try:
        shared = _client(storage_emulator_host, creds)
        storage = GcsStorage(shared.bucket(bucket_name))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
        _run(THREADS, worker)
    finally:
        try:
            _cleanup(setup_bucket)  # pyright: ignore[reportUnknownArgumentType]
        finally:
            setup_client.close()
            if shared is not None:
                shared.close()

    assert creds.refreshes > 1
    assert creds.max_inflight > 1
    assert creds.headers
    assert all(h is not None and re.fullmatch(r"Bearer tok-\d+", h) for h in creds.headers)
