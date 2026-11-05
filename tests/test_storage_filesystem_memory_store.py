"""MemoryStore end to end on FilesystemStorage (AIE-1335, AC2).

A smoke-level pass over create, read, update, version conflict, delete, the
memory index, export and purge. The core behavior is covered against
InMemoryStorage elsewhere; this checks the filesystem backend carries it.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from wenchang.core import MemoryStore
from wenchang.errors import NotFoundError, VersionConflictError
from wenchang.file_format import FileMetadata
from wenchang.storage.filesystem import FilesystemStorage

pytestmark = pytest.mark.unit

CLOCK_TIME = datetime(2025, 3, 1, 12, 0, 0, tzinfo=UTC)
PATH = "user/u1/notes/a.md"


def _meta(description: str = "desc") -> FileMetadata:
    return FileMetadata(
        description=description,
        aliases=("alias-one",),
        sources=frozenset({"seed"}),
        last_updated=datetime(2024, 1, 1, tzinfo=UTC),
    )


@pytest.fixture
def store(tmp_path: Path) -> MemoryStore:
    return MemoryStore(FilesystemStorage(tmp_path / "root"), clock=lambda: CLOCK_TIME)


def test_create_then_read_round_trips_content_and_metadata(store: MemoryStore) -> None:
    """A created file reads back with its content, metadata, stamped time and
    version (AIE-1335, AC2).
    """
    written = store.write_file(PATH, "- fact café\n", _meta("first"), None, source="agent")
    read = store.read_file(PATH)
    assert read.content == "- fact café\n"
    assert read.metadata.description == "first"
    assert read.metadata.aliases == ("alias-one",)
    assert read.metadata.sources == frozenset({"seed", "agent"})
    assert read.metadata.last_updated == CLOCK_TIME
    assert read.version == written.version


def test_update_with_current_version_succeeds_and_stale_version_conflicts(
    store: MemoryStore,
) -> None:
    """An update with the current version lands; one with the old version
    raises VersionConflictError carrying the current content (AIE-1335, AC2).
    """
    first = store.write_file(PATH, "one\n", _meta(), None, source="agent")
    second = store.write_file(PATH, "two\n", _meta(), first.version, source="agent")
    assert second.version != first.version

    with pytest.raises(VersionConflictError) as excinfo:
        store.write_file(PATH, "three\n", _meta(), first.version, source="agent")
    assert excinfo.value.content == "two\n"
    assert excinfo.value.version == second.version
    assert store.read_file(PATH).content == "two\n"


def test_create_over_existing_file_conflicts(store: MemoryStore) -> None:
    """Creating a path that already exists raises VersionConflictError
    (AIE-1335, AC2).
    """
    store.write_file(PATH, "one\n", _meta(), None, source="agent")
    with pytest.raises(VersionConflictError):
        store.write_file(PATH, "again\n", _meta(), None, source="agent")


def test_delete_with_current_version_removes_the_file(store: MemoryStore) -> None:
    """delete_file with the current version removes the file; a stale version
    conflicts first (AIE-1335, AC2).
    """
    first = store.write_file(PATH, "one\n", _meta(), None, source="agent")
    second = store.write_file(PATH, "two\n", _meta(), first.version, source="agent")
    with pytest.raises(VersionConflictError):
        store.delete_file(PATH, first.version)
    store.delete_file(PATH, second.version)
    with pytest.raises(NotFoundError):
        store.read_file(PATH)


def test_memory_index_lists_the_files(store: MemoryStore) -> None:
    """get_memory_index returns every file for the scope, most recently
    updated first (AIE-1335, AC2).
    """
    store.write_file("user/u1/notes/a.md", "a\n", _meta("da"), None, source="agent")
    store.write_file("user/u1/prefs/b.md", "b\n", _meta("db"), None, source="agent")
    store.write_file("user/u10/notes/other.md", "x\n", _meta("dx"), None, source="agent")

    index = store.get_memory_index({"user": "u1"})
    assert sorted(e.path for e in index.entries) == [
        "user/u1/notes/a.md",
        "user/u1/prefs/b.md",
    ]
    assert index.capped == ()
    descriptions = {e.path: e.metadata.description for e in index.entries}
    assert descriptions == {"user/u1/notes/a.md": "da", "user/u1/prefs/b.md": "db"}


def test_export_then_purge_removes_the_entity_and_spares_neighbours(
    store: MemoryStore,
) -> None:
    """export returns the entity's objects, purge returns their count and
    removes them, and a neighbouring entity is untouched (AIE-1335, AC2).
    """
    keys = ["user/u1/notes/a.md", "user/u1/notes/b.md", "user/u1/prefs/c.md"]
    for key in keys:
        store.write_file(key, f"{key}\n", _meta(), None, source="agent")
    store.write_file("user/u10/notes/a.md", "keep\n", _meta(), None, source="agent")

    exported = store.export("user", "u1")
    assert [o.key for o in exported] == keys
    assert [o.data for o in exported] == [f"{k}\n".encode() for k in keys]

    assert store.purge("user", "u1") == 3
    assert store.export("user", "u1") == ()
    assert store.read_file("user/u10/notes/a.md").content == "keep\n"


def test_state_persists_to_a_fresh_store_on_the_same_root(tmp_path: Path) -> None:
    """A second MemoryStore on a new FilesystemStorage over the same root sees
    the file and its version, and can update it (AIE-1335, AC2).
    """
    root = tmp_path / "root"
    first_store = MemoryStore(FilesystemStorage(root), clock=lambda: CLOCK_TIME)
    written = first_store.write_file(PATH, "one\n", _meta(), None, source="agent")

    second_store = MemoryStore(FilesystemStorage(root), clock=lambda: CLOCK_TIME)
    read = second_store.read_file(PATH)
    assert read.content == "one\n"
    assert read.version == written.version
    updated = second_store.write_file(PATH, "two\n", _meta(), read.version, source="agent")
    assert first_store.read_file(PATH).version == updated.version
