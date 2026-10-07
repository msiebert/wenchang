"""Tests for tool enumeration and the agent-facing tool descriptions.

Covers AIE-1044, US5.1 through US5.8: TOOL_NAMES, MemoryTools.tools(), and
the docstrings a host shows the agent as tool descriptions; and AIE-1151,
US5.1: the aliases and description paragraph on append_line and replace_fact; and
AIE-1165, US2 and US4: shared mechanics stated once in get_memory_index, with each
write tool keeping its own expected_version and conflict guidance.
"""

import re
import types
from collections.abc import Mapping, Sequence
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

IDENTITY = Identity({"user": ScopeGrant("u-1", "owner"), "org": ScopeGrant("o-9", "member")})
POLICY = ScopePolicy({"org": frozenset({"admin", "owner"})})

PHRASES: dict[str, tuple[str, ...]] = {
    "get_memory_index": (
        "capped",
        "list_prefix",
        "read_file(scope, area, name)",
        "list_prefix(scope, area)",
        "`scope`",
        "`area`",
        "`name`",
        ".md",
        "filled in",
        "Areas are lowercase ASCII slugs.",
        "The `system/` area is read-only.",
    ),
    "read_file": ("Any area may be read, including `system/`.",),
    "list_prefix": ("scope", "area", "cursor", "next_cursor"),
    "write_file": (
        "expected_version=None",
        "the version you read",
        "routine",
        "byte ceiling",
        "current size and the limit",
        "description",
        "aliases",
        "not merged",
        "replace the stored values",
    ),
    "append_line": (
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
    ),
    "replace_fact": (
        "routine",
        "expected_version",
        "byte ceiling",
        "exactly once",
        "quote a unique span",
        "applies to the result",
    ),
    "delete_file": (
        "routine",
        "expected_version",
        "Pass the version you read as `expected_version`.",
        "only if the file should still go",
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
        self,
        path: str,
        line: str,
        expected_version: VersionToken,
        *,
        source: str,
        aliases: Sequence[str] | None = None,
        description: str | None = None,
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
        aliases: Sequence[str] | None = None,
        description: str | None = None,
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
    (AIE-1044, US5.4, US5.5, US5.6, US5.8; AIE-1165, US2.3, US2.4, US2.6).
    """
    assert phrase in _doc(tool)


METADATA_PHRASES = (
    "added to the file's existing aliases",
    "never removed",
    "write_file",
    "replaces the whole set",
    "one-line `description` replaces the stored one",
)


@pytest.mark.parametrize("tool", ["append_line", "replace_fact"])
@pytest.mark.parametrize("phrase", METADATA_PHRASES)
def test_fact_docstring_explains_aliases_and_description(tool: str, phrase: str) -> None:
    """The append_line and replace_fact docstrings say aliases are added and
    never removed, point to write_file for removal, and say description
    replaces the stored one (AIE-1151, US5.1).
    """
    assert phrase in " ".join(_doc(tool).split())


@pytest.mark.parametrize("tool", MUTATING_TOOLS)
def test_mutating_docstring_presents_conflict_as_merge_and_retry(tool: str) -> None:
    """Each mutating docstring presents a version conflict as routine and says
    to retry; delete_file has no merge step, it retries only if the file should
    still go (AIE-1044, US5.4; AIE-1165, US2.4, US2.6).
    """
    doc = " ".join(_doc(tool).split())

    assert "version conflict is routine" in doc
    assert "retry" in doc


@pytest.mark.parametrize("tool", ["write_file", "append_line", "replace_fact"])
def test_merging_docstring_says_merge_and_retry(tool: str) -> None:
    """Each write tool that changes content says to merge into the returned
    content and retry with its version (AIE-1044, US5.4; AIE-1165, US2.5).
    """
    doc = " ".join(_doc(tool).split())

    assert "merge your change into the content it returns and retry with its version" in doc


@pytest.mark.parametrize("tool", ["append_line", "replace_fact"])
def test_fact_docstring_says_pass_version_you_read(tool: str) -> None:
    """The append_line and replace_fact docstrings say to pass the version you
    read as expected_version; the sentence spans a line break, so it is matched
    whitespace-collapsed (AIE-1044, US5.4; AIE-1165, US2.4).
    """
    assert "Pass the version you read as `expected_version`." in " ".join(_doc(tool).split())


def test_name_docstring_says_name_excludes_md() -> None:
    """The name rule (name excludes the .md extension) is stated once, in
    get_memory_index (AIE-1044, US5.8; AIE-1165, US2.3).
    """
    doc = _doc("get_memory_index")

    assert re.search(r"\b(without|excludes?|excluding)\b[^.]{0,40}\.md", doc), (
        "get_memory_index must say name excludes .md"
    )


def test_area_docstring_states_slug_rule() -> None:
    """The area slug rule is stated once, in get_memory_index
    (AIE-1136, US4.4; AIE-1165, US2.3).
    """
    assert "Areas are lowercase ASCII slugs." in _doc("get_memory_index")


def test_shared_mechanics_stated_once() -> None:
    """The slug rule, the .md rule, and the read-only rule appear in
    get_memory_index and no other tool docstring, and no docstring repeats the
    per-tool scope/area glossary (AIE-1165, US2.2).
    """
    holders = {
        phrase: [tool for tool in EXPECTED_TOOL_NAMES if phrase in _doc(tool)]
        for phrase in (
            "Areas are lowercase ASCII slugs.",
            ".md",
            "is read-only",
            "`scope` is one of the scopes",
            "folder inside it",
        )
    }

    assert holders == {
        "Areas are lowercase ASCII slugs.": ["get_memory_index"],
        ".md": ["get_memory_index"],
        "is read-only": ["get_memory_index"],
        "`scope` is one of the scopes": [],
        "folder inside it": [],
    }


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
