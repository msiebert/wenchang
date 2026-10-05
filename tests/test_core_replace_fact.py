"""Tests for MemoryStore.replace_fact (AIE-1034): unique-anchor replacement,
match-count rejection, metadata stamping, and stale-version re-apply with
the bounded retry loop.
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
    ReplaceFactMatchError,
    TransientReason,
    VersionConflictError,
)
from wenchang.file_format import FileMetadata, MetadataFormatError, metadata_to_map
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
    """Build a MemoryStore, defaulting to a fixed clock unless clock=None.

    Passing clock=None constructs MemoryStore with no clock override, to
    exercise its own default (real UTC time).
    """
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


# --- US1: successful single-match replacement -------------------------------


def test_replace_fact_replaces_unique_match_and_read_file_agrees() -> None:
    """A unique match is replaced, leaving every other byte unchanged, and
    produces a new version distinct from the original that read_file also
    sees (AIE-1034, US1.1).
    """
    storage = InMemoryStorage()
    meta = _metadata()
    _seed(storage, VALID_PATH, "before old middle after", meta)
    store = _new_store(storage)
    before = store.read_file(VALID_PATH)

    result = store.replace_fact(
        VALID_PATH, "old middle", "new middle", before.version, source="src"
    )

    assert result.path == VALID_PATH
    assert result.content == "before new middle after"
    assert result.version != before.version

    reread = store.read_file(VALID_PATH)
    assert reread.content == result.content
    assert reread.metadata == result.metadata
    assert reread.version == result.version


@pytest.mark.parametrize(
    ("body", "old", "new", "expected"),
    [
        ("HEAD rest of body", "HEAD", "TOP", "TOP rest of body"),
        ("body rest of TAIL", "TAIL", "END", "body rest of END"),
        ("line one\nold span\nline three", "one\nold span\n", "one\nnew span\n", None),
    ],
)
def test_replace_fact_matches_at_start_end_or_across_line_break(
    body: str, old: str, new: str, expected: str | None
) -> None:
    """A match at the start of the file, at the end, or spanning a line
    break replaces only that span, leaving the rest exactly as it was
    (AIE-1034, US1.2).
    """
    storage = InMemoryStorage()
    _seed(storage, VALID_PATH, body, _metadata())
    store = _new_store(storage)
    before = store.read_file(VALID_PATH)

    result = store.replace_fact(VALID_PATH, old, new, before.version, source="src")

    want = expected if expected is not None else body.replace(old, new, 1)
    assert result.content == want


def test_replace_fact_with_empty_new_string_deletes_the_span() -> None:
    """new_string == "" deletes the matched span entirely (AIE-1034, US1.3)."""
    storage = InMemoryStorage()
    _seed(storage, VALID_PATH, "keep [delete me] keep", _metadata())
    store = _new_store(storage)
    before = store.read_file(VALID_PATH)

    result = store.replace_fact(VALID_PATH, "[delete me] ", "", before.version, source="src")

    assert result.content == "keep keep"


@pytest.mark.parametrize(
    "body",
    [
        "unicode: café 日本語 here",
        "line one\r\nold\r\nline three",
    ],
)
def test_replace_fact_handles_unicode_and_crlf_without_normalization(body: str) -> None:
    """Multi-byte unicode and CRLF content and anchors are matched and
    replaced exactly, with no normalization (AIE-1034, US1.4).
    """
    storage = InMemoryStorage()
    _seed(storage, VALID_PATH, body, _metadata())
    store = _new_store(storage)
    before = store.read_file(VALID_PATH)
    old = "old" if "old" in body else "café"
    new = "NEW" if old == "old" else "CAFÉ"

    result = store.replace_fact(VALID_PATH, old, new, before.version, source="src")

    assert result.content == body.replace(old, new, 1)


# --- US2: match-count errors -------------------------------------------------


def test_replace_fact_zero_matches_raises_with_current_content_and_version() -> None:
    """When old_string does not occur, ReplaceFactMatchError carries the
    current content, the current version, and match_count == 0, and the
    file is left unchanged (AIE-1034, US2.1).
    """
    storage = InMemoryStorage()
    _seed(storage, VALID_PATH, "no such text here", _metadata())
    store = _new_store(storage)
    before = store.read_file(VALID_PATH)

    with pytest.raises(ReplaceFactMatchError) as excinfo:
        store.replace_fact(VALID_PATH, "absent", "x", before.version, source="src")

    assert excinfo.value.path == VALID_PATH
    assert excinfo.value.content == "no such text here"
    assert excinfo.value.version == before.version
    assert excinfo.value.match_count == 0

    after = store.read_file(VALID_PATH)
    assert after.content == before.content
    assert after.version == before.version


def test_replace_fact_multiple_non_overlapping_matches_raises_with_count() -> None:
    """When old_string occurs at k >= 2 non-overlapping positions,
    ReplaceFactMatchError carries match_count == k and the file is left
    unchanged (AIE-1034, US2.2).
    """
    storage = InMemoryStorage()
    _seed(storage, VALID_PATH, "dup here and dup there and dup again", _metadata())
    store = _new_store(storage)
    before = store.read_file(VALID_PATH)

    with pytest.raises(ReplaceFactMatchError) as excinfo:
        store.replace_fact(VALID_PATH, "dup", "x", before.version, source="src")

    assert excinfo.value.match_count == 3

    after = store.read_file(VALID_PATH)
    assert after.content == before.content
    assert after.version == before.version


def test_replace_fact_overlapping_matches_counted_and_rejected() -> None:
    """Overlapping occurrences of old_string ("aa" within "aaa") count as 2
    and are rejected as a ReplaceFactMatchError (AIE-1034, US2.3).
    """
    storage = InMemoryStorage()
    _seed(storage, VALID_PATH, "aaa", _metadata())
    store = _new_store(storage)
    before = store.read_file(VALID_PATH)

    with pytest.raises(ReplaceFactMatchError) as excinfo:
        store.replace_fact(VALID_PATH, "aa", "b", before.version, source="src")

    assert excinfo.value.match_count == 2

    after = store.read_file(VALID_PATH)
    assert after.content == "aaa"
    assert after.version == before.version


def test_replace_fact_empty_old_string_raises_value_error_without_storage() -> None:
    """old_string == "" raises ValueError without calling storage
    (AIE-1034, US2.4).
    """
    stub = _StubStorage()
    store = _new_store(stub)

    with pytest.raises(ValueError):
        store.replace_fact(VALID_PATH, "", "new", VersionToken("v1"), source="src")

    assert stub.get_calls == []
    assert stub.put_if_version_calls == []


# --- US4: metadata stamping, size ceiling, path/backend errors --------------


def test_replace_fact_stamps_sources_and_last_updated_preserving_rest() -> None:
    """On success, returned and stored metadata equal the prior metadata
    except sources gains the given source and last_updated is the clock's
    value; description and aliases are unchanged (AIE-1034, US4.1).
    """
    storage = InMemoryStorage()
    meta = _metadata(description="d", aliases=("x", "y"), sources=frozenset({"existing"}))
    _seed(storage, VALID_PATH, "old text here", meta)
    store = _new_store(storage, clock=_fixed_clock)
    before = store.read_file(VALID_PATH)

    result = store.replace_fact(VALID_PATH, "old text", "new text", before.version, source="added")

    assert result.metadata.description == "d"
    assert result.metadata.aliases == ("x", "y")
    assert result.metadata.sources == frozenset({"existing", "added"})
    assert result.metadata.last_updated == FIXED_CLOCK_TIME

    reread = store.read_file(VALID_PATH)
    assert reread.metadata == result.metadata


def test_replace_fact_source_already_present_leaves_sources_unchanged() -> None:
    """When the given source is already in the stored sources, replace_fact
    leaves sources unchanged (still just that set) after the call
    (AIE-1034, US4.1).
    """
    storage = InMemoryStorage()
    meta = _metadata(sources=frozenset({"already-there"}))
    _seed(storage, VALID_PATH, "old text here", meta)
    store = _new_store(storage)
    before = store.read_file(VALID_PATH)

    result = store.replace_fact(
        VALID_PATH, "old text", "new text", before.version, source="already-there"
    )

    assert result.metadata.sources == frozenset({"already-there"})


def test_replace_fact_over_byte_ceiling_raises_oversize_and_writes_nothing() -> None:
    """Replaced content whose UTF-8 encoding exceeds max_file_bytes raises
    OversizeWriteError with the resulting size and limit; nothing is
    written (AIE-1034, US4.2).
    """
    storage = InMemoryStorage()
    _seed(storage, VALID_PATH, "old", _metadata())
    store = _new_store_with_limit(storage, max_file_bytes=10)
    before = store.read_file(VALID_PATH)

    with pytest.raises(OversizeWriteError) as excinfo:
        store.replace_fact(VALID_PATH, "old", "a" * 20, before.version, source="src")

    assert excinfo.value.path == VALID_PATH
    assert excinfo.value.size == 20
    assert excinfo.value.limit == 10

    after = store.read_file(VALID_PATH)
    assert after.content == "old"
    assert after.version == before.version


def test_replace_fact_at_exact_byte_ceiling_succeeds() -> None:
    """Replaced content whose UTF-8 encoding is exactly max_file_bytes
    succeeds (AIE-1034, US4.2).
    """
    storage = InMemoryStorage()
    _seed(storage, VALID_PATH, "old", _metadata())
    store = _new_store_with_limit(storage, max_file_bytes=10)
    before = store.read_file(VALID_PATH)

    result = store.replace_fact(VALID_PATH, "old", "a" * 10, before.version, source="src")

    assert result.content == "a" * 10
    assert len(result.content.encode("utf-8")) == 10


MALFORMED_PATHS = (
    "",
    "a/b.md",
    "user/u/a/b.txt",
    "user//a/b.md",
)


@pytest.mark.parametrize("path", MALFORMED_PATHS)
def test_replace_fact_malformed_path_raises_invalid_path_without_storage(
    path: str,
) -> None:
    """A malformed path raises NotFoundError with reason INVALID_PATH and
    never calls storage (AIE-1034, US4.3).
    """
    stub = _StubStorage()
    store = _new_store(stub)

    with pytest.raises(NotFoundError) as excinfo:
        store.replace_fact(path, "old", "new", VersionToken("v1"), source="src")

    assert excinfo.value.reason is NotFoundReason.INVALID_PATH
    assert excinfo.value.path == path
    assert stub.get_calls == []
    assert stub.put_if_version_calls == []


def test_replace_fact_no_file_raises_file_absent() -> None:
    """A well-formed path with no file raises NotFoundError with reason
    FILE_ABSENT (AIE-1034, US4.4).
    """
    storage = InMemoryStorage()
    store = _new_store(storage)

    with pytest.raises(NotFoundError) as excinfo:
        store.replace_fact(VALID_PATH, "old", "new", VersionToken("v1"), source="src")

    assert excinfo.value.reason is NotFoundReason.FILE_ABSENT


def test_replace_fact_naive_clock_raises_value_error_and_writes_nothing() -> None:
    """A clock returning a naive datetime causes replace_fact to raise
    ValueError, leaving the stored file unchanged (AIE-1034, US4.5).
    """
    storage = InMemoryStorage()
    _seed(storage, VALID_PATH, "old text here", _metadata())
    naive_store = _new_store(storage, clock=lambda: datetime(2025, 1, 1))
    before = storage.get(VALID_PATH)
    assert before is not None

    with pytest.raises(ValueError):
        naive_store.replace_fact(VALID_PATH, "old text", "new text", before.version, source="src")

    after = storage.get(VALID_PATH)
    assert after is not None
    assert after.data == before.data
    assert after.version == before.version


def test_replace_fact_propagates_backend_unavailable_from_get() -> None:
    """A BackendUnavailableError raised by storage.get() propagates
    unwrapped (AIE-1034, US4.6).
    """
    error = BackendUnavailableError(TransientReason.UNAVAILABLE)
    stub = _StubStorage(get_raises=error)
    store = _new_store(stub)

    with pytest.raises(BackendUnavailableError) as excinfo:
        store.replace_fact(VALID_PATH, "old", "new", VersionToken("v1"), source="src")

    assert excinfo.value is error


def test_replace_fact_propagates_backend_unavailable_from_put_if_version() -> None:
    """A BackendUnavailableError raised by storage.put_if_version()
    propagates unwrapped (AIE-1034, US4.6).
    """
    error = BackendUnavailableError(TransientReason.TIMEOUT)
    stub = _StubStorage(
        get_result=StoredObject(
            data=b"old text here",
            metadata=metadata_to_map(_metadata()),
            version=VersionToken("v1"),
        ),
        put_if_version_raises=error,
    )
    store = _new_store(stub)

    with pytest.raises(BackendUnavailableError) as excinfo:
        store.replace_fact(VALID_PATH, "old text", "new text", VersionToken("v1"), source="src")

    assert excinfo.value is error


def test_replace_fact_corrupt_metadata_propagates() -> None:
    """A stored object with a corrupt metadata map causes
    MetadataFormatError to propagate (AIE-1034, US4.6).
    """
    bad_map = dict(metadata_to_map(_metadata()))
    del bad_map["description"]
    stub = _StubStorage(
        get_result=StoredObject(data=b"old text here", metadata=bad_map, version=VersionToken("v1"))
    )
    store = _new_store(stub)

    with pytest.raises(MetadataFormatError) as excinfo:
        store.replace_fact(VALID_PATH, "old text", "new text", VersionToken("v1"), source="src")

    assert excinfo.value.key == "description"


def test_replace_fact_non_utf8_bytes_propagates() -> None:
    """A stored object with non-UTF-8 bytes causes UnicodeDecodeError to
    propagate (AIE-1034, US4.6).
    """
    stub = _StubStorage(
        get_result=StoredObject(
            data=b"\xff\xfe",
            metadata=metadata_to_map(_metadata()),
            version=VersionToken("v1"),
        )
    )
    store = _new_store(stub)

    with pytest.raises(UnicodeDecodeError):
        store.replace_fact(VALID_PATH, "old text", "new text", VersionToken("v1"), source="src")


def test_replace_fact_empty_source_raises_value_error_without_storage() -> None:
    """source == "" raises ValueError without calling storage (AIE-1034,
    US4.7).
    """
    stub = _StubStorage()
    store = _new_store(stub)

    with pytest.raises(ValueError):
        store.replace_fact(VALID_PATH, "old", "new", VersionToken("v1"), source="")

    assert stub.get_calls == []
    assert stub.put_if_version_calls == []


# --- Edge cases ---------------------------------------------------------------


def test_replace_fact_old_equals_new_is_a_normal_write() -> None:
    """old_string == new_string with a unique match is treated as a normal
    write: it succeeds, producing a new version with last_updated refreshed
    and content byte-identical to before (AIE-1034, edge case).
    """
    storage = InMemoryStorage()
    meta = _metadata(last_updated=datetime(2020, 1, 1, tzinfo=UTC))
    _seed(storage, VALID_PATH, "keep this text", meta)
    store = _new_store(storage, clock=_fixed_clock)
    before = store.read_file(VALID_PATH)

    result = store.replace_fact(VALID_PATH, "this text", "this text", before.version, source="src")

    assert result.content == before.content
    assert result.version != before.version
    assert result.metadata.last_updated == FIXED_CLOCK_TIME


def test_replace_fact_rejected_calls_leave_stored_file_and_version_unchanged() -> None:
    """SC-001: a call rejected for a match-count error leaves the stored
    file's content and version exactly as they were (AIE-1034, SC-001).
    """
    storage = InMemoryStorage()
    _seed(storage, VALID_PATH, "no match text", _metadata())
    store = _new_store(storage)
    before = store.read_file(VALID_PATH)

    with pytest.raises(ReplaceFactMatchError):
        store.replace_fact(VALID_PATH, "absent", "x", before.version, source="src")

    after = store.read_file(VALID_PATH)
    assert after.content == before.content
    assert after.version == before.version


# --- US3: stale expected_version against another writer's change ------------


def test_replace_fact_succeeds_when_another_writer_changed_a_different_line() -> None:
    """A caller holding a stale version succeeds when the anchor is still
    unique in the file another writer has since changed elsewhere; the
    result carries both writers' changes and a version distinct from both
    reads, and read_file agrees (AIE-1034, US3.1, SC-002).
    """
    storage = InMemoryStorage()
    meta = _metadata()
    _seed(storage, VALID_PATH, "line one\nOLD anchor\nline three", meta)
    store = _new_store(storage)
    before = store.read_file(VALID_PATH)

    other_writer_version = storage.put(
        VALID_PATH, b"line one CHANGED\nOLD anchor\nline three", metadata_to_map(meta)
    )
    assert other_writer_version != before.version

    result = store.replace_fact(
        VALID_PATH, "OLD anchor", "NEW anchor", before.version, source="src"
    )

    assert result.content == "line one CHANGED\nNEW anchor\nline three"
    assert result.version != before.version
    assert result.version != other_writer_version

    reread = store.read_file(VALID_PATH)
    assert reread.content == result.content
    assert reread.version == result.version


def test_replace_fact_raises_version_conflict_when_other_writer_removed_anchor() -> None:
    """A caller holding a stale version gets VersionConflictError, never
    ReplaceFactMatchError, when another writer has since removed the
    anchor; the error carries the other writer's content and version, and
    the file is left exactly as that writer left it (AIE-1034, US3.2).
    """
    storage = InMemoryStorage()
    meta = _metadata()
    _seed(storage, VALID_PATH, "OLD anchor here", meta)
    store = _new_store(storage)
    before = store.read_file(VALID_PATH)

    other_writer_version = storage.put(VALID_PATH, b"anchor is gone", metadata_to_map(meta))

    with pytest.raises(VersionConflictError) as excinfo:
        store.replace_fact(VALID_PATH, "OLD anchor", "NEW anchor", before.version, source="src")

    assert excinfo.value.path == VALID_PATH
    assert excinfo.value.content == "anchor is gone"
    assert excinfo.value.version == other_writer_version

    after = store.read_file(VALID_PATH)
    assert after.content == "anchor is gone"
    assert after.version == other_writer_version


def test_replace_fact_raises_version_conflict_when_other_writer_added_second_match() -> None:
    """A caller holding a stale version gets VersionConflictError, never
    ReplaceFactMatchError, when another writer has since introduced a
    second occurrence of the anchor; the error carries the other writer's
    content and version, and the file is unchanged by the call (AIE-1034,
    US3.3).
    """
    storage = InMemoryStorage()
    meta = _metadata()
    _seed(storage, VALID_PATH, "OLD anchor here", meta)
    store = _new_store(storage)
    before = store.read_file(VALID_PATH)

    other_writer_version = storage.put(
        VALID_PATH, b"OLD anchor here and OLD anchor again", metadata_to_map(meta)
    )

    with pytest.raises(VersionConflictError) as excinfo:
        store.replace_fact(VALID_PATH, "OLD anchor", "NEW anchor", before.version, source="src")

    assert excinfo.value.content == "OLD anchor here and OLD anchor again"
    assert excinfo.value.version == other_writer_version

    after = store.read_file(VALID_PATH)
    assert after.content == "OLD anchor here and OLD anchor again"
    assert after.version == other_writer_version


# --- US3: races between get() and put_if_version() --------------------------


class _RacingPutStorage:
    """Wraps InMemoryStorage, injecting a concurrent put before
    put_if_version.

    Models a second writer landing between replace_fact's get() and its
    put_if_version() (AIE-1034, T2). `race_every_call=False` races only
    before the first put_if_version call; `True` races before every call.
    Each race's resulting version is recorded in `race_versions`, in order.
    """

    def __init__(
        self,
        inner: InMemoryStorage,
        race_contents: list[str],
        race_metadata: Mapping[str, str],
        *,
        race_every_call: bool = False,
    ) -> None:
        self._inner = inner
        self._race_contents = race_contents
        self._race_metadata = race_metadata
        self._race_every_call = race_every_call
        self.put_if_version_calls = 0
        self.race_versions: list[VersionToken] = []

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
        should_race = self._race_every_call or self.put_if_version_calls == 1
        if should_race:
            idx = self.put_if_version_calls - 1
            content = self._race_contents[idx]
            raced_version = self._inner.put(key, content.encode("utf-8"), self._race_metadata)
            self.race_versions.append(raced_version)
        return self._inner.put_if_version(key, data, metadata, expected)

    def list_page(self, prefix: str, start_after: str | None, limit: int) -> Sequence[ListedObject]:
        return self._inner.list_page(prefix, start_after, limit)

    def delete_if_version(self, key: str, expected: VersionToken) -> None:
        self._inner.delete_if_version(key, expected)


def test_replace_fact_reapplies_after_a_race_that_preserves_the_anchor() -> None:
    """A write landing between get() and put_if_version() causes exactly
    one retry; because the anchor is still unique in the new content,
    replace_fact re-applies its edit and succeeds, preserving the racing
    write's change in the final content (AIE-1034, US3.4, SC-002).
    """
    storage = InMemoryStorage()
    meta = _metadata()
    _seed(storage, VALID_PATH, "before OLD after", meta)
    wrapped = _RacingPutStorage(
        storage,
        race_contents=["before OLD after RACED"],
        race_metadata=metadata_to_map(meta),
    )
    store = _new_store(wrapped)
    before = store.read_file(VALID_PATH)

    result = store.replace_fact(VALID_PATH, "OLD", "NEW", before.version, source="src")

    assert result.content == "before NEW after RACED"
    assert wrapped.put_if_version_calls == 2

    reread = store.read_file(VALID_PATH)
    assert reread.content == result.content
    assert reread.version == result.version


def test_replace_fact_raises_version_conflict_when_a_race_removes_the_anchor() -> None:
    """A write landing between get() and put_if_version() that removes the
    anchor causes VersionConflictError carrying the racing write's content
    and version, not a successful retry (AIE-1034, US3.4b).
    """
    storage = InMemoryStorage()
    meta = _metadata()
    _seed(storage, VALID_PATH, "before OLD after", meta)
    wrapped = _RacingPutStorage(
        storage,
        race_contents=["before RACED after, no anchor"],
        race_metadata=metadata_to_map(meta),
    )
    store = _new_store(wrapped)
    before = store.read_file(VALID_PATH)

    with pytest.raises(VersionConflictError) as excinfo:
        store.replace_fact(VALID_PATH, "OLD", "NEW", before.version, source="src")

    assert excinfo.value.content == "before RACED after, no anchor"
    assert excinfo.value.version == wrapped.race_versions[0]


def test_replace_fact_exhausts_three_attempts_when_every_put_races() -> None:
    """When a racing write lands before every put_if_version call,
    replace_fact makes exactly 3 put attempts and then raises
    VersionConflictError carrying the content and version it read at the
    start of its last attempt (AIE-1034, US3.5).
    """
    storage = InMemoryStorage()
    meta = _metadata()
    _seed(storage, VALID_PATH, "before OLD after", meta)
    wrapped = _RacingPutStorage(
        storage,
        race_contents=[
            "before OLD after race1",
            "before OLD after race2",
            "before OLD after race3",
        ],
        race_metadata=metadata_to_map(meta),
        race_every_call=True,
    )
    store = _new_store(wrapped)
    before = store.read_file(VALID_PATH)

    with pytest.raises(VersionConflictError) as excinfo:
        store.replace_fact(VALID_PATH, "OLD", "NEW", before.version, source="src")

    assert wrapped.put_if_version_calls == 3
    assert excinfo.value.content == "before OLD after race2"
    assert excinfo.value.version == wrapped.race_versions[1]


def test_replace_fact_retry_with_the_same_version_sees_its_own_prior_write() -> None:
    """A retried call whose earlier attempt actually succeeded (but whose
    response was lost) raises VersionConflictError whose content equals
    what that earlier attempt wrote, because old_string no longer matches
    (AIE-1034, US3.6).
    """
    storage = InMemoryStorage()
    meta = _metadata()
    _seed(storage, VALID_PATH, "before OLD after", meta)
    store = _new_store(storage)
    before = store.read_file(VALID_PATH)

    first = store.replace_fact(VALID_PATH, "OLD", "NEW", before.version, source="src")
    assert first.content == "before NEW after"

    with pytest.raises(VersionConflictError) as excinfo:
        store.replace_fact(VALID_PATH, "OLD", "NEWER", before.version, source="src")

    assert excinfo.value.content == first.content
    assert excinfo.value.version == first.version


# --- US4.4: file deleted mid-retry -------------------------------------------


class _DeletableStorage(InMemoryStorage):
    """InMemoryStorage plus a delete primitive, for simulating a concurrent
    delete landing mid-retry (AIE-1034, US4.4).
    """

    def delete(self, key: str) -> None:
        self._objects.pop(key, None)


class _DeleteBeforePutStorage:
    """Wraps a _DeletableStorage, deleting the object before the first
    put_if_version call, to simulate a delete landing between a failed
    write and the retry's re-read (AIE-1034, US4.4).
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
        if self.put_if_version_calls == 1:
            self._inner.delete(key)
        return self._inner.put_if_version(key, data, metadata, expected)

    def list_page(self, prefix: str, start_after: str | None, limit: int) -> Sequence[ListedObject]:
        return self._inner.list_page(prefix, start_after, limit)

    def delete_if_version(self, key: str, expected: VersionToken) -> None:
        self._inner.delete_if_version(key, expected)


def test_replace_fact_raises_file_absent_when_file_deleted_mid_retry() -> None:
    """A delete landing between a failed put_if_version and the retry's
    re-read raises NotFoundError with reason FILE_ABSENT, not a version
    conflict or a crash (AIE-1034, US4.4).
    """
    storage = _DeletableStorage()
    meta = _metadata()
    _seed(storage, VALID_PATH, "before OLD after", meta)
    wrapped = _DeleteBeforePutStorage(storage)
    store = _new_store(wrapped)
    before = store.read_file(VALID_PATH)

    with pytest.raises(NotFoundError) as excinfo:
        store.replace_fact(VALID_PATH, "OLD", "NEW", before.version, source="src")

    assert excinfo.value.reason is NotFoundReason.FILE_ABSENT
    assert excinfo.value.path == VALID_PATH


# --- Edge case: an expected_version token no write ever produced ------------


def test_replace_fact_treats_an_unminted_expected_version_as_stale_and_succeeds() -> None:
    """An expected_version token no write ever produced is treated as
    stale, not a parse error: with a unique anchor the call still
    succeeds (AIE-1034, edge case).
    """
    storage = InMemoryStorage()
    _seed(storage, VALID_PATH, "before OLD after", _metadata())
    store = _new_store(storage)
    bogus = VersionToken("not-a-real-token")

    result = store.replace_fact(VALID_PATH, "OLD", "NEW", bogus, source="src")

    assert result.content == "before NEW after"


def test_replace_fact_unminted_expected_version_with_zero_matches_raises_version_conflict() -> None:
    """The same never-minted expected_version token, when old_string does
    not match, raises VersionConflictError rather than ReplaceFactMatchError
    or a parse error (AIE-1034, edge case).
    """
    storage = InMemoryStorage()
    _seed(storage, VALID_PATH, "no such text", _metadata())
    store = _new_store(storage)
    bogus = VersionToken("not-a-real-token")

    with pytest.raises(VersionConflictError) as excinfo:
        store.replace_fact(VALID_PATH, "absent", "x", bogus, source="src")

    assert excinfo.value.content == "no such text"


# --- Optional aliases and description -----------------------------------------

F_BODY = "- [stated] beta\n"


def _f_metadata(description: str = "d", aliases: tuple[str, ...] = ("x", "y")) -> FileMetadata:
    return _metadata(description=description, aliases=aliases, sources=frozenset({"s1"}))


class _CountingStorage(InMemoryStorage):
    """InMemoryStorage that records every put_if_version call."""

    def __init__(self) -> None:
        super().__init__()
        self.put_if_version_calls: list[tuple[bytes, dict[str, str]]] = []

    def put_if_version(
        self,
        key: str,
        data: bytes,
        metadata: Mapping[str, str],
        expected: VersionToken | None,
    ) -> VersionToken:
        self.put_if_version_calls.append((data, dict(metadata)))
        return super().put_if_version(key, data, metadata, expected)


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


def _seed_f(storage: InMemoryStorage) -> tuple[MemoryStore, VersionToken]:
    _seed(storage, VALID_PATH, F_BODY, _f_metadata())
    store = _new_store(storage)
    return store, store.read_file(VALID_PATH).version


def _assert_exact_aliases(aliases: object, expected: tuple[str, ...]) -> None:
    assert type(aliases) is tuple
    members = cast(tuple[object, ...], aliases)
    assert all(type(a) is str for a in members)
    assert members == expected


def test_replace_fact_unions_aliases_and_replaces_description_in_one_put() -> None:
    """Content is replaced, aliases are unioned with duplicates dropped, the
    description is replaced, sources gains the source, and one put_if_version
    carries it all (AIE-1151, US2.1).
    """
    storage = _CountingStorage()
    store, v = _seed_f(storage)

    result = store.replace_fact(
        VALID_PATH, "beta", "gamma", v, source="src", aliases=["y", "z", "z"], description="d2"
    )

    assert result.content == "- [stated] gamma\n"
    _assert_exact_aliases(result.metadata.aliases, ("x", "y", "z"))
    assert result.metadata.description == "d2"
    assert result.metadata.sources == frozenset({"s1", "src"})
    assert result.metadata.last_updated == FIXED_CLOCK_TIME
    assert storage.put_if_version_calls == [
        (b"- [stated] gamma\n", dict(metadata_to_map(result.metadata)))
    ]
    assert store.read_file(VALID_PATH).metadata == result.metadata


def test_replace_fact_normalizes_str_subclass_alias_and_description() -> None:
    """Lying str-subclass aliases and description are stored as exact str, and
    alias dedup compares exact strings (AIE-1151, US2.1, US1.6, US1.11).
    """
    storage = InMemoryStorage()
    store, v = _seed_f(storage)

    result = store.replace_fact(
        VALID_PATH,
        "beta",
        "gamma",
        v,
        source="src",
        aliases=[_LyingStr("q"), "q"],
        description=_LyingStr("d2"),
    )

    _assert_exact_aliases(result.metadata.aliases, ("x", "y", "q"))
    assert type(result.metadata.description) is str
    assert result.metadata.description == "d2"


@pytest.mark.parametrize(
    "kwargs",
    [{}, {"aliases": None, "description": None}],
    ids=["omitted", "explicit-none"],
)
def test_replace_fact_absent_arguments_leave_metadata_unchanged(
    kwargs: dict[str, object],
) -> None:
    """Omitted or None arguments leave metadata other than sources and
    last_updated unchanged (AIE-1151, US2.2).
    """
    storage = InMemoryStorage()
    store, v = _seed_f(storage)
    call = cast(Callable[..., MemoryFile], store.replace_fact)

    result = call(VALID_PATH, "beta", "gamma", v, source="src", **kwargs)

    expected = replace(
        _f_metadata(), sources=frozenset({"s1", "src"}), last_updated=FIXED_CLOCK_TIME
    )
    assert result.content == "- [stated] gamma\n"
    assert result.metadata == expected
    assert store.read_file(VALID_PATH).metadata == expected


def test_replace_fact_stale_reapply_unions_onto_current_aliases() -> None:
    """A stale-token replace_fact whose match is still unique unions its aliases
    onto the aliases another writer committed since the caller's read
    (AIE-1151, US2.3).
    """
    storage = InMemoryStorage()
    store, stale = _seed_f(storage)
    storage.put(
        VALID_PATH,
        (F_BODY + "- [stated] other\n").encode("utf-8"),
        metadata_to_map(_f_metadata(aliases=("x", "y", "w"))),
    )

    result = store.replace_fact(VALID_PATH, "beta", "gamma", stale, source="src", aliases=["z"])

    assert result.content == "- [stated] gamma\n- [stated] other\n"
    _assert_exact_aliases(result.metadata.aliases, ("x", "y", "w", "z"))
    assert store.read_file(VALID_PATH).metadata.aliases == ("x", "y", "w", "z")


def test_replace_fact_union_uses_the_committing_attempts_read() -> None:
    """When the first put fails because a concurrent write changed the aliases,
    the union is computed on the object read by the attempt that commits
    (AIE-1151, US2.4).
    """
    storage = InMemoryStorage()
    _seed(storage, VALID_PATH, F_BODY, _f_metadata())
    wrapped = _RacingPutStorage(
        storage,
        race_contents=[F_BODY],
        race_metadata=metadata_to_map(_f_metadata(aliases=("x", "y", "q"))),
    )
    store = _new_store(wrapped)
    before = store.read_file(VALID_PATH)

    result = store.replace_fact(
        VALID_PATH, "beta", "gamma", before.version, source="src", aliases=["z"]
    )

    assert wrapped.put_if_version_calls == 2
    _assert_exact_aliases(result.metadata.aliases, ("x", "y", "q", "z"))
    assert store.read_file(VALID_PATH).metadata.aliases == ("x", "y", "q", "z")


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

_BAD_ARGUMENTS: list[tuple[object, object, type[Exception], str]] = [
    *(
        (a, None, TypeError, f"aliases must be a sequence of str, not {type(a).__name__}")
        for a in BAD_ALIAS_CONTAINERS
    ),
    (["a", 5], None, TypeError, "aliases entry must be str, got int"),
    (None, 5, TypeError, "description must be a str, not int"),
    (None, "a\nb", ValueError, "description must not contain a newline or carriage return"),
    (None, "a\rb", ValueError, "description must not contain a newline or carriage return"),
]
_BAD_ARGUMENT_IDS = [
    *(f"aliases-{i}" for i in BAD_ALIAS_CONTAINER_IDS),
    "alias-entry-int",
    "description-int",
    "description-lf",
    "description-cr",
]


@pytest.mark.parametrize(
    ("aliases", "description", "error", "message"), _BAD_ARGUMENTS, ids=_BAD_ARGUMENT_IDS
)
def test_replace_fact_bad_aliases_or_description_raise_without_storage(
    aliases: object, description: object, error: type[Exception], message: str
) -> None:
    """Bad aliases or description raise the same errors and messages as
    append_line, without calling storage (AIE-1151, US2.5).
    """
    stub = _StubStorage()
    store = _new_store(stub)

    with pytest.raises(error) as excinfo:
        store.replace_fact(
            VALID_PATH,
            "beta",
            "gamma",
            VersionToken("v1"),
            source="src",
            aliases=cast(Sequence[str] | None, aliases),
            description=cast(str | None, description),
        )

    assert type(excinfo.value) is error
    assert str(excinfo.value) == message
    assert stub.get_calls == []
    assert stub.put_if_version_calls == []


def test_replace_fact_invalid_path_wins_over_bad_aliases() -> None:
    """An invalid path raises NotFoundError(INVALID_PATH) before bad aliases are
    checked (AIE-1151, US2.6).
    """
    stub = _StubStorage()
    store = _new_store(stub)

    with pytest.raises(NotFoundError) as excinfo:
        store.replace_fact(
            "a/b.md",
            "",
            "gamma",
            VersionToken("v1"),
            source="",
            aliases=cast(Sequence[str], "ab"),
            description=cast(str, 5),
        )

    assert excinfo.value.reason is NotFoundReason.INVALID_PATH
    assert stub.get_calls == []


@pytest.mark.parametrize(
    ("old_string", "source"), [("", "src"), ("beta", "")], ids=["empty-old", "empty-source"]
)
def test_replace_fact_existing_value_error_wins_over_bad_aliases(
    old_string: str, source: str
) -> None:
    """An empty old_string or source raises the existing ValueError before bad
    aliases or description are checked (AIE-1151, US2.6).
    """
    stub = _StubStorage()
    store = _new_store(stub)

    with pytest.raises(ValueError) as excinfo:
        store.replace_fact(
            VALID_PATH,
            old_string,
            "gamma",
            VersionToken("v1"),
            source=source,
            aliases=cast(Sequence[str], "ab"),
            description=cast(str, 5),
        )

    assert type(excinfo.value) is ValueError
    assert str(excinfo.value) == "old_string and source must be non-empty"
    assert stub.get_calls == []


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
def test_replace_fact_new_argument_errors_in_order(
    aliases: object, description: object, error: type[Exception], message: str
) -> None:
    """aliases TypeError precedes description TypeError, which precedes the
    description ValueError (AIE-1151, US2.6).
    """
    stub = _StubStorage()
    store = _new_store(stub)

    with pytest.raises(error) as excinfo:
        store.replace_fact(
            VALID_PATH,
            "beta",
            "gamma",
            VersionToken("v1"),
            source="src",
            aliases=cast(Sequence[str], aliases),
            description=cast(str, description),
        )

    assert str(excinfo.value) == message
    assert stub.get_calls == []


def test_replace_fact_match_error_leaves_content_and_metadata_unchanged() -> None:
    """A ReplaceFactMatchError outcome with aliases and description leaves the
    stored bytes, metadata, and version unchanged (AIE-1151, US2.7).
    """
    storage = InMemoryStorage()
    store, v = _seed_f(storage)
    before = storage.get(VALID_PATH)

    with pytest.raises(ReplaceFactMatchError):
        store.replace_fact(
            VALID_PATH, "absent", "gamma", v, source="src", aliases=["z"], description="d2"
        )

    assert storage.get(VALID_PATH) == before


def test_replace_fact_version_conflict_leaves_content_and_metadata_unchanged() -> None:
    """A VersionConflictError outcome with aliases and description leaves the
    file exactly as the other writer left it (AIE-1151, US2.7).
    """
    storage = InMemoryStorage()
    store, stale = _seed_f(storage)
    storage.put(VALID_PATH, b"- [stated] gone\n", metadata_to_map(_f_metadata()))
    before = storage.get(VALID_PATH)

    with pytest.raises(VersionConflictError):
        store.replace_fact(
            VALID_PATH, "beta", "gamma", stale, source="src", aliases=["z"], description="d2"
        )

    assert storage.get(VALID_PATH) == before


def test_replace_fact_stale_reapply_overwrites_concurrent_description() -> None:
    """A stale-token re-apply with a description overwrites a description
    committed since the caller's read, with no conflict (AIE-1151, US2.8).
    """
    storage = InMemoryStorage()
    store, stale = _seed_f(storage)
    storage.put(VALID_PATH, F_BODY.encode("utf-8"), metadata_to_map(_f_metadata(description="q")))

    result = store.replace_fact(VALID_PATH, "beta", "gamma", stale, source="src", description="d2")

    assert result.metadata.description == "d2"
    assert store.read_file(VALID_PATH).metadata.description == "d2"


def test_replace_fact_old_equals_new_with_aliases_changes_only_metadata() -> None:
    """old_string == new_string with aliases leaves content unchanged, unions the
    aliases, and produces a new version through one conditional put
    (AIE-1151, US2.9).
    """
    storage = _CountingStorage()
    store, v = _seed_f(storage)

    result = store.replace_fact(VALID_PATH, "beta", "beta", v, source="src", aliases=["z"])

    assert result.content == F_BODY
    _assert_exact_aliases(result.metadata.aliases, ("x", "y", "z"))
    assert result.version != v
    assert len(storage.put_if_version_calls) == 1
