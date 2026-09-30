"""Tests for building and parsing memory paths from scope and entity ID.

Covers AIE-1041.
"""

import ast
import dataclasses
import re
import unicodedata
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
from wenchang.paths import (
    PathParts,
    build_path,
    build_prefix,
    is_valid_path,
    is_valid_prefix,
    parse_path,
)

pytestmark = pytest.mark.unit

PATHS_SOURCE = Path(__file__).resolve().parent.parent / "src" / "wenchang" / "paths.py"

SEGMENT_ARGS = ("scope", "entity_id", "area")
BUILD_PATH_ARGS = (*SEGMENT_ARGS, "name")

ZERO_WIDTH_SPACE = chr(0x200B)
LINE_SEPARATOR = chr(0x2028)
PARAGRAPH_SEPARATOR = chr(0x2029)
LONE_SURROGATE = chr(0xD800)
EMOJI = chr(0x1F600)
NFC_CAFE = unicodedata.normalize("NFC", "cafe" + chr(0x0301))
NFD_CAFE = unicodedata.normalize("NFD", NFC_CAFE)

INVALID_SEGMENT_VALUES = (
    "",
    ".",
    "..",
    "/",
    "a/b",
    "a/",
    "/a",
    "a\\b",
    "\t",
    "a\nb",
    "\x00",
    "a\x7f",
    "\x85",
)

NON_CC_SEGMENT_VALUES = (
    ZERO_WIDTH_SPACE,
    f"a{LINE_SEPARATOR}b",
    PARAGRAPH_SEPARATOR,
)

INVALID_NAME_VALUES = (
    "",
    "/",
    "a/b",
    "a\\b",
    "a\tb",
    "\n",
    "\x00",
    "b\x7f",
    "\x85",
)

EDGE_NAMES = (".", "..", ".md", "b.md", "notes.md")

VALID_BUILD_ARGS: tuple[tuple[str, str, str, str], ...] = (
    ("user", "u_42", "preferences", "editor"),
    ("u", "e", "a", "b.md"),
    ("u", "e", "a", "."),
    ("u", "e", "a", ".."),
    ("u", "e", "a", ".md"),
    ("project", "p 1", "glossary", NFC_CAFE),
    ("u", "e", "a", NFD_CAFE),
    ("User", "U_42", "Prefs", "Editor"),
    ("system", "x", "system", "a"),
    ("s", "e", "system", "x"),
    ("u", "e", "a", "v1.2"),
    (ZERO_WIDTH_SPACE, f"a{LINE_SEPARATOR}b", PARAGRAPH_SEPARATOR, ZERO_WIDTH_SPACE),
    (EMOJI, EMOJI, EMOJI, EMOJI),
)

MALFORMED_PATHS = (
    *MALFORMED_STRUCTURE_PATHS,
    *DOT_SEGMENT_PATHS,
    *CONTROL_CHAR_PATHS,
    *WRONG_SEGMENT_COUNT_PATHS,
    *BAD_NAME_PATHS,
)

ARBITRARY_INPUTS = (
    "\x00\x00\x00",
    f"{EMOJI}/{EMOJI}/{EMOJI}/{EMOJI}.md",
    "a" * 10000,
    "///",
    "user/u/a/b.md" * 100,
    LONE_SURROGATE,
    "\\\\",
    "a/" * 100,
)


def _valid_args_with(arg: str, value: str) -> dict[str, str]:
    args = {"scope": "user", "entity_id": "u_42", "area": "preferences", "name": "editor"}
    args[arg] = value
    return args


def _match(arg: str) -> str:
    return rf"^invalid {arg}: "


# US1: build_path


def test_build_path_formats_four_segments() -> None:
    """build_path joins scope, entity ID, area, and name + '.md' (AIE-1041, US1.1, FR-001)."""
    assert build_path("user", "u_42", "preferences", "editor") == "user/u_42/preferences/editor.md"


def test_build_path_accepts_keyword_arguments() -> None:
    """build_path parameters are positional-or-keyword (AIE-1041, US1.1, FR-001)."""
    result = build_path(scope="user", entity_id="u_42", area="preferences", name="editor")
    assert result == "user/u_42/preferences/editor.md"


@pytest.mark.parametrize("args", VALID_BUILD_ARGS)
def test_build_path_result_is_valid_path(args: tuple[str, str, str, str]) -> None:
    """Every accepted build_path result satisfies is_valid_path (AIE-1041, US1.2, FR-005)."""
    assert is_valid_path(build_path(*args)) is True


@pytest.mark.parametrize("value", INVALID_SEGMENT_VALUES)
@pytest.mark.parametrize("arg", SEGMENT_ARGS)
def test_build_path_rejects_invalid_segment_argument(arg: str, value: str) -> None:
    """An empty, dot, slash, backslash, or Cc scope/entity_id/area raises
    ValueError naming that argument (AIE-1041, US1.3, FR-001, FR-007).
    """
    with pytest.raises(ValueError, match=_match(arg)) as excinfo:
        build_path(**_valid_args_with(arg, value))
    assert str(excinfo.value) == f"invalid {arg}: {value!r}"


@pytest.mark.parametrize("value", NON_CC_SEGMENT_VALUES)
@pytest.mark.parametrize("arg", BUILD_PATH_ARGS)
def test_build_path_accepts_non_cc_characters(arg: str, value: str) -> None:
    """Characters outside Unicode Cc, such as U+200B and U+2028, are accepted
    in any argument (AIE-1041, US1.3, US1.4).
    """
    args = _valid_args_with(arg, value)
    expected = f"{args['scope']}/{args['entity_id']}/{args['area']}/{args['name']}.md"
    assert build_path(**args) == expected


@pytest.mark.parametrize("value", INVALID_NAME_VALUES)
def test_build_path_rejects_invalid_name(value: str) -> None:
    """An empty name, or one with '/', a backslash, or a Cc character, raises
    ValueError naming name (AIE-1041, US1.4, FR-001, FR-007).
    """
    with pytest.raises(ValueError, match=_match("name")) as excinfo:
        build_path("user", "u_42", "preferences", value)
    assert str(excinfo.value) == f"invalid name: {value!r}"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        (".", "u/e/a/..md"),
        ("..", "u/e/a/...md"),
        ("notes.md", "u/e/a/notes.md.md"),
        ("b.md", "u/e/a/b.md.md"),
        (".md", "u/e/a/.md.md"),
    ],
)
def test_build_path_appends_md_unconditionally(name: str, expected: str) -> None:
    """Names '.', '..', '.md', and ones ending in '.md' are accepted and get
    '.md' appended (AIE-1041, US1.5, Edge Cases).
    """
    assert build_path("u", "e", "a", name) == expected


@pytest.mark.parametrize(
    ("args", "expected_arg"),
    [
        (("", "", "", ""), "scope"),
        (("u/x", "..", "a\\b", ""), "scope"),
        (("u", ".", "\x00", "a/b"), "entity_id"),
        (("u", "", "a", ""), "entity_id"),
        (("u", "e", "..", ""), "area"),
        (("u", "e", "a/b", "\n"), "area"),
    ],
)
def test_build_path_names_first_invalid_argument(
    args: tuple[str, str, str, str], expected_arg: str
) -> None:
    """With several invalid arguments, the error names the first in order
    scope, entity_id, area, name (AIE-1041, US1.6, FR-001).
    """
    with pytest.raises(ValueError, match=_match(expected_arg)):
        build_path(*args)


def test_build_path_worked_example_slash_in_scope() -> None:
    """build_path('u/x', ...) raises 'invalid scope: 'u/x'' (AIE-1041, US1.3)."""
    with pytest.raises(ValueError, match=re.escape("invalid scope: 'u/x'")):
        build_path("u/x", "e", "a", "b")


def test_build_path_worked_example_empty_name() -> None:
    """build_path with an empty name raises "invalid name: ''" (AIE-1041, US1.4)."""
    with pytest.raises(ValueError, match=re.escape("invalid name: ''")):
        build_path("u", "e", "a", "")


@pytest.mark.parametrize(
    "args",
    [
        ("project", "p 1", "glossary", NFC_CAFE),
        ("u", "e", "a", NFD_CAFE),
        ("User", "U_42", "Prefs", "Editor"),
        ("Scope Name", "Ünïcödé", "A B", "Mixed Case"),
    ],
)
def test_build_path_uses_inputs_verbatim(args: tuple[str, str, str, str]) -> None:
    """Unicode, spaces, and mixed case are used verbatim with no normalization
    or case folding (AIE-1041, US1.7).
    """
    scope, entity_id, area, name = args
    assert build_path(*args) == f"{scope}/{entity_id}/{area}/{name}.md"


def test_build_path_does_not_nfc_normalize() -> None:
    """Decomposed 'cafe' + U+0301 is not normalized to its NFC form (AIE-1041, US1.7)."""
    assert NFD_CAFE != NFC_CAFE
    result = build_path("u", "e", "a", NFD_CAFE)
    assert result == f"u/e/a/{NFD_CAFE}.md"
    assert result != f"u/e/a/{NFC_CAFE}.md"


@pytest.mark.parametrize("arg", SEGMENT_ARGS)
def test_build_path_accepts_system_segment(arg: str) -> None:
    """'system' is accepted as scope, entity ID, or area with no authorization
    check (AIE-1041, Edge Cases).
    """
    args = _valid_args_with(arg, "system")
    assert build_path(**args).split("/")[BUILD_PATH_ARGS.index(arg)] == "system"


# US2: build_prefix


def test_build_prefix_scope_only() -> None:
    """build_prefix('user') returns 'user/' (AIE-1041, US2.1, FR-002)."""
    assert build_prefix("user") == "user/"


def test_build_prefix_scope_and_entity_id() -> None:
    """build_prefix('user', 'u_42') returns 'user/u_42/' (AIE-1041, US2.2, FR-002)."""
    assert build_prefix("user", "u_42") == "user/u_42/"


def test_build_prefix_scope_entity_id_and_area() -> None:
    """build_prefix with all three returns 'user/u_42/preferences/'
    (AIE-1041, US2.3, FR-002).
    """
    assert build_prefix("user", "u_42", "preferences") == "user/u_42/preferences/"


def test_build_prefix_accepts_keyword_arguments() -> None:
    """build_prefix parameters are positional-or-keyword (AIE-1041, US2.3, FR-002)."""
    assert build_prefix(scope="user", entity_id="u_42", area="preferences") == (
        "user/u_42/preferences/"
    )


@pytest.mark.parametrize(
    ("scope", "area"),
    [
        ("user", "preferences"),
        ("bad/", "a"),
        ("u", ""),
        ("", ".."),
        ("..", "a/b"),
    ],
)
def test_build_prefix_area_without_entity_id(scope: str, area: str) -> None:
    """An area with no entity ID raises 'area requires entity_id', checked
    before segment validation (AIE-1041, US2.4, FR-002).
    """
    with pytest.raises(ValueError, match="area requires entity_id") as excinfo:
        build_prefix(scope, None, area)
    assert str(excinfo.value) == "area requires entity_id"


@pytest.mark.parametrize("scope", ["user", "bad/", ""])
def test_build_prefix_area_without_entity_id_keyword(scope: str) -> None:
    """Passing area by keyword without entity_id raises 'area requires entity_id'
    (AIE-1041, US2.4, FR-002).
    """
    with pytest.raises(ValueError, match="area requires entity_id"):
        build_prefix(scope, area="a")


@pytest.mark.parametrize("value", INVALID_SEGMENT_VALUES)
@pytest.mark.parametrize("arg", SEGMENT_ARGS)
def test_build_prefix_rejects_invalid_supplied_argument(arg: str, value: str) -> None:
    """A supplied argument that is not a valid segment, including '', raises
    ValueError naming it (AIE-1041, US2.5, FR-002, FR-007).
    """
    args: dict[str, str] = {"scope": "user", "entity_id": "u_42", "area": "preferences"}
    args[arg] = value
    with pytest.raises(ValueError, match=_match(arg)) as excinfo:
        build_prefix(**args)
    assert str(excinfo.value) == f"invalid {arg}: {value!r}"


@pytest.mark.parametrize("value", INVALID_SEGMENT_VALUES)
def test_build_prefix_rejects_invalid_scope_alone(value: str) -> None:
    """An invalid scope with nothing else supplied raises ValueError naming
    scope (AIE-1041, US2.5, FR-002).
    """
    with pytest.raises(ValueError, match=_match("scope")):
        build_prefix(value)


@pytest.mark.parametrize("value", INVALID_SEGMENT_VALUES)
def test_build_prefix_rejects_invalid_entity_id_without_area(value: str) -> None:
    """An invalid entity ID with no area raises ValueError naming entity_id
    (AIE-1041, US2.5, FR-002).
    """
    with pytest.raises(ValueError, match=_match("entity_id")):
        build_prefix("user", value)


def test_build_prefix_empty_entity_id_is_not_omitted() -> None:
    """'' as entity_id is invalid, not treated as omitted (AIE-1041, US2.5)."""
    with pytest.raises(ValueError, match=re.escape("invalid entity_id: ''")):
        build_prefix("user", "")


PREFIX_CASES: tuple[tuple[str, str | None, str | None], ...] = tuple(
    case
    for scope, entity_id, area, _ in VALID_BUILD_ARGS
    for case in ((scope, None, None), (scope, entity_id, None), (scope, entity_id, area))
)


@pytest.mark.parametrize("args", PREFIX_CASES)
def test_build_prefix_result_is_valid_prefix(args: tuple[str, str | None, str | None]) -> None:
    """Every accepted build_prefix result satisfies is_valid_prefix
    (AIE-1041, US2.6, FR-005).
    """
    assert is_valid_prefix(build_prefix(*args)) is True


@pytest.mark.parametrize("args", VALID_BUILD_ARGS)
def test_build_path_starts_with_build_prefix(args: tuple[str, str, str, str]) -> None:
    """Every build_path result starts with the build_prefix of the same
    leading arguments (AIE-1041, US2.6, FR-002).
    """
    scope, entity_id, area, name = args
    path = build_path(scope, entity_id, area, name)
    assert path.startswith(build_prefix(scope))
    assert path.startswith(build_prefix(scope, entity_id))
    assert path.startswith(build_prefix(scope, entity_id, area))


@pytest.mark.parametrize(
    ("args", "expected_arg"),
    [
        (("", "", ""), "scope"),
        (("u/x", "..", "a\\b"), "scope"),
        (("..", ""), "scope"),
        (("u", ".", "\x00"), "entity_id"),
        (("u", "", ""), "entity_id"),
        (("u", "e", ".."), "area"),
    ],
)
def test_build_prefix_names_first_invalid_argument(
    args: tuple[str, ...], expected_arg: str
) -> None:
    """With several invalid supplied arguments, the error names the first in
    order scope, entity_id, area (AIE-1041, US2.7, FR-002).
    """
    with pytest.raises(ValueError, match=_match(expected_arg)):
        build_prefix(*args)


# US3: parse_path


def test_parse_path_splits_into_parts() -> None:
    """parse_path returns the four parts with the '.md' stripped from name
    (AIE-1041, US3.1, FR-003).
    """
    assert parse_path("user/u_42/preferences/editor.md") == PathParts(
        scope="user", entity_id="u_42", area="preferences", name="editor"
    )


@pytest.mark.parametrize("path", MALFORMED_PATHS)
def test_parse_path_rejects_malformed_paths(path: str) -> None:
    """Every malformed path from test_paths raises ValueError with the plan's
    message (AIE-1041, US3.2, FR-003, FR-007).
    """
    with pytest.raises(ValueError, match=r"^invalid path: ") as excinfo:
        parse_path(path)
    assert str(excinfo.value) == f"invalid path: {path!r}"


def test_parse_path_worked_example_wrong_extension() -> None:
    """parse_path('u/e/a/b.txt') raises "invalid path: 'u/e/a/b.txt'"
    (AIE-1041, US3.2, FR-003).
    """
    with pytest.raises(ValueError, match=re.escape("invalid path: 'u/e/a/b.txt'")):
        parse_path("u/e/a/b.txt")


@pytest.mark.parametrize("path", ARBITRARY_INPUTS)
def test_parse_path_raises_only_value_error_iff_invalid(path: str) -> None:
    """parse_path raises ValueError iff is_valid_path rejects the input, and
    never another exception, for the never-raises inputs (AIE-1041, US3.2,
    FR-003, FR-007).
    """
    if is_valid_path(path):
        assert isinstance(parse_path(path), PathParts)
    else:
        with pytest.raises(ValueError, match=r"^invalid path: "):
            parse_path(path)


def test_parse_path_exposes_system_area() -> None:
    """parse_path exposes a 'system' area directly (AIE-1041, US3.3, FR-003)."""
    assert parse_path("s/e/system/x.md").area == "system"


@pytest.mark.parametrize(
    ("path", "expected_name"),
    [
        ("u/e/a/..md", "."),
        ("u/e/a/...md", ".."),
        ("u/e/a/b.md.md", "b.md"),
        ("u/e/a/.md.md", ".md"),
    ],
)
def test_parse_path_strips_only_final_md(path: str, expected_name: str) -> None:
    """Only the final '.md' is stripped from the name (AIE-1041, US3.4, FR-003)."""
    assert parse_path(path).name == expected_name


def test_parse_path_worked_example_double_md() -> None:
    """parse_path('u/e/a/b.md.md') equals PathParts('u', 'e', 'a', 'b.md')
    (AIE-1041, US3.4).
    """
    assert parse_path("u/e/a/b.md.md") == PathParts("u", "e", "a", "b.md")


# US4: round trip

ROUND_TRIP_BUILD_ARGS: tuple[tuple[str, str, str, str], ...] = (
    *VALID_BUILD_ARGS,
    *(("u", "e", "a", name) for name in EDGE_NAMES),
)

ROUND_TRIP_PATHS = (
    *VALID_PATHS,
    *(f"u/e/a/{name}.md" for name in EDGE_NAMES),
    "s/e/system/x.md",
    f"u/e/a/{NFD_CAFE}.md",
    f"{EMOJI}/{EMOJI}/{EMOJI}/{EMOJI}.md",
)


@pytest.mark.parametrize("args", ROUND_TRIP_BUILD_ARGS)
def test_parse_inverts_build(args: tuple[str, str, str, str]) -> None:
    """parse_path(build_path(s, e, a, n)) == PathParts(s, e, a, n)
    (AIE-1041, US4.1, FR-004).
    """
    assert parse_path(build_path(*args)) == PathParts(*args)


@pytest.mark.parametrize("path", ROUND_TRIP_PATHS)
def test_build_inverts_parse(path: str) -> None:
    """build_path(**asdict(parse_path(p))) == p for every valid path
    (AIE-1041, US4.2, FR-004).
    """
    assert is_valid_path(path) is True
    assert build_path(**dataclasses.asdict(parse_path(path))) == path


@pytest.mark.parametrize("path", ROUND_TRIP_PATHS)
def test_build_inverts_parse_positionally(path: str) -> None:
    """PathParts field order matches build_path parameter order, so astuple
    round-trips too (AIE-1041, US4.2, FR-004).
    """
    assert build_path(*dataclasses.astuple(parse_path(path))) == path


# Edge cases: PathParts


def test_path_parts_is_frozen() -> None:
    """PathParts is frozen (AIE-1041, Edge Cases)."""
    parts = PathParts("u", "e", "a", "n")
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(parts, "scope", "other")  # noqa: B010


def test_path_parts_compares_by_value() -> None:
    """PathParts compares and hashes by value (AIE-1041, Edge Cases)."""
    assert PathParts("u", "e", "a", "n") == PathParts("u", "e", "a", "n")
    assert PathParts("u", "e", "a", "n") != PathParts("u", "e", "a", "m")
    assert hash(PathParts("u", "e", "a", "n")) == hash(PathParts("u", "e", "a", "n"))


def test_path_parts_does_no_validation() -> None:
    """PathParts('', '', '', '') constructs without validation (AIE-1041, Edge Cases)."""
    parts = PathParts("", "", "", "")
    assert dataclasses.astuple(parts) == ("", "", "", "")


def test_path_parts_field_order() -> None:
    """PathParts fields are scope, entity_id, area, name in that order
    (AIE-1041, US4.2).
    """
    assert tuple(field.name for field in dataclasses.fields(PathParts)) == BUILD_PATH_ARGS


# FR-006: dependency-free module


def test_paths_module_has_no_wenchang_import() -> None:
    """wenchang.paths imports nothing from wenchang, so it stays free of
    identity, storage, and core (AIE-1041, FR-006).
    """
    tree = ast.parse(PATHS_SOURCE.read_text(encoding="utf-8"))
    offending: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            offending.extend(
                alias.name
                for alias in node.names
                if alias.name == "wenchang" or alias.name.startswith("wenchang.")
            )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level > 0 or module == "wenchang" or module.startswith("wenchang."):
                offending.append("." * node.level + module)
    assert offending == []
