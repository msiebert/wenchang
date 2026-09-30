"""Failing tests for MemoryStore.read_file, ahead of src/wenchang/core.py existing.

Covers AIE-1032, US1 through US3 and edge cases for reading a memory file.
"""

import dataclasses
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta, timezone

import pytest

from wenchang.core import MemoryStore
from wenchang.errors import (
    BackendUnavailableError,
    NotFoundError,
    NotFoundReason,
    TransientReason,
    WenchangError,
)
from wenchang.file_format import FileMetadata, MetadataFormatError, metadata_to_map
from wenchang.storage import ListedObject, Storage, StoredObject
from wenchang.storage.memory import InMemoryStorage
from wenchang.version_token import VersionToken

pytestmark = pytest.mark.unit

VALID_PATH = "user/u_42/preferences/editor.md"


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


class _StubStorage:
    """Hand-written Storage stub that records get() calls and can raise on demand."""

    def __init__(
        self,
        get_result: StoredObject | None = None,
        get_raises: BaseException | None = None,
    ) -> None:
        self._get_result = get_result
        self._get_raises = get_raises
        self.get_calls: list[str] = []

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
        raise NotImplementedError("not exercised by these tests")


def _as_storage(stub: _StubStorage) -> Storage:
    return stub


def test_read_file_returns_stored_content_metadata_path_and_version() -> None:
    """A file stored at a valid path with body B and metadata M is read back
    with matching content, metadata, path, and a version token (AIE-1032, US1-1).
    """
    storage = InMemoryStorage()
    meta = _metadata()
    _seed(storage, VALID_PATH, "hello world", meta)
    store = MemoryStore(storage)

    result = store.read_file(VALID_PATH)

    assert result.content == "hello world"
    assert result.metadata == meta
    assert result.path == VALID_PATH
    assert result.version is not None


BODIES = (
    "unicode: café 日本語",
    "line one\r\nline two\r\n",
    "trailing newline\n",
    "no trailing newline",
    "- [stated] x\n- [Stated] y",
    "",
)


@pytest.mark.parametrize("body", BODIES)
def test_read_file_returns_stored_body_exactly(body: str) -> None:
    """Stored bodies round-trip through read_file byte-for-byte, including
    unicode, CRLF, trailing/missing newline, fact-like syntax, and the empty
    string (AIE-1032, US1-2).
    """
    storage = InMemoryStorage()
    _seed(storage, VALID_PATH, body, _metadata())
    store = MemoryStore(storage)

    result = store.read_file(VALID_PATH)

    assert result.content == body


def test_read_file_returns_metadata_with_special_characters_and_offset_timezone() -> None:
    """Metadata whose aliases/sources contain commas, quotes, brackets, and
    unicode, and whose last-updated uses a non-UTC offset, round-trips exactly
    (AIE-1032, US1-3).
    """
    meta = _metadata(
        description='d, "quoted" [bracketed] café',
        aliases=("a, b", 'c"d', "[e]", "café"),
        sources=frozenset({"src, one", 'src"two', "[src3]", "日本"}),
        last_updated=datetime(2024, 6, 1, 12, 30, tzinfo=timezone(timedelta(hours=5, minutes=30))),
    )
    storage = InMemoryStorage()
    _seed(storage, VALID_PATH, "body", meta)
    store = MemoryStore(storage)

    result = store.read_file(VALID_PATH)

    assert result.metadata.description == meta.description
    assert result.metadata.aliases == meta.aliases
    assert result.metadata.sources == meta.sources
    assert result.metadata.last_updated == meta.last_updated


def test_read_file_returns_equal_version_tokens_for_unchanged_file() -> None:
    """Reading an unchanged file twice returns equal version tokens
    (AIE-1032, US1-4).
    """
    storage = InMemoryStorage()
    _seed(storage, VALID_PATH, "body", _metadata())
    store = MemoryStore(storage)

    first = store.read_file(VALID_PATH)
    second = store.read_file(VALID_PATH)

    assert first.version == second.version


def test_read_file_returns_different_version_and_new_content_after_overwrite() -> None:
    """Reading, overwriting via storage.put, then reading again yields a
    different version token (by equality only) and the new content/metadata
    (AIE-1032, US1-5).
    """
    storage = InMemoryStorage()
    _seed(storage, VALID_PATH, "old body", _metadata(description="old"))
    store = MemoryStore(storage)

    first = store.read_file(VALID_PATH)

    new_meta = _metadata(description="new")
    _seed(storage, VALID_PATH, "new body", new_meta)
    second = store.read_file(VALID_PATH)

    assert first.version != second.version
    assert second.content == "new body"
    assert second.metadata == new_meta


def test_read_file_version_is_a_str() -> None:
    """The returned version is a str, since VersionToken is a NewType over str
    (AIE-1032, US1-6).
    """
    storage = InMemoryStorage()
    _seed(storage, VALID_PATH, "body", _metadata())
    store = MemoryStore(storage)

    result = store.read_file(VALID_PATH)

    assert isinstance(result.version, str)


def test_read_file_raises_not_found_file_absent_when_no_object_at_path() -> None:
    """A well-formed path with no object stored raises NotFoundError with
    reason FILE_ABSENT and .path equal to the path given (AIE-1032, US2-1).
    """
    storage = InMemoryStorage()
    store = MemoryStore(storage)

    with pytest.raises(NotFoundError) as excinfo:
        store.read_file(VALID_PATH)

    assert excinfo.value.reason is NotFoundReason.FILE_ABSENT
    assert excinfo.value.path == VALID_PATH


MALFORMED_PATHS = (
    "",
    "/user/u/a/b.md",
    "user/u/a",
    "user/u/a/../b.md",
    "user/u/a/b.txt",
)


@pytest.mark.parametrize("path", MALFORMED_PATHS)
def test_read_file_raises_not_found_invalid_path_without_calling_storage(path: str) -> None:
    """A malformed path raises NotFoundError with reason INVALID_PATH,
    .path equal to the path given, and never calls storage.get (AIE-1032, US2-2).
    """
    stub = _StubStorage()
    store = MemoryStore(_as_storage(stub))

    with pytest.raises(NotFoundError) as excinfo:
        store.read_file(path)

    assert excinfo.value.reason is NotFoundReason.INVALID_PATH
    assert excinfo.value.path == path
    assert stub.get_calls == []


def test_read_file_is_case_sensitive_on_path() -> None:
    """A file stored at one path is not found by a differently-cased path
    (AIE-1032, US2-5).
    """
    storage = InMemoryStorage()
    _seed(storage, "user/u_42/preferences/editor.md", "body", _metadata())
    store = MemoryStore(storage)

    with pytest.raises(NotFoundError) as excinfo:
        store.read_file("user/u_42/preferences/Editor.md")

    assert excinfo.value.reason is NotFoundReason.FILE_ABSENT


@pytest.mark.parametrize("reason", [TransientReason.TIMEOUT, TransientReason.UNAVAILABLE])
def test_read_file_propagates_backend_unavailable_error_unchanged(
    reason: TransientReason,
) -> None:
    """A BackendUnavailableError raised by storage.get() propagates as the
    same exception object, unwrapped (AIE-1032, US3-1).
    """
    error = BackendUnavailableError(reason)
    stub = _StubStorage(get_raises=error)
    store = MemoryStore(_as_storage(stub))

    with pytest.raises(BackendUnavailableError) as excinfo:
        store.read_file(VALID_PATH)

    assert excinfo.value is error


def test_read_file_raises_metadata_format_error_naming_missing_key() -> None:
    """A stored object whose metadata map is missing a required key raises
    MetadataFormatError naming that key (AIE-1032, US3-3).
    """
    full_map = metadata_to_map(_metadata())
    del full_map["description"]
    stub = _StubStorage(
        get_result=StoredObject(data=b"body", metadata=full_map, version=VersionToken("1"))
    )
    store = MemoryStore(_as_storage(stub))

    with pytest.raises(MetadataFormatError) as excinfo:
        store.read_file(VALID_PATH)

    assert excinfo.value.key == "description"


def test_read_file_raises_metadata_format_error_naming_malformed_aliases() -> None:
    """A stored object whose aliases value is malformed JSON raises
    MetadataFormatError naming the aliases key (AIE-1032, US3-3).
    """
    bad_map = metadata_to_map(_metadata())
    bad_map["aliases"] = "not json"
    stub = _StubStorage(
        get_result=StoredObject(data=b"body", metadata=bad_map, version=VersionToken("1"))
    )
    store = MemoryStore(_as_storage(stub))

    with pytest.raises(MetadataFormatError) as excinfo:
        store.read_file(VALID_PATH)

    assert excinfo.value.key == "aliases"


def test_read_file_raises_value_error_not_wenchang_error_on_invalid_utf8() -> None:
    """A stored body that is not valid UTF-8 raises ValueError that is not a
    WenchangError (AIE-1032, US3-4).
    """
    stub = _StubStorage(
        get_result=StoredObject(
            data=b"\xff\xfe", metadata=metadata_to_map(_metadata()), version=VersionToken("1")
        )
    )
    store = MemoryStore(_as_storage(stub))

    with pytest.raises(ValueError) as excinfo:
        store.read_file(VALID_PATH)

    assert not isinstance(excinfo.value, WenchangError)


def test_read_file_reads_a_system_area_path() -> None:
    """A path within a system/ area is readable, like any other well-formed
    path (AIE-1032, edge case).
    """
    storage = InMemoryStorage()
    path = "project/p_1/system/defs.md"
    _seed(storage, path, "system body", _metadata())
    store = MemoryStore(storage)

    result = store.read_file(path)

    assert result.content == "system body"


def test_read_file_allows_empty_content_with_valid_metadata() -> None:
    """A stored file with empty content and valid metadata is a valid file to
    read (AIE-1032, edge case).
    """
    storage = InMemoryStorage()
    _seed(storage, VALID_PATH, "", _metadata())
    store = MemoryStore(storage)

    result = store.read_file(VALID_PATH)

    assert result.content == ""


def test_read_file_ignores_extra_metadata_keys() -> None:
    """A stored metadata map with extra keys beyond the four documented ones
    is read successfully, ignoring the extras (AIE-1032, edge case).
    """
    extended_map = dict(metadata_to_map(_metadata()))
    extended_map["extra-key"] = "extra-value"
    stub = _StubStorage(
        get_result=StoredObject(data=b"body", metadata=extended_map, version=VersionToken("1"))
    )
    store = MemoryStore(_as_storage(stub))

    result = store.read_file(VALID_PATH)

    assert result.content == "body"


def test_memory_file_is_frozen() -> None:
    """MemoryFile is a frozen dataclass; assigning an attribute raises
    FrozenInstanceError (AIE-1032, edge case).
    """
    storage = InMemoryStorage()
    _seed(storage, VALID_PATH, "body", _metadata())
    store = MemoryStore(storage)
    result = store.read_file(VALID_PATH)

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.content = "mutated"  # type: ignore[misc]
