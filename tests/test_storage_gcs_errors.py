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


def _make_storage(bucket: _StubBucket) -> Storage:
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
