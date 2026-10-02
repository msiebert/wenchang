"""Tests for tool enumeration and the agent-facing tool descriptions.

Covers AIE-1044, US5.1 through US5.8: TOOL_NAMES, MemoryTools.tools(), and
the docstrings a host shows the agent as tool descriptions.
"""

import re
import types
from collections.abc import Mapping
from pathlib import Path

import pytest

from wenchang.core import ListCursor, ListPage, MemoryFile, MemoryIndex
from wenchang.file_format import FileMetadata
from wenchang.identity import Identity, ScopeGrant
from wenchang.scope import ScopePolicy
from wenchang.tools import TOOL_NAMES, MemoryTools
from wenchang.version_token import VersionToken

pytestmark = pytest.mark.unit

TOOLS_MODULE = Path(__file__).resolve().parents[1] / "src" / "wenchang" / "tools.py"

EXPECTED_TOOL_NAMES = (
    "get_memory_index",
    "read_file",
    "list_prefix",
    "write_file",
    "append_line",
    "replace_fact",
    "delete_file",
)
MUTATING_TOOLS = ("write_file", "append_line", "replace_fact", "delete_file")
NAME_TOOLS = ("read_file", *MUTATING_TOOLS)
AREA_TOOLS = ("read_file", "list_prefix", *MUTATING_TOOLS)

IDENTITY = Identity({"user": ScopeGrant("u-1", "owner"), "org": ScopeGrant("o-9", "member")})
POLICY = ScopePolicy({"org": frozenset({"admin", "owner"})})

PHRASES: dict[str, tuple[str, ...]] = {
    "get_memory_index": (
        "capped",
        "list_prefix",
        "read_file(scope, area, name)",
        "list_prefix(scope, area)",
    ),
    "read_file": ("scope", "area", "name", ".md"),
    "list_prefix": ("scope", "area", "cursor", "next_cursor"),
    "write_file": (
        "scope",
        "area",
        "name",
        ".md",
        "routine",
        "expected_version",
        "byte ceiling",
        "current size and the limit",
        "description",
        "aliases",
        "not merged",
        "replace the stored values",
        "system/",
        "read-only",
    ),
    "append_line": (
        "scope",
        "area",
        "name",
        ".md",
        "routine",
        "expected_version",
        "byte ceiling",
        "single fact line",
        "leading bracketed label",
        "applies to the result",
        "[stated]",
        "[observed]",
        "[inferred]",
        "[system]",
        "system/",
        "read-only",
    ),
    "replace_fact": (
        "scope",
        "area",
        "name",
        ".md",
        "routine",
        "expected_version",
        "byte ceiling",
        "exactly once",
        "applies to the result",
        "system/",
        "read-only",
    ),
    "delete_file": (
        "scope",
        "area",
        "name",
        ".md",
        "routine",
        "expected_version",
        "system/",
        "read-only",
    ),
}
PHRASE_CASES = [(tool, phrase) for tool, phrases in PHRASES.items() for phrase in phrases]


class _NullClient:
    """A TransportClient that is never called."""

    def read_file(self, path: str) -> MemoryFile:
        raise AssertionError("unexpected call")

    def write_file(
        self,
        path: str,
        content: str,
        metadata: FileMetadata,
        expected_version: VersionToken | None,
        *,
        source: str,
    ) -> MemoryFile:
        raise AssertionError("unexpected call")

    def append_line(
        self, path: str, line: str, expected_version: VersionToken, *, source: str
    ) -> MemoryFile:
        raise AssertionError("unexpected call")

    def replace_fact(
        self,
        path: str,
        old_string: str,
        new_string: str,
        expected_version: VersionToken,
        *,
        source: str,
    ) -> MemoryFile:
        raise AssertionError("unexpected call")

    def list_prefix(self, prefix: str, cursor: ListCursor | None = None) -> ListPage:
        raise AssertionError("unexpected call")

    def delete_file(self, path: str, expected_version: VersionToken) -> None:
        raise AssertionError("unexpected call")

    def get_memory_index(self, scope_map: Mapping[str, str]) -> MemoryIndex:
        raise AssertionError("unexpected call")


@pytest.fixture
def tools() -> MemoryTools:
    return MemoryTools(_NullClient(), IDENTITY, POLICY, source="test-surface")


def _doc(tool: str) -> str:
    doc = getattr(MemoryTools, tool).__doc__
    assert isinstance(doc, str), f"{tool} has no docstring"
    return doc


def test_tool_names_are_fixed_tuple() -> None:
    """TOOL_NAMES is the seven tool names in the fixed order (AIE-1044, US5.1)."""
    assert type(TOOL_NAMES) is tuple
    assert TOOL_NAMES == EXPECTED_TOOL_NAMES


def test_tools_mapping_holds_bound_methods_in_order(tools: MemoryTools) -> None:
    """tools() maps each TOOL_NAMES entry, in order, to the bound method of
    that name (AIE-1044, US5.2).
    """
    mapping = tools.tools()

    assert list(mapping) == list(EXPECTED_TOOL_NAMES)
    for name, method in mapping.items():
        assert isinstance(method, types.MethodType)
        assert method.__self__ is tools
        assert method.__name__ == name
        assert method.__func__ is getattr(MemoryTools, name)


def test_tools_mapping_is_fresh_and_read_only(tools: MemoryTools) -> None:
    """tools() returns a new read-only MappingProxyType on each call
    (AIE-1044, US5.2).
    """
    first = tools.tools()
    second = tools.tools()

    assert type(first) is types.MappingProxyType
    assert first is not second
    with pytest.raises(TypeError):
        first["read_file"] = tools.read_file  # pyright: ignore[reportIndexIssue]


@pytest.mark.parametrize("tool", EXPECTED_TOOL_NAMES)
def test_docstring_first_line_is_one_sentence(tool: str) -> None:
    """Each tool docstring is non-empty and its first line is a single
    sentence (AIE-1044, US5.3).
    """
    doc = _doc(tool)

    assert doc.strip()
    first_line = doc.strip().splitlines()[0].strip()
    assert first_line.endswith(".")
    assert ". " not in first_line


@pytest.mark.parametrize(("tool", "phrase"), PHRASE_CASES)
def test_docstring_contains_pinned_phrase(tool: str, phrase: str) -> None:
    """Each tool docstring contains the phrases a host must not lose
    (AIE-1044, US5.4, US5.5, US5.6, US5.8).
    """
    assert phrase in _doc(tool)


@pytest.mark.parametrize("tool", MUTATING_TOOLS)
def test_mutating_docstring_presents_conflict_as_merge_and_retry(tool: str) -> None:
    """Each mutating docstring presents a version conflict as routine: merge
    and retry (AIE-1044, US5.4).
    """
    doc = _doc(tool)

    assert "routine" in doc
    assert "merge" in doc
    assert "retry" in doc


@pytest.mark.parametrize("tool", NAME_TOOLS)
def test_name_docstring_says_name_excludes_md(tool: str) -> None:
    """Every tool taking name says name excludes the .md extension
    (AIE-1044, US5.8).
    """
    doc = _doc(tool)

    assert re.search(r"\b(without|excludes?|excluding)\b[^.]{0,40}\.md", doc), (
        f"{tool} must say name excludes .md"
    )


@pytest.mark.parametrize("tool", AREA_TOOLS)
def test_area_docstring_states_slug_rule(tool: str) -> None:
    """Every tool taking area says areas are lowercase ASCII slugs (AIE-1136, US4.4)."""
    assert "Areas are lowercase ASCII slugs." in _doc(tool)


def test_get_memory_index_docstring_explains_entity_segment() -> None:
    """The get_memory_index docstring says the entity segment is filled in by
    the tools (AIE-1044, US5.8).
    """
    doc = _doc("get_memory_index")

    assert "entity" in doc
    assert "filled in" in doc


def test_tools_module_cites_no_linear_ids() -> None:
    """src/wenchang/tools.py contains no AIE-\\d+ reference (AIE-1044, US5.7)."""
    assert re.findall(r"AIE-\d+", TOOLS_MODULE.read_text()) == []
