"""Transport-agnostic client contract mirroring the core API.

The tool layer calls a `TransportClient`. A concrete implementation is
injected at startup and may run in-process over `MemoryStore` or remotely
(for example over gRPC); implementations must be behaviorally
indistinguishable.
"""

from collections.abc import Mapping
from typing import Protocol, cast, runtime_checkable

from wenchang.core import ListCursor, ListPage, MemoryFile, MemoryIndex, MemoryStore
from wenchang.file_format import FileMetadata
from wenchang.version_token import VersionToken

__all__ = ["InProcessClient", "TransportClient"]


def _type_name(t: type) -> str:
    # A metaclass may make __name__ raise or return a str subclass.
    try:
        return str.__str__(t.__name__)
    except Exception:
        return "<unnamed>"


@runtime_checkable
class TransportClient(Protocol):
    """The seven memory operations over any transport.

    Each of the six operations that `MemoryStore` implements mirrors
    the `MemoryStore` method of the same name: the same parameters, the same
    return type, and, for well-typed arguments, exactly the same exception
    types with equal attributes and message. That covers the
    `wenchang.errors` taxonomy (same category, same payload) and the
    non-taxonomy errors core raises, including `ValueError` for an empty
    `source` or `old_string`, a `line` that is not a fact line, or a
    malformed or foreign `cursor`; `MetadataFormatError` for corrupt stored
    metadata; and `UnicodeDecodeError` for a non-UTF-8 body. A client never
    reshapes an error into its own vocabulary: a version conflict is a
    `VersionConflictError` carrying current content and version whether it
    came from an in-process call or a remote one. A failure of the
    transport itself (a timeout, a refused connection, a crashed server)
    surfaces as `BackendUnavailableError` with the matching
    `TransientReason`, never as a transport library's own exception type.
    `get_memory_index` follows
    `MemoryStore.get_memory_index` the same way.
    """

    def read_file(self, path: str) -> MemoryFile:
        """Return the file at `path` with its metadata and version token."""
        ...

    def write_file(
        self,
        path: str,
        content: str,
        metadata: FileMetadata,
        expected_version: VersionToken | None,
        *,
        source: str,
    ) -> MemoryFile:
        """Replace the whole file, or create it when `expected_version` is None."""
        ...

    def append_line(
        self, path: str, line: str, expected_version: VersionToken, *, source: str
    ) -> MemoryFile:
        """Append one fact line to an existing file at `expected_version`."""
        ...

    def replace_fact(
        self,
        path: str,
        old_string: str,
        new_string: str,
        expected_version: VersionToken,
        *,
        source: str,
    ) -> MemoryFile:
        """Replace the unique occurrence of `old_string` with `new_string`."""
        ...

    def list_prefix(self, prefix: str, cursor: ListCursor | None = None) -> ListPage:
        """Return one page of file metadata under `prefix`, without content."""
        ...

    def delete_file(self, path: str, expected_version: VersionToken) -> None:
        """Delete the file at `path` if it is still at `expected_version`."""
        ...

    def get_memory_index(self, scope_map: Mapping[str, str]) -> MemoryIndex:
        """Return merged metadata across every scope in `scope_map`, byte-capped."""
        ...


class InProcessClient:
    """A TransportClient that calls a MemoryStore directly, with no network hop.

    Every method forwards its arguments unchanged and returns the store's
    result; every exception propagates as raised.
    """

    def __init__(self, store: MemoryStore) -> None:
        if not issubclass(type(cast(object, store)), MemoryStore):
            raise TypeError(f"store must be a MemoryStore, got {_type_name(type(store))}")
        self._store = store

    @property
    def store(self) -> MemoryStore:
        """The wrapped store."""
        return self._store

    def read_file(self, path: str) -> MemoryFile:
        """Return the file at `path` with its metadata and version token."""
        return self._store.read_file(path)

    def write_file(
        self,
        path: str,
        content: str,
        metadata: FileMetadata,
        expected_version: VersionToken | None,
        *,
        source: str,
    ) -> MemoryFile:
        """Replace the whole file, or create it when `expected_version` is None."""
        return self._store.write_file(path, content, metadata, expected_version, source=source)

    def append_line(
        self, path: str, line: str, expected_version: VersionToken, *, source: str
    ) -> MemoryFile:
        """Append one fact line to an existing file at `expected_version`."""
        return self._store.append_line(path, line, expected_version, source=source)

    def replace_fact(
        self,
        path: str,
        old_string: str,
        new_string: str,
        expected_version: VersionToken,
        *,
        source: str,
    ) -> MemoryFile:
        """Replace the unique occurrence of `old_string` with `new_string`."""
        return self._store.replace_fact(
            path, old_string, new_string, expected_version, source=source
        )

    def list_prefix(self, prefix: str, cursor: ListCursor | None = None) -> ListPage:
        """Return one page of file metadata under `prefix`, without content."""
        return self._store.list_prefix(prefix, cursor)

    def delete_file(self, path: str, expected_version: VersionToken) -> None:
        """Delete the file at `path` if it is still at `expected_version`."""
        self._store.delete_file(path, expected_version)

    def get_memory_index(self, scope_map: Mapping[str, str]) -> MemoryIndex:
        """Return merged metadata across every scope in `scope_map`, byte-capped."""
        return self._store.get_memory_index(scope_map)
