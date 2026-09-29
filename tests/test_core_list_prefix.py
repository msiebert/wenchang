"""Failing tests for MemoryStore.list_prefix, ahead of src/wenchang/core.py
implementing it.

Covers AIE-1035, US1 through US3 and edge cases for paginated prefix
listing.
"""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

import pytest

from wenchang.core import (
    DEFAULT_LIST_PAGE_SIZE,
    FileEntry,
    ListCursor,
    ListPage,
    MemoryStore,
)
from wenchang.errors import BackendUnavailableError, NotFoundError, NotFoundReason, TransientReason
from wenchang.file_format import FileMetadata, MetadataFormatError, metadata_to_map
from wenchang.storage import ListedObject, Storage, StoredObject
from wenchang.storage.memory import InMemoryStorage
from wenchang.version_token import VersionToken

pytestmark = pytest.mark.unit


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


def _new_store(storage: Storage, *, list_page_size: int = DEFAULT_LIST_PAGE_SIZE) -> MemoryStore:
    return MemoryStore(storage, list_page_size=list_page_size)


class _StubStorage:
    """Hand-written Storage stub whose list_page is scripted; get/put fail
    the test if called, since list_prefix must never read content.
    """

    def __init__(
        self,
        list_page_result: Sequence[ListedObject] | None = None,
        list_page_raises: BaseException | None = None,
    ) -> None:
        self._list_page_result: Sequence[ListedObject] = (
            list_page_result if list_page_result is not None else []
        )
        self._list_page_raises = list_page_raises
        self.list_page_calls: list[tuple[str, str | None, int]] = []

    def get(self, key: str) -> StoredObject | None:
        raise AssertionError("list_prefix must not call storage.get")

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
        self.list_page_calls.append((prefix, start_after, limit))
        if self._list_page_raises is not None:
            raise self._list_page_raises
        return self._list_page_result

    def delete_if_version(self, key: str, expected: VersionToken) -> None:
        raise NotImplementedError("not exercised by these tests")


class _NeverCalledStorage:
    """Storage stub whose list_page fails the test if invoked at all."""

    def get(self, key: str) -> StoredObject | None:
        raise AssertionError("must not call storage.get")

    def put(self, key: str, data: bytes, metadata: Mapping[str, str]) -> VersionToken:
        raise AssertionError("must not call storage.put")

    def put_if_version(
        self,
        key: str,
        data: bytes,
        metadata: Mapping[str, str],
        expected: VersionToken | None,
    ) -> VersionToken:
        raise AssertionError("must not call storage.put_if_version")

    def list_page(self, prefix: str, start_after: str | None, limit: int) -> Sequence[ListedObject]:
        raise AssertionError("must not consult storage for an invalid prefix")

    def delete_if_version(self, key: str, expected: VersionToken) -> None:
        raise AssertionError("must not call storage.delete_if_version")


class _DeletableStorage(InMemoryStorage):
    """InMemoryStorage plus a delete primitive, for simulating a concurrent
    write/delete landing between two pages (AIE-1035, US2.3).
    """

    def delete(self, key: str) -> None:
        self._objects.pop(key, None)


# --- US1: list a prefix in one page ------------------------------------------


def test_list_prefix_returns_entries_in_order_with_no_next_cursor() -> None:
    """Two files under a prefix are returned as FileEntry tuples in path
    order with next_cursor None (AIE-1035, US1.1).
    """
    storage = InMemoryStorage()
    m1, m2 = _metadata(description="m1"), _metadata(description="m2")
    v1 = _seed(storage, "a/e/x/1.md", "one", m1)
    v2 = _seed(storage, "a/e/x/2.md", "two", m2)
    store = _new_store(storage)

    page = store.list_prefix("a/e/x/")

    assert isinstance(page, ListPage)
    assert page.entries == (
        FileEntry("a/e/x/1.md", m1, v1),
        FileEntry("a/e/x/2.md", m2, v2),
    )
    assert page.next_cursor is None


def test_list_prefix_recurses_into_all_areas_under_a_shorter_prefix() -> None:
    """Listing a shorter prefix returns every file under both of its areas
    but none under a sibling area (AIE-1035, US1.2).
    """
    storage = InMemoryStorage()
    _seed(storage, "a/e/x/1.md", "x1", _metadata())
    _seed(storage, "a/e/y/1.md", "y1", _metadata())
    _seed(storage, "a/f/x/1.md", "f1", _metadata())
    store = _new_store(storage)

    page = store.list_prefix("a/e/")

    paths = {entry.path for entry in page.entries}
    assert paths == {"a/e/x/1.md", "a/e/y/1.md"}


def test_list_prefix_is_segment_aligned_not_substring_match() -> None:
    """A sibling area whose name merely starts with the listed area's name
    is not returned (AIE-1035, US1.3).
    """
    storage = InMemoryStorage()
    _seed(storage, "a/e/x/1.md", "x1", _metadata())
    _seed(storage, "a/e/xy/1.md", "xy1", _metadata())
    store = _new_store(storage)

    page = store.list_prefix("a/e/x/")

    assert page.entries == tuple(e for e in page.entries if e.path == "a/e/x/1.md")
    assert "a/e/xy/1.md" not in {e.path for e in page.entries}


def test_list_prefix_with_no_files_returns_empty_page() -> None:
    """A well-formed prefix with nothing under it returns entries == () and
    next_cursor is None, without error (AIE-1035, US1.4).
    """
    storage = InMemoryStorage()
    store = _new_store(storage)

    page = store.list_prefix("a/e/x/")

    assert page.entries == ()
    assert page.next_cursor is None


def test_list_prefix_entries_agree_with_read_file() -> None:
    """Each entry's metadata and version equal what read_file returns for
    that path (AIE-1035, US1.5).
    """
    storage = InMemoryStorage()
    _seed(storage, "a/e/x/1.md", "body", _metadata(description="agree"))
    store = _new_store(storage)

    page = store.list_prefix("a/e/x/")
    read = store.read_file("a/e/x/1.md")

    assert len(page.entries) == 1
    entry = page.entries[0]
    assert entry.metadata == read.metadata
    assert entry.version == read.version


def test_list_prefix_orders_unicode_names_by_ascending_code_point() -> None:
    """Files whose names differ only in multi-byte unicode are ordered by
    ascending code point of the path (AIE-1035, US1.6).
    """
    storage = InMemoryStorage()
    # "é" (U+00E9) sorts after "e" (U+0065); "日" (U+65E5) sorts after both.
    _seed(storage, "a/e/x/日.md", "jp", _metadata())
    _seed(storage, "a/e/x/e.md", "ascii", _metadata())
    _seed(storage, "a/e/x/é.md", "accent", _metadata())
    store = _new_store(storage)

    page = store.list_prefix("a/e/x/")

    assert [entry.path for entry in page.entries] == [
        "a/e/x/e.md",
        "a/e/x/é.md",
        "a/e/x/日.md",
    ]


# --- US2: pagination ----------------------------------------------------------


def test_list_prefix_paginates_across_repeated_cursors() -> None:
    """With list_page_size=2 and 5 files, draining pages via next_cursor
    yields 2, 2, 1 entries covering every file exactly once, in ascending
    order (AIE-1035, US2.1).
    """
    storage = InMemoryStorage()
    paths = [f"a/e/x/{i}.md" for i in range(1, 6)]
    for path in paths:
        _seed(storage, path, path, _metadata())
    store = _new_store(storage, list_page_size=2)

    pages: list[ListPage] = []
    cursor: ListCursor | None = None
    while True:
        page = store.list_prefix("a/e/x/", cursor)
        pages.append(page)
        cursor = page.next_cursor
        if cursor is None:
            break

    assert [len(p.entries) for p in pages] == [2, 2, 1]
    seen = [entry.path for p in pages for entry in p.entries]
    assert seen == sorted(paths)
    assert len(seen) == len(set(seen))


def test_list_prefix_exact_multiple_of_page_size_has_no_trailing_empty_page() -> None:
    """With list_page_size=2 and exactly 4 files, the second page has 2
    entries and next_cursor is None: no trailing empty page (AIE-1035,
    US2.2).
    """
    storage = InMemoryStorage()
    paths = [f"a/e/x/{i}.md" for i in range(1, 5)]
    for path in paths:
        _seed(storage, path, path, _metadata())
    store = _new_store(storage, list_page_size=2)

    first = store.list_prefix("a/e/x/")
    assert len(first.entries) == 2
    assert first.next_cursor is not None

    second = store.list_prefix("a/e/x/", first.next_cursor)
    assert len(second.entries) == 2
    assert second.next_cursor is None


def test_list_prefix_reflects_concurrent_write_and_delete_between_pages() -> None:
    """A cursor from page 1: a file sorting after it is written and one
    sorting before it is deleted before page 2 is fetched; page 2 includes
    the new file, and every file present throughout is returned exactly
    once across all pages (AIE-1035, US2.3).
    """
    storage = _DeletableStorage()
    _seed(storage, "a/e/x/1.md", "one", _metadata())
    _seed(storage, "a/e/x/2.md", "two", _metadata())
    _seed(storage, "a/e/x/3.md", "three", _metadata())
    store = _new_store(storage, list_page_size=2)

    first = store.list_prefix("a/e/x/")
    assert [e.path for e in first.entries] == ["a/e/x/1.md", "a/e/x/2.md"]
    assert first.next_cursor is not None

    storage.delete("a/e/x/1.md")
    _seed(storage, "a/e/x/4.md", "four", _metadata())

    second = store.list_prefix("a/e/x/", first.next_cursor)

    all_seen = [e.path for e in first.entries] + [e.path for e in second.entries]
    assert "a/e/x/4.md" in {e.path for e in second.entries}
    assert len(all_seen) == len(set(all_seen))
    # Every file present throughout (1, 2, 3) appears exactly once overall.
    assert set(all_seen) >= {"a/e/x/2.md", "a/e/x/3.md"}


@pytest.mark.parametrize(
    "bad_cursor",
    ["not-a-cursor", "", "!!!"],
)
def test_list_prefix_rejects_cursor_strings_it_never_issued(bad_cursor: str) -> None:
    """A cursor string not produced by list_prefix raises ValueError
    (AIE-1035, US2.4).
    """
    storage = InMemoryStorage()
    _seed(storage, "a/e/x/1.md", "one", _metadata())
    store = _new_store(storage)

    with pytest.raises(ValueError):
        store.list_prefix("a/e/x/", ListCursor(bad_cursor))


def test_list_prefix_rejects_cursor_issued_for_a_different_prefix() -> None:
    """A cursor from list_prefix("a/e/x/") raises ValueError when passed
    with a different prefix it was not issued for (AIE-1035, US2.4).
    """
    storage = InMemoryStorage()
    _seed(storage, "a/e/x/1.md", "one", _metadata())
    _seed(storage, "a/e/x/2.md", "two", _metadata())
    _seed(storage, "a/f/1.md", "other", _metadata())
    store = _new_store(storage, list_page_size=1)

    first = store.list_prefix("a/e/x/")
    assert first.next_cursor is not None

    with pytest.raises(ValueError):
        store.list_prefix("a/f/", first.next_cursor)


@pytest.mark.parametrize("list_page_size", [0, -1])
def test_memory_store_rejects_non_positive_list_page_size(list_page_size: int) -> None:
    """Constructing MemoryStore with list_page_size <= 0 raises ValueError
    (AIE-1035, US2.5).
    """
    storage = InMemoryStorage()

    with pytest.raises(ValueError):
        MemoryStore(storage, list_page_size=list_page_size)


def test_memory_store_default_list_page_size_is_100_and_named_constant() -> None:
    """DEFAULT_LIST_PAGE_SIZE == 100, and a store built without an explicit
    list_page_size pages 101 files as a 100-entry page with a non-None
    cursor (AIE-1035, US2.5).
    """
    assert DEFAULT_LIST_PAGE_SIZE == 100

    storage = InMemoryStorage()
    for i in range(101):
        _seed(storage, f"a/e/x/{i:03d}.md", str(i), _metadata())
    store = MemoryStore(storage)

    page = store.list_prefix("a/e/x/")

    assert len(page.entries) == 100
    assert page.next_cursor is not None


# --- US3: prefix validation and robustness -----------------------------------


@pytest.mark.parametrize(
    "prefix",
    ["", "a", "a/e/x", "a//", "a/../", "a/e/x/y/", "a/e/x/1.md"],
)
def test_list_prefix_rejects_malformed_prefix_without_consulting_storage(prefix: str) -> None:
    """A malformed prefix raises NotFoundError with reason INVALID_PATH and
    .path equal to the prefix given, without ever calling storage.list_page
    (AIE-1035, US3.1).
    """
    store = MemoryStore(_NeverCalledStorage())

    with pytest.raises(NotFoundError) as excinfo:
        store.list_prefix(prefix)

    assert excinfo.value.reason is NotFoundReason.INVALID_PATH
    assert excinfo.value.path == prefix


def test_list_prefix_omits_malformed_keys_but_still_reaches_every_valid_file() -> None:
    """Objects under the prefix whose key is not a well-formed memory path
    are omitted from entries, and pagination still reaches every
    well-formed file (AIE-1035, US3.2).
    """
    storage = InMemoryStorage()
    _seed(storage, "a/e/x/1.md", "one", _metadata())
    storage.put("a/e/x/notes.txt", b"not markdown", metadata_to_map(_metadata()))
    storage.put("a/e/x/deep/1.md", b"too deep", metadata_to_map(_metadata()))
    _seed(storage, "a/e/x/2.md", "two", _metadata())
    store = _new_store(storage)

    page = store.list_prefix("a/e/x/")

    assert [e.path for e in page.entries] == ["a/e/x/1.md", "a/e/x/2.md"]
    assert page.next_cursor is None


def test_list_prefix_page_of_only_malformed_keys_can_be_short_with_a_cursor() -> None:
    """With list_page_size=2, a page whose raw keys are all malformed may
    have fewer entries than list_page_size (even zero) while next_cursor is
    still non-None, and draining still yields every valid file (AIE-1035,
    US3.2, edge case).
    """
    storage = InMemoryStorage()
    # Two malformed keys sort between "1.md" and "2.md" to force a
    # malformed-only page under list_page_size=2.
    storage.put("a/e/x/1.md-a-bad.txt", b"bad1", metadata_to_map(_metadata()))
    storage.put("a/e/x/1.md-b-bad.txt", b"bad2", metadata_to_map(_metadata()))
    _seed(storage, "a/e/x/0.md", "zero", _metadata())
    _seed(storage, "a/e/x/2.md", "two", _metadata())
    store = _new_store(storage, list_page_size=2)

    all_paths: list[str] = []
    cursor: ListCursor | None = None
    saw_short_page_with_cursor = False
    for _ in range(10):
        page = store.list_prefix("a/e/x/", cursor)
        all_paths.extend(e.path for e in page.entries)
        if len(page.entries) < 2 and page.next_cursor is not None:
            saw_short_page_with_cursor = True
        cursor = page.next_cursor
        if cursor is None:
            break

    assert saw_short_page_with_cursor
    assert sorted(all_paths) == ["a/e/x/0.md", "a/e/x/2.md"]
    assert len(all_paths) == len(set(all_paths))


def test_list_prefix_propagates_metadata_format_error_for_corrupt_metadata() -> None:
    """An object under the prefix with corrupt metadata causes
    MetadataFormatError to propagate (AIE-1035, US3.3).
    """
    storage = InMemoryStorage()
    bad_map = dict(metadata_to_map(_metadata()))
    del bad_map["description"]
    storage.put("a/e/x/1.md", b"body", bad_map)
    store = _new_store(storage)

    with pytest.raises(MetadataFormatError) as excinfo:
        store.list_prefix("a/e/x/")

    assert excinfo.value.key == "description"


def test_list_prefix_propagates_backend_unavailable_from_list_page() -> None:
    """A BackendUnavailableError raised by storage.list_page() propagates
    as the same exception object, unwrapped (AIE-1035, US3.4).
    """
    error = BackendUnavailableError(TransientReason.UNAVAILABLE)
    stub = _StubStorage(list_page_raises=error)
    store = _new_store(stub)

    with pytest.raises(BackendUnavailableError) as excinfo:
        store.list_prefix("a/e/x/")

    assert excinfo.value is error


def test_list_prefix_never_reads_object_content() -> None:
    """list_prefix never calls storage.get: content is not read
    (AIE-1035, constraint).
    """
    storage = InMemoryStorage()
    _seed(storage, "a/e/x/1.md", "body", _metadata())
    stub = _StubStorage(
        list_page_result=[
            ListedObject(
                key="a/e/x/1.md",
                metadata=metadata_to_map(_metadata()),
                version=VersionToken("1"),
            )
        ]
    )
    store = _new_store(stub)

    page = store.list_prefix("a/e/x/")

    assert len(page.entries) == 1
    assert stub.list_page_calls == [("a/e/x/", None, DEFAULT_LIST_PAGE_SIZE + 1)]
