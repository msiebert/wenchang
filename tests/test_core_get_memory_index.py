"""Tests for MemoryStore.get_memory_index.

Covers AIE-1046: US1 (fan-out and merge), US2 (ordering), US3.2-3.8 (byte
cap), and US4 (constructor settings and input validation).
"""

from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from wenchang.core import (
    DEFAULT_INDEX_MAX_BYTES,
    CappedPrefix,
    FileEntry,
    ListCursor,
    ListPage,
    MemoryIndex,
    MemoryStore,
    index_entry_bytes,
)
from wenchang.errors import BackendUnavailableError, TransientReason
from wenchang.file_format import FileMetadata, MetadataFormatError, metadata_to_map
from wenchang.storage import ListedObject, Storage, StoredObject
from wenchang.storage.memory import InMemoryStorage
from wenchang.version_token import VersionToken

pytestmark = pytest.mark.unit

T1 = datetime(2024, 1, 1, tzinfo=UTC)
T2 = datetime(2024, 2, 1, tzinfo=UTC)
T3 = datetime(2024, 3, 1, tzinfo=UTC)
T4 = datetime(2024, 4, 1, tzinfo=UTC)
T5 = datetime(2024, 5, 1, tzinfo=UTC)

SCOPE_MAP: dict[str, str] = {"user": "u-1", "org": "o-9"}


def _metadata(last_updated: datetime, description: str = "d") -> FileMetadata:
    return FileMetadata(
        description=description,
        aliases=(),
        sources=frozenset({"t"}),
        last_updated=last_updated,
    )


def _seed(
    storage: InMemoryStorage, path: str, last_updated: datetime, description: str = "d"
) -> VersionToken:
    return storage.put(path, b"body", metadata_to_map(_metadata(last_updated, description)))


def _new_store(storage: Storage, **settings: Any) -> MemoryStore:
    return MemoryStore(storage, clock=lambda: T1, **settings)


def _entry(store: MemoryStore, path: str) -> FileEntry:
    """The FileEntry list_prefix reports for `path`, drained across pages."""
    area_prefix = path.rsplit("/", 1)[0] + "/"
    cursor: ListCursor | None = None
    while True:
        page = MemoryStore.list_prefix(store, area_prefix, cursor)
        for entry in page.entries:
            if entry.path == path:
                return entry
        cursor = page.next_cursor
        if cursor is None:
            raise AssertionError(f"{path} not listed")


def _sizes(store: MemoryStore, paths: Sequence[str]) -> list[int]:
    return [index_entry_bytes(_entry(store, p)) for p in paths]


def _paths(index: MemoryIndex) -> list[str]:
    return [e.path for e in index.entries]


def _require_scope_priority_kwarg() -> None:
    """Guard TypeError tests: an unknown kwarg would also raise TypeError."""
    assert MemoryStore(InMemoryStorage(), scope_priority=("user",)).scope_priority == ("user",)


class _NeverCalledStorage:
    """Storage stub whose every method fails the test if invoked."""

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
        raise AssertionError("must not call storage.list_page")

    def delete_if_version(self, key: str, expected: VersionToken) -> None:
        raise AssertionError("must not call storage.delete_if_version")


class _NoGetStorage(InMemoryStorage):
    """InMemoryStorage whose get fails the test: the index must not read bodies."""

    def get(self, key: str) -> StoredObject | None:
        raise AssertionError("get_memory_index must not call storage.get")


class _RecordingStorage(InMemoryStorage):
    """InMemoryStorage that records every list_page prefix, in call order."""

    def __init__(self) -> None:
        super().__init__()
        self.list_page_prefixes: list[str] = []

    def list_page(self, prefix: str, start_after: str | None, limit: int) -> Sequence[ListedObject]:
        self.list_page_prefixes.append(prefix)
        return super().list_page(prefix, start_after, limit)


class _StubStorage:
    """Storage stub whose list_page raises a configured exception."""

    def __init__(self, list_page_raises: BaseException) -> None:
        self._list_page_raises = list_page_raises

    def get(self, key: str) -> StoredObject | None:
        raise AssertionError("must not call storage.get")

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
        raise self._list_page_raises

    def delete_if_version(self, key: str, expected: VersionToken) -> None:
        raise NotImplementedError("not exercised by these tests")


class _EmptyListingStore(MemoryStore):
    """A MemoryStore subclass whose list_prefix override returns nothing."""

    def list_prefix(self, prefix: str, cursor: ListCursor | None = None) -> ListPage:
        return ListPage(entries=(), next_cursor=None)


class _DuplicateKeyMapping(Mapping[str, str]):
    """A Mapping whose iteration, and so items(), yields the same key twice."""

    def __init__(self) -> None:
        self.items_calls = 0

    def __getitem__(self, key: str) -> str:
        if key == "user":
            return "u-1"
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        yield "user"
        yield "user"

    def __len__(self) -> int:
        return 2

    def items(self) -> Any:
        self.items_calls += 1
        return super().items()


class _CountingMapping(Mapping[str, str]):
    """A well-behaved Mapping that counts items() calls."""

    def __init__(self, data: dict[str, str]) -> None:
        self._data = data
        self.items_calls = 0

    def __getitem__(self, key: str) -> str:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def items(self) -> Any:
        self.items_calls += 1
        return super().items()


class _SpoofedMapping:
    """Not a Mapping, but claims to be a dict via __class__."""

    @property
    def __class__(self) -> type:  # pyright: ignore[reportIncompatibleMethodOverride]
        return dict

    def items(self) -> list[tuple[str, str]]:
        return [("user", "u-1")]


class _SpoofedSequence:
    """Not a Sequence, but claims to be a tuple via __class__."""

    @property
    def __class__(self) -> type:  # pyright: ignore[reportIncompatibleMethodOverride]
        return tuple

    def __iter__(self) -> Iterator[str]:
        return iter(("user",))

    def __len__(self) -> int:
        return 1

    def __getitem__(self, i: int) -> str:
        return ("user",)[i]


class _Str(str):
    """A str subclass, normalized to plain str by validation."""


class _DistinctStr(str):
    """A str subclass whose instances are equal only to themselves, so equal
    values are distinct dict keys until normalized.
    """

    def __eq__(self, other: object) -> bool:
        return self is other

    def __ne__(self, other: object) -> bool:
        return self is not other

    def __hash__(self) -> int:
        return id(self)


class _LyingStr(str):
    """A str subclass whose conversion and concatenation hooks lie."""

    def __str__(self) -> str:
        return "evil"

    def __format__(self, format_spec: str) -> str:
        return "evil"

    def __add__(self, other: object) -> str:  # pyright: ignore[reportIncompatibleMethodOverride]
        return "evil"

    def __radd__(self, other: object) -> str:
        return "evil"


class _BadItemsMapping(Mapping[str, str]):
    """A Mapping whose items() yields a configured, malformed item."""

    def __init__(self, item: object) -> None:
        self._item = item

    def __getitem__(self, key: str) -> str:
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return iter(())

    def __len__(self) -> int:
        return 1

    def items(self) -> Any:
        return [self._item]


# --- US1: fan-out and merge ---------------------------------------------------


def test_index_merges_files_across_scopes_equal_to_list_prefix_entries() -> None:
    """Files under each scope appear as the FileEntry values list_prefix
    returns, and capped is empty (AIE-1046, US1.1).
    """
    storage = InMemoryStorage()
    _seed(storage, "user/u-1/notes/a.md", T1)
    _seed(storage, "org/o-9/glossary/b.md", T2)
    store = _new_store(storage)

    index = store.get_memory_index(SCOPE_MAP)

    assert isinstance(index, MemoryIndex)
    assert index.entries == (
        _entry(store, "org/o-9/glossary/b.md"),
        _entry(store, "user/u-1/notes/a.md"),
    )
    assert index.capped == ()


def test_index_excludes_other_entities_and_scopes() -> None:
    """A file under an entity not in the map and one under a scope not in
    the map do not appear (AIE-1046, US1.2).
    """
    storage = InMemoryStorage()
    _seed(storage, "user/u-1/notes/a.md", T1)
    _seed(storage, "user/u-2/notes/c.md", T2)
    _seed(storage, "team/t-1/notes/d.md", T3)
    store = _new_store(storage)

    index = store.get_memory_index(SCOPE_MAP)

    assert _paths(index) == ["user/u-1/notes/a.md"]
    assert index.capped == ()


def test_index_drains_every_page() -> None:
    """With list_page_size=2 and five files under user/u-1/, all five
    appear (AIE-1046, US1.3).
    """
    storage = InMemoryStorage()
    paths = [f"user/u-1/notes/{i}.md" for i in range(5)]
    for path in paths:
        _seed(storage, path, T1)
    store = _new_store(storage, list_page_size=2)

    index = store.get_memory_index({"user": "u-1"})

    assert sorted(_paths(index)) == sorted(paths)
    assert len(index.entries) == 5
    assert index.capped == ()


def test_index_with_empty_scope_map_never_consults_storage() -> None:
    """An empty scope_map returns MemoryIndex() without any storage call
    (AIE-1046, US1.4).
    """
    store = _new_store(_NeverCalledStorage())

    assert store.get_memory_index({}) == MemoryIndex()


def test_index_scope_with_no_files_contributes_nothing() -> None:
    """A scope with no files contributes nothing and raises nothing
    (AIE-1046, US1.5).
    """
    storage = InMemoryStorage()
    _seed(storage, "user/u-1/notes/a.md", T1)
    store = _new_store(storage)

    index = store.get_memory_index(SCOPE_MAP)

    assert _paths(index) == ["user/u-1/notes/a.md"]
    assert index.capped == ()


def test_index_skips_malformed_keys() -> None:
    """A malformed key under a scanned prefix is skipped, as list_prefix
    skips it (AIE-1046, US1.6).
    """
    storage = InMemoryStorage()
    _seed(storage, "user/u-1/notes/a.md", T1)
    storage.put("user/u-1/notes/x.txt", b"body", metadata_to_map(_metadata(T2)))
    store = _new_store(storage)

    index = store.get_memory_index({"user": "u-1"})

    assert _paths(index) == ["user/u-1/notes/a.md"]


def test_index_drain_does_not_stop_on_an_empty_page() -> None:
    """With list_page_size=1 and a malformed key sorting before a valid
    one, the valid key still appears: draining stops only on
    next_cursor None (AIE-1046, US1.6).
    """
    storage = InMemoryStorage()
    storage.put("user/u-1/notes/0.txt", b"body", metadata_to_map(_metadata(T2)))
    _seed(storage, "user/u-1/notes/a.md", T1)
    store = _new_store(storage, list_page_size=1)

    first = store.list_prefix("user/u-1/")
    assert first.entries == ()
    assert first.next_cursor is not None

    index = store.get_memory_index({"user": "u-1"})

    assert _paths(index) == ["user/u-1/notes/a.md"]


def test_index_propagates_metadata_format_error() -> None:
    """Corrupt metadata on a well-formed key raises MetadataFormatError,
    unwrapped (AIE-1046, US1.7).
    """
    storage = InMemoryStorage()
    bad_map = dict(metadata_to_map(_metadata(T1)))
    del bad_map["description"]
    storage.put("user/u-1/notes/a.md", b"body", bad_map)
    store = _new_store(storage)

    with pytest.raises(MetadataFormatError) as excinfo:
        store.get_memory_index({"user": "u-1"})

    assert type(excinfo.value) is MetadataFormatError
    assert excinfo.value.key == "description"


def test_index_unrenderable_entry_raises_regardless_of_cap() -> None:
    """An entry whose last-updated parses but cannot be rendered raises
    MetadataFormatError even when a tiny cap would omit it: every entry's
    size is computed before capping (AIE-1046, US1.10, US1.7).
    """
    storage = InMemoryStorage()
    _seed(storage, "user/u-1/notes/a.md", T1)
    bad_map = dict(metadata_to_map(_metadata(T1)))
    bad_map["last-updated"] = "0001-01-01T00:00:00+05:00"
    storage.put("user/u-1/notes/b.md", b"body", bad_map)
    store = MemoryStore(storage, index_max_bytes=10)

    with pytest.raises(MetadataFormatError) as excinfo:
        store.get_memory_index({"user": "u-1"})

    assert excinfo.value.key == "last-updated"


def test_index_propagates_backend_unavailable_error_unwrapped() -> None:
    """A BackendUnavailableError from list_page propagates as the same
    object (AIE-1046, US1.7).
    """
    error = BackendUnavailableError(TransientReason.UNAVAILABLE)
    store = _new_store(_StubStorage(error))

    with pytest.raises(BackendUnavailableError) as excinfo:
        store.get_memory_index({"user": "u-1"})

    assert excinfo.value is error


def test_index_never_reads_bodies() -> None:
    """A storage whose get raises still yields the index: bodies are
    never read (AIE-1046, US1.8).
    """
    storage = _NoGetStorage()
    _seed(storage, "user/u-1/notes/a.md", T1)
    _seed(storage, "org/o-9/notes/b.md", T2)
    store = _new_store(storage)

    index = store.get_memory_index(SCOPE_MAP)

    assert _paths(index) == ["org/o-9/notes/b.md", "user/u-1/notes/a.md"]


def test_index_prefix_is_segment_aligned() -> None:
    """For {"user": "u-1"}, a file under user/u-10/ is excluded
    (AIE-1046, US1.9).
    """
    storage = InMemoryStorage()
    _seed(storage, "user/u-1/notes/a.md", T1)
    _seed(storage, "user/u-10/notes/x.md", T2)
    store = _new_store(storage)

    index = store.get_memory_index({"user": "u-1"})

    assert _paths(index) == ["user/u-1/notes/a.md"]


def test_index_drains_through_base_list_prefix_not_subclass_override() -> None:
    """A subclass overriding list_prefix to return nothing does not change
    the index (AIE-1046, US1.12).
    """
    storage = InMemoryStorage()
    _seed(storage, "user/u-1/notes/a.md", T1)
    store = _EmptyListingStore(storage, clock=lambda: T1)

    assert store.list_prefix("user/u-1/").entries == ()

    index = store.get_memory_index({"user": "u-1"})

    assert _paths(index) == ["user/u-1/notes/a.md"]


# --- US2: ordering ------------------------------------------------------------


def _seed_us2_1(storage: InMemoryStorage) -> None:
    _seed(storage, "user/u-1/system/s.md", T1)
    _seed(storage, "org/o-9/system/t.md", T3)
    _seed(storage, "user/u-1/notes/n.md", T3)
    _seed(storage, "org/o-9/notes/m.md", T2)


def test_index_orders_system_first_then_flat_recency() -> None:
    """With no scope_priority, system/ areas come first by recency, then
    everything else as one tier by recency (AIE-1046, US2.1).
    """
    storage = InMemoryStorage()
    _seed_us2_1(storage)
    store = _new_store(storage)

    index = store.get_memory_index(SCOPE_MAP)

    assert _paths(index) == [
        "org/o-9/system/t.md",
        "user/u-1/system/s.md",
        "user/u-1/notes/n.md",
        "org/o-9/notes/m.md",
    ]


def test_index_scope_priority_applies_only_to_non_system_entries() -> None:
    """With scope_priority=("org", "user"), the older org note precedes
    the newer user note; system/ entries keep recency order (AIE-1046,
    US2.2).
    """
    storage = InMemoryStorage()
    _seed_us2_1(storage)
    store = _new_store(storage, scope_priority=("org", "user"))

    index = store.get_memory_index(SCOPE_MAP)

    assert _paths(index) == [
        "org/o-9/system/t.md",
        "user/u-1/system/s.md",
        "org/o-9/notes/m.md",
        "user/u-1/notes/n.md",
    ]


def test_index_unlisted_scopes_form_one_trailing_recency_tier() -> None:
    """With scope_priority=("org",), org comes first despite being oldest,
    and the unlisted team and user scopes form one tier by recency
    (AIE-1046, US2.3).
    """
    storage = InMemoryStorage()
    _seed(storage, "org/o-9/notes/m.md", T1)
    _seed(storage, "user/u-1/notes/n.md", T2)
    _seed(storage, "team/t-1/notes/p.md", T3)
    store = _new_store(storage, scope_priority=("org",))

    index = store.get_memory_index({"user": "u-1", "org": "o-9", "team": "t-1"})

    assert _paths(index) == [
        "org/o-9/notes/m.md",
        "team/t-1/notes/p.md",
        "user/u-1/notes/n.md",
    ]


def test_index_breaks_timestamp_ties_by_path_ascending() -> None:
    """Equal last-updated in the same tier orders by path ascending
    (AIE-1046, US2.4).
    """
    storage = InMemoryStorage()
    _seed(storage, "user/u-1/notes/b.md", T1)
    _seed(storage, "user/u-1/notes/a.md", T1)
    _seed(storage, "org/o-9/notes/c.md", T1)
    store = _new_store(storage)

    index = store.get_memory_index(SCOPE_MAP)

    assert _paths(index) == [
        "org/o-9/notes/c.md",
        "user/u-1/notes/a.md",
        "user/u-1/notes/b.md",
    ]


def test_index_tiebreak_uses_full_path_not_fan_out_order() -> None:
    """Equal timestamps under scopes "a" and "a-b" order by path, where "-"
    sorts before "/", though fan-out visits "a" first (AIE-1046, US2.4).
    """
    storage = InMemoryStorage()
    _seed(storage, "a/x/notes/f.md", T1)
    _seed(storage, "a-b/y/notes/f.md", T1)
    store = _new_store(storage)

    index = store.get_memory_index({"a": "x", "a-b": "y"})

    assert _paths(index) == ["a-b/y/notes/f.md", "a/x/notes/f.md"]


def test_index_orders_one_microsecond_difference_newest_first() -> None:
    """Timestamps one microsecond apart order newest first, even far in
    the future where a float timestamp loses microsecond resolution
    (AIE-1046, US2.4).
    """
    older = datetime(9000, 1, 1, 0, 0, 0, 1, tzinfo=UTC)
    newer = older + timedelta(microseconds=1)
    storage = InMemoryStorage()
    _seed(storage, "user/u-1/notes/a.md", older)
    _seed(storage, "user/u-1/notes/b.md", newer)
    store = _new_store(storage)

    index = store.get_memory_index({"user": "u-1"})

    assert _paths(index) == ["user/u-1/notes/b.md", "user/u-1/notes/a.md"]


def test_index_ignores_priority_scopes_absent_from_scope_map() -> None:
    """A scope in scope_priority absent from scope_map is ignored
    (AIE-1046, US2.5).
    """
    storage = InMemoryStorage()
    _seed_us2_1(storage)
    flat = _new_store(storage).get_memory_index(SCOPE_MAP)
    store = _new_store(storage, scope_priority=("team",))

    index = store.get_memory_index(SCOPE_MAP)

    assert index == flat
    assert _paths(index) == [
        "org/o-9/system/t.md",
        "user/u-1/system/s.md",
        "user/u-1/notes/n.md",
        "org/o-9/notes/m.md",
    ]


def test_index_system_tier_is_decided_by_area_segment_only() -> None:
    """Only the area segment decides the system/ tier, not a scope,
    entity, or file named system (AIE-1046, US2.6).
    """
    storage = InMemoryStorage()
    _seed(storage, "system/e/notes/a.md", T1)
    _seed(storage, "user/system/notes/b.md", T2)
    _seed(storage, "user/system/notes/system.md", T3)
    _seed(storage, "user/system/system/c.md", T1)
    store = _new_store(storage)

    index = store.get_memory_index({"system": "e", "user": "system"})

    assert _paths(index) == [
        "user/system/system/c.md",
        "user/system/notes/system.md",
        "user/system/notes/b.md",
        "system/e/notes/a.md",
    ]


# --- US3: byte cap ------------------------------------------------------------

# Index order for _seed_cap_files: newest first, all in one flat tier.
_CAP_ORDER = [
    "user/u-1/notes/c.md",
    "org/o-9/notes/b.md",
    "user/u-1/people/a.md",
]


def _seed_cap_files(storage: InMemoryStorage) -> None:
    _seed(storage, "user/u-1/people/a.md", T1)
    _seed(storage, "org/o-9/notes/b.md", T2)
    _seed(storage, "user/u-1/notes/c.md", T3)


def test_index_cap_is_inclusive() -> None:
    """A cap exactly equal to the sum of entry sizes includes everything
    (AIE-1046, US3.2).
    """
    storage = InMemoryStorage()
    _seed_cap_files(storage)
    total = sum(_sizes(_new_store(storage), _CAP_ORDER))
    store = _new_store(storage, index_max_bytes=total)

    index = store.get_memory_index(SCOPE_MAP)

    assert _paths(index) == _CAP_ORDER
    assert index.capped == ()


def test_index_cap_one_byte_short_omits_last_entry() -> None:
    """A cap one byte less than the total omits the last entry and
    reports its area prefix with count 1 (AIE-1046, US3.3).
    """
    storage = InMemoryStorage()
    _seed_cap_files(storage)
    total = sum(_sizes(_new_store(storage), _CAP_ORDER))
    store = _new_store(storage, index_max_bytes=total - 1)

    index = store.get_memory_index(SCOPE_MAP)

    assert _paths(index) == _CAP_ORDER[:2]
    assert index.capped == (CappedPrefix("user/u-1/people/", 1),)


def test_index_inclusion_stops_at_first_miss() -> None:
    """When e3 does not fit, e3, e4, and e5 are all omitted even though
    e4 alone would fit (AIE-1046, US3.4).
    """
    storage = InMemoryStorage()
    order = [f"user/u-1/notes/e{i}.md" for i in range(1, 6)]
    for path, ts in zip(order, [T5, T4, T3, T2, T1], strict=True):
        description = "x" * 200 if path.endswith("e3.md") else "d"
        _seed(storage, path, ts, description)
    s1, s2, s3, s4, _ = _sizes(_new_store(storage), order)
    assert s3 > s4
    cap = s1 + s2 + s4
    store = _new_store(storage, index_max_bytes=cap)

    index = store.get_memory_index({"user": "u-1"})

    assert _paths(index) == order[:2]
    assert index.capped == (CappedPrefix("user/u-1/notes/", 3),)


def test_index_capped_is_sorted_by_prefix_with_counts() -> None:
    """Omitted entries are grouped by area prefix, sorted by prefix
    string, with counts (AIE-1046, US3.5).
    """
    storage = InMemoryStorage()
    _seed(storage, "user/u-1/system/top.md", datetime(2025, 1, 1, tzinfo=UTC))
    # Omitted entries, interleaved in recency so groups are not contiguous.
    _seed(storage, "user/u-1/notes/n1.md", T5)
    _seed(storage, "org/o-9/notes/o1.md", T4)
    _seed(storage, "user/u-1/people/p1.md", T3)
    _seed(storage, "user/u-1/notes/n2.md", T2)
    _seed(storage, "org/o-9/notes/o2.md", T1)
    _seed(storage, "user/u-1/notes/n3.md", datetime(2023, 1, 1, tzinfo=UTC))
    (top,) = _sizes(_new_store(storage), ["user/u-1/system/top.md"])
    store = _new_store(storage, index_max_bytes=top)

    index = store.get_memory_index(SCOPE_MAP)

    assert _paths(index) == ["user/u-1/system/top.md"]
    assert index.capped == (
        CappedPrefix("org/o-9/notes/", 2),
        CappedPrefix("user/u-1/notes/", 3),
        CappedPrefix("user/u-1/people/", 1),
    )


def test_index_cap_smaller_than_first_entry_omits_everything() -> None:
    """A cap smaller than the first entry yields no entries and counts
    every entry in capped (AIE-1046, US3.6).
    """
    storage = InMemoryStorage()
    _seed_cap_files(storage)
    first = _sizes(_new_store(storage), _CAP_ORDER)[0]
    store = _new_store(storage, index_max_bytes=first - 1)

    index = store.get_memory_index(SCOPE_MAP)

    assert index.entries == ()
    assert index.capped == (
        CappedPrefix("org/o-9/notes/", 1),
        CappedPrefix("user/u-1/notes/", 1),
        CappedPrefix("user/u-1/people/", 1),
    )


@pytest.mark.parametrize("cap", [0, -1])
def test_memory_store_rejects_non_positive_index_max_bytes(cap: int) -> None:
    """index_max_bytes <= 0 raises ValueError at construction (AIE-1046,
    US3.7).
    """
    with pytest.raises(ValueError, match=r"^index_max_bytes must be positive$"):
        MemoryStore(InMemoryStorage(), index_max_bytes=cap)


def test_default_index_max_bytes_is_64_kib() -> None:
    """DEFAULT_INDEX_MAX_BYTES == 65536 and is the store's default
    (AIE-1046, US3.7).
    """
    assert DEFAULT_INDEX_MAX_BYTES == 65536
    assert MemoryStore(InMemoryStorage()).index_max_bytes == 65536


def test_index_capped_section_size_is_not_counted() -> None:
    """With the cap exactly equal to the included entries' size and many
    entries omitted, the included entries are all returned: capped's own
    bytes are not charged against the budget (AIE-1046, US3.8).
    """
    storage = InMemoryStorage()
    included = ["user/u-1/notes/a.md", "user/u-1/notes/b.md"]
    _seed(storage, included[0], datetime(2025, 2, 1, tzinfo=UTC))
    _seed(storage, included[1], datetime(2025, 1, 1, tzinfo=UTC))
    for i in range(20):
        _seed(storage, f"org/o-9/area{i:02d}/x.md", T1)
    cap = sum(_sizes(_new_store(storage), included))
    store = _new_store(storage, index_max_bytes=cap)

    index = store.get_memory_index(SCOPE_MAP)

    assert _paths(index) == included
    assert len(index.capped) == 20
    assert all(c.omitted == 1 for c in index.capped)


# --- US4: constructor settings and input validation ---------------------------


def test_scope_priority_and_index_max_bytes_are_read_only_properties() -> None:
    """scope_priority is stored as a tuple and both settings are
    read-only properties (AIE-1046, US4.1).
    """
    store = MemoryStore(InMemoryStorage(), scope_priority=("user", "org"), index_max_bytes=123)

    assert store.scope_priority == ("user", "org")
    assert type(store.scope_priority) is tuple
    assert store.index_max_bytes == 123
    assert MemoryStore(InMemoryStorage()).scope_priority == ()

    with pytest.raises(AttributeError):
        store.scope_priority = ("org",)  # pyright: ignore[reportAttributeAccessIssue]
    with pytest.raises(AttributeError):
        store.index_max_bytes = 1  # pyright: ignore[reportAttributeAccessIssue]


@pytest.mark.parametrize(
    "bad",
    [
        "user",
        b"user",
        bytearray(b"user"),
        "",
        b"",
        bytearray(),
        {"user"},
        3,
        _SpoofedSequence(),
    ],
    ids=[
        "str",
        "bytes",
        "bytearray",
        "empty-str",
        "empty-bytes",
        "empty-bytearray",
        "set",
        "int",
        "spoofed-class",
    ],
)
def test_scope_priority_rejects_non_sequence_or_bare_string(bad: object) -> None:
    """A bare str/bytes/bytearray, a non-Sequence, or a spoofed __class__
    raises TypeError (AIE-1046, US4.2, US4.4).
    """
    _require_scope_priority_kwarg()
    with pytest.raises(TypeError):
        MemoryStore(InMemoryStorage(), scope_priority=bad)  # pyright: ignore[reportArgumentType]


def test_scope_priority_rejects_non_str_member() -> None:
    """A non-str member raises TypeError (AIE-1046, US4.2)."""
    _require_scope_priority_kwarg()
    with pytest.raises(TypeError):
        MemoryStore(InMemoryStorage(), scope_priority=("user", 3))  # pyright: ignore[reportArgumentType]


def test_scope_priority_type_errors_precede_value_errors() -> None:
    """("user", "user", 3) raises TypeError, not the duplicate ValueError
    (AIE-1046, US4.2).
    """
    _require_scope_priority_kwarg()
    with pytest.raises(TypeError):
        MemoryStore(
            InMemoryStorage(),
            scope_priority=("user", "user", 3),  # pyright: ignore[reportArgumentType]
        )


def test_scope_priority_invalid_entry_checked_before_duplicate() -> None:
    """("a/", "a/") raises the invalid-entry ValueError (AIE-1046, US4.2)."""
    with pytest.raises(ValueError, match=r"^invalid scope_priority entry: 'a/'$"):
        MemoryStore(InMemoryStorage(), scope_priority=("a/", "a/"))


def test_scope_priority_rejects_duplicate() -> None:
    """A repeated entry raises the duplicate ValueError (AIE-1046, US4.2)."""
    with pytest.raises(ValueError, match=r"^duplicate scope_priority entry: 'user'$"):
        MemoryStore(InMemoryStorage(), scope_priority=("user", "org", "user"))


def test_scope_priority_normalizes_str_subclass_members() -> None:
    """str-subclass members are normalized to plain str (AIE-1046, US4.2)."""
    store = MemoryStore(InMemoryStorage(), scope_priority=(_Str("user"),))

    assert store.scope_priority == ("user",)
    assert type(store.scope_priority[0]) is str


def test_scope_priority_list_is_copied_to_tuple() -> None:
    """A list is accepted, stored as a tuple, and later mutation has no
    effect (AIE-1046, US4.3).
    """
    priority = ["org", "user"]
    store = MemoryStore(InMemoryStorage(), scope_priority=priority)
    priority.append("team")
    priority[0] = "zzz"

    assert store.scope_priority == ("org", "user")
    assert type(store.scope_priority) is tuple


@pytest.mark.parametrize(
    "bad",
    [[("user", "u-1")], "user", None, _SpoofedMapping()],
    ids=["list-of-pairs", "str", "none", "spoofed-class"],
)
def test_scope_map_must_be_a_real_mapping(bad: object) -> None:
    """A scope_map whose real type is not a Mapping raises TypeError
    without consulting storage (AIE-1046, US4.4).
    """
    store = _new_store(_NeverCalledStorage())

    with pytest.raises(TypeError):
        store.get_memory_index(bad)  # pyright: ignore[reportArgumentType]


def test_scope_map_non_str_value_raises_type_error_before_value_errors() -> None:
    """{"a/": "x", "b": 1} raises TypeError though "a/" is an invalid
    scope (AIE-1046, US4.5).
    """
    store = _new_store(_NeverCalledStorage())

    with pytest.raises(TypeError, match=r"^scope_map value must be str, got "):
        store.get_memory_index({"a/": "x", "b": 1})  # pyright: ignore[reportArgumentType]


def test_scope_map_non_str_key_raises_type_error() -> None:
    """A non-str key raises TypeError (AIE-1046, US4.5)."""
    store = _new_store(_NeverCalledStorage())

    with pytest.raises(TypeError, match=r"^scope_map key must be str, got "):
        store.get_memory_index({1: "x"})  # pyright: ignore[reportArgumentType]


def test_scope_map_key_type_checked_before_value_type() -> None:
    """{1: 2} reports the key, not the value (AIE-1046, US4.5)."""
    store = _new_store(_NeverCalledStorage())

    with pytest.raises(TypeError, match=r"^scope_map key must be str, got "):
        store.get_memory_index({1: 2})  # pyright: ignore[reportArgumentType]


@pytest.mark.parametrize(
    "scope_map",
    [{"a/": "x", "b": "y/"}, {"b": "y/", "a/": "x"}],
    ids=["sorted-insertion", "reverse-insertion"],
)
def test_scope_map_value_errors_follow_sorted_scope_order(scope_map: dict[str, str]) -> None:
    """Value checks run over pairs sorted by scope, so "a/" is reported
    before "b"'s bad entity regardless of insertion order (AIE-1046,
    US4.5).
    """
    store = _new_store(_NeverCalledStorage())

    with pytest.raises(ValueError, match=r"^invalid scope: 'a/'$"):
        store.get_memory_index(scope_map)


def test_scope_map_values_validated_before_any_storage_call() -> None:
    """A valid first pair does not trigger a scan before a later bad
    entity_id is reported (AIE-1046, US4.5).
    """
    store = _new_store(_NeverCalledStorage())

    with pytest.raises(ValueError, match=r"^invalid entity_id: 'x/'$"):
        store.get_memory_index({"a": "ok", "b": "x/"})


def test_scope_map_duplicate_detected_after_normalization() -> None:
    """Two str-subclass keys that are distinct dict keys but both "user"
    raise the duplicate ValueError once normalized (AIE-1046, US4.5).
    """
    store = _new_store(_NeverCalledStorage())
    scope_map: dict[str, str] = {_DistinctStr("user"): "u-1", _DistinctStr("user"): "u-2"}
    assert len(scope_map) == 2

    with pytest.raises(ValueError, match=r"^duplicate scope: 'user'$"):
        store.get_memory_index(scope_map)


def test_scope_map_prefix_built_from_normalized_values() -> None:
    """A str-subclass value whose __str__, __format__, and __add__ lie
    still yields the prefix user/u-1/ (AIE-1046, US4.5).
    """
    storage = _RecordingStorage()
    store = _new_store(storage)

    store.get_memory_index({"user": _LyingStr("u-1")})

    assert storage.list_page_prefixes == ["user/u-1/"]


def test_scope_map_invalid_entity_id_raises_value_error() -> None:
    """An invalid entity_id raises ValueError naming it (AIE-1046, US4.5)."""
    store = _new_store(_NeverCalledStorage())

    with pytest.raises(ValueError, match=r"^invalid entity_id: 'x/'$"):
        store.get_memory_index({"user": "x/"})


def test_scope_map_duplicate_scope_raises_value_error() -> None:
    """A Mapping whose items() yields the same key twice raises the
    duplicate ValueError, reading items() once, before storage
    (AIE-1046, US4.5).
    """
    store = _new_store(_NeverCalledStorage())
    scope_map = _DuplicateKeyMapping()

    with pytest.raises(ValueError, match=r"^duplicate scope: 'user'$"):
        store.get_memory_index(scope_map)

    assert scope_map.items_calls == 1


@pytest.mark.parametrize(
    "item",
    [("user", "u-1", "extra"), "ab"],
    ids=["three-tuple", "two-char-str"],
)
def test_scope_map_items_must_be_pairs(item: object) -> None:
    """A Mapping whose items() yields something other than a 2-tuple,
    including the 2-char string "ab", raises TypeError without consulting
    storage (AIE-1046, US4.5).
    """
    store = _new_store(_NeverCalledStorage())

    with pytest.raises(TypeError, match="scope_map items"):
        store.get_memory_index(_BadItemsMapping(item))


def test_scope_map_items_is_read_exactly_once() -> None:
    """items() is read exactly once for a valid Mapping (AIE-1046, US4.5)."""
    storage = InMemoryStorage()
    _seed(storage, "user/u-1/notes/a.md", T1)
    store = _new_store(storage)
    scope_map = _CountingMapping({"user": "u-1"})

    index = store.get_memory_index(scope_map)

    assert _paths(index) == ["user/u-1/notes/a.md"]
    assert scope_map.items_calls == 1


def test_scope_map_str_subclass_keys_and_values_are_normalized() -> None:
    """str-subclass keys and values are accepted and normalized
    (AIE-1046, US4.5).
    """
    storage = InMemoryStorage()
    _seed(storage, "user/u-1/notes/a.md", T1)
    store = _new_store(storage)

    index = store.get_memory_index({_Str("user"): _Str("u-1")})

    assert _paths(index) == ["user/u-1/notes/a.md"]


def test_index_is_independent_of_scope_map_iteration_order() -> None:
    """Both iteration orders yield identical results, and fan-out runs in
    sorted scope order (AIE-1046, US4.6).
    """
    storage = _RecordingStorage()
    _seed_us2_1(storage)
    _seed(storage, "user/u-1/notes/z.md", T2)
    _seed(storage, "org/o-9/people/q.md", T1)
    store = _new_store(storage)

    forward = store.get_memory_index({"org": "o-9", "user": "u-1"})
    forward_calls = list(storage.list_page_prefixes)
    storage.list_page_prefixes.clear()
    backward = store.get_memory_index({"user": "u-1", "org": "o-9"})
    backward_calls = list(storage.list_page_prefixes)

    assert forward == backward
    assert forward_calls == backward_calls
    assert forward_calls[0] == "org/o-9/"
    assert forward_calls[-1] == "user/u-1/"


@pytest.mark.parametrize("cap", [True, 1.5], ids=["bool", "float"])
def test_index_max_bytes_accepts_non_int_positive_values(cap: object) -> None:
    """index_max_bytes=True or 1.5 is accepted; only <= 0 is rejected
    (AIE-1046, US4.7).
    """
    store = MemoryStore(InMemoryStorage(), index_max_bytes=cap)  # pyright: ignore[reportArgumentType]

    assert store.index_max_bytes == cap
