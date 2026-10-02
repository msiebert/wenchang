"""Self-tests for the transport conformance harness.

Covers AIE-1047: US1.6 (sentinel helpers) and US2.0-2.8 (expect_error, canonical
readers, probe_path, require_fresh, _call) at helper level, and US1.2-1.4 and
US4 (broken clients and bad fixtures make each baseline case fail). Each failing
call is expected to raise pytest.fail with a message starting "{name}: {label}: "
and containing the key phrase.
"""

import inspect
import re
from collections.abc import Callable, Iterator, Mapping
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from itertools import pairwise
from typing import cast

import pytest

from wenchang.core import (
    CappedPrefix,
    FileEntry,
    ListCursor,
    ListPage,
    MemoryFile,
    MemoryIndex,
    MemoryStore,
    index_entry_bytes,
)
from wenchang.errors import (
    ErrorCategory,
    NotFoundError,
    NotFoundReason,
    OversizeWriteError,
    VersionConflictError,
)
from wenchang.file_format import FileMetadata, MetadataFormatError
from wenchang.storage.memory import InMemoryStorage
from wenchang.testing import transport_conformance
from wenchang.testing.transport_conformance import (
    MIN_FILE_BYTES,
    PROBE_AREA,
    PROBE_STEM,
    PROBE_STEM_2,
    SENTINEL_AREA,
    SENTINEL_STEM,
    TransportConformance,
    canonical_entry,
    canonical_file,
    canonical_index,
    canonical_page,
    check_client,
    check_scope_map,
    expect_error,
    probe_path,
    require_fresh,
    sentinel_entry_bytes,
    sentinel_path,
    without_sentinel,
)
from wenchang.transport import InProcessClient
from wenchang.version_token import VersionToken

pytestmark = pytest.mark.unit
pytest_plugins = ["pytester"]

_call = transport_conformance._call  # pyright: ignore[reportPrivateUsage]

NAME = "Client"
LABEL = "check-label"
SCOPE_MAP: Mapping[str, str] = {"user": "u-1", "org": "o-9"}
SENTINEL = "org/o-9/conformance-sentinel/sentinel.md"
SENTINEL_PREFIX = "org/o-9/conformance-sentinel/"
P = "org/o-9/notes/conformance-probe.md"
Q = "org/o-9/notes/conformance-probe-2.md"
WHEN = datetime(2024, 1, 1, tzinfo=UTC)
TOKEN = VersionToken("v-1")
RECOVERABLE = ErrorCategory.RECOVERABLE
FILE_ABSENT = NotFoundReason.FILE_ABSENT


class _Ticking:
    """Returns an aware datetime one microsecond later on each call."""

    def __init__(self) -> None:
        self._n = 0

    def __call__(self) -> datetime:
        self._n += 1
        return WHEN + timedelta(microseconds=self._n)


def _reference() -> InProcessClient:
    return InProcessClient(
        MemoryStore(
            InMemoryStorage(),
            clock=_Ticking(),
            max_file_bytes=256,
            index_max_bytes=4096,
            scope_priority=("user", "org"),
            list_page_size=2,
        )
    )


def _meta() -> FileMetadata:
    return FileMetadata("d", ("x", "y"), frozenset({"b", "a"}), WHEN)


class _Forwarding:
    """Forwards all seven TransportClient methods to a real InProcessClient."""

    def __init__(self, inner: InProcessClient | None = None) -> None:
        self.inner = inner if inner is not None else _reference()

    def read_file(self, path: str) -> MemoryFile:
        return self.inner.read_file(path)

    def write_file(
        self,
        path: str,
        content: str,
        metadata: FileMetadata,
        expected_version: VersionToken | None,
        *,
        source: str,
    ) -> MemoryFile:
        return self.inner.write_file(path, content, metadata, expected_version, source=source)

    def append_line(
        self, path: str, line: str, expected_version: VersionToken, *, source: str
    ) -> MemoryFile:
        return self.inner.append_line(path, line, expected_version, source=source)

    def replace_fact(
        self,
        path: str,
        old_string: str,
        new_string: str,
        expected_version: VersionToken,
        *,
        source: str,
    ) -> MemoryFile:
        return self.inner.replace_fact(
            path, old_string, new_string, expected_version, source=source
        )

    def list_prefix(self, prefix: str, cursor: ListCursor | None = None) -> ListPage:
        return self.inner.list_prefix(prefix, cursor)

    def delete_file(self, path: str, expected_version: VersionToken) -> None:
        self.inner.delete_file(path, expected_version)

    def get_memory_index(self, scope_map: Mapping[str, str]) -> MemoryIndex:
        return self.inner.get_memory_index(scope_map)


class _ReadRaises(_Forwarding):
    """read_file raises `exc` for every path."""

    def __init__(self, exc: Exception) -> None:
        super().__init__()
        self.exc = exc

    def read_file(self, path: str) -> MemoryFile:
        raise self.exc


class _SentinelWriteFails(_Forwarding):
    """write_file raises RuntimeError for the sentinel path only."""

    def write_file(
        self,
        path: str,
        content: str,
        metadata: FileMetadata,
        expected_version: VersionToken | None,
        *,
        source: str,
    ) -> MemoryFile:
        if path == SENTINEL:
            raise RuntimeError("sentinel write refused")
        return super().write_file(path, content, metadata, expected_version, source=source)


class _RecordsWrites(_Forwarding):
    """Records each write_file call's arguments, then forwards it."""

    def __init__(self) -> None:
        super().__init__()
        self.writes: list[tuple[str, str, FileMetadata, VersionToken | None, str]] = []

    def write_file(
        self,
        path: str,
        content: str,
        metadata: FileMetadata,
        expected_version: VersionToken | None,
        *,
        source: str,
    ) -> MemoryFile:
        self.writes.append((path, content, metadata, expected_version, source))
        return super().write_file(path, content, metadata, expected_version, source=source)


class _ListRaises(_Forwarding):
    """list_prefix raises RuntimeError."""

    def list_prefix(self, prefix: str, cursor: ListCursor | None = None) -> ListPage:
        raise RuntimeError("listing exploded")


class _ListReturns(_Forwarding):
    """list_prefix returns a fixed object."""

    def __init__(self, page: object) -> None:
        super().__init__()
        self.page = page

    def list_prefix(self, prefix: str, cursor: ListCursor | None = None) -> ListPage:
        return self.page  # pyright: ignore[reportReturnType]


class _StrSub(str):
    """A str subclass, which exact-type checks must reject."""


class _DatetimeSub(datetime):
    """A datetime subclass, which exact-type checks must reject."""


class _MemoryFileSub(MemoryFile):
    """A MemoryFile subclass, which the outer exact-type check must reject."""


class _FileMetadataSub(FileMetadata):
    """A FileMetadata subclass, which the metadata exact-type check must reject."""


def _build[T](cls: type[T], fields: Mapping[str, object]) -> T:
    """Construct `cls` bypassing __init__ and validation, setting each field."""
    obj = object.__new__(cls)
    for key, value in fields.items():
        object.__setattr__(obj, key, value)
    return obj


def _raw_meta(**overrides: object) -> FileMetadata:
    fields: dict[str, object] = {
        "description": "d",
        "aliases": ("x", "y"),
        "sources": frozenset({"b", "a"}),
        "last_updated": WHEN,
    }
    return _build(FileMetadata, fields | overrides)


def _raw_file(cls: type[MemoryFile] = MemoryFile, **overrides: object) -> MemoryFile:
    fields: dict[str, object] = {
        "path": P,
        "content": "- [stated] a\n",
        "metadata": _raw_meta(),
        "version": TOKEN,
    }
    return _build(cls, fields | overrides)


def _raw_entry(**overrides: object) -> FileEntry:
    fields: dict[str, object] = {"path": P, "metadata": _raw_meta(), "version": TOKEN}
    return _build(FileEntry, fields | overrides)


def _raising(exc: BaseException) -> Callable[[], object]:
    def call() -> object:
        raise exc

    return call


def _fails(call: Callable[[], object], phrase: str, name: str = NAME, label: str = LABEL) -> str:
    """Run call; require pytest.fail starting "{name}: {label}: " and containing phrase."""
    with pytest.raises(pytest.fail.Exception) as exc_info:
        call()
    message = str(exc_info.value)
    assert message.startswith(f"{name}: {label}: "), message
    assert phrase in message, message
    return message


# --- Constants and probe_path (US2.5) ---------------------------------------


def test_constants_match_spec() -> None:
    """The harness constants have the spec's values (AIE-1047, US1.6, US2.5)."""
    assert PROBE_AREA == "notes"
    assert PROBE_STEM == "conformance-probe"
    assert PROBE_STEM_2 == "conformance-probe-2"
    assert SENTINEL_AREA == "conformance-sentinel"
    assert SENTINEL_STEM == "sentinel"
    assert MIN_FILE_BYTES == 64


def test_probe_path_builds_path_in_scope() -> None:
    """probe_path returns build_path over the mapped entity (AIE-1047, US2.5)."""
    assert probe_path(NAME, LABEL, SCOPE_MAP, "org", PROBE_AREA, PROBE_STEM) == P
    assert probe_path(NAME, LABEL, SCOPE_MAP, "org", PROBE_AREA, PROBE_STEM_2) == Q
    assert (
        probe_path(NAME, LABEL, SCOPE_MAP, "user", PROBE_AREA, PROBE_STEM)
        == "user/u-1/notes/conformance-probe.md"
    )


def test_probe_path_unmapped_scope_fails() -> None:
    """probe_path for a scope not in the map fails "probe scope" (AIE-1047, US2.5, US2.0)."""
    message = _fails(
        lambda: probe_path(NAME, LABEL, SCOPE_MAP, "team", PROBE_AREA, PROBE_STEM), "probe scope"
    )

    assert "team" in message


# --- Sentinel helpers (US1.6) -----------------------------------------------


def test_sentinel_path_is_first_scope_own_entity() -> None:
    """The sentinel lives under the first sorted scope's entity (AIE-1047, US1.6)."""
    assert sentinel_path(SCOPE_MAP) == SENTINEL
    assert sentinel_path({"org": "o-9", "user": "u-1"}) == SENTINEL
    assert sentinel_path({"zeta": "z-1", "alpha": "a-1"}) == (
        "alpha/a-1/conformance-sentinel/sentinel.md"
    )


SENTINEL_ENTRY = FileEntry(SENTINEL, _meta(), VersionToken("v-s"))
OTHER_SENTINEL_AREA_ENTRY = FileEntry(
    "user/u-1/conformance-sentinel/other.md", _meta(), VersionToken("v-o")
)
P_ENTRY = FileEntry(P, _meta(), VersionToken("v-p"))
Q_ENTRY = FileEntry(Q, _meta(), VersionToken("v-q"))


def test_without_sentinel_filters_entries() -> None:
    """Entries whose area is the sentinel area are dropped, as a tuple (AIE-1047, US1.6)."""
    result = without_sentinel(
        NAME, LABEL, [P_ENTRY, SENTINEL_ENTRY, Q_ENTRY, OTHER_SENTINEL_AREA_ENTRY]
    )

    assert type(result) is tuple
    assert len(result) == 2
    assert result[0] is P_ENTRY
    assert result[1] is Q_ENTRY


def test_without_sentinel_accepts_any_iterable() -> None:
    """A generator of entries is filtered like a list (AIE-1047, US1.6)."""
    result = without_sentinel(NAME, LABEL, (e for e in (SENTINEL_ENTRY, P_ENTRY)))

    assert result == (P_ENTRY,)


def test_without_sentinel_filters_index_entries_and_capped() -> None:
    """A MemoryIndex loses sentinel entries and the sentinel CappedPrefix (AIE-1047, US1.6)."""
    index = MemoryIndex(
        entries=(SENTINEL_ENTRY, P_ENTRY, Q_ENTRY),
        capped=(
            CappedPrefix(SENTINEL_PREFIX, 1),
            CappedPrefix("org/o-9/notes/", 2),
            CappedPrefix("org/o-9/conformance-sentinel-x/", 3),
            CappedPrefix("user/", 4),
        ),
    )

    result = without_sentinel(NAME, LABEL, index)

    assert type(result) is MemoryIndex
    assert result.entries == (P_ENTRY, Q_ENTRY)
    assert [(c.prefix, c.omitted) for c in result.capped] == [
        ("org/o-9/notes/", 2),
        ("org/o-9/conformance-sentinel-x/", 3),
        ("user/", 4),
    ]


def test_without_sentinel_malformed_entry_path_fails_as_bad_field() -> None:
    """A malformed entry path fails "bad field path", not ValueError (AIE-1047, US2.8)."""
    bad = FileEntry("not-a-path", _meta(), VersionToken("v-b"))

    _fails(lambda: without_sentinel(NAME, LABEL, [P_ENTRY, bad]), "bad field path")


def test_without_sentinel_malformed_index_path_fails_as_bad_field() -> None:
    """A malformed index entry path fails "bad field path" (AIE-1047, US2.8)."""
    bad = FileEntry("not-a-path", _meta(), VersionToken("v-b"))
    index = MemoryIndex(entries=(bad,))

    _fails(lambda: without_sentinel(NAME, LABEL, index), "bad field path")


def test_without_sentinel_checks_entries_canonically() -> None:
    """Each entry is canonicalized first, so a list of aliases fails (AIE-1047, US2.8)."""
    bad = _raw_entry(metadata=_raw_meta(aliases=["x", "y"]))

    _fails(lambda: without_sentinel(NAME, LABEL, [bad]), "bad field aliases")


def test_sentinel_entry_bytes_measures_listed_sentinel() -> None:
    """sentinel_entry_bytes is index_entry_bytes of the listed sentinel (AIE-1047, US1.6)."""
    client = _reference()
    require_fresh(NAME, client, SCOPE_MAP)
    client.write_file(P, "- [stated] a\n", _meta(), None, source="conformance")
    page = client.list_prefix(SENTINEL_PREFIX)
    assert len(page.entries) == 1

    assert sentinel_entry_bytes(NAME, client, SCOPE_MAP) == index_entry_bytes(page.entries[0])


def test_sentinel_entry_bytes_without_sentinel_fails() -> None:
    """No sentinel listed fails "sentinel missing" (AIE-1047, US1.6)."""
    _fails(
        lambda: sentinel_entry_bytes(NAME, _reference(), SCOPE_MAP),
        "sentinel missing",
        label=f"list_prefix({SENTINEL_PREFIX})",
    )


def test_sentinel_entry_bytes_with_extra_entry_fails() -> None:
    """Two files in the sentinel area fail "sentinel missing" (AIE-1047, US1.6)."""
    client = _reference()
    require_fresh(NAME, client, SCOPE_MAP)
    client.write_file(SENTINEL_PREFIX + "other.md", "- [stated] a\n", _meta(), None, source="s")

    _fails(
        lambda: sentinel_entry_bytes(NAME, client, SCOPE_MAP),
        "sentinel missing",
        label=f"list_prefix({SENTINEL_PREFIX})",
    )


def test_sentinel_entry_bytes_listing_error_is_unexpected() -> None:
    """A raising list_prefix fails "unexpected error" (AIE-1047, US1.6, US2.8)."""
    message = _fails(
        lambda: sentinel_entry_bytes(NAME, _ListRaises(), SCOPE_MAP),
        "unexpected error",
        label=f"list_prefix({SENTINEL_PREFIX})",
    )

    assert "RuntimeError" in message


def test_sentinel_entry_bytes_checks_page_canonically() -> None:
    """A page whose entries are a list fails "bad field entries" (AIE-1047, US1.6)."""
    page = ListPage(entries=[SENTINEL_ENTRY], next_cursor=None)  # pyright: ignore[reportArgumentType]

    _fails(
        lambda: sentinel_entry_bytes(NAME, _ListReturns(page), SCOPE_MAP),
        "bad field entries",
        label=f"list_prefix({SENTINEL_PREFIX})",
    )


# --- expect_error (US2.1, US2.2) --------------------------------------------


def test_expect_error_returns_matching_exception() -> None:
    """A matching type, category, and payload returns the exception (AIE-1047, US2.1)."""
    exc = NotFoundError(P, FILE_ABSENT)

    got = expect_error(
        NAME, LABEL, _raising(exc), NotFoundError, RECOVERABLE, path=P, reason=FILE_ABSENT
    )

    assert got is exc


def test_expect_error_exact_message_passes() -> None:
    """message equal to str(exc) passes (AIE-1047, US2.2)."""
    exc = NotFoundError(P, FILE_ABSENT)

    assert expect_error(NAME, LABEL, _raising(exc), NotFoundError, RECOVERABLE, message=str(exc))


@pytest.mark.parametrize(
    "exc",
    [
        ValueError("empty source"),
        MetadataFormatError("sources", "bad json"),
        UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"),
    ],
    ids=["ValueError", "MetadataFormatError", "UnicodeDecodeError"],
)
def test_expect_error_non_taxonomy_with_none_category_passes(exc: Exception) -> None:
    """Non-taxonomy errors are matched with category None (AIE-1047, US2.2)."""
    assert expect_error(NAME, LABEL, _raising(exc), type(exc), None) is exc


def test_expect_error_did_not_raise_names_returned_type() -> None:
    """A call that returns fails "did not raise" naming the result type (AIE-1047, US2.1)."""
    message = _fails(
        lambda: expect_error(
            NAME, LABEL, lambda: 5, NotFoundError, RECOVERABLE, path=P, reason=FILE_ABSENT
        ),
        "did not raise",
    )

    assert "NotFoundError" in message
    assert "int" in message
    assert "max_file_bytes" not in message


def test_expect_error_oversize_did_not_raise_hints_fixture() -> None:
    """An OversizeWriteError that did not raise hints at max_file_bytes (AIE-1047, US2.1)."""
    message = _fails(
        lambda: expect_error(NAME, LABEL, lambda: None, OversizeWriteError, RECOVERABLE),
        "did not raise",
    )

    assert "OversizeWriteError" in message
    assert "NoneType" in message
    assert "check the max_file_bytes fixture" in message


class _NotFoundSub(NotFoundError):
    """A NotFoundError subclass, which a real-type match must reject."""


class _SpoofedNotFound(Exception):
    """Claims to be a NotFoundError through __class__."""

    path = P
    reason = FILE_ABSENT
    category = RECOVERABLE

    @property
    def __class__(self) -> type:  # pyright: ignore[reportIncompatibleMethodOverride]
        return NotFoundError


@pytest.mark.parametrize(
    ("exc", "got_name"),
    [
        (KeyError(P), "KeyError"),
        (_NotFoundSub(P, FILE_ABSENT), "_NotFoundSub"),
        (_SpoofedNotFound(), "_SpoofedNotFound"),
        (OversizeWriteError(P, 1, 1), "OversizeWriteError"),
    ],
    ids=["other-type", "subclass", "class-spoof", "sibling-taxonomy"],
)
def test_expect_error_wrong_type_names_both(exc: Exception, got_name: str) -> None:
    """A different real type fails "wrong error type" naming both (AIE-1047, US2.1)."""
    message = _fails(
        lambda: expect_error(
            NAME, LABEL, _raising(exc), NotFoundError, RECOVERABLE, path=P, reason=FILE_ABSENT
        ),
        "wrong error type",
    )

    assert got_name in message
    assert "NotFoundError" in message


def test_expect_error_wrong_category_fails() -> None:
    """An instance category override fails "wrong category" (AIE-1047, US2.1)."""
    exc = NotFoundError(P, FILE_ABSENT)
    vars(exc)["category"] = ErrorCategory.TRANSIENT

    message = _fails(
        lambda: expect_error(
            NAME, LABEL, _raising(exc), NotFoundError, RECOVERABLE, path=P, reason=FILE_ABSENT
        ),
        "wrong category",
    )

    assert "transient" in message
    assert "recoverable" in message


def test_expect_error_wrong_message_fails() -> None:
    """A different str(exc) fails "wrong message" (AIE-1047, US2.2)."""
    message = _fails(
        lambda: expect_error(NAME, LABEL, _raising(ValueError("y")), ValueError, None, message="x"),
        "wrong message",
    )

    assert "'y'" in message
    assert "'x'" in message


class _UnreadableStr(Exception):
    """An exception whose str() raises."""

    def __str__(self) -> str:
        raise RuntimeError("no str for you")


def test_expect_error_unreadable_message_fails() -> None:
    """A raising str(exc) fails "wrong message" with "unreadable" (AIE-1047, US2.2)."""
    message = _fails(
        lambda: expect_error(
            NAME, LABEL, _raising(_UnreadableStr()), _UnreadableStr, None, message="x"
        ),
        "wrong message",
    )

    assert "unreadable" in message


def test_expect_error_missing_payload_fails() -> None:
    """A missing payload attribute fails "wrong payload" naming it (AIE-1047, US2.1)."""
    exc = NotFoundError(P, FILE_ABSENT)

    message = _fails(
        lambda: expect_error(
            NAME, LABEL, _raising(exc), NotFoundError, RECOVERABLE, size=3, path=P
        ),
        "wrong payload",
    )

    assert "size" in message
    assert "missing" in message


class _UnreadablePath(Exception):
    """An exception whose path attribute raises on read."""

    @property
    def path(self) -> str:
        raise RuntimeError("no path for you")


def test_expect_error_unreadable_payload_fails() -> None:
    """A payload attribute raising on read fails "wrong payload" (AIE-1047, US2.1)."""
    message = _fails(
        lambda: expect_error(
            NAME, LABEL, _raising(_UnreadablePath()), _UnreadablePath, None, path=P
        ),
        "wrong payload",
    )

    assert "path" in message
    assert "unreadable" in message


def test_expect_error_plain_str_reason_is_wrong_type() -> None:
    """reason "file_absent" (plain str) against the StrEnum fails (AIE-1047, US2.1)."""
    exc = NotFoundError(P, "file_absent")  # pyright: ignore[reportArgumentType]

    message = _fails(
        lambda: expect_error(
            NAME, LABEL, _raising(exc), NotFoundError, RECOVERABLE, path=P, reason=FILE_ABSENT
        ),
        "wrong payload",
    )

    assert "reason" in message
    assert "str" in message
    assert "NotFoundReason" in message


def test_expect_error_str_subclass_path_is_wrong_type() -> None:
    """A str-subclass path fails "wrong payload" naming path (AIE-1047, US2.1)."""
    exc = NotFoundError(_StrSub(P), FILE_ABSENT)

    message = _fails(
        lambda: expect_error(
            NAME, LABEL, _raising(exc), NotFoundError, RECOVERABLE, path=P, reason=FILE_ABSENT
        ),
        "wrong payload",
    )

    assert "path" in message
    assert "_StrSub" in message


def test_expect_error_wrong_payload_value_names_both() -> None:
    """A different payload value fails naming the attribute and both values (AIE-1047, US2.1)."""
    exc = OversizeWriteError(P, 300, 256)

    message = _fails(
        lambda: expect_error(
            NAME, LABEL, _raising(exc), OversizeWriteError, RECOVERABLE, path=P, size=257
        ),
        "wrong payload",
    )

    assert "size" in message
    assert "300" in message
    assert "257" in message


def test_expect_error_payload_reprs_are_truncated() -> None:
    """Payload reprs are truncated to 80 characters (AIE-1047, US2.1)."""
    got_path = "g" * 300
    want_path = "w" * 300
    exc = NotFoundError(got_path, FILE_ABSENT)

    message = _fails(
        lambda: expect_error(
            NAME, LABEL, _raising(exc), NotFoundError, RECOVERABLE, path=want_path
        ),
        "wrong payload",
    )

    assert repr(got_path)[:40] in message
    assert repr(want_path)[:40] in message
    assert "g" * 81 not in message
    assert "w" * 81 not in message


class _Abort(BaseException):
    """A non-Exception BaseException."""


def test_expect_error_base_exception_propagates() -> None:
    """A non-Exception BaseException is not caught (AIE-1047, US2.1)."""
    with pytest.raises(_Abort):
        expect_error(NAME, LABEL, _raising(_Abort()), NotFoundError, RECOVERABLE)


@pytest.mark.parametrize(
    ("expected", "category"),
    [
        (ValueError, RECOVERABLE),
        (MetadataFormatError, ErrorCategory.PERMANENT),
        (NotFoundError, None),
        (VersionConflictError, None),
    ],
    ids=["value-error-category", "metadata-format-category", "not-found-none", "conflict-none"],
)
def test_expect_error_category_misuse_fails(
    expected: type[Exception], category: ErrorCategory | None
) -> None:
    """category must be given iff expected is a WenchangError (AIE-1047, US2.2)."""
    message = _fails(
        lambda: expect_error(NAME, LABEL, lambda: None, expected, category), "harness misuse"
    )

    assert expected.__name__ in message


def test_expect_error_leading_parameters_are_positional_only() -> None:
    """name, label, call, expected, category are positional-only (AIE-1047, US2.2)."""
    params = inspect.signature(expect_error).parameters

    leading = ["name", "label", "call", "expected", "category"]
    assert list(params)[:5] == leading
    for param in leading:
        assert params[param].kind is inspect.Parameter.POSITIONAL_ONLY, param
    assert params["message"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["message"].default is None
    assert list(params.values())[-1].kind is inspect.Parameter.VAR_KEYWORD


def test_expect_error_payload_may_be_named_like_a_parameter() -> None:
    """A payload attribute called "name" goes to the payload (AIE-1047, US2.2)."""
    exc = ImportError("no module", name="mod", path="p")

    assert expect_error(NAME, LABEL, _raising(exc), ImportError, None, name="mod", path="p") is exc

    message = _fails(
        lambda: expect_error(NAME, LABEL, _raising(exc), ImportError, None, name="other"),
        "wrong payload",
    )
    assert "name" in message


# --- Canonical readers (US2.3, US2.4) ---------------------------------------


def test_canonical_file_returns_plain_tuple() -> None:
    """A real MemoryFile canonicalizes to the six-field tuple (AIE-1047, US2.3)."""
    value = MemoryFile(P, "- [stated] a\n", _meta(), TOKEN)

    result = canonical_file(NAME, LABEL, value)

    assert result == (P, "- [stated] a\n", "d", ("x", "y"), ("a", "b"), WHEN)
    assert type(result) is tuple
    assert type(result[4]) is tuple


@pytest.mark.parametrize(
    ("value", "got_name"),
    [
        ({"path": P}, "dict"),
        (None, "NoneType"),
        (FileEntry(P, _meta(), TOKEN), "FileEntry"),
        (_raw_file(_MemoryFileSub), "_MemoryFileSub"),
    ],
    ids=["dict", "none", "file-entry", "subclass"],
)
def test_canonical_file_wrong_outer_type_fails(value: object, got_name: str) -> None:
    """A non-MemoryFile fails "wrong result type" naming it (AIE-1047, US2.3)."""
    message = _fails(lambda: canonical_file(NAME, LABEL, value), "wrong result type")

    assert "MemoryFile" in message
    assert got_name in message


NAIVE = datetime(2024, 1, 1)

BAD_FILES: list[tuple[str, MemoryFile, str]] = [
    ("path-int", _raw_file(path=3), "path"),
    ("path-str-sub", _raw_file(path=_StrSub(P)), "path"),
    ("content-bytes", _raw_file(content=b"- [stated] a\n"), "content"),
    ("content-str-sub", _raw_file(content=_StrSub("x")), "content"),
    ("metadata-dict", _raw_file(metadata={"description": "d"}), "metadata"),
    ("metadata-sub", _raw_file(metadata=_build(_FileMetadataSub, vars(_meta()))), "metadata"),
    ("description-int", _raw_file(metadata=_raw_meta(description=1)), "description"),
    ("description-sub", _raw_file(metadata=_raw_meta(description=_StrSub("d"))), "description"),
    ("aliases-list", _raw_file(metadata=_raw_meta(aliases=["x", "y"])), "aliases"),
    ("aliases-member", _raw_file(metadata=_raw_meta(aliases=("x", 1))), "aliases"),
    ("aliases-sub", _raw_file(metadata=_raw_meta(aliases=("x", _StrSub("y")))), "aliases"),
    ("sources-set", _raw_file(metadata=_raw_meta(sources={"a", "b"})), "sources"),
    ("sources-tuple", _raw_file(metadata=_raw_meta(sources=("a", "b"))), "sources"),
    ("sources-member", _raw_file(metadata=_raw_meta(sources=frozenset({"a", 1}))), "sources"),
    (
        "sources-sub",
        _raw_file(metadata=_raw_meta(sources=frozenset({"a", _StrSub("b")}))),
        "sources",
    ),
    ("last-updated-str", _raw_file(metadata=_raw_meta(last_updated="2024")), "last_updated"),
    ("last-updated-naive", _raw_file(metadata=_raw_meta(last_updated=NAIVE)), "last_updated"),
    (
        "last-updated-sub",
        _raw_file(metadata=_raw_meta(last_updated=_DatetimeSub(2024, 1, 1, tzinfo=UTC))),
        "last_updated",
    ),
    ("version-empty", _raw_file(version=""), "version"),
    ("version-none", _raw_file(version=None), "version"),
    ("version-int", _raw_file(version=7), "version"),
    ("version-sub", _raw_file(version=_StrSub("v-1")), "version"),
    ("path-before-version", _raw_file(path=3, version=""), "path"),
    ("path-before-metadata", _raw_file(path=3, metadata={}), "path"),
    ("content-before-metadata", _raw_file(content=3, metadata={}), "content"),
    (
        "aliases-before-version",
        _raw_file(metadata=_raw_meta(aliases=["x"]), version=""),
        "aliases",
    ),
    (
        "description-before-aliases",
        _raw_file(metadata=_raw_meta(description=1, aliases=["x"])),
        "description",
    ),
    (
        "sources-before-last-updated",
        _raw_file(metadata=_raw_meta(sources={"a"}, last_updated=NAIVE)),
        "sources",
    ),
]


@pytest.mark.parametrize(
    ("value", "field"), [(v, f) for _, v, f in BAD_FILES], ids=[i for i, _, _ in BAD_FILES]
)
def test_canonical_file_bad_field_fails(value: MemoryFile, field: str) -> None:
    """The first wrongly typed nested field fails "bad field <name>" (AIE-1047, US2.3, US2.0)."""
    _fails(lambda: canonical_file(NAME, LABEL, value), f"bad field {field}")


def test_canonical_file_naive_last_updated_says_naive() -> None:
    """A naive last_updated is reported as naive (AIE-1047, US2.3)."""
    value = _raw_file(metadata=_raw_meta(last_updated=NAIVE))

    message = _fails(lambda: canonical_file(NAME, LABEL, value), "bad field last_updated")

    assert "naive" in message


def test_canonical_entry_returns_plain_tuple() -> None:
    """A real FileEntry canonicalizes to the five-field tuple (AIE-1047, US2.4)."""
    result = canonical_entry(NAME, LABEL, FileEntry(P, _meta(), TOKEN))

    assert result == (P, "d", ("x", "y"), ("a", "b"), WHEN)
    assert type(result) is tuple


@pytest.mark.parametrize(
    ("value", "got_name"),
    [({"path": P}, "dict"), (MemoryFile(P, "c", _meta(), TOKEN), "MemoryFile")],
    ids=["dict", "memory-file"],
)
def test_canonical_entry_wrong_outer_type_fails(value: object, got_name: str) -> None:
    """A non-FileEntry fails "wrong result type" (AIE-1047, US2.4)."""
    message = _fails(lambda: canonical_entry(NAME, LABEL, value), "wrong result type")

    assert "FileEntry" in message
    assert got_name in message


BAD_ENTRIES: list[tuple[str, FileEntry, str]] = [
    ("path-sub", _raw_entry(path=_StrSub(P)), "path"),
    ("metadata-dict", _raw_entry(metadata={}), "metadata"),
    ("description-int", _raw_entry(metadata=_raw_meta(description=1)), "description"),
    ("aliases-list", _raw_entry(metadata=_raw_meta(aliases=["x"])), "aliases"),
    ("sources-set", _raw_entry(metadata=_raw_meta(sources={"a"})), "sources"),
    ("last-updated-naive", _raw_entry(metadata=_raw_meta(last_updated=NAIVE)), "last_updated"),
    ("version-empty", _raw_entry(version=""), "version"),
    ("version-sub", _raw_entry(version=_StrSub("v")), "version"),
]


@pytest.mark.parametrize(
    ("value", "field"), [(v, f) for _, v, f in BAD_ENTRIES], ids=[i for i, _, _ in BAD_ENTRIES]
)
def test_canonical_entry_bad_field_fails(value: FileEntry, field: str) -> None:
    """A wrongly typed entry field fails "bad field <name>" (AIE-1047, US2.4)."""
    _fails(lambda: canonical_entry(NAME, LABEL, value), f"bad field {field}")


def test_canonical_page_returns_entries_and_last_page_flag() -> None:
    """A ListPage canonicalizes to (entries, next_cursor is None) (AIE-1047, US2.4)."""
    entry = FileEntry(P, _meta(), TOKEN)
    canonical = (P, "d", ("x", "y"), ("a", "b"), WHEN)

    assert canonical_page(NAME, LABEL, ListPage((entry,), None)) == ((canonical,), True)
    assert canonical_page(NAME, LABEL, ListPage((entry,), ListCursor("abc"))) == (
        (canonical,),
        False,
    )
    assert canonical_page(NAME, LABEL, ListPage((), None)) == ((), True)


def test_canonical_page_wrong_outer_type_fails() -> None:
    """A non-ListPage fails "wrong result type" (AIE-1047, US2.4)."""
    message = _fails(
        lambda: canonical_page(NAME, LABEL, MemoryIndex()),
        "wrong result type",
    )

    assert "ListPage" in message
    assert "MemoryIndex" in message


BAD_PAGES: list[tuple[str, ListPage, str]] = [
    ("entries-list", _build(ListPage, {"entries": [P_ENTRY], "next_cursor": None}), "entries"),
    (
        "entry-bad-field",
        _build(
            ListPage,
            {"entries": (_raw_entry(metadata=_raw_meta(aliases=["x"])),), "next_cursor": None},
        ),
        "aliases",
    ),
    ("cursor-int", _build(ListPage, {"entries": (P_ENTRY,), "next_cursor": 1}), "next_cursor"),
    (
        "cursor-sub",
        _build(ListPage, {"entries": (P_ENTRY,), "next_cursor": _StrSub("c")}),
        "next_cursor",
    ),
]


@pytest.mark.parametrize(
    ("value", "field"), [(v, f) for _, v, f in BAD_PAGES], ids=[i for i, _, _ in BAD_PAGES]
)
def test_canonical_page_bad_field_fails(value: ListPage, field: str) -> None:
    """A wrongly typed page field fails "bad field <name>" (AIE-1047, US2.4)."""
    _fails(lambda: canonical_page(NAME, LABEL, value), f"bad field {field}")


def test_canonical_page_non_entry_member_fails_naming_type() -> None:
    """A page member that is not a FileEntry fails naming its type (AIE-1047, US2.4)."""
    page = _build(ListPage, {"entries": ({"path": P},), "next_cursor": None})

    message = _fails(lambda: canonical_page(NAME, LABEL, page), "dict")

    assert "bad field entries[0]: expected FileEntry" in message


def test_canonical_index_returns_entries_and_capped() -> None:
    """A MemoryIndex canonicalizes to (entries, ((prefix, omitted), ...)) (AIE-1047, US2.4)."""
    index = MemoryIndex(
        entries=(FileEntry(P, _meta(), TOKEN),),
        capped=(CappedPrefix("org/", 2), CappedPrefix("user/u-1/", 1)),
    )

    result = canonical_index(NAME, LABEL, index)

    assert result == (
        ((P, "d", ("x", "y"), ("a", "b"), WHEN),),
        (("org/", 2), ("user/u-1/", 1)),
    )


def test_canonical_index_wrong_outer_type_fails() -> None:
    """A non-MemoryIndex fails "wrong result type" (AIE-1047, US2.4)."""
    message = _fails(lambda: canonical_index(NAME, LABEL, ListPage((), None)), "wrong result type")

    assert "MemoryIndex" in message
    assert "ListPage" in message


BAD_INDEXES: list[tuple[str, MemoryIndex, str]] = [
    ("entries-list", _build(MemoryIndex, {"entries": [P_ENTRY], "capped": ()}), "entries"),
    (
        "entry-bad-field",
        _build(MemoryIndex, {"entries": (_raw_entry(version=""),), "capped": ()}),
        "version",
    ),
    (
        "capped-list",
        _build(MemoryIndex, {"entries": (), "capped": [CappedPrefix("org/", 1)]}),
        "capped",
    ),
    (
        "capped-member-tuple",
        _build(MemoryIndex, {"entries": (), "capped": (("org/", 1),)}),
        "capped",
    ),
    (
        "capped-prefix-int",
        _build(
            MemoryIndex,
            {"entries": (), "capped": (_build(CappedPrefix, {"prefix": 1, "omitted": 1}),)},
        ),
        "capped[0].prefix",
    ),
    (
        "capped-omitted-bool",
        _build(
            MemoryIndex,
            {"entries": (), "capped": (_build(CappedPrefix, {"prefix": "org/", "omitted": True}),)},
        ),
        "capped[0].omitted",
    ),
    (
        "capped-omitted-str",
        _build(
            MemoryIndex,
            {"entries": (), "capped": (_build(CappedPrefix, {"prefix": "org/", "omitted": "1"}),)},
        ),
        "capped[0].omitted",
    ),
]


@pytest.mark.parametrize(
    ("value", "field"), [(v, f) for _, v, f in BAD_INDEXES], ids=[i for i, _, _ in BAD_INDEXES]
)
def test_canonical_index_bad_field_fails(value: MemoryIndex, field: str) -> None:
    """A wrongly typed index field fails "bad field <name>" (AIE-1047, US2.4)."""
    _fails(lambda: canonical_index(NAME, LABEL, value), f"bad field {field}")


# --- _call (US2.8) ----------------------------------------------------------


def test_call_returns_result() -> None:
    """_call returns fn()'s result (AIE-1047, US2.8)."""
    assert _call(NAME, LABEL, lambda: 42) == 42


def test_call_exception_is_unexpected_error() -> None:
    """Any Exception fails "unexpected error" naming the type (AIE-1047, US2.8)."""

    def boom() -> int:
        raise RuntimeError("boom")

    message = _fails(lambda: _call(NAME, LABEL, boom), "unexpected error")

    assert "RuntimeError" in message


# --- require_fresh (US1.4, US2.7) -------------------------------------------


def test_require_fresh_writes_sentinel_on_fresh_client() -> None:
    """A fresh client passes and the sentinel is written as specified (AIE-1047, US2.7)."""
    client = _RecordsWrites()

    require_fresh(NAME, client, SCOPE_MAP)

    assert len(client.writes) == 1
    path, content, metadata, expected_version, source = client.writes[0]
    assert path == SENTINEL
    assert content == "- [system] conformance sentinel\n"
    assert metadata.description == "conformance sentinel"
    assert metadata.aliases == ()
    assert metadata.sources == frozenset()
    assert expected_version is None
    assert source == "conformance-harness"
    stored = client.inner.read_file(SENTINEL)
    assert stored.content == "- [system] conformance sentinel\n"


def test_require_fresh_sentinel_fits_minimum_file_size() -> None:
    """The sentinel content fits within MIN_FILE_BYTES (AIE-1047, US2.7)."""
    client = InProcessClient(MemoryStore(InMemoryStorage(), max_file_bytes=MIN_FILE_BYTES))

    require_fresh(NAME, client, SCOPE_MAP)


def test_require_fresh_twice_is_not_isolated() -> None:
    """A second require_fresh on one client fails "not isolated" (AIE-1047, US1.4, US2.7)."""
    client = _reference()
    require_fresh(NAME, client, SCOPE_MAP)

    message = _fails(
        lambda: require_fresh(NAME, client, SCOPE_MAP),
        "not isolated",
        label=f"read_file({SENTINEL})",
    )

    assert SENTINEL in message


def test_require_fresh_sentinel_write_failure_fails() -> None:
    """A raising sentinel write fails "sentinel write failed" naming the type.

    (AIE-1047, US2.7)
    """
    message = _fails(
        lambda: require_fresh(NAME, _SentinelWriteFails(), SCOPE_MAP),
        "sentinel write failed",
        label=f"write_file({SENTINEL})",
    )

    assert "RuntimeError" in message


def test_require_fresh_wrong_read_error_type_fails() -> None:
    """A non-NotFoundError sentinel read fails "wrong error type" (AIE-1047, US2.7)."""
    message = _fails(
        lambda: require_fresh(NAME, _ReadRaises(KeyError(SENTINEL)), SCOPE_MAP),
        "wrong error type",
        label=f"read_file({SENTINEL})",
    )

    assert "KeyError" in message


def test_require_fresh_wrong_read_reason_fails() -> None:
    """A NotFoundError with INVALID_PATH fails "wrong payload" naming reason (AIE-1047, US2.7)."""
    exc = NotFoundError(SENTINEL, NotFoundReason.INVALID_PATH)

    message = _fails(
        lambda: require_fresh(NAME, _ReadRaises(exc), SCOPE_MAP),
        "wrong payload",
        label=f"read_file({SENTINEL})",
    )

    assert "reason" in message


# --- Running baseline cases (US4 harness) -----------------------------------

SUITE = TransportConformance()
SOURCE = "conformance"
PROBES = (P, Q)
ROUND_TRIP = "test_write_then_read_round_trips"
TOKEN_CASE = "test_returned_token_is_accepted"
ABSENT = "test_read_absent_is_not_found"
OVERSIZE = "test_oversize_write_is_rejected"
PROTOCOL = "test_client_satisfies_protocol"
STATEFUL_CASES = (ROUND_TRIP, TOKEN_CASE, ABSENT, OVERSIZE)
ALL_CASES = (PROTOCOL, *STATEFUL_CASES)
FIXTURE_ORDER = (
    "client",
    "source",
    "scope_map",
    "max_file_bytes",
    "index_max_bytes",
    "scope_priority",
    "list_page_size",
)


def _fixtures(client: object, **overrides: object) -> dict[str, object]:
    """The reference fixture values, with overrides applied."""
    base: dict[str, object] = {
        "client": client,
        "source": SOURCE,
        "scope_map": dict(SCOPE_MAP),
        "max_file_bytes": 256,
        "index_max_bytes": 4096,
        "scope_priority": ("user", "org"),
        "list_page_size": 2,
    }
    return base | overrides


def _case_params(case: str) -> list[str]:
    method = cast(Callable[..., None], getattr(TransportConformance, case))
    return [p for p in inspect.signature(method).parameters if p != "self"]


def _run(case: str, client: object, **overrides: object) -> None:
    """Call SUITE.<case> with the fixtures its signature asks for."""
    values = _fixtures(client, **overrides)
    method = cast(Callable[..., None], getattr(SUITE, case))
    method(**{p: values[p] for p in _case_params(case)})


def _reference_passes(case: str) -> None:
    """The case passes for the reference client and the forwarding wrapper (US4.10)."""
    _run(case, _reference())
    _run(case, _Forwarding())


def _case_fails(case: str, client: object, label: str, phrase: str, **overrides: object) -> str:
    """Run the case; require a failure "{client type}: {label}: ...{phrase}..."."""
    prefix = f"{type(client).__name__}: {label}: "
    pattern = f"(?s)^{re.escape(prefix)}.*{re.escape(phrase)}"
    with pytest.raises(pytest.fail.Exception, match=pattern) as exc_info:
        _run(case, client, **overrides)
    return str(exc_info.value)


def _fixture_fails(case: str, client: object, fixture: str, **overrides: object) -> str:
    """Run the case; require a failure "{client type}: fixture {fixture} ..."."""
    pattern = f"^{re.escape(type(client).__name__)}: fixture {re.escape(fixture)} "
    with pytest.raises(pytest.fail.Exception, match=pattern) as exc_info:
        _run(case, client, **overrides)
    return str(exc_info.value)


def _with(file: MemoryFile, **overrides: object) -> MemoryFile:
    """A copy of file with fields replaced, bypassing validation."""
    return _build(MemoryFile, vars(file) | overrides)


def _with_meta(file: MemoryFile, **overrides: object) -> MemoryFile:
    """A copy of file with metadata fields replaced, bypassing validation."""
    return _with(file, metadata=_build(FileMetadata, vars(file.metadata) | overrides))


class _ProbeReadReturns(_Forwarding):
    """read_file of a probe path returns transform(real result); absent reads still raise."""

    def __init__(self, transform: Callable[[MemoryFile], object]) -> None:
        super().__init__()
        self.transform = transform

    def read_file(self, path: str) -> MemoryFile:
        result = super().read_file(path)
        if path in PROBES:
            return cast(MemoryFile, self.transform(result))
        return result


class _StripsSource(_Forwarding):
    """write_file and read_file drop SOURCE from the sources of probe results."""

    def _strip(self, path: str, result: MemoryFile) -> MemoryFile:
        if path in PROBES:
            return _with_meta(result, sources=result.metadata.sources - {SOURCE})
        return result

    def read_file(self, path: str) -> MemoryFile:
        return self._strip(path, super().read_file(path))

    def write_file(
        self,
        path: str,
        content: str,
        metadata: FileMetadata,
        expected_version: VersionToken | None,
        *,
        source: str,
    ) -> MemoryFile:
        result = super().write_file(path, content, metadata, expected_version, source=source)
        return self._strip(path, result)


class _ProbeReadRaises(_Forwarding):
    """read_file of a probe path raises `exc`."""

    def __init__(self, exc: Exception) -> None:
        super().__init__()
        self.exc = exc

    def read_file(self, path: str) -> MemoryFile:
        if path in PROBES:
            raise self.exc
        return super().read_file(path)


class _ProbeWriteRaises(_Forwarding):
    """write_file of a probe path raises `exc`."""

    def __init__(self, exc: Exception) -> None:
        super().__init__()
        self.exc = exc

    def write_file(
        self,
        path: str,
        content: str,
        metadata: FileMetadata,
        expected_version: VersionToken | None,
        *,
        source: str,
    ) -> MemoryFile:
        if path in PROBES:
            raise self.exc
        return super().write_file(path, content, metadata, expected_version, source=source)


class _AcceptsOversize(_Forwarding):
    """write_file of a probe path goes to a store with a far larger size limit."""

    def __init__(self) -> None:
        super().__init__()
        self.lenient = InProcessClient(MemoryStore(InMemoryStorage(), max_file_bytes=1 << 20))

    def write_file(
        self,
        path: str,
        content: str,
        metadata: FileMetadata,
        expected_version: VersionToken | None,
        *,
        source: str,
    ) -> MemoryFile:
        target = self.lenient if path in PROBES else self.inner
        return target.write_file(path, content, metadata, expected_version, source=source)


class _ForgetsTokens(_Forwarding):
    """Rejects any token handed back for a probe path with VersionConflictError."""

    def __init__(self, *, on_write: bool, on_append: bool) -> None:
        super().__init__()
        self.on_write = on_write
        self.on_append = on_append

    def write_file(
        self,
        path: str,
        content: str,
        metadata: FileMetadata,
        expected_version: VersionToken | None,
        *,
        source: str,
    ) -> MemoryFile:
        if self.on_write and path in PROBES and expected_version is not None:
            raise VersionConflictError(path, content, VersionToken("forgotten"))
        return super().write_file(path, content, metadata, expected_version, source=source)

    def append_line(
        self, path: str, line: str, expected_version: VersionToken, *, source: str
    ) -> MemoryFile:
        if self.on_append and path in PROBES:
            raise VersionConflictError(path, line, VersionToken("forgotten"))
        return super().append_line(path, line, expected_version, source=source)


class _NotAClient:
    """Has only read_file, so it does not satisfy TransportClient."""

    def read_file(self, path: str) -> MemoryFile:
        raise NotImplementedError


def test_forwarding_wrapper_satisfies_every_case() -> None:
    """The forwarding base and reference client pass all five cases (AIE-1047, US1.1, US4.10)."""
    for case in ALL_CASES:
        _reference_passes(case)


# --- US4.1-4.3: round trip ---------------------------------------------------

READ_RESULT_P = f"read result for {P}"

BAD_READS: list[tuple[str, Callable[[MemoryFile], object], str]] = [
    ("dict", lambda f: {"path": f.path, "content": f.content}, "wrong result type"),
    (
        "aliases-list",
        lambda f: _with_meta(f, aliases=list(f.metadata.aliases)),
        "bad field aliases",
    ),
    (
        "last-updated-naive",
        lambda f: _with_meta(f, last_updated=f.metadata.last_updated.replace(tzinfo=None)),
        "bad field last_updated",
    ),
    ("version-empty", lambda f: _with(f, version=""), "bad field version"),
    (
        "drops-alias",
        lambda f: _with_meta(f, aliases=f.metadata.aliases[:1]),
        "round trip changed aliases",
    ),
    (
        "strips-newline",
        lambda f: _with(f, content=f.content.removesuffix("\n")),
        "round trip changed content",
    ),
    (
        "doubles-newline",
        lambda f: _with(f, content=f.content + "\n"),
        "round trip changed content",
    ),
    (
        "other-last-updated",
        lambda f: _with_meta(f, last_updated=f.metadata.last_updated + timedelta(seconds=1)),
        "round trip changed last_updated",
    ),
    ("wrong-path", lambda f: _with(f, path=Q), "round trip changed path"),
    (
        "changes-description",
        lambda f: _with_meta(f, description="other"),
        "round trip changed description",
    ),
]


@pytest.mark.parametrize(
    ("transform", "phrase"), [(t, p) for _, t, p in BAD_READS], ids=[i for i, _, _ in BAD_READS]
)
def test_round_trip_bad_read_fails(transform: Callable[[MemoryFile], object], phrase: str) -> None:
    """A misbehaving read_file(P) fails the round trip with its phrase.

    (AIE-1047, US4.1, US4.2, US4.3, US4.10)
    """
    _reference_passes(ROUND_TRIP)

    _case_fails(ROUND_TRIP, _ProbeReadReturns(transform), READ_RESULT_P, phrase)


def test_round_trip_dict_read_names_dict() -> None:
    """A dict read result fails "wrong result type" naming dict (AIE-1047, US4.1, US4.10)."""
    _reference_passes(ROUND_TRIP)

    message = _case_fails(
        ROUND_TRIP,
        _ProbeReadReturns(lambda f: {"path": f.path}),
        READ_RESULT_P,
        "wrong result type",
    )

    assert "dict" in message
    assert "MemoryFile" in message


def test_round_trip_dict_reader_still_raises_for_absent() -> None:
    """The dict-returning client still raises for absent reads (AIE-1047, US4.1, US4.10)."""
    _reference_passes(ABSENT)

    _run(ABSENT, _ProbeReadReturns(lambda f: {"path": f.path}))


# --- US4.4: source stamping --------------------------------------------------


def test_round_trip_source_not_stamped_fails() -> None:
    """Stripping source from both results fails "source not stamped" on the write result.

    (AIE-1047, US4.4, US4.10)
    """
    _reference_passes(ROUND_TRIP)

    message = _case_fails(
        ROUND_TRIP, _StripsSource(), f"write result for {P}", "source not stamped"
    )

    assert SOURCE in message


# --- US4.5: absent read parity -----------------------------------------------


def _category_overridden() -> NotFoundError:
    exc = NotFoundError(P, FILE_ABSENT)
    vars(exc)["category"] = ErrorCategory.TRANSIENT
    return exc


ABSENT_READ_ERRORS: list[tuple[str, Exception, str, str]] = [
    ("key-error", KeyError(P), "wrong error type", "KeyError"),
    ("class-spoof", _SpoofedNotFound(), "wrong error type", "_SpoofedNotFound"),
    (
        "plain-str-reason",
        NotFoundError(P, "file_absent"),  # pyright: ignore[reportArgumentType]
        "wrong payload",
        "reason",
    ),
    ("category-override", _category_overridden(), "wrong category", "transient"),
]


@pytest.mark.parametrize(
    ("exc", "phrase", "detail"),
    [(e, p, d) for _, e, p, d in ABSENT_READ_ERRORS],
    ids=[i for i, _, _, _ in ABSENT_READ_ERRORS],
)
def test_read_absent_wrong_error_fails(exc: Exception, phrase: str, detail: str) -> None:
    """A wrong absent-read error fails with its phrase and detail (AIE-1047, US4.5, US4.10)."""
    _reference_passes(ABSENT)

    message = _case_fails(ABSENT, _ProbeReadRaises(exc), f"read_file({P})", phrase)

    assert detail in message


# --- US4.6: oversize rejection -----------------------------------------------


def test_oversize_accepted_fails_did_not_raise() -> None:
    """Accepting the oversize write fails "did not raise" with the fixture hint.

    (AIE-1047, US4.6, US4.10)
    """
    _reference_passes(OVERSIZE)

    message = _case_fails(OVERSIZE, _AcceptsOversize(), f"write_file({P})", "did not raise")

    assert "max_file_bytes" in message


@pytest.mark.parametrize(
    ("exc", "phrase", "detail"),
    [
        (NotFoundError(P, NotFoundReason.INVALID_PATH), "wrong error type", "NotFoundError"),
        (OversizeWriteError(P, 1, 1), "wrong payload", "size"),
    ],
    ids=["not-found", "wrong-size"],
)
def test_oversize_wrong_error_fails(exc: Exception, phrase: str, detail: str) -> None:
    """A wrong oversize error fails with its phrase and detail (AIE-1047, US4.6, US4.10)."""
    _reference_passes(OVERSIZE)

    message = _case_fails(OVERSIZE, _ProbeWriteRaises(exc), f"write_file({P})", phrase)

    assert detail in message


# --- US4.7: token acceptance -------------------------------------------------


@pytest.mark.parametrize(
    ("make_client", "label"),
    [
        (lambda: _ForgetsTokens(on_write=True, on_append=False), f"write_file({P})"),
        (lambda: _ForgetsTokens(on_write=False, on_append=True), f"append_line({Q})"),
    ],
    ids=["write", "append"],
)
def test_forgotten_token_fails_token_not_accepted(
    make_client: Callable[[], _ForgetsTokens], label: str
) -> None:
    """A client rejecting its own token fails "token not accepted" (AIE-1047, US4.7, US4.10)."""
    _reference_passes(TOKEN_CASE)

    message = _case_fails(TOKEN_CASE, make_client(), label, "token not accepted")

    assert "VersionConflictError" in message


# --- US1.4, US4.8: isolation and setup failures ------------------------------


@pytest.mark.parametrize(
    ("first", "second"),
    [(a, b) for a in STATEFUL_CASES for b in STATEFUL_CASES if a != b],
    ids=[f"{a}-then-{b}" for a in STATEFUL_CASES for b in STATEFUL_CASES if a != b],
)
def test_shared_client_second_case_not_isolated(first: str, second: str) -> None:
    """A client shared by two different cases fails the second "not isolated".

    (AIE-1047, US1.4, US4.8, US4.10)
    """
    shared = _reference()
    _run(first, shared)

    message = _case_fails(second, shared, f"read_file({SENTINEL})", "not isolated")

    assert SENTINEL in message


@pytest.mark.parametrize("case", STATEFUL_CASES)
def test_sentinel_write_failure_fails_every_stateful_case(case: str) -> None:
    """A sentinel-only write failure fails "sentinel write failed" (AIE-1047, US4.8, US4.10)."""
    _reference_passes(case)

    message = _case_fails(
        case, _SentinelWriteFails(), f"write_file({SENTINEL})", "sentinel write failed"
    )

    assert "RuntimeError" in message


def test_round_trip_write_runtime_error_is_unexpected() -> None:
    """write_file(P) raising RuntimeError fails "unexpected error" (AIE-1047, US4.8, US4.10)."""
    _reference_passes(ROUND_TRIP)

    message = _case_fails(
        ROUND_TRIP,
        _ProbeWriteRaises(RuntimeError("write exploded")),
        f"write_file({P})",
        "unexpected error",
    )

    assert "RuntimeError" in message


# --- US1.2, US1.3, US4.8a: fixture validation --------------------------------

BAD_FIXTURES: list[tuple[str, str, object, str]] = [
    ("source-int", "source", 1, "int"),
    ("source-empty", "source", "", "empty"),
    ("source-str-sub", "source", _StrSub("s"), "_StrSub"),
    ("source-none", "source", None, "NoneType"),
    ("scope-map-list", "scope_map", [("user", "u-1"), ("org", "o-9")], "list"),
    ("scope-map-one-entry", "scope_map", {"user": "u-1"}, "two"),
    ("scope-map-empty", "scope_map", {}, "two"),
    ("scope-map-int-value", "scope_map", {"user": 1, "org": "o-9"}, "int"),
    ("scope-map-int-key", "scope_map", {1: "u-1", "org": "o-9"}, "int"),
    ("scope-map-str-sub-key", "scope_map", {_StrSub("user"): "u-1", "org": "o-9"}, "_StrSub"),
    ("scope-map-bad-key", "scope_map", {"us/er": "u-1", "org": "o-9"}, "segment"),
    ("scope-map-bad-value", "scope_map", {"user": "u/1", "org": "o-9"}, "segment"),
    ("max-file-bytes-small", "max_file_bytes", MIN_FILE_BYTES - 1, str(MIN_FILE_BYTES)),
    ("max-file-bytes-zero", "max_file_bytes", 0, str(MIN_FILE_BYTES)),
    ("max-file-bytes-bool", "max_file_bytes", True, "bool"),
    ("max-file-bytes-float", "max_file_bytes", 256.0, "float"),
    ("max-file-bytes-str", "max_file_bytes", "256", "str"),
    ("index-max-bytes-zero", "index_max_bytes", 0, "at least 1"),
    ("index-max-bytes-negative", "index_max_bytes", -1, "at least 1"),
    ("index-max-bytes-bool", "index_max_bytes", True, "bool"),
    ("index-max-bytes-float", "index_max_bytes", 4096.0, "float"),
    ("scope-priority-str", "scope_priority", "user", "str"),
    ("scope-priority-list", "scope_priority", ["user", "org"], "list"),
    ("scope-priority-int-member", "scope_priority", ("user", 1), "int"),
    ("scope-priority-str-sub-member", "scope_priority", ("user", _StrSub("org")), "_StrSub"),
    ("scope-priority-duplicate", "scope_priority", ("user", "user"), "duplicate"),
    ("scope-priority-bad-segment", "scope_priority", ("user", "o/rg"), "segment"),
    ("list-page-size-zero", "list_page_size", 0, "at least 1"),
    ("list-page-size-true", "list_page_size", True, "bool"),
    ("list-page-size-false", "list_page_size", False, "bool"),
    ("list-page-size-float", "list_page_size", 2.0, "float"),
]


@pytest.mark.parametrize("case", ALL_CASES)
def test_non_client_fails_every_case(case: str) -> None:
    """A client not satisfying TransportClient fails every case "fixture client".

    (AIE-1047, US1.2, US4.10)
    """
    _reference_passes(case)

    message = _fixture_fails(case, _NotAClient(), "client")

    assert "_NotAClient" in message


@pytest.mark.parametrize(
    ("fixture", "value", "detail"),
    [(f, v, d) for _, f, v, d in BAD_FIXTURES],
    ids=[i for i, _, _, _ in BAD_FIXTURES],
)
def test_protocol_case_rejects_bad_fixture(fixture: str, value: object, detail: str) -> None:
    """test_client_satisfies_protocol fails "fixture <name>" for each bad fixture.

    (AIE-1047, US1.3, US4.8a, US4.10)
    """
    _reference_passes(PROTOCOL)

    message = _fixture_fails(PROTOCOL, _reference(), fixture, **{fixture: value})

    assert detail in message


def test_protocol_case_rejects_bad_client() -> None:
    """test_client_satisfies_protocol fails "fixture client" for a non-client.

    (AIE-1047, US4.8a, US4.10)
    """
    _reference_passes(PROTOCOL)

    _fixture_fails(PROTOCOL, _NotAClient(), "client")


BAD_FIXTURE_VALUES: dict[str, object] = {
    "source": "",
    "scope_map": {"user": "u-1"},
    "max_file_bytes": True,
    "index_max_bytes": 0,
    "scope_priority": ["user", "org"],
    "list_page_size": False,
}

FIXTURE_PAIRS = [
    *pairwise(FIXTURE_ORDER),
    ("client", "list_page_size"),
    ("source", "list_page_size"),
    ("scope_map", "scope_priority"),
]


@pytest.mark.parametrize(("earlier", "later"), FIXTURE_PAIRS)
def test_protocol_case_reports_earlier_bad_fixture(earlier: str, later: str) -> None:
    """With two bad fixtures, the earlier in the fixed order is reported.

    (AIE-1047, US1.3, US4.8a, US4.10)
    """
    _reference_passes(PROTOCOL)
    client: object = _NotAClient() if earlier == "client" else _reference()
    overrides = {f: BAD_FIXTURE_VALUES[f] for f in (earlier, later) if f != "client"}

    message = _fixture_fails(PROTOCOL, client, earlier, **overrides)

    assert f"fixture {later}" not in message


USED_BAD_FIXTURES: list[tuple[str, str, str, object]] = [
    (f"{case}-{bad_id}", case, fixture, value)
    for case in STATEFUL_CASES
    for bad_id, fixture, value, _ in BAD_FIXTURES
    if fixture in _case_params(case)
]


@pytest.mark.parametrize(
    ("case", "fixture", "value"),
    [(c, f, v) for _, c, f, v in USED_BAD_FIXTURES],
    ids=[i for i, _, _, _ in USED_BAD_FIXTURES],
)
def test_stateful_case_rejects_bad_fixture_it_uses(case: str, fixture: str, value: object) -> None:
    """A stateful case fails "fixture <name>" for a bad fixture it takes.

    (AIE-1047, US1.3, US4.10)
    """
    _reference_passes(case)

    _fixture_fails(case, _reference(), fixture, **{fixture: value})


def test_every_case_takes_only_the_seven_fixtures() -> None:
    """Each case's parameters are client plus a subset of the fixtures (AIE-1047, US1.3)."""
    assert _case_params(PROTOCOL) == list(FIXTURE_ORDER)
    for case in STATEFUL_CASES:
        params = _case_params(case)
        assert params[0] == "client"
        assert set(params) <= set(FIXTURE_ORDER)
    assert "max_file_bytes" in _case_params(OVERSIZE)


# --- US2.0, FR-003: adversarial values fail, never raise raw -----------------


def _without(fields: Mapping[str, object], missing: str) -> dict[str, object]:
    return {k: v for k, v in fields.items() if k != missing}


def _file_without(missing: str) -> MemoryFile:
    """A MemoryFile with every field except `missing` set, so reading it raises."""
    fields: dict[str, object] = {
        "path": P,
        "content": "- [stated] a\n",
        "metadata": _raw_meta(),
        "version": TOKEN,
    }
    return _build(MemoryFile, _without(fields, missing))


def _meta_without(missing: str) -> FileMetadata:
    """A FileMetadata with every field except `missing` set, so reading it raises."""
    return _build(FileMetadata, _without(vars(_raw_meta()), missing))


UNREADABLE_FILES: list[tuple[str, MemoryFile, str]] = [
    ("no-metadata", _file_without("metadata"), "bad field metadata: unreadable"),
    ("no-version", _file_without("version"), "bad field version"),
    ("no-aliases", _raw_file(metadata=_meta_without("aliases")), "bad field aliases: unreadable"),
]


@pytest.mark.parametrize(
    ("value", "phrase"),
    [(v, p) for _, v, p in UNREADABLE_FILES],
    ids=[i for i, _, _ in UNREADABLE_FILES],
)
def test_canonical_file_unreadable_field_fails(value: MemoryFile, phrase: str) -> None:
    """A field that raises on read fails "bad field <name>", not AttributeError.

    (AIE-1047, US2.3, US2.0, FR-003)
    """
    _fails(lambda: canonical_file(NAME, LABEL, value), phrase)


UNREADABLE_READS: list[tuple[str, Callable[[MemoryFile], object], str]] = [
    (
        "no-metadata",
        lambda f: _build(MemoryFile, _without(vars(f), "metadata")),
        "bad field metadata: unreadable",
    ),
    (
        "no-version",
        lambda f: _build(MemoryFile, _without(vars(f), "version")),
        "bad field version",
    ),
    (
        "no-aliases",
        lambda f: _with(f, metadata=_build(FileMetadata, _without(vars(f.metadata), "aliases"))),
        "bad field aliases: unreadable",
    ),
]


@pytest.mark.parametrize(
    ("transform", "phrase"),
    [(t, p) for _, t, p in UNREADABLE_READS],
    ids=[i for i, _, _ in UNREADABLE_READS],
)
def test_round_trip_unreadable_read_field_fails(
    transform: Callable[[MemoryFile], object], phrase: str
) -> None:
    """A read result with an unreadable field fails the round trip, not AttributeError.

    (AIE-1047, US2.3, US4.10, FR-003)
    """
    _reference_passes(ROUND_TRIP)

    _case_fails(ROUND_TRIP, _ProbeReadReturns(transform), READ_RESULT_P, phrase)


class _ClassRaises(_Forwarding):
    """A working client whose __class__ raises on read."""

    @property
    def __class__(self) -> type:  # pyright: ignore[reportIncompatibleMethodOverride]
        raise RuntimeError("no class for you")


def test_check_client_raising_class_fails_as_fixture_client() -> None:
    """A client whose __class__ raises fails "fixture client", not RuntimeError.

    (AIE-1047, US1.2, US2.0, FR-003)
    """
    with pytest.raises(pytest.fail.Exception, match=f"^{NAME}: fixture client "):
        check_client(NAME, _ClassRaises())


@pytest.mark.parametrize("case", ALL_CASES)
def test_raising_class_client_fails_every_case(case: str) -> None:
    """Every case fails "fixture client" for a client whose __class__ raises.

    (AIE-1047, US1.2, US4.10, FR-003)
    """
    _reference_passes(case)

    _fixture_fails(case, _ClassRaises(), "client")


class _FlakyOffset(tzinfo):
    """A zero UTC offset on the first utcoffset call; raises on every later call."""

    def __init__(self) -> None:
        self.calls = 0

    def utcoffset(self, dt: datetime | None, /) -> timedelta:
        self.calls += 1
        if self.calls > 1:
            raise RuntimeError("offset changed its mind")
        return timedelta(0)

    def dst(self, dt: datetime | None, /) -> None:
        return None

    def tzname(self, dt: datetime | None, /) -> str:
        return "flaky"


def test_round_trip_flaky_offset_fails_not_raises() -> None:
    """A last_updated whose offset raises after the first read fails, never raises raw.

    (AIE-1047, US2.3, US4.3, FR-003)
    """
    _reference_passes(ROUND_TRIP)
    client = _ProbeReadReturns(
        lambda f: _with_meta(f, last_updated=f.metadata.last_updated.replace(tzinfo=_FlakyOffset()))
    )

    with pytest.raises(pytest.fail.Exception) as exc_info:
        _run(ROUND_TRIP, client)

    message = str(exc_info.value)
    assert message.startswith(f"_ProbeReadReturns: {READ_RESULT_P}: "), message
    assert "bad field last_updated" in message or "round trip" in message, message


def test_round_trip_same_instant_other_offset_passes() -> None:
    """A read last_updated at +05:00 for the same instant passes the round trip.

    (AIE-1047, US2.3, US4.3)
    """
    plus_five = timezone(timedelta(hours=5))
    client = _ProbeReadReturns(
        lambda f: _with_meta(f, last_updated=f.metadata.last_updated.astimezone(plus_five))
    )

    _run(ROUND_TRIP, client)


class _DuplicateItems(dict[str, str]):
    """A dict whose items() yields `pairs`, which may repeat a key."""

    def __init__(self, pairs: list[tuple[str, str]]) -> None:
        super().__init__(pairs)
        self.pairs = pairs

    def items(self) -> list[tuple[str, str]]:  # pyright: ignore[reportIncompatibleMethodOverride]
        return self.pairs


DUPLICATE_SCOPE_PAIRS: list[tuple[str, list[tuple[str, str]]]] = [
    ("different-entities", [("user", "u-1"), ("user", "u-2"), ("org", "o-9")]),
    ("one-distinct-scope", [("user", "u-1"), ("user", "u-1")]),
]


@pytest.mark.parametrize(
    "pairs", [p for _, p in DUPLICATE_SCOPE_PAIRS], ids=[i for i, _ in DUPLICATE_SCOPE_PAIRS]
)
def test_check_scope_map_duplicate_items_key_fails(pairs: list[tuple[str, str]]) -> None:
    """A scope_map whose items() repeats a key fails "fixture scope_map".

    (AIE-1047, US1.3, US2.0, FR-003)
    """
    with pytest.raises(pytest.fail.Exception, match=f"^{NAME}: fixture scope_map "):
        check_scope_map(NAME, _DuplicateItems(pairs))


@pytest.mark.parametrize(
    "pairs", [p for _, p in DUPLICATE_SCOPE_PAIRS], ids=[i for i, _ in DUPLICATE_SCOPE_PAIRS]
)
def test_protocol_case_rejects_duplicate_items_scope_map(pairs: list[tuple[str, str]]) -> None:
    """test_client_satisfies_protocol fails "fixture scope_map" for a repeated key.

    (AIE-1047, US1.3, US4.8a, US4.10)
    """
    _reference_passes(PROTOCOL)

    _fixture_fails(PROTOCOL, _reference(), "scope_map", scope_map=_DuplicateItems(pairs))


def test_without_sentinel_duplicate_index_paths_fails() -> None:
    """An unvalidated MemoryIndex with duplicate entry paths fails, not ValueError.

    (AIE-1047, US1.6, US2.4, US2.8, FR-003)
    """
    index = _build(MemoryIndex, {"entries": (P_ENTRY, P_ENTRY), "capped": ()})

    with pytest.raises(pytest.fail.Exception) as exc_info:
        without_sentinel(NAME, LABEL, index)

    message = str(exc_info.value)
    assert message.startswith(f"{NAME}: {LABEL}: "), message
    assert "bad field entries" in message or "unexpected error" in message, message


class _ReadReturnsNone(_Forwarding):
    """read_file returns None for every path instead of raising."""

    def read_file(self, path: str) -> MemoryFile:
        return None  # pyright: ignore[reportReturnType]


def test_require_fresh_non_raising_read_names_returned_type() -> None:
    """A sentinel read that returns fails "not isolated" naming the returned type.

    (AIE-1047, US2.7, US1.4)
    """
    message = _fails(
        lambda: require_fresh(NAME, _ReadReturnsNone(), SCOPE_MAP),
        "not isolated",
        label=f"read_file({SENTINEL})",
    )

    assert "NoneType" in message


# --- Mutation survivors -------------------------------------------------------

MAX_FILE_BYTES = 256


class _StoresThenRejectsOversize(_Forwarding):
    """write_file of a probe path stores small content, then raises OversizeWriteError."""

    def write_file(
        self,
        path: str,
        content: str,
        metadata: FileMetadata,
        expected_version: VersionToken | None,
        *,
        source: str,
    ) -> MemoryFile:
        if path in PROBES:
            super().write_file(path, "- [stated] a\n", metadata, expected_version, source=source)
            raise OversizeWriteError(path, MAX_FILE_BYTES + 1, MAX_FILE_BYTES)
        return super().write_file(path, content, metadata, expected_version, source=source)


def test_oversize_write_that_stores_fails_on_follow_up_read() -> None:
    """A correct OversizeWriteError after storing the file fails the follow-up read.

    (AIE-1047, US3.5, US4.6)
    """
    _reference_passes(OVERSIZE)

    _case_fails(OVERSIZE, _StoresThenRejectsOversize(), f"read_file({P})", "did not raise")


def test_oversize_limit_one_byte_high_fails_did_not_raise() -> None:
    """A store accepting exactly max_file_bytes + 1 fails "did not raise" (AIE-1047, US3.5)."""
    _reference_passes(OVERSIZE)
    store = MemoryStore(InMemoryStorage(), clock=_Ticking(), max_file_bytes=MAX_FILE_BYTES + 1)
    client = _Forwarding(InProcessClient(store))

    _case_fails(OVERSIZE, client, f"write_file({P})", "did not raise")


class _StripsGivenSource(_Forwarding):
    """write_file and read_file drop `source` from the sources of probe results."""

    def __init__(self, source: str) -> None:
        super().__init__()
        self.source = source

    def _strip(self, path: str, result: MemoryFile) -> MemoryFile:
        if path in PROBES:
            return _with_meta(result, sources=result.metadata.sources - {self.source})
        return result

    def read_file(self, path: str) -> MemoryFile:
        return self._strip(path, super().read_file(path))

    def write_file(
        self,
        path: str,
        content: str,
        metadata: FileMetadata,
        expected_version: VersionToken | None,
        *,
        source: str,
    ) -> MemoryFile:
        result = super().write_file(path, content, metadata, expected_version, source=source)
        return self._strip(path, result)


@pytest.mark.parametrize("source", ["conformance", "s0"])
def test_round_trip_strips_fixture_source_fails(source: str) -> None:
    """Dropping the fixture's source fails "source not stamped", whatever the seed.

    (AIE-1047, US3.2, US4.4)
    """
    _run(ROUND_TRIP, _reference(), source=source)

    message = _case_fails(
        ROUND_TRIP,
        _StripsGivenSource(source),
        f"write result for {P}",
        "source not stamped",
        source=source,
    )

    assert source in message


class _ReplaceFactNone(_Forwarding):
    """replace_fact is None instead of a method."""

    replace_fact = None  # pyright: ignore[reportAssignmentType, reportIncompatibleMethodOverride]


class _ReplaceFactInt(_Forwarding):
    """replace_fact is a non-callable int instead of a method."""

    replace_fact = 5  # pyright: ignore[reportAssignmentType, reportIncompatibleMethodOverride]


@pytest.mark.parametrize("make_client", [_ReplaceFactNone, _ReplaceFactInt], ids=["none", "int"])
def test_protocol_case_non_callable_method_fails(make_client: Callable[[], _Forwarding]) -> None:
    """A non-callable replace_fact fails "fixture client" naming the method.

    (AIE-1047, US3.1, US4.8a)
    """
    message = _fixture_fails(PROTOCOL, make_client(), "client")

    assert "replace_fact" in message


class _ReturnsDict(_Forwarding):
    """The token rewrite of P or the append to Q returns a dict instead of a MemoryFile."""

    def __init__(self, *, on_rewrite: bool, on_append: bool) -> None:
        super().__init__()
        self.on_rewrite = on_rewrite
        self.on_append = on_append

    def write_file(
        self,
        path: str,
        content: str,
        metadata: FileMetadata,
        expected_version: VersionToken | None,
        *,
        source: str,
    ) -> MemoryFile:
        result = super().write_file(path, content, metadata, expected_version, source=source)
        if self.on_rewrite and path == P and expected_version is not None:
            return {"path": path}  # pyright: ignore[reportReturnType]
        return result

    def append_line(
        self, path: str, line: str, expected_version: VersionToken, *, source: str
    ) -> MemoryFile:
        result = super().append_line(path, line, expected_version, source=source)
        if self.on_append and path == Q:
            return {"path": path}  # pyright: ignore[reportReturnType]
        return result


@pytest.mark.parametrize(
    ("make_client", "label"),
    [
        (lambda: _ReturnsDict(on_rewrite=True, on_append=False), f"write result for {P}"),
        (lambda: _ReturnsDict(on_rewrite=False, on_append=True), f"append result for {Q}"),
    ],
    ids=["rewrite", "append"],
)
def test_token_case_dict_result_fails(make_client: Callable[[], _ReturnsDict], label: str) -> None:
    """A dict from the token rewrite or append fails "wrong result type".

    (AIE-1047, US3.3, US4.7)
    """
    _reference_passes(TOKEN_CASE)

    message = _case_fails(TOKEN_CASE, make_client(), label, "wrong result type")

    assert "dict" in message


def test_without_sentinel_capped_list_fails() -> None:
    """A MemoryIndex whose capped is a list fails "bad field capped" (AIE-1047, US1.6, US2.4)."""
    index = _build(MemoryIndex, {"entries": (P_ENTRY,), "capped": [CappedPrefix("org/", 1)]})

    _fails(lambda: without_sentinel(NAME, LABEL, index), "bad field capped")


def test_without_sentinel_keeps_lookalike_capped_prefix() -> None:
    """A capped prefix only ending in "conformance-sentinel/" is kept (AIE-1047, US1.6)."""
    lookalike = CappedPrefix("org/o-9/x-conformance-sentinel/", 2)
    index = MemoryIndex(entries=(P_ENTRY,), capped=(lookalike, CappedPrefix(SENTINEL_PREFIX, 1)))

    result = without_sentinel(NAME, LABEL, index)

    assert [(c.prefix, c.omitted) for c in result.capped] == [
        ("org/o-9/x-conformance-sentinel/", 2)
    ]


class _UnreadableCategory(NotFoundError):
    """A NotFoundError whose category raises on read."""

    @property
    def category(self) -> ErrorCategory:  # pyright: ignore[reportIncompatibleVariableOverride]
        raise RuntimeError("no category for you")


def test_expect_error_unreadable_category_fails() -> None:
    """A category raising on read fails "wrong category" with "unreadable" (AIE-1047, US2.1)."""
    exc = _UnreadableCategory(P, FILE_ABSENT)

    message = _fails(
        lambda: expect_error(NAME, LABEL, _raising(exc), _UnreadableCategory, RECOVERABLE),
        "wrong category",
    )

    assert "unreadable" in message


class _ItemsRaises(dict[str, str]):
    """A dict whose items() raises."""

    def items(self) -> list[tuple[str, str]]:  # pyright: ignore[reportIncompatibleMethodOverride]
        raise RuntimeError("no items for you")


def test_protocol_case_rejects_unreadable_scope_map() -> None:
    """A scope_map whose items() raises fails "fixture scope_map" (AIE-1047, US1.3, US4.8a)."""
    _reference_passes(PROTOCOL)

    message = _fixture_fails(PROTOCOL, _reference(), "scope_map", scope_map=_ItemsRaises(SCOPE_MAP))

    assert "RuntimeError" in message


def test_without_sentinel_raising_iterable_is_unexpected() -> None:
    """A generator raising mid-iteration fails "unexpected error" (AIE-1047, US1.6, US2.8)."""

    def entries() -> Iterator[FileEntry]:
        yield P_ENTRY
        raise RuntimeError("iteration exploded")

    message = _fails(lambda: without_sentinel(NAME, LABEL, entries()), "unexpected error")

    assert "RuntimeError" in message


MISSING_SOURCE_MODULE = """
from collections.abc import Mapping

import pytest

from wenchang.core import MemoryStore
from wenchang.storage.memory import InMemoryStorage
from wenchang.testing import TransportConformance
from wenchang.transport import InProcessClient, TransportClient


class TestMissingSource(TransportConformance):
    @pytest.fixture
    def client(self) -> TransportClient:
        return InProcessClient(MemoryStore(InMemoryStorage(), max_file_bytes=256))

    @pytest.fixture
    def scope_map(self) -> Mapping[str, str]:
        return {"user": "u-1", "org": "o-9"}

    @pytest.fixture
    def max_file_bytes(self) -> int:
        return 256

    @pytest.fixture
    def index_max_bytes(self) -> int:
        return 4096

    @pytest.fixture
    def scope_priority(self) -> tuple[str, ...]:
        return ("user", "org")

    @pytest.fixture
    def list_page_size(self) -> int:
        return 2
"""


def test_subclass_missing_fixture_reports_fixture_error(pytester: pytest.Pytester) -> None:
    """A subclass without the source fixture errors every case that takes it.

    The expected counts come from the suite's case signatures, so they track
    added cases. (AIE-1047, US1.5; AIE-1045, US11.1)
    """
    cases = [
        value
        for name, value in vars(TransportConformance).items()
        if name.startswith("test_") and callable(value)
    ]
    takes_source = sum("source" in inspect.signature(case).parameters for case in cases)
    pytester.makepyfile(test_missing_source=MISSING_SOURCE_MODULE)

    result = pytester.runpytest("-p", "no:cacheprovider")

    assert takes_source > 0
    result.assert_outcomes(passed=len(cases) - takes_source, errors=takes_source)
    result.stdout.fnmatch_lines(["*fixture 'source' not found*"])
