"""Tests for the CappedPrefix and MemoryIndex value types in wenchang.core.

Covers AIE-1048, US3.1 through US3.6.
"""

import dataclasses
from datetime import UTC, datetime

import pytest

from wenchang.core import CappedPrefix, FileEntry, MemoryIndex
from wenchang.file_format import FileMetadata
from wenchang.version_token import VersionToken

pytestmark = pytest.mark.unit

PREFIX = "user/u-1/notes/"
OTHER_PREFIX = "user/u-1/projects/"


def _metadata(description: str = "desc") -> FileMetadata:
    return FileMetadata(
        description=description,
        aliases=("a",),
        sources=frozenset({"s1"}),
        last_updated=datetime(2024, 1, 1, tzinfo=UTC),
    )


def _entry(path: str = "user/u-1/notes/a.md", version: str = "1") -> FileEntry:
    return FileEntry(path=path, metadata=_metadata(), version=VersionToken(version))


class _StrSub(str):
    pass


class _LyingInt(int):
    """int subclass whose comparisons claim it is always positive."""

    def __le__(self, other: int, /) -> bool:
        return False

    def __lt__(self, other: int, /) -> bool:
        return False

    def __gt__(self, other: int, /) -> bool:
        return True

    def __ge__(self, other: int, /) -> bool:
        return True

    def __index__(self) -> int:
        return int.__int__(self)


class _EntryTuple(tuple[FileEntry, ...]):
    pass


class _CappedTuple(tuple[CappedPrefix, ...]):
    pass


# US3.1


def test_capped_prefix_fields_readable() -> None:
    """AIE-1048, US3.1: CappedPrefix exposes prefix and omitted."""
    cap = CappedPrefix(PREFIX, 12)
    assert cap.prefix == PREFIX
    assert cap.omitted == 12
    assert dataclasses.is_dataclass(cap)


@pytest.mark.parametrize("field", ["prefix", "omitted"])
def test_capped_prefix_is_frozen(field: str) -> None:
    """AIE-1048, US3.1: assigning a CappedPrefix field raises FrozenInstanceError."""
    cap = CappedPrefix(PREFIX, 12)
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(cap, field, "x")


# US3.2


@pytest.mark.parametrize("omitted", [0, -1])
def test_capped_prefix_rejects_non_positive_omitted(omitted: int) -> None:
    """AIE-1048, US3.2: omitted <= 0 raises ValueError."""
    with pytest.raises(ValueError):
        CappedPrefix(PREFIX, omitted)


@pytest.mark.parametrize("prefix", ["", "user", "user/u-1/notes/x.md"])
def test_capped_prefix_rejects_invalid_prefix(prefix: str) -> None:
    """AIE-1048, US3.2: a prefix failing is_valid_prefix raises ValueError."""
    with pytest.raises(ValueError):
        CappedPrefix(prefix, 1)


# US3.3


def test_capped_prefix_rejects_none_prefix() -> None:
    """AIE-1048, US3.3: a non-str prefix raises TypeError."""
    with pytest.raises(TypeError):
        CappedPrefix(None, 1)  # pyright: ignore[reportArgumentType]


@pytest.mark.parametrize("omitted", [True, False])
def test_capped_prefix_rejects_bool_omitted(omitted: bool) -> None:
    """AIE-1048, US3.3: a bool omitted raises TypeError."""
    with pytest.raises(TypeError):
        CappedPrefix(PREFIX, omitted)


@pytest.mark.parametrize("omitted", ["3", 3.0])
def test_capped_prefix_rejects_non_int_omitted(omitted: object) -> None:
    """AIE-1048, US3.3: a non-int omitted raises TypeError."""
    with pytest.raises(TypeError):
        CappedPrefix(PREFIX, omitted)  # pyright: ignore[reportArgumentType]


def test_capped_prefix_type_check_precedes_value_check() -> None:
    """AIE-1048, US3.3: CappedPrefix("", True) raises TypeError, not ValueError."""
    with pytest.raises(TypeError):
        CappedPrefix("", True)


def test_capped_prefix_normalizes_str_subclass() -> None:
    """AIE-1048, US3.3: a str subclass prefix is stored as an exact str."""
    cap = CappedPrefix(_StrSub(PREFIX), 1)
    assert type(cap.prefix) is str
    assert cap.prefix == PREFIX


def test_capped_prefix_normalizes_int_subclass() -> None:
    """AIE-1048, US3.3: an int subclass omitted is stored as an exact int."""
    cap = CappedPrefix(PREFIX, _LyingInt(5))
    assert type(cap.omitted) is int
    assert cap.omitted == 5


def test_capped_prefix_rejects_lying_non_positive_int_subclass() -> None:
    """AIE-1048, US3.3: an int subclass with a lying __le__ and value -3 raises ValueError."""
    with pytest.raises(ValueError):
        CappedPrefix(PREFIX, _LyingInt(-3))


# US3.4


def test_memory_index_defaults_empty() -> None:
    """AIE-1048, US3.4: MemoryIndex() is the empty index."""
    index = MemoryIndex()
    assert index.entries == ()
    assert index.capped == ()
    assert type(index.entries) is tuple
    assert type(index.capped) is tuple


def test_memory_index_holds_entries_and_capped() -> None:
    """AIE-1048, US3.4: MemoryIndex holds the given entries and capped tuples."""
    entry = _entry()
    cap = CappedPrefix(OTHER_PREFIX, 4)
    index = MemoryIndex(entries=(entry,), capped=(cap,))
    assert index.entries == (entry,)
    assert index.capped == (cap,)

    entries_only = MemoryIndex(entries=(entry,), capped=())
    assert entries_only.entries == (entry,)
    assert entries_only.capped == ()


@pytest.mark.parametrize("field", ["entries", "capped"])
def test_memory_index_is_frozen(field: str) -> None:
    """AIE-1048, US3.4: assigning a MemoryIndex field raises FrozenInstanceError."""
    index = MemoryIndex()
    assert dataclasses.is_dataclass(index)
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(index, field, ())


# US3.5


def test_memory_index_rejects_list_entries() -> None:
    """AIE-1048, US3.5: entries as a list raises TypeError."""
    with pytest.raises(TypeError):
        MemoryIndex(entries=[_entry()])  # pyright: ignore[reportArgumentType]


def test_memory_index_rejects_list_capped() -> None:
    """AIE-1048, US3.5: capped as a list raises TypeError."""
    with pytest.raises(TypeError):
        MemoryIndex(capped=[CappedPrefix(PREFIX, 1)])  # pyright: ignore[reportArgumentType]


def test_memory_index_rejects_tuple_subclass_entries() -> None:
    """AIE-1048, US3.5: entries as a tuple subclass raises TypeError."""
    with pytest.raises(TypeError):
        MemoryIndex(entries=_EntryTuple((_entry(),)))


def test_memory_index_rejects_tuple_subclass_capped() -> None:
    """AIE-1048, US3.5: capped as a tuple subclass raises TypeError."""
    with pytest.raises(TypeError):
        MemoryIndex(capped=_CappedTuple((CappedPrefix(PREFIX, 1),)))


@pytest.mark.parametrize("member", [CappedPrefix(PREFIX, 1), object(), "user/u-1/notes/a.md"])
def test_memory_index_rejects_non_file_entry_member(member: object) -> None:
    """AIE-1048, US3.5: an entries member that is not a FileEntry raises TypeError."""
    with pytest.raises(TypeError):
        MemoryIndex(entries=(_entry(), member))  # pyright: ignore[reportArgumentType]


@pytest.mark.parametrize("member", [_entry(), object(), PREFIX])
def test_memory_index_rejects_non_capped_prefix_member(member: object) -> None:
    """AIE-1048, US3.5: a capped member that is not a CappedPrefix raises TypeError."""
    with pytest.raises(TypeError):
        MemoryIndex(capped=(CappedPrefix(OTHER_PREFIX, 1), member))  # pyright: ignore[reportArgumentType]


def test_memory_index_rejects_duplicate_entry_paths() -> None:
    """AIE-1048, US3.5: two entries sharing a path raise ValueError."""
    with pytest.raises(ValueError):
        MemoryIndex(entries=(_entry(version="1"), _entry(version="2")))


def test_memory_index_rejects_duplicate_capped_prefixes() -> None:
    """AIE-1048, US3.5: two capped members sharing a prefix raise ValueError."""
    with pytest.raises(ValueError):
        MemoryIndex(capped=(CappedPrefix(PREFIX, 1), CappedPrefix(PREFIX, 2)))


def test_memory_index_accepts_distinct_members() -> None:
    """AIE-1048, US3.5: distinct paths and prefixes are accepted."""
    index = MemoryIndex(
        entries=(_entry("user/u-1/notes/a.md"), _entry("user/u-1/notes/b.md")),
        capped=(CappedPrefix(PREFIX, 1), CappedPrefix(OTHER_PREFIX, 2)),
    )
    assert len(index.entries) == 2
    assert len(index.capped) == 2


# US3.6


def test_memory_index_equal_fields_equal_and_hash_equal() -> None:
    """AIE-1048, US3.6: MemoryIndex values with equal fields are equal and hash equal."""
    a = MemoryIndex(entries=(_entry(),), capped=(CappedPrefix(OTHER_PREFIX, 3),))
    b = MemoryIndex(entries=(_entry(),), capped=(CappedPrefix(OTHER_PREFIX, 3),))
    assert a == b
    assert hash(a) == hash(b)
    assert MemoryIndex() == MemoryIndex()
    assert hash(MemoryIndex()) == hash(MemoryIndex())


def test_memory_index_differing_entries_unequal() -> None:
    """AIE-1048, US3.6: MemoryIndex values differing in entries compare unequal."""
    cap = (CappedPrefix(OTHER_PREFIX, 3),)
    a = MemoryIndex(entries=(_entry(version="1"),), capped=cap)
    b = MemoryIndex(entries=(_entry(version="2"),), capped=cap)
    assert a != b
    assert MemoryIndex(entries=(_entry(),), capped=cap) != MemoryIndex(capped=cap)


def test_memory_index_differing_capped_unequal() -> None:
    """AIE-1048, US3.6: MemoryIndex values differing in capped compare unequal."""
    entries = (_entry(),)
    a = MemoryIndex(entries=entries, capped=(CappedPrefix(OTHER_PREFIX, 3),))
    b = MemoryIndex(entries=entries, capped=(CappedPrefix(OTHER_PREFIX, 4),))
    assert a != b
    assert MemoryIndex(entries=entries) != a


def test_capped_prefix_equality_and_hash() -> None:
    """AIE-1048, US3.6: CappedPrefix values with equal fields are equal and hash equal."""
    assert CappedPrefix(PREFIX, 2) == CappedPrefix(PREFIX, 2)
    assert hash(CappedPrefix(PREFIX, 2)) == hash(CappedPrefix(PREFIX, 2))
    assert CappedPrefix(PREFIX, 2) != CappedPrefix(PREFIX, 3)
    assert CappedPrefix(PREFIX, 2) != CappedPrefix(OTHER_PREFIX, 2)
