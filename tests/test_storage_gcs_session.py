"""GcsStorage builds the bucket client's HTTP session on construction (AIE-1316)."""

from typing import Any

import pytest
from google.auth.credentials import AnonymousCredentials
from google.cloud.storage import Bucket, Client  # pyright: ignore[reportMissingTypeStubs]

from wenchang.storage.gcs import GcsStorage

pytestmark = pytest.mark.unit


def _real_client() -> Client:
    return Client(
        project="test",
        credentials=AnonymousCredentials(),
        client_options={"api_endpoint": "http://localhost:1"},
    )


def test_constructing_gcs_storage_initializes_the_client_session() -> None:
    """A client that has made no request has its HTTP session built by
    GcsStorage construction, on the constructing thread (AIE-1316).
    """
    client = _real_client()
    assert client._http_internal is None  # pyright: ignore[reportPrivateUsage, reportUnknownMemberType]

    GcsStorage(client.bucket("b"))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]

    assert client._http_internal is not None  # pyright: ignore[reportPrivateUsage]


def test_session_is_created_once_and_kept() -> None:
    """Construction creates the session exactly once, and later use sees the
    same session object (AIE-1316).
    """
    client = _real_client()

    GcsStorage(client.bucket("b"))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    session: Any = client._http_internal  # pyright: ignore[reportPrivateUsage, reportUnknownMemberType, reportUnknownVariableType]

    assert session is not None
    assert client._http is session  # pyright: ignore[reportPrivateUsage, reportUnknownMemberType]
    assert client._http_internal is session  # pyright: ignore[reportPrivateUsage, reportUnknownMemberType]


def test_bucket_without_client_is_accepted() -> None:
    """A Bucket whose client is None constructs without raising (AIE-1316)."""
    GcsStorage(Bucket(client=None, name="b"))  # pyright: ignore[reportArgumentType]
