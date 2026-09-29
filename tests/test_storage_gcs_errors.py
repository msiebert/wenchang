"""Unit tests for GcsStorage error mapping and retry behavior (AIE-1032).

No network: exercises `src/wenchang/storage/gcs.py` against small
hand-written stub Bucket/Blob objects, cast to `Bucket` for the constructor.
"""

import ast
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import pytest
from google.api_core.exceptions import (
    BadGateway,
    DeadlineExceeded,
    Forbidden,
    GatewayTimeout,
    InternalServerError,
    NotFound,
    PreconditionFailed,
    ServiceUnavailable,
    TooManyRequests,
)
from google.cloud.storage import Bucket  # pyright: ignore[reportMissingTypeStubs]
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import ReadTimeout

from wenchang.errors import BackendUnavailableError, TransientReason
from wenchang.storage import PreconditionFailedError, Storage
from wenchang.storage.gcs import GcsStorage
from wenchang.version_token import VersionToken

pytestmark = pytest.mark.unit

TIMEOUT_EXCEPTIONS: list[Exception] = [
    DeadlineExceeded("timed out"),
    GatewayTimeout("gateway timeout"),
    ReadTimeout("read timeout"),
]

UNAVAILABLE_EXCEPTIONS: list[Exception] = [
    ServiceUnavailable("unavailable"),
    InternalServerError("internal error"),
    BadGateway("bad gateway"),
    TooManyRequests("too many requests"),
    RequestsConnectionError("connection error"),
]


class _StubBlob:
    """Minimal stand-in for google.cloud.storage.Blob."""

    def __init__(
        self,
        generation: int,
        data: bytes = b"",
        metadata: Mapping[str, str] | None = None,
        download_raises: list[BaseException] | None = None,
    ) -> None:
        self.generation = generation
        self._data = data
        self.metadata: dict[str, str] | None = dict(metadata) if metadata is not None else None
        self._download_raises = list(download_raises or [])
        self.download_calls: list[dict[str, Any]] = []
        self.uploaded_data: bytes | None = None
        self.uploaded_content_type: str | None = None

    def download_as_bytes(self, *, if_generation_match: int | None = None) -> bytes:
        self.download_calls.append({"if_generation_match": if_generation_match})
        if self._download_raises:
            raise self._download_raises.pop(0)
        return self._data

    def upload_from_string(
        self, data: bytes, *, content_type: str, if_generation_match: int | None = None
    ) -> None:
        self.uploaded_data = data
        self.uploaded_content_type = content_type
        self.upload_if_generation_match = if_generation_match


class _StubBucket:
    """Minimal stand-in for google.cloud.storage.Bucket."""

    def __init__(
        self,
        get_blob_sequence: list[_StubBlob | None] | None = None,
        get_blob_raises: BaseException | None = None,
        blob_for_put: _StubBlob | None = None,
    ) -> None:
        self._get_blob_sequence = list(get_blob_sequence or [])
        self._get_blob_raises = get_blob_raises
        self.get_blob_calls = 0
        self._blob_for_put = blob_for_put
        self.blob_calls: list[str] = []

    def get_blob(self, key: str) -> _StubBlob | None:
        self.get_blob_calls += 1
        if self._get_blob_raises is not None:
            raise self._get_blob_raises
        return self._get_blob_sequence.pop(0)

    def blob(self, key: str) -> _StubBlob:
        self.blob_calls.append(key)
        assert self._blob_for_put is not None
        return self._blob_for_put


def _make_storage(bucket: "_StubBucket | _StubBucketForList") -> Storage:
    """Build a GcsStorage over a stub bucket, typed as `Storage` so pyright
    treats every call site consistently with the protocol.
    """
    return GcsStorage(cast(Bucket, bucket))


@pytest.mark.parametrize("exc", TIMEOUT_EXCEPTIONS, ids=lambda e: type(e).__name__)
def test_get_blob_timeout_exceptions_map_to_backend_unavailable_timeout(
    exc: Exception,
) -> None:
    """Each timeout-class exception raised from get_blob() maps to
    BackendUnavailableError with reason TIMEOUT (AIE-1032, US3-2, FR-004).
    """
    bucket = _StubBucket(get_blob_raises=exc)
    storage = _make_storage(bucket)
    with pytest.raises(BackendUnavailableError) as excinfo:
        storage.get("k")
    assert excinfo.value.reason is TransientReason.TIMEOUT


@pytest.mark.parametrize("exc", UNAVAILABLE_EXCEPTIONS, ids=lambda e: type(e).__name__)
def test_get_blob_unavailable_exceptions_map_to_backend_unavailable_unavailable(
    exc: Exception,
) -> None:
    """Each unavailable-class exception raised from get_blob() maps to
    BackendUnavailableError with reason UNAVAILABLE (AIE-1032, US3-2, FR-004).
    """
    bucket = _StubBucket(get_blob_raises=exc)
    storage = _make_storage(bucket)
    with pytest.raises(BackendUnavailableError) as excinfo:
        storage.get("k")
    assert excinfo.value.reason is TransientReason.UNAVAILABLE


@pytest.mark.parametrize("exc", TIMEOUT_EXCEPTIONS, ids=lambda e: type(e).__name__)
def test_download_as_bytes_timeout_exceptions_map_to_backend_unavailable_timeout(
    exc: Exception,
) -> None:
    """Each timeout-class exception raised from download_as_bytes() maps to
    BackendUnavailableError with reason TIMEOUT (AIE-1032, US3-2, FR-004).
    """
    blob = _StubBlob(generation=1, download_raises=[exc])
    bucket = _StubBucket(get_blob_sequence=[blob])
    storage = _make_storage(bucket)
    with pytest.raises(BackendUnavailableError) as excinfo:
        storage.get("k")
    assert excinfo.value.reason is TransientReason.TIMEOUT


@pytest.mark.parametrize("exc", UNAVAILABLE_EXCEPTIONS, ids=lambda e: type(e).__name__)
def test_download_as_bytes_unavailable_exceptions_map_to_backend_unavailable_unavailable(
    exc: Exception,
) -> None:
    """Each unavailable-class exception raised from download_as_bytes() maps
    to BackendUnavailableError with reason UNAVAILABLE (AIE-1032, US3-2, FR-004).
    """
    blob = _StubBlob(generation=1, download_raises=[exc])
    bucket = _StubBucket(get_blob_sequence=[blob])
    storage = _make_storage(bucket)
    with pytest.raises(BackendUnavailableError) as excinfo:
        storage.get("k")
    assert excinfo.value.reason is TransientReason.UNAVAILABLE


class _RaisingOnUploadBlob(_StubBlob):
    def __init__(self, generation: int, upload_raises: BaseException) -> None:
        super().__init__(generation=generation)
        self._upload_raises = upload_raises

    def upload_from_string(
        self, data: bytes, *, content_type: str, if_generation_match: int | None = None
    ) -> None:
        raise self._upload_raises


@pytest.mark.parametrize("exc", TIMEOUT_EXCEPTIONS, ids=lambda e: type(e).__name__)
def test_upload_from_string_timeout_exceptions_map_to_backend_unavailable_timeout(
    exc: Exception,
) -> None:
    """Each timeout-class exception raised from upload_from_string() maps to
    BackendUnavailableError with reason TIMEOUT (AIE-1032, US3-2, FR-004).
    """
    blob = _RaisingOnUploadBlob(generation=1, upload_raises=exc)
    bucket = _StubBucket(blob_for_put=blob)
    storage = _make_storage(bucket)
    with pytest.raises(BackendUnavailableError) as excinfo:
        storage.put("k", b"data", {})
    assert excinfo.value.reason is TransientReason.TIMEOUT


@pytest.mark.parametrize("exc", UNAVAILABLE_EXCEPTIONS, ids=lambda e: type(e).__name__)
def test_upload_from_string_unavailable_exceptions_map_to_backend_unavailable_unavailable(
    exc: Exception,
) -> None:
    """Each unavailable-class exception raised from upload_from_string() maps
    to BackendUnavailableError with reason UNAVAILABLE (AIE-1032, US3-2, FR-004).
    """
    blob = _RaisingOnUploadBlob(generation=1, upload_raises=exc)
    bucket = _StubBucket(blob_for_put=blob)
    storage = _make_storage(bucket)
    with pytest.raises(BackendUnavailableError) as excinfo:
        storage.put("k", b"data", {})
    assert excinfo.value.reason is TransientReason.UNAVAILABLE


def test_unmapped_exception_from_get_blob_propagates_unchanged() -> None:
    """An exception not in the mapping (Forbidden) raised from get_blob()
    propagates unchanged, not wrapped (AIE-1032, US3-2, FR-004).
    """
    bucket = _StubBucket(get_blob_raises=Forbidden("forbidden"))
    storage = _make_storage(bucket)
    with pytest.raises(Forbidden):
        storage.get("k")


def test_unmapped_value_error_from_upload_propagates_unchanged() -> None:
    """A plain ValueError raised from upload_from_string() propagates
    unchanged, not wrapped (AIE-1032, US3-2, FR-004).
    """
    blob = _RaisingOnUploadBlob(generation=1, upload_raises=ValueError("bad value"))
    bucket = _StubBucket(blob_for_put=blob)
    storage = _make_storage(bucket)
    with pytest.raises(ValueError, match="bad value"):
        storage.put("k", b"data", {})


def test_get_retries_once_on_precondition_failed_and_returns_second_generation() -> None:
    """If download_as_bytes raises PreconditionFailed once, get() re-fetches
    via get_blob and returns the second blob's data/metadata/version
    (AIE-1032, US3-2).
    """
    stale_blob = _StubBlob(
        generation=1, data=b"stale", download_raises=[PreconditionFailed("stale generation")]
    )
    fresh_blob = _StubBlob(generation=2, data=b"fresh", metadata={"a": "1"})
    bucket = _StubBucket(get_blob_sequence=[stale_blob, fresh_blob])
    storage = _make_storage(bucket)

    result = storage.get("k")

    assert result is not None
    assert result.data == b"fresh"
    assert dict(result.metadata) == {"a": "1"}
    assert result.version == "2"
    assert bucket.get_blob_calls == 2


def test_get_returns_none_when_retry_after_not_found_finds_nothing() -> None:
    """If download_as_bytes raises NotFound and the re-fetch get_blob returns
    None, get() returns None (AIE-1032, US3-2).
    """
    blob = _StubBlob(generation=1, download_raises=[NotFound("gone")])
    bucket = _StubBucket(get_blob_sequence=[blob, None])
    storage = _make_storage(bucket)

    result = storage.get("k")

    assert result is None
    assert bucket.get_blob_calls == 2


def test_get_raises_backend_unavailable_after_three_precondition_failures() -> None:
    """If download_as_bytes raises PreconditionFailed on all 3 attempts,
    get() raises BackendUnavailableError(UNAVAILABLE) and get_blob is called
    at most 3 times (AIE-1032, US3-2).
    """
    blobs = [
        _StubBlob(generation=i, download_raises=[PreconditionFailed(f"stale {i}")])
        for i in range(1, 4)
    ]
    bucket = _StubBucket(get_blob_sequence=list(blobs))
    storage = _make_storage(bucket)

    with pytest.raises(BackendUnavailableError) as excinfo:
        storage.get("k")

    assert excinfo.value.reason is TransientReason.UNAVAILABLE
    assert bucket.get_blob_calls <= 3


def test_get_passes_matching_generation_to_download_as_bytes() -> None:
    """get() passes if_generation_match equal to the fetched blob's
    generation into download_as_bytes (AIE-1032, US3-2).
    """
    blob = _StubBlob(generation=42, data=b"data")
    bucket = _StubBucket(get_blob_sequence=[blob])
    storage = _make_storage(bucket)

    storage.get("k")

    assert blob.download_calls == [{"if_generation_match": 42}]


def test_put_sets_metadata_copy_content_type_and_returns_generation_token() -> None:
    """put() sets blob.metadata as a plain dict copy of the caller's mapping,
    uploads with content_type "text/markdown; charset=utf-8", and returns
    VersionToken(str(blob.generation)) (AIE-1032, US3-2).
    """
    blob = _StubBlob(generation=7)
    bucket = _StubBucket(blob_for_put=blob)
    storage = _make_storage(bucket)

    metadata = {"lang": "en"}
    token = storage.put("k", b"payload", metadata)

    assert token == "7"
    assert blob.metadata == {"lang": "en"}
    assert blob.metadata is not metadata
    assert blob.uploaded_data == b"payload"
    assert blob.uploaded_content_type == "text/markdown; charset=utf-8"


class _StubBlobForPutIfVersion(_StubBlob):
    """Stub blob whose upload_from_string records if_generation_match."""

    def __init__(
        self,
        generation: int,
        upload_raises: BaseException | None = None,
    ) -> None:
        super().__init__(generation=generation)
        self._upload_raises = upload_raises
        self.upload_if_generation_match: int | None = None

    def upload_from_string(
        self, data: bytes, *, content_type: str, if_generation_match: int | None = None
    ) -> None:
        self.upload_if_generation_match = if_generation_match
        if self._upload_raises is not None:
            raise self._upload_raises
        self.uploaded_data = data
        self.uploaded_content_type = content_type


def test_put_if_version_none_uploads_with_generation_zero_and_returns_token() -> None:
    """put_if_version(expected=None) sets blob.metadata, uploads with
    if_generation_match=0, and returns VersionToken(str(blob.generation))
    (AIE-1033).
    """
    blob = _StubBlobForPutIfVersion(generation=1)
    bucket = _StubBucket(blob_for_put=blob)
    storage = _make_storage(bucket)

    metadata = {"lang": "en"}
    token = storage.put_if_version("k", b"payload", metadata, None)

    assert blob.metadata == {"lang": "en"}
    assert blob.upload_if_generation_match == 0
    assert blob.uploaded_data == b"payload"
    assert blob.uploaded_content_type == "text/markdown; charset=utf-8"
    assert token == "1"


def test_put_if_version_with_token_uploads_with_matching_generation() -> None:
    """put_if_version(expected=VersionToken("42")) uploads with
    if_generation_match=42 (AIE-1033).
    """
    blob = _StubBlobForPutIfVersion(generation=43)
    bucket = _StubBucket(blob_for_put=blob)
    storage = _make_storage(bucket)

    storage.put_if_version("k", b"payload", {}, VersionToken("42"))

    assert blob.upload_if_generation_match == 42


@pytest.mark.parametrize(
    "bogus_token", ["", "abc", "0", "-1", "007", "4.2", " 42", "42\n", "42\r\n"]
)
def test_put_if_version_with_non_canonical_token_raises_without_upload(
    bogus_token: str,
) -> None:
    """A non-canonical expected token (not matching ^[1-9][0-9]*$ as a whole
    string, including trailing-newline variants which `re.match` with a bare
    `$` would wrongly accept) raises PreconditionFailedError(key) without
    calling bucket.blob or uploading (AIE-1033).
    """
    bucket = _StubBucket()
    storage = _make_storage(bucket)

    with pytest.raises(PreconditionFailedError) as excinfo:
        storage.put_if_version("k", b"payload", {}, VersionToken(bogus_token))

    assert excinfo.value.key == "k"
    assert bucket.blob_calls == []


def test_put_if_version_upload_precondition_failed_raises_precondition_failed_error() -> None:
    """PreconditionFailed raised from upload_from_string() maps to
    PreconditionFailedError(key) (AIE-1033).
    """
    blob = _StubBlobForPutIfVersion(
        generation=1, upload_raises=PreconditionFailed("generation mismatch")
    )
    bucket = _StubBucket(blob_for_put=blob)
    storage = _make_storage(bucket)

    with pytest.raises(PreconditionFailedError) as excinfo:
        storage.put_if_version("k", b"payload", {}, None)

    assert excinfo.value.key == "k"


@pytest.mark.parametrize("exc", TIMEOUT_EXCEPTIONS, ids=lambda e: type(e).__name__)
def test_put_if_version_upload_timeout_exceptions_map_to_backend_unavailable_timeout(
    exc: Exception,
) -> None:
    """Each timeout-class exception raised from upload_from_string() during
    put_if_version() maps to BackendUnavailableError with reason TIMEOUT
    (AIE-1033).
    """
    blob = _StubBlobForPutIfVersion(generation=1, upload_raises=exc)
    bucket = _StubBucket(blob_for_put=blob)
    storage = _make_storage(bucket)

    with pytest.raises(BackendUnavailableError) as excinfo:
        storage.put_if_version("k", b"payload", {}, None)

    assert excinfo.value.reason is TransientReason.TIMEOUT


@pytest.mark.parametrize("exc", UNAVAILABLE_EXCEPTIONS, ids=lambda e: type(e).__name__)
def test_put_if_version_upload_unavailable_exceptions_map_to_backend_unavailable_unavailable(
    exc: Exception,
) -> None:
    """Each unavailable-class exception raised from upload_from_string()
    during put_if_version() maps to BackendUnavailableError with reason
    UNAVAILABLE (AIE-1033).
    """
    blob = _StubBlobForPutIfVersion(generation=1, upload_raises=exc)
    bucket = _StubBucket(blob_for_put=blob)
    storage = _make_storage(bucket)

    with pytest.raises(BackendUnavailableError) as excinfo:
        storage.put_if_version("k", b"payload", {}, None)

    assert excinfo.value.reason is TransientReason.UNAVAILABLE


def test_put_if_version_unmapped_exception_from_upload_propagates_unchanged() -> None:
    """An exception not in the mapping (Forbidden) raised from
    upload_from_string() during put_if_version() propagates unchanged, not
    wrapped (AIE-1033).
    """
    blob = _StubBlobForPutIfVersion(generation=1, upload_raises=Forbidden("forbidden"))
    bucket = _StubBucket(blob_for_put=blob)
    storage = _make_storage(bucket)

    with pytest.raises(Forbidden):
        storage.put_if_version("k", b"payload", {}, None)


class _StubBlobForDeleteIfVersion(_StubBlob):
    """Stub blob whose delete() records if_generation_match."""

    def __init__(
        self,
        generation: int,
        delete_raises: BaseException | None = None,
    ) -> None:
        super().__init__(generation=generation)
        self._delete_raises = delete_raises
        self.delete_if_generation_match: int | None = None
        self.delete_calls = 0

    def delete(self, *, if_generation_match: int | None = None) -> None:
        self.delete_calls += 1
        self.delete_if_generation_match = if_generation_match
        if self._delete_raises is not None:
            raise self._delete_raises


class _StubBucketForDeleteIfVersion(_StubBucket):
    """Stub Bucket for delete_if_version: `blob()` always returns the same
    stub blob, recording the key it was requested for.
    """

    def __init__(self, blob_for_delete: _StubBlobForDeleteIfVersion) -> None:
        super().__init__(blob_for_put=blob_for_delete)


def test_delete_if_version_deletes_with_matching_generation() -> None:
    """delete_if_version(key, VersionToken("42")) calls bucket.blob(key)
    then blob.delete(if_generation_match=42) (AIE-1037, US4.1/US4.6).
    """
    blob = _StubBlobForDeleteIfVersion(generation=42)
    bucket = _StubBucketForDeleteIfVersion(blob)
    storage = _make_storage(bucket)

    storage.delete_if_version("k", VersionToken("42"))

    assert bucket.blob_calls == ["k"]
    assert blob.delete_if_generation_match == 42
    assert blob.delete_calls == 1


@pytest.mark.parametrize(
    "bogus_token", ["", "abc", "0", "-1", "007", "4.2", " 42", "42\n", "42\r\n"]
)
def test_delete_if_version_with_non_canonical_token_raises_without_client_call(
    bogus_token: str,
) -> None:
    """A non-canonical expected token (not matching ^[1-9][0-9]*$ as a whole
    string) raises PreconditionFailedError(key) without calling bucket.blob
    or blob.delete (AIE-1037, US4.6).
    """
    blob = _StubBlobForDeleteIfVersion(generation=1)
    bucket = _StubBucketForDeleteIfVersion(blob)
    storage = _make_storage(bucket)

    with pytest.raises(PreconditionFailedError) as excinfo:
        storage.delete_if_version("k", VersionToken(bogus_token))

    assert excinfo.value.key == "k"
    assert bucket.blob_calls == []
    assert blob.delete_calls == 0


def test_delete_if_version_precondition_failed_raises_precondition_failed_error() -> None:
    """PreconditionFailed raised from blob.delete() maps to
    PreconditionFailedError(key) (AIE-1037, US4.2/US4.3).
    """
    blob = _StubBlobForDeleteIfVersion(
        generation=1, delete_raises=PreconditionFailed("generation mismatch")
    )
    bucket = _StubBucketForDeleteIfVersion(blob)
    storage = _make_storage(bucket)

    with pytest.raises(PreconditionFailedError) as excinfo:
        storage.delete_if_version("k", VersionToken("1"))

    assert excinfo.value.key == "k"


def test_delete_if_version_not_found_raises_precondition_failed_error() -> None:
    """NotFound raised from blob.delete() (the object is absent) maps to
    PreconditionFailedError(key) (AIE-1037, US4.3).
    """
    blob = _StubBlobForDeleteIfVersion(generation=1, delete_raises=NotFound("gone"))
    bucket = _StubBucketForDeleteIfVersion(blob)
    storage = _make_storage(bucket)

    with pytest.raises(PreconditionFailedError) as excinfo:
        storage.delete_if_version("k", VersionToken("1"))

    assert excinfo.value.key == "k"


@pytest.mark.parametrize("exc", TIMEOUT_EXCEPTIONS, ids=lambda e: type(e).__name__)
def test_delete_if_version_timeout_exceptions_map_to_backend_unavailable_timeout(
    exc: Exception,
) -> None:
    """Each timeout-class exception raised from blob.delete() during
    delete_if_version() maps to BackendUnavailableError with reason TIMEOUT
    (AIE-1037, US4.6).
    """
    blob = _StubBlobForDeleteIfVersion(generation=1, delete_raises=exc)
    bucket = _StubBucketForDeleteIfVersion(blob)
    storage = _make_storage(bucket)

    with pytest.raises(BackendUnavailableError) as excinfo:
        storage.delete_if_version("k", VersionToken("1"))

    assert excinfo.value.reason is TransientReason.TIMEOUT


@pytest.mark.parametrize("exc", UNAVAILABLE_EXCEPTIONS, ids=lambda e: type(e).__name__)
def test_delete_if_version_unavailable_exceptions_map_to_backend_unavailable_unavailable(
    exc: Exception,
) -> None:
    """Each unavailable-class exception raised from blob.delete() during
    delete_if_version() maps to BackendUnavailableError with reason
    UNAVAILABLE (AIE-1037, US4.6).
    """
    blob = _StubBlobForDeleteIfVersion(generation=1, delete_raises=exc)
    bucket = _StubBucketForDeleteIfVersion(blob)
    storage = _make_storage(bucket)

    with pytest.raises(BackendUnavailableError) as excinfo:
        storage.delete_if_version("k", VersionToken("1"))

    assert excinfo.value.reason is TransientReason.UNAVAILABLE


def test_delete_if_version_unmapped_exception_propagates_unchanged() -> None:
    """An exception not in the mapping (Forbidden) raised from blob.delete()
    during delete_if_version() propagates unchanged, not wrapped (AIE-1037,
    US4.6).
    """
    blob = _StubBlobForDeleteIfVersion(generation=1, delete_raises=Forbidden("forbidden"))
    bucket = _StubBucketForDeleteIfVersion(blob)
    storage = _make_storage(bucket)

    with pytest.raises(Forbidden):
        storage.delete_if_version("k", VersionToken("1"))


class _StubListBlob:
    """Minimal stand-in for a google.cloud.storage.Blob as returned by list_blobs.

    Records whether any download method is called, so tests can assert
    list_page() never reads object bodies (AIE-1035).
    """

    def __init__(
        self,
        name: str,
        generation: int,
        metadata: Mapping[str, str] | None = None,
    ) -> None:
        self.name = name
        self.generation = generation
        self.metadata: dict[str, str] | None = dict(metadata) if metadata is not None else None
        self.download_called = False

    def download_as_bytes(self, *, if_generation_match: int | None = None) -> bytes:
        self.download_called = True
        raise AssertionError("list_page must never download object bodies")


class _StubBucketForList:
    """Minimal stand-in for google.cloud.storage.Bucket, for list_blobs only."""

    def __init__(
        self,
        blobs: list[_StubListBlob] | None = None,
        list_blobs_raises: BaseException | None = None,
        raises_mid_iteration: BaseException | None = None,
    ) -> None:
        self._blobs = list(blobs or [])
        self._list_blobs_raises = list_blobs_raises
        self._raises_mid_iteration = raises_mid_iteration
        self.list_blobs_calls: list[dict[str, Any]] = []

    def list_blobs(
        self,
        *,
        prefix: str,
        max_results: int,
        start_offset: str | None = None,
    ) -> Any:
        call: dict[str, Any] = {"prefix": prefix, "max_results": max_results}
        if start_offset is not None:
            call["start_offset"] = start_offset
        self.list_blobs_calls.append(call)
        if self._list_blobs_raises is not None:
            raise self._list_blobs_raises

        def _iterator() -> Any:
            for blob in self._blobs:
                if self._raises_mid_iteration is not None and blob is self._blobs[-1]:
                    raise self._raises_mid_iteration
                yield blob

        return _iterator()


@pytest.mark.parametrize("exc", TIMEOUT_EXCEPTIONS, ids=lambda e: type(e).__name__)
def test_list_blobs_timeout_exceptions_map_to_backend_unavailable_timeout(
    exc: Exception,
) -> None:
    """Each timeout-class exception raised from list_blobs() itself maps to
    BackendUnavailableError with reason TIMEOUT (AIE-1035).
    """
    bucket = _StubBucketForList(list_blobs_raises=exc)
    storage = _make_storage(bucket)
    with pytest.raises(BackendUnavailableError) as excinfo:
        storage.list_page("prefix/", None, 10)
    assert excinfo.value.reason is TransientReason.TIMEOUT


@pytest.mark.parametrize("exc", UNAVAILABLE_EXCEPTIONS, ids=lambda e: type(e).__name__)
def test_list_blobs_unavailable_exceptions_map_to_backend_unavailable_unavailable(
    exc: Exception,
) -> None:
    """Each unavailable-class exception raised from list_blobs() itself maps
    to BackendUnavailableError with reason UNAVAILABLE (AIE-1035).
    """
    bucket = _StubBucketForList(list_blobs_raises=exc)
    storage = _make_storage(bucket)
    with pytest.raises(BackendUnavailableError) as excinfo:
        storage.list_page("prefix/", None, 10)
    assert excinfo.value.reason is TransientReason.UNAVAILABLE


def test_list_blobs_unmapped_exception_propagates_unchanged() -> None:
    """An exception not in the mapping (Forbidden) raised from list_blobs()
    propagates unchanged, not wrapped (AIE-1035).
    """
    bucket = _StubBucketForList(list_blobs_raises=Forbidden("forbidden"))
    storage = _make_storage(bucket)
    with pytest.raises(Forbidden):
        storage.list_page("prefix/", None, 10)


@pytest.mark.parametrize("exc", TIMEOUT_EXCEPTIONS, ids=lambda e: type(e).__name__)
def test_list_blobs_mid_iteration_timeout_exceptions_map_to_backend_unavailable_timeout(
    exc: Exception,
) -> None:
    """Each timeout-class exception raised while iterating the list_blobs()
    result maps to BackendUnavailableError with reason TIMEOUT (AIE-1035).
    """
    blobs = [_StubListBlob("prefix/a", 1), _StubListBlob("prefix/b", 2)]
    bucket = _StubBucketForList(blobs=blobs, raises_mid_iteration=exc)
    storage = _make_storage(bucket)
    with pytest.raises(BackendUnavailableError) as excinfo:
        storage.list_page("prefix/", None, 10)
    assert excinfo.value.reason is TransientReason.TIMEOUT


@pytest.mark.parametrize("exc", UNAVAILABLE_EXCEPTIONS, ids=lambda e: type(e).__name__)
def test_list_blobs_mid_iteration_unavailable_exceptions_map_to_backend_unavailable_unavailable(
    exc: Exception,
) -> None:
    """Each unavailable-class exception raised while iterating the
    list_blobs() result maps to BackendUnavailableError with reason
    UNAVAILABLE (AIE-1035).
    """
    blobs = [_StubListBlob("prefix/a", 1), _StubListBlob("prefix/b", 2)]
    bucket = _StubBucketForList(blobs=blobs, raises_mid_iteration=exc)
    storage = _make_storage(bucket)
    with pytest.raises(BackendUnavailableError) as excinfo:
        storage.list_page("prefix/", None, 10)
    assert excinfo.value.reason is TransientReason.UNAVAILABLE


def test_list_blobs_mid_iteration_unmapped_exception_propagates_unchanged() -> None:
    """An unmapped exception (Forbidden) raised while iterating the
    list_blobs() result propagates unchanged, not wrapped (AIE-1035).
    """
    blobs = [_StubListBlob("prefix/a", 1), _StubListBlob("prefix/b", 2)]
    bucket = _StubBucketForList(blobs=blobs, raises_mid_iteration=Forbidden("forbidden"))
    storage = _make_storage(bucket)
    with pytest.raises(Forbidden):
        storage.list_page("prefix/", None, 10)


def test_list_page_omits_start_offset_when_start_after_is_none() -> None:
    """list_page(start_after=None) calls list_blobs without a start_offset
    argument, with max_results == limit + 1 (AIE-1035).
    """
    bucket = _StubBucketForList(blobs=[])
    storage = _make_storage(bucket)

    storage.list_page("prefix/", None, 5)

    assert bucket.list_blobs_calls == [{"prefix": "prefix/", "max_results": 6}]


def test_list_page_passes_start_offset_when_start_after_given() -> None:
    """list_page(start_after="k") calls list_blobs with start_offset="k" and
    max_results == limit + 1 (AIE-1035).
    """
    bucket = _StubBucketForList(blobs=[])
    storage = _make_storage(bucket)

    storage.list_page("prefix/", "prefix/k", 5)

    assert bucket.list_blobs_calls == [
        {"prefix": "prefix/", "max_results": 6, "start_offset": "prefix/k"}
    ]


def test_list_page_drops_blob_equal_to_start_after_and_truncates_to_limit() -> None:
    """A returned blob whose name equals start_after (inclusive start_offset
    semantics) is dropped, and the remaining results are truncated to limit
    even though max_results was limit + 1 (AIE-1035).
    """
    blobs = [
        _StubListBlob("prefix/a", 1),
        _StubListBlob("prefix/b", 2),
        _StubListBlob("prefix/c", 3),
        _StubListBlob("prefix/d", 4),
    ]
    bucket = _StubBucketForList(blobs=blobs)
    storage = _make_storage(bucket)

    result = storage.list_page("prefix/", "prefix/a", 2)

    assert [obj.key for obj in result] == ["prefix/b", "prefix/c"]


def test_list_page_never_calls_download() -> None:
    """list_page() never calls download_as_bytes on any returned blob
    (AIE-1035).
    """
    blobs = [_StubListBlob("prefix/a", 1, metadata={"lang": "en"})]
    bucket = _StubBucketForList(blobs=blobs)
    storage = _make_storage(bucket)

    result = storage.list_page("prefix/", None, 10)

    assert len(result) == 1
    assert result[0].key == "prefix/a"
    assert dict(result[0].metadata) == {"lang": "en"}
    assert result[0].version == "1"
    assert blobs[0].download_called is False


def test_no_module_outside_storage_gcs_imports_google_cloud() -> None:
    """No module under src/wenchang other than storage/gcs.py imports
    google.cloud (or any `google` submodule), keeping the GCS SDK isolated
    behind the storage boundary (AIE-1032, FR-008).
    """
    src_root = Path(__file__).parent.parent / "src" / "wenchang"
    gcs_module = src_root / "storage" / "gcs.py"
    offenders: list[str] = []

    for path in src_root.rglob("*.py"):
        if path == gcs_module:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "google" or alias.name.startswith("google."):
                        offenders.append(f"{path}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                module_is_google = node.module == "google" or node.module.startswith("google.")
                if module_is_google:
                    offenders.append(f"{path}: from {node.module} import ...")

    assert offenders == []
