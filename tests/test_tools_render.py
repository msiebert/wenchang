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
        _UnsortableRolesError,
        _BytesContentError,
    ],
    ids=["no-category", "str-category", "unsortable-roles", "bytes-content"],
)
def test_render_error_never_raises_on_hostile_wenchang_error(
    make: Callable[[], WenchangError],
) -> None:
    """AIE-1044, US7.12: a WenchangError subclass with a missing or wrongly typed
    category or payload field renders without raising, JSON-safe, with the
    error, category, and message keys.
    """
    out = render_error(make())

    assert {"error", "category", "message"} <= out.keys()
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
