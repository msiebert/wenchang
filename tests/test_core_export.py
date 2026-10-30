"""Tests for MemoryStore.export and ExportedObject.

Covers AIE-1291, US4.
"""

import dataclasses
from collections.abc import Callable, Sequence
from typing import Any, cast

import pytest

from purge_export_support import (
    NEIGHBOURS,
    READABLE_SUFFIXES,
    SEED_SUFFIXES,
    RecordingStorage,
    seed_entity,
    seed_many,
    seed_neighbours,
    snapshot,
    valid_metadata,
)
from wenchang.core import ExportedObject, MemoryStore
from wenchang.errors import BackendUnavailableError, TransientReason
from wenchang.storage import ListedObject
from wenchang.version_token import VersionToken

pytestmark = pytest.mark.unit

PREFIX = "user/u1/"
SEED_KEYS = [PREFIX + s for s in SEED_SUFFIXES]


class _SpoofedStr:
    """Not a str, but claims to be one via __class__."""

    @property
    def __class__(self) -> type:  # pyright: ignore[reportIncompatibleMethodOverride]
        return str


def _m(h: RecordingStorage) -> MemoryStore:
    return MemoryStore(h, list_page_size=2)


def _seeded() -> RecordingStorage:
    h = RecordingStorage()
    seed_entity(h.inner)
    seed_neighbours(h.inner)
    return h


def _triples(objects: Sequence[ExportedObject]) -> list[tuple[str, bytes, dict[str, str]]]:
    return [(o.key, o.data, dict(o.metadata)) for o in objects]


def _on_first_list(h: RecordingStorage, action: Callable[[Sequence[ListedObject]], None]) -> None:
    def hook(
        prefix: str, start_after: str | None, limit: int, result: Sequence[ListedObject]
    ) -> None:
        if h.count("list_page") == 1:
            action(result)

    h.after_list = hook


def test_export_returns_every_object_in_key_order() -> None:
    """Export returns a tuple of 6 ExportedObjects in ascending key order,
    including system/, corrupt-metadata, non-UTF-8, and non-path keys
    (AIE-1291, US4.1).
    """
    h = _seeded()

    exported = _m(h).export("user", "u1")

    assert type(exported) is tuple
    assert all(type(o) is ExportedObject for o in exported)
    assert [o.key for o in exported] == SEED_KEYS


def test_export_matches_stored_objects() -> None:
    """Each object's data, metadata, and version equal storage's
    (AIE-1291, US4.2).
    """
    h = _seeded()

    exported = _m(h).export("user", "u1")

    assert len(exported) == 6
    for o in exported:
        stored = h.inner.get(o.key)
        assert stored is not None
        assert o.data == stored.data
        assert dict(o.metadata) == dict(stored.metadata)
        assert o.version == stored.version


def test_export_excludes_neighbours() -> None:
    """No neighbour key appears in the export (AIE-1291, US4.3)."""
    h = _seeded()

    keys = {o.key for o in _m(h).export("user", "u1")}

    assert keys.isdisjoint(NEIGHBOURS)


def test_export_writes_nothing() -> None:
    """Export makes no write or delete call and every object keeps its
    version (AIE-1291, US4.4).
    """
    h = _seeded()
    all_keys = [*SEED_KEYS, *NEIGHBOURS]
    before = snapshot(h.inner, all_keys)

    _m(h).export("user", "u1")

    for method in ("put", "put_if_version", "delete_if_version"):
        assert h.count(method) == 0
    assert snapshot(h.inner, all_keys) == before


def test_export_purge_restore_round_trip() -> None:
    """Export, purge, restore with put, and export again yields the same
    keys, data, and metadata; restored files read back unchanged
    (AIE-1291, US4.5).
    """
    h = _seeded()
    store = _m(h)
    originals = {s: store.read_file(PREFIX + s) for s in READABLE_SUFFIXES}

    first = store.export("user", "u1")
    store.purge("user", "u1")
    for o in first:
        h.inner.put(o.key, o.data, o.metadata)
    second = store.export("user", "u1")

    assert _triples(first) == _triples(second)
    for suffix, original in originals.items():
        restored = store.read_file(PREFIX + suffix)
        assert restored.content == original.content
        assert restored.metadata == original.metadata


def test_export_of_empty_entity() -> None:
    """An entity with no objects exports as () (AIE-1291, US4.6)."""
    h = RecordingStorage()
    seed_neighbours(h.inner)

    assert _m(h).export("user", "u1") == ()


def test_export_paginates_seven_objects() -> None:
    """Seven objects with page size 2 are all exported in ascending order
    (AIE-1291, US4.7).
    """
    h = RecordingStorage()
    keys = seed_many(h.inner, 7)

    assert [o.key for o in _m(h).export("user", "u1")] == keys


def test_export_omits_object_deleted_after_listing() -> None:
    """An object deleted between listing and get is omitted without error
    (AIE-1291, US4.8).
    """
    h = _seeded()
    gone: list[str] = []

    def delete_first(result: Sequence[ListedObject]) -> None:
        first = result[0]
        h.inner.delete_if_version(first.key, first.version)
        gone.append(first.key)

    _on_first_list(h, delete_first)

    exported = _m(h).export("user", "u1")

    assert gone == [SEED_KEYS[0]]
    assert len(exported) == 5
    assert gone[0] not in [o.key for o in exported]


def test_export_object_rewritten_after_listing_is_consistent() -> None:
    """An object rewritten between listing and get carries the new data,
    metadata, and version together (AIE-1291, US4.9).
    """
    h = _seeded()
    new_data = b"- [stated] rewritten\n"
    new_metadata = valid_metadata("rewritten")
    versions: list[VersionToken] = []

    def rewrite_first(result: Sequence[ListedObject]) -> None:
        versions.append(h.inner.put(result[0].key, new_data, new_metadata))

    _on_first_list(h, rewrite_first)

    exported = _m(h).export("user", "u1")

    first = next(o for o in exported if o.key == SEED_KEYS[0])
    assert first.data == new_data
    assert dict(first.metadata) == new_metadata
    assert first.version == versions[0]


_NON_STR_ARGS: dict[str, tuple[object, object]] = {
    "int_scope": (1, "u1"),
    "none_entity": ("user", None),
    "bytes_scope": (b"user", "u1"),
    "spoofed_scope": (_SpoofedStr(), "u1"),
    "spoofed_entity": ("user", _SpoofedStr()),
}

_INVALID_SEGMENTS: dict[str, tuple[str, str, str]] = {
    "empty_scope": ("", "u1", r"^invalid scope: ''$"),
    "slash_scope": ("a/b", "u1", r"^invalid scope: 'a/b'$"),
    "dotdot_scope": ("..", "u1", r"^invalid scope: '\.\.'$"),
    "empty_entity": ("user", "", r"^invalid entity_id: ''$"),
    "slash_entity": ("user", "a/b", r"^invalid entity_id: 'a/b'$"),
    "dotdot_entity": ("user", "..", r"^invalid entity_id: '\.\.'$"),
}


@pytest.mark.parametrize(
    ("scope", "entity_id"), list(_NON_STR_ARGS.values()), ids=list(_NON_STR_ARGS)
)
def test_export_rejects_non_str(scope: object, entity_id: object) -> None:
    """A non-str scope or entity_id raises TypeError with no storage call
    (AIE-1291, US4.10).
    """
    h = _seeded()

    with pytest.raises(TypeError):
        _m(h).export(cast(Any, scope), cast(Any, entity_id))

    assert h.calls == []


@pytest.mark.parametrize(
    ("scope", "entity_id", "message"), list(_INVALID_SEGMENTS.values()), ids=list(_INVALID_SEGMENTS)
)
def test_export_rejects_invalid_segments(scope: str, entity_id: str, message: str) -> None:
    """An invalid scope or entity_id raises ValueError naming it, with no
    storage call (AIE-1291, US4.10).
    """
    h = _seeded()

    with pytest.raises(ValueError, match=message):
        _m(h).export(scope, entity_id)

    assert h.calls == []


def test_exported_object_copies_metadata() -> None:
    """Mutating the dict passed to ExportedObject leaves its metadata
    unchanged (AIE-1291, US4.11a).
    """
    m = {"a": "1"}
    o = ExportedObject("user/u1/notes/a.md", b"data", m, VersionToken("1"))

    m["a"] = "mutated"
    m["b"] = "new"

    assert dict(o.metadata) == {"a": "1"}


def _immutable_cases() -> list[ExportedObject]:
    h = _seeded()
    exported = _m(h).export("user", "u1")
    built = ExportedObject("user/u1/notes/a.md", b"data", {"a": "1"}, VersionToken("1"))
    return [built, exported[0]]


@pytest.mark.parametrize("which", [0, 1], ids=["constructed", "exported"])
def test_exported_object_is_read_only(which: int) -> None:
    """ExportedObject metadata rejects item assignment and its fields are
    frozen (AIE-1291, US4.11b).
    """
    o = _immutable_cases()[which]

    with pytest.raises(TypeError):
        cast(Any, o.metadata)["x"] = "y"
    with pytest.raises(dataclasses.FrozenInstanceError):
        cast(Any, o).data = b""


def test_export_propagates_list_page_failure() -> None:
    """A BackendUnavailableError from list_page propagates (AIE-1291, US4.12)."""
    h = _seeded()
    error = BackendUnavailableError(TransientReason.UNAVAILABLE)

    def fail(prefix: str, start_after: str | None, limit: int) -> None:
        raise error

    h.before_list = fail

    with pytest.raises(BackendUnavailableError) as excinfo:
        _m(h).export("user", "u1")

    assert excinfo.value is error


def test_export_propagates_get_failure() -> None:
    """A BackendUnavailableError from get propagates (AIE-1291, US4.12)."""
    h = _seeded()
    error = BackendUnavailableError(TransientReason.TIMEOUT)

    def fail(key: str) -> None:
        raise error

    h.before_get = fail

    with pytest.raises(BackendUnavailableError) as excinfo:
        _m(h).export("user", "u1")

    assert excinfo.value is error
