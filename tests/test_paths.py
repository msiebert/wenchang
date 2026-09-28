"""Tests for memory file path validation.

Covers AIE-1032.
"""

import pytest

from wenchang.paths import is_valid_path

VALID_PATHS = (
    "user/u_42/preferences/editor.md",
    "project/p 1/glossary/café.md",
    "system/x/system/a.md",
    "User/U_42/Prefs/Editor.md",
    "user/u/a/v1.2.md",
)

MALFORMED_STRUCTURE_PATHS = (
    "",
    "/user/u/a/b.md",
    "user/u/a/b.md/",
    "user//a/b.md",
)

DOT_SEGMENT_PATHS = (
    "./u/a/b.md",
    "user/../a/b.md",
    "user/u/./b.md",
    "user/u/a/..",
)

CONTROL_CHAR_PATHS = (
    "user/u/a/b\\c.md",
    "user/u/a/b\tc.md",
    "user/u/a/b\nc.md",
    "user/u/a/b\x00c.md",
    "user/u/a/b\x7fc.md",
)

WRONG_SEGMENT_COUNT_PATHS = (
    "user/u/b.md",
    "user/u/a/b/c.md",
)

BAD_NAME_PATHS = (
    "user/u/a/b.txt",
    "user/u/a/b",
    "user/u/a/.md",
    "user/u/a/b.MD",
)


@pytest.mark.unit
@pytest.mark.parametrize("path", VALID_PATHS)
def test_valid_paths_accepted(path: str) -> None:
    """Well-formed scope/entity_id/area/name.md paths are accepted (AIE-1032, US2-4, FR-007)."""
    assert is_valid_path(path) is True


@pytest.mark.unit
@pytest.mark.parametrize("path", MALFORMED_STRUCTURE_PATHS)
def test_malformed_structure_rejected(path: str) -> None:
    """Empty string, leading/trailing slash, and empty segments are rejected (AIE-1032, US2-3)."""
    assert is_valid_path(path) is False


@pytest.mark.unit
@pytest.mark.parametrize("path", DOT_SEGMENT_PATHS)
def test_dot_segments_rejected(path: str) -> None:
    """A '.' or '..' segment anywhere in the path is rejected (AIE-1032, US2-3)."""
    assert is_valid_path(path) is False


@pytest.mark.unit
@pytest.mark.parametrize("path", CONTROL_CHAR_PATHS)
def test_backslash_and_control_chars_rejected(path: str) -> None:
    """Backslashes and control characters in a segment are rejected (AIE-1032, US2-3)."""
    assert is_valid_path(path) is False


@pytest.mark.unit
@pytest.mark.parametrize("path", WRONG_SEGMENT_COUNT_PATHS)
def test_wrong_segment_count_rejected(path: str) -> None:
    """Fewer or more than four segments is rejected (AIE-1032, US2-3, FR-007)."""
    assert is_valid_path(path) is False


@pytest.mark.unit
@pytest.mark.parametrize("path", BAD_NAME_PATHS)
def test_bad_final_segment_rejected(path: str) -> None:
    """A final segment not ending in '.md' or too short is rejected (AIE-1032, US2-3)."""
    assert is_valid_path(path) is False


@pytest.mark.unit
def test_never_raises_on_arbitrary_input() -> None:
    """is_valid_path never raises for any str input, including odd unicode (AIE-1032, FR-007)."""
    weird_inputs = (
        "\x00\x00\x00",
        "😀/😀/😀/😀.md",
        "a" * 10000,
        "///",
        "user/u/a/b.md" * 100,
    )
    for value in weird_inputs:
        is_valid_path(value)
