"""Tests for the per-entity file-count cap on MemoryStore.write_file (AIE-1292)."""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

import pytest

from wenchang.core import (
    DEFAULT_MAX_FILES_PER_ENTITY,
    ListCursor,
    ListPage,
    MemoryFile,
    MemoryStore,
)
from wenchang.errors import FileQuotaExceededError, OversizeWriteError, VersionConflictError
from wenchang.file_format import FileMetadata, MetadataFormatError, metadata_to_map
from wenchang.paths import is_valid_path, parse_path
from wenchang.storage import ListedObject, StoredObject
from wenchang.storage.memory import InMemoryStorage
from wenchang.version_token import VersionToken

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 10, 30, 12, 0, 0, tzinfo=UTC)
_SOURCE = "test"
_ENTITY = "user/u1/"


def _clock() -> datetime:
    return _NOW


def _metadata() -> FileMetadata:
    return FileMetadata(
        description="d",
        aliases=(),
        sources=frozenset({"seed"}),
        last_updated=datetime(2024, 1, 1, tzinfo=UTC),
    )


def _store(
    storage: InMemoryStorage, cap: int | None = 3, *, list_page_size: int = 100
) -> MemoryStore:
    return MemoryStore(
        storage, clock=_clock, list_page_size=list_page_size, max_files_per_entity=cap
    )


def _seed(storage: InMemoryStorage, path: str, body: str = "- [stated] x\n") -> VersionToken:
    return storage.put(path, body.encode("utf-8"), metadata_to_map(_metadata()))


def _create(store: MemoryStore, path: str, content: str = "- [stated] x\n") -> MemoryFile:
    return store.write_file(path, content, _metadata(), None, source=_SOURCE)


def _fill(
    store: MemoryStore, n: int, prefix: str = _ENTITY, area: str = "notes"
) -> list[MemoryFile]:
    return [_create(store, f"{prefix}{area}/f{i}.md") for i in range(n)]


def _counted(storage: InMemoryStorage, prefix: str = _ENTITY) -> int:
    keys = [obj.key for obj in storage.list_page(prefix, None, 10_000)]
    return sum(1 for key in keys if is_valid_path(key) and parse_path(key).area != "system")


class _WrappedStorage:
    """Delegates to an InMemoryStorage; `get` of `hidden` returns None."""

    def __init__(self, inner: InMemoryStorage, hidden: str | None = None) -> None:
        self.inner = inner
        self.hidden = hidden
        self.list_page_calls: list[tuple[str, str | None, int]] = []

    def get(self, key: str) -> StoredObject | None:
        if key == self.hidden:
            return None
        return self.inner.get(key)

    def put(self, key: str, data: bytes, metadata: Mapping[str, str]) -> VersionToken:
        return self.inner.put(key, data, metadata)

    def put_if_version(
        self,
        key: str,
        data: bytes,
        metadata: Mapping[str, str],
        expected: VersionToken | None,
    ) -> VersionToken:
        return self.inner.put_if_version(key, data, metadata, expected)

    def delete_if_version(self, key: str, expected: VersionToken) -> None:
        self.inner.delete_if_version(key, expected)

    def list_page(self, prefix: str, start_after: str | None, limit: int) -> Sequence[ListedObject]:
        self.list_page_calls.append((prefix, start_after, limit))
        return self.inner.list_page(prefix, start_after, limit)


class _EmptyListingStore(MemoryStore):
    """A MemoryStore whose list_prefix always reports no files."""

    def list_prefix(self, prefix: str, cursor: ListCursor | None = None) -> ListPage:
        return ListPage(entries=(), next_cursor=None)


# --- setting ------------------------------------------------------------------


def test_default_max_files_per_entity_is_500() -> None:
    """core.DEFAULT_MAX_FILES_PER_ENTITY is 500 and is the store's default cap
    (AIE-1292, US1.3, FR-001).
    """
    assert DEFAULT_MAX_FILES_PER_ENTITY == 500
    store = MemoryStore(InMemoryStorage())
    assert store.max_files_per_entity == 500
    assert store.max_files_per_entity == DEFAULT_MAX_FILES_PER_ENTITY


@pytest.mark.parametrize("cap", [1, 3, 7, None])
def test_max_files_per_entity_is_configurable(cap: int | None) -> None:
    """max_files_per_entity reads back the configured value, None included
    (AIE-1292, FR-001, US6.1).
    """
    store = MemoryStore(InMemoryStorage(), max_files_per_entity=cap)
    assert store.max_files_per_entity == cap


def test_max_files_per_entity_is_read_only() -> None:
    """The max_files_per_entity property cannot be assigned (AIE-1292, FR-001)."""
    store = MemoryStore(InMemoryStorage(), max_files_per_entity=3)
    with pytest.raises(AttributeError):
        setattr(store, "max_files_per_entity", 4)  # noqa: B010
    assert store.max_files_per_entity == 3


@pytest.mark.parametrize("cap", [0, -1])
def test_non_positive_max_files_per_entity_is_rejected(cap: int) -> None:
    """max_files_per_entity 0 or -1 raises ValueError with the exact message
    (AIE-1292, US6.2).
    """
    with pytest.raises(ValueError, match=r"^max_files_per_entity must be positive or None$"):
        MemoryStore(InMemoryStorage(), max_files_per_entity=cap)


def test_index_max_bytes_check_precedes_max_files_check() -> None:
    """The index_max_bytes positivity check runs before the max_files_per_entity
    check (AIE-1292, FR-001).
    """
    with pytest.raises(ValueError, match=r"^index_max_bytes must be positive$"):
        MemoryStore(InMemoryStorage(), index_max_bytes=0, max_files_per_entity=0)


def test_bool_cap_is_accepted_as_one() -> None:
    """max_files_per_entity=True is not type-checked and acts as a cap of 1
    (AIE-1292, FR-001).
    """
    store = MemoryStore(InMemoryStorage(), max_files_per_entity=True)
    _create(store, "user/u1/notes/a.md")
    with pytest.raises(FileQuotaExceededError) as info:
        _create(store, "user/u1/notes/b.md")
    assert info.value.limit == 1


# --- US1: a runaway agent cannot create unbounded files -------------------------


def test_create_past_cap_is_rejected_and_nothing_is_stored() -> None:
    """With cap 3 and 3 counted files, creating a 4th raises
    FileQuotaExceededError with the requested path and limit 3, and nothing is
    stored (AIE-1292, US1.1).
    """
    storage = InMemoryStorage()
    store = _store(storage)
    _fill(store, 3)
    path = "user/u1/notes/new.md"

    with pytest.raises(FileQuotaExceededError) as info:
        _create(store, path)

    assert info.value.path == path
    assert info.value.limit == 3
    assert storage.get(path) is None
    assert _counted(storage) == 3


def test_create_up_to_cap_is_allowed() -> None:
    """With cap 3 and 2 counted files, creating a 3rd succeeds: the cap is
    inclusive (AIE-1292, US1.2).
    """
    storage = InMemoryStorage()
    store = _store(storage)
    _fill(store, 2)

    created = _create(store, "user/u1/notes/third.md")

    assert created.path == "user/u1/notes/third.md"
    assert _counted(storage) == 3


def test_default_cap_rejects_the_501st_file() -> None:
    """Under the default cap an entity may hold 500 counted files and the 501st
    create raises FileQuotaExceededError with limit 500 (AIE-1292, US1.3).
    """
    storage = InMemoryStorage()
    for i in range(499):
        _seed(storage, f"user/u1/notes/f{i:03d}.md")
    store = MemoryStore(storage, clock=_clock)

    _create(store, "user/u1/notes/f499.md")
    with pytest.raises(FileQuotaExceededError) as info:
        _create(store, "user/u1/notes/f500.md")

    assert info.value.limit == 500
    assert storage.get("user/u1/notes/f500.md") is None


# --- US2: existing files stay editable at the cap ------------------------------


def test_replace_with_version_at_cap_succeeds() -> None:
    """At the cap, write_file with the current version token replaces the file
    (AIE-1292, US2.1).
    """
    store = _store(InMemoryStorage())
    files = _fill(store, 3)

    replaced = store.write_file(
        files[0].path, "- [stated] y\n", _metadata(), files[0].version, source=_SOURCE
    )

    assert replaced.content == "- [stated] y\n"
    assert store.read_file(files[0].path).content == "- [stated] y\n"


def test_append_line_at_cap_succeeds() -> None:
    """At the cap, append_line appends to an existing file (AIE-1292, US2.2)."""
    store = _store(InMemoryStorage())
    files = _fill(store, 3)

    appended = store.append_line(files[1].path, "- [stated] z", files[1].version, source=_SOURCE)

    assert appended.content == "- [stated] x\n- [stated] z\n"


def test_replace_fact_at_cap_succeeds() -> None:
    """At the cap, replace_fact edits an existing file (AIE-1292, US2.3)."""
    store = _store(InMemoryStorage())
    files = _fill(store, 3)

    edited = store.replace_fact(
        files[2].path, "- [stated] x", "- [stated] w", files[2].version, source=_SOURCE
    )

    assert edited.content == "- [stated] w\n"


def test_create_existing_path_at_cap_is_version_conflict() -> None:
    """At the cap, creating a path that already exists raises
    VersionConflictError with its current content and version, not
    FileQuotaExceededError (AIE-1292, US2.4).
    """
    storage = InMemoryStorage()
    store = _store(storage)
    files = _fill(store, 3)

    with pytest.raises(VersionConflictError) as info:
        _create(store, files[0].path, "- [stated] other\n")

    assert not isinstance(info.value, FileQuotaExceededError)
    assert info.value.path == files[0].path
    assert info.value.content == "- [stated] x\n"
    assert info.value.version == files[0].version
    assert store.read_file(files[0].path).version == files[0].version


def test_create_vanished_path_at_cap_is_quota_error() -> None:
    """At the cap, when get of the requested path returns None (the file
    vanished after the count), the create raises FileQuotaExceededError
    (AIE-1292, US2.5).
    """
    inner = InMemoryStorage()
    path = "user/u1/notes/gone.md"
    _seed(inner, "user/u1/notes/a.md")
    _seed(inner, "user/u1/notes/b.md")
    original = _seed(inner, path)
    store = MemoryStore(_WrappedStorage(inner, hidden=path), clock=_clock, max_files_per_entity=3)

    with pytest.raises(FileQuotaExceededError) as info:
        _create(store, path, "- [stated] new\n")

    assert info.value.path == path
    assert info.value.limit == 3
    stored = inner.get(path)
    assert stored is not None
    assert stored.version == original


def test_create_existing_path_with_corrupt_metadata_at_cap_propagates() -> None:
    """At the cap, creating a path whose stored object has corrupt metadata
    propagates MetadataFormatError and stores nothing (AIE-1292, US2.6).
    """
    storage = InMemoryStorage()
    path = "user/u1/notes/corrupt.md"
    _seed(storage, "user/u1/notes/a.md")
    _seed(storage, "user/u1/notes/b.md")
    original = storage.put(path, b"- [stated] x\n", {"description": "only"})
    store = _store(storage)

    with pytest.raises(MetadataFormatError):
        _create(store, path, "- [stated] new\n")

    stored = storage.get(path)
    assert stored is not None
    assert stored.version == original


def test_create_existing_path_with_non_utf8_content_at_cap_propagates() -> None:
    """At the cap, creating a path whose stored content is not valid UTF-8
    propagates UnicodeDecodeError and stores nothing (AIE-1292, US2.6).
    """
    storage = InMemoryStorage()
    path = "user/u1/notes/binary.md"
    _seed(storage, "user/u1/notes/a.md")
    _seed(storage, "user/u1/notes/b.md")
    original = storage.put(path, b"\xff\xfe", metadata_to_map(_metadata()))
    store = _store(storage)

    with pytest.raises(UnicodeDecodeError):
        _create(store, path, "- [stated] new\n")

    stored = storage.get(path)
    assert stored is not None
    assert stored.version == original


# --- US3: deleting a file frees a slot ------------------------------------------


def test_delete_frees_a_slot() -> None:
    """At the cap, deleting one file lets a new create succeed, leaving exactly
    limit counted files (AIE-1292, US3.1).
    """
    storage = InMemoryStorage()
    store = _store(storage)
    files = _fill(store, 3)
    with pytest.raises(FileQuotaExceededError):
        _create(store, "user/u1/notes/new.md")

    store.delete_file(files[0].path, files[0].version)
    _create(store, "user/u1/notes/new.md")

    assert _counted(storage) == 3
    assert store.read_file("user/u1/notes/new.md").content == "- [stated] x\n"


# --- US4: the limit is per entity and excludes system/ ---------------------------


def test_other_entity_in_same_scope_is_unaffected() -> None:
    """With user/u1/ at the cap, a create under user/u2/ succeeds (AIE-1292, US4.1)."""
    store = _store(InMemoryStorage())
    _fill(store, 3)

    created = _create(store, "user/u2/notes/a.md")

    assert created.path == "user/u2/notes/a.md"


def test_same_entity_id_in_other_scope_is_unaffected() -> None:
    """With user/u1/ at the cap, a create under project/u1/ succeeds: the same
    entity ID in another scope is another entity (AIE-1292, US4.2).
    """
    store = _store(InMemoryStorage())
    _fill(store, 3)

    created = _create(store, "project/u1/notes/a.md")

    assert created.path == "project/u1/notes/a.md"


def test_system_files_do_not_count_at_cap() -> None:
    """With 2 system/ files and 3 other files over two areas, a create under
    notes/ raises FileQuotaExceededError (AIE-1292, US4.3).
    """
    storage = InMemoryStorage()
    _seed(storage, "user/u1/system/profile.md")
    _seed(storage, "user/u1/system/rules.md")
    _seed(storage, "user/u1/notes/a.md")
    _seed(storage, "user/u1/notes/b.md")
    _seed(storage, "user/u1/preferences/c.md")
    store = _store(storage)

    with pytest.raises(FileQuotaExceededError) as info:
        _create(store, "user/u1/notes/new.md")

    assert info.value.limit == 3
    assert storage.get("user/u1/notes/new.md") is None


def test_system_files_do_not_count_below_cap() -> None:
    """With 2 system/ files and 2 other files, a create under notes/ succeeds
    (AIE-1292, US4.4).
    """
    storage = InMemoryStorage()
    _seed(storage, "user/u1/system/profile.md")
    _seed(storage, "user/u1/system/rules.md")
    _seed(storage, "user/u1/notes/a.md")
    _seed(storage, "user/u1/preferences/b.md")
    store = _store(storage)

    _create(store, "user/u1/notes/new.md")

    assert _counted(storage) == 3


def test_system_create_at_cap_is_not_checked() -> None:
    """With 3 counted files, MemoryStore.write_file creating
    user/u1/system/x.md succeeds (AIE-1292, US4.5).
    """
    store = _store(InMemoryStorage())
    _fill(store, 3)

    created = _create(store, "user/u1/system/x.md", "- [system] x\n")

    assert created.path == "user/u1/system/x.md"


def test_malformed_keys_do_not_count() -> None:
    """With 2 well-formed files plus 2 malformed keys under user/u1/, a 3rd
    well-formed create succeeds (AIE-1292, US4.6).
    """
    storage = InMemoryStorage()
    _seed(storage, "user/u1/notes/a.md")
    _seed(storage, "user/u1/notes/b.md")
    _seed(storage, "user/u1/notes/c.txt")
    _seed(storage, "user/u1/deep/nested/d.md")
    store = _store(storage)

    created = _create(store, "user/u1/notes/third.md")

    assert created.path == "user/u1/notes/third.md"


# --- US6: adopters disable the cap ----------------------------------------------


def test_none_cap_allows_more_than_500_files() -> None:
    """With max_files_per_entity=None, 501 creates under one entity all succeed
    and the property reads None (AIE-1292, US6.1).
    """
    storage = InMemoryStorage()
    store = _store(storage, cap=None)

    for i in range(501):
        _create(store, f"user/u1/notes/f{i:03d}.md")

    assert store.max_files_per_entity is None
    assert _counted(storage) == 501


# --- edge cases -----------------------------------------------------------------


def test_oversize_create_at_cap_is_oversize_error() -> None:
    """An oversize create at the cap raises OversizeWriteError: the size check
    precedes the cap check (AIE-1292, edge case).
    """
    storage = InMemoryStorage()
    store = MemoryStore(storage, clock=_clock, max_file_bytes=32, max_files_per_entity=3)
    _fill(store, 3)

    with pytest.raises(OversizeWriteError):
        _create(store, "user/u1/notes/big.md", "- [stated] " + "x" * 64 + "\n")

    assert storage.get("user/u1/notes/big.md") is None


def test_corrupt_metadata_on_another_file_does_not_block_create() -> None:
    """Corrupt metadata on another file under the entity does not block a create
    below the cap (AIE-1292, edge case).
    """
    storage = InMemoryStorage()
    storage.put("user/u1/notes/corrupt.md", b"- [stated] x\n", {"description": "only"})
    _seed(storage, "user/u1/notes/a.md")
    store = _store(storage)

    created = _create(store, "user/u1/notes/new.md")

    assert created.path == "user/u1/notes/new.md"


def test_corrupt_metadata_on_another_file_counts_toward_cap() -> None:
    """A file with corrupt metadata is still a counted file (AIE-1292, edge case)."""
    storage = InMemoryStorage()
    storage.put("user/u1/notes/corrupt.md", b"- [stated] x\n", {"description": "only"})
    _seed(storage, "user/u1/notes/a.md")
    _seed(storage, "user/u1/notes/b.md")
    store = _store(storage)

    with pytest.raises(FileQuotaExceededError):
        _create(store, "user/u1/notes/new.md")


def test_count_ignores_list_prefix_override() -> None:
    """The cap counts through Storage.list_page, so a subclass overriding
    list_prefix does not change the count (AIE-1292, edge case).
    """
    storage = InMemoryStorage()
    _seed(storage, "user/u1/notes/a.md")
    _seed(storage, "user/u1/notes/b.md")
    _seed(storage, "user/u1/notes/c.md")
    store = _EmptyListingStore(storage, clock=_clock, max_files_per_entity=3)

    with pytest.raises(FileQuotaExceededError):
        _create(store, "user/u1/notes/new.md")


def test_count_uses_storage_list_page_under_entity_prefix() -> None:
    """The cap check lists the entity prefix through Storage.list_page
    (AIE-1292, FR-002).
    """
    inner = InMemoryStorage()
    wrapped = _WrappedStorage(inner)
    store = MemoryStore(wrapped, clock=_clock, max_files_per_entity=3)

    _create(store, "user/u1/notes/a.md")

    assert wrapped.list_page_calls
    assert all(prefix == "user/u1/" for prefix, _, _ in wrapped.list_page_calls)


def test_system_create_does_not_list() -> None:
    """A create under system/ never consults the cap, so it does not list
    (AIE-1292, FR-003).
    """
    wrapped = _WrappedStorage(InMemoryStorage())
    store = MemoryStore(wrapped, clock=_clock, max_files_per_entity=3)

    _create(store, "user/u1/system/x.md", "- [system] x\n")

    assert wrapped.list_page_calls == []


def test_none_cap_create_does_not_list() -> None:
    """With the cap disabled, a create does not list (AIE-1292, FR-002)."""
    wrapped = _WrappedStorage(InMemoryStorage())
    store = MemoryStore(wrapped, clock=_clock, max_files_per_entity=None)

    _create(store, "user/u1/notes/x.md")

    assert wrapped.list_page_calls == []


def test_small_page_size_with_leading_system_keys_reaches_cap() -> None:
    """With list_page_size=1 and several system/ keys sorting before the counted
    keys, the count still reaches the cap (AIE-1292, edge case).
    """
    storage = InMemoryStorage()
    for name in ("a", "b", "c", "d", "e"):
        _seed(storage, f"user/u1/system/{name}.md")
    _seed(storage, "user/u1/workflows/w1.md")
    _seed(storage, "user/u1/workflows/w2.md")
    _seed(storage, "user/u1/workflows/w3.md")
    store = _store(storage, list_page_size=1)

    with pytest.raises(FileQuotaExceededError) as info:
        _create(store, "user/u1/workflows/w4.md")

    assert info.value.limit == 3
    assert storage.get("user/u1/workflows/w4.md") is None


def test_small_page_size_with_leading_system_keys_below_cap() -> None:
    """With list_page_size=1 and several system/ keys sorting before 2 counted
    keys, a create succeeds (AIE-1292, edge case).
    """
    storage = InMemoryStorage()
    for name in ("a", "b", "c", "d", "e"):
        _seed(storage, f"user/u1/system/{name}.md")
    _seed(storage, "user/u1/workflows/w1.md")
    _seed(storage, "user/u1/workflows/w2.md")
    store = _store(storage, list_page_size=1)

    _create(store, "user/u1/workflows/w3.md")

    assert _counted(storage) == 3


def test_lowered_cap_blocks_creates_but_keeps_files() -> None:
    """A cap below the entity's current count blocks creates and removes no
    files (AIE-1292, edge case).
    """
    storage = InMemoryStorage()
    for i in range(5):
        _seed(storage, f"user/u1/notes/f{i}.md")
    store = _store(storage)

    with pytest.raises(FileQuotaExceededError):
        _create(store, "user/u1/notes/new.md")

    assert _counted(storage) == 5
