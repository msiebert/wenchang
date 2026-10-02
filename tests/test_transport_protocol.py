"""Tests for the TransportClient protocol.

Covers AIE-1048, US1.1 through US1.5, US2.1 through US2.3, and US4.1 through US4.3.
"""

import ast
import inspect
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import NoReturn

import pytest

import wenchang.transport
from wenchang.core import ListCursor, ListPage, MemoryFile, MemoryIndex, MemoryStore
from wenchang.file_format import FileMetadata
from wenchang.transport import TransportClient
from wenchang.version_token import VersionToken

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = REPO_ROOT / "src" / "wenchang"
TRANSPORT_MODULE = PACKAGE_DIR / "transport.py"
CORE_MODULE = PACKAGE_DIR / "core.py"

LINEAR_ID = re.compile(r"AIE-\d+")

STORE_METHODS = (
    "read_file",
    "write_file",
    "append_line",
    "replace_fact",
    "list_prefix",
    "delete_file",
)
ALL_METHODS = (*STORE_METHODS, "get_memory_index")

ALLOWED_WENCHANG_IMPORTS = frozenset(
    {"wenchang.core", "wenchang.file_format", "wenchang.version_token"}
)
FORBIDDEN_IMPORT_ROOTS = (
    "google",
    "wenchang.storage",
    "wenchang.identity",
    "wenchang.scope",
    "wenchang.testing",
)

ERROR_PARITY_NAMES = (
    "MemoryStore",
    "wenchang.errors",
    "ValueError",
    "MetadataFormatError",
    "UnicodeDecodeError",
    "BackendUnavailableError",
)


class _Ref:
    def get_memory_index(self, scope_map: Mapping[str, str]) -> MemoryIndex:
        raise NotImplementedError


class _FullClient:
    def read_file(self, path: str) -> MemoryFile:
        raise NotImplementedError

    def write_file(
        self,
        path: str,
        content: str,
        metadata: FileMetadata,
        expected_version: VersionToken | None,
        *,
        source: str,
    ) -> MemoryFile:
        raise NotImplementedError

    def append_line(
        self, path: str, line: str, expected_version: VersionToken, *, source: str
    ) -> MemoryFile:
        raise NotImplementedError

    def replace_fact(
        self,
        path: str,
        old_string: str,
        new_string: str,
        expected_version: VersionToken,
        *,
        source: str,
    ) -> MemoryFile:
        raise NotImplementedError

    def list_prefix(self, prefix: str, cursor: ListCursor | None = None) -> ListPage:
        raise NotImplementedError

    def delete_file(self, path: str, expected_version: VersionToken) -> None:
        raise NotImplementedError

    def get_memory_index(self, scope_map: Mapping[str, str]) -> MemoryIndex:
        raise NotImplementedError


_TYPED_CLIENT: TransportClient = _FullClient()


def _stub(self: object, *args: object, **kwargs: object) -> NoReturn:
    raise NotImplementedError


def _matches_root(module: str, root: str) -> bool:
    return module == root or module.startswith(root + ".")


def _imported_modules(tree: ast.AST) -> list[str]:
    """Return the absolute module name of every import in the tree.

    Relative imports resolve against the ``wenchang`` package.
    """
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                assert node.module is not None
                base = node.module
            else:
                base = "wenchang" + (f".{node.module}" if node.module else "")
            if base == "wenchang":
                found.extend(f"wenchang.{alias.name}" for alias in node.names)
            else:
                found.append(base)
    return found


def _names_type_checking(test: ast.expr) -> bool:
    return any(
        (isinstance(node, ast.Name) and node.id == "TYPE_CHECKING")
        or (isinstance(node, ast.Attribute) and node.attr == "TYPE_CHECKING")
        for node in ast.walk(test)
    )


def test_transport_client_is_exported() -> None:
    """TransportClient imports from wenchang.transport and is in __all__ (AIE-1048, US1.1)."""
    assert isinstance(TransportClient, type)
    assert "TransportClient" in wenchang.transport.__all__


def test_transport_client_declares_exactly_seven_methods() -> None:
    """TransportClient's public methods are exactly the seven planned (AIE-1048, US1.2)."""
    names = {n for n, v in vars(TransportClient).items() if callable(v) and not n.startswith("_")}

    assert names == set(ALL_METHODS)


@pytest.mark.parametrize("method", STORE_METHODS)
def test_method_signature_matches_memory_store(method: str) -> None:
    """Each shared method's signature equals MemoryStore's (AIE-1048, US1.3)."""
    protocol_method: Callable[..., object] = getattr(TransportClient, method)
    store_method: Callable[..., object] = getattr(MemoryStore, method)

    assert inspect.signature(protocol_method, eval_str=True) == inspect.signature(
        store_method, eval_str=True
    )


def test_get_memory_index_signature() -> None:
    """get_memory_index takes a str-to-str Mapping and returns MemoryIndex (AIE-1048, US1.4)."""
    assert inspect.signature(TransportClient.get_memory_index, eval_str=True) == inspect.signature(
        _Ref.get_memory_index, eval_str=True
    )


@pytest.mark.parametrize("method", ALL_METHODS)
def test_method_has_docstring(method: str) -> None:
    """Every protocol method has a non-empty docstring (AIE-1048, US1.5)."""
    doc = getattr(TransportClient, method).__doc__

    assert isinstance(doc, str)
    assert doc.strip()


@pytest.mark.parametrize("name", ERROR_PARITY_NAMES)
def test_class_docstring_states_error_parity(name: str) -> None:
    """The class docstring names each error-parity reference (AIE-1048, US1.5)."""
    doc = TransportClient.__doc__

    assert doc is not None
    assert name in doc


def test_full_client_is_a_transport_client() -> None:
    """A class with all seven methods passes isinstance (AIE-1048, US2.1)."""
    candidate: object = _FullClient()

    assert isinstance(candidate, TransportClient)
    assert isinstance(_TYPED_CLIENT, TransportClient)


@pytest.mark.parametrize("missing", ALL_METHODS)
def test_client_missing_a_method_is_not_a_transport_client(missing: str) -> None:
    """A class lacking any one of the seven methods fails isinstance (AIE-1048, US2.2)."""
    namespace: dict[str, object] = {name: _stub for name in ALL_METHODS if name != missing}
    partial = type("Partial", (), namespace)
    candidate: object = partial()

    assert not isinstance(candidate, TransportClient)


def test_transport_client_cannot_be_instantiated() -> None:
    """Instantiating the protocol directly raises TypeError (AIE-1048, US2.3)."""
    with pytest.raises(TypeError):
        TransportClient()  # pyright: ignore[reportAbstractUsage]


def test_transport_module_imports_are_restricted() -> None:
    """transport.py imports only core, file_format, and version_token from wenchang,
    all at module level, with no __future__ import and no TYPE_CHECKING guard (AIE-1048, US4.1).
    """
    tree = ast.parse(TRANSPORT_MODULE.read_text(), filename=str(TRANSPORT_MODULE))
    modules = _imported_modules(tree)

    disallowed_wenchang = [
        m for m in modules if _matches_root(m, "wenchang") and m not in ALLOWED_WENCHANG_IMPORTS
    ]
    forbidden = [
        m for m in modules if any(_matches_root(m, root) for root in FORBIDDEN_IMPORT_ROOTS)
    ]
    guarded = [
        f"line {node.lineno}"
        for node in ast.walk(tree)
        if isinstance(node, ast.If) and _names_type_checking(node.test)
        for child in ast.walk(node)
        if isinstance(child, ast.Import | ast.ImportFrom)
    ]
    top_level = {id(node) for node in tree.body}
    nested = [
        f"line {node.lineno}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom) and id(node) not in top_level
    ]

    assert disallowed_wenchang == []
    assert forbidden == []
    assert "__future__" not in modules
    assert guarded == []
    assert nested == [], "every import must be a top-level module statement"


def test_core_does_not_import_transport() -> None:
    """core.py does not import wenchang.transport in any form (AIE-1048, US4.2).

    Regression guard: passes before transport.py exists.
    """
    tree = ast.parse(CORE_MODULE.read_text(), filename=str(CORE_MODULE))

    assert [m for m in _imported_modules(tree) if _matches_root(m, "wenchang.transport")] == []


def test_library_cites_no_linear_ids() -> None:
    """No module under src/wenchang/ matches AIE-\\d+ (AIE-1048, US4.3).

    Regression guard: passes before transport.py exists.
    """
    files = sorted(PACKAGE_DIR.rglob("*.py"))
    assert files, f"no modules found under {PACKAGE_DIR}"

    found = {
        str(path.relative_to(REPO_ROOT)): LINEAR_ID.findall(path.read_text()) for path in files
    }
    matches = {name: ids for name, ids in found.items() if ids}

    assert matches == {}
