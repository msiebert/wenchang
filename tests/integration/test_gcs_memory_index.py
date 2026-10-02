"""Integration tests for MemoryStore.get_memory_index on GcsStorage against a
fake-gcs-server emulator (AIE-1046, SC-002).

Covers fan-out with page draining (US1.3) and the byte cap (US3.3) on a real
`google.cloud.storage.Client`, since the index drains `list_page` on the backend.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from google.auth.credentials import AnonymousCredentials
from google.cloud.storage import Client  # pyright: ignore[reportMissingTypeStubs]

from wenchang.core import CappedPrefix, FileEntry, MemoryStore, index_entry_bytes
from wenchang.file_format import FileMetadata, metadata_to_map
from wenchang.storage import Storage
from wenchang.storage.gcs import GcsStorage

pytestmark = pytest.mark.integration

_BASE = datetime(2024, 1, 1, tzinfo=UTC)


@pytest.fixture
def storage(storage_emulator_host: str) -> Iterator[Storage]:
    client = Client(
        project="test",
        credentials=AnonymousCredentials(),
        client_options={"api_endpoint": storage_emulator_host},
    )
    bucket_name = f"wenchang-test-{uuid.uuid4().hex}"
    bucket = client.create_bucket(bucket_name)  # pyright: ignore[reportUnknownMemberType]
    try:
        yield GcsStorage(bucket)
    finally:
        try:
            for blob in bucket.list_blobs():  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
                blob.delete()  # pyright: ignore[reportUnknownMemberType]
            bucket.delete()  # pyright: ignore[reportUnknownMemberType]
        except Exception:
            pass  # best-effort cleanup; the emulator's data is ephemeral anyway


def _seed(storage: Storage, path: str, last_updated: datetime) -> None:
    metadata = FileMetadata(
        description="d",
        aliases=(),
        sources=frozenset({"t"}),
        last_updated=last_updated,
    )
    storage.put(path, b"body\n", metadata_to_map(metadata))


def _seed_fixture(storage: Storage) -> tuple[dict[str, str], list[str]]:
    """Seed five user notes and two org glossary files; return the scope map
    and the paths in expected index order (most recent first).
    """
    run = uuid.uuid4().hex
    user_id = f"u-{run}"
    org_id = f"o-{run}"
    # The oldest file is an org glossary entry, so it is the one a cap drops.
    seeded = [
        (f"org/{org_id}/glossary/g0.md", 0),
        (f"user/{user_id}/notes/n1.md", 1),
        (f"user/{user_id}/notes/n2.md", 2),
        (f"user/{user_id}/notes/n3.md", 3),
        (f"org/{org_id}/glossary/g4.md", 4),
        (f"user/{user_id}/notes/n5.md", 5),
        (f"user/{user_id}/notes/n6.md", 6),
    ]
    for path, hours in seeded:
        _seed(storage, path, _BASE + timedelta(hours=hours))
    expected_order = [path for path, _ in reversed(seeded)]
    return {"user": user_id, "org": org_id}, expected_order


def _drain(store: MemoryStore, prefix: str) -> list[FileEntry]:
    entries: list[FileEntry] = []
    page = store.list_prefix(prefix)
    entries.extend(page.entries)
    while page.next_cursor is not None:
        page = store.list_prefix(prefix, page.next_cursor)
        entries.extend(page.entries)
    return entries


def test_get_memory_index_drains_every_page_and_orders_by_recency(storage: Storage) -> None:
    """With list_page_size=2, get_memory_index on GcsStorage drains every page
    of each scope, returns all seven files equal to what list_prefix returns,
    and orders them by last-updated, most recent first (AIE-1046, SC-002, US1.3).
    """
    scope_map, expected_order = _seed_fixture(storage)
    store = MemoryStore(storage, list_page_size=2)

    index = store.get_memory_index(scope_map)

    assert [entry.path for entry in index.entries] == expected_order
    assert index.capped == ()
    listed = _drain(store, f"user/{scope_map['user']}/") + _drain(store, f"org/{scope_map['org']}/")
    by_path = {entry.path: entry for entry in listed}
    assert len(by_path) == 7
    assert {entry.path: entry for entry in index.entries} == by_path


def test_get_memory_index_caps_last_entry_one_byte_under_total(storage: Storage) -> None:
    """With index_max_bytes one less than the total entry size, the oldest
    entry is omitted and reported as exactly one CappedPrefix for its area
    with omitted=1 (AIE-1046, SC-002, US3.3).
    """
    scope_map, expected_order = _seed_fixture(storage)
    lister = MemoryStore(storage, list_page_size=2)
    listed = _drain(lister, f"user/{scope_map['user']}/") + _drain(
        lister, f"org/{scope_map['org']}/"
    )
    assert len(listed) == 7
    total = sum(index_entry_bytes(entry) for entry in listed)
    store = MemoryStore(storage, list_page_size=2, index_max_bytes=total - 1)

    index = store.get_memory_index(scope_map)

    assert [entry.path for entry in index.entries] == expected_order[:-1]
    assert index.capped == (CappedPrefix(f"org/{scope_map['org']}/glossary/", 1),)
