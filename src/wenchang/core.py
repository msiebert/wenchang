"""Core memory operations over a Storage backend."""

from dataclasses import dataclass

from wenchang.errors import NotFoundError, NotFoundReason
from wenchang.file_format import FileMetadata, metadata_from_map
from wenchang.paths import is_valid_path
from wenchang.storage import Storage
from wenchang.version_token import VersionToken


@dataclass(frozen=True)
class MemoryFile:
    """A memory file's content, metadata, path, and version, as read from storage."""

    path: str
    content: str
    metadata: FileMetadata
    version: VersionToken


class MemoryStore:
    """Core memory operations over a Storage backend.

    The remaining operations (write, list, and so on) are added later.
    """

    def __init__(self, storage: Storage) -> None:
        self._storage = storage

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
