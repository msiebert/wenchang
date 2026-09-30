"""Core memory operations over a Storage backend."""

import base64
import binascii
import dataclasses
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import NewType

from wenchang.errors import (
    NotFoundError,
    NotFoundReason,
    OversizeWriteError,
    ReplaceFactMatchError,
    VersionConflictError,
)
from wenchang.file_format import FileMetadata, metadata_from_map, metadata_to_map, parse_fact
from wenchang.paths import is_valid_path, is_valid_prefix
from wenchang.storage import PreconditionFailedError, Storage
from wenchang.version_token import VersionToken

DEFAULT_MAX_FILE_BYTES: int = 16 * 1024
DEFAULT_LIST_PAGE_SIZE: int = 100

_MAX_REPLACE_ATTEMPTS = 3

ListCursor = NewType("ListCursor", str)


def _encode_cursor(key: str) -> ListCursor:
    """Encode a storage key as an opaque cursor for resuming a listing."""
    return ListCursor(base64.urlsafe_b64encode(key.encode("utf-8")).decode("ascii"))


def _decode_cursor(cursor: ListCursor, prefix: str) -> str:
    """Decode `cursor` to the key it was issued after.

    Raises ValueError if `cursor` is not a well-formed cursor, or if it
    decodes to a key that does not start with `prefix`.
    """
    try:
        raw = base64.b64decode(cursor.encode("ascii"), altchars=b"-_", validate=True)
        key = raw.decode("utf-8")
    except (binascii.Error, UnicodeError) as exc:
        raise ValueError(f"Malformed list cursor: {cursor!r}") from exc
    if not key.startswith(prefix):
        raise ValueError(f"Cursor {cursor!r} was not issued for prefix {prefix!r}")
    return key


def _count_occurrences(content: str, old_string: str) -> int:
    """Count overlapping start positions of `old_string` in `content`."""
    count = 0
    index = 0
    while True:
        found = content.find(old_string, index)
        if found == -1:
            return count
        count += 1
        index = found + 1


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class MemoryFile:
    """A memory file's content, metadata, path, and version, as read from storage."""

    path: str
    content: str
    metadata: FileMetadata
    version: VersionToken


@dataclass(frozen=True)
class FileEntry:
    """One file's path, metadata, and version, as returned by list_prefix."""

    path: str
    metadata: FileMetadata
    version: VersionToken


@dataclass(frozen=True)
class ListPage:
    """One page of list_prefix results, with a cursor for the next page."""

    entries: tuple[FileEntry, ...]
    next_cursor: ListCursor | None


class MemoryStore:
    """Core memory operations over a Storage backend.

    Exposes read_file, write_file, replace_fact, and list_prefix.
    """

    def __init__(
        self,
        storage: Storage,
        *,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
        clock: Callable[[], datetime] = _utc_now,
        list_page_size: int = DEFAULT_LIST_PAGE_SIZE,
    ) -> None:
        if max_file_bytes <= 0:
            raise ValueError("max_file_bytes must be positive")
        if list_page_size <= 0:
            raise ValueError("list_page_size must be positive")
        self._storage = storage
        self._max_file_bytes = max_file_bytes
        self._clock = clock
        self._list_page_size = list_page_size

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

    def replace_fact(
        self,
        path: str,
        old_string: str,
        new_string: str,
        expected_version: VersionToken,
        *,
        source: str,
    ) -> MemoryFile:
        """Replace the single occurrence of `old_string` with `new_string`.

        Raises NotFoundError with reason INVALID_PATH if `path` is not
        well-formed, without calling storage. Raises ValueError if
        `old_string` or `source` is empty, without calling storage. Raises
        NotFoundError with reason FILE_ABSENT if no object exists at `path`.
        Raises ReplaceFactMatchError if `old_string` matches zero or more
        than one span of the current content, carrying that content,
        version, and match count; the file is left unchanged. On success,
        stamps `metadata.sources` with `source` added and `last_updated`
        with the store's clock, raising ValueError (from FileMetadata's own
        validation) if the clock returns a naive datetime. Retries on a
        concurrent write up to a fixed number of attempts, each time
        re-reading the current content and re-checking the match count
        against it; if `expected_version` no longer matches the version
        just read, raises VersionConflictError instead of
        ReplaceFactMatchError, carrying the current content and version.
        Raises VersionConflictError if attempts are exhausted. Propagates
        MetadataFormatError, UnicodeDecodeError, and BackendUnavailableError
        unchanged.
        """
        if not is_valid_path(path):
            raise NotFoundError(path, NotFoundReason.INVALID_PATH)

        if old_string == "" or source == "":
            raise ValueError("old_string and source must be non-empty")

        content = ""
        version: VersionToken = expected_version
        for _ in range(_MAX_REPLACE_ATTEMPTS):
            obj = self._storage.get(path)
            if obj is None:
                raise NotFoundError(path, NotFoundReason.FILE_ABSENT)

            content = obj.data.decode("utf-8")
            metadata = metadata_from_map(obj.metadata)
            version = obj.version

            count = _count_occurrences(content, old_string)
            if count != 1:
                if version == expected_version:
                    raise ReplaceFactMatchError(path, content, version, count)
                raise VersionConflictError(path, content, version)

            new_content = content.replace(old_string, new_string, 1)
            data = new_content.encode("utf-8")
            if len(data) > self._max_file_bytes:
                raise OversizeWriteError(path, len(data), self._max_file_bytes)

            stamped = dataclasses.replace(
                metadata,
                sources=metadata.sources | {source},
                last_updated=self._clock(),
            )

            try:
                new_version = self._storage.put_if_version(
                    path, data, metadata_to_map(stamped), version
                )
            except PreconditionFailedError:
                continue

            return MemoryFile(path=path, content=new_content, metadata=stamped, version=new_version)

        raise VersionConflictError(path, content, version)

    def append_line(
        self,
        path: str,
        line: str,
        expected_version: VersionToken,
        *,
        source: str,
    ) -> MemoryFile:
        """Append `line` to the current content, if it is at `expected_version`.

        Raises NotFoundError with reason INVALID_PATH if `path` is not
        well-formed, without calling storage. Raises ValueError if `line`
        does not parse as a single fact line, or if `source` is empty,
        without calling storage. Raises NotFoundError with reason
        FILE_ABSENT if no object exists at `path`. Raises
        VersionConflictError if `expected_version` does not match the
        current version, carrying the current content and version; there is
        no automatic re-apply. Raises OversizeWriteError if the resulting
        content exceeds max_file_bytes. On success, stamps
        `metadata.sources` with `source` added and `last_updated` with the
        store's clock, leaving other metadata unchanged. If the conditional
        write fails its precondition, re-reads and returns success if the
        stored content and metadata already equal exactly what was written
        (a backend-level retry of its own landed write); otherwise raises
        VersionConflictError, or NotFoundError with reason FILE_ABSENT if
        the file is now gone. Propagates MetadataFormatError,
        UnicodeDecodeError, and BackendUnavailableError unchanged.
        """
        if not is_valid_path(path):
            raise NotFoundError(path, NotFoundReason.INVALID_PATH)

        if parse_fact(line) is None or source == "":
            raise ValueError("line must be a single fact line and source must be non-empty")

        obj = self._storage.get(path)
        if obj is None:
            raise NotFoundError(path, NotFoundReason.FILE_ABSENT)

        content = obj.data.decode("utf-8")
        if obj.version != expected_version:
            raise VersionConflictError(path, content, obj.version)
        metadata = metadata_from_map(obj.metadata)

        sep = "\n" if content and not content.endswith("\n") else ""
        new_content = content + sep + line + "\n"
        data = new_content.encode("utf-8")
        if len(data) > self._max_file_bytes:
            raise OversizeWriteError(path, len(data), self._max_file_bytes)

        stamped = dataclasses.replace(
            metadata,
            sources=metadata.sources | {source},
            last_updated=self._clock(),
        )
        meta_map = metadata_to_map(stamped)

        try:
            new_version = self._storage.put_if_version(path, data, meta_map, expected_version)
        except PreconditionFailedError:
            cur = self._storage.get(path)
            if cur is None:
                raise NotFoundError(path, NotFoundReason.FILE_ABSENT) from None
            if cur.data == data and cur.metadata == meta_map:
                return MemoryFile(
                    path=path, content=new_content, metadata=stamped, version=cur.version
                )
            raise VersionConflictError(path, cur.data.decode("utf-8"), cur.version) from None

        return MemoryFile(path=path, content=new_content, metadata=stamped, version=new_version)

    def delete_file(self, path: str, expected_version: VersionToken) -> None:
        """Delete the file at `path`, if it is at `expected_version`.

        Raises NotFoundError with reason INVALID_PATH if `path` is not
        well-formed, without calling storage. Raises NotFoundError with
        reason FILE_ABSENT if no object exists at `path`. Raises
        VersionConflictError if `expected_version` does not match the
        current version, carrying the current content and version. Does
        not parse metadata, so a file with corrupt metadata is still
        deletable. If the conditional delete fails its precondition,
        re-reads and raises NotFoundError with reason FILE_ABSENT if the
        file is now gone, or VersionConflictError carrying the content and
        version found on re-read otherwise. Propagates
        BackendUnavailableError unchanged.
        """
        if not is_valid_path(path):
            raise NotFoundError(path, NotFoundReason.INVALID_PATH)

        obj = self._storage.get(path)
        if obj is None:
            raise NotFoundError(path, NotFoundReason.FILE_ABSENT)

        if obj.version != expected_version:
            raise VersionConflictError(path, obj.data.decode("utf-8"), obj.version)

        try:
            self._storage.delete_if_version(path, expected_version)
        except PreconditionFailedError:
            cur = self._storage.get(path)
            if cur is None:
                raise NotFoundError(path, NotFoundReason.FILE_ABSENT) from None
            raise VersionConflictError(path, cur.data.decode("utf-8"), cur.version) from None

    def list_prefix(self, prefix: str, cursor: ListCursor | None = None) -> ListPage:
        """List files under `prefix`, one page at a time.

        Raises NotFoundError with reason INVALID_PATH if `prefix` is not a
        well-formed prefix, without calling storage. `cursor`, if given,
        must be a value previously returned as `next_cursor` for this same
        `prefix`; otherwise raises ValueError. Entries are ordered
        ascending by path; objects whose key is not a well-formed memory
        path are omitted. Never calls storage.get. Propagates
        MetadataFormatError and BackendUnavailableError unchanged.
        """
        if not is_valid_prefix(prefix):
            raise NotFoundError(prefix, NotFoundReason.INVALID_PATH)

        start_after = None if cursor is None else _decode_cursor(cursor, prefix)

        objs = self._storage.list_page(prefix, start_after, self._list_page_size + 1)
        page, more = objs[: self._list_page_size], len(objs) > self._list_page_size

        entries = tuple(
            FileEntry(obj.key, metadata_from_map(obj.metadata), obj.version)
            for obj in page
            if is_valid_path(obj.key)
        )
        next_cursor = _encode_cursor(page[-1].key) if more else None
        return ListPage(entries=entries, next_cursor=next_cursor)
