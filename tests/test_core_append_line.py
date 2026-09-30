"""Tests for MemoryStore.append_line (AIE-1036): version-guarded single-line
append, metadata stamping, retry safety on precondition failure, and
validation/error ordering.
"""

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime

import pytest

from wenchang.core import MemoryStore
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
