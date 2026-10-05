"""Tests for InProcessClient, the in-process TransportClient.

Covers AIE-1046, US5.1 through US5.6, US6.1, and US6.3, and AIE-1151, US3.2 through US3.5.
"""

import ast
import inspect
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

import wenchang.transport
from wenchang.core import (
    ListCursor,
    ListPage,
    MemoryFile,
    MemoryIndex,
    MemoryStore,
)
from wenchang.errors import VersionConflictError
from wenchang.file_format import FileMetadata, MetadataFormatError
from wenchang.storage.memory import InMemoryStorage
from wenchang.transport import InProcessClient, TransportClient
from wenchang.version_token import VersionToken

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = REPO_ROOT / "src" / "wenchang"
TRANSPORT_MODULE = PACKAGE_DIR / "transport.py"
CORE_MODULE = PACKAGE_DIR / "core.py"

LINEAR_ID = re.compile(r"AIE-\d+")

ALL_METHODS = (
    "read_file",
    "write_file",
    "append_line",
    "replace_fact",
    "list_prefix",
    "delete_file",
    "get_memory_index",
)

ALLOWED_WENCHANG_IMPORTS = frozenset(
    {"wenchang.core", "wenchang.file_format", "wenchang.version_token"}
)

PATH = "user/u-1/notes/a.md"
OTHER_PATH = "org/o-9/glossary/b.md"
FIXED_NOW = datetime(2024, 1, 1, tzinfo=UTC)
META = FileMetadata(description="d", aliases=(), sources=frozenset({"t"}), last_updated=FIXED_NOW)

_A: TransportClient = InProcessClient(MemoryStore(InMemoryStorage()))
_B: TransportClient = MemoryStore(InMemoryStorage())


def _fixed_clock() -> datetime:
    return FIXED_NOW


class _RecordingStore(MemoryStore):
    """A MemoryStore that records every call and returns a per-method sentinel."""

    def __init__(self) -> None:
        super().__init__(InMemoryStorage())
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []
        self.raises: BaseException | None = None
        self.sentinels: dict[str, object] = {
            name: object() for name in ALL_METHODS if name != "delete_file"
        }

    def _record(self, name: str, args: tuple[object, ...], kwargs: dict[str, object]) -> object:
        self.calls.append((name, args, kwargs))
        if self.raises is not None:
            raise self.raises
        return self.sentinels.get(name)

    def read_file(self, *args: object, **kwargs: object) -> MemoryFile:
        return cast(MemoryFile, self._record("read_file", args, kwargs))

    def write_file(self, *args: object, **kwargs: object) -> MemoryFile:
        return cast(MemoryFile, self._record("write_file", args, kwargs))

    def append_line(self, *args: object, **kwargs: object) -> MemoryFile:
        return cast(MemoryFile, self._record("append_line", args, kwargs))

    def replace_fact(self, *args: object, **kwargs: object) -> MemoryFile:
        return cast(MemoryFile, self._record("replace_fact", args, kwargs))

    def list_prefix(self, *args: object, **kwargs: object) -> ListPage:
        return cast(ListPage, self._record("list_prefix", args, kwargs))

    def delete_file(self, *args: object, **kwargs: object) -> None:
        self._record("delete_file", args, kwargs)

    def get_memory_index(self, *args: object, **kwargs: object) -> MemoryIndex:
        return cast(MemoryIndex, self._record("get_memory_index", args, kwargs))


_SCOPE_MAP: Mapping[str, str] = {"user": "u-1", "org": "o-9"}
_V1 = VersionToken("v1")
_ALIASES = ("q",)

# Each call: method name, positional args, keyword args, as a client caller passes them.
_CALLS: tuple[tuple[str, tuple[object, ...], dict[str, object]], ...] = (
    ("read_file", (PATH,), {}),
    ("write_file", (PATH, "- [stated] x\n", META, None), {"source": "chat"}),
    ("write_file", (PATH, "- [stated] x\n", META, _V1), {"source": "chat"}),
    (
        "append_line",
        (PATH, "- [stated] y", _V1),
        {"source": "chat", "aliases": _ALIASES, "description": "d2"},
    ),
    (
        "replace_fact",
        (PATH, "x", "z", _V1),
        {"source": "chat", "aliases": _ALIASES, "description": "d2"},
    ),
    ("list_prefix", ("user/u-1/", None), {}),
    ("list_prefix", ("user/u-1/", ListCursor("abc")), {}),
    ("delete_file", (PATH, _V1), {}),
    ("get_memory_index", (_SCOPE_MAP,), {}),
)
_CALL_IDS = (
    "read_file",
    "write_file-create",
    "write_file-update",
    "append_line",
    "replace_fact",
    "list_prefix-first-page",
    "list_prefix-cursor",
    "delete_file",
    "get_memory_index",
)
_VALUE_CALLS = tuple(c for c in _CALLS if c[0] != "delete_file")
_VALUE_CALL_IDS = tuple(i for c, i in zip(_CALLS, _CALL_IDS, strict=True) if c[0] != "delete_file")


def _invoke(
    client: InProcessClient, name: str, args: tuple[object, ...], kw: dict[str, object]
) -> object:
    method: Callable[..., object] = getattr(client, name)
    return method(*args, **kw)


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


def test_client_and_store_are_transport_clients() -> None:
    """InProcessClient and MemoryStore both satisfy TransportClient (AIE-1046, US5.1)."""
    store = MemoryStore(InMemoryStorage())
    client = InProcessClient(store)

    assert client.store is store
    assert isinstance(client, TransportClient)
    assert isinstance(cast(object, store), TransportClient)
    assert isinstance(_A, TransportClient)


def test_in_process_client_is_exported() -> None:
    """InProcessClient is in wenchang.transport.__all__ (AIE-1046, US5.1)."""
    assert "InProcessClient" in wenchang.transport.__all__


@pytest.mark.parametrize(("name", "args", "kwargs"), _VALUE_CALLS, ids=_VALUE_CALL_IDS)
def test_value_methods_forward_unchanged(
    name: str, args: tuple[object, ...], kwargs: dict[str, object]
) -> None:
    """Each value-returning method returns the store's object and passes the same
    arguments (AIE-1046, US5.2).
    """
    store = _RecordingStore()
    client = InProcessClient(store)

    result = _invoke(client, name, args, kwargs)

    assert result is store.sentinels[name]
    assert store.calls == [(name, args, kwargs)]
    _, recorded_args, _ = store.calls[0]
    assert all(r is a for r, a in zip(recorded_args, args, strict=True))


def test_delete_file_forwards_and_returns_none() -> None:
    """delete_file passes the same arguments and returns None (AIE-1046, US5.2)."""
    store = _RecordingStore()
    client = InProcessClient(store)

    result = client.delete_file(PATH, _V1)

    assert result is None
    assert store.calls == [("delete_file", (PATH, _V1), {})]


class _ValueReturningDeleteStore(MemoryStore):
    """A MemoryStore whose delete_file returns a sentinel instead of None."""

    sentinel = object()

    def __init__(self) -> None:
        super().__init__(InMemoryStorage())

    def delete_file(self, path: str, expected_version: VersionToken) -> None:
        return cast(None, self.sentinel)


def test_delete_file_returns_none_even_if_store_returns_a_value() -> None:
    """delete_file returns None even when the store's delete_file returns a
    value (AIE-1046, US5.2).
    """
    client = InProcessClient(_ValueReturningDeleteStore())

    assert client.delete_file(PATH, _V1) is None


def _fresh_exceptions() -> list[Callable[[], BaseException]]:
    return [
        lambda: VersionConflictError(PATH, "body", _V1),
        lambda: ValueError("bad"),
        lambda: MetadataFormatError("last-updated", "bad"),
    ]


@pytest.mark.parametrize("make_exc", _fresh_exceptions(), ids=["wenchang", "value", "metadata"])
@pytest.mark.parametrize(("name", "args", "kwargs"), _CALLS, ids=_CALL_IDS)
def test_exceptions_propagate_unchanged(
    name: str,
    args: tuple[object, ...],
    kwargs: dict[str, object],
    make_exc: Callable[[], BaseException],
) -> None:
    """A store exception propagates as the same object, with no cause or context
    added (AIE-1046, US5.3).
    """
    store = _RecordingStore()
    configured = make_exc()
    store.raises = configured
    client = InProcessClient(store)

    with pytest.raises(type(configured)) as exc_info:
        _invoke(client, name, args, kwargs)

    assert exc_info.value is configured
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


class _Description(str):
    """A str subclass, so forwarding by identity is distinguishable from normalizing."""


_FACT_CALLS: tuple[tuple[str, tuple[object, ...]], ...] = (
    ("append_line", (PATH, "- [stated] y", _V1)),
    ("replace_fact", (PATH, "x", "z", _V1)),
)


@pytest.mark.parametrize(("name", "args"), _FACT_CALLS, ids=[c[0] for c in _FACT_CALLS])
def test_alias_and_description_keywords_forward_by_identity(
    name: str, args: tuple[object, ...]
) -> None:
    """append_line and replace_fact pass path and strings positionally and
    source, aliases, and description as keywords, the same objects, returning
    the store's object (AIE-1151, US3.2, US3.4).
    """
    store = _RecordingStore()
    client = InProcessClient(store)
    source = _Description("chat")
    aliases = ["q", "r"]
    description = _Description("d2")

    result = _invoke(
        client, name, args, {"source": source, "aliases": aliases, "description": description}
    )

    assert result is store.sentinels[name]
    assert len(store.calls) == 1
    recorded_name, recorded_args, recorded_kwargs = store.calls[0]
    assert recorded_name == name
    assert len(recorded_args) == len(args)
    assert all(r is a for r, a in zip(recorded_args, args, strict=True))
    assert set(recorded_kwargs) == {"source", "aliases", "description"}
    assert recorded_kwargs["source"] is source
    assert recorded_kwargs["aliases"] is aliases
    assert recorded_kwargs["description"] is description


@pytest.mark.parametrize(("name", "args"), _FACT_CALLS, ids=[c[0] for c in _FACT_CALLS])
def test_omitted_alias_and_description_forward_as_none(name: str, args: tuple[object, ...]) -> None:
    """Omitting aliases and description forwards them explicitly as None
    (AIE-1151, US3.3, US3.4).
    """
    store = _RecordingStore()
    client = InProcessClient(store)

    _invoke(client, name, args, {"source": "chat"})

    assert store.calls == [(name, args, {"source": "chat", "aliases": None, "description": None})]


def _run_sequence(target: TransportClient) -> list[object]:
    results: list[object] = []
    written = target.write_file(PATH, "- [stated] alpha\n", META, None, source="chat")
    results.append(written)
    read = target.read_file(PATH)
    results.append(read)
    appended = target.append_line(PATH, "- [stated] beta", read.version, source="chat")
    results.append(appended)
    replaced = target.replace_fact(PATH, "alpha", "gamma", appended.version, source="chat")
    results.append(replaced)
    results.append(target.write_file(OTHER_PATH, "- [stated] term\n", META, None, source="doc"))
    results.append(target.list_prefix("user/u-1/"))
    results.append(target.get_memory_index(_SCOPE_MAP))
    results.append(target.delete_file(PATH, replaced.version))
    results.append(target.list_prefix("user/u-1/"))
    results.append(target.get_memory_index(_SCOPE_MAP))
    return results


def test_end_to_end_matches_direct_store() -> None:
    """A full operation sequence through the client equals the same sequence run
    directly on a fresh store (AIE-1046, US5.4).
    """
    via_client = _run_sequence(InProcessClient(MemoryStore(InMemoryStorage(), clock=_fixed_clock)))
    direct = _run_sequence(MemoryStore(InMemoryStorage(), clock=_fixed_clock))

    assert len(via_client) == len(direct)
    for got, expected in zip(via_client, direct, strict=True):
        assert got == expected


def test_non_store_is_rejected() -> None:
    """InProcessClient rejects an argument whose real type is not a MemoryStore
    (AIE-1046, US5.5).
    """
    with pytest.raises(TypeError):
        InProcessClient(cast(MemoryStore, object()))


def test_store_subclass_is_accepted() -> None:
    """A MemoryStore subclass is accepted (AIE-1046, US5.5)."""
    store = _RecordingStore()

    assert InProcessClient(store).store is store


class _Spoofed:
    """Claims to be a MemoryStore through __class__ only."""

    @property
    def __class__(self) -> type:  # pyright: ignore[reportIncompatibleMethodOverride]
        return MemoryStore


def test_spoofed_class_is_rejected() -> None:
    """A spoofed __class__ does not pass the real-type check (AIE-1046, US5.5)."""
    with pytest.raises(TypeError):
        InProcessClient(cast(MemoryStore, _Spoofed()))


class _RaisingNameMeta(type):
    """A metaclass whose classes raise on __name__ access."""

    @property
    def __name__(self) -> str:  # pyright: ignore[reportIncompatibleVariableOverride]
        raise ZeroDivisionError


class _RaisingName(metaclass=_RaisingNameMeta):
    """An object whose type's __name__ raises."""


def test_non_store_with_raising_type_name_is_rejected_with_type_error() -> None:
    """A non-store whose type's __name__ raises still yields TypeError
    (AIE-1046, US5.5).
    """
    with pytest.raises(TypeError):
        InProcessClient(cast(MemoryStore, _RaisingName()))


@pytest.mark.parametrize("method", ALL_METHODS)
def test_client_signature_matches_protocol(method: str) -> None:
    """Each InProcessClient method's signature equals TransportClient's (AIE-1046, US5.6)."""
    client_method: Callable[..., object] = getattr(InProcessClient, method)
    protocol_method: Callable[..., object] = getattr(TransportClient, method)

    assert inspect.signature(client_method, eval_str=True) == inspect.signature(
        protocol_method, eval_str=True
    )


def test_store_get_memory_index_signature_matches_protocol() -> None:
    """MemoryStore.get_memory_index's signature equals TransportClient's (AIE-1046, US5.6)."""
    assert inspect.signature(MemoryStore.get_memory_index, eval_str=True) == inspect.signature(
        TransportClient.get_memory_index, eval_str=True
    )


def test_transport_module_imports_are_restricted() -> None:
    """transport.py imports only core, file_format, and version_token from wenchang, all
    top-level, with no __future__ import or TYPE_CHECKING guard, and takes MemoryStore from
    wenchang.core (AIE-1046, US6.1).
    """
    tree = ast.parse(TRANSPORT_MODULE.read_text(), filename=str(TRANSPORT_MODULE))
    modules = _imported_modules(tree)

    disallowed = [
        m for m in modules if _matches_root(m, "wenchang") and m not in ALLOWED_WENCHANG_IMPORTS
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
    from_core = {
        alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module == "wenchang.core"
        for alias in node.names
    }

    assert disallowed == []
    assert "__future__" not in modules
    assert guarded == []
    assert nested == [], "every import must be a top-level module statement"
    assert "MemoryStore" in from_core


def test_core_does_not_import_transport() -> None:
    """core.py does not import wenchang.transport (AIE-1046, US6.1)."""
    tree = ast.parse(CORE_MODULE.read_text(), filename=str(CORE_MODULE))

    assert [m for m in _imported_modules(tree) if _matches_root(m, "wenchang.transport")] == []


def test_library_cites_no_linear_ids() -> None:
    """No module under src/wenchang/ matches AIE-\\d+ (AIE-1046, US6.3).

    Regression guard: passes once the module imports.
    """
    files = sorted(PACKAGE_DIR.rglob("*.py"))
    assert files, f"no modules found under {PACKAGE_DIR}"

    found = {
        str(path.relative_to(REPO_ROOT)): LINEAR_ID.findall(path.read_text()) for path in files
    }

    assert {name: ids for name, ids in found.items() if ids} == {}
