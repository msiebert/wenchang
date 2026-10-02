"""Helper-level self-tests for the transport conformance harness.

Covers AIE-1047: US1.6 (sentinel helpers) and US2.0-2.8 (expect_error, canonical
readers, probe_path, require_fresh, _call). Each failing call is expected to raise
pytest.fail with a message starting "{name}: {label}: " and containing the key phrase.
"""

import inspect
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta

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
    canonical_entry,
    canonical_file,
    canonical_index,
    canonical_page,
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

    assert "bad field" in message or "wrong result type" in message


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
