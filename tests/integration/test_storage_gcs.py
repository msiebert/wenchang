"""Integration tests for GcsStorage against a fake-gcs-server emulator
(AIE-1032).

Runs the shared `StorageConformance` suite (spec US4 scenarios 1-6) against
a real `google.cloud.storage.Client` pointed at the emulator, plus a
GCS-specific smoke check that put/get round-trip through the real client
stack (blob metadata, generation-based version tokens, content type).
"""

import uuid
from collections.abc import Iterator

import pytest
from google.auth.credentials import AnonymousCredentials
from google.cloud.storage import Client  # pyright: ignore[reportMissingTypeStubs]

from storage_conformance import StorageConformance
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


class TestGcsStorage(StorageConformance):
    """Runs the shared conformance suite against GcsStorage and the emulator
    (AIE-1032, US4-1 through US4-6).
    """


def test_put_then_get_round_trips_through_real_client_stack(storage: Storage) -> None:
    """A put/get round trip through the real google-cloud-storage client and
    the fake-gcs-server emulator preserves bytes and metadata, and get()
    reports the token returned by put() (AIE-1032, US3-2).
    """
    data = b"hello, wenchang"
    metadata = {"lang": "en"}

    token = storage.put("some/key.md", data, metadata)
    result = storage.get("some/key.md")

    assert result is not None
    assert result.data == data
    assert dict(result.metadata) == metadata
    assert result.version == token
