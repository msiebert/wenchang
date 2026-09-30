"""Tests for read-only enforcement of the system/ area in wenchang.scope.

Covers AIE-1040, US1 through US4 and the Edge Cases equivalence.
"""

import ast
import inspect
from datetime import UTC, datetime
from pathlib import Path

import pytest

from test_paths import (
    BAD_NAME_PATHS,
    CONTROL_CHAR_PATHS,
    DOT_SEGMENT_PATHS,
    MALFORMED_STRUCTURE_PATHS,
    VALID_PATHS,
    WRONG_SEGMENT_COUNT_PATHS,
)
from wenchang.core import MemoryStore
from wenchang.errors import (
    ErrorCategory,
    NotFoundError,
    NotFoundReason,
    RestrictedScopeError,
    RestrictionReason,
)
from wenchang.file_format import FileMetadata
from wenchang.paths import is_valid_path, parse_path
from wenchang.scope import SYSTEM_AREA, check_not_system, is_system_path
from wenchang.storage.memory import InMemoryStorage

pytestmark = pytest.mark.unit

SRC_DIR = Path(__file__).resolve().parent.parent / "src" / "wenchang"

US1_PRIMARY_PATH = "user/u_42/system/policy.md"

US1_ANY_SCOPE_PATHS = (
    "org/o_1/system/x.md",
    "team/t 9/system/café.md",
    "system/e/system/x.md",
)

US1_ANY_NAME_PATHS = (
    "u/e/system/..md",
    "u/e/system/a.md.md",
)

REJECTED_VALID_PATHS = (
    US1_PRIMARY_PATH,
    *US1_ANY_SCOPE_PATHS,
    *US1_ANY_NAME_PATHS,
    *(p for p in VALID_PATHS if parse_path(p).area == "system"),
)

US2_PRIMARY_PATH = "user/u_42/preferences/editor.md"

LOOKALIKE_AREAS = (
    "systems",
    "System",
    "SYSTEM",
    "system2",
    "_system",
    "system ",
    " system",
    "sys",
    chr(0x0455) + "ystem",  # Cyrillic dze
    "".join(chr(ord(c) + 0xFEE0) for c in "system"),  # fullwidth
    "system" + chr(0x200B),  # zero-width space
    "system" + chr(0x00A0),  # no-break space
    "system" + chr(0x0301),  # combining acute accent
)

LOOKALIKE_PATHS = tuple(f"u/e/{area}/x.md" for area in LOOKALIKE_AREAS)

NON_AREA_SYSTEM_PATHS = (
    "system/e/a/x.md",
    "u/system/a/x.md",
    "u/e/a/system.md",
)

EMOJI_PATH = "\U0001f600/\U0001f600/\U0001f600/\U0001f600.md"

ALLOWED_VALID_PATHS = (
    US2_PRIMARY_PATH,
    *LOOKALIKE_PATHS,
    *NON_AREA_SYSTEM_PATHS,
    *(p for p in VALID_PATHS if parse_path(p).area != "system"),
    EMOJI_PATH,
)

MALFORMED_PATHS = (
    *MALFORMED_STRUCTURE_PATHS,
    *DOT_SEGMENT_PATHS,
    *CONTROL_CHAR_PATHS,
    *WRONG_SEGMENT_COUNT_PATHS,
    *BAD_NAME_PATHS,
    "u/e/system/x.txt",
    "u/e/system/",
    "u/e/system/sub/x.md",
    "u/e/sys/tem/x.md",
    "/u/e/system/x.md",
    "u/e/system/x.md/",
    "u/e/system/x.md\n",
    "\tu/e/system/x.md",
    "u/e/system/x.md\x00",
)

EXTRA_PREDICATE_INPUTS = (
    "\x00\x00\x00",
    "a" * 10000,
    "///",
)

ALL_PATHS = (*REJECTED_VALID_PATHS, *ALLOWED_VALID_PATHS, *MALFORMED_PATHS)


def test_system_area_constant() -> None:
    """SYSTEM_AREA is exactly "system". (AIE-1040, FR-001)"""
    assert SYSTEM_AREA == "system"


def test_check_not_system_rejects_primary_path() -> None:
    """A write under user/u_42/system/ raises a permanent SYSTEM_READ_ONLY
    RestrictedScopeError naming scope "user" and no role. (AIE-1040, AIE-1042, US1.1)"""
    with pytest.raises(RestrictedScopeError) as exc_info:
        check_not_system(US1_PRIMARY_PATH)
    err = exc_info.value
    assert err.path == US1_PRIMARY_PATH
    assert err.scope == "user"
    assert err.reason is RestrictionReason.SYSTEM_READ_ONLY
    assert err.category is ErrorCategory.PERMANENT
    assert err.required_roles is None
    assert getattr(err, "required_roles", None) is None
    assert is_system_path(US1_PRIMARY_PATH) is True


@pytest.mark.parametrize("path", US1_ANY_SCOPE_PATHS)
def test_check_not_system_rejects_any_scope_and_entity(path: str) -> None:
    """A system area under any scope and entity ID is rejected, naming that
    path's first segment as the scope. (AIE-1040, US1.2)"""
    with pytest.raises(RestrictedScopeError) as exc_info:
        check_not_system(path)
    err = exc_info.value
    assert err.path == path
    assert err.scope == path.split("/")[0]
    assert err.reason is RestrictionReason.SYSTEM_READ_ONLY
    assert is_system_path(path) is True


@pytest.mark.parametrize("path", US1_ANY_NAME_PATHS)
def test_check_not_system_rejects_any_name(path: str) -> None:
    """Any valid last segment under system is rejected. (AIE-1040, US1.3)"""
    assert is_valid_path(path)
    with pytest.raises(RestrictedScopeError) as exc_info:
        check_not_system(path)
    assert exc_info.value.reason is RestrictionReason.SYSTEM_READ_ONLY
    assert is_system_path(path) is True


def test_valid_paths_system_entry_rejected() -> None:
    """The system/x/system/a.md entry of VALID_PATHS has area system and is
    rejected with scope "system". (AIE-1040, US1.2)"""
    path = "system/x/system/a.md"
    assert path in VALID_PATHS
    with pytest.raises(RestrictedScopeError) as exc_info:
        check_not_system(path)
    assert exc_info.value.scope == "system"
    assert is_system_path(path) is True


def test_rejection_message_names_scope_and_read_only() -> None:
    """The error message names the scope and says the area is read-only.
    (AIE-1040, US1.4)"""
    with pytest.raises(RestrictedScopeError) as exc_info:
        check_not_system(US1_PRIMARY_PATH)
    err = exc_info.value
    assert f"scope {err.scope}" in str(err)
    assert "read-only" in str(err)


def test_check_not_system_takes_only_path() -> None:
    """check_not_system's only parameter is path; no identity or role
    argument exists. (AIE-1040, US1.5)"""
    assert list(inspect.signature(check_not_system).parameters) == ["path"]


def test_check_not_system_allows_primary_path() -> None:
    """A non-system area returns None and is not a system path.
    (AIE-1040, US2.1)"""
    assert check_not_system(US2_PRIMARY_PATH) is None
    assert is_system_path(US2_PRIMARY_PATH) is False


@pytest.mark.parametrize("path", LOOKALIKE_PATHS)
def test_lookalike_areas_allowed(path: str) -> None:
    """Areas resembling system are allowed: the match is exact, with no case
    folding or Unicode normalization. (AIE-1040, US2.2)"""
    assert is_valid_path(path)
    assert parse_path(path).area != "system"
    assert check_not_system(path) is None
    assert is_system_path(path) is False


@pytest.mark.parametrize("path", NON_AREA_SYSTEM_PATHS)
def test_system_outside_area_position_allowed(path: str) -> None:
    """ "system" as scope, entity ID, or name is not restricted.
    (AIE-1040, US2.3)"""
    assert check_not_system(path) is None
    assert is_system_path(path) is False


@pytest.mark.parametrize("path", [p for p in VALID_PATHS if parse_path(p).area != "system"])
def test_other_valid_paths_allowed(path: str) -> None:
    """Every VALID_PATHS entry whose area is not system is allowed.
    (AIE-1040, US2.1)"""
    assert check_not_system(path) is None
    assert is_system_path(path) is False


@pytest.mark.parametrize("path", MALFORMED_PATHS)
def test_malformed_path_raises_invalid_path(path: str) -> None:
    """A malformed path raises NotFoundError(INVALID_PATH) before the system
    check, never RestrictedScopeError or ValueError. (AIE-1040, US3.1)"""
    assert not is_valid_path(path)
    try:
        check_not_system(path)
    except NotFoundError as err:
        assert err.reason is NotFoundReason.INVALID_PATH
        assert err.path == path
    except (RestrictedScopeError, ValueError) as err:
        pytest.fail(f"expected NotFoundError, got {type(err).__name__}: {err}")
    else:
        pytest.fail("expected NotFoundError, got no exception")


@pytest.mark.parametrize("path", (*MALFORMED_PATHS, *EXTRA_PREDICATE_INPUTS))
def test_is_system_path_false_for_malformed(path: str) -> None:
    """is_system_path returns False and never raises for malformed input.
    (AIE-1040, US3.2)"""
    assert is_system_path(path) is False


def test_is_system_path_false_for_non_str() -> None:
    """is_system_path returns False, without raising, for a non-str.
    (AIE-1040, AIE-1042, review finding 1)"""
    assert is_system_path(None) is False  # pyright: ignore[reportArgumentType]
    assert is_system_path(5) is False  # pyright: ignore[reportArgumentType]


def test_emoji_path_allowed() -> None:
    """An all-emoji valid path is not system. (AIE-1040, US3.2)"""
    assert is_valid_path(EMOJI_PATH)
    assert is_system_path(EMOJI_PATH) is False
    assert check_not_system(EMOJI_PATH) is None


@pytest.mark.parametrize("path", ALL_PATHS)
def test_check_raises_restricted_iff_is_system_path(path: str) -> None:
    """check_not_system raises RestrictedScopeError iff is_system_path is
    True, and repeated calls agree. (AIE-1040, Edge Cases)"""
    predicate = is_system_path(path)
    assert is_system_path(path) is predicate

    def _restricted() -> bool:
        try:
            check_not_system(path)
        except RestrictedScopeError:
            return True
        except NotFoundError:
            return False
        return False

    first = _restricted()
    assert _restricted() is first
    assert first is predicate


def test_scope_named_system_not_restricted() -> None:
    """A scope literally named system is not restricted. (AIE-1040, Edge Cases)"""
    assert check_not_system("system/e/notes/x.md") is None
    assert is_system_path("system/e/notes/x.md") is False


def test_core_accepts_system_paths_for_seeding() -> None:
    """MemoryStore performs no system/ check: create, replace, append_line,
    replace_fact, and delete_file all succeed under system/. (AIE-1040, US4.1)"""
    path = "org/o_1/system/policy.md"
    storage = InMemoryStorage()
    store = MemoryStore(storage, clock=lambda: datetime(2025, 3, 1, 12, 0, 0, tzinfo=UTC))
    meta = FileMetadata(
        description="policy",
        aliases=(),
        sources=frozenset({"seed"}),
        last_updated=datetime(2024, 1, 1, tzinfo=UTC),
    )

    try:
        created = store.write_file(path, "- [stated] a\n", meta, None, source="seed")
        replaced = store.write_file(path, "- [stated] b\n", meta, created.version, source="seed")
        appended = store.append_line(path, "- [stated] c", replaced.version, source="seed")
        edited = store.replace_fact(
            path, "- [stated] c", "- [stated] d", appended.version, source="seed"
        )
        assert store.read_file(path).content == edited.content
        store.delete_file(path, edited.version)
    except RestrictedScopeError as err:
        pytest.fail(f"core must not restrict system/ writes: {err}")

    assert storage.get(path) is None


def _imported_modules(source_path: Path) -> set[str]:
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def _imports_any(names: set[str], module: str) -> bool:
    return any(name == module or name.startswith(f"{module}.") for name in names)


def test_scope_does_not_import_core_or_storage() -> None:
    """wenchang.scope imports neither wenchang.core nor wenchang.storage.
    (AIE-1040, FR-006)"""
    names = _imported_modules(SRC_DIR / "scope.py")
    assert not _imports_any(names, "wenchang.core")
    assert not _imports_any(names, "wenchang.storage")


def test_core_does_not_import_scope() -> None:
    """wenchang.core does not import wenchang.scope. (AIE-1040, FR-006)"""
    names = _imported_modules(SRC_DIR / "core.py")
    assert not _imports_any(names, "wenchang.scope")
