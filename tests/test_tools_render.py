"""Tests for render_result and render_error in wenchang.tools.

Covers AIE-1044, US7.1 through US7.12 (including US7.5a).
"""

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from typing import cast

import pytest

from wenchang.core import CappedPrefix, FileEntry, ListCursor, ListPage, MemoryFile, MemoryIndex
from wenchang.errors import (
    BackendUnavailableError,
    InvalidArgumentError,
    NotFoundError,
    NotFoundReason,
    OversizeWriteError,
    RecoverableError,
    ReplaceFactMatchError,
    ResolverFailureError,
    RestrictedScopeError,
    RestrictionReason,
    TransientReason,
    VersionConflictError,
    WenchangError,
)
from wenchang.file_format import (
    LAST_UPDATED_KEY,
    FileMetadata,
    MetadataFormatError,
    metadata_to_map,
)
from wenchang.tools import render_error, render_result
from wenchang.version_token import VersionToken

pytestmark = pytest.mark.unit

_PATH = "user/u-1/notes/a.md"
_LAST_UPDATED = datetime(2026, 10, 2, 12, 0, 0, tzinfo=timezone(timedelta(hours=2)))
_METADATA = FileMetadata(
    description="Notes about a",
    aliases=("b", "a"),
    sources=frozenset({"z", "y"}),
    last_updated=_LAST_UPDATED,
)
_VERSION = VersionToken("v-17")


def _round_trips(out: dict[str, object]) -> None:
    assert json.loads(json.dumps(out)) == out


def _entry(path: str, version: str = "v-1", description: str = "d") -> FileEntry:
    metadata = FileMetadata(
        description=description,
        aliases=("x",),
        sources=frozenset({"s2", "s1"}),
        last_updated=datetime(2026, 1, 1, tzinfo=UTC),
    )
    return FileEntry(path, metadata, VersionToken(version))


def _entry_fields(
    path: str, scope: str | None, area: str | None, name: str | None
) -> dict[str, object]:
    return {
        "path": path,
        "scope": scope,
        "area": area,
        "name": name,
        "version": "v-1",
        "description": "d",
        "aliases": ["x"],
        "sources": ["s1", "s2"],
        "last_updated": "2026-01-01T00:00:00Z",
    }


# --- render_result ---------------------------------------------------------


def test_render_memory_file() -> None:
    """AIE-1044, US7.1: a MemoryFile renders as flat file fields plus content."""
    file = MemoryFile(path=_PATH, content="- [stated] x\n", metadata=_METADATA, version=_VERSION)

    out = render_result(file)

    assert out == {
        "path": _PATH,
        "scope": "user",
        "area": "notes",
        "name": "a",
        "content": "- [stated] x\n",
        "version": "v-17",
        "description": "Notes about a",
        "aliases": ["b", "a"],
        "sources": ["y", "z"],
        "last_updated": "2026-10-02T10:00:00Z",
    }
    assert type(out["version"]) is str
    assert out["last_updated"] == metadata_to_map(_METADATA)[LAST_UPDATED_KEY]


def test_render_memory_file_with_empty_content() -> None:
    """AIE-1044, US7.1: an empty body renders as content "", not omitted or None."""
    file = MemoryFile(path=_PATH, content="", metadata=_METADATA, version=_VERSION)

    out = render_result(file)

    assert out["content"] == ""
    assert json.loads(json.dumps(out)) == out
    _round_trips(out)


def test_render_list_page_with_cursor() -> None:
    """AIE-1044, US7.2: a ListPage renders entries in page order without content."""
    page = ListPage(
        entries=(_entry("user/u-1/notes/b.md"), _entry("user/u-1/notes/a.md")),
        next_cursor=ListCursor("abc"),
    )

    out = render_result(page)

    assert out == {
        "entries": [
            _entry_fields("user/u-1/notes/b.md", "user", "notes", "b"),
            _entry_fields("user/u-1/notes/a.md", "user", "notes", "a"),
        ],
        "next_cursor": "abc",
    }
    assert type(out["next_cursor"]) is str
    _round_trips(out)


def test_render_list_page_without_cursor() -> None:
    """AIE-1044, US7.2: a ListPage with no next cursor renders next_cursor None."""
    out = render_result(ListPage(entries=(), next_cursor=None))

    assert out == {"entries": [], "next_cursor": None}
    _round_trips(out)


def test_render_memory_index_with_capped_prefixes() -> None:
    """AIE-1044, US7.3: capped rows carry prefix, scope, area, and omitted."""
    index = MemoryIndex(
        entries=(_entry("org/o-9/system/rules.md"),),
        capped=(
            CappedPrefix("user/u-1/notes/", 3),
            CappedPrefix("org/o-9/", 2),
            CappedPrefix("team/", 1),
        ),
    )

    out = render_result(index)

    assert out == {
        "entries": [_entry_fields("org/o-9/system/rules.md", "org", "system", "rules")],
        "capped": [
            {"prefix": "user/u-1/notes/", "scope": "user", "area": "notes", "omitted": 3},
            {"prefix": "org/o-9/", "scope": "org", "area": None, "omitted": 2},
            {"prefix": "team/", "scope": "team", "area": None, "omitted": 1},
        ],
    }
    _round_trips(out)


def test_render_empty_memory_index() -> None:
    """AIE-1044, US7.3: an empty MemoryIndex renders empty entries and capped."""
    out = render_result(MemoryIndex())

    assert out == {"entries": [], "capped": []}
    _round_trips(out)


def test_render_none() -> None:
    """AIE-1044, US7.4: None (the delete_file result) renders as ok."""
    out = render_result(None)

    assert out == {"ok": True}
    _round_trips(out)


@pytest.mark.parametrize(
    "value",
    ["text", {"path": _PATH}, _entry(_PATH)],
    ids=["str", "dict", "file-entry"],
)
def test_render_unsupported_value_raises_type_error(value: object) -> None:
    """AIE-1044, US7.5: any value other than the four supported types is a TypeError."""
    with pytest.raises(TypeError):
        render_result(value)  # pyright: ignore[reportArgumentType]


def test_render_malformed_entry_path_renders_none_segments() -> None:
    """AIE-1044, US7.5a: a malformed entry path renders None segments without raising."""
    page = ListPage(entries=(_entry("not-a-path"),), next_cursor=None)

    out = render_result(page)

    assert out == {
        "entries": [_entry_fields("not-a-path", None, None, None)],
        "next_cursor": None,
    }
    _round_trips(out)


# --- render_error: taxonomy ------------------------------------------------


def _assert_error(exc: WenchangError, payload: dict[str, object]) -> dict[str, object]:
    out = render_error(exc)
    expected: dict[str, object] = {
        "error": type(exc).__name__,
        "category": exc.category.value,
        "message": str(exc),
        **payload,
    }
    assert out == expected
    assert list(out)[:3] == ["error", "category", "message"]
    _round_trips(out)
    return out


def test_render_version_conflict_error() -> None:
    """AIE-1044, US7.6/US7.7: a version conflict carries path, content, and version."""
    exc = VersionConflictError(_PATH, "current body", VersionToken("v-9"))

    out = _assert_error(exc, {"path": _PATH, "content": "current body", "version": "v-9"})

    assert out["category"] == "recoverable"
    assert type(out["version"]) is str


def test_render_oversize_write_error() -> None:
    """AIE-1044, US7.6/US7.7: an oversize write carries path, size, and limit as ints."""
    out = _assert_error(
        OversizeWriteError(_PATH, 20000, 16384), {"path": _PATH, "size": 20000, "limit": 16384}
    )

    assert type(out["size"]) is int
    assert type(out["limit"]) is int


def test_render_replace_fact_match_error() -> None:
    """AIE-1044, US7.6/US7.7: a match error carries path, content, version, match_count."""
    exc = ReplaceFactMatchError(_PATH, "body", VersionToken("v-3"), 2)

    _assert_error(exc, {"path": _PATH, "content": "body", "version": "v-3", "match_count": 2})


@pytest.mark.parametrize(
    ("reason", "value"),
    [(NotFoundReason.FILE_ABSENT, "file_absent"), (NotFoundReason.INVALID_PATH, "invalid_path")],
)
def test_render_not_found_error(reason: NotFoundReason, value: str) -> None:
    """AIE-1044, US7.6/US7.8: NotFoundError carries path and the reason's value."""
    out = _assert_error(NotFoundError(_PATH, reason), {"path": _PATH, "reason": value})

    assert type(out["reason"]) is str


@pytest.mark.parametrize(
    ("reason", "value"),
    [(TransientReason.TIMEOUT, "timeout"), (TransientReason.UNAVAILABLE, "unavailable")],
)
def test_render_backend_unavailable_error(reason: TransientReason, value: str) -> None:
    """AIE-1044, US7.6/US7.8: BackendUnavailableError is transient with its reason."""
    out = _assert_error(BackendUnavailableError(reason), {"reason": value})

    assert out["category"] == "transient"


def test_render_restricted_scope_role_required() -> None:
    """AIE-1044, US7.6/US7.9: ROLE_REQUIRED carries sorted required_roles."""
    exc = RestrictedScopeError(
        "org/o-9/notes/a.md",
        "org",
        RestrictionReason.ROLE_REQUIRED,
        required_roles=frozenset({"owner", "admin", "editor", "viewer", "auditor"}),
    )

    out = _assert_error(
        exc,
        {
            "path": "org/o-9/notes/a.md",
            "reason": "role_required",
            "scope": "org",
            "required_roles": ["admin", "auditor", "editor", "owner", "viewer"],
        },
    )

    assert out["category"] == "permanent"


@pytest.mark.parametrize(
    ("reason", "value"),
    [
        (RestrictionReason.SYSTEM_READ_ONLY, "system_read_only"),
        (RestrictionReason.NOT_GRANTED, "not_granted"),
    ],
)
def test_render_restricted_scope_without_roles(reason: RestrictionReason, value: str) -> None:
    """AIE-1044, US7.6/US7.9: other restriction reasons have no required_roles key."""
    exc = RestrictedScopeError("user/u-1/system/x.md", "user", reason)

    out = _assert_error(exc, {"path": "user/u-1/system/x.md", "reason": value, "scope": "user"})

    assert "required_roles" not in out


def test_render_invalid_argument_error() -> None:
    """AIE-1044, US7.6/US7.10: InvalidArgumentError carries argument and is recoverable."""
    out = _assert_error(InvalidArgumentError("scope", "bad scope"), {"argument": "scope"})

    assert out["category"] == "recoverable"


@pytest.mark.parametrize("detail", ["", "Resolver expired."])
def test_render_resolver_failure_error(detail: str) -> None:
    """AIE-1044, US7.6/US7.10: ResolverFailureError renders only error, category, message."""
    out = _assert_error(ResolverFailureError(detail), {})

    assert set(out) == {"error", "category", "message"}
    assert out["category"] == "permanent"


# --- render_error: outside the taxonomy -----------------------------------


@pytest.mark.parametrize(
    "exc",
    [
        MetadataFormatError("aliases", "must be a JSON array"),
        UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"),
    ],
    ids=["metadata-format", "unicode-decode"],
)
def test_render_data_integrity_errors(exc: Exception) -> None:
    """AIE-1044, US7.11: data-integrity errors render as internal with str(exc)."""
    out = render_error(exc)

    assert out == {"error": type(exc).__name__, "category": "internal", "message": str(exc)}
    _round_trips(out)


@pytest.mark.parametrize(
    "exc",
    [ValueError("secret detail"), RuntimeError("boom"), KeyError("k"), TypeError("t")],
    ids=["value-error", "runtime-error", "key-error", "type-error"],
)
def test_render_other_exceptions_use_fixed_message(exc: Exception) -> None:
    """AIE-1044, US7.11: off-contract exceptions render the fixed "internal error"."""
    out = render_error(exc)

    assert out == {
        "error": type(exc).__name__,
        "category": "internal",
        "message": "internal error",
    }
    _round_trips(out)


# --- render_error: hostile exceptions --------------------------------------


class _RaisingName(type):
    @property
    def __name__(cls) -> str:  # pyright: ignore[reportIncompatibleVariableOverride]
        raise RuntimeError("no name")


class _BadStrConflict(VersionConflictError):
    def __str__(self) -> str:
        raise RuntimeError("no str")


class _BadStrMetadata(MetadataFormatError):
    def __str__(self) -> str:
        raise RuntimeError("no str")


class _BadStrDecode(UnicodeDecodeError):
    def __str__(self) -> str:
        raise RuntimeError("no str")


class _BadStrRuntime(RuntimeError):
    def __str__(self) -> str:
        raise RuntimeError("no str")


class _NamelessRuntime(RuntimeError, metaclass=_RaisingName):
    pass


class _NamelessNotFound(NotFoundError, metaclass=_RaisingName):
    pass


def test_hostile_str_on_wenchang_error_falls_back() -> None:
    """AIE-1044, US7.12: a WenchangError whose __str__ raises renders "<unreadable>"."""
    exc = _BadStrConflict(_PATH, "body", VersionToken("v-1"))

    out = render_error(exc)

    assert out["error"] == "_BadStrConflict"
    assert out["category"] == "recoverable"
    assert out["message"] == "<unreadable>"
    assert type(out["message"]) is str
    assert out["path"] == _PATH
    assert out["content"] == "body"
    assert out["version"] == "v-1"
    _round_trips(out)


@pytest.mark.parametrize(
    "exc",
    [
        _BadStrMetadata("aliases", "bad"),
        _BadStrDecode("utf-8", b"\xff", 0, 1, "invalid start byte"),
    ],
    ids=["metadata-format", "unicode-decode"],
)
def test_hostile_str_on_data_integrity_error_falls_back(exc: Exception) -> None:
    """AIE-1044, US7.12: a data-integrity error whose __str__ raises renders "<unreadable>"."""
    out = render_error(exc)

    assert out == {"error": type(exc).__name__, "category": "internal", "message": "<unreadable>"}
    _round_trips(out)


def test_hostile_str_on_other_exception_never_raises() -> None:
    """AIE-1044, US7.12: an off-contract exception whose __str__ raises still renders."""
    out = render_error(_BadStrRuntime("x"))

    assert out == {"error": "_BadStrRuntime", "category": "internal", "message": "internal error"}
    _round_trips(out)


def test_hostile_type_name_on_other_exception_falls_back() -> None:
    """AIE-1044, US7.12: a type whose __name__ raises renders "<unnamed>"."""
    out = render_error(_NamelessRuntime("x"))

    assert out == {"error": "<unnamed>", "category": "internal", "message": "internal error"}
    assert type(out["error"]) is str
    _round_trips(out)


def test_hostile_type_name_on_wenchang_error_falls_back() -> None:
    """AIE-1044, US7.12: a WenchangError whose type __name__ raises renders "<unnamed>"."""
    exc = _NamelessNotFound(_PATH, NotFoundReason.FILE_ABSENT)

    out = render_error(exc)

    assert out == {
        "error": "<unnamed>",
        "category": "recoverable",
        "message": str(exc),
        "path": _PATH,
        "reason": "file_absent",
    }
    _round_trips(out)


# --- render_error never raises on hostile WenchangError subclasses ------------


class _NoCategoryError(WenchangError):
    """A WenchangError subclass that never sets category."""

    guidance = "Guidance."


class _StrCategoryError(RecoverableError):
    """A WenchangError subclass whose category is a plain str, not an ErrorCategory."""

    category = "notenum"  # pyright: ignore[reportAssignmentType, reportIncompatibleVariableOverride]


class _UnsortableRolesError(RecoverableError):
    """A WenchangError carrying required_roles whose members cannot be sorted together."""

    def __init__(self) -> None:
        self.required_roles = cast(frozenset[str], frozenset({1, "a"}))
        super().__init__("unsortable roles")


class _BytesContentError(RecoverableError):
    """A WenchangError carrying non-JSON content."""

    def __init__(self) -> None:
        self.content = cast(str, b"x")
        super().__init__("bytes content")


@pytest.mark.parametrize(
    "make",
    [
        lambda: _NoCategoryError("no category"),
        lambda: _StrCategoryError("str category"),
    ],
    ids=["no-category", "str-category"],
)
def test_render_error_without_valid_category_renders_internal(
    make: Callable[[], WenchangError],
) -> None:
    """AIE-1044, US7.12: a WenchangError subclass with a missing or non-enum
    category renders as a fixed internal error without raising.
    """
    exc = make()

    out = render_error(exc)

    assert out == {
        "error": type(exc).__name__,
        "category": "internal",
        "message": "internal error",
    }
    _round_trips(out)


@pytest.mark.parametrize(
    ("make", "dropped"),
    [(_UnsortableRolesError, "required_roles"), (_BytesContentError, "content")],
    ids=["unsortable-roles", "bytes-content"],
)
def test_render_error_drops_wrongly_typed_payload_field(
    make: Callable[[], WenchangError], dropped: str
) -> None:
    """AIE-1044, US7.12: a WenchangError with a wrongly typed payload field renders
    without raising, keeps its category, and omits the bad field.
    """
    out = render_error(make())

    assert dropped not in out
    assert out["category"] == "recoverable"
    assert all(type(out[key]) is str for key in ("error", "category", "message"))
    _round_trips(out)


# --- render_result never raises on hostile metadata ---------------------------


def _hostile_metadata() -> FileMetadata:
    return FileMetadata(
        description="d",
        aliases=cast(tuple[str, ...], ("b", datetime(2026, 1, 1, tzinfo=UTC))),
        sources=cast(frozenset[str], frozenset({"s", 1})),
        last_updated=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_render_memory_file_drops_non_str_metadata_members() -> None:
    """AIE-1044, US7.5: a MemoryFile whose aliases hold a datetime and sources an
    int renders without raising, drops the bad members, and round-trips JSON.
    """
    file = MemoryFile(_PATH, "", _hostile_metadata(), _VERSION)

    out = render_result(file)

    assert out["aliases"] == ["b"]
    assert out["sources"] == ["s"]
    assert out["last_updated"] == "2026-01-01T00:00:00Z"
    _round_trips(out)


def test_render_list_page_drops_non_str_metadata_members() -> None:
    """AIE-1044, US7.5a: a ListPage entry with hostile metadata renders without
    raising, drops the bad members, and round-trips JSON.
    """
    page = ListPage((FileEntry(_PATH, _hostile_metadata(), _VERSION),), None)

    out = render_result(page)

    entries = cast(list[dict[str, object]], out["entries"])
    assert entries[0]["aliases"] == ["b"]
    assert entries[0]["sources"] == ["s"]
    _round_trips(out)


# --- render_result never raises on wrongly typed core fields ------------------


def _tuple_description_metadata() -> FileMetadata:
    return FileMetadata(
        description=cast(str, ("d1", "d2")),
        aliases=("x",),
        sources=frozenset({"s"}),
        last_updated=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _render_entry(entry: FileEntry) -> dict[str, object]:
    out = render_result(ListPage((entry,), None))
    _round_trips(out)
    entries = cast(list[dict[str, object]], out["entries"])
    return entries[0]


def test_render_file_entry_drops_non_str_version() -> None:
    """AIE-1044, US7.5a: a FileEntry whose version is an int renders without
    raising, omits version, and keeps its well-typed fields.
    """
    entry = FileEntry(_PATH, _METADATA, cast(VersionToken, 5))

    out = _render_entry(entry)

    assert "version" not in out
    assert out["path"] == _PATH
    assert out["description"] == "Notes about a"


def test_render_file_entry_drops_non_str_path() -> None:
    """AIE-1044, US7.5a: a FileEntry whose path is an int renders without
    raising, omits path, and keeps its well-typed fields.
    """
    entry = FileEntry(cast(str, 5), _METADATA, _VERSION)

    out = _render_entry(entry)

    assert "path" not in out
    assert out["version"] == "v-17"
    assert out["description"] == "Notes about a"


def test_render_list_page_drops_non_str_next_cursor() -> None:
    """AIE-1044, US7.5a: a ListPage whose next_cursor is an int renders without
    raising, omits next_cursor, and keeps its entries.
    """
    page = ListPage((_entry(_PATH),), cast(ListCursor, 7))

    out = render_result(page)

    assert "next_cursor" not in out
    assert out["entries"] == [_entry_fields(_PATH, "user", "notes", "a")]
    _round_trips(out)


def test_render_memory_file_drops_bytes_content() -> None:
    """AIE-1044, US7.5a: a MemoryFile whose content is bytes renders without
    raising, omits content, and keeps its well-typed fields.
    """
    file = MemoryFile(_PATH, cast(str, b"x"), _METADATA, _VERSION)

    out = render_result(file)

    assert "content" not in out
    assert out["path"] == _PATH
    assert out["version"] == "v-17"
    _round_trips(out)


def test_render_memory_file_drops_tuple_description() -> None:
    """AIE-1044, US7.5a: a MemoryFile whose metadata description is a tuple
    renders without raising, omits description, and keeps its well-typed fields.
    """
    file = MemoryFile(_PATH, "body", _tuple_description_metadata(), _VERSION)

    out = render_result(file)

    assert "description" not in out
    assert out["content"] == "body"
    assert out["aliases"] == ["x"]
    _round_trips(out)


def test_render_file_entry_drops_tuple_description() -> None:
    """AIE-1044, US7.5a: a FileEntry whose metadata description is a tuple
    renders without raising, omits description, and keeps its well-typed fields.
    """
    entry = FileEntry(_PATH, _tuple_description_metadata(), _VERSION)

    out = _render_entry(entry)

    assert "description" not in out
    assert out["path"] == _PATH
    assert out["sources"] == ["s"]


# --- render_result never raises on wrongly typed container fields -------------


def _metadata_with(
    aliases: object = ("x",),
    sources: object = frozenset({"s"}),
    last_updated: object = datetime(2026, 1, 1, tzinfo=UTC),
) -> FileMetadata:
    metadata = FileMetadata(
        description="d",
        aliases=cast(tuple[str, ...], aliases),
        sources=cast(frozenset[str], sources),
        last_updated=datetime(2026, 1, 1, tzinfo=UTC),
    )
    # Bypasses __post_init__, which rejects a non-datetime last_updated.
    object.__setattr__(metadata, "last_updated", last_updated)
    return metadata


def test_render_memory_file_drops_none_aliases() -> None:
    """AIE-1044, US7.5a: metadata aliases of None renders without raising, omits
    aliases, and keeps the other fields.
    """
    file = MemoryFile(_PATH, "body", _metadata_with(aliases=None), _VERSION)

    out = render_result(file)

    assert "aliases" not in out
    assert out["sources"] == ["s"]
    assert out["description"] == "d"
    assert out["last_updated"] == "2026-01-01T00:00:00Z"
    assert out["content"] == "body"
    _round_trips(out)


def test_render_memory_file_drops_none_sources() -> None:
    """AIE-1044, US7.5a: metadata sources of None renders without raising, omits
    sources, and keeps the other fields.
    """
    file = MemoryFile(_PATH, "body", _metadata_with(sources=None), _VERSION)

    out = render_result(file)

    assert "sources" not in out
    assert out["aliases"] == ["x"]
    assert out["description"] == "d"
    _round_trips(out)


def test_render_memory_file_with_none_metadata() -> None:
    """AIE-1044, US7.5a: a MemoryFile with metadata None renders path, content, and
    version, and omits every metadata field.
    """
    file = MemoryFile(_PATH, "body", cast(FileMetadata, None), _VERSION)

    out = render_result(file)

    for key in ("aliases", "sources", "description", "last_updated"):
        assert key not in out
    assert out["path"] == _PATH
    assert out["content"] == "body"
    assert out["version"] == "v-17"
    _round_trips(out)


@pytest.mark.parametrize("last_updated", [None, "x"], ids=["none", "str"])
def test_render_memory_file_drops_non_datetime_last_updated(last_updated: object) -> None:
    """AIE-1044, US7.5a: a non-datetime last_updated renders without raising,
    omits last_updated, and keeps the other fields.
    """
    file = MemoryFile(_PATH, "body", _metadata_with(last_updated=last_updated), _VERSION)

    out = render_result(file)

    assert "last_updated" not in out
    assert out["aliases"] == ["x"]
    assert out["description"] == "d"
    _round_trips(out)


@pytest.mark.parametrize("entries", [None, 5], ids=["none", "int"])
def test_render_list_page_with_non_iterable_entries(entries: object) -> None:
    """AIE-1044, US7.5a: a ListPage whose entries is not a tuple renders entries
    as [] without raising.
    """
    page = ListPage(cast(tuple[FileEntry, ...], entries), None)

    out = render_result(page)

    assert out["entries"] == []
    assert out["next_cursor"] is None
    _round_trips(out)


@pytest.mark.parametrize("field", ["entries", "capped"])
def test_render_memory_index_with_none_field(field: str) -> None:
    """AIE-1044, US7.5a: a MemoryIndex whose entries or capped is None renders
    that field as [] without raising.
    """
    index = MemoryIndex()
    # Bypasses __post_init__ validation, as a hostile caller could.
    object.__setattr__(index, field, None)

    out = render_result(index)

    assert out == {"entries": [], "capped": []}
    _round_trips(out)


def _bad_cap(field: str, value: object) -> Callable[[], CappedPrefix]:
    def make() -> CappedPrefix:
        cap = CappedPrefix("org/o-9/", 1)
        # Bypasses __post_init__, which rejects wrongly typed fields.
        object.__setattr__(cap, field, value)
        return cap

    return make


@pytest.mark.parametrize(
    "make_bad",
    [
        lambda: None,
        _bad_cap("prefix", 5),
        _bad_cap("omitted", True),
        _bad_cap("omitted", "3"),
    ],
    ids=["none-member", "int-prefix", "bool-omitted", "str-omitted"],
)
def test_render_memory_index_skips_bad_capped_rows(make_bad: Callable[[], object]) -> None:
    """AIE-1044, US7.5a: a capped member that is None or has a non-str prefix is
    skipped without raising; valid rows still render.
    """
    index = MemoryIndex()
    # Bypasses __post_init__ validation, as a hostile caller could.
    object.__setattr__(index, "capped", (make_bad(), CappedPrefix("user/u-1/notes/", 2)))

    out = render_result(index)

    assert out["capped"] == [
        {"prefix": "user/u-1/notes/", "scope": "user", "area": "notes", "omitted": 2}
    ]
    _round_trips(out)


def test_render_memory_file_drops_naive_last_updated() -> None:
    """AIE-1044, US7.5a: a naive last_updated renders without raising and omits
    last_updated.
    """
    metadata = _metadata_with(last_updated=datetime(2026, 1, 1))
    file = MemoryFile(_PATH, "body", metadata, _VERSION)

    out = render_result(file)

    assert "last_updated" not in out
    assert out["description"] == "d"
    _round_trips(out)
