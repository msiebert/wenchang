"""Integration test for the per-entity file cap on GcsStorage against a
fake-gcs-server emulator (AIE-1292, SC-002).
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from google.auth.credentials import AnonymousCredentials
from google.cloud.storage import Client  # pyright: ignore[reportMissingTypeStubs]

from wenchang.core import MemoryFile, MemoryStore
from wenchang.errors import FileQuotaExceededError
from wenchang.file_format import FileMetadata
from wenchang.storage import Storage
from wenchang.storage.gcs import GcsStorage

pytestmark = pytest.mark.integration


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


def _create(store: MemoryStore, path: str) -> MemoryFile:
    metadata = FileMetadata("d", (), frozenset(), datetime(2024, 1, 1, tzinfo=UTC))
    return store.write_file(path, "- [stated] x\n", metadata, None, source="test")


def test_file_cap_on_gcs(storage: Storage) -> None:
    """With cap 2 on GcsStorage, a system/ file does not count, a third create
    raises FileQuotaExceededError and stores nothing, and deleting a file frees
    a slot (AIE-1292, SC-002).
    """
    entity = f"user/u-{uuid.uuid4().hex}/"
    store = MemoryStore(storage, list_page_size=1, max_files_per_entity=2)
    _create(store, f"{entity}system/profile.md")
    first = _create(store, f"{entity}notes/a.md")
    _create(store, f"{entity}notes/b.md")

    with pytest.raises(FileQuotaExceededError) as info:
        _create(store, f"{entity}notes/c.md")
    assert info.value.limit == 2
    assert storage.get(f"{entity}notes/c.md") is None

    store.delete_file(first.path, first.version)
    created = _create(store, f"{entity}notes/c.md")

    assert created.path == f"{entity}notes/c.md"
