"""Core memory operations over a Storage backend."""

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from wenchang.errors import (
    NotFoundError,
    NotFoundReason,
    OversizeWriteError,
    VersionConflictError,
)
from wenchang.file_format import FileMetadata, metadata_from_map, metadata_to_map
from wenchang.paths import is_valid_path
from wenchang.storage import PreconditionFailedError, Storage
from wenchang.version_token import VersionToken

DEFAULT_MAX_FILE_BYTES: int = 16 * 1024


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class MemoryFile:
    """A memory file's content, metadata, path, and version, as read from storage."""

    path: str
    content: str
    metadata: FileMetadata
    version: VersionToken


class MemoryStore:
    """Core memory operations over a Storage backend.

    Currently exposes read_file and write_file; list and other operations
    are added separately.
    """

    def __init__(
        self,
        storage: Storage,
        *,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if max_file_bytes <= 0:
            raise ValueError("max_file_bytes must be positive")
        self._storage = storage
        self._max_file_bytes = max_file_bytes
        self._clock = clock

    def read_file(self, path: str) -> MemoryFile:
        """Read the memory file at `path`.

        Raises NotFoundError with reason INVALID_PATH if `path` is not
        well-formed, without calling storage. Raises NotFoundError with
        reason FILE_ABSENT if no object exists at `path`. Propagates
        MetadataFormatError, UnicodeDecodeError, and BackendUnavailableError
        unchanged.
        """
        if not is_valid_path(path):
            raise NotFoundError(path, NotFoundReason.INVALID_PATH)

        obj = self._storage.get(path)
        if obj is None:
            raise NotFoundError(path, NotFoundReason.FILE_ABSENT)

        content = obj.data.decode("utf-8")
        metadata = metadata_from_map(obj.metadata)
        return MemoryFile(path=path, content=content, metadata=metadata, version=obj.version)

    def write_file(
        self,
        path: str,
        content: str,
        metadata: FileMetadata,
        expected_version: VersionToken | None,
    ) -> MemoryFile:
        """Write the memory file at `path`, creating or replacing it.

        Raises NotFoundError with reason INVALID_PATH if `path` is not
        well-formed, without calling storage. Raises OversizeWriteError if
        the UTF-8 encoding of `content` exceeds `max_file_bytes`, without
        calling storage. Stamps `metadata.last_updated` with the store's
        clock, raising ValueError (from FileMetadata's own validation) if
        the clock returns a naive datetime, without calling storage.
        `expected_version=None` requires the file to not already exist; a
        non-None value requires it to match the current version exactly.
        On a version mismatch raises VersionConflictError carrying the
        current content and version, or NotFoundError with reason
        FILE_ABSENT if the file does not exist. Propagates
        MetadataFormatError, UnicodeDecodeError, and BackendUnavailableError
        unchanged.
        """
        if not is_valid_path(path):
            raise NotFoundError(path, NotFoundReason.INVALID_PATH)

        data = content.encode("utf-8")
        if len(data) > self._max_file_bytes:
            raise OversizeWriteError(path, len(data), self._max_file_bytes)

        stamped = dataclasses.replace(metadata, last_updated=self._clock())

        try:
            version = self._storage.put_if_version(
                path, data, metadata_to_map(stamped), expected_version
            )
        except PreconditionFailedError:
            obj = self._storage.get(path)
            if obj is None:
                raise NotFoundError(path, NotFoundReason.FILE_ABSENT) from None
            current_content = obj.data.decode("utf-8")
            metadata_from_map(obj.metadata)
            raise VersionConflictError(path, current_content, obj.version) from None

        return MemoryFile(path=path, content=content, metadata=stamped, version=version)
