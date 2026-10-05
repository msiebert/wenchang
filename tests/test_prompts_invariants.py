"""Text invariants for every prompt section module.

Covers AIE-1055, US5.1 through US5.9. Section modules are discovered with
pkgutil, so a section added later is checked without editing this file.
"""

import ast
import importlib
import inspect
import pkgutil
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import cast

import pytest

import wenchang.prompts
from wenchang.core import CappedPrefix, FileEntry, ListCursor, ListPage, MemoryFile, MemoryIndex
from wenchang.errors import (
    ErrorCategory,
    NotFoundReason,
    ReplaceFactMatchError,
    RestrictedScopeError,
    RestrictionReason,
    TransientReason,
)
from wenchang.file_format import ConfidenceLabel, FileMetadata
from wenchang.prompts import assemble
from wenchang.tools import TOOL_NAMES, MemoryTools, render_error, render_result
from wenchang.version_token import VersionToken

pytestmark = pytest.mark.unit

EXPECTED_SECTION_MODULES = frozenset(
    {
        "overview",
        "systems_of_record",
        "applying_memory",
        "remembering",
        "privacy",
        "filing",
        "write_mechanics",
        "curated_content",
        "forgetting",
    }
)
NON_SECTION_MODULES = frozenset({"assemble", "slots"})
PROMPTS_DIR = Path(next(iter(wenchang.prompts.__path__)))
PROMPT_FILES = sorted(PROMPTS_DIR.rglob("*.py"))

SECTION_MODULES = sorted(
    info.name
    for info in pkgutil.iter_modules(wenchang.prompts.__path__)
    if info.name not in NON_SECTION_MODULES
)
_CONSTANT_NAME = re.compile(r"[A-Z][A-Z0-9_]*")


def _texts() -> list[tuple[str, str]]:
    texts: list[tuple[str, str]] = []
    for module_name in SECTION_MODULES:
        module = importlib.import_module(f"wenchang.prompts.{module_name}")
        for attr, value in sorted(vars(module).items()):
            if _CONSTANT_NAME.fullmatch(attr) and type(value) is str:
                texts.append((f"{module_name}.{attr}", value))
    texts.append(("assemble.SCOPE_GUIDANCE_HEADING", assemble.SCOPE_GUIDANCE_HEADING))
    texts.append(("assemble.SEED_AREAS_HEADING", assemble.SEED_AREAS_HEADING))
    return texts


TEXTS = _texts()
TEXT_IDS = [text_id for text_id, _ in TEXTS]
TEXT_VALUES = [text for _, text in TEXTS]

text_param = pytest.mark.parametrize("text", TEXT_VALUES, ids=TEXT_IDS)


def _tool_parameters(tool: str) -> set[str]:
    signature = inspect.signature(getattr(MemoryTools, tool))
    return {name for name in signature.parameters if name != "self"}


def _keys(value: object) -> Iterator[str]:
    """Every dict key in a rendered JSON-shaped value, at any depth."""
    if isinstance(value, dict):
        for key, item in cast(dict[object, object], value).items():
            yield str(key)
            yield from _keys(item)
    elif isinstance(value, list):
        for item in cast(list[object], value):
            yield from _keys(item)


def _allowed_identifiers() -> set[str]:
    path = "user/u-1/notes/a.md"
    metadata = FileMetadata(
        description="Notes about a",
        aliases=("b",),
        sources=frozenset({"s1"}),
        last_updated=datetime(2026, 1, 1, tzinfo=UTC),
    )
    version = VersionToken("v-1")
    entry = FileEntry(path, metadata, version)
    rendered: list[dict[str, object]] = [
        render_result(
            MemoryFile(path=path, content="- [stated] x\n", metadata=metadata, version=version)
        ),
        render_result(ListPage(entries=(entry,), next_cursor=ListCursor("c-1"))),
        render_result(MemoryIndex(entries=(entry,), capped=(CappedPrefix("user/u-1/notes/", 1),))),
        render_error(ReplaceFactMatchError(path, "body", version, 2)),
        render_error(
            RestrictedScopeError(
                "org/o-1/notes/a.md",
                "org",
                RestrictionReason.ROLE_REQUIRED,
                required_roles=frozenset({"admin"}),
            )
        ),
    ]
    allowed: set[str] = set(TOOL_NAMES)
    for tool in TOOL_NAMES:
        allowed |= _tool_parameters(tool)
    for out in rendered:
        allowed |= set(_keys(out))
    enums: list[type[Enum]] = [
        RestrictionReason,
        NotFoundReason,
        TransientReason,
        ErrorCategory,
        ConfidenceLabel,
    ]
    for enum in enums:
        allowed |= {str(member.value) for member in enum}
    return allowed


def test_discovered_section_modules() -> None:
    """AIE-1055, US5.1: the discovered section modules are exactly the nine planned."""
    assert set(SECTION_MODULES) == EXPECTED_SECTION_MODULES
    assert len(SECTION_MODULES) == len(EXPECTED_SECTION_MODULES)


def test_text_set_covers_every_section() -> None:
    """AIE-1055, US5.1: every discovered section module contributes at least its HEADING."""
    for module_name in SECTION_MODULES:
        assert f"{module_name}.HEADING" in TEXT_IDS, module_name


@text_param
def test_text_is_ascii_with_short_lines(text: str) -> None:
    """AIE-1055, US5.2: every text is ASCII and every line is at most 100 characters."""
    assert text.isascii()
    for line in text.split("\n"):
        assert len(line) <= 100, line


def test_no_linear_ids_in_prompt_sources() -> None:
    """AIE-1055, US5.3: no file under src/wenchang/prompts/ contains a Linear issue ID."""
    assert PROMPT_FILES
    for file in PROMPT_FILES:
        assert re.search(r"AIE-\d+", file.read_text(encoding="utf-8")) is None, file.name


@text_param
def test_text_has_no_paths_braces_or_entity(text: str) -> None:
    """AIE-1055, US5.4: no `.md`, no `{`, no `x/y.md` path, and no word entity/entities."""
    assert ".md" not in text
    assert "{" not in text
    assert re.search(r"\S+/\S+\.md", text) is None
    assert re.search(r"\bentit(y|ies)\b", text, re.IGNORECASE) is None


@text_param
def test_text_tool_calls_use_real_names_and_parameters(text: str) -> None:
    """AIE-1055, US5.5: every backticked call names a tool, and each argument is `...`
    or a parameter of that tool read from inspect.signature."""
    for match in re.finditer(r"`([a-z][a-z0-9_]*)\(([^`]*)\)`", text):
        tool = match.group(1)
        assert tool in TOOL_NAMES, match.group(0)
        parameters = _tool_parameters(tool)
        args = [a.strip() for a in match.group(2).split(",") if a.strip()]
        for arg in args:
            if arg == "...":
                continue
            arg_match = re.match(r"^([a-z_][a-z0-9_]*)(\s*=.*)?$", arg)
            assert arg_match is not None, match.group(0)
            assert arg_match.group(1) in parameters, match.group(0)


@text_param
def test_text_snake_case_identifiers_are_agent_visible(text: str) -> None:
    """AIE-1055, US5.6: every backticked snake_case identifier is a tool name, tool
    parameter, rendered result/error key, or enum value."""
    allowed = _allowed_identifiers()
    for match in re.finditer(r"`([a-z][a-z0-9]*(?:_[a-z0-9]+)+)`", text):
        assert match.group(1) in allowed, match.group(0)


def test_allowed_identifier_set_is_populated() -> None:
    """AIE-1055, US5.6: the computed allowed set includes representative members of
    each source, so the identifier check is not vacuous."""
    allowed = _allowed_identifiers()

    assert {"get_memory_index", "expected_version", "next_cursor", "match_count"} <= allowed
    assert {"required_roles", "role_required", "file_absent", "omitted"} <= allowed


@text_param
def test_text_has_no_adopter_scope_names(text: str) -> None:
    """AIE-1055, US5.7: no text names organization(s) or project(s)."""
    assert re.search(r"\b(organizations?|projects?)\b", text, re.IGNORECASE) is None


@text_param
def test_text_length_limit(text: str) -> None:
    """AIE-1055, US5.8: every text is at most 2500 characters."""
    assert len(text) <= 2500


def _resolved_import(node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""
    package = ["wenchang", "prompts"]
    base = package[: len(package) - (node.level - 1)]
    return ".".join([*base, *([node.module] if node.module else [])])


def _in_prompts(module: str) -> bool:
    return module == "wenchang.prompts" or module.startswith("wenchang.prompts.")


def _in_wenchang(module: str) -> bool:
    return module == "wenchang" or module.startswith("wenchang.")


@pytest.mark.parametrize("file", PROMPT_FILES, ids=[f.name for f in PROMPT_FILES])
def test_prompts_import_only_prompts_from_wenchang(file: Path) -> None:
    """AIE-1055, US5.9: modules under wenchang.prompts import from wenchang only
    wenchang.prompts submodules."""
    tree = ast.parse(file.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _in_wenchang(alias.name):
                    assert _in_prompts(alias.name), alias.name
        elif isinstance(node, ast.ImportFrom):
            module = _resolved_import(node)
            if module == "wenchang":
                assert all(alias.name == "prompts" for alias in node.names), module
            elif _in_wenchang(module):
                assert _in_prompts(module), module


def test_prompt_files_include_package_modules() -> None:
    """AIE-1055, US5.9: the import scan covers __init__, assemble, and slots."""
    names = {file.name for file in PROMPT_FILES}

    assert {"__init__.py", "assemble.py", "slots.py"} <= names
