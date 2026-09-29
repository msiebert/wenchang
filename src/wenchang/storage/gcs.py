"""GCS-backed implementation of the Storage protocol.

The only module under `src/wenchang` that imports `google.cloud`,
`google.api_core`, or `requests`; every other module reaches storage only
through the `Storage` protocol.
"""

import re
from collections.abc import Mapping, Sequence

import requests.exceptions
from google.api_core.exceptions import (
    BadGateway,
    DeadlineExceeded,
    GatewayTimeout,
    InternalServerError,
    NotFound,
    PreconditionFailed,
    ServiceUnavailable,
    TooManyRequests,
)
from google.cloud.storage import Bucket  # pyright: ignore[reportMissingTypeStubs]

from wenchang.errors import BackendUnavailableError, TransientReason
from wenchang.storage import ListedObject, PreconditionFailedError, StoredObject
from wenchang.version_token import VersionToken

_GET_RETRY_ATTEMPTS = 3
_CONTENT_TYPE = "text/markdown; charset=utf-8"
_GENERATION_TOKEN_RE = re.compile(r"[1-9][0-9]*")


def _map_backend_error(exc: Exception) -> BackendUnavailableError | None:
    """Map a client-call exception to BackendUnavailableError, or None if unmapped.

    Timeout classes are checked before connection classes because
    `requests.exceptions.ConnectTimeout` subclasses both `Timeout` and
    `ConnectionError`.
    """
    if isinstance(exc, (DeadlineExceeded, GatewayTimeout, requests.exceptions.Timeout)):
        return BackendUnavailableError(TransientReason.TIMEOUT, str(exc))
    if isinstance(
        exc,
        (
            ServiceUnavailable,
            InternalServerError,
            BadGateway,
            TooManyRequests,
            requests.exceptions.ConnectionError,
        ),
    ):
        return BackendUnavailableError(TransientReason.UNAVAILABLE, str(exc))
    return None


class GcsStorage:
    """Structurally satisfies Storage, backed by a single GCS bucket."""

    def __init__(self, bucket: Bucket) -> None:
        self._bucket = bucket

    def get(self, key: str) -> StoredObject | None:
        for _ in range(_GET_RETRY_ATTEMPTS):
            try:
                blob = self._bucket.get_blob(key)  # pyright: ignore[reportUnknownMemberType]
            except Exception as exc:
                mapped = _map_backend_error(exc)
                if mapped is None:
                    raise
                raise mapped from exc
            if blob is None:
                return None
            try:
                data = blob.download_as_bytes(  # pyright: ignore[reportUnknownMemberType]
                    if_generation_match=blob.generation  # pyright: ignore[reportUnknownMemberType]
                )
            except (PreconditionFailed, NotFound):
                continue
            except Exception as exc:
                mapped = _map_backend_error(exc)
                if mapped is None:
                    raise
                raise mapped from exc
            blob_metadata: dict[str, str] = dict(
                blob.metadata or {}  # pyright: ignore[reportUnknownArgumentType, reportUnknownMemberType]
            )
            return StoredObject(
                data=data,
                metadata=blob_metadata,
                version=VersionToken(str(blob.generation)),  # pyright: ignore[reportUnknownMemberType]
            )
        raise BackendUnavailableError(
            TransientReason.UNAVAILABLE, f"Repeated generation conflicts fetching {key!r}."
        )

    def put(self, key: str, data: bytes, metadata: Mapping[str, str]) -> VersionToken:
        blob = self._bucket.blob(key)  # pyright: ignore[reportUnknownMemberType]
        blob.metadata = dict(metadata)
        try:
            blob.upload_from_string(  # pyright: ignore[reportUnknownMemberType]
                data, content_type=_CONTENT_TYPE
            )
        except Exception as exc:
            mapped = _map_backend_error(exc)
            if mapped is None:
                raise
            raise mapped from exc
        return VersionToken(str(blob.generation))  # pyright: ignore[reportUnknownMemberType]

    def put_if_version(
        self,
        key: str,
        data: bytes,
        metadata: Mapping[str, str],
        expected: VersionToken | None,
    ) -> VersionToken:
        if expected is None:
            generation = 0
        else:
            if not _GENERATION_TOKEN_RE.fullmatch(expected):
                raise PreconditionFailedError(key)
            generation = int(expected)
        blob = self._bucket.blob(key)  # pyright: ignore[reportUnknownMemberType]
        blob.metadata = dict(metadata)
        try:
            blob.upload_from_string(  # pyright: ignore[reportUnknownMemberType]
                data, content_type=_CONTENT_TYPE, if_generation_match=generation
            )
        except PreconditionFailed as exc:
            raise PreconditionFailedError(key) from exc
        except Exception as exc:
            mapped = _map_backend_error(exc)
            if mapped is None:
                raise
            raise mapped from exc
        return VersionToken(str(blob.generation))  # pyright: ignore[reportUnknownMemberType]

    def list_page(self, prefix: str, start_after: str | None, limit: int) -> Sequence[ListedObject]:
        try:
            if start_after is None:
                blob_iter = self._bucket.list_blobs(prefix=prefix, max_results=limit + 1)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            else:
                blob_iter = self._bucket.list_blobs(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
                    prefix=prefix, start_offset=start_after, max_results=limit + 1
                )
            blobs = list(blob_iter)  # pyright: ignore[reportUnknownArgumentType, reportUnknownVariableType]
        except Exception as exc:
            mapped = _map_backend_error(exc)
            if mapped is None:
                raise
            raise mapped from exc
        results: list[ListedObject] = []
        for blob in blobs:  # pyright: ignore[reportUnknownVariableType]
            name: str = blob.name  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType, reportUnknownVariableType]
            if start_after is not None and name == start_after:
                continue
            results.append(
                ListedObject(
                    key=name,  # pyright: ignore[reportUnknownArgumentType]
                    metadata=dict(
                        blob.metadata or {}  # pyright: ignore[reportUnknownArgumentType, reportUnknownMemberType]
                    ),
                    version=VersionToken(str(blob.generation)),  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                )
            )
        return results[:limit]
