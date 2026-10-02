"""Conformance suite for TransportClient implementations.

Requires the `testing` extra: `pip install "wenchang[testing]"`.

Subclass TransportConformance in a test module, with a class name starting
with "Test", and supply these fixtures:

    client           a fresh TransportClient over an empty store, per test
    source           a non-empty str the cases pass as `source=`
    scope_map        a Mapping of at least two scopes to entity IDs; every
                     scope must be writable through `client`
    max_file_bytes   the store's max_file_bytes (an int, at least 64)
    index_max_bytes  the store's index_max_bytes (a positive int)
    scope_priority   the store's scope_priority, as an exact tuple of str
    list_page_size   the store's list_page_size (a positive int)

Isolation: each case that touches the store first writes a sentinel file
under the first sorted scope's entity, in area "conformance-sentinel", and
fails if it already exists, so a `client` fixture shared across tests is
caught.

Clock: within one test, a client's writes must stamp strictly increasing
`last_updated` values. Cases call the client sequentially; no thread safety
is required.

Version tokens are opaque: the suite never compares them, only hands them
back to the client.

Example:

    class TestMyClient(TransportConformance):
        @pytest.fixture
        def client(self) -> TransportClient:
            return MyClient(...)
        ...

The suite applies no pytest marks; mark your own subclass if needed.
Passing every test defines a conforming client.
"""

from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from typing import Final, NoReturn, cast, overload

import pytest

from wenchang.core import (
    CappedPrefix,
    FileEntry,
    ListCursor,
    ListPage,
    MemoryFile,
    MemoryIndex,
    index_entry_bytes,
)
from wenchang.errors import (
    ErrorCategory,
    NotFoundError,
    NotFoundReason,
    OversizeWriteError,
    RecoverableError,
    ReplaceFactMatchError,
    VersionConflictError,
    WenchangError,
)
from wenchang.file_format import FileMetadata
from wenchang.paths import build_path, build_prefix, is_valid_path, is_valid_segment, parse_path
from wenchang.transport import TransportClient
from wenchang.version_token import VersionToken

PROBE_AREA: Final = "notes"
PROBE_STEM: Final = "conformance-probe"
PROBE_STEM_2: Final = "conformance-probe-2"
PROBE_STEM_3: Final = "conformance-probe-3"
INDEX_AREA: Final = "conformance-index"
SENTINEL_AREA: Final = "conformance-sentinel"
SENTINEL_STEM: Final = "sentinel"
MIN_FILE_BYTES: Final = 64
_SENTINEL_SOURCE: Final = "conformance-harness"
_SENTINEL_CONTENT: Final = "- [system] conformance sentinel\n"
_REPR_LIMIT: Final = 80
_MAX_PAGES: Final = 1000
_FACTS: Final = "- [stated] alpha\n- [stated] beta\n- [stated] alpha\n"
# Handed only to calls on absent paths, where any token must yield FILE_ABSENT.
_ABSENT_TOKEN: Final = VersionToken("1")

# Exact core messages, pinned for parity.
MSG_WRITE_ARGS: Final = "source must be non-empty"
MSG_REPLACE_ARGS: Final = "old_string and source must be non-empty"
MSG_APPEND_ARGS: Final = "line must be a single fact line and source must be non-empty"
MSG_MALFORMED_CURSOR: Final = "Malformed list cursor: {cursor!r}"
MSG_FOREIGN_CURSOR: Final = "Cursor {cursor!r} was not issued for prefix {prefix!r}"
MSG_INVALID_SCOPE: Final = "invalid scope: {scope!r}"
MSG_INVALID_ENTITY: Final = "invalid entity_id: {entity_id!r}"
_INVALID_PATHS: Final = ("a/b", "a/b/c/d", "a/../c/d.md")

_SYSTEM_AREA: Final = "system"
_CAP_FILES: Final = 20
_CAP_DESCRIPTION: Final = "x" * 200

_METHODS: Final = (
    "read_file",
    "write_file",
    "append_line",
    "replace_fact",
    "list_prefix",
    "delete_file",
    "get_memory_index",
)
_PROBE_LABEL: Final = "probe path"
_RECOVERABLE: Final = ErrorCategory.RECOVERABLE
_FILE_ABSENT: Final = NotFoundReason.FILE_ABSENT

type CanonicalFile = tuple[str, str, str, tuple[str, ...], tuple[str, ...], datetime]
type CanonicalEntry = tuple[str, str, tuple[str, ...], tuple[str, ...], datetime]
type CanonicalPage = tuple[tuple[CanonicalEntry, ...], bool]
type CanonicalIndex = tuple[tuple[CanonicalEntry, ...], tuple[tuple[str, int], ...]]


def _name(t: type) -> str:
    """t.__name__, or "<unnamed>" if reading it raises."""
    # A metaclass may make __name__ raise or return a str subclass.
    try:
        return str.__str__(t.__name__)
    except Exception:
        return "<unnamed>"


def _short(value: object) -> str:
    """repr(value) truncated to _REPR_LIMIT characters, or "<unreadable>" if repr raises."""
    try:
        text = str.__str__(repr(value))
    except Exception:
        return "<unreadable>"
    if len(text) <= _REPR_LIMIT:
        return text
    return text[: _REPR_LIMIT - 3] + "..."


def _fail(name: str, label: str, text: str, /) -> NoReturn:
    pytest.fail(f"{name}: {label}: {text}")


# --- Fixture checks ----------------------------------------------------------


def check_client(name: str, client: object) -> TransportClient:
    """Return client if it satisfies TransportClient, else fail ("fixture client")."""
    for method in _METHODS:
        try:
            attr = cast(object, getattr(client, method))
        except AttributeError:
            pytest.fail(f"{name}: fixture client is missing method {method}")
        except Exception as exc:
            pytest.fail(
                f"{name}: fixture client method {method} could not be read: "
                f"raised {_name(type(exc))}"
            )
        if not callable(attr):
            pytest.fail(f"{name}: fixture client method {method} is not callable")
    try:
        satisfies = isinstance(client, TransportClient)
    except Exception as exc:
        pytest.fail(f"{name}: fixture client could not be checked: raised {_name(type(exc))}")
    if not satisfies:
        pytest.fail(f"{name}: fixture client must be a TransportClient, got {_name(type(client))}")
    return cast(TransportClient, client)


def check_source(name: str, source: object) -> str:
    """Return source if it is a non-empty exact str, else fail ("fixture source")."""
    if type(source) is not str:
        pytest.fail(f"{name}: fixture source must be a non-empty str, got {_name(type(source))}")
    if not source:
        pytest.fail(f"{name}: fixture source must be a non-empty str, got an empty str")
    return source


def check_scope_map(name: str, scope_map: object) -> dict[str, str]:
    """Return a plain dict copy of a valid scope_map, else fail ("fixture scope_map")."""
    prefix = f"{name}: fixture scope_map"
    if not issubclass(type(scope_map), Mapping):
        pytest.fail(f"{prefix} must be a Mapping, got {_name(type(scope_map))}")
    mapping = cast(Mapping[object, object], scope_map)
    try:
        items = list(mapping.items())
    except Exception as exc:
        pytest.fail(f"{prefix} could not be read: raised {_name(type(exc))}")
    if len(items) < 2:
        pytest.fail(f"{prefix} must map at least two scopes, got {len(items)}")
    result: dict[str, str] = {}
    for key, value in items:
        if type(key) is not str:
            pytest.fail(f"{prefix} key must be a str, got {_name(type(key))}")
        if key in result:
            pytest.fail(f"{prefix} has duplicate key {_short(key)}")
        if type(value) is not str:
            pytest.fail(f"{prefix} value for {key!r} must be a str, got {_name(type(value))}")
        if not is_valid_segment(key):
            pytest.fail(f"{prefix} key {_short(key)} is not a valid path segment")
        if not is_valid_segment(value):
            pytest.fail(f"{prefix} value {_short(value)} is not a valid path segment")
        result[key] = value
    if len(result) < 2:
        pytest.fail(f"{prefix} must map at least two scopes, got {len(result)}")
    return result


def check_positive_int(name: str, fixture: str, value: object, minimum: int = 1) -> int:
    """Return value if it is an exact int (not bool) of at least minimum, else fail."""
    if type(value) is not int:
        pytest.fail(f"{name}: fixture {fixture} must be an int, got {_name(type(value))}")
    if value < minimum:
        pytest.fail(f"{name}: fixture {fixture} must be at least {minimum}, got {value}")
    return value


def check_scope_priority(name: str, value: object) -> tuple[str, ...]:
    """Return value if it is a tuple of distinct valid str segments, else fail."""
    prefix = f"{name}: fixture scope_priority"
    if type(value) is not tuple:
        pytest.fail(f"{prefix} must be a tuple, got {_name(type(value))}")
    members = cast(tuple[object, ...], value)
    seen: list[str] = []
    for member in members:
        if type(member) is not str:
            pytest.fail(f"{prefix} member must be a str, got {_name(type(member))}")
        if not is_valid_segment(member):
            pytest.fail(f"{prefix} member {_short(member)} is not a valid path segment")
        if member in seen:
            pytest.fail(f"{prefix} has duplicate member {_short(member)}")
        seen.append(member)
    return tuple(seen)


# --- Paths and the sentinel --------------------------------------------------


def probe_path(
    name: str, label: str, scope_map: Mapping[str, str], scope: str, area: str, stem: str, /
) -> str:
    """build_path(scope, scope_map[scope], area, stem); fail ("probe scope") if scope is absent."""
    if scope not in scope_map:
        _fail(name, label, f"probe scope {_short(scope)} is not in scope_map")
    return build_path(scope, scope_map[scope], area, stem)


def _first_scope(scope_map: Mapping[str, str]) -> str:
    return sorted(scope_map)[0]


def sentinel_path(scope_map: Mapping[str, str]) -> str:
    """The sentinel file path, under the first sorted scope's own entity."""
    first = _first_scope(scope_map)
    return build_path(first, scope_map[first], SENTINEL_AREA, SENTINEL_STEM)


def _drop_sentinel(name: str, label: str, entries: Iterable[object]) -> tuple[FileEntry, ...]:
    kept: list[FileEntry] = []
    for entry in entries:
        path = canonical_entry(name, label, entry)[0]
        if parse_path(path).area != SENTINEL_AREA:
            kept.append(cast(FileEntry, entry))
    return tuple(kept)


@overload
def without_sentinel(name: str, label: str, value: MemoryIndex, /) -> MemoryIndex: ...
@overload
def without_sentinel(
    name: str, label: str, value: Iterable[FileEntry], /
) -> tuple[FileEntry, ...]: ...
def without_sentinel(
    name: str, label: str, value: MemoryIndex | Iterable[FileEntry], /
) -> MemoryIndex | tuple[FileEntry, ...]:
    """Drop sentinel-area entries (and, for an index, the sentinel CappedPrefix)."""
    raw = cast(object, value)
    if issubclass(type(raw), MemoryIndex):
        raw_entries, canon_entries, raw_capped, canon_capped = _index_parts(name, label, raw)
        suffix = f"/{SENTINEL_AREA}/"
        entries = tuple(
            cast(FileEntry, e)
            for e, c in zip(raw_entries, canon_entries, strict=True)
            if parse_path(c[0]).area != SENTINEL_AREA
        )
        capped = tuple(
            cast(CappedPrefix, cap)
            for cap, (prefix, _) in zip(raw_capped, canon_capped, strict=True)
            if not prefix.endswith(suffix)
        )
        return _call(name, label, lambda: MemoryIndex(entries=entries, capped=capped))
    entries = _call(name, label, lambda: tuple(cast(Iterable[object], raw)))
    return _drop_sentinel(name, label, entries)


def sentinel_entry_bytes(
    name: str, client: TransportClient, scope_map: Mapping[str, str], /
) -> int:
    """index_entry_bytes of the sentinel FileEntry as listed through the client."""
    first = _first_scope(scope_map)
    prefix = build_prefix(first, scope_map[first], SENTINEL_AREA)
    label = f"list_prefix({prefix})"
    page = cast(object, _call(name, label, lambda: client.list_prefix(prefix)))
    _outer(name, label, page, ListPage)
    raw_entries = _get(name, label, page, "entries")
    _canonical_entries(name, label, raw_entries)
    _canonical_cursor(name, label, page)
    entries = cast(tuple[FileEntry, ...], raw_entries)
    if len(entries) != 1:
        _fail(name, label, f"sentinel missing: expected exactly one entry, got {len(entries)}")
    entry = entries[0]
    return _call(name, label, lambda: index_entry_bytes(entry))


def _call[T](name: str, label: str, fn: Callable[[], T], /) -> T:
    """Run fn(); any Exception fails ("unexpected error") naming label and the type."""
    try:
        return fn()
    except Exception as exc:
        # Raised inside the handler so pytest shows the original exception as context.
        _fail(name, label, f"unexpected error: {_name(type(exc))}")


def _reraise(exc: Exception) -> Callable[[], object]:
    def call() -> object:
        raise exc

    return call


def require_fresh(name: str, client: TransportClient, scope_map: Mapping[str, str], /) -> None:
    """Fail ("not isolated") if the sentinel exists; then write it."""
    path = sentinel_path(scope_map)
    read_label = f"read_file({path})"
    write_label = f"write_file({path})"
    try:
        result = cast(object, client.read_file(path))
    except Exception as exc:
        expect_error(
            name,
            read_label,
            _reraise(exc),
            NotFoundError,
            _RECOVERABLE,
            path=path,
            reason=_FILE_ABSENT,
        )
    else:
        _fail(
            name,
            read_label,
            "client is not isolated: the sentinel exists before this test wrote it "
            f"(read returned {_name(type(result))})",
        )
    metadata = FileMetadata(
        "conformance sentinel", (), frozenset(), datetime(2000, 1, 1, tzinfo=UTC)
    )
    try:
        client.write_file(path, _SENTINEL_CONTENT, metadata, None, source=_SENTINEL_SOURCE)
    except Exception as exc:
        _fail(name, write_label, f"sentinel write failed: {_name(type(exc))}")


# --- Error parity ------------------------------------------------------------


def _check_raised[E: Exception](
    name: str,
    label: str,
    exc: Exception,
    expected: type[E],
    category: ErrorCategory | None,
    message: str | None,
    payload: Mapping[str, object],
) -> E:
    if type(exc) is not expected:
        _fail(
            name,
            label,
            f"raised {_name(type(exc))}, wrong error type, expected {_name(expected)}",
        )
    if category is not None:
        try:
            got_category = cast(object, cast(WenchangError, exc).category)
        except Exception:
            _fail(name, label, "wrong category: unreadable")
        if got_category is not category:
            _fail(name, label, f"wrong category: {_short(got_category)}, expected {category}")
    if message is not None:
        try:
            got_message = str(exc)
        except Exception:
            _fail(name, label, "wrong message: unreadable")
        if got_message != message:
            _fail(name, label, f"wrong message: {_short(got_message)}, expected {_short(message)}")
    for attr, want in payload.items():
        try:
            got = cast(object, getattr(exc, attr))
        except AttributeError:
            _fail(name, label, f"wrong payload: {attr} missing")
        except Exception:
            _fail(name, label, f"wrong payload: {attr} unreadable")
        if type(got) is not type(want):
            _fail(
                name,
                label,
                f"wrong payload: {attr} has type {_name(type(got))}, expected {_name(type(want))}",
            )
        if got != want:
            _fail(name, label, f"wrong payload: {attr} is {_short(got)}, expected {_short(want)}")
    return cast(E, exc)


def expect_error[E: Exception](
    name: str,
    label: str,
    call: Callable[[], object],
    expected: type[E],
    category: ErrorCategory | None,
    /,
    *,
    message: str | None = None,
    **payload: object,
) -> E:
    """Run call(); fail unless it raises exactly `expected` with this category, message, payload.

    `category` is required for WenchangError subclasses and must be None otherwise.
    """
    is_taxonomy = issubclass(expected, WenchangError)
    if (category is None) == is_taxonomy:
        need = "given" if is_taxonomy else "None"
        _fail(name, label, f"harness misuse: category must be {need} for {_name(expected)}")
    try:
        result = call()
    except Exception as exc:
        return _check_raised(name, label, exc, expected, category, message, payload)
    hint = "; check the max_file_bytes fixture" if expected is OversizeWriteError else ""
    _fail(
        name,
        label,
        f"{_name(expected)} did not raise; call returned {_name(type(result))}{hint}",
    )


# --- Canonical readers -------------------------------------------------------


def _get(name: str, label: str, value: object, attr: str, /) -> object:
    """getattr(value, attr); any Exception fails "bad field <attr>: unreadable"."""
    try:
        return cast(object, getattr(value, attr))
    except Exception:
        _fail(name, label, f"bad field {attr}: unreadable")


def _exact(name: str, label: str, field: str, value: object, t: type, /) -> None:
    if type(value) is not t:
        _fail(name, label, f"bad field {field}: expected {_name(t)}, got {_name(type(value))}")


def _outer(name: str, label: str, value: object, t: type, /) -> None:
    if type(value) is not t:
        _fail(name, label, f"wrong result type: expected {_name(t)}, got {_name(type(value))}")


def _canonical_metadata(
    name: str, label: str, value: object, /
) -> tuple[str, tuple[str, ...], tuple[str, ...], datetime]:
    _exact(name, label, "metadata", value, FileMetadata)
    description = _get(name, label, value, "description")
    _exact(name, label, "description", description, str)
    aliases = _get(name, label, value, "aliases")
    _exact(name, label, "aliases", aliases, tuple)
    for i, alias in enumerate(cast(tuple[object, ...], aliases)):
        _exact(name, label, f"aliases[{i}]", alias, str)
    sources = _get(name, label, value, "sources")
    _exact(name, label, "sources", sources, frozenset)
    for source in cast(frozenset[object], sources):
        _exact(name, label, "sources member", source, str)
    last_updated = _get(name, label, value, "last_updated")
    _exact(name, label, "last_updated", last_updated, datetime)
    # Normalized to UTC so later comparison and formatting never call client tzinfo code.
    try:
        offset = cast(datetime, last_updated).utcoffset()
        if offset is None:
            _fail(name, label, "bad field last_updated: naive")
        utc = cast(datetime, last_updated).astimezone(UTC)
    except Exception:
        _fail(name, label, "bad field last_updated: offset unreadable")
    return (
        cast(str, description),
        cast(tuple[str, ...], aliases),
        tuple(sorted(cast(frozenset[str], sources))),
        utc,
    )


def canonical_file(name: str, label: str, value: object, /) -> CanonicalFile:
    """Check every field of a MemoryFile by exact type; return it as a plain tuple.

    The version is checked for shape only and is not part of the result.
    """
    _outer(name, label, value, MemoryFile)
    path = _get(name, label, value, "path")
    _exact(name, label, "path", path, str)
    content = _get(name, label, value, "content")
    _exact(name, label, "content", content, str)
    metadata = _get(name, label, value, "metadata")
    description, aliases, sources, last_updated = _canonical_metadata(name, label, metadata)
    v = _get(name, label, value, "version")
    if not (type(v) is str and v):
        _fail(name, label, "bad field version: not a non-empty str")
    return (cast(str, path), cast(str, content), description, aliases, sources, last_updated)


def canonical_entry(name: str, label: str, value: object, /) -> CanonicalEntry:
    """Check every field of a FileEntry by exact type; return it as a plain tuple.

    The version is checked for shape only and is not part of the result.
    """
    _outer(name, label, value, FileEntry)
    path = _get(name, label, value, "path")
    _exact(name, label, "path", path, str)
    if not is_valid_path(cast(str, path)):
        _fail(name, label, f"bad field path: {_short(path)} is not a valid path")
    metadata = _get(name, label, value, "metadata")
    description, aliases, sources, last_updated = _canonical_metadata(name, label, metadata)
    v = _get(name, label, value, "version")
    if not (type(v) is str and v):
        _fail(name, label, "bad field version: not a non-empty str")
    return (cast(str, path), description, aliases, sources, last_updated)


def _canonical_entries(name: str, label: str, value: object, /) -> tuple[CanonicalEntry, ...]:
    _exact(name, label, "entries", value, tuple)
    result: list[CanonicalEntry] = []
    for i, entry in enumerate(cast(tuple[object, ...], value)):
        _exact(name, label, f"entries[{i}]", entry, FileEntry)
        result.append(canonical_entry(name, label, entry))
    return tuple(result)


def canonical_page(name: str, label: str, value: object, /) -> CanonicalPage:
    """Check a ListPage by exact type; return (canonical entries, next_cursor is None)."""
    _outer(name, label, value, ListPage)
    entries = _canonical_entries(name, label, _get(name, label, value, "entries"))
    return (entries, _canonical_cursor(name, label, value))


def _canonical_cursor(name: str, label: str, page: object, /) -> bool:
    """Check a ListPage's next_cursor; return whether it is None."""
    cursor = _get(name, label, page, "next_cursor")
    if cursor is not None:
        _exact(name, label, "next_cursor", cursor, str)
    return cursor is None


def _index_parts(
    name: str, label: str, value: object, /
) -> tuple[
    tuple[object, ...], tuple[CanonicalEntry, ...], tuple[object, ...], tuple[tuple[str, int], ...]
]:
    """Check a MemoryIndex; return its raw and canonical entries and capped, each read once."""
    _outer(name, label, value, MemoryIndex)
    raw_entries = _get(name, label, value, "entries")
    entries = _canonical_entries(name, label, raw_entries)
    capped = _get(name, label, value, "capped")
    _exact(name, label, "capped", capped, tuple)
    result: list[tuple[str, int]] = []
    for i, cap in enumerate(cast(tuple[object, ...], capped)):
        _exact(name, label, f"capped[{i}]", cap, CappedPrefix)
        prefix = _get(name, label, cap, "prefix")
        _exact(name, label, f"capped[{i}].prefix", prefix, str)
        omitted = _get(name, label, cap, "omitted")
        _exact(name, label, f"capped[{i}].omitted", omitted, int)
        result.append((cast(str, prefix), cast(int, omitted)))
    return (
        cast(tuple[object, ...], raw_entries),
        entries,
        cast(tuple[object, ...], capped),
        tuple(result),
    )


def canonical_index(name: str, label: str, value: object, /) -> CanonicalIndex:
    """Check a MemoryIndex by exact type; return (canonical entries, ((prefix, omitted), ...))."""
    _, entries, _, capped = _index_parts(name, label, value)
    return (entries, capped)


# --- The suite ---------------------------------------------------------------


def _meta(
    description: str = "d", aliases: tuple[str, ...] = ("x", "y"), *, sources: frozenset[str]
) -> FileMetadata:
    return FileMetadata(description, aliases, sources, datetime(2000, 1, 1, tzinfo=UTC))


def _seed(source: str) -> str:
    return "s0" if source != "s0" else "s1"


def _write(name: str, label: str, fn: Callable[[], object], /) -> MemoryFile:
    """Run a write under _call and check its result is a well-formed MemoryFile."""
    result = _call(name, label, fn)
    canonical_file(name, label, result)
    return cast(MemoryFile, result)


def _read(name: str, label: str, fn: Callable[[], object], /) -> MemoryFile:
    """Run a read under _call and check its result is a well-formed MemoryFile."""
    result = _call(name, label, fn)
    canonical_file(name, label, result)
    return cast(MemoryFile, result)


def _conflict(
    name: str, label: str, fn: Callable[[], object], path: str, content: str, /
) -> VersionConflictError:
    """expect_error for a VersionConflictError carrying path and current content."""
    return expect_error(
        name, label, fn, VersionConflictError, _RECOVERABLE, path=path, content=content
    )


def _accepted(name: str, label: str, fn: Callable[[], object], /) -> object:
    """Run a call handing back a token; any Exception fails "token not accepted"."""
    try:
        return fn()
    except Exception as exc:
        _fail(name, label, f"token not accepted: raised {_name(type(exc))}")


def _expect_fields(
    name: str,
    label: str,
    phrase: str,
    got: CanonicalFile,
    expected: tuple[str, str, str, tuple[str, ...], tuple[str, ...]],
    /,
) -> None:
    """Fail with `phrase` naming the first of path, content, description, aliases, sources
    that differs from expected."""
    fields = ("path", "content", "description", "aliases", "sources")
    for i, field in enumerate(fields):
        if got[i] != expected[i]:
            _fail(
                name,
                label,
                f"{phrase}: {field} expected {_short(expected[i])}, got {_short(got[i])}",
            )


def _listed_entries(
    name: str, client: TransportClient, prefix: str, /
) -> tuple[tuple[FileEntry, CanonicalEntry], ...]:
    """Every entry under prefix, across all pages, raw and canonical."""
    label = f"list_prefix({prefix})"
    result: list[tuple[FileEntry, CanonicalEntry]] = []
    cursor: ListCursor | None = None
    for _ in range(_MAX_PAGES):
        page = cast(object, _call(name, label, lambda c=cursor: client.list_prefix(prefix, c)))
        _outer(name, label, page, ListPage)
        raw_entries = _get(name, label, page, "entries")
        canon = _canonical_entries(name, label, raw_entries)
        raw = cast(tuple[FileEntry, ...], raw_entries)
        result.extend(zip(raw, canon, strict=True))
        if _canonical_cursor(name, label, page):
            return tuple(result)
        cursor = cast(ListCursor, _get(name, label, page, "next_cursor"))
    _fail(name, label, f"pagination did not end within {_MAX_PAGES} pages")


def _round_trip(
    name: str,
    client: TransportClient,
    scopes: Mapping[str, str],
    src: str,
    content: str,
    description: str,
    aliases: tuple[str, ...],
    sources: frozenset[str],
    /,
) -> None:
    """Write the probe file, read it back; both results match and carry `src` in sources."""
    p = probe_path(name, _PROBE_LABEL, scopes, _first_scope(scopes), PROBE_AREA, PROBE_STEM)
    metadata = _meta(description, aliases, sources=sources)
    expected = (p, content, description, aliases, tuple(sorted(sources | {src})))
    written = _write(
        name,
        f"write_file({p})",
        lambda: client.write_file(p, content, metadata, None, source=src),
    )
    read = _read(name, f"read_file({p})", lambda: client.read_file(p))
    write_label = f"write result for {p}"
    read_label = f"read result for {p}"
    cw = canonical_file(name, write_label, written)
    cr = canonical_file(name, read_label, read)
    _expect_fields(name, write_label, "round trip changed", cw, expected)
    _expect_fields(name, read_label, "round trip changed", cr, expected)
    if cw[5] != cr[5]:
        _fail(name, read_label, f"round trip changed last_updated: wrote {cw[5]}, read {cr[5]}")


def _create_and_read(
    name: str, client: TransportClient, path: str, content: str, src: str, /
) -> MemoryFile:
    """Create path with content, then return a read of it."""
    metadata = _meta(sources=frozenset({_seed(src)}))
    _write(
        name,
        f"write_file({path})",
        lambda: client.write_file(path, content, metadata, None, source=src),
    )
    return _read(name, f"read_file({path})", lambda: client.read_file(path))


def _read_content(name: str, client: TransportClient, path: str, /) -> str:
    """Read path and return its content."""
    read = _read(name, f"read_file({path})", lambda: client.read_file(path))
    return canonical_file(name, f"read result for {path}", read)[1]


def _expect_content(
    name: str, client: TransportClient, path: str, phrase: str, want: str, /
) -> str:
    """Read path; fail with `phrase` unless its content equals want."""
    got = _read_content(name, client, path)
    if got != want:
        _fail(
            name, f"read result for {path}", f"{phrase}: expected {_short(want)}, got {_short(got)}"
        )
    return got


def _expect_once(name: str, label: str, content: str, line: str, /) -> None:
    """Fail "missing line" or "duplicated line" unless line occurs exactly once in content."""
    count = content.splitlines().count(line)
    if count == 0:
        _fail(name, label, f"missing line: {_short(line)} not in {_short(content)}")
    if count > 1:
        _fail(name, label, f"duplicated line: {_short(line)} occurs {count} times")


def _expect_absent(name: str, client: TransportClient, path: str, /) -> None:
    """read_file(path) raises NotFoundError with reason FILE_ABSENT."""
    expect_error(
        name,
        f"read_file({path})",
        lambda: client.read_file(path),
        NotFoundError,
        _RECOVERABLE,
        path=path,
        reason=_FILE_ABSENT,
    )


def _create(
    name: str, client: TransportClient, path: str, metadata: FileMetadata, src: str, /
) -> None:
    """Create path with a one-fact content and the given metadata."""
    _write(
        name,
        f"write_file({path})",
        lambda: client.write_file(path, "- [stated] a\n", metadata, None, source=src),
    )


def _tier(priority: tuple[str, ...], scope: str, /) -> int:
    """core's non-system tier of scope: its scope_priority position, or one trailing tier."""
    return priority.index(scope) if scope in priority else len(priority)


def _entry_bytes(name: str, label: str, entries: Iterable[FileEntry], /) -> tuple[int, ...]:
    """index_entry_bytes of each client-returned entry."""
    return tuple(_call(name, label, lambda e=e: index_entry_bytes(e)) for e in entries)


def _replay_cap(
    sentinel: str,
    written: list[str],
    sizes: Mapping[str, int],
    priority: tuple[str, ...],
    budget: int,
    /,
) -> tuple[list[str], list[str]]:
    """core's cap over the sentinel and written non-system paths: (full order, included prefix)."""
    # The sentinel was written first, so it is the oldest entry in its tier.
    recency = {path: i for i, path in enumerate([sentinel, *written])}
    replay = sorted(
        recency,
        key=lambda path: (_tier(priority, parse_path(path).scope), -recency[path]),
    )
    included: list[str] = []
    total = 0
    for path in replay:
        if total + sizes[path] > budget:
            break
        included.append(path)
        total += sizes[path]
    return replay, included


def _area_prefix(path: str, /) -> str:
    parts = parse_path(path)
    return build_prefix(parts.scope, parts.entity_id, parts.area)


def _first_page(
    name: str, client: TransportClient, prefix: str, size: int, /
) -> tuple[ListPage, CanonicalPage]:
    """List prefix's first page; fail unless it is full and carries a next_cursor."""
    label = f"list_prefix({prefix})"
    page = cast(object, _call(name, label, lambda: client.list_prefix(prefix)))
    canon = canonical_page(name, label, page)
    if len(canon[0]) != size:
        _fail(name, label, f"wrong page size: expected {size} entries, got {len(canon[0])}")
    if canon[1]:
        _fail(name, label, f"missing cursor: a full first page of {size} has next_cursor None")
    return cast(ListPage, page), canon


class TransportConformance:
    """Tests every TransportClient must pass. Subclass with a Test* name and supply fixtures."""

    def test_client_satisfies_protocol(
        self,
        client: TransportClient,
        source: str,
        scope_map: Mapping[str, str],
        max_file_bytes: int,
        index_max_bytes: int,
        scope_priority: tuple[str, ...],
        list_page_size: int,
    ) -> None:
        """Every fixture is valid and the client exposes the seven TransportClient methods."""
        name = _name(type(client))
        check_client(name, client)
        check_source(name, source)
        check_scope_map(name, scope_map)
        check_positive_int(name, "max_file_bytes", max_file_bytes, MIN_FILE_BYTES)
        check_positive_int(name, "index_max_bytes", index_max_bytes)
        check_scope_priority(name, scope_priority)
        check_positive_int(name, "list_page_size", list_page_size)

    def test_write_then_read_round_trips(
        self, client: TransportClient, source: str, scope_map: Mapping[str, str]
    ) -> None:
        """Content and all four metadata fields survive write-then-read; source is stamped."""
        name = _name(type(client))
        check_client(name, client)
        src = check_source(name, source)
        scopes = check_scope_map(name, scope_map)
        require_fresh(name, client, scopes)
        p = probe_path(name, _PROBE_LABEL, scopes, _first_scope(scopes), PROBE_AREA, PROBE_STEM)
        content = "- [stated] a\n"
        seed = _seed(src)
        metadata = _meta(sources=frozenset({seed}))
        expected = (p, content, "d", ("x", "y"), tuple(sorted({seed, src})))
        written = _call(
            name,
            f"write_file({p})",
            lambda: client.write_file(p, content, metadata, None, source=src),
        )
        read = _call(name, f"read_file({p})", lambda: client.read_file(p))
        write_label = f"write result for {p}"
        read_label = f"read result for {p}"
        cw = canonical_file(name, write_label, written)
        cr = canonical_file(name, read_label, read)
        fields = ("path", "content", "description", "aliases")
        for label, c in ((write_label, cw), (read_label, cr)):
            if c[4] != expected[4]:
                _fail(
                    name,
                    label,
                    f"source not stamped: sources are {c[4]}, expected {expected[4]}",
                )
            for i, field in enumerate(fields):
                if c[i] != expected[i]:
                    _fail(
                        name,
                        label,
                        f"round trip changed {field}: expected {_short(expected[i])}, "
                        f"got {_short(c[i])}",
                    )
        if cw[5] != cr[5]:
            _fail(
                name,
                read_label,
                f"round trip changed last_updated: wrote {cw[5]}, read {cr[5]}",
            )

    def test_returned_token_is_accepted(
        self, client: TransportClient, source: str, scope_map: Mapping[str, str]
    ) -> None:
        """A version token the client returned is accepted back as expected_version."""
        name = _name(type(client))
        check_client(name, client)
        src = check_source(name, source)
        scopes = check_scope_map(name, scope_map)
        require_fresh(name, client, scopes)
        first = _first_scope(scopes)
        p = probe_path(name, _PROBE_LABEL, scopes, first, PROBE_AREA, PROBE_STEM)
        q = probe_path(name, _PROBE_LABEL, scopes, first, PROBE_AREA, PROBE_STEM_2)
        metadata = _meta(sources=frozenset({_seed(src)}))
        written = _call(
            name,
            f"write_file({p})",
            lambda: client.write_file(p, "- [stated] a\n", metadata, None, source=src),
        )
        canonical_file(name, f"write result for {p}", written)
        read = _call(name, f"read_file({p})", lambda: client.read_file(p))
        read_label = f"read result for {p}"
        canonical_file(name, read_label, read)
        read_metadata = cast(FileMetadata, _get(name, read_label, read, "metadata"))
        token = cast(VersionToken, _get(name, read_label, read, "version"))
        try:
            rewritten = client.write_file(p, "- [stated] b\n", read_metadata, token, source=src)
        except Exception as exc:
            _fail(name, f"write_file({p})", f"token not accepted: raised {_name(type(exc))}")
        canonical_file(name, f"write result for {p}", rewritten)
        created = _call(
            name,
            f"write_file({q})",
            lambda: client.write_file(q, "- [stated] q\n", metadata, None, source=src),
        )
        created_label = f"write result for {q}"
        canonical_file(name, created_label, created)
        created_token = cast(VersionToken, _get(name, created_label, created, "version"))
        try:
            appended = client.append_line(q, "- [stated] c", created_token, source=src)
        except Exception as exc:
            _fail(name, f"append_line({q})", f"token not accepted: raised {_name(type(exc))}")
        canonical_file(name, f"append result for {q}", appended)

    def test_read_absent_is_not_found(
        self, client: TransportClient, scope_map: Mapping[str, str]
    ) -> None:
        """Reading an absent file raises NotFoundError with reason FILE_ABSENT."""
        name = _name(type(client))
        check_client(name, client)
        scopes = check_scope_map(name, scope_map)
        require_fresh(name, client, scopes)
        p = probe_path(name, _PROBE_LABEL, scopes, _first_scope(scopes), PROBE_AREA, PROBE_STEM)
        expect_error(
            name,
            f"read_file({p})",
            lambda: client.read_file(p),
            NotFoundError,
            _RECOVERABLE,
            path=p,
            reason=_FILE_ABSENT,
        )

    def test_oversize_write_is_rejected(
        self,
        client: TransportClient,
        source: str,
        scope_map: Mapping[str, str],
        max_file_bytes: int,
    ) -> None:
        """A write one byte over max_file_bytes raises OversizeWriteError and stores nothing."""
        name = _name(type(client))
        check_client(name, client)
        src = check_source(name, source)
        scopes = check_scope_map(name, scope_map)
        limit = check_positive_int(name, "max_file_bytes", max_file_bytes, MIN_FILE_BYTES)
        require_fresh(name, client, scopes)
        p = probe_path(name, _PROBE_LABEL, scopes, _first_scope(scopes), PROBE_AREA, PROBE_STEM)
        size = limit + 1
        metadata = _meta(sources=frozenset({_seed(src)}))
        expect_error(
            name,
            f"write_file({p})",
            lambda: client.write_file(p, "x" * size, metadata, None, source=src),
            OversizeWriteError,
            _RECOVERABLE,
            path=p,
            size=size,
            limit=limit,
        )
        expect_error(
            name,
            f"read_file({p})",
            lambda: client.read_file(p),
            NotFoundError,
            _RECOVERABLE,
            path=p,
            reason=_FILE_ABSENT,
        )

    # --- Round-trip fidelity ---------------------------------------------------

    def test_round_trip_unicode_content_and_metadata(
        self, client: TransportClient, source: str, scope_map: Mapping[str, str]
    ) -> None:
        """Non-ASCII content, description, and aliases survive write-then-read unchanged."""
        name = _name(type(client))
        check_client(name, client)
        src = check_source(name, source)
        scopes = check_scope_map(name, scope_map)
        require_fresh(name, client, scopes)
        _round_trip(
            name,
            client,
            scopes,
            src,
            "- [stated] café ☕ 日本語 \U0001f600\n",
            "déjà vu",
            ("ñ", "日本"),
            frozenset({_seed(src)}),
        )

    def test_round_trip_markdown_resembling_fact_syntax(
        self, client: TransportClient, source: str, scope_map: Mapping[str, str]
    ) -> None:
        """Content with near-fact lines, a blank line, and a code fence survives byte-for-byte."""
        name = _name(type(client))
        check_client(name, client)
        src = check_source(name, source)
        scopes = check_scope_map(name, scope_map)
        require_fresh(name, client, scopes)
        content = "- [shouted] x\n- stated y\n[stated] z\n\n```\n- [stated] fenced\n```\n"
        _round_trip(name, client, scopes, src, content, "d", ("x", "y"), frozenset({_seed(src)}))

    def test_round_trip_content_without_trailing_newline(
        self, client: TransportClient, source: str, scope_map: Mapping[str, str]
    ) -> None:
        """Content lacking a trailing newline survives unchanged."""
        name = _name(type(client))
        check_client(name, client)
        src = check_source(name, source)
        scopes = check_scope_map(name, scope_map)
        require_fresh(name, client, scopes)
        _round_trip(
            name, client, scopes, src, "- [stated] a", "d", ("x", "y"), frozenset({_seed(src)})
        )

    def test_round_trip_empty_content(
        self, client: TransportClient, source: str, scope_map: Mapping[str, str]
    ) -> None:
        """Empty content survives unchanged."""
        name = _name(type(client))
        check_client(name, client)
        src = check_source(name, source)
        scopes = check_scope_map(name, scope_map)
        require_fresh(name, client, scopes)
        _round_trip(name, client, scopes, src, "", "d", ("x", "y"), frozenset({_seed(src)}))

    def test_round_trip_empty_aliases_and_many_sources(
        self, client: TransportClient, source: str, scope_map: Mapping[str, str]
    ) -> None:
        """Empty aliases and several sources survive; source is added to them."""
        name = _name(type(client))
        check_client(name, client)
        src = check_source(name, source)
        scopes = check_scope_map(name, scope_map)
        require_fresh(name, client, scopes)
        seed = _seed(src)
        sources = frozenset({seed, seed + "-b", seed + "-c"})
        _round_trip(name, client, scopes, src, "- [stated] a\n", "d", (), sources)

    def test_write_replace_round_trips(
        self, client: TransportClient, source: str, scope_map: Mapping[str, str]
    ) -> None:
        """A replace stores new content, description, and aliases; sources accumulate."""
        name = _name(type(client))
        check_client(name, client)
        src = check_source(name, source)
        scopes = check_scope_map(name, scope_map)
        require_fresh(name, client, scopes)
        p = probe_path(name, _PROBE_LABEL, scopes, _first_scope(scopes), PROBE_AREA, PROBE_STEM)
        seed = _seed(src)
        seed2 = seed + "-2"
        created_meta = _meta(sources=frozenset({seed}))
        replaced_meta = _meta("d2", ("z",), sources=frozenset({seed2}))
        write_label = f"write_file({p})"
        _write(
            name,
            write_label,
            lambda: client.write_file(p, "- [stated] a\n", created_meta, None, source=src),
        )
        r1 = _read(name, f"read_file({p})", lambda: client.read_file(p))
        _write(
            name,
            write_label,
            lambda: client.write_file(p, "- [stated] b\n", replaced_meta, r1.version, source=src),
        )
        read = _read(name, f"read_file({p})", lambda: client.read_file(p))
        read_label = f"read result for {p}"
        expected = (p, "- [stated] b\n", "d2", ("z",), tuple(sorted({seed, seed2, src})))
        _expect_fields(
            name, read_label, "round trip changed", canonical_file(name, read_label, read), expected
        )

    # --- Atomicity -------------------------------------------------------------

    def test_failed_replace_leaves_content_and_metadata_together(
        self, client: TransportClient, source: str, scope_map: Mapping[str, str]
    ) -> None:
        """A replace rejected for a stale token changes neither content nor metadata."""
        name = _name(type(client))
        check_client(name, client)
        src = check_source(name, source)
        scopes = check_scope_map(name, scope_map)
        require_fresh(name, client, scopes)
        p = probe_path(name, _PROBE_LABEL, scopes, _first_scope(scopes), PROBE_AREA, PROBE_STEM)
        seed = _seed(src)
        meta_a = _meta("dA", sources=frozenset({seed}))
        meta_b = _meta("dB", sources=frozenset({seed}))
        meta_c = _meta("dC", sources=frozenset({seed}))
        content_b = "- [stated] b\n"
        write_label = f"write_file({p})"
        _write(
            name,
            write_label,
            lambda: client.write_file(p, "- [stated] a\n", meta_a, None, source=src),
        )
        r1 = _read(name, f"read_file({p})", lambda: client.read_file(p))
        _write(
            name,
            write_label,
            lambda: client.write_file(p, content_b, meta_b, r1.version, source=src),
        )
        _conflict(
            name,
            write_label,
            lambda: client.write_file(p, "- [stated] c\n", meta_c, r1.version, source=src),
            p,
            content_b,
        )
        read = _read(name, f"read_file({p})", lambda: client.read_file(p))
        read_label = f"read result for {p}"
        expected = (p, content_b, "dB", ("x", "y"), tuple(sorted({seed, src})))
        _expect_fields(
            name, read_label, "wrong content", canonical_file(name, read_label, read), expected
        )

    def test_delete_removes_content_and_metadata_together(
        self, client: TransportClient, source: str, scope_map: Mapping[str, str]
    ) -> None:
        """After a delete the file neither reads nor lists."""
        name = _name(type(client))
        check_client(name, client)
        src = check_source(name, source)
        scopes = check_scope_map(name, scope_map)
        require_fresh(name, client, scopes)
        first = _first_scope(scopes)
        p = probe_path(name, _PROBE_LABEL, scopes, first, PROBE_AREA, PROBE_STEM)
        metadata = _meta(sources=frozenset({_seed(src)}))
        _write(
            name,
            f"write_file({p})",
            lambda: client.write_file(p, "- [stated] a\n", metadata, None, source=src),
        )
        r = _read(name, f"read_file({p})", lambda: client.read_file(p))
        delete_label = f"delete_file({p})"
        deleted = cast(object, _call(name, delete_label, lambda: client.delete_file(p, r.version)))
        if deleted is not None:
            _fail(
                name, delete_label, f"wrong result type: expected None, got {_name(type(deleted))}"
            )
        expect_error(
            name,
            f"read_file({p})",
            lambda: client.read_file(p),
            NotFoundError,
            _RECOVERABLE,
            path=p,
            reason=_FILE_ABSENT,
        )
        prefix = build_prefix(first, scopes[first], PROBE_AREA)
        if any(c[0] == p for _, c in _listed_entries(name, client, prefix)):
            _fail(name, f"list_prefix({prefix})", f"deleted file still listed: {p}")

    def test_append_updates_content_and_last_updated_together(
        self, client: TransportClient, source: str, scope_map: Mapping[str, str]
    ) -> None:
        """An append changes content, advances last_updated, and stamps source."""
        name = _name(type(client))
        check_client(name, client)
        src = check_source(name, source)
        scopes = check_scope_map(name, scope_map)
        require_fresh(name, client, scopes)
        p = probe_path(name, _PROBE_LABEL, scopes, _first_scope(scopes), PROBE_AREA, PROBE_STEM)
        metadata = _meta(sources=frozenset({_seed(src)}))
        _write(
            name,
            f"write_file({p})",
            lambda: client.write_file(p, "- [stated] a\n", metadata, None, source=src),
        )
        read_label = f"read result for {p}"
        r1 = _read(name, f"read_file({p})", lambda: client.read_file(p))
        before = canonical_file(name, read_label, r1)
        _write(
            name,
            f"append_line({p})",
            lambda: client.append_line(p, "- [stated] b", r1.version, source=src),
        )
        r2 = _read(name, f"read_file({p})", lambda: client.read_file(p))
        after = canonical_file(name, read_label, r2)
        want = "- [stated] a\n- [stated] b\n"
        if after[1] != want:
            _fail(
                name, read_label, f"wrong content: expected {_short(want)}, got {_short(after[1])}"
            )
        if not before[5] < after[5]:
            _fail(
                name,
                read_label,
                f"last_updated not later after append: before {before[5]}, after {after[5]}",
            )
        if src not in after[4]:
            _fail(name, read_label, f"source not stamped: sources are {after[4]}")

    # --- Version token opacity -------------------------------------------------

    def test_tokens_from_every_operation_are_accepted(
        self, client: TransportClient, source: str, scope_map: Mapping[str, str]
    ) -> None:
        """Tokens from write, append, replace_fact, read, and list are each accepted back."""
        name = _name(type(client))
        check_client(name, client)
        src = check_source(name, source)
        scopes = check_scope_map(name, scope_map)
        require_fresh(name, client, scopes)
        first = _first_scope(scopes)
        p = probe_path(name, _PROBE_LABEL, scopes, first, PROBE_AREA, PROBE_STEM)
        metadata = _meta(sources=frozenset({_seed(src)}))
        write_label = f"write_file({p})"
        append_label = f"append_line({p})"
        written = _write(
            name,
            write_label,
            lambda: client.write_file(p, "- [stated] alpha\n", metadata, None, source=src),
        )
        appended = _accepted(
            name,
            append_label,
            lambda: client.append_line(p, "- [stated] beta", written.version, source=src),
        )
        canonical_file(name, f"append result for {p}", appended)
        after_append = cast(MemoryFile, appended)
        replace_label = f"replace_fact({p})"
        replaced = _accepted(
            name,
            replace_label,
            lambda: client.replace_fact(p, "beta", "gamma", after_append.version, source=src),
        )
        canonical_file(name, f"replace result for {p}", replaced)
        after_replace = cast(MemoryFile, replaced)
        rewritten = _accepted(
            name,
            write_label,
            lambda: client.write_file(
                p, "- [stated] delta\n", metadata, after_replace.version, source=src
            ),
        )
        canonical_file(name, f"write result for {p}", rewritten)
        read = _read(name, f"read_file({p})", lambda: client.read_file(p))
        appended_again = _accepted(
            name,
            append_label,
            lambda: client.append_line(p, "- [stated] epsilon", read.version, source=src),
        )
        canonical_file(name, f"append result for {p}", appended_again)
        prefix = build_prefix(first, scopes[first], PROBE_AREA)
        matches = [e for e, c in _listed_entries(name, client, prefix) if c[0] == p]
        if len(matches) != 1:
            _fail(name, f"list_prefix({prefix})", f"expected one entry for {p}, got {len(matches)}")
        entry = matches[0]
        delete_label = f"delete_file({p})"
        deleted = _accepted(name, delete_label, lambda: client.delete_file(p, entry.version))
        if deleted is not None:
            _fail(
                name, delete_label, f"wrong result type: expected None, got {_name(type(deleted))}"
            )

    def test_index_entry_tokens_are_accepted(
        self, client: TransportClient, source: str, scope_map: Mapping[str, str]
    ) -> None:
        """The token on a get_memory_index entry is accepted by delete_file."""
        name = _name(type(client))
        check_client(name, client)
        src = check_source(name, source)
        scopes = check_scope_map(name, scope_map)
        require_fresh(name, client, scopes)
        p = probe_path(name, _PROBE_LABEL, scopes, _first_scope(scopes), PROBE_AREA, PROBE_STEM)
        metadata = _meta(sources=frozenset({_seed(src)}))
        _write(
            name,
            f"write_file({p})",
            lambda: client.write_file(p, "- [stated] a\n", metadata, None, source=src),
        )
        index_label = "get_memory_index result"
        index = cast(
            object,
            _call(name, "get_memory_index(scope_map)", lambda: client.get_memory_index(scopes)),
        )
        raw_entries, canon_entries, _, _ = _index_parts(name, index_label, index)
        matches = [
            cast(FileEntry, e) for e, c in zip(raw_entries, canon_entries, strict=True) if c[0] == p
        ]
        if len(matches) != 1:
            _fail(name, index_label, f"expected one entry for {p}, got {len(matches)}")
        entry = matches[0]
        delete_label = f"delete_file({p})"
        deleted = _accepted(name, delete_label, lambda: client.delete_file(p, entry.version))
        if deleted is not None:
            _fail(
                name, delete_label, f"wrong result type: expected None, got {_name(type(deleted))}"
            )
        expect_error(
            name,
            f"read_file({p})",
            lambda: client.read_file(p),
            NotFoundError,
            _RECOVERABLE,
            path=p,
            reason=_FILE_ABSENT,
        )

    # --- Conflict semantics ----------------------------------------------------

    def test_stale_write_conflicts_with_current_content(
        self, client: TransportClient, source: str, scope_map: Mapping[str, str]
    ) -> None:
        """A stale-token write conflicts with the current content; the carried token is accepted."""
        name = _name(type(client))
        check_client(name, client)
        src = check_source(name, source)
        scopes = check_scope_map(name, scope_map)
        require_fresh(name, client, scopes)
        p = probe_path(name, _PROBE_LABEL, scopes, _first_scope(scopes), PROBE_AREA, PROBE_STEM)
        metadata = _meta(sources=frozenset({_seed(src)}))
        content_b = "- [stated] b\n"
        content_c = "- [stated] c\n"
        write_label = f"write_file({p})"
        r1 = _create_and_read(name, client, p, "- [stated] a\n", src)
        _write(
            name,
            write_label,
            lambda: client.write_file(p, content_b, metadata, r1.version, source=src),
        )
        observed = _read_content(name, client, p)
        exc = _conflict(
            name,
            write_label,
            lambda: client.write_file(p, content_c, metadata, r1.version, source=src),
            p,
            observed,
        )
        retried = _accepted(
            name,
            write_label,
            lambda: client.write_file(p, content_c, metadata, exc.version, source=src),
        )
        canonical_file(name, f"write result for {p}", retried)
        _expect_content(name, client, p, "wrong content", content_c)

    def test_create_on_existing_path_conflicts(
        self, client: TransportClient, source: str, scope_map: Mapping[str, str]
    ) -> None:
        """A create (no token) on an existing path conflicts and leaves the content alone."""
        name = _name(type(client))
        check_client(name, client)
        src = check_source(name, source)
        scopes = check_scope_map(name, scope_map)
        require_fresh(name, client, scopes)
        p = probe_path(name, _PROBE_LABEL, scopes, _first_scope(scopes), PROBE_AREA, PROBE_STEM)
        metadata = _meta(sources=frozenset({_seed(src)}))
        read = _create_and_read(name, client, p, "- [stated] a\n", src)
        observed = canonical_file(name, f"read result for {p}", read)[1]
        _conflict(
            name,
            f"write_file({p})",
            lambda: client.write_file(p, "- [stated] b\n", metadata, None, source=src),
            p,
            observed,
        )
        _expect_content(name, client, p, "content changed", observed)

    def test_write_with_token_on_absent_path_is_not_found(
        self, client: TransportClient, source: str, scope_map: Mapping[str, str]
    ) -> None:
        """A guarded write to an absent path raises NotFoundError with reason FILE_ABSENT."""
        name = _name(type(client))
        check_client(name, client)
        src = check_source(name, source)
        scopes = check_scope_map(name, scope_map)
        require_fresh(name, client, scopes)
        p = probe_path(name, _PROBE_LABEL, scopes, _first_scope(scopes), PROBE_AREA, PROBE_STEM)
        metadata = _meta(sources=frozenset({_seed(src)}))
        expect_error(
            name,
            f"write_file({p})",
            lambda: client.write_file(p, "- [stated] a\n", metadata, _ABSENT_TOKEN, source=src),
            NotFoundError,
            _RECOVERABLE,
            path=p,
            reason=_FILE_ABSENT,
        )
        _expect_absent(name, client, p)

    def test_stale_delete_conflicts(
        self, client: TransportClient, source: str, scope_map: Mapping[str, str]
    ) -> None:
        """A delete with a stale token conflicts and keeps the file; the carried token deletes."""
        name = _name(type(client))
        check_client(name, client)
        src = check_source(name, source)
        scopes = check_scope_map(name, scope_map)
        require_fresh(name, client, scopes)
        p = probe_path(name, _PROBE_LABEL, scopes, _first_scope(scopes), PROBE_AREA, PROBE_STEM)
        metadata = _meta(sources=frozenset({_seed(src)}))
        delete_label = f"delete_file({p})"
        r1 = _create_and_read(name, client, p, "- [stated] a\n", src)
        _write(
            name,
            f"write_file({p})",
            lambda: client.write_file(p, "- [stated] b\n", metadata, r1.version, source=src),
        )
        observed = _read_content(name, client, p)
        exc = _conflict(name, delete_label, lambda: client.delete_file(p, r1.version), p, observed)
        _expect_content(name, client, p, "content changed", observed)
        deleted = _accepted(name, delete_label, lambda: client.delete_file(p, exc.version))
        if deleted is not None:
            _fail(
                name, delete_label, f"wrong result type: expected None, got {_name(type(deleted))}"
            )
        _expect_absent(name, client, p)

    def test_delete_absent_is_not_found(
        self, client: TransportClient, scope_map: Mapping[str, str]
    ) -> None:
        """Deleting an absent path raises NotFoundError with reason FILE_ABSENT."""
        name = _name(type(client))
        check_client(name, client)
        scopes = check_scope_map(name, scope_map)
        require_fresh(name, client, scopes)
        p = probe_path(name, _PROBE_LABEL, scopes, _first_scope(scopes), PROBE_AREA, PROBE_STEM)
        expect_error(
            name,
            f"delete_file({p})",
            lambda: client.delete_file(p, _ABSENT_TOKEN),
            NotFoundError,
            _RECOVERABLE,
            path=p,
            reason=_FILE_ABSENT,
        )

    # --- Replace-fact matching -------------------------------------------------

    def test_replace_fact_unique_match_succeeds(
        self, client: TransportClient, source: str, scope_map: Mapping[str, str]
    ) -> None:
        """A uniquely matching old_string is replaced; other lines are kept."""
        name = _name(type(client))
        check_client(name, client)
        src = check_source(name, source)
        scopes = check_scope_map(name, scope_map)
        require_fresh(name, client, scopes)
        p = probe_path(name, _PROBE_LABEL, scopes, _first_scope(scopes), PROBE_AREA, PROBE_STEM)
        r = _create_and_read(name, client, p, _FACTS, src)
        _write(
            name,
            f"replace_fact({p})",
            lambda: client.replace_fact(p, "beta", "gamma", r.version, source=src),
        )
        want = "- [stated] alpha\n- [stated] gamma\n- [stated] alpha\n"
        _expect_content(name, client, p, "wrong content", want)

    def test_replace_fact_zero_matches_rejected(
        self, client: TransportClient, source: str, scope_map: Mapping[str, str]
    ) -> None:
        """An old_string matching nothing raises ReplaceFactMatchError with match_count 0."""
        name = _name(type(client))
        check_client(name, client)
        src = check_source(name, source)
        scopes = check_scope_map(name, scope_map)
        require_fresh(name, client, scopes)
        p = probe_path(name, _PROBE_LABEL, scopes, _first_scope(scopes), PROBE_AREA, PROBE_STEM)
        r = _create_and_read(name, client, p, _FACTS, src)
        observed = canonical_file(name, f"read result for {p}", r)[1]
        expect_error(
            name,
            f"replace_fact({p})",
            lambda: client.replace_fact(p, "delta", "gamma", r.version, source=src),
            ReplaceFactMatchError,
            _RECOVERABLE,
            path=p,
            content=observed,
            match_count=0,
        )
        _expect_content(name, client, p, "content changed", observed)

    def test_replace_fact_multiple_matches_rejected(
        self, client: TransportClient, source: str, scope_map: Mapping[str, str]
    ) -> None:
        """An old_string matching twice raises ReplaceFactMatchError with match_count 2."""
        name = _name(type(client))
        check_client(name, client)
        src = check_source(name, source)
        scopes = check_scope_map(name, scope_map)
        require_fresh(name, client, scopes)
        p = probe_path(name, _PROBE_LABEL, scopes, _first_scope(scopes), PROBE_AREA, PROBE_STEM)
        r = _create_and_read(name, client, p, _FACTS, src)
        observed = canonical_file(name, f"read result for {p}", r)[1]
        expect_error(
            name,
            f"replace_fact({p})",
            lambda: client.replace_fact(p, "alpha", "gamma", r.version, source=src),
            ReplaceFactMatchError,
            _RECOVERABLE,
            path=p,
            content=observed,
            match_count=2,
        )
        _expect_content(name, client, p, "content changed", observed)

    def test_replace_fact_stale_token_unique_match_reapplies(
        self, client: TransportClient, source: str, scope_map: Mapping[str, str]
    ) -> None:
        """With a stale token, a match still unique in the current content is re-applied."""
        name = _name(type(client))
        check_client(name, client)
        src = check_source(name, source)
        scopes = check_scope_map(name, scope_map)
        require_fresh(name, client, scopes)
        p = probe_path(name, _PROBE_LABEL, scopes, _first_scope(scopes), PROBE_AREA, PROBE_STEM)
        r1 = _create_and_read(name, client, p, _FACTS, src)
        _write(
            name,
            f"append_line({p})",
            lambda: client.append_line(p, "- [stated] delta", r1.version, source=src),
        )
        _write(
            name,
            f"replace_fact({p})",
            lambda: client.replace_fact(p, "beta", "gamma", r1.version, source=src),
        )
        want = "- [stated] alpha\n- [stated] gamma\n- [stated] alpha\n- [stated] delta\n"
        _expect_content(name, client, p, "wrong content", want)

    def test_replace_fact_stale_token_non_unique_conflicts(
        self, client: TransportClient, source: str, scope_map: Mapping[str, str]
    ) -> None:
        """With a stale token, a match no longer unique in the current content conflicts."""
        name = _name(type(client))
        check_client(name, client)
        src = check_source(name, source)
        scopes = check_scope_map(name, scope_map)
        require_fresh(name, client, scopes)
        p = probe_path(name, _PROBE_LABEL, scopes, _first_scope(scopes), PROBE_AREA, PROBE_STEM)
        replace_label = f"replace_fact({p})"
        r1 = _create_and_read(name, client, p, _FACTS, src)
        _write(
            name,
            replace_label,
            lambda: client.replace_fact(p, "beta", "alpha", r1.version, source=src),
        )
        observed = _read_content(name, client, p)
        _conflict(
            name,
            replace_label,
            lambda: client.replace_fact(p, "beta", "x", r1.version, source=src),
            p,
            observed,
        )
        _expect_content(name, client, p, "content changed", observed)

    def test_replace_fact_empty_old_string_is_value_error(
        self, client: TransportClient, source: str, scope_map: Mapping[str, str]
    ) -> None:
        """An empty old_string raises ValueError with core's message and changes nothing."""
        name = _name(type(client))
        check_client(name, client)
        src = check_source(name, source)
        scopes = check_scope_map(name, scope_map)
        require_fresh(name, client, scopes)
        p = probe_path(name, _PROBE_LABEL, scopes, _first_scope(scopes), PROBE_AREA, PROBE_STEM)
        r = _create_and_read(name, client, p, _FACTS, src)
        observed = canonical_file(name, f"read result for {p}", r)[1]
        expect_error(
            name,
            f"replace_fact({p})",
            lambda: client.replace_fact(p, "", "gamma", r.version, source=src),
            ValueError,
            None,
            message=MSG_REPLACE_ARGS,
        )
        _expect_content(name, client, p, "content changed", observed)

    # --- Append guarding -------------------------------------------------------

    def test_concurrent_appends_one_lands_one_conflicts(
        self, client: TransportClient, source: str, scope_map: Mapping[str, str]
    ) -> None:
        """Of two appends at the same token, one lands and one conflicts; the retry lands once."""
        name = _name(type(client))
        check_client(name, client)
        src = check_source(name, source)
        scopes = check_scope_map(name, scope_map)
        require_fresh(name, client, scopes)
        p = probe_path(name, _PROBE_LABEL, scopes, _first_scope(scopes), PROBE_AREA, PROBE_STEM)
        append_label = f"append_line({p})"
        one = "- [stated] one"
        two = "- [stated] two"
        r = _create_and_read(name, client, p, "- [stated] a\n", src)
        _write(name, append_label, lambda: client.append_line(p, one, r.version, source=src))
        observed = _read_content(name, client, p)
        exc = _conflict(
            name,
            append_label,
            lambda: client.append_line(p, two, r.version, source=src),
            p,
            observed,
        )
        retried = _accepted(
            name, append_label, lambda: client.append_line(p, two, exc.version, source=src)
        )
        canonical_file(name, f"append result for {p}", retried)
        content = _read_content(name, client, p)
        read_label = f"read result for {p}"
        _expect_once(name, read_label, content, one)
        _expect_once(name, read_label, content, two)
        want = f"- [stated] a\n{one}\n{two}\n"
        if content != want:
            _fail(
                name, read_label, f"wrong content: expected {_short(want)}, got {_short(content)}"
            )

    def test_retried_append_does_not_duplicate(
        self, client: TransportClient, source: str, scope_map: Mapping[str, str]
    ) -> None:
        """Repeating a landed append at its original token conflicts instead of duplicating."""
        name = _name(type(client))
        check_client(name, client)
        src = check_source(name, source)
        scopes = check_scope_map(name, scope_map)
        require_fresh(name, client, scopes)
        p = probe_path(name, _PROBE_LABEL, scopes, _first_scope(scopes), PROBE_AREA, PROBE_STEM)
        append_label = f"append_line({p})"
        one = "- [stated] one"
        r = _create_and_read(name, client, p, "- [stated] a\n", src)
        _write(name, append_label, lambda: client.append_line(p, one, r.version, source=src))
        observed = _read_content(name, client, p)
        _conflict(
            name,
            append_label,
            lambda: client.append_line(p, one, r.version, source=src),
            p,
            observed,
        )
        content = _read_content(name, client, p)
        _expect_once(name, f"read result for {p}", content, one)

    def test_append_inserts_separator_when_needed(
        self, client: TransportClient, source: str, scope_map: Mapping[str, str]
    ) -> None:
        """An append adds a newline before the line only if the content lacks one, and after it."""
        name = _name(type(client))
        check_client(name, client)
        src = check_source(name, source)
        scopes = check_scope_map(name, scope_map)
        require_fresh(name, client, scopes)
        first = _first_scope(scopes)
        p = probe_path(name, _PROBE_LABEL, scopes, first, PROBE_AREA, PROBE_STEM)
        q = probe_path(name, _PROBE_LABEL, scopes, first, PROBE_AREA, PROBE_STEM_2)
        want = "- [stated] a\n- [stated] b\n"
        rp = _create_and_read(name, client, p, "- [stated] a", src)
        _write(
            name,
            f"append_line({p})",
            lambda: client.append_line(p, "- [stated] b", rp.version, source=src),
        )
        _expect_content(name, client, p, "wrong content", want)
        rq = _create_and_read(name, client, q, "- [stated] a\n", src)
        _write(
            name,
            f"append_line({q})",
            lambda: client.append_line(q, "- [stated] b", rq.version, source=src),
        )
        _expect_content(name, client, q, "wrong content", want)

    def test_append_to_absent_file_is_not_found_and_creates_nothing(
        self, client: TransportClient, source: str, scope_map: Mapping[str, str]
    ) -> None:
        """Appending to an absent path raises NotFoundError (FILE_ABSENT) and creates nothing."""
        name = _name(type(client))
        check_client(name, client)
        src = check_source(name, source)
        scopes = check_scope_map(name, scope_map)
        require_fresh(name, client, scopes)
        p = probe_path(name, _PROBE_LABEL, scopes, _first_scope(scopes), PROBE_AREA, PROBE_STEM)
        expect_error(
            name,
            f"append_line({p})",
            lambda: client.append_line(p, "- [stated] a", _ABSENT_TOKEN, source=src),
            NotFoundError,
            _RECOVERABLE,
            path=p,
            reason=_FILE_ABSENT,
        )
        _expect_absent(name, client, p)

    def test_append_non_fact_line_is_value_error(
        self, client: TransportClient, source: str, scope_map: Mapping[str, str]
    ) -> None:
        """A non-fact or multi-line line raises ValueError with core's message; nothing changes."""
        name = _name(type(client))
        check_client(name, client)
        src = check_source(name, source)
        scopes = check_scope_map(name, scope_map)
        require_fresh(name, client, scopes)
        p = probe_path(name, _PROBE_LABEL, scopes, _first_scope(scopes), PROBE_AREA, PROBE_STEM)
        r = _create_and_read(name, client, p, "- [stated] a\n", src)
        observed = canonical_file(name, f"read result for {p}", r)[1]
        for line in ("not a fact", "- [stated] a\n- [stated] b"):
            expect_error(
                name,
                f"append_line({p})",
                lambda line=line: client.append_line(p, line, r.version, source=src),
                ValueError,
                None,
                message=MSG_APPEND_ARGS,
            )
        _expect_content(name, client, p, "content changed", observed)

    # --- Enforcement -----------------------------------------------------------

    def test_oversize_append_is_rejected(
        self,
        client: TransportClient,
        source: str,
        scope_map: Mapping[str, str],
        max_file_bytes: int,
    ) -> None:
        """An append pushing the UTF-8 size over max_file_bytes is rejected; nothing changes."""
        name = _name(type(client))
        check_client(name, client)
        src = check_source(name, source)
        scopes = check_scope_map(name, scope_map)
        limit = check_positive_int(name, "max_file_bytes", max_file_bytes, MIN_FILE_BYTES)
        require_fresh(name, client, scopes)
        p = probe_path(name, _PROBE_LABEL, scopes, _first_scope(scopes), PROBE_AREA, PROBE_STEM)
        # 11 bytes of prefix, 3 per character, 1 for the newline: at most `limit` bytes.
        content = "- [stated] " + "日" * ((limit - 12) // 3) + "\n"
        line = "- [stated] é"
        separator = "\n" if content and not content.endswith("\n") else ""
        size = len((content + separator + line + "\n").encode("utf-8"))
        r = _create_and_read(name, client, p, content, src)
        expect_error(
            name,
            f"append_line({p})",
            lambda: client.append_line(p, line, r.version, source=src),
            OversizeWriteError,
            _RECOVERABLE,
            path=p,
            size=size,
            limit=limit,
        )
        _expect_content(name, client, p, "content changed", content)

    def test_oversize_replace_fact_is_rejected(
        self,
        client: TransportClient,
        source: str,
        scope_map: Mapping[str, str],
        max_file_bytes: int,
    ) -> None:
        """A replace_fact taking the UTF-8 size over max_file_bytes is rejected; nothing changes."""
        name = _name(type(client))
        check_client(name, client)
        src = check_source(name, source)
        scopes = check_scope_map(name, scope_map)
        limit = check_positive_int(name, "max_file_bytes", max_file_bytes, MIN_FILE_BYTES)
        require_fresh(name, client, scopes)
        p = probe_path(name, _PROBE_LABEL, scopes, _first_scope(scopes), PROBE_AREA, PROBE_STEM)
        anchor = "anchor"
        longer = "日" * len(anchor)
        head = f"- [stated] {anchor}\n"
        growth = len(longer.encode("utf-8")) - len(anchor)
        # Fills to within 3 bytes of `limit`, so growing by `growth` overflows it.
        filler_chars = (limit - len(head) - growth) // 3
        content = head + "- [stated] " + "日" * filler_chars + "\n"
        size = len(content.replace(anchor, longer, 1).encode("utf-8"))
        r = _create_and_read(name, client, p, content, src)
        expect_error(
            name,
            f"replace_fact({p})",
            lambda: client.replace_fact(p, anchor, longer, r.version, source=src),
            OversizeWriteError,
            _RECOVERABLE,
            path=p,
            size=size,
            limit=limit,
        )
        _expect_content(name, client, p, "content changed", content)

    def test_system_area_write_is_accepted_at_transport(
        self, client: TransportClient, source: str, scope_map: Mapping[str, str]
    ) -> None:
        """A write to a system/ area is accepted and reads back unchanged.

        system/ and role enforcement belong to the tool layer, never the transport.
        """
        name = _name(type(client))
        check_client(name, client)
        src = check_source(name, source)
        scopes = check_scope_map(name, scope_map)
        require_fresh(name, client, scopes)
        first = _first_scope(scopes)
        path = probe_path(name, _PROBE_LABEL, scopes, first, _SYSTEM_AREA, "conformance-curated")
        content = "- [system] curated\n"
        metadata = _meta(sources=frozenset({_seed(src)}))
        _write(
            name,
            f"write_file({path})",
            lambda: client.write_file(path, content, metadata, None, source=src),
        )
        _expect_content(name, client, path, "round trip changed content", content)

    # --- Index behavior --------------------------------------------------------

    def test_index_fans_out_over_every_scope(
        self, client: TransportClient, source: str, scope_map: Mapping[str, str]
    ) -> None:
        """get_memory_index returns files from every scope in the map, with nothing capped."""
        name = _name(type(client))
        check_client(name, client)
        src = check_source(name, source)
        scopes = check_scope_map(name, scope_map)
        require_fresh(name, client, scopes)
        ordered = sorted(scopes)
        p = probe_path(name, _PROBE_LABEL, scopes, ordered[0], PROBE_AREA, PROBE_STEM)
        r = probe_path(name, _PROBE_LABEL, scopes, ordered[1], PROBE_AREA, PROBE_STEM_3)
        metadata = _meta(sources=frozenset({_seed(src)}))
        for path in (p, r):
            _create(name, client, path, metadata, src)
        index_label = "get_memory_index result"
        index = cast(
            object,
            _call(name, "get_memory_index(scope_map)", lambda: client.get_memory_index(scopes)),
        )
        entries, capped = canonical_index(
            name, index_label, without_sentinel(name, index_label, cast(MemoryIndex, index))
        )
        paths = [c[0] for c in entries]
        for path in (p, r):
            if path not in paths:
                _fail(name, index_label, f"missing entry: {path} not in {_short(paths)}")
        if capped:
            _fail(name, index_label, f"wrong capped: expected (), got {_short(capped)}")

    def test_index_orders_system_first_then_priority_then_recency(
        self,
        client: TransportClient,
        source: str,
        scope_map: Mapping[str, str],
        scope_priority: tuple[str, ...],
    ) -> None:
        """Index order: system/ by recency, then scope_priority tiers, each by recency."""
        name = _name(type(client))
        check_client(name, client)
        src = check_source(name, source)
        scopes = check_scope_map(name, scope_map)
        priority = check_scope_priority(name, scope_priority)
        require_fresh(name, client, scopes)
        ordered = sorted(scopes)
        metadata = _meta(sources=frozenset({_seed(src)}))
        s1 = probe_path(name, _PROBE_LABEL, scopes, ordered[0], _SYSTEM_AREA, PROBE_STEM)
        s2 = probe_path(name, _PROBE_LABEL, scopes, ordered[1], _SYSTEM_AREA, PROBE_STEM_2)
        listed = [s for s in priority if s in scopes]
        unlisted = [s for s in ordered if s not in priority]
        written: list[str] = []
        for path in [s1, s2] + [
            probe_path(name, _PROBE_LABEL, scopes, s, PROBE_AREA, PROBE_STEM)
            for s in listed + unlisted
        ]:
            _create(name, client, path, metadata, src)
            written.append(path)
        # Write order is recency order, so within a tier newest first is reverse write order.
        recency = {path: i for i, path in enumerate(written)}
        expected = sorted(
            written,
            key=lambda path: (
                (0, 0)
                if parse_path(path).area == _SYSTEM_AREA
                else (1, _tier(priority, parse_path(path).scope)),
                -recency[path],
            ),
        )
        index_label = "get_memory_index result"
        index = cast(
            object,
            _call(name, "get_memory_index(scope_map)", lambda: client.get_memory_index(scopes)),
        )
        entries, _ = canonical_index(
            name, index_label, without_sentinel(name, index_label, cast(MemoryIndex, index))
        )
        got = [c[0] for c in entries]
        if got != expected:
            _fail(name, index_label, f"wrong order: expected {expected}, got {got}")

    def test_index_byte_cap_degrades_with_capped_prefixes(
        self,
        client: TransportClient,
        source: str,
        scope_map: Mapping[str, str],
        index_max_bytes: int,
        scope_priority: tuple[str, ...],
    ) -> None:
        """Past index_max_bytes the index returns the longest fitting prefix and caps the rest."""
        name = _name(type(client))
        check_client(name, client)
        src = check_source(name, source)
        scopes = check_scope_map(name, scope_map)
        budget = check_positive_int(name, "index_max_bytes", index_max_bytes)
        priority = check_scope_priority(name, scope_priority)
        require_fresh(name, client, scopes)
        second = sorted(scopes)[1]
        sentinel = sentinel_path(scopes)
        sentinel_bytes = sentinel_entry_bytes(name, client, scopes)
        prefix = build_prefix(second, scopes[second], INDEX_AREA)
        list_label = f"list_prefix({prefix})"
        metadata = _meta(_CAP_DESCRIPTION, sources=frozenset({_seed(src)}))
        written: list[str] = []
        replay: list[str] = []
        included: list[str] = []
        # Continue until an INDEX_AREA entry, not just the sentinel, is predicted capped.
        for i in range(_CAP_FILES):
            path = probe_path(name, _PROBE_LABEL, scopes, second, INDEX_AREA, f"{PROBE_STEM}-{i}")
            _create(name, client, path, metadata, src)
            written.append(path)
            listed = _listed_entries(name, client, prefix)
            raw = [e for e, _ in listed]
            sizes = dict(
                zip((c[0] for _, c in listed), _entry_bytes(name, list_label, raw), strict=True)
            )
            missing = [p for p in written if p not in sizes]
            if missing:
                _fail(name, list_label, f"missing entry: {_short(missing)}")
            sizes[sentinel] = sentinel_bytes
            replay, included = _replay_cap(sentinel, written, sizes, priority, budget)
            if any(p != sentinel for p in replay[len(included) :]):
                break
        else:
            pytest.skip(
                f"{_CAP_FILES} index entries cannot overflow index_max_bytes={budget} "
                f"past the sentinel"
            )
        counts: dict[str, int] = {}
        for path in replay[len(included) :]:
            area = _area_prefix(path)
            counts[area] = counts.get(area, 0) + 1
        sentinel_area = _area_prefix(sentinel)
        expected_capped = tuple(
            (area, n) for area, n in sorted(counts.items()) if area != sentinel_area
        )
        index_label = "get_memory_index result"
        index = cast(
            object,
            _call(name, "get_memory_index(scope_map)", lambda: client.get_memory_index(scopes)),
        )
        raw_entries, canon_entries, _, _ = _index_parts(name, index_label, index)
        used = sum(_entry_bytes(name, index_label, cast(tuple[FileEntry, ...], raw_entries)))
        if used > budget:
            _fail(name, index_label, f"budget exceeded: entries total {used} > {budget}")
        got = [c[0] for c in canon_entries]
        if got != included:
            _fail(name, index_label, f"wrong order: expected {included}, got {got}")
        _, capped = canonical_index(
            name, index_label, without_sentinel(name, index_label, cast(MemoryIndex, index))
        )
        if capped != expected_capped:
            _fail(
                name,
                index_label,
                f"wrong capped: expected {_short(expected_capped)}, got {_short(capped)}",
            )

    def test_index_of_empty_scope_map_is_empty(self, client: TransportClient) -> None:
        """get_memory_index({}) returns no entries and nothing capped."""
        name = _name(type(client))
        check_client(name, client)
        index = cast(
            object, _call(name, "get_memory_index({})", lambda: client.get_memory_index({}))
        )
        got = canonical_index(name, "get_memory_index result", index)
        if got != ((), ()):
            _fail(name, "get_memory_index result", f"not empty: got {_short(got)}")

    # --- Listing ---------------------------------------------------------------

    def test_list_prefix_paginates_with_stable_cursors(
        self,
        client: TransportClient,
        source: str,
        scope_map: Mapping[str, str],
        list_page_size: int,
    ) -> None:
        """One more file than a page lists as a full page with a cursor, then the rest."""
        name = _name(type(client))
        check_client(name, client)
        src = check_source(name, source)
        scopes = check_scope_map(name, scope_map)
        size = check_positive_int(name, "list_page_size", list_page_size)
        require_fresh(name, client, scopes)
        first = _first_scope(scopes)
        metadata = _meta(sources=frozenset({_seed(src)}))
        written = [
            probe_path(name, _PROBE_LABEL, scopes, first, PROBE_AREA, f"{PROBE_STEM}-{i}")
            for i in range(size + 1)
        ]
        for path in written:
            _create(name, client, path, metadata, src)
        prefix = build_prefix(first, scopes[first], PROBE_AREA)
        label = f"list_prefix({prefix})"
        page, (entries1, _) = _first_page(name, client, prefix, size)
        cursor = cast(ListCursor, _get(name, label, page, "next_cursor"))
        second = _call(name, label, lambda: client.list_prefix(prefix, cursor))
        entries2, last = canonical_page(name, label, second)
        if not last:
            _fail(name, label, "bad field next_cursor: expected None on the last page")
        again = _call(name, label, lambda: client.list_prefix(prefix, cursor))
        if canonical_page(name, label, again) != (entries2, last):
            _fail(name, label, "unstable cursor: the same cursor listed a different page")
        paths = [c[0] for c in entries1 + entries2]
        if sorted(set(paths)) != sorted(written):
            _fail(name, label, f"wrong entries: expected {sorted(written)}, got {paths}")
        if paths != sorted(paths):
            _fail(name, label, f"wrong order: expected ascending paths, got {paths}")

    def test_list_prefix_levels(
        self, client: TransportClient, source: str, scope_map: Mapping[str, str]
    ) -> None:
        """Entity- and scope-level listings include everything the area-level listing does."""
        name = _name(type(client))
        check_client(name, client)
        src = check_source(name, source)
        scopes = check_scope_map(name, scope_map)
        require_fresh(name, client, scopes)
        first = _first_scope(scopes)
        p = probe_path(name, _PROBE_LABEL, scopes, first, PROBE_AREA, PROBE_STEM)
        _create(name, client, p, _meta(sources=frozenset({_seed(src)})), src)
        area = build_prefix(first, scopes[first], PROBE_AREA)
        levels = (area, build_prefix(first, scopes[first]), build_prefix(first))
        listings: list[set[str]] = []
        for prefix in levels:
            raw = [e for e, _ in _listed_entries(name, client, prefix)]
            kept = without_sentinel(name, f"list_prefix({prefix})", raw)
            listings.append({canonical_entry(name, f"list_prefix({prefix})", e)[0] for e in kept})
        if p not in listings[0]:
            _fail(name, f"list_prefix({area})", f"missing entry: {p}")
        for prefix, listing in zip(levels[1:], listings[1:], strict=True):
            missing = sorted(listings[0] - listing)
            if missing:
                _fail(name, f"list_prefix({prefix})", f"missing entry: {_short(missing)}")

    def test_list_prefix_invalid_prefix_is_not_found(
        self, client: TransportClient, scope_map: Mapping[str, str]
    ) -> None:
        """A malformed prefix raises NotFoundError with reason INVALID_PATH."""
        name = _name(type(client))
        check_client(name, client)
        scopes = check_scope_map(name, scope_map)
        require_fresh(name, client, scopes)
        for prefix in ("nope", ""):
            expect_error(
                name,
                f"list_prefix({prefix!r})",
                lambda prefix=prefix: client.list_prefix(prefix),
                NotFoundError,
                _RECOVERABLE,
                path=prefix,
                reason=NotFoundReason.INVALID_PATH,
            )

    def test_list_prefix_malformed_cursor_is_value_error(
        self,
        client: TransportClient,
        source: str,
        scope_map: Mapping[str, str],
        list_page_size: int,
    ) -> None:
        """A malformed cursor, or one issued for another prefix, raises core's ValueError."""
        name = _name(type(client))
        check_client(name, client)
        src = check_source(name, source)
        scopes = check_scope_map(name, scope_map)
        size = check_positive_int(name, "list_page_size", list_page_size)
        require_fresh(name, client, scopes)
        first = _first_scope(scopes)
        prefix = build_prefix(first, scopes[first], PROBE_AREA)
        malformed = ListCursor("!!!")
        expect_error(
            name,
            f"list_prefix({prefix})",
            lambda: client.list_prefix(prefix, malformed),
            ValueError,
            None,
            message=MSG_MALFORMED_CURSOR.format(cursor=malformed),
        )
        metadata = _meta(sources=frozenset({_seed(src)}))
        for i in range(size + 1):
            path = probe_path(name, _PROBE_LABEL, scopes, first, PROBE_AREA, f"{PROBE_STEM}-{i}")
            _create(name, client, path, metadata, src)
        page, _ = _first_page(name, client, prefix, size)
        cursor = cast(ListCursor, _get(name, f"list_prefix({prefix})", page, "next_cursor"))
        other = build_prefix(first, scopes[first], INDEX_AREA)
        expect_error(
            name,
            f"list_prefix({other})",
            lambda: client.list_prefix(other, cursor),
            ValueError,
            None,
            message=MSG_FOREIGN_CURSOR.format(cursor=cursor, prefix=other),
        )

    # --- Error parity ----------------------------------------------------------

    def test_invalid_path_is_not_found_for_every_operation(
        self, client: TransportClient, source: str, scope_map: Mapping[str, str]
    ) -> None:
        """Every path-taking operation rejects a malformed path as INVALID_PATH, storing nothing."""
        name = _name(type(client))
        check_client(name, client)
        src = check_source(name, source)
        scopes = check_scope_map(name, scope_map)
        require_fresh(name, client, scopes)
        p = probe_path(name, _PROBE_LABEL, scopes, _first_scope(scopes), PROBE_AREA, PROBE_STEM)
        metadata = _meta(sources=frozenset({_seed(src)}))
        for bad in _INVALID_PATHS:
            calls: tuple[tuple[str, Callable[[], object]], ...] = (
                ("read_file", lambda bad=bad: client.read_file(bad)),
                (
                    "write_file",
                    lambda bad=bad: client.write_file(
                        bad, "- [stated] a\n", metadata, None, source=src
                    ),
                ),
                (
                    "append_line",
                    lambda bad=bad: client.append_line(
                        bad, "- [stated] a", _ABSENT_TOKEN, source=src
                    ),
                ),
                (
                    "replace_fact",
                    lambda bad=bad: client.replace_fact(
                        bad, "alpha", "gamma", _ABSENT_TOKEN, source=src
                    ),
                ),
                ("delete_file", lambda bad=bad: client.delete_file(bad, _ABSENT_TOKEN)),
            )
            for method, call in calls:
                expect_error(
                    name,
                    f"{method}({bad!r})",
                    call,
                    NotFoundError,
                    _RECOVERABLE,
                    path=bad,
                    reason=NotFoundReason.INVALID_PATH,
                )
        _expect_absent(name, client, p)

    def test_absent_file_is_not_found_for_every_mutating_read(
        self, client: TransportClient, source: str, scope_map: Mapping[str, str]
    ) -> None:
        """read, append, replace_fact, and delete on an absent path raise FILE_ABSENT."""
        name = _name(type(client))
        check_client(name, client)
        src = check_source(name, source)
        scopes = check_scope_map(name, scope_map)
        require_fresh(name, client, scopes)
        p = probe_path(name, _PROBE_LABEL, scopes, _first_scope(scopes), PROBE_AREA, PROBE_STEM)
        calls: tuple[tuple[str, Callable[[], object]], ...] = (
            ("read_file", lambda: client.read_file(p)),
            (
                "append_line",
                lambda: client.append_line(p, "- [stated] a", _ABSENT_TOKEN, source=src),
            ),
            (
                "replace_fact",
                lambda: client.replace_fact(p, "alpha", "gamma", _ABSENT_TOKEN, source=src),
            ),
            ("delete_file", lambda: client.delete_file(p, _ABSENT_TOKEN)),
        )
        for method, call in calls:
            expect_error(
                name,
                f"{method}({p})",
                call,
                NotFoundError,
                _RECOVERABLE,
                path=p,
                reason=_FILE_ABSENT,
            )

    def test_empty_source_is_value_error(
        self, client: TransportClient, source: str, scope_map: Mapping[str, str]
    ) -> None:
        """An empty source raises ValueError with core's message on every writing call."""
        name = _name(type(client))
        check_client(name, client)
        src = check_source(name, source)
        scopes = check_scope_map(name, scope_map)
        require_fresh(name, client, scopes)
        p = probe_path(name, _PROBE_LABEL, scopes, _first_scope(scopes), PROBE_AREA, PROBE_STEM)
        r = _create_and_read(name, client, p, _FACTS, src)
        observed = canonical_file(name, f"read result for {p}", r)[1]
        metadata = _meta(sources=frozenset({_seed(src)}))
        calls: tuple[tuple[str, Callable[[], object], str], ...] = (
            (
                "write_file",
                lambda: client.write_file(p, "- [stated] b\n", metadata, r.version, source=""),
                MSG_WRITE_ARGS,
            ),
            (
                "replace_fact",
                lambda: client.replace_fact(p, "beta", "gamma", r.version, source=""),
                MSG_REPLACE_ARGS,
            ),
            (
                "append_line",
                lambda: client.append_line(p, "- [stated] b", r.version, source=""),
                MSG_APPEND_ARGS,
            ),
        )
        for method, call, message in calls:
            expect_error(name, f"{method}({p})", call, ValueError, None, message=message)
        _expect_content(name, client, p, "content changed", observed)

    def test_error_messages_carry_category_guidance(
        self,
        client: TransportClient,
        source: str,
        scope_map: Mapping[str, str],
        max_file_bytes: int,
    ) -> None:
        """Each recoverable error's text equals core's and ends with the category guidance."""
        name = _name(type(client))
        check_client(name, client)
        src = check_source(name, source)
        scopes = check_scope_map(name, scope_map)
        limit = check_positive_int(name, "max_file_bytes", max_file_bytes, MIN_FILE_BYTES)
        require_fresh(name, client, scopes)
        first = _first_scope(scopes)
        p = probe_path(name, _PROBE_LABEL, scopes, first, PROBE_AREA, PROBE_STEM)
        q = probe_path(name, _PROBE_LABEL, scopes, first, PROBE_AREA, PROBE_STEM_2)
        metadata = _meta(sources=frozenset({_seed(src)}))
        read_label = f"read_file({p})"
        write_label = f"write_file({p})"
        raised: list[tuple[str, Exception]] = []

        raised.append(
            (
                read_label,
                expect_error(
                    name,
                    read_label,
                    lambda: client.read_file(p),
                    NotFoundError,
                    _RECOVERABLE,
                    message=str(NotFoundError(p, _FILE_ABSENT)),
                    path=p,
                    reason=_FILE_ABSENT,
                ),
            )
        )

        r1 = _create_and_read(name, client, p, _FACTS, src)
        _write(
            name,
            write_label,
            lambda: client.write_file(p, "- [stated] b\n", metadata, r1.version, source=src),
        )
        observed = _read_content(name, client, p)
        raised.append(
            (
                write_label,
                expect_error(
                    name,
                    write_label,
                    lambda: client.write_file(
                        p, "- [stated] c\n", metadata, r1.version, source=src
                    ),
                    VersionConflictError,
                    _RECOVERABLE,
                    message=str(VersionConflictError(p, observed, _ABSENT_TOKEN)),
                    path=p,
                    content=observed,
                ),
            )
        )

        size = limit + 1
        oversize_label = f"write_file({q})"
        raised.append(
            (
                oversize_label,
                expect_error(
                    name,
                    oversize_label,
                    lambda: client.write_file(q, "x" * size, metadata, None, source=src),
                    OversizeWriteError,
                    _RECOVERABLE,
                    message=str(OversizeWriteError(q, size, limit)),
                    path=q,
                    size=size,
                    limit=limit,
                ),
            )
        )

        r2 = _read(name, read_label, lambda: client.read_file(p))
        current = canonical_file(name, f"read result for {p}", r2)[1]
        replace_label = f"replace_fact({p})"
        raised.append(
            (
                replace_label,
                expect_error(
                    name,
                    replace_label,
                    lambda: client.replace_fact(p, "delta", "gamma", r2.version, source=src),
                    ReplaceFactMatchError,
                    _RECOVERABLE,
                    message=str(ReplaceFactMatchError(p, current, _ABSENT_TOKEN, 0)),
                    path=p,
                    content=current,
                    match_count=0,
                ),
            )
        )

        guidance = RecoverableError.guidance
        for label, exc in raised:
            text = _call(name, label, lambda exc=exc: str(exc))
            if not text.endswith(guidance):
                _fail(name, label, f"missing guidance: {_short(text)}")

    def test_get_memory_index_argument_errors_match_core(
        self, client: TransportClient, scope_map: Mapping[str, str]
    ) -> None:
        """A malformed scope_map raises TypeError, or ValueError with core's message."""
        name = _name(type(client))
        check_client(name, client)
        scopes = check_scope_map(name, scope_map)
        require_fresh(name, client, scopes)
        first = _first_scope(scopes)
        type_cases: tuple[tuple[str, object], ...] = (
            ("a list", [(first, scopes[first])]),
            ("a non-str key", {1: scopes[first]}),
            ("a non-str value", {first: 1}),
        )
        for what, bad in type_cases:
            arg = cast(Mapping[str, str], bad)
            expect_error(
                name,
                f"get_memory_index({what})",
                lambda arg=arg: client.get_memory_index(arg),
                TypeError,
                None,
            )
        bad_scope = "a/"
        bad_entity = "x/"
        value_cases: tuple[tuple[dict[str, str], str], ...] = (
            ({bad_scope: scopes[first]}, MSG_INVALID_SCOPE.format(scope=bad_scope)),
            ({first: bad_entity}, MSG_INVALID_ENTITY.format(entity_id=bad_entity)),
        )
        for arg, message in value_cases:
            expect_error(
                name,
                f"get_memory_index({arg!r})",
                lambda arg=arg: client.get_memory_index(arg),
                ValueError,
                None,
                message=message,
            )
