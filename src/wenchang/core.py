"""Core memory operations over a Storage backend."""

import base64
import binascii
import dataclasses
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, NewType, cast

from wenchang.errors import (
    NotFoundError,
    NotFoundReason,
    OversizeWriteError,
    ReplaceFactMatchError,
    VersionConflictError,
)
from wenchang.file_format import (
    LAST_UPDATED_KEY,
    FileMetadata,
    MetadataFormatError,
    metadata_from_map,
    metadata_to_map,
    parse_fact,
)
from wenchang.paths import (
    build_prefix,
    is_valid_path,
    is_valid_prefix,
    is_valid_segment,
    parse_path,
)
from wenchang.storage import PreconditionFailedError, Storage
from wenchang.version_token import VersionToken

DEFAULT_MAX_FILE_BYTES: int = 16 * 1024
DEFAULT_LIST_PAGE_SIZE: int = 100
DEFAULT_INDEX_MAX_BYTES: int = 64 * 1024

# Equals scope.SYSTEM_AREA; core must not import scope.
INDEX_SYSTEM_AREA: Final = "system"

_MAX_REPLACE_ATTEMPTS = 3

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

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


def _type_name(t: type) -> str:
    # A metaclass may make __name__ raise or return a str subclass.
    try:
        return str.__str__(t.__name__)
    except Exception:
        return "<unnamed>"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _normalize_aliases(aliases: object) -> tuple[str, ...]:
    """Validate `aliases` by real type and return its members as exact str."""
    # A str is a Sequence of its characters, and a spoofed __class__ must not pass.
    if issubclass(type(aliases), (str, bytes, bytearray)) or not issubclass(
        type(aliases), Sequence
    ):
        raise TypeError(f"aliases must be a sequence of str, not {_type_name(type(aliases))}")
    members: list[str] = []
    for member in cast(Sequence[object], aliases):
        if not issubclass(type(member), str):
            raise TypeError(f"aliases entry must be str, got {_type_name(type(member))}")
        members.append(str.__str__(cast(str, member)))
    return tuple(members)


def _normalize_description(description: object) -> str:
    """Validate `description` by real type and return it as an exact single-line str."""
    if not issubclass(type(description), str):
        raise TypeError(f"description must be a str, not {_type_name(type(description))}")
    exact = str.__str__(cast(str, description))
    if "\n" in exact or "\r" in exact:
        raise ValueError("description must not contain a newline or carriage return")
    return exact


def _merge_metadata(
    stored: FileMetadata,
    source: str,
    aliases: tuple[str, ...] | None,
    description: str | None,
    now: datetime,
) -> FileMetadata:
    """`stored` with `aliases` unioned in order, `description` replaced, and `source` added."""
    merged = list(stored.aliases)
    for alias in aliases or ():
        if alias not in merged:
            merged.append(alias)
    return dataclasses.replace(
        stored,
        aliases=tuple(merged),
        description=stored.description if description is None else description,
        sources=stored.sources | {source},
        last_updated=now,
    )


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


def _utf8_len(s: str) -> int:
    return len(s.encode("utf-8", errors="surrogatepass"))


def index_entry_bytes(entry: FileEntry) -> int:
    """UTF-8 size of an index entry: path, every metadata key and value, and version.

    Raises MetadataFormatError if last-updated cannot be rendered in UTC.
    """
    try:
        rendered = metadata_to_map(entry.metadata)
    except OverflowError as exc:
        raise MetadataFormatError(
            LAST_UPDATED_KEY, "last-updated cannot be rendered in UTC"
        ) from exc
    return (
        _utf8_len(entry.path)
        + sum(_utf8_len(k) + _utf8_len(v) for k, v in rendered.items())
        + _utf8_len(entry.version)
    )


@dataclass(frozen=True)
class ListPage:
    """One page of list_prefix results, with a cursor for the next page."""

    entries: tuple[FileEntry, ...]
    next_cursor: ListCursor | None


@dataclass(frozen=True)
class CappedPrefix:
    """A prefix the memory index could not return in full.

    `omitted` is how many files under `prefix` were left out. The agent can
    call `list_prefix(prefix)` to page through them.
    """

    prefix: str
    omitted: int

    def __post_init__(self) -> None:
        # Real-type checks: a remote client builds this from deserialized data.
        prefix = cast(object, self.prefix)
        omitted = cast(object, self.omitted)
        if not issubclass(type(prefix), str):
            raise TypeError(f"prefix must be a str, not {_type_name(type(prefix))}")
        if issubclass(type(omitted), bool) or not issubclass(type(omitted), int):
            raise TypeError(f"omitted must be an int, not {_type_name(type(omitted))}")
        # Exact str and int, so overridden subclass methods cannot mislead validation.
        exact_prefix = str.__str__(cast(str, prefix))
        exact_omitted = int.__index__(cast(int, omitted))
        object.__setattr__(self, "prefix", exact_prefix)
        object.__setattr__(self, "omitted", exact_omitted)
        if not is_valid_prefix(exact_prefix):
            raise ValueError(f"invalid prefix: {exact_prefix!r}")
        if exact_omitted <= 0:
            raise ValueError(f"omitted must be positive, got {exact_omitted}")


@dataclass(frozen=True)
class MemoryIndex:
    """Merged metadata across every scope in a scope map, in load order.

    `entries` is already ordered: system/ areas across all scopes first;
    then the remaining scopes in the configured priority order, or as one
    tier if none is configured; within each tier by last-updated, most
    recent first. `capped` lists every prefix not fully returned once the
    byte budget was reached; an empty `capped` means the index is complete.
    """

    entries: tuple[FileEntry, ...] = ()
    capped: tuple[CappedPrefix, ...] = ()

    def __post_init__(self) -> None:
        # Exact types: a subclass can lie through __iter__, __eq__, __hash__, or
        # __getattribute__, defeating duplicate detection and equality.
        if type(self.entries) is not tuple or type(self.capped) is not tuple:
            raise TypeError("entries and capped must be exact tuples")
        for entry in cast(tuple[object, ...], self.entries):
            if type(entry) is not FileEntry:
                raise TypeError(
                    f"entries member must be a FileEntry, not {_type_name(type(entry))}"
                )
        for cap in cast(tuple[object, ...], self.capped):
            if type(cap) is not CappedPrefix:
                raise TypeError(
                    f"capped member must be a CappedPrefix, not {_type_name(type(cap))}"
                )
        paths: set[str] = set()
        for entry in self.entries:
            if entry.path in paths:
                raise ValueError(f"duplicate entry path: {entry.path!r}")
            paths.add(entry.path)
        prefixes: set[str] = set()
        for cap in self.capped:
            if cap.prefix in prefixes:
                raise ValueError(f"duplicate capped prefix: {cap.prefix!r}")
            prefixes.add(cap.prefix)


class MemoryStore:
    """Core memory operations over a Storage backend.

    Exposes read_file, write_file, replace_fact, append_line, delete_file,
    list_prefix, and get_memory_index.
    """

    def __init__(
        self,
        storage: Storage,
        *,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
        clock: Callable[[], datetime] = _utc_now,
        list_page_size: int = DEFAULT_LIST_PAGE_SIZE,
        index_max_bytes: int = DEFAULT_INDEX_MAX_BYTES,
        scope_priority: Sequence[str] = (),
    ) -> None:
        # Real-type checks: a str is a Sequence of its characters, and a
        # spoofed __class__ must not pass.
        priority = cast(object, scope_priority)
        if issubclass(type(priority), (str, bytes, bytearray)) or not issubclass(
            type(priority), Sequence
        ):
            raise TypeError(
                f"scope_priority must be a sequence of str, not {_type_name(type(priority))}"
            )
        members: list[str] = []
        for member in cast(Sequence[object], priority):
            if not issubclass(type(member), str):
                raise TypeError(f"scope_priority entry must be str, got {_type_name(type(member))}")
            members.append(str.__str__(cast(str, member)))

        if max_file_bytes <= 0:
            raise ValueError("max_file_bytes must be positive")
        if list_page_size <= 0:
            raise ValueError("list_page_size must be positive")
        if index_max_bytes <= 0:
            raise ValueError("index_max_bytes must be positive")
        seen: set[str] = set()
        for s in members:
            if not is_valid_segment(s):
                raise ValueError(f"invalid scope_priority entry: {s!r}")
            if s in seen:
                raise ValueError(f"duplicate scope_priority entry: {s!r}")
            seen.add(s)

        self._storage = storage
        self._max_file_bytes = max_file_bytes
        self._clock = clock
        self._list_page_size = list_page_size
        self._index_max_bytes = index_max_bytes
        self._scope_priority = tuple(members)

    @property
    def index_max_bytes(self) -> int:
        """The byte budget for get_memory_index entries."""
        return self._index_max_bytes

    @property
    def scope_priority(self) -> tuple[str, ...]:
        """Scopes in index priority order; unlisted scopes rank after them."""
        return self._scope_priority

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
        *,
        source: str,
    ) -> MemoryFile:
        """Write the memory file at `path`, creating or replacing it.

        Raises NotFoundError with reason INVALID_PATH if `path` is not
        well-formed, without calling storage. Raises ValueError if `source`
        is empty, without calling storage. Raises OversizeWriteError if the
        UTF-8 encoding of `content` exceeds `max_file_bytes`, without
        calling storage. `expected_version=None` requires the file to not
        already exist, and stores `metadata.sources | {source}`. A non-None
        value requires it to match the current version exactly, and stores
        the union of the currently stored sources, `metadata.sources`, and
        `source`: a caller never has to carry forward sources it doesn't
        know about, and can't remove a source others recorded. Stamps
        `metadata.last_updated` with the store's clock, raising ValueError
        (from FileMetadata's own validation) if the clock returns a naive
        datetime. On a version mismatch raises VersionConflictError
        carrying the current content and version, or NotFoundError with
        reason FILE_ABSENT if the file does not exist. Propagates
        MetadataFormatError, UnicodeDecodeError, and BackendUnavailableError
        unchanged.
        """
        if not is_valid_path(path):
            raise NotFoundError(path, NotFoundReason.INVALID_PATH)

        if source == "":
            raise ValueError("source must be non-empty")

        data = content.encode("utf-8")
        if len(data) > self._max_file_bytes:
            raise OversizeWriteError(path, len(data), self._max_file_bytes)

        if expected_version is None:
            sources = metadata.sources | {source}
        else:
            obj = self._storage.get(path)
            if obj is None:
                raise NotFoundError(path, NotFoundReason.FILE_ABSENT)
            if obj.version != expected_version:
                metadata_from_map(obj.metadata)
                raise VersionConflictError(path, obj.data.decode("utf-8"), obj.version)
            stored = metadata_from_map(obj.metadata)
            sources = stored.sources | metadata.sources | {source}

        stamped = dataclasses.replace(metadata, sources=sources, last_updated=self._clock())

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
        aliases: Sequence[str] | None = None,
        description: str | None = None,
    ) -> MemoryFile:
        """Replace the single occurrence of `old_string` with `new_string`.

        Raises NotFoundError with reason INVALID_PATH if `path` is not
        well-formed, without calling storage. Raises ValueError if
        `old_string` or `source` is empty, without calling storage. Raises
        TypeError for a wrongly typed `aliases`, alias, or `description`,
        and ValueError for a `description` containing a newline or carriage
        return, all without calling storage. Raises NotFoundError with
        reason FILE_ABSENT if no object exists at `path`.
        Raises ReplaceFactMatchError if `old_string` matches zero or more
        than one span of the current content, carrying that content,
        version, and match count; the file is left unchanged. On success,
        stamps `metadata.sources` with `source` added and `last_updated`
        with the store's clock, raising ValueError (from FileMetadata's own
        validation) if the clock returns a naive datetime. `aliases`, if
        given, are added to the stored aliases in order, skipping any
        already present; stored aliases are never removed or reordered.
        `description`, if given, replaces the stored description. Both
        commit in the same write as the content. Retries on a
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

        new_aliases = None if aliases is None else _normalize_aliases(aliases)
        new_description = None if description is None else _normalize_description(description)

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

            stamped = _merge_metadata(metadata, source, new_aliases, new_description, self._clock())

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
        aliases: Sequence[str] | None = None,
        description: str | None = None,
    ) -> MemoryFile:
        """Append `line` to the current content, if it is at `expected_version`.

        Raises NotFoundError with reason INVALID_PATH if `path` is not
        well-formed, without calling storage. Raises ValueError if `line`
        does not parse as a single fact line, or if `source` is empty,
        without calling storage. Raises TypeError for a wrongly typed
        `aliases`, alias, or `description`, and ValueError for a
        `description` containing a newline or carriage return, all without
        calling storage. Raises NotFoundError with reason
        FILE_ABSENT if no object exists at `path`. Raises
        VersionConflictError if `expected_version` does not match the
        current version, carrying the current content and version; there is
        no automatic re-apply. Raises OversizeWriteError if the resulting
        content exceeds max_file_bytes. On success, stamps
        `metadata.sources` with `source` added and `last_updated` with the
        store's clock. `aliases`, if given, are added to the stored aliases
        in order, skipping any already present; stored aliases are never
        removed or reordered. `description`, if given, replaces the stored
        description. Both commit in the same write as the content. Other
        metadata is left unchanged. If the conditional
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

        new_aliases = None if aliases is None else _normalize_aliases(aliases)
        new_description = None if description is None else _normalize_description(description)

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

        stamped = _merge_metadata(metadata, source, new_aliases, new_description, self._clock())
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

    def get_memory_index(self, scope_map: Mapping[str, str]) -> MemoryIndex:
        """Merged metadata across every scope in `scope_map`, ordered and byte-capped.

        Order: system/ areas across all scopes first; then scopes in
        `scope_priority` order, unlisted scopes last as one tier; within a
        tier by last-updated, most recent first, then by path. Entries are
        included in that order until the next one would exceed
        `index_max_bytes`; the rest are reported in `capped` by area prefix.
        Every entry is sized first, so an unrenderable one raises even past
        the cap.

        Raises TypeError if `scope_map` is not a Mapping of str to str, and
        ValueError for an invalid scope or entity_id or a duplicate scope,
        all without calling storage. Propagates MetadataFormatError and
        BackendUnavailableError unchanged.
        """
        if not issubclass(type(cast(object, scope_map)), Mapping):
            raise TypeError(
                f"scope_map must be a Mapping, not {_type_name(type(cast(object, scope_map)))}"
            )
        raw = list(cast(Mapping[object, object], scope_map).items())
        normalized: list[tuple[str, str]] = []
        for item in cast(list[object], raw):
            if type(item) is not tuple or len(cast(tuple[object, ...], item)) != 2:
                raise TypeError("scope_map items must be (str, str) pairs")
            key, value = cast(tuple[object, object], item)
            if not issubclass(type(key), str):
                raise TypeError(f"scope_map key must be str, got {_type_name(type(key))}")
            if not issubclass(type(value), str):
                raise TypeError(f"scope_map value must be str, got {_type_name(type(value))}")
            normalized.append((str.__str__(cast(str, key)), str.__str__(cast(str, value))))
        pairs = sorted(normalized)
        seen: set[str] = set()
        for scope, entity_id in pairs:
            if not is_valid_segment(scope):
                raise ValueError(f"invalid scope: {scope!r}")
            if not is_valid_segment(entity_id):
                raise ValueError(f"invalid entity_id: {entity_id!r}")
            if scope in seen:
                raise ValueError(f"duplicate scope: {scope!r}")
            seen.add(scope)
        if not pairs:
            return MemoryIndex()

        collected: list[FileEntry] = []
        for scope, entity_id in pairs:
            prefix = build_prefix(scope, entity_id)
            cursor: ListCursor | None = None
            while True:
                # The base method, so a subclass override cannot alter the index.
                page = MemoryStore.list_prefix(self, prefix, cursor)
                collected.extend(page.entries)
                cursor = page.next_cursor
                if cursor is None:
                    break

        priority_index = {s: i for i, s in enumerate(self._scope_priority)}
        unlisted = len(self._scope_priority)

        def sort_key(entry: FileEntry) -> tuple[int, int, int, str]:
            parts = parse_path(entry.path)
            micros = (entry.metadata.last_updated - _EPOCH) // timedelta(microseconds=1)
            if parts.area == INDEX_SYSTEM_AREA:
                return (0, 0, -micros, entry.path)
            return (1, priority_index.get(parts.scope, unlisted), -micros, entry.path)

        ordered = sorted(collected, key=sort_key)
        # Size every entry up front so an unrenderable one raises regardless of the cap.
        sized = [(entry, index_entry_bytes(entry)) for entry in ordered]

        included: list[FileEntry] = []
        total = 0
        for entry, size in sized:
            if total + size > self._index_max_bytes:
                break
            included.append(entry)
            total += size

        counts: dict[str, int] = {}
        for entry in ordered[len(included) :]:
            parts = parse_path(entry.path)
            area_prefix = build_prefix(parts.scope, parts.entity_id, parts.area)
            counts[area_prefix] = counts.get(area_prefix, 0) + 1
        capped = tuple(CappedPrefix(p, n) for p, n in sorted(counts.items()))
        return MemoryIndex(entries=tuple(included), capped=capped)
