"""Failing tests for MemoryStore.write_file, ahead of src/wenchang/core.py
implementing it.

Covers AIE-1033, US1 through US3, US5, and US6, excluding the byte-size
limit (T4, tested separately).
"""

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta

import pytest

from wenchang.core import DEFAULT_MAX_FILE_BYTES, MemoryStore
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


def _seed(storage: InMemoryStorage, path: str, body: str, meta: FileMetadata) -> None:
    storage.put(path, body.encode("utf-8"), metadata_to_map(meta))


def _new_store(
    storage: Storage, *, clock: Callable[[], datetime] | None = _fixed_clock
) -> MemoryStore:
    """Build a MemoryStore, defaulting to a fixed clock unless clock=None.

    Passing clock=None constructs MemoryStore with no clock override, to
    exercise its own default (real UTC time).
    """
    if clock is None:
        return MemoryStore(storage)
    return MemoryStore(storage, clock=clock)


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


# --- US1: create -----------------------------------------------------------


def test_write_file_creates_file_and_read_file_agrees() -> None:
    """Writing to an absent path with expected_version=None returns a
    MemoryFile with the given path/content and a token that read_file also
    sees (AIE-1033, US1-1).
    """
    storage = InMemoryStorage()
    store = _new_store(storage)
    meta = _metadata()

    result = store.write_file(VALID_PATH, "hello world", meta, None)

    assert result.path == VALID_PATH
    assert result.content == "hello world"
    assert result.metadata.description == meta.description
    assert result.metadata.aliases == meta.aliases
    assert result.metadata.sources == meta.sources

    reread = store.read_file(VALID_PATH)
    assert reread.content == "hello world"
    assert reread.metadata == result.metadata
    assert reread.version == result.version


def test_write_file_with_none_expected_conflicts_when_file_exists() -> None:
    """Writing with expected_version=None against an existing file raises
    VersionConflictError with the existing content and version, leaving the
    file unchanged (AIE-1033, US1-2).
    """
    storage = InMemoryStorage()
    _seed(storage, VALID_PATH, "existing body", _metadata(description="existing"))
    store = _new_store(storage)
    before = store.read_file(VALID_PATH)

    with pytest.raises(VersionConflictError) as excinfo:
        store.write_file(VALID_PATH, "new body", _metadata(), None)

    assert excinfo.value.content == "existing body"
    assert excinfo.value.version == before.version

    after = store.read_file(VALID_PATH)
    assert after.content == "existing body"
    assert after.version == before.version


# --- US2: version-guarded update --------------------------------------------


def test_write_file_updates_with_matching_expected_version() -> None:
    """Writing with expected_version equal to the current token succeeds,
    producing a new distinct token, with read_file returning the new content
    and metadata (AIE-1033, US2-1).
    """
    storage = InMemoryStorage()
    store = _new_store(storage)
    first = store.write_file(VALID_PATH, "v1 body", _metadata(description="v1"), None)

    second = store.write_file(VALID_PATH, "v2 body", _metadata(description="v2"), first.version)

    assert second.version != first.version
    reread = store.read_file(VALID_PATH)
    assert reread.content == "v2 body"
    assert reread.metadata.description == "v2"
    assert reread.version == second.version


def test_write_file_with_stale_expected_version_conflicts() -> None:
    """Writing with an expected_version that is no longer current raises
    VersionConflictError carrying the path as given, the latest content, and
    the latest version; the file is left unchanged (AIE-1033, US2-2).
    """
    storage = InMemoryStorage()
    store = _new_store(storage)
    first = store.write_file(VALID_PATH, "v1 body", _metadata(), None)
    second = store.write_file(VALID_PATH, "v2 body", _metadata(), first.version)

    with pytest.raises(VersionConflictError) as excinfo:
        store.write_file(VALID_PATH, "v3 body", _metadata(), first.version)

    assert excinfo.value.path == VALID_PATH
    assert excinfo.value.content == "v2 body"
    assert excinfo.value.version == second.version

    after = store.read_file(VALID_PATH)
    assert after.content == "v2 body"
    assert after.version == second.version


def test_write_file_retry_with_conflict_version_succeeds() -> None:
    """Retrying write_file with the version carried by a VersionConflictError
    it just raised succeeds (AIE-1033, US2-3).
    """
    storage = InMemoryStorage()
    store = _new_store(storage)
    store.write_file(VALID_PATH, "v1 body", _metadata(), None)

    with pytest.raises(VersionConflictError) as excinfo:
        store.write_file(VALID_PATH, "v2 body", _metadata(), None)
    conflict_version = excinfo.value.version

    result = store.write_file(VALID_PATH, "v2 body retried", _metadata(), conflict_version)

    assert result.content == "v2 body retried"
    reread = store.read_file(VALID_PATH)
    assert reread.content == "v2 body retried"
    assert reread.version == result.version


def test_write_file_with_expected_version_and_no_file_raises_file_absent() -> None:
    """A non-None expected_version against an absent file raises
    NotFoundError with reason FILE_ABSENT, and nothing is written
    (AIE-1033, US2-4).
    """
    storage = InMemoryStorage()
    store = _new_store(storage)

    with pytest.raises(NotFoundError) as excinfo:
        store.write_file(VALID_PATH, "body", _metadata(), VersionToken("1"))

    assert excinfo.value.reason is NotFoundReason.FILE_ABSENT
    assert excinfo.value.path == VALID_PATH

    with pytest.raises(NotFoundError) as reread_excinfo:
        store.read_file(VALID_PATH)
    assert reread_excinfo.value.reason is NotFoundReason.FILE_ABSENT


def test_write_file_with_unmatched_expected_version_conflicts_with_current_state() -> None:
    """An expected_version that never corresponds to any version this file
    has had raises VersionConflictError carrying the current content and
    version (AIE-1033, US2-5).
    """
    storage = InMemoryStorage()
    store = _new_store(storage)
    store.write_file(VALID_PATH, "current body", _metadata(description="current"), None)
    current = store.read_file(VALID_PATH)

    with pytest.raises(VersionConflictError) as excinfo:
        store.write_file(VALID_PATH, "new body", _metadata(), VersionToken("abc"))

    assert excinfo.value.content == "current body"
    assert excinfo.value.version == current.version


def test_write_file_retrying_same_successful_call_conflicts_with_own_write() -> None:
    """Retrying an already-successful write_file call with the same
    expected_version raises VersionConflictError whose content equals what
    the first attempt wrote (AIE-1033, US2-6).
    """
    storage = InMemoryStorage()
    store = _new_store(storage)
    initial = store.write_file(VALID_PATH, "seed", _metadata(), None)

    first = store.write_file(VALID_PATH, "written once", _metadata(), initial.version)

    with pytest.raises(VersionConflictError) as excinfo:
        store.write_file(VALID_PATH, "written once", _metadata(), initial.version)

    assert excinfo.value.content == first.content


# --- US3: reads reflect writes precisely ------------------------------------


def test_write_file_sequential_writes_never_mix_content_and_metadata() -> None:
    """After two successive writes, read_file returns the second write's
    content paired with the second write's metadata, never a mix
    (AIE-1033, US3-1).
    """
    storage = InMemoryStorage()
    store = _new_store(storage)
    first_meta = _metadata(description="first", aliases=("f",), sources=frozenset({"fs"}))
    first = store.write_file(VALID_PATH, "content one", first_meta, None)
    second_meta = _metadata(description="second", aliases=("s",), sources=frozenset({"ss"}))
    store.write_file(VALID_PATH, "content two", second_meta, first.version)

    result = store.read_file(VALID_PATH)

    assert result.content == "content two"
    assert result.metadata.description == "second"
    assert result.metadata.aliases == ("s",)
    assert result.metadata.sources == frozenset({"ss"})


def test_write_file_invalid_path_leaves_prior_read_behavior_unchanged() -> None:
    """A rejected write due to an invalid path leaves read_file's behavior
    for that path unchanged: still INVALID_PATH (AIE-1033, US3-2).
    """
    storage = InMemoryStorage()
    store = _new_store(storage)

    with pytest.raises(NotFoundError):
        store.write_file("not/a/valid", "body", _metadata(), None)

    with pytest.raises(NotFoundError) as excinfo:
        store.read_file("not/a/valid")
    assert excinfo.value.reason is NotFoundReason.INVALID_PATH


def test_write_file_conflict_leaves_prior_state_including_token_unchanged() -> None:
    """A write rejected as a version conflict leaves read_file returning
    exactly the prior content and the same token (AIE-1033, US3-2).
    """
    storage = InMemoryStorage()
    store = _new_store(storage)
    store.write_file(VALID_PATH, "stable body", _metadata(), None)
    before = store.read_file(VALID_PATH)

    with pytest.raises(VersionConflictError):
        store.write_file(VALID_PATH, "unwanted", _metadata(), VersionToken("nonexistent"))

    after = store.read_file(VALID_PATH)
    assert after.content == before.content
    assert after.version == before.version


def test_write_file_naive_clock_leaves_prior_state_unchanged() -> None:
    """A write rejected because the clock returned a naive datetime leaves
    an existing file's content and version unchanged (AIE-1033, US3-2).
    """
    storage = InMemoryStorage()
    store = _new_store(storage)
    store.write_file(VALID_PATH, "stable body", _metadata(), None)
    before = store.read_file(VALID_PATH)

    naive_store = _new_store(storage, clock=lambda: datetime(2025, 1, 1))
    with pytest.raises(ValueError):
        naive_store.write_file(VALID_PATH, "unwanted", _metadata(), before.version)

    after = store.read_file(VALID_PATH)
    assert after.content == before.content
    assert after.version == before.version


def test_write_file_file_absent_leaves_prior_state_absent() -> None:
    """A write rejected as FILE_ABSENT leaves the path still absent
    (AIE-1033, US3-2).
    """
    storage = InMemoryStorage()
    store = _new_store(storage)

    with pytest.raises(NotFoundError):
        store.write_file(VALID_PATH, "body", _metadata(), VersionToken("1"))

    with pytest.raises(NotFoundError) as excinfo:
        store.read_file(VALID_PATH)
    assert excinfo.value.reason is NotFoundReason.FILE_ABSENT


BODIES = (
    "unicode: café 日本語",
    "line one\r\nline two\r\n",
    "trailing newline\n",
    "no trailing newline",
    "- [stated] x\n- [Stated] y",
    "",
)


@pytest.mark.parametrize("body", BODIES)
def test_write_file_round_trips_content_exactly(body: str) -> None:
    """Written content round-trips through read_file byte-for-byte,
    including unicode, CRLF, trailing/missing newline, fact-like syntax, and
    the empty string (AIE-1033, US3-3).
    """
    storage = InMemoryStorage()
    store = _new_store(storage)

    store.write_file(VALID_PATH, body, _metadata(), None)

    result = store.read_file(VALID_PATH)
    assert result.content == body


def test_write_file_round_trips_metadata_with_special_characters() -> None:
    """Metadata whose aliases/sources contain commas, quotes, brackets, and
    unicode round-trips exactly through write_file and read_file
    (AIE-1033, US3-3).
    """
    storage = InMemoryStorage()
    store = _new_store(storage)
    meta = _metadata(
        description='d, "quoted" [bracketed] café',
        aliases=("a, b", 'c"d', "[e]", "café"),
        sources=frozenset({"src, one", 'src"two', "[src3]", "日本"}),
    )

    store.write_file(VALID_PATH, "body", meta, None)

    result = store.read_file(VALID_PATH)
    assert result.metadata.description == meta.description
    assert result.metadata.aliases == meta.aliases
    assert result.metadata.sources == meta.sources


# --- US5: last-updated stamping ---------------------------------------------


def test_write_file_stamps_last_updated_from_clock_overriding_caller_value() -> None:
    """write_file overrides the caller's last_updated with the injected
    clock's value, while leaving description, aliases, and sources exactly
    as supplied (AIE-1033, US5-1).
    """
    storage = InMemoryStorage()
    store = _new_store(storage, clock=_fixed_clock)
    caller_meta = _metadata(
        description="d",
        aliases=("x", "y"),
        sources=frozenset({"s"}),
        last_updated=datetime(2020, 1, 1, tzinfo=UTC),
    )

    result = store.write_file(VALID_PATH, "body", caller_meta, None)

    assert result.metadata.last_updated == FIXED_CLOCK_TIME
    assert result.metadata.description == "d"
    assert result.metadata.aliases == ("x", "y")
    assert result.metadata.sources == frozenset({"s"})

    reread = store.read_file(VALID_PATH)
    assert reread.metadata.last_updated == FIXED_CLOCK_TIME


def test_write_file_default_clock_stamps_tz_aware_utc_now() -> None:
    """With no clock override, write_file stamps last_updated with a
    tz-aware UTC value between the times immediately before and after the
    call (AIE-1033, US5-2).
    """
    storage = InMemoryStorage()
    store = _new_store(storage, clock=None)

    before = datetime.now(UTC)
    result = store.write_file(VALID_PATH, "body", _metadata(), None)
    after = datetime.now(UTC)

    assert result.metadata.last_updated.tzinfo is not None
    assert result.metadata.last_updated.utcoffset() == timedelta(0)
    assert before <= result.metadata.last_updated <= after


def test_write_file_naive_clock_raises_value_error_and_writes_nothing() -> None:
    """A clock that returns a naive datetime causes write_file to raise
    ValueError, and nothing is written (AIE-1033, US5-3).
    """
    storage = InMemoryStorage()
    store = _new_store(storage, clock=lambda: datetime(2025, 1, 1))

    with pytest.raises(ValueError):
        store.write_file(VALID_PATH, "body", _metadata(), None)

    with pytest.raises(NotFoundError) as excinfo:
        store.read_file(VALID_PATH)
    assert excinfo.value.reason is NotFoundReason.FILE_ABSENT


# --- US6: malformed paths and propagated errors -----------------------------


MALFORMED_PATHS = (
    "",
    "a/b.md",
    "user/u/a/b.txt",
    "user//a/b.md",
)


@pytest.mark.parametrize("path", MALFORMED_PATHS)
def test_write_file_raises_not_found_invalid_path_without_calling_storage(path: str) -> None:
    """A malformed path raises NotFoundError with reason INVALID_PATH and
    never calls storage (AIE-1033, US6-1).
    """
    stub = _StubStorage()
    store = _new_store(stub)

    with pytest.raises(NotFoundError) as excinfo:
        store.write_file(path, "body", _metadata(), None)

    assert excinfo.value.reason is NotFoundReason.INVALID_PATH
    assert excinfo.value.path == path
    assert stub.get_calls == []
    assert stub.put_if_version_calls == []


def test_write_file_propagates_backend_unavailable_error_from_put_unchanged() -> None:
    """A BackendUnavailableError raised by storage.put_if_version()
    propagates as the same exception object, unwrapped (AIE-1033, US6-2).
    """
    error = BackendUnavailableError(TransientReason.UNAVAILABLE)
    stub = _StubStorage(put_if_version_raises=error)
    store = _new_store(stub)

    with pytest.raises(BackendUnavailableError) as excinfo:
        store.write_file(VALID_PATH, "body", _metadata(), None)

    assert excinfo.value is error


def test_write_file_propagates_backend_unavailable_error_from_get_on_conflict_unchanged() -> None:
    """When translating a PreconditionFailedError, a BackendUnavailableError
    raised by the follow-up storage.get() propagates unwrapped, not as a
    VersionConflictError (AIE-1033, US6-2).
    """
    get_error = BackendUnavailableError(TransientReason.TIMEOUT)
    stub = _StubStorage(
        get_raises=get_error, put_if_version_raises=PreconditionFailedError(VALID_PATH)
    )
    store = _new_store(stub)

    with pytest.raises(BackendUnavailableError) as excinfo:
        store.write_file(VALID_PATH, "body", _metadata(), None)

    assert excinfo.value is get_error


# --- Edge cases --------------------------------------------------------------


def test_write_file_conflict_with_absent_follow_up_get_raises_file_absent() -> None:
    """If storage.put_if_version raises PreconditionFailedError but the
    follow-up storage.get() finds nothing, write_file raises NotFoundError
    with reason FILE_ABSENT (AIE-1033, edge case).
    """
    stub = _StubStorage(get_result=None, put_if_version_raises=PreconditionFailedError(VALID_PATH))
    store = _new_store(stub)

    with pytest.raises(NotFoundError) as excinfo:
        store.write_file(VALID_PATH, "body", _metadata(), VersionToken("1"))

    assert excinfo.value.reason is NotFoundReason.FILE_ABSENT


def test_write_file_conflict_with_corrupt_metadata_on_follow_up_get_propagates() -> None:
    """If the follow-up storage.get() (after a PreconditionFailedError)
    returns an object with a corrupt metadata map, MetadataFormatError
    propagates (AIE-1033, edge case).
    """
    bad_map = dict(metadata_to_map(_metadata()))
    del bad_map["description"]
    stub = _StubStorage(
        get_result=StoredObject(data=b"body", metadata=bad_map, version=VersionToken("1")),
        put_if_version_raises=PreconditionFailedError(VALID_PATH),
    )
    store = _new_store(stub)

    with pytest.raises(MetadataFormatError) as excinfo:
        store.write_file(VALID_PATH, "body", _metadata(), None)

    assert excinfo.value.key == "description"


def test_write_file_conflict_with_non_utf8_bytes_on_follow_up_get_propagates() -> None:
    """If the follow-up storage.get() (after a PreconditionFailedError)
    returns non-UTF-8 bytes, UnicodeDecodeError propagates (AIE-1033, edge
    case).
    """
    stub = _StubStorage(
        get_result=StoredObject(
            data=b"\xff\xfe", metadata=metadata_to_map(_metadata()), version=VersionToken("1")
        ),
        put_if_version_raises=PreconditionFailedError(VALID_PATH),
    )
    store = _new_store(stub)

    with pytest.raises(UnicodeDecodeError):
        store.write_file(VALID_PATH, "body", _metadata(), None)


# --- T4: byte-size ceiling ---------------------------------------------------


def _new_store_with_limit(storage: Storage, *, max_file_bytes: int) -> MemoryStore:
    """Build a MemoryStore with a fixed clock and a max_file_bytes override."""
    return MemoryStore(
        storage,
        max_file_bytes=max_file_bytes,
        clock=_fixed_clock,
    )


def test_default_max_file_bytes_is_16384() -> None:
    """DEFAULT_MAX_FILE_BYTES is importable from wenchang.core and equals
    16384 (AIE-1033, T4/US4.1).
    """
    assert DEFAULT_MAX_FILE_BYTES == 16384


def test_write_file_at_default_byte_ceiling_succeeds() -> None:
    """Content whose UTF-8 encoding is exactly the default 16384-byte
    ceiling is accepted (AIE-1033, US4.1).
    """
    storage = InMemoryStorage()
    store = _new_store(storage)
    content = "a" * 16384

    result = store.write_file(VALID_PATH, content, _metadata(), None)

    assert result.content == content
    assert len(content.encode("utf-8")) == 16384


def test_write_file_over_default_byte_ceiling_raises_oversize_and_writes_nothing() -> None:
    """Content one byte over the default 16384-byte ceiling raises
    OversizeWriteError with the given path, the actual size, and the
    default limit; nothing is written (AIE-1033, US4.2).
    """

    stub = _StubStorage()
    store = _new_store(stub)
    content = "a" * 16385

    with pytest.raises(OversizeWriteError) as excinfo:
        store.write_file(VALID_PATH, content, _metadata(), None)

    assert excinfo.value.path == VALID_PATH
    assert excinfo.value.size == 16385
    assert excinfo.value.limit == 16384
    assert stub.get_calls == []
    assert stub.put_if_version_calls == []


def test_write_file_over_default_byte_ceiling_leaves_path_absent() -> None:
    """After an oversize write against a real InMemoryStorage backend, the
    path remains absent (AIE-1033, US4.2).
    """
    storage = InMemoryStorage()
    store = _new_store(storage)

    with pytest.raises(OversizeWriteError):
        store.write_file(VALID_PATH, "a" * 16385, _metadata(), None)

    with pytest.raises(NotFoundError) as excinfo:
        store.read_file(VALID_PATH)
    assert excinfo.value.reason is NotFoundReason.FILE_ABSENT


def test_write_file_byte_size_counts_utf8_bytes_not_characters() -> None:
    """Size is measured in UTF-8 bytes, not characters: 5462 multi-byte
    characters produce 16386 bytes, over the default ceiling, even though
    the character count (5462) is well under it (AIE-1033, US4.3).
    """

    stub = _StubStorage()
    store = _new_store(stub)
    content = "\N{EURO SIGN}" * 5462

    assert len(content) < 16384
    assert len(content.encode("utf-8")) == 16386

    with pytest.raises(OversizeWriteError) as excinfo:
        store.write_file(VALID_PATH, content, _metadata(), None)

    assert excinfo.value.size == 16386


def test_write_file_custom_max_file_bytes_rejects_one_byte_over() -> None:
    """With max_file_bytes=100, a 101-byte write raises OversizeWriteError
    with limit == 100 (AIE-1033, US4.4).
    """

    stub = _StubStorage()
    store = _new_store_with_limit(stub, max_file_bytes=100)

    with pytest.raises(OversizeWriteError) as excinfo:
        store.write_file(VALID_PATH, "a" * 101, _metadata(), None)

    assert excinfo.value.limit == 100
    assert excinfo.value.size == 101


def test_write_file_custom_max_file_bytes_accepts_exact_limit() -> None:
    """With max_file_bytes=100, a 100-byte write succeeds (AIE-1033,
    US4.4).
    """
    storage = InMemoryStorage()
    store = _new_store_with_limit(storage, max_file_bytes=100)

    result = store.write_file(VALID_PATH, "a" * 100, _metadata(), None)

    assert result.content == "a" * 100


@pytest.mark.parametrize("bad_limit", [0, -1])
def test_max_file_bytes_non_positive_raises_value_error_at_construction(bad_limit: int) -> None:
    """Constructing a MemoryStore with max_file_bytes <= 0 raises
    ValueError immediately (AIE-1033, US4.5).
    """
    storage = InMemoryStorage()

    with pytest.raises(ValueError):
        _new_store_with_limit(storage, max_file_bytes=bad_limit)


def test_write_file_oversize_with_stale_expected_version_raises_oversize_not_conflict() -> None:
    """An oversize write against an existing file, with a stale
    expected_version, raises OversizeWriteError rather than
    VersionConflictError: size is checked before storage is consulted
    (AIE-1033, US4.6).
    """

    storage = InMemoryStorage()
    store = _new_store(storage)
    first = store.write_file(VALID_PATH, "v1 body", _metadata(), None)
    store.write_file(VALID_PATH, "v2 body", _metadata(), first.version)

    with pytest.raises(OversizeWriteError):
        store.write_file(VALID_PATH, "a" * 16385, _metadata(), first.version)


def test_write_file_oversize_leaves_existing_file_and_token_unchanged() -> None:
    """An oversize write against an existing file leaves that file's
    content and version token exactly as they were (AIE-1033, US3.2/US4).
    """

    storage = InMemoryStorage()
    store = _new_store(storage)
    written = store.write_file(VALID_PATH, "stable body", _metadata(), None)

    with pytest.raises(OversizeWriteError):
        store.write_file(VALID_PATH, "a" * 16385, _metadata(), written.version)

    after = store.read_file(VALID_PATH)
    assert after.content == "stable body"
    assert after.version == written.version
