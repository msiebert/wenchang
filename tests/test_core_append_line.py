"""Tests for MemoryStore.append_line (AIE-1036): version-guarded single-line
append, metadata stamping, retry safety on precondition failure, and
validation/error ordering.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

import pytest

from wenchang.core import MemoryFile, MemoryStore
from wenchang.errors import (
    BackendUnavailableError,
    NotFoundError,
    NotFoundReason,
    OversizeWriteError,
    TransientReason,
    VersionConflictError,
)
from wenchang.file_format import FileMetadata, MetadataFormatError, metadata_to_map
from wenchang.storage import ListedObject, PreconditionFailedError, Storage, StoredObject
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


def _new_store_with_limit(
    storage: Storage, *, max_file_bytes: int, clock: Callable[[], datetime] = _fixed_clock
) -> MemoryStore:
    return MemoryStore(storage, max_file_bytes=max_file_bytes, clock=clock)


class _StubStorage:
    """Hand-written Storage stub that records calls and can raise on demand."""

    def __init__(
        self,
        get_result: StoredObject | None = None,
        get_raises: BaseException | None = None,
        put_if_version_raises: BaseException | None = None,
    ) -> None:
        self._get_result = get_result
        self._get_raises = get_raises
        self._put_if_version_raises = put_if_version_raises
        self.get_calls: list[str] = []
        self.put_if_version_calls: list[
            tuple[str, bytes, Mapping[str, str], VersionToken | None]
        ] = []

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
        self.put_if_version_calls.append((key, data, metadata, expected))
        if self._put_if_version_raises is not None:
            raise self._put_if_version_raises
        raise NotImplementedError("not exercised by these tests")

    def list_page(self, prefix: str, start_after: str | None, limit: int) -> Sequence[ListedObject]:
        raise NotImplementedError("not exercised by these tests")

    def delete_if_version(self, key: str, expected: VersionToken) -> None:
        raise NotImplementedError("not exercised by these tests")


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


# --- US1: append at current version ------------------------------------------


def test_append_line_appends_to_trailing_newline_content_and_read_file_agrees() -> None:
    """Appending to content ending in a newline produces the concatenated
    content and a new version distinct from the original, which read_file
    also sees afterwards (AIE-1036, US1.1).
    """
    storage = InMemoryStorage()
    _seed(storage, VALID_PATH, "- [stated] a\n", _metadata())
    store = _new_store(storage)
    before = store.read_file(VALID_PATH)

    result = store.append_line(VALID_PATH, "- [observed] b", before.version, source="chat")

    assert result.content == "- [stated] a\n- [observed] b\n"
    assert result.version != before.version

    reread = store.read_file(VALID_PATH)
    assert reread.content == result.content
    assert reread.version == result.version


def test_append_line_inserts_separator_when_content_lacks_trailing_newline() -> None:
    """Content with no trailing newline gets one inserted before the new
    line, so the existing last line is not extended (AIE-1036, US1.2).
    """
    storage = InMemoryStorage()
    _seed(storage, VALID_PATH, "- [stated] a", _metadata())
    store = _new_store(storage)
    before = store.read_file(VALID_PATH)

    result = store.append_line(VALID_PATH, "- [observed] b", before.version, source="chat")

    assert result.content == "- [stated] a\n- [observed] b\n"


def test_append_line_on_empty_content_is_exactly_the_line() -> None:
    """Empty content becomes exactly the line plus a trailing newline
    (AIE-1036, US1.3).
    """
    storage = InMemoryStorage()
    _seed(storage, VALID_PATH, "", _metadata())
    store = _new_store(storage)
    before = store.read_file(VALID_PATH)

    result = store.append_line(VALID_PATH, "- [stated] x", before.version, source="chat")

    assert result.content == "- [stated] x\n"


def test_append_line_preserves_non_fact_lines_and_blank_lines() -> None:
    """Content containing headings and blank lines is preserved byte for
    byte, with the new line following it (AIE-1036, US1.4).
    """
    storage = InMemoryStorage()
    body = "# Heading\n\n- [stated] existing\n\n"
    _seed(storage, VALID_PATH, body, _metadata())
    store = _new_store(storage)
    before = store.read_file(VALID_PATH)

    result = store.append_line(VALID_PATH, "- [observed] new", before.version, source="chat")

    assert result.content == body + "- [observed] new\n"


def test_append_line_stamps_sources_union_and_clock_leaving_rest_unchanged() -> None:
    """The stamped metadata gains the given source in sources, sets
    last_updated to the store clock's value, and leaves description and
    aliases unchanged, for both the returned and reread metadata (AIE-1036,
    US1.5).
    """
    storage = InMemoryStorage()
    meta = _metadata(
        description="d",
        aliases=("x", "y"),
        sources=frozenset({"cli"}),
        last_updated=datetime(2020, 1, 1, tzinfo=UTC),
    )
    _seed(storage, VALID_PATH, "- [stated] a\n", meta)
    store = _new_store(storage, clock=_fixed_clock)
    before = store.read_file(VALID_PATH)

    result = store.append_line(VALID_PATH, "- [observed] b", before.version, source="chat")

    assert result.metadata.sources == frozenset({"cli", "chat"})
    assert result.metadata.last_updated == FIXED_CLOCK_TIME
    assert result.metadata.description == "d"
    assert result.metadata.aliases == ("x", "y")

    reread = store.read_file(VALID_PATH)
    assert reread.metadata == result.metadata


def test_append_line_same_line_appended_twice_appears_twice() -> None:
    """Appending the same line at V then at the resulting V2 leaves it
    present twice; deliberate repeats are allowed (AIE-1036, US1.6).
    """
    storage = InMemoryStorage()
    _seed(storage, VALID_PATH, "- [stated] a\n", _metadata())
    store = _new_store(storage)
    before = store.read_file(VALID_PATH)

    first = store.append_line(VALID_PATH, "- [observed] b", before.version, source="chat")
    second = store.append_line(VALID_PATH, "- [observed] b", first.version, source="chat")

    assert second.content == "- [stated] a\n- [observed] b\n- [observed] b\n"
    assert second.content.count("- [observed] b") == 2


def test_append_line_unicode_and_fact_like_markdown_round_trips_exactly() -> None:
    """A line containing unicode text and fact-like markdown round-trips
    byte for byte (AIE-1036, US1.7).
    """
    storage = InMemoryStorage()
    _seed(storage, VALID_PATH, "- [stated] a\n", _metadata())
    store = _new_store(storage)
    before = store.read_file(VALID_PATH)
    line = "- [stated] café ✓ looks like - [observed] x"

    result = store.append_line(VALID_PATH, line, before.version, source="chat")

    assert result.content == "- [stated] a\n" + line + "\n"


# --- US2: stale token and retry safety ---------------------------------------


def test_append_line_stale_token_raises_version_conflict_with_current_content() -> None:
    """A caller holding a stale version gets VersionConflictError carrying
    the current content and version; the file is unchanged (AIE-1036,
    US2.1).
    """
    storage = InMemoryStorage()
    meta = _metadata()
    _seed(storage, VALID_PATH, "- [stated] a\n", meta)
    store = _new_store(storage)
    v1 = store.read_file(VALID_PATH).version

    v2 = storage.put(VALID_PATH, b"- [stated] a\n- [observed] other\n", metadata_to_map(meta))
    assert v2 != v1

    with pytest.raises(VersionConflictError) as excinfo:
        store.append_line(VALID_PATH, "- [observed] b", v1, source="chat")

    assert excinfo.value.path == VALID_PATH
    assert excinfo.value.content == "- [stated] a\n- [observed] other\n"
    assert excinfo.value.version == v2

    after = store.read_file(VALID_PATH)
    assert after.content == "- [stated] a\n- [observed] other\n"
    assert after.version == v2


def test_append_line_identical_retry_at_stale_version_conflicts_line_appears_once() -> None:
    """A successful append followed by an identical retry with the same
    (now stale) version raises VersionConflictError whose content contains
    the line exactly once, and the file is unchanged by the retry
    (AIE-1036, US2.2).
    """
    storage = InMemoryStorage()
    _seed(storage, VALID_PATH, "- [stated] a\n", _metadata())
    store = _new_store(storage)
    v1 = store.read_file(VALID_PATH).version

    first = store.append_line(VALID_PATH, "- [observed] b", v1, source="chat")

    with pytest.raises(VersionConflictError) as excinfo:
        store.append_line(VALID_PATH, "- [observed] b", v1, source="chat")

    assert excinfo.value.content.count("- [observed] b") == 1
    assert excinfo.value.version == first.version

    after = store.read_file(VALID_PATH)
    assert after.content == first.content
    assert after.version == first.version


def test_append_line_two_callers_same_version_second_conflicts_then_retry_succeeds() -> None:
    """Two callers holding the same version append different lines: the
    first succeeds, the second gets VersionConflictError whose content
    includes the first's line, and retrying with the error's version
    succeeds with both lines present exactly once (AIE-1036, US2.3).
    """
    storage = InMemoryStorage()
    _seed(storage, VALID_PATH, "- [stated] a\n", _metadata())
    store = _new_store(storage)
    v = store.read_file(VALID_PATH).version

    first = store.append_line(VALID_PATH, "- [observed] first", v, source="chat")

    with pytest.raises(VersionConflictError) as excinfo:
        store.append_line(VALID_PATH, "- [observed] second", v, source="chat")

    assert "- [observed] first" in excinfo.value.content
    assert excinfo.value.version == first.version

    retried = store.append_line(
        VALID_PATH, "- [observed] second", excinfo.value.version, source="chat"
    )

    assert retried.content.count("- [observed] first") == 1
    assert retried.content.count("- [observed] second") == 1


class _RacingPutStorage:
    """Wraps InMemoryStorage, injecting a concurrent put before
    put_if_version, to model a second writer landing between append_line's
    get() and its put_if_version() (AIE-1036, US2.4).
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
        self.put_if_version_calls = 0
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
        self.put_if_version_calls += 1
        if self.put_if_version_calls == 1:
            self.race_version = self._inner.put(
                key, self._race_content.encode("utf-8"), self._race_metadata
            )
        return self._inner.put_if_version(key, data, metadata, expected)

    def list_page(self, prefix: str, start_after: str | None, limit: int) -> Sequence[ListedObject]:
        return self._inner.list_page(prefix, start_after, limit)

    def delete_if_version(self, key: str, expected: VersionToken) -> None:
        self._inner.delete_if_version(key, expected)


def test_append_line_race_before_put_raises_conflict_and_does_not_retry_write() -> None:
    """A write landing between append_line's read and its conditional
    write causes VersionConflictError carrying the content and version
    current after that write, with no second write attempted (AIE-1036,
    US2.4).
    """
    storage = InMemoryStorage()
    meta = _metadata()
    _seed(storage, VALID_PATH, "- [stated] a\n", meta)
    wrapped = _RacingPutStorage(
        storage, "- [stated] a\n- [observed] raced\n", metadata_to_map(meta)
    )
    store = _new_store(wrapped)
    before = store.read_file(VALID_PATH)

    with pytest.raises(VersionConflictError) as excinfo:
        store.append_line(VALID_PATH, "- [observed] mine", before.version, source="chat")

    assert excinfo.value.content == "- [stated] a\n- [observed] raced\n"
    assert excinfo.value.version == wrapped.race_version
    assert wrapped.put_if_version_calls == 1


class _OwnWriteLandsThenPreconditionFailsStorage:
    """Wraps InMemoryStorage; put_if_version performs the real write, then
    raises PreconditionFailedError, simulating a lost response followed by
    a retried 412 (AIE-1036, US2.5).
    """

    def __init__(self, inner: InMemoryStorage) -> None:
        self._inner = inner
        self.put_if_version_calls = 0

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
        self.put_if_version_calls += 1
        self._inner.put_if_version(key, data, metadata, expected)
        raise PreconditionFailedError(key)

    def list_page(self, prefix: str, start_after: str | None, limit: int) -> Sequence[ListedObject]:
        return self._inner.list_page(prefix, start_after, limit)

    def delete_if_version(self, key: str, expected: VersionToken) -> None:
        self._inner.delete_if_version(key, expected)


def test_append_line_own_write_lands_then_precondition_fails_returns_success() -> None:
    """When put_if_version's own write actually lands but then raises
    PreconditionFailedError (a backend-level retry of a lost response),
    append_line re-reads, finds the stored content and metadata equal what
    it tried to write, and returns success with the stored version rather
    than appending again (AIE-1036, US2.5).
    """
    storage = InMemoryStorage()
    _seed(storage, VALID_PATH, "- [stated] a\n", _metadata())
    wrapped = _OwnWriteLandsThenPreconditionFailsStorage(storage)
    store = _new_store(wrapped)
    before = store.read_file(VALID_PATH)

    result = store.append_line(VALID_PATH, "- [observed] b", before.version, source="chat")

    assert result.content == "- [stated] a\n- [observed] b\n"
    assert result.content.count("- [observed] b") == 1
    assert wrapped.put_if_version_calls == 1

    reread = store.read_file(VALID_PATH)
    assert reread.content == result.content
    assert reread.version == result.version


class _DeletableStorage(InMemoryStorage):
    """InMemoryStorage plus a delete primitive, for simulating a delete
    landing mid-retry (AIE-1036, US2.5b).
    """

    def delete(self, key: str) -> None:
        self._objects.pop(key, None)


class _DeleteThenPreconditionFailsStorage:
    """Wraps a _DeletableStorage; put_if_version deletes the object and
    then raises PreconditionFailedError, so the retry's re-read finds
    nothing (AIE-1036, US2.5b).
    """

    def __init__(self, inner: _DeletableStorage) -> None:
        self._inner = inner
        self.put_if_version_calls = 0

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
        self.put_if_version_calls += 1
        self._inner.delete(key)
        raise PreconditionFailedError(key)

    def list_page(self, prefix: str, start_after: str | None, limit: int) -> Sequence[ListedObject]:
        return self._inner.list_page(prefix, start_after, limit)

    def delete_if_version(self, key: str, expected: VersionToken) -> None:
        self._inner.delete_if_version(key, expected)


def test_append_line_deleted_mid_retry_raises_file_absent() -> None:
    """A precondition failure whose re-read finds the object gone raises
    NotFoundError with reason FILE_ABSENT (AIE-1036, US2.5b).
    """
    storage = _DeletableStorage()
    _seed(storage, VALID_PATH, "- [stated] a\n", _metadata())
    wrapped = _DeleteThenPreconditionFailsStorage(storage)
    store = _new_store(wrapped)
    before = store.read_file(VALID_PATH)

    with pytest.raises(NotFoundError) as excinfo:
        store.append_line(VALID_PATH, "- [observed] b", before.version, source="chat")

    assert excinfo.value.reason is NotFoundReason.FILE_ABSENT
    assert excinfo.value.path == VALID_PATH


# --- US3: validation and errors ----------------------------------------------


MALFORMED_PATHS = (
    "",
    "a/b.md",
    "user/u/a/b.txt",
    "user//a/b.md",
)


@pytest.mark.parametrize("path", MALFORMED_PATHS)
def test_append_line_malformed_path_raises_invalid_path_without_storage(path: str) -> None:
    """A malformed path raises NotFoundError with reason INVALID_PATH and
    never consults storage (AIE-1036, US3.1).
    """
    store = _new_store(_NeverCalledStorage())

    with pytest.raises(NotFoundError) as excinfo:
        store.append_line(path, "- [stated] x", VersionToken("v1"), source="chat")

    assert excinfo.value.reason is NotFoundReason.INVALID_PATH
    assert excinfo.value.path == path


def test_append_line_no_file_raises_file_absent_and_creates_nothing() -> None:
    """A well-formed path with no object raises NotFoundError with reason
    FILE_ABSENT and creates nothing (AIE-1036, US3.2).
    """
    storage = InMemoryStorage()
    store = _new_store(storage)

    with pytest.raises(NotFoundError) as excinfo:
        store.append_line(VALID_PATH, "- [stated] x", VersionToken("v1"), source="chat")

    assert excinfo.value.reason is NotFoundReason.FILE_ABSENT
    assert storage.get(VALID_PATH) is None


@pytest.mark.parametrize(
    "line",
    [
        "",
        "plain text",
        "- [guess] x",
        "- [stated] ",
        "- [stated] a\n- [stated] b",
        "- [stated] a\n",
    ],
)
def test_append_line_malformed_line_raises_value_error_without_storage(line: str) -> None:
    """A line that does not parse as exactly one fact line raises
    ValueError without consulting storage (AIE-1036, US3.3).
    """
    store = _new_store(_NeverCalledStorage())

    with pytest.raises(ValueError):
        store.append_line(VALID_PATH, line, VersionToken("v1"), source="chat")


def test_append_line_empty_source_raises_value_error_without_storage() -> None:
    """source == "" raises ValueError without consulting storage
    (AIE-1036, US3.4).
    """
    store = _new_store(_NeverCalledStorage())

    with pytest.raises(ValueError):
        store.append_line(VALID_PATH, "- [stated] x", VersionToken("v1"), source="")


def test_append_line_over_byte_ceiling_raises_oversize_and_writes_nothing() -> None:
    """An append whose resulting UTF-8 encoding exceeds max_file_bytes
    raises OversizeWriteError with the would-be size and the limit, and
    the file is unchanged (AIE-1036, US3.5).
    """
    storage = InMemoryStorage()
    _seed(storage, VALID_PATH, "- [stated] a\n", _metadata())
    store = _new_store_with_limit(storage, max_file_bytes=15)
    before = store.read_file(VALID_PATH)

    with pytest.raises(OversizeWriteError) as excinfo:
        store.append_line(VALID_PATH, "- [stated] " + "x" * 20, before.version, source="chat")

    assert excinfo.value.path == VALID_PATH
    assert excinfo.value.limit == 15

    after = store.read_file(VALID_PATH)
    assert after.content == "- [stated] a\n"
    assert after.version == before.version


def test_append_line_at_exact_byte_ceiling_succeeds() -> None:
    """An append whose resulting UTF-8 encoding is exactly max_file_bytes
    succeeds (AIE-1036, US3.5).
    """
    storage = InMemoryStorage()
    _seed(storage, VALID_PATH, "", _metadata())
    line = "- [stated] " + "x" * 3
    limit = len((line + "\n").encode("utf-8"))
    store = _new_store_with_limit(storage, max_file_bytes=limit)
    before = store.read_file(VALID_PATH)

    result = store.append_line(VALID_PATH, line, before.version, source="chat")

    assert result.content == line + "\n"
    assert len(result.content.encode("utf-8")) == limit


def test_append_line_stale_token_and_oversize_line_raises_version_conflict_first() -> None:
    """When both the token is stale and the line would be oversize,
    VersionConflictError is raised because the version is checked first
    (AIE-1036, US3.6).
    """
    storage = InMemoryStorage()
    meta = _metadata()
    _seed(storage, VALID_PATH, "- [stated] a\n", meta)
    store = _new_store_with_limit(storage, max_file_bytes=5)
    stale = VersionToken("not-a-real-token")

    with pytest.raises(VersionConflictError):
        store.append_line(VALID_PATH, "- [stated] " + "x" * 50, stale, source="chat")


def test_append_line_propagates_backend_unavailable_from_get() -> None:
    """A BackendUnavailableError raised by storage.get() propagates
    unwrapped (AIE-1036, US3.7).
    """
    error = BackendUnavailableError(TransientReason.UNAVAILABLE)
    stub = _StubStorage(get_raises=error)
    store = _new_store(stub)

    with pytest.raises(BackendUnavailableError) as excinfo:
        store.append_line(VALID_PATH, "- [stated] x", VersionToken("v1"), source="chat")

    assert excinfo.value is error


def test_append_line_propagates_backend_unavailable_from_put_if_version() -> None:
    """A BackendUnavailableError raised by storage.put_if_version()
    propagates unwrapped (AIE-1036, US3.7).
    """
    error = BackendUnavailableError(TransientReason.TIMEOUT)
    v1 = VersionToken("v1")
    stub = _StubStorage(
        get_result=StoredObject(
            data=b"- [stated] a\n",
            metadata=metadata_to_map(_metadata()),
            version=v1,
        ),
        put_if_version_raises=error,
    )
    store = _new_store(stub)

    with pytest.raises(BackendUnavailableError) as excinfo:
        store.append_line(VALID_PATH, "- [stated] x", v1, source="chat")

    assert excinfo.value is error


def test_append_line_corrupt_metadata_propagates() -> None:
    """A stored object with a corrupt metadata map causes
    MetadataFormatError to propagate (AIE-1036, US3.7).
    """
    bad_map = dict(metadata_to_map(_metadata()))
    del bad_map["description"]
    v1 = VersionToken("v1")
    stub = _StubStorage(
        get_result=StoredObject(data=b"- [stated] a\n", metadata=bad_map, version=v1)
    )
    store = _new_store(stub)

    with pytest.raises(MetadataFormatError) as excinfo:
        store.append_line(VALID_PATH, "- [stated] x", v1, source="chat")

    assert excinfo.value.key == "description"


# --- Optional aliases and description -----------------------------------------

F_BODY = "- [stated] a\n"
F_LINE = "- [stated] b"


def _f_metadata(aliases: tuple[str, ...] = ("x", "y")) -> FileMetadata:
    return _metadata(description="d", aliases=aliases, sources=frozenset({"s1"}))


class _CountingStorage(InMemoryStorage):
    """InMemoryStorage that records every put_if_version call and counts
    unconditional puts not made from inside put_if_version.
    """

    def __init__(self) -> None:
        super().__init__()
        self.put_if_version_calls: list[tuple[bytes, dict[str, str]]] = []
        self.put_calls = 0
        self._in_put_if_version = False

    def put(self, key: str, data: bytes, metadata: Mapping[str, str]) -> VersionToken:
        if not self._in_put_if_version:
            self.put_calls += 1
        return super().put(key, data, metadata)

    def put_if_version(
        self,
        key: str,
        data: bytes,
        metadata: Mapping[str, str],
        expected: VersionToken | None,
    ) -> VersionToken:
        self.put_if_version_calls.append((data, dict(metadata)))
        self._in_put_if_version = True
        try:
            return super().put_if_version(key, data, metadata, expected)
        finally:
            self._in_put_if_version = False


class _LyingStr(str):
    """A str subclass whose __eq__, __hash__, and __str__ lie."""

    def __eq__(self, other: object) -> bool:
        return True

    def __ne__(self, other: object) -> bool:
        return False

    def __hash__(self) -> int:
        return 0

    def __str__(self) -> str:
        return "lie"


class _SpoofList:
    """Claims to be a list through __class__ only; its real type is not a Sequence."""

    @property
    def __class__(self) -> type:  # pyright: ignore[reportIncompatibleMethodOverride]
        return list

    def __iter__(self) -> object:
        return iter(["a"])


def _seed_f(
    storage: InMemoryStorage, aliases: tuple[str, ...] = ("x", "y")
) -> tuple[MemoryStore, VersionToken]:
    _seed(storage, VALID_PATH, F_BODY, _f_metadata(aliases))
    store = _new_store(storage)
    return store, store.read_file(VALID_PATH).version


def _assert_exact_aliases(aliases: object, expected: tuple[str, ...]) -> None:
    assert type(aliases) is tuple
    members = cast(tuple[object, ...], aliases)
    assert all(type(a) is str for a in members)
    assert members == expected


def test_append_line_unions_aliases_in_order_dropping_duplicates() -> None:
    """Given aliases are added after the stored ones, in given order, skipping
    any already present or repeated; content appended; description unchanged
    (AIE-1151, US1.1).
    """
    storage = InMemoryStorage()
    store, v = _seed_f(storage)

    result = store.append_line(VALID_PATH, F_LINE, v, source="chat", aliases=["y", "z", "w", "z"])

    _assert_exact_aliases(result.metadata.aliases, ("x", "y", "z", "w"))
    assert result.content == F_BODY + F_LINE + "\n"
    assert result.metadata.description == "d"
    reread = store.read_file(VALID_PATH)
    _assert_exact_aliases(reread.metadata.aliases, ("x", "y", "z", "w"))
    assert reread.metadata == result.metadata


def test_append_line_description_replaces_stored_and_leaves_aliases() -> None:
    """description replaces the stored description; aliases are unchanged
    (AIE-1151, US1.2).
    """
    storage = InMemoryStorage()
    store, v = _seed_f(storage)

    result = store.append_line(VALID_PATH, F_LINE, v, source="chat", description="d2")

    assert result.metadata.description == "d2"
    assert result.metadata.aliases == ("x", "y")
    reread = store.read_file(VALID_PATH)
    assert reread.metadata.description == "d2"
    assert reread.metadata.aliases == ("x", "y")


def test_append_line_aliases_and_description_commit_in_one_put() -> None:
    """Both arguments apply, sources gains the source, last_updated is the
    clock value, and exactly one put_if_version carries content and metadata
    together (AIE-1151, US1.3).
    """
    storage = _CountingStorage()
    store, v = _seed_f(storage)
    storage.put_calls = 0

    result = store.append_line(
        VALID_PATH, F_LINE, v, source="chat", aliases=["z"], description="d2"
    )

    assert result.metadata.aliases == ("x", "y", "z")
    assert result.metadata.description == "d2"
    assert result.metadata.sources == frozenset({"s1", "chat"})
    assert result.metadata.last_updated == FIXED_CLOCK_TIME
    assert storage.put_calls == 0
    assert storage.put_if_version_calls == [
        ((F_BODY + F_LINE + "\n").encode("utf-8"), dict(metadata_to_map(result.metadata)))
    ]


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"aliases": None, "description": None},
        {"aliases": []},
        {"aliases": ()},
    ],
    ids=["omitted", "explicit-none", "empty-list", "empty-tuple"],
)
def test_append_line_absent_arguments_leave_metadata_unchanged(
    kwargs: dict[str, object],
) -> None:
    """Omitted, None, or empty aliases leave description and aliases exactly as
    stored, as today (AIE-1151, US1.4).
    """
    storage = InMemoryStorage()
    store, v = _seed_f(storage)
    call = cast(Callable[..., MemoryFile], store.append_line)

    result = call(VALID_PATH, F_LINE, v, source="chat", **kwargs)

    expected = replace(
        _f_metadata(), sources=frozenset({"s1", "chat"}), last_updated=FIXED_CLOCK_TIME
    )
    assert result.content == F_BODY + F_LINE + "\n"
    assert result.metadata == expected
    _assert_exact_aliases(result.metadata.aliases, ("x", "y"))
    assert store.read_file(VALID_PATH).metadata == expected


def test_append_line_aliases_all_present_leaves_aliases_unchanged() -> None:
    """Aliases that are all already stored leave the tuple unchanged
    (AIE-1151, US1.5).
    """
    storage = InMemoryStorage()
    store, v = _seed_f(storage)

    result = store.append_line(VALID_PATH, F_LINE, v, source="chat", aliases=["x", "y"])

    _assert_exact_aliases(result.metadata.aliases, ("x", "y"))


def test_append_line_normalizes_str_subclass_alias_with_exact_comparison() -> None:
    """A lying str-subclass alias is stored as the exact str from str.__str__,
    and dedup compares exact strings (AIE-1151, US1.6).
    """
    storage = InMemoryStorage()
    store, v = _seed_f(storage)

    result = store.append_line(
        VALID_PATH, F_LINE, v, source="chat", aliases=[_LyingStr("q"), "q", _LyingStr("x")]
    )

    _assert_exact_aliases(result.metadata.aliases, ("x", "y", "q"))
    _assert_exact_aliases(store.read_file(VALID_PATH).metadata.aliases, ("x", "y", "q"))


def test_append_line_accepts_empty_alias_and_empty_description() -> None:
    """An empty-string alias and an empty description are accepted, as with
    write_file (AIE-1151, US1.1, US1.2).
    """
    storage = InMemoryStorage()
    store, v = _seed_f(storage)

    result = store.append_line(VALID_PATH, F_LINE, v, source="chat", aliases=[""], description="")

    assert result.metadata.aliases == ("x", "y", "")
    assert result.metadata.description == ""


BAD_ALIAS_CONTAINERS: tuple[object, ...] = (
    "ab",
    b"ab",
    bytearray(b"ab"),
    5,
    {"a"},
    iter(["a"]),
    _SpoofList(),
)
BAD_ALIAS_CONTAINER_IDS = ("str", "bytes", "bytearray", "int", "set", "iterator", "spoof")


@pytest.mark.parametrize("aliases", BAD_ALIAS_CONTAINERS, ids=BAD_ALIAS_CONTAINER_IDS)
def test_append_line_bad_aliases_container_raises_type_error_without_storage(
    aliases: object,
) -> None:
    """A str, bytes, bytearray, non-Sequence, or __class__-spoofed aliases raises
    TypeError naming the real type, and storage is never called (AIE-1151, US1.7).
    """
    store = _new_store(_NeverCalledStorage())
    expected = f"aliases must be a sequence of str, not {type(aliases).__name__}"

    with pytest.raises(TypeError) as excinfo:
        store.append_line(
            VALID_PATH,
            F_LINE,
            VersionToken("v1"),
            source="chat",
            aliases=cast(Sequence[str], aliases),
        )

    assert str(excinfo.value) == expected


def test_append_line_non_str_alias_entry_raises_type_error_without_storage() -> None:
    """A non-str alias member raises TypeError naming its type, and storage is
    never called (AIE-1151, US1.8).
    """
    store = _new_store(_NeverCalledStorage())

    with pytest.raises(TypeError) as excinfo:
        store.append_line(
            VALID_PATH,
            F_LINE,
            VersionToken("v1"),
            source="chat",
            aliases=cast(Sequence[str], ["a", 5]),
        )

    assert str(excinfo.value) == "aliases entry must be str, got int"


def test_append_line_non_str_description_raises_type_error_without_storage() -> None:
    """A non-str description raises TypeError naming its type, and storage is
    never called (AIE-1151, US1.9).
    """
    store = _new_store(_NeverCalledStorage())

    with pytest.raises(TypeError) as excinfo:
        store.append_line(
            VALID_PATH, F_LINE, VersionToken("v1"), source="chat", description=cast(str, 5)
        )

    assert str(excinfo.value) == "description must be a str, not int"


@pytest.mark.parametrize("description", ["a\nb", "a\rb"], ids=["lf", "cr"])
def test_append_line_multiline_description_raises_value_error_without_storage(
    description: str,
) -> None:
    """A description containing a newline or carriage return raises ValueError,
    and storage is never called (AIE-1151, US1.10).
    """
    store = _new_store(_NeverCalledStorage())

    with pytest.raises(ValueError) as excinfo:
        store.append_line(
            VALID_PATH, F_LINE, VersionToken("v1"), source="chat", description=description
        )

    assert str(excinfo.value) == "description must not contain a newline or carriage return"


def test_append_line_normalizes_str_subclass_description() -> None:
    """A lying str-subclass description is stored as the exact str "d2"
    (AIE-1151, US1.11).
    """
    storage = InMemoryStorage()
    store, v = _seed_f(storage)

    result = store.append_line(VALID_PATH, F_LINE, v, source="chat", description=_LyingStr("d2"))

    assert type(result.metadata.description) is str
    assert result.metadata.description == "d2"
    reread = store.read_file(VALID_PATH).metadata.description
    assert type(reread) is str
    assert reread == "d2"


def test_append_line_invalid_path_wins_over_bad_aliases() -> None:
    """An invalid path raises NotFoundError(INVALID_PATH) before bad aliases are
    checked (AIE-1151, US1.12).
    """
    store = _new_store(_NeverCalledStorage())

    with pytest.raises(NotFoundError) as excinfo:
        store.append_line(
            "a/b.md",
            "plain text",
            VersionToken("v1"),
            source="",
            aliases=cast(Sequence[str], "ab"),
            description=cast(str, 5),
        )

    assert excinfo.value.reason is NotFoundReason.INVALID_PATH


@pytest.mark.parametrize(
    ("line", "source"),
    [("- [stated] b", ""), ("plain text", "chat")],
    ids=["empty-source", "non-fact-line"],
)
def test_append_line_existing_value_error_wins_over_bad_aliases(line: str, source: str) -> None:
    """An empty source or non-fact line raises the existing ValueError before bad
    aliases or description are checked (AIE-1151, US1.12).
    """
    store = _new_store(_NeverCalledStorage())

    with pytest.raises(ValueError) as excinfo:
        store.append_line(
            VALID_PATH,
            line,
            VersionToken("v1"),
            source=source,
            aliases=cast(Sequence[str], "ab"),
            description=cast(str, 5),
        )

    assert type(excinfo.value) is ValueError
    assert str(excinfo.value) == "line must be a single fact line and source must be non-empty"


@pytest.mark.parametrize(
    ("aliases", "description", "error", "message"),
    [
        ("ab", 5, TypeError, "aliases must be a sequence of str, not str"),
        (["a", 5], "a\nb", TypeError, "aliases entry must be str, got int"),
        (["a"], 5, TypeError, "description must be a str, not int"),
        (
            ["a"],
            "a\nb",
            ValueError,
            "description must not contain a newline or carriage return",
        ),
    ],
    ids=[
        "aliases-before-description-type",
        "entry-before-description-value",
        "description-type",
        "description-value",
    ],
)
def test_append_line_new_argument_errors_in_order(
    aliases: object, description: object, error: type[Exception], message: str
) -> None:
    """aliases TypeError precedes description TypeError, which precedes the
    description ValueError (AIE-1151, US1.12).
    """
    store = _new_store(_NeverCalledStorage())

    with pytest.raises(error) as excinfo:
        store.append_line(
            VALID_PATH,
            F_LINE,
            VersionToken("v1"),
            source="chat",
            aliases=cast(Sequence[str], aliases),
            description=cast(str, description),
        )

    assert type(excinfo.value) is error
    assert str(excinfo.value) == message


def test_append_line_landed_retry_with_new_metadata_returns_success() -> None:
    """A precondition failure whose re-read finds exactly the bytes and metadata
    map this call wrote, including new aliases and description, returns success
    with the new metadata and the re-read version (AIE-1151, US1.13).
    """
    storage = InMemoryStorage()
    _seed(storage, VALID_PATH, F_BODY, _f_metadata())
    wrapped = _OwnWriteLandsThenPreconditionFailsStorage(storage)
    store = _new_store(wrapped)
    before = store.read_file(VALID_PATH)

    result = store.append_line(
        VALID_PATH, F_LINE, before.version, source="chat", aliases=["z"], description="d2"
    )

    assert wrapped.put_if_version_calls == 1
    assert result.metadata.aliases == ("x", "y", "z")
    assert result.metadata.description == "d2"
    reread = store.read_file(VALID_PATH)
    assert reread.version == result.version
    assert reread.metadata == result.metadata
    assert reread.content == result.content


class _SameBytesDifferentMetadataStorage:
    """Wraps InMemoryStorage; put_if_version stores the attempted bytes with a
    different metadata map, then raises PreconditionFailedError.
    """

    def __init__(self, inner: InMemoryStorage, metadata: Mapping[str, str]) -> None:
        self._inner = inner
        self._metadata = metadata
        self.landed_version: VersionToken | None = None

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
        self.landed_version = self._inner.put(key, data, self._metadata)
        raise PreconditionFailedError(key)

    def list_page(self, prefix: str, start_after: str | None, limit: int) -> Sequence[ListedObject]:
        return self._inner.list_page(prefix, start_after, limit)

    def delete_if_version(self, key: str, expected: VersionToken) -> None:
        self._inner.delete_if_version(key, expected)


def test_append_line_same_bytes_different_metadata_map_conflicts() -> None:
    """A precondition failure whose re-read shows the same bytes but a metadata
    map without the new aliases raises VersionConflictError (AIE-1151, US1.14).
    """
    storage = InMemoryStorage()
    _seed(storage, VALID_PATH, F_BODY, _f_metadata())
    other = replace(_f_metadata(), sources=frozenset({"s1", "chat"}), last_updated=FIXED_CLOCK_TIME)
    wrapped = _SameBytesDifferentMetadataStorage(storage, metadata_to_map(other))
    store = _new_store(wrapped)
    before = store.read_file(VALID_PATH)

    with pytest.raises(VersionConflictError) as excinfo:
        store.append_line(VALID_PATH, F_LINE, before.version, source="chat", aliases=["z"])

    assert excinfo.value.content == F_BODY + F_LINE + "\n"
    assert excinfo.value.version == wrapped.landed_version


def test_append_line_keeps_stored_duplicate_aliases_as_stored() -> None:
    """Stored aliases with a pre-existing duplicate are kept as stored, never
    deduplicated or reordered, with new aliases after them (AIE-1151, US1.15).
    """
    storage = InMemoryStorage()
    store, v = _seed_f(storage, aliases=("x", "x"))

    result = store.append_line(VALID_PATH, F_LINE, v, source="chat", aliases=["z"])

    _assert_exact_aliases(result.metadata.aliases, ("x", "x", "z"))
    _assert_exact_aliases(store.read_file(VALID_PATH).metadata.aliases, ("x", "x", "z"))
