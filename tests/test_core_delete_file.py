"""Tests for MemoryStore.delete_file (AIE-1037): version-guarded file
deletion, error ordering, and retry safety on precondition failure.
"""

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime

import pytest

from wenchang.core import MemoryStore
from wenchang.errors import (
    BackendUnavailableError,
    NotFoundError,
    NotFoundReason,
    TransientReason,
    VersionConflictError,
)
from wenchang.file_format import FileMetadata, metadata_to_map
from wenchang.storage import ListedObject, Storage, StoredObject
from wenchang.storage.memory import InMemoryStorage
from wenchang.version_token import VersionToken

pytestmark = pytest.mark.unit

VALID_PATH = "user/u_42/preferences/editor.md"

FIXED_CLOCK_TIME = datetime(2025, 3, 1, 12, 0, 0, tzinfo=UTC)


def _fixed_clock() -> datetime:
    return FIXED_CLOCK_TIME


def _metadata(
    description: str = "desc",
    aliases: tuple[str, ...] = ("a", "b"),
    sources: frozenset[str] = frozenset({"s1"}),
    last_updated: datetime = datetime(2024, 1, 1, tzinfo=UTC),
) -> FileMetadata:
    return FileMetadata(
        description=description,
        aliases=aliases,
        sources=sources,
        last_updated=last_updated,
    )


def _seed(storage: InMemoryStorage, path: str, body: str, meta: FileMetadata) -> VersionToken:
    return storage.put(path, body.encode("utf-8"), metadata_to_map(meta))


def _new_store(
    storage: Storage, *, clock: Callable[[], datetime] | None = _fixed_clock
) -> MemoryStore:
    """Build a MemoryStore, defaulting to a fixed clock unless clock=None."""
    if clock is None:
        return MemoryStore(storage)
    return MemoryStore(storage, clock=clock)


def _fail_on_any_call(_name: str) -> None:
    pytest.fail("storage should not have been consulted")


class _NeverCalledStorage:
    """A Storage stub that fails the test if any method is called."""

    def get(self, key: str) -> StoredObject | None:
        _fail_on_any_call("get")
        raise AssertionError("unreachable")

    def put(self, key: str, data: bytes, metadata: Mapping[str, str]) -> VersionToken:
        _fail_on_any_call("put")
        raise AssertionError("unreachable")

    def put_if_version(
        self,
        key: str,
        data: bytes,
        metadata: Mapping[str, str],
        expected: VersionToken | None,
    ) -> VersionToken:
        _fail_on_any_call("put_if_version")
        raise AssertionError("unreachable")

    def list_page(self, prefix: str, start_after: str | None, limit: int) -> Sequence[ListedObject]:
        _fail_on_any_call("list_page")
        raise AssertionError("unreachable")

    def delete_if_version(self, key: str, expected: VersionToken) -> None:
        _fail_on_any_call("delete_if_version")
        raise AssertionError("unreachable")


class _StubStorage:
    """Hand-written Storage stub that records calls and can raise on demand."""

    def __init__(
        self,
        get_result: StoredObject | None = None,
        get_raises: BaseException | None = None,
        delete_if_version_raises: BaseException | None = None,
    ) -> None:
        self._get_result = get_result
        self._get_raises = get_raises
        self._delete_if_version_raises = delete_if_version_raises
        self.get_calls: list[str] = []
        self.delete_if_version_calls: list[tuple[str, VersionToken]] = []

    def get(self, key: str) -> StoredObject | None:
        self.get_calls.append(key)
        if self._get_raises is not None:
            raise self._get_raises
        return self._get_result

    def put(self, key: str, data: bytes, metadata: Mapping[str, str]) -> VersionToken:
        raise NotImplementedError("not exercised by these tests")

    def put_if_version(
        self,
        key: str,
        data: bytes,
        metadata: Mapping[str, str],
        expected: VersionToken | None,
    ) -> VersionToken:
        raise NotImplementedError("not exercised by these tests")

    def list_page(self, prefix: str, start_after: str | None, limit: int) -> Sequence[ListedObject]:
        raise NotImplementedError("not exercised by these tests")

    def delete_if_version(self, key: str, expected: VersionToken) -> None:
        self.delete_if_version_calls.append((key, expected))
        if self._delete_if_version_raises is not None:
            raise self._delete_if_version_raises
        return None


# --- US1: delete at current version -------------------------------------------


def test_delete_file_at_current_version_removes_file_from_read_and_list() -> None:
    """Deleting at the current version returns None, a subsequent read_file
    raises NotFoundError(FILE_ABSENT), and list_prefix no longer returns the
    file (AIE-1037, US1.1).
    """
    storage = InMemoryStorage()
    _seed(storage, VALID_PATH, "- [stated] a\n", _metadata())
    store = _new_store(storage)
    before = store.read_file(VALID_PATH)

    result = store.delete_file(VALID_PATH, before.version)

    assert result is None

    with pytest.raises(NotFoundError) as excinfo:
        store.read_file(VALID_PATH)
    assert excinfo.value.reason is NotFoundReason.FILE_ABSENT

    page = store.list_prefix("user/u_42/preferences/")
    assert VALID_PATH not in [entry.path for entry in page.entries]


def test_delete_file_leaves_other_file_under_same_prefix_unchanged() -> None:
    """Given two files under one prefix, deleting one leaves the other's
    content, metadata, and version unchanged (AIE-1037, US1.2).
    """
    storage = InMemoryStorage()
    other_path = "user/u_42/preferences/other.md"
    meta_a = _metadata(sources=frozenset({"a"}))
    meta_b = _metadata(sources=frozenset({"b"}))
    _seed(storage, VALID_PATH, "- [stated] a\n", meta_a)
    _seed(storage, other_path, "- [stated] b\n", meta_b)
    store = _new_store(storage)
    before_a = store.read_file(VALID_PATH)
    before_b = store.read_file(other_path)

    store.delete_file(VALID_PATH, before_a.version)

    after_b = store.read_file(other_path)
    assert after_b.content == before_b.content
    assert after_b.metadata == before_b.metadata
    assert after_b.version == before_b.version


def test_delete_file_then_write_file_with_none_recreates_it() -> None:
    """After a file is deleted, write_file(path, ..., None) succeeds in
    creating it again (AIE-1037, US1.3).
    """
    storage = InMemoryStorage()
    _seed(storage, VALID_PATH, "- [stated] a\n", _metadata())
    store = _new_store(storage)
    before = store.read_file(VALID_PATH)

    store.delete_file(VALID_PATH, before.version)

    recreated = store.write_file(VALID_PATH, "- [stated] new\n", _metadata(), None, source="chat")

    assert recreated.content == "- [stated] new\n"
    reread = store.read_file(VALID_PATH)
    assert reread.content == "- [stated] new\n"


# --- US2: stale token, retry safety, and races --------------------------------


def test_delete_file_stale_token_raises_version_conflict_and_leaves_file() -> None:
    """A caller holding a stale version gets VersionConflictError carrying
    the current content and version; the file is unchanged (AIE-1037, US2.1).
    """
    storage = InMemoryStorage()
    meta = _metadata()
    _seed(storage, VALID_PATH, "- [stated] a\n", meta)
    store = _new_store(storage)
    v1 = store.read_file(VALID_PATH).version

    v2 = storage.put(VALID_PATH, b"- [stated] a\n- [observed] other\n", metadata_to_map(meta))
    assert v2 != v1

    with pytest.raises(VersionConflictError) as excinfo:
        store.delete_file(VALID_PATH, v1)

    assert excinfo.value.path == VALID_PATH
    assert excinfo.value.content == "- [stated] a\n- [observed] other\n"
    assert excinfo.value.version == v2

    after = store.read_file(VALID_PATH)
    assert after.content == "- [stated] a\n- [observed] other\n"
    assert after.version == v2


def test_delete_file_identical_retry_after_success_raises_file_absent() -> None:
    """A successful delete_file followed by an identical retry raises
    NotFoundError(FILE_ABSENT) (AIE-1037, US2.2).
    """
    storage = InMemoryStorage()
    _seed(storage, VALID_PATH, "- [stated] a\n", _metadata())
    store = _new_store(storage)
    before = store.read_file(VALID_PATH)

    store.delete_file(VALID_PATH, before.version)

    with pytest.raises(NotFoundError) as excinfo:
        store.delete_file(VALID_PATH, before.version)

    assert excinfo.value.reason is NotFoundReason.FILE_ABSENT
    assert excinfo.value.path == VALID_PATH


class _RacingWriteStorage:
    """Wraps InMemoryStorage, injecting a concurrent write before
    delete_if_version, to model a second writer landing between
    delete_file's version check and its conditional delete (AIE-1037,
    US2.3).
    """

    def __init__(
        self,
        inner: InMemoryStorage,
        race_content: str,
        race_metadata: Mapping[str, str],
    ) -> None:
        self._inner = inner
        self._race_content = race_content
        self._race_metadata = race_metadata
        self.delete_if_version_calls = 0
        self.race_version: VersionToken | None = None

    def get(self, key: str) -> StoredObject | None:
        return self._inner.get(key)

    def put(self, key: str, data: bytes, metadata: Mapping[str, str]) -> VersionToken:
        return self._inner.put(key, data, metadata)

    def put_if_version(
        self,
        key: str,
        data: bytes,
        metadata: Mapping[str, str],
        expected: VersionToken | None,
    ) -> VersionToken:
        return self._inner.put_if_version(key, data, metadata, expected)

    def list_page(self, prefix: str, start_after: str | None, limit: int) -> Sequence[ListedObject]:
        return self._inner.list_page(prefix, start_after, limit)

    def delete_if_version(self, key: str, expected: VersionToken) -> None:
        self.delete_if_version_calls += 1
        self.race_version = self._inner.put(
            key, self._race_content.encode("utf-8"), self._race_metadata
        )
        self._inner.delete_if_version(key, expected)


def test_delete_file_race_before_delete_raises_conflict_with_content_after_race() -> None:
    """A write landing between delete_file's version check and its
    conditional delete causes VersionConflictError carrying the content and
    version current after that write; the file still exists (AIE-1037,
    US2.3).
    """
    storage = InMemoryStorage()
    meta = _metadata()
    _seed(storage, VALID_PATH, "- [stated] a\n", meta)
    wrapped = _RacingWriteStorage(
        storage, "- [stated] a\n- [observed] raced\n", metadata_to_map(meta)
    )
    store = _new_store(wrapped)
    before = store.read_file(VALID_PATH)

    with pytest.raises(VersionConflictError) as excinfo:
        store.delete_file(VALID_PATH, before.version)

    assert excinfo.value.content == "- [stated] a\n- [observed] raced\n"
    assert excinfo.value.version == wrapped.race_version

    still_there = store.read_file(VALID_PATH)
    assert still_there.content == "- [stated] a\n- [observed] raced\n"


class _DeletableStorage(InMemoryStorage):
    """InMemoryStorage plus a delete primitive, for simulating a delete
    landing mid-delete (AIE-1037, US2.4).
    """

    def delete(self, key: str) -> None:
        self._objects.pop(key, None)


class _DeleteAgainBeforeDeleteIfVersionStorage:
    """Wraps a _DeletableStorage; deletes the object before delegating to
    delete_if_version, so the retry's re-read finds nothing, simulating a
    second delete landing between delete_file's version check and its
    conditional delete (AIE-1037, US2.4).
    """

    def __init__(self, inner: _DeletableStorage) -> None:
        self._inner = inner
        self.delete_if_version_calls = 0

    def get(self, key: str) -> StoredObject | None:
        return self._inner.get(key)

    def put(self, key: str, data: bytes, metadata: Mapping[str, str]) -> VersionToken:
        return self._inner.put(key, data, metadata)

    def put_if_version(
        self,
        key: str,
        data: bytes,
        metadata: Mapping[str, str],
        expected: VersionToken | None,
    ) -> VersionToken:
        return self._inner.put_if_version(key, data, metadata, expected)

    def list_page(self, prefix: str, start_after: str | None, limit: int) -> Sequence[ListedObject]:
        return self._inner.list_page(prefix, start_after, limit)

    def delete_if_version(self, key: str, expected: VersionToken) -> None:
        self.delete_if_version_calls += 1
        self._inner.delete(key)
        self._inner.delete_if_version(key, expected)


def test_delete_file_deleted_mid_delete_raises_file_absent() -> None:
    """A precondition failure whose re-read finds the object gone raises
    NotFoundError with reason FILE_ABSENT (AIE-1037, US2.4).
    """
    storage = _DeletableStorage()
    _seed(storage, VALID_PATH, "- [stated] a\n", _metadata())
    wrapped = _DeleteAgainBeforeDeleteIfVersionStorage(storage)
    store = _new_store(wrapped)
    before = store.read_file(VALID_PATH)

    with pytest.raises(NotFoundError) as excinfo:
        store.delete_file(VALID_PATH, before.version)

    assert excinfo.value.reason is NotFoundReason.FILE_ABSENT
    assert excinfo.value.path == VALID_PATH


# --- US3: validation and errors -----------------------------------------------


MALFORMED_PATHS = (
    "",
    "a/b.md",
    "user/u/a/b.txt",
    "user//a/b.md",
)


@pytest.mark.parametrize("path", MALFORMED_PATHS)
def test_delete_file_malformed_path_raises_invalid_path_without_storage(path: str) -> None:
    """A malformed path raises NotFoundError with reason INVALID_PATH and
    never consults storage (AIE-1037, US3.1).
    """
    store = _new_store(_NeverCalledStorage())

    with pytest.raises(NotFoundError) as excinfo:
        store.delete_file(path, VersionToken("v1"))

    assert excinfo.value.reason is NotFoundReason.INVALID_PATH
    assert excinfo.value.path == path


def test_delete_file_no_file_raises_file_absent() -> None:
    """A well-formed path with no object raises NotFoundError with reason
    FILE_ABSENT (AIE-1037, US3.2).
    """
    storage = InMemoryStorage()
    store = _new_store(storage)

    with pytest.raises(NotFoundError) as excinfo:
        store.delete_file(VALID_PATH, VersionToken("v1"))

    assert excinfo.value.reason is NotFoundReason.FILE_ABSENT
    assert excinfo.value.path == VALID_PATH


def test_delete_file_propagates_backend_unavailable_from_get() -> None:
    """A BackendUnavailableError raised by storage.get() propagates
    unwrapped (AIE-1037, US3.3).
    """
    error = BackendUnavailableError(TransientReason.UNAVAILABLE)
    stub = _StubStorage(get_raises=error)
    store = _new_store(stub)

    with pytest.raises(BackendUnavailableError) as excinfo:
        store.delete_file(VALID_PATH, VersionToken("v1"))

    assert excinfo.value is error


def test_delete_file_propagates_backend_unavailable_from_delete_if_version() -> None:
    """A BackendUnavailableError raised by storage.delete_if_version()
    propagates unwrapped (AIE-1037, US3.3).
    """
    error = BackendUnavailableError(TransientReason.TIMEOUT)
    v1 = VersionToken("v1")
    stub = _StubStorage(
        get_result=StoredObject(
            data=b"- [stated] a\n",
            metadata=metadata_to_map(_metadata()),
            version=v1,
        ),
        delete_if_version_raises=error,
    )
    store = _new_store(stub)

    with pytest.raises(BackendUnavailableError) as excinfo:
        store.delete_file(VALID_PATH, v1)

    assert excinfo.value is error


def test_delete_file_with_corrupt_metadata_still_deletes() -> None:
    """A file whose stored metadata is corrupt (would raise
    MetadataFormatError if parsed) is still deleted successfully, because
    delete_file does not parse metadata (AIE-1037).
    """
    storage = InMemoryStorage()
    bad_map = dict(metadata_to_map(_metadata()))
    del bad_map["description"]
    token = storage.put(VALID_PATH, b"- [stated] a\n", bad_map)
    store = _new_store(storage)

    result = store.delete_file(VALID_PATH, token)

    assert result is None
    assert storage.get(VALID_PATH) is None
