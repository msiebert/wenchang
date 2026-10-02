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
    WenchangError,
)
from wenchang.file_format import FileMetadata
from wenchang.paths import build_path, build_prefix, is_valid_path, is_valid_segment, parse_path
from wenchang.transport import TransportClient

PROBE_AREA: Final = "notes"
PROBE_STEM: Final = "conformance-probe"
PROBE_STEM_2: Final = "conformance-probe-2"
SENTINEL_AREA: Final = "conformance-sentinel"
SENTINEL_STEM: Final = "sentinel"
MIN_FILE_BYTES: Final = 64
_SENTINEL_SOURCE: Final = "conformance-harness"
_SENTINEL_CONTENT: Final = "- [system] conformance sentinel\n"
_REPR_LIMIT: Final = 80

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
        canonical_entry(name, label, entry)
        checked = cast(FileEntry, entry)
        if parse_path(checked.path).area != SENTINEL_AREA:
            kept.append(checked)
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
        canonical_index(name, label, raw)
        index = cast(MemoryIndex, raw)
        suffix = f"/{SENTINEL_AREA}/"
        entries = _drop_sentinel(name, label, index.entries)
        capped = tuple(c for c in index.capped if not c.prefix.endswith(suffix))
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
    page = _call(name, label, lambda: client.list_prefix(prefix))
    canonical_page(name, label, page)
    count = len(page.entries)
    if count != 1:
        _fail(name, label, f"sentinel missing: expected exactly one entry, got {count}")
    return _call(name, label, lambda: index_entry_bytes(page.entries[0]))


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
    cursor = _get(name, label, value, "next_cursor")
    if cursor is not None:
        _exact(name, label, "next_cursor", cursor, str)
    return (entries, cursor is None)


def canonical_index(name: str, label: str, value: object, /) -> CanonicalIndex:
    """Check a MemoryIndex by exact type; return (canonical entries, ((prefix, omitted), ...))."""
    _outer(name, label, value, MemoryIndex)
    entries = _canonical_entries(name, label, _get(name, label, value, "entries"))
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
    return (entries, tuple(result))


# --- The suite ---------------------------------------------------------------


def _round_trip_metadata(seed: str) -> FileMetadata:
    return FileMetadata("d", ("x", "y"), frozenset({seed}), datetime(2000, 1, 1, tzinfo=UTC))


def _seed(source: str) -> str:
    return "s0" if source != "s0" else "s1"


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
        checked = check_client(name, client)
        check_source(name, source)
        check_scope_map(name, scope_map)
        check_positive_int(name, "max_file_bytes", max_file_bytes, MIN_FILE_BYTES)
        check_positive_int(name, "index_max_bytes", index_max_bytes)
        check_scope_priority(name, scope_priority)
        check_positive_int(name, "list_page_size", list_page_size)
        for method in _METHODS:
            try:
                attr = cast(object, getattr(checked, method))
            except Exception as exc:
                pytest.fail(
                    f"{name}: fixture client method {method} could not be read: "
                    f"raised {_name(type(exc))}"
                )
            if not callable(attr):
                pytest.fail(f"{name}: fixture client method {method} is not callable")

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
        metadata = _round_trip_metadata(seed)
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
        metadata = _round_trip_metadata(_seed(src))
        written = _call(
            name,
            f"write_file({p})",
            lambda: client.write_file(p, "- [stated] a\n", metadata, None, source=src),
        )
        canonical_file(name, f"write result for {p}", written)
        read = _call(name, f"read_file({p})", lambda: client.read_file(p))
        canonical_file(name, f"read result for {p}", read)
        try:
            rewritten = client.write_file(
                p, "- [stated] b\n", read.metadata, read.version, source=src
            )
        except Exception as exc:
            _fail(name, f"write_file({p})", f"token not accepted: raised {_name(type(exc))}")
        canonical_file(name, f"write result for {p}", rewritten)
        created = _call(
            name,
            f"write_file({q})",
            lambda: client.write_file(q, "- [stated] q\n", metadata, None, source=src),
        )
        canonical_file(name, f"write result for {q}", created)
        try:
            appended = client.append_line(q, "- [stated] c", created.version, source=src)
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
        metadata = _round_trip_metadata(_seed(src))
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
