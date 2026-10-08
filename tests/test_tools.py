"""Tests for the scope-relative memory tools in wenchang.tools.

Covers AIE-1044, US1 (construction and binding), US2 (reads, listing, index),
US3 (checked writes), US4 (argument-error conversion), and US6 (module
boundaries); AIE-1151, US4 (aliases and description on append_line and
replace_fact); and AIE-1164, US4 (the product constructor argument).
"""

import ast
import functools
import gc
import inspect
import tomllib
import weakref
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Concatenate, cast

import pytest

import wenchang.scope
import wenchang.tools
from wenchang.core import FileEntry, ListCursor, ListPage, MemoryFile, MemoryIndex
from wenchang.errors import (
    BackendUnavailableError,
    ErrorCategory,
    InvalidArgumentError,
    NotFoundError,
    NotFoundReason,
    OversizeWriteError,
    ReplaceFactMatchError,
    ResolverFailureError,
    RestrictedScopeError,
    RestrictionReason,
    TransientReason,
    VersionConflictError,
)
from wenchang.file_format import FileMetadata, MetadataFormatError
from wenchang.identity import Identity, ResolutionFailure, SandboxResolver, ScopeGrant
from wenchang.scope import ScopePolicy
from wenchang.tools import MemoryTools, bind_tools
from wenchang.transport import TransportClient
from wenchang.version_token import VersionToken

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = REPO_ROOT / "src" / "wenchang"
TOOLS_MODULE = PACKAGE_DIR / "tools.py"

SOURCE = "test-surface"
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
VERSION = VersionToken("v1")
CONTENT = "- [stated] Likes tea"
DESCRIPTION = "Tea preferences"
LINE = "- [observed] Drinks it black"
OLD = "Likes tea"
NEW = "Likes green tea"
ORG_ROLES = frozenset({"admin", "owner"})

GRANTS = {"user": ScopeGrant("u-1", "owner"), "org": ScopeGrant("o-9", "member")}
IDENTITY = Identity(GRANTS)
OWNER_IDENTITY = Identity({"user": ScopeGrant("u-1", "owner"), "org": ScopeGrant("o-9", "owner")})
POLICY = ScopePolicy({"org": ORG_ROLES})

UNGRANTED_DETAIL = (
    "Argument scope is invalid: scope 'team' is not available in this session; "
    "available scopes: org, user"
)

READ_TOOLS = ("read_file", "list_prefix", "get_memory_index")
MUTATING_TOOLS = ("write_file", "append_line", "replace_fact", "delete_file")
SCOPE_TOOLS = ("read_file", "list_prefix", *MUTATING_TOOLS)
NAME_TOOLS = ("read_file", *MUTATING_TOOLS)
ALL_TOOLS = ("get_memory_index", "read_file", "list_prefix", *MUTATING_TOOLS)

ALLOWED_WENCHANG_IMPORTS = frozenset(
    {
        "wenchang.core",
        "wenchang.errors",
        "wenchang.file_format",
        "wenchang.identity",
        "wenchang.paths",
        "wenchang.scope",
        "wenchang.transport",
        "wenchang.version_token",
    }
)

type _Call = tuple[str, tuple[object, ...], dict[str, object]]


def _metadata(description: str = DESCRIPTION, aliases: tuple[str, ...] = ()) -> FileMetadata:
    return FileMetadata(description, aliases, frozenset({SOURCE}), datetime(2026, 1, 1, tzinfo=UTC))


def _file(path: str = "user/u-1/notes/a.md") -> MemoryFile:
    return MemoryFile(path, CONTENT, _metadata(), VersionToken("v2"))


# --- Test doubles ---------------------------------------------------------------


def _recorded[**P, R](
    method: Callable[Concatenate["_FakeClient", P], R],
) -> Callable[Concatenate["_FakeClient", P], R]:
    """Record each call as (name, args, kwargs), then raise or return the preset."""
    name = method.__name__

    @functools.wraps(method)
    def wrapper(self: "_FakeClient", *args: P.args, **kwargs: P.kwargs) -> R:
        self.log.append((name, tuple(args), dict(kwargs)))
        error = self.raises.get(name)
        if error is not None:
            raise error
        return method(self, *args, **kwargs)

    return wrapper


class _FakeClient:
    """A TransportClient recording double with preset returns and raises."""

    def __init__(self, log: list[_Call]) -> None:
        self.log = log
        self.raises: dict[str, BaseException] = {}
        self.returns: dict[str, object] = {
            "read_file": _file(),
            "write_file": _file(),
            "append_line": _file(),
            "replace_fact": _file(),
            "list_prefix": ListPage((), None),
            "delete_file": None,
            "get_memory_index": MemoryIndex(),
        }

    @_recorded
    def read_file(self, path: str) -> MemoryFile:
        return cast(MemoryFile, self.returns["read_file"])

    @_recorded
    def write_file(
        self,
        path: str,
        content: str,
        metadata: FileMetadata,
        expected_version: VersionToken | None,
        *,
        source: str,
    ) -> MemoryFile:
        return cast(MemoryFile, self.returns["write_file"])

    @_recorded
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
        return cast(MemoryFile, self.returns["append_line"])

    @_recorded
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
        return cast(MemoryFile, self.returns["replace_fact"])

    @_recorded
    def list_prefix(self, prefix: str, cursor: ListCursor | None = None) -> ListPage:
        return cast(ListPage, self.returns["list_prefix"])

    @_recorded
    def delete_file(self, path: str, expected_version: VersionToken) -> None:
        return None

    @_recorded
    def get_memory_index(self, scope_map: Mapping[str, str]) -> MemoryIndex:
        return cast(MemoryIndex, self.returns["get_memory_index"])


@dataclass
class _Harness:
    log: list[_Call]
    client: _FakeClient
    tools: MemoryTools

    def client_calls(self) -> list[_Call]:
        return [call for call in self.log if call[0] != "check_write"]

    def spy_calls(self) -> list[_Call]:
        return [call for call in self.log if call[0] == "check_write"]


def _make(monkeypatch: pytest.MonkeyPatch, identity: Identity = IDENTITY) -> _Harness:
    log: list[_Call] = []

    def spy(path: str, identity: Identity, policy: ScopePolicy) -> None:
        log.append(("check_write", (path, identity, policy), {}))
        wenchang.scope.check_write(path, identity, policy)

    monkeypatch.setattr(wenchang.tools, "check_write", spy)
    client = _FakeClient(log)
    tools = MemoryTools(client, identity, POLICY, source=SOURCE)
    return _Harness(log, client, tools)


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> _Harness:
    return _make(monkeypatch)


def _base(
    tool: str, scope: str = "user", area: str = "notes", name: str = "a"
) -> dict[str, object]:
    """Well-formed keyword arguments for each tool."""
    if tool == "get_memory_index":
        return {}
    if tool == "list_prefix":
        return {"scope": scope, "area": area, "cursor": None}
    segments: dict[str, object] = {"scope": scope, "area": area, "name": name}
    extra: dict[str, dict[str, object]] = {
        "read_file": {},
        "write_file": {
            "content": CONTENT,
            "description": DESCRIPTION,
            "aliases": ["tea"],
            "expected_version": VERSION,
        },
        "append_line": {"line": LINE, "expected_version": VERSION},
        "replace_fact": {"old_string": OLD, "new_string": NEW, "expected_version": VERSION},
        "delete_file": {"expected_version": VERSION},
    }
    return segments | extra[tool]


def _call(h: _Harness, tool: str, **overrides: object) -> object:
    kwargs = _base(tool) | overrides
    method: Callable[..., object] = getattr(h.tools, tool)
    return method(**kwargs)


def _bound(call: _Call) -> dict[str, object]:
    """A recorded client call's arguments by parameter name, defaults applied."""
    name, args, kwargs = call
    signature = inspect.signature(getattr(TransportClient, name))
    bound = signature.bind(None, *args, **kwargs)
    bound.apply_defaults()
    arguments = dict(bound.arguments)
    del arguments["self"]
    return arguments


def _forwarded_metadata(kwargs: dict[str, object]) -> dict[str, object]:
    """The aliases and description a fact tool forwards: None when omitted."""
    aliases = kwargs.get("aliases")
    return {
        "aliases": None if aliases is None else tuple(cast(Sequence[str], aliases)),
        "description": kwargs.get("description"),
    }


def _expected(tool: str, path: str, kwargs: dict[str, object]) -> dict[str, object]:
    """The forwarded client arguments for a file tool called with kwargs."""
    if tool == "read_file":
        return {"path": path}
    if tool == "write_file":
        aliases = tuple(cast(list[str], kwargs["aliases"]))
        metadata = FileMetadata(cast(str, kwargs["description"]), aliases, frozenset(), EPOCH)
        return {
            "path": path,
            "content": kwargs["content"],
            "metadata": metadata,
            "expected_version": kwargs["expected_version"],
            "source": SOURCE,
        }
    if tool == "append_line":
        return {
            "path": path,
            "line": kwargs["line"],
            "expected_version": kwargs["expected_version"],
            "source": SOURCE,
            **_forwarded_metadata(kwargs),
        }
    if tool == "replace_fact":
        return {
            "path": path,
            "old_string": kwargs["old_string"],
            "new_string": kwargs["new_string"],
            "expected_version": kwargs["expected_version"],
            "source": SOURCE,
            **_forwarded_metadata(kwargs),
        }
    assert tool == "delete_file"
    return {"path": path, "expected_version": kwargs["expected_version"]}


def _invalid(h: _Harness, tool: str, argument: str, **overrides: object) -> InvalidArgumentError:
    """Call the tool, expect InvalidArgumentError naming argument and no client call."""
    with pytest.raises(InvalidArgumentError) as excinfo:
        _call(h, tool, **overrides)
    assert excinfo.value.argument == argument
    assert h.client_calls() == []
    return excinfo.value


def _wrong_type_detail(argument: str, type_name: str) -> str:
    return f"Argument {argument} is invalid: {argument} must be a string, not {type_name}"


class _LyingStr(str):
    """A str subclass whose formatting, equality, and hashing lie."""

    def __str__(self) -> str:
        return "evil"

    def __format__(self, format_spec: str) -> str:
        return "evil"

    def __eq__(self, other: object) -> bool:
        return True

    def __hash__(self) -> int:
        return 0


class _NameRaisingMeta(type):
    """A metaclass whose classes raise when their __name__ is read."""

    @property
    def __name__(self) -> str:  # pyright: ignore[reportIncompatibleVariableOverride]
        raise RuntimeError("no name")


class _UnnamedValue(metaclass=_NameRaisingMeta):
    """A value whose type name cannot be read."""


class _IdentitySpoof:
    """Claims to be an Identity through __class__; its real type is not."""

    grants = GRANTS

    @property
    def __class__(self) -> type:  # pyright: ignore[reportIncompatibleVariableOverride, reportIncompatibleMethodOverride]
        return Identity


class _PolicySpoof:
    """Claims to be a ScopePolicy through __class__; its real type is not."""

    write_roles = POLICY.write_roles

    @property
    def __class__(self) -> type:  # pyright: ignore[reportIncompatibleVariableOverride, reportIncompatibleMethodOverride]
        return ScopePolicy


class _LyingIdentity(Identity):
    """An Identity whose entity_id() names a different entity than its grants."""

    def entity_id(self, scope: str) -> str:
        return "u-evil"


class _FailingResolver:
    def resolve(self, credentials: object) -> Identity | ResolutionFailure:
        return ResolutionFailure("expired")


class _RaisingResolver:
    def resolve(self, credentials: object) -> Identity | ResolutionFailure:
        raise RuntimeError("secret")


class _Credentials:
    """A weakref-able credentials sentinel."""


class _LyingScopeMapIdentity(Identity):
    """An Identity whose scope_map names different entities than its grants."""

    @property
    def scope_map(self) -> dict[str, str]:
        return {"user": "u-evil", "org": "o-evil"}


class _UnreadableValueError(ValueError):
    """A ValueError whose message cannot be read."""

    def __str__(self) -> str:
        raise RuntimeError("unreadable")


class _ListSpoof:
    """Claims to be a list through __class__; its real type is not, and it is not iterable."""

    __class__ = list  # pyright: ignore[reportAssignmentType, reportIncompatibleMethodOverride, reportIncompatibleVariableOverride]


def _unicode_decode_error() -> UnicodeDecodeError:
    return UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")


# --- US1: construction and binding ------------------------------------------------


def test_constructor_exposes_read_only_properties() -> None:
    """MemoryTools exposes client, identity, policy, and source as read-only
    properties (AIE-1044, US1.1).
    """
    client = _FakeClient([])
    tools = MemoryTools(client, IDENTITY, POLICY, source="s")

    assert tools.identity is IDENTITY
    assert tools.policy is POLICY
    assert tools.client is client
    assert tools.source == "s"
    for attribute in ("client", "identity", "policy", "source"):
        with pytest.raises(AttributeError):
            setattr(tools, attribute, None)


def test_empty_source_raises_value_error() -> None:
    """An empty source raises ValueError at construction (AIE-1044, US1.2)."""
    with pytest.raises(ValueError):
        MemoryTools(_FakeClient([]), IDENTITY, POLICY, source="")


@pytest.mark.parametrize("source", [5, b"s", None], ids=["int", "bytes", "none"])
def test_non_str_source_raises_type_error(source: object) -> None:
    """A source whose real type is not str raises TypeError (AIE-1044, US1.2)."""
    with pytest.raises(TypeError):
        MemoryTools(_FakeClient([]), IDENTITY, POLICY, source=cast(str, source))


def test_str_subclass_source_is_stored_as_exact_str() -> None:
    """A str-subclass source is stored as an exact str (AIE-1044, US1.2)."""
    tools = MemoryTools(_FakeClient([]), IDENTITY, POLICY, source=_LyingStr("surface"))

    assert type(tools.source) is str
    assert str.__eq__(tools.source, "surface") is True


def test_non_client_raises_type_error() -> None:
    """A client that does not satisfy TransportClient raises TypeError (AIE-1044, US1.3)."""
    with pytest.raises(TypeError):
        MemoryTools(cast(TransportClient, object()), IDENTITY, POLICY, source=SOURCE)


@pytest.mark.parametrize(
    "identity",
    [{"user": ScopeGrant("u-1", "owner")}, ScopeGrant("u-1", "owner"), _IdentitySpoof()],
    ids=["dict", "grant", "spoofed-class"],
)
def test_non_identity_raises_type_error(identity: object) -> None:
    """An identity whose real type is not Identity raises TypeError, even if
    its __class__ claims Identity (AIE-1044, US1.3).
    """
    with pytest.raises(TypeError):
        MemoryTools(_FakeClient([]), cast(Identity, identity), POLICY, source=SOURCE)


@pytest.mark.parametrize(
    "policy",
    [{"org": ORG_ROLES}, None, _PolicySpoof()],
    ids=["dict", "none", "spoofed-class"],
)
def test_non_policy_raises_type_error(policy: object) -> None:
    """A policy whose real type is not ScopePolicy raises TypeError, even if
    its __class__ claims ScopePolicy (AIE-1044, US1.3).
    """
    with pytest.raises(TypeError):
        MemoryTools(_FakeClient([]), IDENTITY, cast(ScopePolicy, policy), source=SOURCE)


def test_bind_tools_resolves_identity() -> None:
    """bind_tools with a SandboxResolver returns MemoryTools for the resolved
    identity (AIE-1044, US1.4).
    """
    client = _FakeClient([])

    tools = bind_tools(client, SandboxResolver(IDENTITY), object(), POLICY, source="s")

    assert type(tools) is MemoryTools
    assert tools.identity == IDENTITY
    assert tools.client is client
    assert tools.policy is POLICY
    assert tools.source == "s"


def test_bind_tools_resolution_failure_is_permanent_and_never_calls_client() -> None:
    """A ResolutionFailure becomes a PERMANENT ResolverFailureError and the
    client is never called (AIE-1044, US1.5).
    """
    log: list[_Call] = []

    with pytest.raises(ResolverFailureError) as excinfo:
        bind_tools(_FakeClient(log), _FailingResolver(), object(), POLICY, source=SOURCE)

    assert excinfo.value.category is ErrorCategory.PERMANENT
    assert "expired" in str(excinfo.value)
    assert log == []


def test_bind_tools_raising_resolver_does_not_leak_message() -> None:
    """A resolver raising RuntimeError("secret") yields ResolverFailureError
    whose message omits the secret (AIE-1044, US1.6).
    """
    log: list[_Call] = []

    with pytest.raises(ResolverFailureError) as excinfo:
        bind_tools(_FakeClient(log), _RaisingResolver(), object(), POLICY, source=SOURCE)

    assert "secret" not in str(excinfo.value)
    assert log == []


def test_bind_tools_does_not_retain_credentials() -> None:
    """The credentials passed to bind_tools are not reachable from the
    returned tools once the caller drops them (AIE-1044, US1.7).
    """
    credentials = _Credentials()
    ref = weakref.ref(credentials)

    tools = bind_tools(_FakeClient([]), SandboxResolver(IDENTITY), credentials, POLICY, source="s")
    del credentials
    gc.collect()

    assert ref() is None
    assert tools.identity == IDENTITY


# --- product ----------------------------------------------------------------------


class _StrSpoof:
    """Claims to be a str through __class__; its real type is not."""

    @property
    def __class__(self) -> type:  # pyright: ignore[reportIncompatibleVariableOverride, reportIncompatibleMethodOverride]
        return str


PRODUCT_LINE_BOUNDARIES = {
    "lf": "\n",
    "cr": "\r",
    "crlf": "\r\n",
    "vt": "\x0b",
    "ff": "\x0c",
    "fs": "\x1c",
    "gs": "\x1d",
    "rs": "\x1e",
    "nel": "\x85",
    "ls": chr(0x2028),
    "ps": chr(0x2029),
}


def _with_product(product: object) -> MemoryTools:
    return MemoryTools(_FakeClient([]), IDENTITY, POLICY, source=SOURCE, product=cast(str, product))


def test_product_defaults_to_none() -> None:
    """Without a product argument, MemoryTools.product is None (AIE-1164, US4.1)."""
    tools = MemoryTools(_FakeClient([]), IDENTITY, POLICY, source=SOURCE)

    assert tools.product is None


def test_product_none_is_stored_as_none() -> None:
    """An explicit product=None is stored as None (AIE-1164, US4.1)."""
    assert _with_product(None).product is None


def test_product_is_stored_from_constructor() -> None:
    """product="Mixpanel" is exposed as tools.product (AIE-1164, US4.2)."""
    assert _with_product("Mixpanel").product == "Mixpanel"


def test_bind_tools_forwards_product() -> None:
    """bind_tools forwards product to MemoryTools, and without product the
    bound tools have product None (AIE-1164, US4.2).
    """
    resolver = SandboxResolver(IDENTITY)

    with_product = bind_tools(
        _FakeClient([]), resolver, object(), POLICY, source=SOURCE, product="Mixpanel"
    )
    without_product = bind_tools(_FakeClient([]), resolver, object(), POLICY, source=SOURCE)

    assert with_product.product == "Mixpanel"
    assert without_product.product is None


@pytest.mark.parametrize(
    "product", ["  Mixpanel \n", _LyingStr("  Mixpanel \n")], ids=["padded", "lying-subclass"]
)
def test_product_is_stripped_to_exact_str(product: str) -> None:
    """A padded or lying str-subclass product is stored as the exact str
    "Mixpanel" (AIE-1164, US4.3).
    """
    stored = _with_product(product).product

    assert type(stored) is str
    assert str.__eq__(stored, "Mixpanel") is True


@pytest.mark.parametrize(
    ("product", "type_name"),
    [(5, "int"), (b"Mixpanel", "bytes"), (_StrSpoof(), "_StrSpoof")],
    ids=["int", "bytes", "spoofed-class"],
)
def test_non_str_product_raises_type_error(product: object, type_name: str) -> None:
    """A product whose real type is neither str nor None raises TypeError
    naming that type, even if its __class__ claims str (AIE-1164, US4.4).
    """
    with pytest.raises(TypeError) as excinfo:
        _with_product(product)

    assert type(excinfo.value) is TypeError
    assert str(excinfo.value) == f"product must be a str or None, not {type_name}"


@pytest.mark.parametrize("product", ["", "  ", "\n\t"], ids=["empty", "spaces", "newline-tab"])
def test_blank_product_raises_value_error(product: str) -> None:
    """An empty or whitespace-only product raises ValueError (AIE-1164, US4.5)."""
    with pytest.raises(ValueError) as excinfo:
        _with_product(product)

    assert type(excinfo.value) is ValueError
    assert str(excinfo.value) == "product must be non-empty"


@pytest.mark.parametrize("boundary", PRODUCT_LINE_BOUNDARIES.values(), ids=PRODUCT_LINE_BOUNDARIES)
def test_multiline_product_raises_value_error(boundary: str) -> None:
    """A product with a str.splitlines boundary inside the stripped text
    raises ValueError (AIE-1164, US4.6).
    """
    with pytest.raises(ValueError) as excinfo:
        _with_product(f"Mix{boundary}panel")

    assert type(excinfo.value) is ValueError
    assert str(excinfo.value) == "product must be one line"


def test_unencodable_product_raises_value_error() -> None:
    """A product with a lone surrogate raises ValueError chained from the
    UnicodeEncodeError (AIE-1164, US4.7).
    """
    with pytest.raises(ValueError) as excinfo:
        _with_product("Mix\ud800panel")

    assert type(excinfo.value) is ValueError
    assert str(excinfo.value) == "product must be encodable as UTF-8"
    assert isinstance(excinfo.value.__cause__, UnicodeEncodeError)


def test_product_is_read_only() -> None:
    """Assigning tools.product raises AttributeError (AIE-1164, US4.8)."""
    tools = _with_product("Mixpanel")
    attribute = "product"

    with pytest.raises(AttributeError):
        setattr(tools, attribute, "Other")
    assert tools.product == "Mixpanel"


def test_product_is_keyword_only_on_memory_tools() -> None:
    """product cannot be passed positionally to MemoryTools, and is declared
    keyword-only with default None (AIE-1164, US4.9).
    """
    parameter = inspect.signature(MemoryTools).parameters["product"]

    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is None
    construct = cast(Callable[..., object], MemoryTools)
    with pytest.raises(TypeError):
        construct(_FakeClient([]), IDENTITY, POLICY, "s", "X")


def test_product_is_keyword_only_on_bind_tools() -> None:
    """product cannot be passed positionally to bind_tools, and is declared
    keyword-only with default None (AIE-1164, US4.9).
    """
    parameter = inspect.signature(bind_tools).parameters["product"]

    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is None
    bind = cast(Callable[..., object], bind_tools)
    with pytest.raises(TypeError):
        bind(_FakeClient([]), SandboxResolver(IDENTITY), object(), POLICY, "X")


@pytest.mark.parametrize("tool", ALL_TOOLS)
def test_tool_methods_take_no_product_parameter(tool: str) -> None:
    """No tool method has a product parameter (AIE-1164, US4.10)."""
    assert "product" not in inspect.signature(getattr(MemoryTools, tool)).parameters


def test_tools_mapping_unchanged_with_product() -> None:
    """With a product set, tools() still maps each tool name to the bound
    method of that name (AIE-1164, US4.10).
    """
    tools = _with_product("Mixpanel")

    mapping = tools.tools()

    assert list(mapping) == list(wenchang.tools.TOOL_NAMES)
    assert dict(mapping) == {name: getattr(tools, name) for name in wenchang.tools.TOOL_NAMES}


@pytest.mark.parametrize(
    ("source", "product", "expected"),
    [("", 5, ValueError), (5, "", TypeError)],
    ids=["empty-source-int-product", "int-source-empty-product"],
)
def test_source_error_precedes_product_error(
    source: object, product: object, expected: type[Exception]
) -> None:
    """With both source and product invalid, the source error is raised
    (AIE-1164, US4.11).
    """
    with pytest.raises(expected) as excinfo:
        MemoryTools(
            _FakeClient([]),
            IDENTITY,
            POLICY,
            source=cast(str, source),
            product=cast(str, product),
        )

    assert "product" not in str(excinfo.value)


# --- US2: reads, listing, and index ---------------------------------------------


def test_read_file_builds_own_path_and_returns_client_result(harness: _Harness) -> None:
    """read_file forwards the caller's built path, returns the client's
    object, and never runs check_write (AIE-1044, US2.1).
    """
    preset = _file("org/o-9/notes/a.md")
    harness.client.returns["read_file"] = preset

    result = harness.tools.read_file("org", "notes", "a")

    assert result is preset
    assert [(c[0], _bound(c)) for c in harness.log] == [
        ("read_file", {"path": "org/o-9/notes/a.md"})
    ]
    assert harness.spy_calls() == []


def test_read_file_may_read_system_area(harness: _Harness) -> None:
    """Reading the system/ area is allowed and forwarded (AIE-1044, US2.1)."""
    harness.tools.read_file("user", "system", "rules")

    assert [(c[0], _bound(c)) for c in harness.log] == [
        ("read_file", {"path": "user/u-1/system/rules.md"})
    ]


def test_list_prefix_scope_only_passes_entity_prefix_positionally(harness: _Harness) -> None:
    """list_prefix(scope) forwards ("user/u-1/", None) positionally and
    returns the client's object (AIE-1044, US2.2).
    """
    preset = ListPage((), None)
    harness.client.returns["list_prefix"] = preset

    result = harness.tools.list_prefix("user")

    assert result is preset
    assert harness.log == [("list_prefix", ("user/u-1/", None), {})]


def test_list_prefix_with_area_and_cursor_passes_both_positionally(harness: _Harness) -> None:
    """list_prefix(scope, area, cursor) forwards ("user/u-1/notes/", cursor)
    positionally and never runs check_write (AIE-1044, US2.2).
    """
    cursor = ListCursor("abc")
    entry = FileEntry("user/u-1/notes/a.md", _metadata(), VERSION)
    preset = ListPage((entry,), ListCursor("next"))
    harness.client.returns["list_prefix"] = preset

    result = harness.tools.list_prefix("user", "notes", cursor)

    assert result is preset
    assert harness.log == [("list_prefix", ("user/u-1/notes/", cursor), {})]
    assert harness.spy_calls() == []


def test_get_memory_index_passes_scope_map(harness: _Harness) -> None:
    """get_memory_index passes the scope map built from identity.grants and
    returns the client's object, without check_write (AIE-1044, US2.3).
    """
    preset = MemoryIndex()
    harness.client.returns["get_memory_index"] = preset

    result = harness.tools.get_memory_index()

    assert result is preset
    assert [(c[0], _bound(c)) for c in harness.log] == [
        ("get_memory_index", {"scope_map": {"user": "u-1", "org": "o-9"}})
    ]


def test_get_memory_index_scope_map_comes_from_grants(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_memory_index builds the scope map from identity.grants, so an
    Identity subclass overriding scope_map cannot redirect it (AIE-1044, US2.3, US2.9).
    """
    lying = _LyingScopeMapIdentity(GRANTS)
    assert lying.scope_map == {"user": "u-evil", "org": "o-evil"}
    h = _make(monkeypatch, lying)

    h.tools.get_memory_index()

    calls = h.client_calls()
    assert len(calls) == 1
    assert _bound(calls[0])["scope_map"] == {"user": "u-1", "org": "o-9"}


def test_get_memory_index_takes_no_parameters() -> None:
    """get_memory_index takes no parameters besides self (AIE-1044, US2.3)."""
    parameters = list(inspect.signature(MemoryTools.get_memory_index).parameters)

    assert parameters == ["self"]


@pytest.mark.parametrize(
    "error",
    [
        NotFoundError("user/u-1/notes/a.md", NotFoundReason.FILE_ABSENT),
        BackendUnavailableError(TransientReason.TIMEOUT),
        MetadataFormatError("description", "bad"),
        _unicode_decode_error(),
    ],
    ids=["not-found", "backend", "metadata", "decode"],
)
def test_read_file_errors_propagate_unchanged(harness: _Harness, error: Exception) -> None:
    """Errors from the client's read_file propagate as the same object
    (AIE-1044, US2.4).
    """
    harness.client.raises["read_file"] = error

    with pytest.raises(type(error)) as excinfo:
        harness.tools.read_file("user", "notes", "a")

    assert excinfo.value is error


@pytest.mark.parametrize("tool", SCOPE_TOOLS)
def test_ungranted_scope_is_invalid_argument(harness: _Harness, tool: str) -> None:
    """An ungranted scope raises InvalidArgumentError("scope") with the exact
    detail, no __cause__, and no client or check_write call (AIE-1044, US2.5,
    US3.3, US4.6).
    """
    err = _invalid(harness, tool, "scope", scope="team")

    assert err.detail == UNGRANTED_DETAIL
    assert err.__cause__ is None
    assert harness.log == []


@pytest.mark.parametrize("tool", SCOPE_TOOLS)
@pytest.mark.parametrize("area", ["", "..", "a/b"], ids=["empty", "dotdot", "slash"])
def test_invalid_area_is_invalid_argument(harness: _Harness, tool: str, area: str) -> None:
    """An invalid area raises InvalidArgumentError("area") chained from the
    path builder's ValueError; no client call (AIE-1044, US2.6, US3.5, US4.6).
    """
    err = _invalid(harness, tool, "area", area=area)

    assert type(err.__cause__) is ValueError
    assert "area" in str(err.__cause__)
    assert harness.spy_calls() == []


@pytest.mark.parametrize("tool", NAME_TOOLS)
@pytest.mark.parametrize("name", ["", "x/y"], ids=["empty", "slash"])
def test_invalid_name_is_invalid_argument(harness: _Harness, tool: str, name: str) -> None:
    """An invalid name raises InvalidArgumentError("name") chained from
    build_path's ValueError; no client call (AIE-1044, US2.6, US3.5, US4.6).
    """
    err = _invalid(harness, tool, "name", name=name)

    assert type(err.__cause__) is ValueError
    assert "name" in str(err.__cause__)
    assert harness.spy_calls() == []


def test_name_ending_in_md_gets_md_appended(harness: _Harness) -> None:
    """A name already ending in .md is not rejected; .md is appended again
    (AIE-1044, US2.7).
    """
    harness.tools.read_file("user", "notes", "a.md")

    assert [(c[0], _bound(c)) for c in harness.log] == [
        ("read_file", {"path": "user/u-1/notes/a.md.md"})
    ]


def _segment_cases(tools: tuple[str, ...], arguments: tuple[str, ...]) -> list[tuple[str, str]]:
    return [(tool, argument) for tool in tools for argument in arguments]


SEGMENT_CASES = [
    *_segment_cases(NAME_TOOLS, ("scope", "area", "name")),
    *_segment_cases(("list_prefix",), ("scope", "area")),
]


@pytest.mark.parametrize(("tool", "argument"), SEGMENT_CASES)
def test_wrong_type_segment_is_invalid_argument(
    harness: _Harness, tool: str, argument: str
) -> None:
    """A scope, area, or name whose real type is not str raises
    InvalidArgumentError naming it with the exact detail, never TypeError
    (AIE-1044, US2.8, US3.10).
    """
    err = _invalid(harness, tool, argument, **{argument: 5})

    assert err.detail == _wrong_type_detail(argument, "int")
    assert err.__cause__ is None
    assert harness.spy_calls() == []


@pytest.mark.parametrize("tool", NAME_TOOLS)
def test_none_area_is_invalid_argument_for_file_tools(harness: _Harness, tool: str) -> None:
    """area=None is a wrong type for file tools (AIE-1044, US2.8, US3.10)."""
    err = _invalid(harness, tool, "area", area=None)

    assert err.detail == _wrong_type_detail("area", "NoneType")


def test_wrong_type_cursor_is_invalid_argument(harness: _Harness) -> None:
    """A non-None non-str cursor raises InvalidArgumentError("cursor")
    (AIE-1044, US2.8, US3.10).
    """
    err = _invalid(harness, "list_prefix", "cursor", cursor=5)

    assert err.detail == _wrong_type_detail("cursor", "int")


def test_unreadable_type_name_reports_unnamed(harness: _Harness) -> None:
    """A wrong-type argument whose type __name__ raises is reported as
    <unnamed> (AIE-1044, US3.10).
    """
    err = _invalid(harness, "read_file", "scope", scope=_UnnamedValue())

    assert err.detail == _wrong_type_detail("scope", "<unnamed>")


@pytest.mark.parametrize("tool", SCOPE_TOOLS)
def test_lying_str_segments_are_normalized(harness: _Harness, tool: str) -> None:
    """str-subclass segments are normalized with str.__str__ before the grant
    lookup and path building; the client gets an exact str path (AIE-1044, US2.8).
    """
    overrides: dict[str, object] = {"scope": _LyingStr("user"), "area": _LyingStr("notes")}
    if tool != "list_prefix":
        overrides["name"] = _LyingStr("a")

    _call(harness, tool, **overrides)

    calls = harness.client_calls()
    assert len(calls) == 1
    if tool == "list_prefix":
        received = calls[0][1][0]
        expected = "user/u-1/notes/"
    else:
        received = _bound(calls[0])["path"]
        expected = "user/u-1/notes/a.md"
    assert type(received) is str
    assert str.__eq__(received, expected) is True


@pytest.mark.parametrize(("tool", "argument"), SEGMENT_CASES)
def test_unencodable_segment_is_invalid_argument(
    harness: _Harness, tool: str, argument: str
) -> None:
    """A scope, area, or name with a lone surrogate raises InvalidArgumentError
    naming it, chained from UnicodeEncodeError (AIE-1044, US2.8, US3.11).
    """
    err = _invalid(harness, tool, argument, **{argument: "x\ud800"})

    assert type(err.__cause__) is UnicodeEncodeError
    assert harness.spy_calls() == []


@pytest.mark.parametrize("tool", ["read_file", "write_file"])
def test_identity_entity_id_override_cannot_redirect(
    monkeypatch: pytest.MonkeyPatch, tool: str
) -> None:
    """The tool reads identity.grants[scope].entity_id, never entity_id(),
    so an overriding Identity subclass cannot redirect paths (AIE-1044, US2.9).
    """
    lying = _LyingIdentity(GRANTS)
    assert lying.entity_id("user") == "u-evil"
    h = _make(monkeypatch, lying)

    _call(h, tool)

    calls = h.client_calls()
    assert len(calls) == 1
    assert _bound(calls[0])["path"] == "user/u-1/notes/a.md"


# --- Area slugs and name characters ------------------------------------------------

BAD_AREA_SLUGS = {
    "uppercase-system": "System",
    "cyrillic-dze": "\u0455ystem",
    "zero-width-space": "sys\u200bstem",
    "dot": "notes.v2",
    "capitalized": "Notes",
    "leading-hyphen": "-leading",
    "leading-underscore": "_leading",
    "cjk": "\u6709",
    "space": "a b",
    "all-caps": "SYSTEM",
    "soft-hyphen": "a\u00adb",
    "short-dot": "a.b",
    "accented": "caf\u00e9",
    "fullwidth": "\uff53ystem",
}

GOOD_AREA_SLUGS = ("notes", "notes-2", "a_b", "9lives", "a", "0", "2026-q4", "x9_y-z")

BAD_NAME_CHARS = {
    "zwsp": "\u200b",
    "zwj": "\u200d",
    "word-joiner": "\u2060",
    "rtl-override": "\u202e",
    "bom": "\ufeff",
    "line-separator": "\u2028",
    "paragraph-separator": "\u2029",
    "noncharacter": "\ufffe",
    "soft-hyphen": "\u00ad",
    "noncharacter-fdd0": "\ufdd0",
    "noncharacter-ffff": "\uffff",
    "noncharacter-plane-1": "\U0001ffff",
}

GOOD_NAMES = {
    "latin-umlaut": "\u00dcbersicht",
    "cjk": "\u65e5\u672c\u8a9e",
    "space": "my notes",
    "capitalized": "Notes",
    "accented": "caf\u00e9",
    "dot": "a.b",
    "cyrillic-dze": "\u0455",
}

AREA_RULE = "must be a lowercase slug: a-z0-9 first, then a-z0-9, '-' or '_'"


@pytest.mark.parametrize("tool", SCOPE_TOOLS)
@pytest.mark.parametrize("area", list(BAD_AREA_SLUGS.values()), ids=list(BAD_AREA_SLUGS))
def test_non_slug_area_is_invalid_argument(harness: _Harness, tool: str, area: str) -> None:
    """An area not matching ^[a-z0-9][a-z0-9_-]*$ raises InvalidArgumentError("area")
    naming the rule, with no __cause__ and no client or check_write call (AIE-1136).
    """
    err = _invalid(harness, tool, "area", area=area)

    assert AREA_RULE in err.detail
    assert err.__cause__ is None
    assert harness.log == []


@pytest.mark.parametrize("tool", SCOPE_TOOLS)
@pytest.mark.parametrize("area", GOOD_AREA_SLUGS)
def test_slug_area_is_accepted(harness: _Harness, tool: str, area: str) -> None:
    """An area matching the slug rule reaches the client in the built path (AIE-1136)."""
    _call(harness, tool, area=area)

    calls = harness.client_calls()
    assert len(calls) == 1
    if tool == "list_prefix":
        assert calls[0][1][0] == f"user/u-1/{area}/"
    else:
        assert _bound(calls[0])["path"] == f"user/u-1/{area}/a.md"


@pytest.mark.parametrize("tool", NAME_TOOLS)
@pytest.mark.parametrize("char", list(BAD_NAME_CHARS.values()), ids=list(BAD_NAME_CHARS))
def test_name_with_invisible_or_separator_char_is_invalid_argument(
    harness: _Harness, tool: str, char: str
) -> None:
    """A name containing a format character, line or paragraph separator, or
    noncharacter raises InvalidArgumentError("name") naming the code point,
    with no __cause__ and no client or check_write call (AIE-1136).
    """
    err = _invalid(harness, tool, "name", name=f"my{char}notes")

    assert "name must not contain" in err.detail
    assert f"U+{ord(char):04X}" in err.detail
    assert err.__cause__ is None
    assert harness.log == []


@pytest.mark.parametrize("tool", NAME_TOOLS)
@pytest.mark.parametrize("name", list(GOOD_NAMES.values()), ids=list(GOOD_NAMES))
def test_unicode_name_is_accepted(harness: _Harness, tool: str, name: str) -> None:
    """A name with letters in any script or ordinary spaces reaches the client
    as <name>.md (AIE-1136).
    """
    _call(harness, tool, name=name)

    calls = harness.client_calls()
    assert len(calls) == 1
    path = cast(str, _bound(calls[0])["path"])
    assert path == f"user/u-1/notes/{name}.md"


@pytest.mark.parametrize("tool", SCOPE_TOOLS)
def test_grant_check_precedes_area_slug_check(harness: _Harness, tool: str) -> None:
    """An ungranted scope is reported before a non-slug area (AIE-1136)."""
    err = _invalid(harness, tool, "scope", scope="team", area="System")

    assert err.detail == UNGRANTED_DETAIL
    assert harness.log == []


@pytest.mark.parametrize("tool", MUTATING_TOOLS)
def test_area_slug_check_precedes_check_write(harness: _Harness, tool: str) -> None:
    """A non-slug area in a scope the caller may not write is reported as
    InvalidArgumentError("area"), not a role error, and check_write never
    runs (AIE-1136).
    """
    err = _invalid(harness, tool, "area", scope="org", area="System")

    assert AREA_RULE in err.detail
    assert harness.log == []


@pytest.mark.parametrize("tool", NAME_TOOLS)
def test_area_slug_check_precedes_name_check(harness: _Harness, tool: str) -> None:
    """A non-slug area and a core-valid name with a zero-width space report
    the area (AIE-1136, US3.2).
    """
    err = _invalid(harness, tool, "area", area="System", name="my\u200bnotes")

    assert AREA_RULE in err.detail
    assert harness.log == []


# --- US3: checked writes ----------------------------------------------------------


@pytest.mark.parametrize("tool", MUTATING_TOOLS)
def test_mutating_tool_checks_then_forwards_same_path_object(harness: _Harness, tool: str) -> None:
    """check_write runs exactly once before the client call, on the same path
    object the client receives (AIE-1044, US3.0).
    """
    _call(harness, tool)

    assert [call[0] for call in harness.log] == ["check_write", tool]
    spy_path, spy_identity, spy_policy = harness.log[0][1]
    assert spy_path == "user/u-1/notes/a.md"
    assert spy_path is _bound(harness.log[1])["path"]
    assert spy_identity is IDENTITY
    assert spy_policy is POLICY


@pytest.mark.parametrize("tool", MUTATING_TOOLS)
def test_segment_checks_precede_grant_check(harness: _Harness, tool: str) -> None:
    """Segment type and encodability checks run before the grant check
    (AIE-1044, US3.0).
    """
    _invalid(harness, tool, "area", scope="team", area=5)
    _invalid(harness, tool, "name", scope="team", name="x\ud800")

    assert harness.log == []


@pytest.mark.parametrize("tool", SCOPE_TOOLS)
def test_grant_check_precedes_path_building(harness: _Harness, tool: str) -> None:
    """An ungranted scope is reported before an invalid area, for every
    scope-taking tool (AIE-1044, US2.5, US3.0).
    """
    _invalid(harness, tool, "scope", scope="team", area="a/b")

    assert harness.log == []


@pytest.mark.parametrize("tool", MUTATING_TOOLS)
def test_path_building_precedes_check_write(harness: _Harness, tool: str) -> None:
    """An invalid area in a role-gated scope is InvalidArgumentError, and
    check_write never runs (AIE-1044, US3.0).
    """
    _invalid(harness, tool, "area", scope="org", area="a/b")

    assert harness.log == []


BAD_EXTRA_ARGUMENT = {
    "write_file": {"content": 5},
    "append_line": {"line": 5},
    "replace_fact": {"old_string": 5},
    "delete_file": {"expected_version": 5},
}


@pytest.mark.parametrize("tool", MUTATING_TOOLS)
def test_check_write_precedes_argument_validation(harness: _Harness, tool: str) -> None:
    """Writing system/ with a wrongly typed argument raises RestrictedScopeError,
    because check_write runs before argument validation (AIE-1044, US3.0).
    """
    with pytest.raises(RestrictedScopeError):
        _call(harness, tool, area="system", **BAD_EXTRA_ARGUMENT[tool])

    assert [call[0] for call in harness.log] == ["check_write"]


@pytest.mark.parametrize("tool", MUTATING_TOOLS)
def test_mutating_tool_forwards_exact_call(harness: _Harness, tool: str) -> None:
    """Each mutating tool forwards one call with the built path, its
    arguments, and source, and returns the client's result (AIE-1044, US3.1).
    """
    preset = None if tool == "delete_file" else _file()
    harness.client.returns[tool] = preset

    result = _call(harness, tool)

    assert result is preset
    calls = harness.client_calls()
    assert [call[0] for call in calls] == [tool]
    assert _bound(calls[0]) == _expected(tool, "user/u-1/notes/a.md", _base(tool))


def test_write_file_metadata_uses_placeholder_and_tuple_aliases(harness: _Harness) -> None:
    """write_file builds FileMetadata(description, tuple(aliases), frozenset(),
    1970-01-01 UTC) (AIE-1044, US3.1, US3.7).
    """
    harness.tools.write_file("user", "notes", "a", CONTENT, DESCRIPTION, ["x", "y"], VERSION)

    metadata = cast(FileMetadata, _bound(harness.client_calls()[0])["metadata"])
    assert metadata == FileMetadata(DESCRIPTION, ("x", "y"), frozenset(), EPOCH)
    assert type(metadata.aliases) is tuple
    assert metadata.last_updated == EPOCH


@pytest.mark.parametrize("tool", MUTATING_TOOLS)
def test_system_area_is_read_only(harness: _Harness, tool: str) -> None:
    """Every mutating tool rejects system/ with SYSTEM_READ_ONLY and the built
    path; no client call (AIE-1044, US3.2).
    """
    with pytest.raises(RestrictedScopeError) as excinfo:
        _call(harness, tool, area="system", name="x")

    assert excinfo.value.reason is RestrictionReason.SYSTEM_READ_ONLY
    assert excinfo.value.path == "user/u-1/system/x.md"
    assert harness.client_calls() == []


@pytest.mark.parametrize("tool", MUTATING_TOOLS)
def test_member_cannot_write_role_gated_scope(harness: _Harness, tool: str) -> None:
    """A member writing the role-gated org scope gets ROLE_REQUIRED with the
    built path and permitted roles; no client call (AIE-1044, US3.4).
    """
    with pytest.raises(RestrictedScopeError) as excinfo:
        _call(harness, tool, scope="org")

    assert excinfo.value.reason is RestrictionReason.ROLE_REQUIRED
    assert excinfo.value.path == "org/o-9/notes/a.md"
    assert excinfo.value.required_roles == ORG_ROLES
    assert harness.client_calls() == []


@pytest.mark.parametrize("tool", MUTATING_TOOLS)
def test_owner_can_write_role_gated_scope(monkeypatch: pytest.MonkeyPatch, tool: str) -> None:
    """An owner's write to the role-gated org scope is forwarded (AIE-1044, US3.4)."""
    h = _make(monkeypatch, OWNER_IDENTITY)

    _call(h, tool, scope="org")

    calls = h.client_calls()
    assert [call[0] for call in calls] == [tool]
    assert _bound(calls[0]) == _expected(tool, "org/o-9/notes/a.md", _base(tool))


CLIENT_ERRORS: list[Exception] = [
    VersionConflictError("user/u-1/notes/a.md", CONTENT, VersionToken("v2")),
    OversizeWriteError("user/u-1/notes/a.md", 10, 5),
    ReplaceFactMatchError("user/u-1/notes/a.md", CONTENT, VersionToken("v2"), 0),
    NotFoundError("user/u-1/notes/a.md", NotFoundReason.FILE_ABSENT),
]


@pytest.mark.parametrize("tool", MUTATING_TOOLS)
@pytest.mark.parametrize("error", CLIENT_ERRORS, ids=["conflict", "oversize", "match", "not-found"])
def test_client_errors_propagate_from_mutating_tools(
    harness: _Harness, tool: str, error: Exception
) -> None:
    """Taxonomy errors from the client propagate as the same object (AIE-1044, US3.6)."""
    harness.client.raises[tool] = error

    with pytest.raises(type(error)) as excinfo:
        _call(harness, tool)

    assert excinfo.value is error


def test_write_file_none_version_creates(harness: _Harness) -> None:
    """write_file with expected_version=None forwards None (AIE-1044, US3.7)."""
    harness.tools.write_file("user", "notes", "a", CONTENT, DESCRIPTION, ("tea",), None)

    assert _bound(harness.client_calls()[0])["expected_version"] is None


@pytest.mark.parametrize("description", ["a\nb", "a\rb"], ids=["newline", "carriage-return"])
def test_description_with_newline_is_invalid_argument(harness: _Harness, description: str) -> None:
    """A description with a newline raises InvalidArgumentError("description")
    chained from FileMetadata's ValueError (AIE-1044, US3.8).
    """
    err = _invalid(harness, "write_file", "description", description=description)

    assert type(err.__cause__) is ValueError


def test_unencodable_description_is_invalid_argument(harness: _Harness) -> None:
    """A description with a lone surrogate raises InvalidArgumentError
    chained from UnicodeEncodeError (AIE-1044, US3.8, US3.11).
    """
    err = _invalid(harness, "write_file", "description", description="x\ud800")

    assert type(err.__cause__) is UnicodeEncodeError


def test_bad_description_in_system_area_is_restricted(harness: _Harness) -> None:
    """check_write precedes metadata construction (AIE-1044, US3.8)."""
    with pytest.raises(RestrictedScopeError):
        _call(harness, "write_file", area="system", description="a\nb")

    assert harness.client_calls() == []


@pytest.mark.parametrize(
    "separator",
    ["\u2028", "\u2029", "\x85", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e"],
    ids=["ls", "ps", "nel", "vt", "ff", "fs", "gs", "rs"],
)
def test_description_with_line_boundary_is_invalid_argument(
    harness: _Harness, separator: str
) -> None:
    """A description containing any str.splitlines boundary is not one line
    and raises InvalidArgumentError("description") (AIE-1044, US3.8).
    """
    _invalid(harness, "write_file", "description", description=f"a{separator}b")


def test_str_subclass_description_is_normalized(harness: _Harness) -> None:
    """A str-subclass description is stored as an exact str (AIE-1044, US3.8)."""
    _call(harness, "write_file", description=_LyingStr("Tea"))

    metadata = cast(FileMetadata, _bound(harness.client_calls()[0])["metadata"])
    assert type(metadata.description) is str
    assert str.__eq__(metadata.description, "Tea") is True


@pytest.mark.parametrize(
    "aliases",
    ["ab", b"ab", bytearray(b"ab"), 5, iter(["a"]), frozenset({"a"}), ["a", 5], ("a", None)],
    ids=["str", "bytes", "bytearray", "int", "iterator", "set", "int-member", "none-member"],
)
def test_malformed_aliases_are_invalid_argument(harness: _Harness, aliases: object) -> None:
    """A bare str/bytes, a non-Sequence, or a non-str member raises
    InvalidArgumentError("aliases"), never TypeError (AIE-1044, US3.9, US3.10).
    """
    _invalid(harness, "write_file", "aliases", aliases=aliases)


def test_non_str_alias_member_detail(harness: _Harness) -> None:
    """A non-str aliases member gets the wrong-type detail naming aliases
    (AIE-1044, US3.9, US3.10).
    """
    err = _invalid(harness, "write_file", "aliases", aliases=["a", 5])

    assert err.detail == _wrong_type_detail("aliases", "int")
    assert err.__cause__ is None


def test_unencodable_alias_member_is_invalid_argument(harness: _Harness) -> None:
    """An alias member with a lone surrogate raises InvalidArgumentError("aliases")
    chained from UnicodeEncodeError (AIE-1044, US3.9, US3.11).
    """
    err = _invalid(harness, "write_file", "aliases", aliases=["ok", "x\ud800"])

    assert type(err.__cause__) is UnicodeEncodeError


def test_class_spoofing_aliases_is_invalid_argument(harness: _Harness) -> None:
    """aliases whose __class__ claims list but whose real type is not a Sequence
    raises InvalidArgumentError("aliases"), never TypeError (AIE-1044, US3.9, US3.10).
    """
    _invalid(harness, "write_file", "aliases", aliases=_ListSpoof())


def test_str_subclass_alias_members_are_normalized(harness: _Harness) -> None:
    """str-subclass alias members are stored as exact str (AIE-1044, US3.9)."""
    _call(harness, "write_file", aliases=[_LyingStr("x"), "y"])

    metadata = cast(FileMetadata, _bound(harness.client_calls()[0])["metadata"])
    assert [type(alias) for alias in metadata.aliases] == [str, str]
    assert [str.__str__(alias) for alias in metadata.aliases] == ["x", "y"]


WRONG_TYPE_CASES: list[tuple[str, str, object, str]] = [
    ("write_file", "content", 5, "int"),
    ("write_file", "description", 5, "int"),
    ("write_file", "expected_version", 5, "int"),
    ("append_line", "line", 5, "int"),
    ("append_line", "expected_version", 5, "int"),
    ("append_line", "expected_version", None, "NoneType"),
    ("replace_fact", "old_string", 5, "int"),
    ("replace_fact", "new_string", 5, "int"),
    ("replace_fact", "expected_version", 5, "int"),
    ("replace_fact", "expected_version", None, "NoneType"),
    ("delete_file", "expected_version", 5, "int"),
    ("delete_file", "expected_version", None, "NoneType"),
]


@pytest.mark.parametrize(("tool", "argument", "value", "type_name"), WRONG_TYPE_CASES)
def test_wrong_type_argument_is_invalid_argument(
    harness: _Harness, tool: str, argument: str, value: object, type_name: str
) -> None:
    """A wrongly typed agent argument raises InvalidArgumentError naming it,
    with the exact detail and no __cause__, never TypeError (AIE-1044, US3.10).
    """
    err = _invalid(harness, tool, argument, **{argument: value})

    assert err.detail == _wrong_type_detail(argument, type_name)
    assert err.__cause__ is None


def test_wrong_type_content_detail_sentence(harness: _Harness) -> None:
    """content=5 yields the documented detail sentence (AIE-1044, US3.10)."""
    err = _invalid(harness, "write_file", "content", content=5)

    assert err.detail == "Argument content is invalid: content must be a string, not int"


STR_ARGUMENTS: list[tuple[str, str]] = [
    ("write_file", "content"),
    ("write_file", "expected_version"),
    ("append_line", "line"),
    ("append_line", "expected_version"),
    ("replace_fact", "old_string"),
    ("replace_fact", "new_string"),
    ("replace_fact", "expected_version"),
    ("delete_file", "expected_version"),
]


@pytest.mark.parametrize(("tool", "argument"), STR_ARGUMENTS)
def test_str_subclass_arguments_are_forwarded_as_exact_str(
    harness: _Harness, tool: str, argument: str
) -> None:
    """str-subclass arguments are normalized with str.__str__ before the
    client call (AIE-1044, US3.10).
    """
    original = cast(str, _base(tool)[argument])
    _call(harness, tool, **{argument: _LyingStr(original)})

    received = _bound(harness.client_calls()[0])[argument]
    assert type(received) is str
    assert str.__eq__(received, original) is True


def test_str_subclass_cursor_is_forwarded_as_exact_str(harness: _Harness) -> None:
    """A str-subclass cursor is normalized before the client call (AIE-1044, US3.10)."""
    harness.tools.list_prefix("user", "notes", ListCursor(_LyingStr("abc")))

    received = harness.client_calls()[0][1][1]
    assert type(received) is str
    assert str.__eq__(received, "abc") is True


UNENCODABLE_CASES: list[tuple[str, str]] = [
    ("write_file", "content"),
    ("append_line", "line"),
    ("replace_fact", "new_string"),
]


@pytest.mark.parametrize(("tool", "argument"), UNENCODABLE_CASES)
def test_unencodable_text_is_invalid_argument(harness: _Harness, tool: str, argument: str) -> None:
    """content, line, or new_string with a lone surrogate raises
    InvalidArgumentError naming it, chained from UnicodeEncodeError
    (AIE-1044, US3.11).
    """
    err = _invalid(harness, tool, argument, **{argument: "- [stated] x\ud800"})

    assert type(err.__cause__) is UnicodeEncodeError


# --- US4: agent-argument errors ---------------------------------------------------


def test_list_prefix_value_error_becomes_cursor_argument(harness: _Harness) -> None:
    """A client ValueError from list_prefix becomes a recoverable
    InvalidArgumentError("cursor") chained from it (AIE-1044, US4.1).
    """
    original = ValueError("Malformed list cursor: 'x'")
    harness.client.raises["list_prefix"] = original

    with pytest.raises(InvalidArgumentError) as excinfo:
        harness.tools.list_prefix("user", None, ListCursor("x"))

    err = excinfo.value
    assert err.argument == "cursor"
    assert "Malformed list cursor: 'x'" in err.detail
    assert err.category is ErrorCategory.RECOVERABLE
    assert err.__cause__ is original


def test_list_prefix_unreadable_value_error_becomes_cursor_argument(harness: _Harness) -> None:
    """A cursor-call ValueError whose message cannot be read still becomes
    InvalidArgumentError("cursor") with <unreadable> in the detail (AIE-1044, US4.1).
    """
    original = _UnreadableValueError()
    harness.client.raises["list_prefix"] = original

    with pytest.raises(InvalidArgumentError) as excinfo:
        harness.tools.list_prefix("user", None, ListCursor("x"))

    assert excinfo.value.argument == "cursor"
    assert "<unreadable>" in excinfo.value.detail
    assert excinfo.value.__cause__ is original


def test_list_prefix_value_error_without_cursor_propagates(harness: _Harness) -> None:
    """A client ValueError from list_prefix called without a cursor is not the
    agent's cursor and propagates unchanged (AIE-1044, US4.1, US4.5).
    """
    error = ValueError("unexpected")
    harness.client.raises["list_prefix"] = error

    with pytest.raises(ValueError) as excinfo:
        harness.tools.list_prefix("user", "notes")

    assert excinfo.value is error


@pytest.mark.parametrize("tool", ["append_line", "replace_fact"])
def test_client_value_error_for_valid_argument_propagates(harness: _Harness, tool: str) -> None:
    """A client ValueError for a valid fact line or non-empty old_string is not
    an argument error and propagates unchanged (AIE-1044, US4.2, US4.5).
    """
    error = ValueError("last_updated must be timezone-aware")
    harness.client.raises[tool] = error

    with pytest.raises(ValueError) as excinfo:
        _call(harness, tool)

    assert excinfo.value is error
    assert type(excinfo.value) is ValueError


@pytest.mark.parametrize(
    "line",
    ["not a fact", "- [guess] x", "- [stated] ", "- [stated] a\nb", ""],
    ids=["plain", "bad-label", "empty-text", "two-lines", "empty"],
)
def test_non_fact_line_is_rejected_before_client_call(harness: _Harness, line: str) -> None:
    """A line that parse_fact rejects raises InvalidArgumentError("line") from
    the tool's own check, with no client call (AIE-1044, US4.2).
    """
    err = _invalid(harness, "append_line", "line", line=line)

    assert err.category is ErrorCategory.RECOVERABLE


def test_empty_old_string_is_rejected_before_client_call(harness: _Harness) -> None:
    """An empty old_string raises InvalidArgumentError("old_string") from the
    tool's own check, with no client call (AIE-1044, US4.2).
    """
    err = _invalid(harness, "replace_fact", "old_string", old_string="")

    assert err.category is ErrorCategory.RECOVERABLE


@pytest.mark.parametrize("tool", ALL_TOOLS)
@pytest.mark.parametrize(
    "make_error",
    [lambda: MetadataFormatError("aliases", "bad"), _unicode_decode_error],
    ids=["metadata", "decode"],
)
def test_data_integrity_errors_pass_through(
    harness: _Harness, tool: str, make_error: Callable[[], ValueError]
) -> None:
    """MetadataFormatError and UnicodeDecodeError propagate unconverted from
    every tool (AIE-1044, US4.3).
    """
    error = make_error()
    harness.client.raises[tool] = error

    with pytest.raises(ValueError) as excinfo:
        _call(harness, tool)

    assert excinfo.value is error


@pytest.mark.parametrize("tool", ["read_file", "delete_file", "write_file", "get_memory_index"])
def test_unconverted_value_error_propagates(harness: _Harness, tool: str) -> None:
    """A plain ValueError from read_file, delete_file, write_file, or
    get_memory_index propagates unchanged (AIE-1044, US4.5).
    """
    error = ValueError("unexpected")
    harness.client.raises[tool] = error

    with pytest.raises(ValueError) as excinfo:
        _call(harness, tool)

    assert excinfo.value is error
    assert type(excinfo.value) is ValueError


# --- Aliases and description on append_line and replace_fact ----------------------

FACT_TOOLS = ("append_line", "replace_fact")
PATH = "user/u-1/notes/a.md"

FACT_TOOL_PARAMETERS: dict[str, list[tuple[str, object]]] = {
    "append_line": [
        ("self", inspect.Parameter.empty),
        ("scope", inspect.Parameter.empty),
        ("area", inspect.Parameter.empty),
        ("name", inspect.Parameter.empty),
        ("line", inspect.Parameter.empty),
        ("expected_version", inspect.Parameter.empty),
        ("aliases", None),
        ("description", None),
    ],
    "replace_fact": [
        ("self", inspect.Parameter.empty),
        ("scope", inspect.Parameter.empty),
        ("area", inspect.Parameter.empty),
        ("name", inspect.Parameter.empty),
        ("old_string", inspect.Parameter.empty),
        ("new_string", inspect.Parameter.empty),
        ("expected_version", inspect.Parameter.empty),
        ("aliases", None),
        ("description", None),
    ],
}

FACT_POSITIONAL: dict[str, tuple[object, ...]] = {
    "append_line": (PATH, LINE, VERSION),
    "replace_fact": (PATH, OLD, NEW, VERSION),
}

MALFORMED_ALIASES: dict[str, Callable[[], object]] = {
    "str": lambda: "ab",
    "bytes": lambda: b"ab",
    "bytearray": lambda: bytearray(b"ab"),
    "int": lambda: 5,
    "iterator": lambda: iter(["a"]),
    "set": lambda: frozenset({"a"}),
    "int-member": lambda: ["a", 5],
    "none-member": lambda: ("a", None),
    "class-spoof": _ListSpoof,
    "unencodable-member": lambda: ["ok", "x\ud800"],
}

LINE_BOUNDARIES = {
    "vt": "\x0b",
    "ff": "\x0c",
    "fs": "\x1c",
    "gs": "\x1d",
    "rs": "\x1e",
    "nel": "\x85",
    "ls": chr(0x2028),
    "ps": chr(0x2029),
}


def _only_client_call(h: _Harness) -> _Call:
    calls = h.client_calls()
    assert len(calls) == 1
    return calls[0]


@pytest.mark.parametrize("tool", FACT_TOOLS)
def test_fact_tool_signature_has_optional_aliases_and_description(tool: str) -> None:
    """append_line and replace_fact take aliases and description last, as
    positional-or-keyword parameters defaulting to None (AIE-1151, US4.14).
    """
    parameters = inspect.signature(getattr(MemoryTools, tool)).parameters.values()

    assert [(p.name, p.default) for p in parameters] == FACT_TOOL_PARAMETERS[tool]
    assert {p.kind for p in parameters} == {inspect.Parameter.POSITIONAL_OR_KEYWORD}


@pytest.mark.parametrize("tool", FACT_TOOLS)
def test_fact_tool_forwards_aliases_tuple_and_description_as_keywords(
    harness: _Harness, tool: str
) -> None:
    """The client gets the path and the tool's arguments positionally and
    source, aliases as an exact tuple, and description as keywords; the tool
    returns the client's object (AIE-1151, US4.1, US4.3).
    """
    preset = _file()
    harness.client.returns[tool] = preset

    result = _call(harness, tool, aliases=["x", "y"], description="d")

    assert result is preset
    name, args, kwargs = _only_client_call(harness)
    assert name == tool
    assert args == FACT_POSITIONAL[tool]
    assert kwargs == {"source": SOURCE, "aliases": ("x", "y"), "description": "d"}
    assert type(kwargs["aliases"]) is tuple
    assert type(kwargs["description"]) is str


@pytest.mark.parametrize("tool", FACT_TOOLS)
def test_fact_tool_accepts_aliases_and_description_positionally(
    harness: _Harness, tool: str
) -> None:
    """aliases and description may be passed positionally after
    expected_version (AIE-1151, US4.1, US4.3, US4.14).
    """
    positional = [_base(tool)[p] for p, _ in FACT_TOOL_PARAMETERS[tool][1:-2]]
    method: Callable[..., object] = getattr(harness.tools, tool)

    method(*positional, ("x",), "d")

    _, _, kwargs = _only_client_call(harness)
    assert kwargs == {"source": SOURCE, "aliases": ("x",), "description": "d"}


@pytest.mark.parametrize("tool", FACT_TOOLS)
@pytest.mark.parametrize("explicit", [False, True], ids=["omitted", "explicit-none"])
def test_fact_tool_forwards_none_when_metadata_not_given(
    harness: _Harness, tool: str, explicit: bool
) -> None:
    """Omitted or explicit-None aliases and description reach the client as
    explicit aliases=None, description=None keywords (AIE-1151, US4.2, US4.3).
    """
    overrides: dict[str, object] = {"aliases": None, "description": None} if explicit else {}

    _call(harness, tool, **overrides)

    _, args, kwargs = _only_client_call(harness)
    assert args == FACT_POSITIONAL[tool]
    assert kwargs == {"source": SOURCE, "aliases": None, "description": None}


@pytest.mark.parametrize("tool", FACT_TOOLS)
def test_fact_tool_forwards_empty_aliases_as_empty_tuple(harness: _Harness, tool: str) -> None:
    """An empty aliases list is forwarded as the exact empty tuple
    (AIE-1151, US4.1).
    """
    _call(harness, tool, aliases=[])

    _, _, kwargs = _only_client_call(harness)
    assert type(kwargs["aliases"]) is tuple
    assert kwargs["aliases"] == ()


@pytest.mark.parametrize("tool", FACT_TOOLS)
@pytest.mark.parametrize("make", list(MALFORMED_ALIASES.values()), ids=list(MALFORMED_ALIASES))
def test_fact_tool_malformed_aliases_match_write_file(
    harness: _Harness, tool: str, make: Callable[[], object]
) -> None:
    """Malformed aliases raise InvalidArgumentError("aliases") with exactly
    the detail and cause type write_file gives for the same value; no client
    call (AIE-1151, US4.4, US4.5).
    """
    reference = _invalid(harness, "write_file", "aliases", aliases=make())

    err = _invalid(harness, tool, "aliases", aliases=make())

    assert err.detail == reference.detail
    assert type(err.__cause__) is type(reference.__cause__)


@pytest.mark.parametrize("tool", FACT_TOOLS)
@pytest.mark.parametrize(
    ("make", "detail"),
    [
        (lambda: "ab", "aliases must be a list of strings, not str"),
        (lambda: 5, "aliases must be a list of strings, not int"),
        (_ListSpoof, "aliases must be a list of strings, not _ListSpoof"),
        (lambda: ["a", 5], "aliases must be a string, not int"),
    ],
    ids=["str", "int", "class-spoof", "int-member"],
)
def test_fact_tool_wrong_type_aliases_detail(
    harness: _Harness, tool: str, make: Callable[[], object], detail: str
) -> None:
    """Wrongly typed aliases yield write_file's documented detail with no
    cause (AIE-1151, US4.4).
    """
    reference = _invalid(harness, "write_file", "aliases", aliases=make())
    assert reference.detail == f"Argument aliases is invalid: {detail}"

    err = _invalid(harness, tool, "aliases", aliases=make())

    assert err.detail == reference.detail
    assert err.__cause__ is None


@pytest.mark.parametrize("tool", FACT_TOOLS)
def test_fact_tool_unencodable_alias_is_chained(harness: _Harness, tool: str) -> None:
    """An alias member with a lone surrogate raises InvalidArgumentError("aliases")
    chained from UnicodeEncodeError (AIE-1151, US4.5).
    """
    reference = _invalid(harness, "write_file", "aliases", aliases=["ok", "x\ud800"])
    assert reference.detail == "Argument aliases is invalid: aliases is not valid UTF-8 text"

    err = _invalid(harness, tool, "aliases", aliases=["ok", "x\ud800"])

    assert type(err.__cause__) is UnicodeEncodeError
    assert err.detail == reference.detail


@pytest.mark.parametrize("tool", FACT_TOOLS)
def test_fact_tool_wrong_type_description(harness: _Harness, tool: str) -> None:
    """description=5 raises InvalidArgumentError("description") with the
    wrong-type detail and no cause (AIE-1151, US4.6).
    """
    reference = _invalid(harness, "write_file", "description", description=5)
    assert reference.detail == (
        "Argument description is invalid: description must be a string, not int"
    )

    err = _invalid(harness, tool, "description", description=5)

    assert err.detail == reference.detail
    assert err.__cause__ is None


@pytest.mark.parametrize("tool", FACT_TOOLS)
@pytest.mark.parametrize("description", ["a\nb", "a\rb"], ids=["newline", "carriage-return"])
def test_fact_tool_description_with_newline(harness: _Harness, tool: str, description: str) -> None:
    """A description with \\n or \\r raises InvalidArgumentError("description")
    chained from ValueError, with write_file's detail (AIE-1151, US4.7).
    """
    reference = _invalid(harness, "write_file", "description", description=description)
    assert reference.detail == (
        "Argument description is invalid: description must not contain a newline or carriage return"
    )

    err = _invalid(harness, tool, "description", description=description)

    assert type(err.__cause__) is ValueError
    assert err.detail == reference.detail


@pytest.mark.parametrize("tool", FACT_TOOLS)
@pytest.mark.parametrize("boundary", list(LINE_BOUNDARIES.values()), ids=list(LINE_BOUNDARIES))
def test_fact_tool_description_with_line_boundary(
    harness: _Harness, tool: str, boundary: str
) -> None:
    """A description containing a line-boundary character raises
    InvalidArgumentError("description") with write_file's single-line detail
    (AIE-1151, US4.8).
    """
    reference = _invalid(harness, "write_file", "description", description=f"a{boundary}b")
    assert reference.detail == "Argument description is invalid: description must be a single line"

    err = _invalid(harness, tool, "description", description=f"a{boundary}b")

    assert err.detail == reference.detail
    assert err.__cause__ is None


@pytest.mark.parametrize("tool", FACT_TOOLS)
def test_fact_tool_unencodable_description_is_chained(harness: _Harness, tool: str) -> None:
    """A description with a lone surrogate raises InvalidArgumentError("description")
    chained from UnicodeEncodeError (AIE-1151, US4.9).
    """
    reference = _invalid(harness, "write_file", "description", description="x\ud800")
    assert reference.detail == (
        "Argument description is invalid: description is not valid UTF-8 text"
    )

    err = _invalid(harness, tool, "description", description="x\ud800")

    assert type(err.__cause__) is UnicodeEncodeError
    assert err.detail == reference.detail


@pytest.mark.parametrize("tool", FACT_TOOLS)
def test_fact_tool_str_subclass_metadata_is_forwarded_as_exact_str(
    harness: _Harness, tool: str
) -> None:
    """str-subclass description and alias members are forwarded as exact str
    (AIE-1151, US4.10).
    """
    _call(harness, tool, aliases=[_LyingStr("x"), "y"], description=_LyingStr("d"))

    _, _, kwargs = _only_client_call(harness)
    aliases = cast(tuple[str, ...], kwargs["aliases"])
    description = kwargs["description"]
    assert type(aliases) is tuple
    assert [type(alias) for alias in aliases] == [str, str]
    assert [str.__str__(alias) for alias in aliases] == ["x", "y"]
    assert type(description) is str
    assert str.__eq__(description, "d") is True


@pytest.mark.parametrize("tool", FACT_TOOLS)
@pytest.mark.parametrize(
    "overrides",
    [{"aliases": "ab"}, {"aliases": ["a", 5]}, {"description": 5}, {"description": "a\nb"}],
    ids=["str-aliases", "int-alias", "int-description", "newline-description"],
)
def test_fact_tool_check_write_precedes_metadata_checks(
    harness: _Harness, tool: str, overrides: dict[str, object]
) -> None:
    """Writing system/ with bad aliases or description raises
    RestrictedScopeError; only check_write runs (AIE-1151, US4.11).
    """
    with pytest.raises(RestrictedScopeError):
        _call(harness, tool, area="system", **overrides)

    assert [call[0] for call in harness.log] == ["check_write"]


PRECEDENCE_CASES: list[tuple[str, str, object]] = [
    ("append_line", "line", 5),
    ("append_line", "line", "not a fact"),
    ("append_line", "line", "- [stated] x\ud800"),
    ("append_line", "expected_version", 5),
    ("append_line", "expected_version", None),
    ("replace_fact", "old_string", 5),
    ("replace_fact", "old_string", ""),
    ("replace_fact", "new_string", 5),
    ("replace_fact", "new_string", "x\ud800"),
    ("replace_fact", "expected_version", 5),
    ("replace_fact", "expected_version", None),
]


@pytest.mark.parametrize(("tool", "argument", "value"), PRECEDENCE_CASES)
def test_earlier_argument_error_precedes_metadata_errors(
    harness: _Harness, tool: str, argument: str, value: object
) -> None:
    """A bad line, old_string, new_string, or expected_version is reported
    before bad aliases and description (AIE-1151, US4.12).
    """
    _invalid(harness, tool, argument, **{argument: value, "aliases": "ab", "description": 5})

    assert [call[0] for call in harness.log] == ["check_write"]


@pytest.mark.parametrize("tool", FACT_TOOLS)
def test_aliases_error_precedes_description_error(harness: _Harness, tool: str) -> None:
    """Bad aliases are reported before a bad description, in signature order
    (AIE-1151, US4.12).
    """
    _invalid(harness, tool, "aliases", aliases=["a", 5], description="a\nb")


@pytest.mark.parametrize(
    "overrides",
    [{"aliases": "ab"}, {"expected_version": 5}],
    ids=["before-aliases", "before-expected-version"],
)
def test_write_file_description_error_precedes_later_arguments(
    harness: _Harness, overrides: dict[str, object]
) -> None:
    """write_file reports a multi-line description before bad aliases or
    expected_version (AIE-1151, US4.13; ADR 0024).
    """
    err = _invalid(harness, "write_file", "description", description="a\nb", **overrides)

    assert type(err.__cause__) is ValueError


# --- US6: module boundaries -------------------------------------------------------


def _matches_root(module: str, root: str) -> bool:
    return module == root or module.startswith(root + ".")


def _imported_modules(tree: ast.AST) -> list[str]:
    """Absolute module names of every import; relative ones resolve against wenchang."""
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


def test_tools_module_imports_are_restricted() -> None:
    """tools.py imports only the allowed wenchang modules, nothing from
    storage or google, all at module level (AIE-1044, US6.1).
    """
    tree = ast.parse(TOOLS_MODULE.read_text(), filename=str(TOOLS_MODULE))
    modules = _imported_modules(tree)

    disallowed = [
        m for m in modules if _matches_root(m, "wenchang") and m not in ALLOWED_WENCHANG_IMPORTS
    ]
    forbidden = [m for m in modules if _matches_root(m, "google")]
    top_level = {id(node) for node in tree.body}
    nested = [
        f"line {node.lineno}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom) and id(node) not in top_level
    ]

    assert disallowed == []
    assert forbidden == []
    assert nested == [], "every import must be a top-level module statement"


@pytest.mark.parametrize("module", ["core", "scope", "identity", "transport"])
def test_lower_layers_do_not_import_tools(module: str) -> None:
    """core, scope, identity, and transport never import wenchang.tools
    (AIE-1044, US6.2).
    """
    path = PACKAGE_DIR / f"{module}.py"
    tree = ast.parse(path.read_text(), filename=str(path))

    assert [m for m in _imported_modules(tree) if _matches_root(m, "wenchang.tools")] == []


def test_runtime_dependencies_are_unchanged() -> None:
    """pyproject.toml's runtime dependencies are exactly google-cloud-storage
    (AIE-1044, US6.3).
    """
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())

    assert pyproject["project"]["dependencies"] == ["google-cloud-storage>=2.18"]
