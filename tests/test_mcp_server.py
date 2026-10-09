"""Smoke tests for the MCP host adapter, driven by a real MCP client (AIE-1060).

Covers US3 (registration and startup checks), US4 (prompt delivery), US5
(per-call binding and forwarding), US6.4 and US6.5 (concurrent calls), and US7
(the on_call observer). Each async body runs with anyio.run; the client talks
to the server over mcp's in-memory transport.
"""

import inspect
import json
import logging
import subprocess
import sys
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import FrozenInstanceError, fields, is_dataclass
from pathlib import Path
from typing import Any, cast

import anyio
import pytest
from mcp.client import Client
from mcp.server.mcpserver import Context, MCPServer
from mcp.types import CallToolResult, TextContent

import wenchang.mcp as wmcp
from prompts_reference_adopter import REFERENCE_SLOTS
from wenchang.core import MemoryStore
from wenchang.identity import Identity, ResolutionFailure, ScopeGrant
from wenchang.mcp import (
    PROMPT_RESOURCE_URI,
    ToolCallRecord,
    build_server,
    memory_instructions,
    register_memory_tools,
)
from wenchang.prompts import build_memory_prompt
from wenchang.scope import ScopePolicy
from wenchang.storage.memory import InMemoryStorage
from wenchang.tools import (
    TOOL_NAMES,
    MemoryTools,
    bind_tools,
    render_error,
    render_result,
    tool_descriptions,
)
from wenchang.transport import InProcessClient

pytestmark = pytest.mark.unit

TESTS_DIR = Path(__file__).resolve().parent
TIMEOUT = 60
META_KEY = "test/user"
TOOL_PREFIX_RULE = (
    "tool_prefix must be 1-64 characters of A-Z, a-z, 0-9, '_' or '-', "
    "starting and ending with a letter or digit"
)
POLICY = ScopePolicy({})
IDENTITIES = {
    "alice": Identity({"user": ScopeGrant("u-alice", "owner")}),
    "bob": Identity({"user": ScopeGrant("u-bob", "owner")}),
}
FILE = {"scope": "user", "area": "notes", "name": "today"}


class _UserResolver:
    """Maps "alice" and "bob" to distinct identities; counts every call."""

    def __init__(self) -> None:
        self.calls: list[object] = []

    def resolve(self, credentials: object) -> Identity | ResolutionFailure:
        self.calls.append(credentials)
        if isinstance(credentials, str) and credentials in IDENTITIES:
            return IDENTITIES[credentials]
        return ResolutionFailure("no such user")


def _from_meta(ctx: Context[Any, Any]) -> object:
    meta = cast(Mapping[str, object], ctx.request_context.meta)
    return meta[META_KEY]


def _client() -> InProcessClient:
    return InProcessClient(MemoryStore(InMemoryStorage()))


def _kwargs(**overrides: object) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "client": _client(),
        "resolver": _UserResolver(),
        "policy": POLICY,
        "credentials_from_context": _from_meta,
        "source": "mcp-smoke",
    }
    kwargs.update(overrides)
    return kwargs


def _server(**overrides: object) -> MCPServer:
    kwargs = _kwargs(**overrides)
    kwargs.setdefault("slots", REFERENCE_SLOTS)
    return build_server(**kwargs)


def _run[T](fn: Callable[[], Awaitable[T]]) -> T:
    return anyio.run(fn)


def _with_client[T](
    server: MCPServer, body: Callable[[Client], Awaitable[T]], mode: str = "auto"
) -> T:
    async def main() -> T:
        with anyio.fail_after(30):
            async with Client(server, mode=mode) as client:
                return await body(client)

    return _run(main)


async def _call(client: Client, tool: str, user: str, **arguments: object) -> CallToolResult:
    return await client.call_tool(tool, dict(arguments), meta={META_KEY: user})


def _text(result: CallToolResult) -> str:
    assert len(result.content) == 1
    item = result.content[0]
    assert isinstance(item, TextContent)
    return item.text


def _payload(result: CallToolResult) -> dict[str, Any]:
    payload = result.structured_content
    assert payload is not None
    return payload


def _write_args(name: str = "today", **overrides: object) -> dict[str, object]:
    args: dict[str, object] = {
        "scope": "user",
        "area": "notes",
        "name": name,
        "content": "- [stated] Prefers tea\n",
        "description": "Drinks",
        "aliases": ["tea"],
        "expected_version": None,
    }
    args.update(overrides)
    return args


def _snapshot(server: MCPServer) -> tuple[set[str], set[str]]:
    async def main() -> tuple[set[str], set[str]]:
        tools = {tool.name for tool in await server.list_tools()}
        resources = {str(resource.uri) for resource in await server.list_resources()}
        return tools, resources

    return _run(main)


# --- US3: registration --------------------------------------------------------------


def test_module_exports_and_keyword_only_parameters() -> None:
    """wenchang.mcp exports exactly the five public names, and every build_server
    parameter and every register_memory_tools parameter after server is
    keyword-only (AIE-1060, US3.1).
    """
    assert wmcp.__all__ == [
        "PROMPT_RESOURCE_URI",
        "ToolCallRecord",
        "build_server",
        "memory_instructions",
        "register_memory_tools",
    ]
    for param in inspect.signature(build_server).parameters.values():
        assert param.kind is inspect.Parameter.KEYWORD_ONLY, param.name
    params = list(inspect.signature(register_memory_tools).parameters.values())
    assert params[0].name == "server"
    for param in params[1:]:
        assert param.kind is inspect.Parameter.KEYWORD_ONLY, param.name


def _tools(server: MCPServer) -> dict[str, Any]:
    async def body(client: Client) -> dict[str, Any]:
        return {tool.name: tool for tool in (await client.list_tools()).tools}

    return _with_client(server, body)


def test_lists_the_seven_tool_names() -> None:
    """With no prefix, tools/list carries exactly TOOL_NAMES (AIE-1060, US3.2)."""
    assert set(_tools(_server())) == set(TOOL_NAMES)


def test_prefix_applies_to_every_tool_name() -> None:
    """With tool_prefix="mixpanel", every name is "mixpanel_" + the tool name
    (AIE-1060, US3.3).
    """
    assert set(_tools(_server(tool_prefix="mixpanel"))) == {f"mixpanel_{n}" for n in TOOL_NAMES}


@pytest.mark.parametrize("product", [None, "Mixpanel"], ids=["no-product", "product"])
@pytest.mark.parametrize("prefix", [None, "mixpanel"], ids=["no-prefix", "prefix"])
def test_descriptions_equal_tool_descriptions(product: str | None, prefix: str | None) -> None:
    """Each listed description equals tool_descriptions(product)[name]
    (AIE-1060, US3.4).
    """
    listed = _tools(_server(product=product, tool_prefix=prefix))
    expected = tool_descriptions(product)

    for name in TOOL_NAMES:
        registered = name if prefix is None else f"{prefix}_{name}"
        assert listed[registered].description == expected[name]


def test_description_first_lines_name_the_product() -> None:
    """With product "Mixpanel", each description's first line contains it
    (AIE-1060, US3.5).
    """
    for tool in _tools(_server(product="Mixpanel")).values():
        assert "Mixpanel" in tool.description.split("\n", 1)[0]


def test_input_schemas_mirror_memory_tools_signatures() -> None:
    """Each input schema's properties are the MemoryTools method's parameters
    and its required set is those without a default; no schema exposes ctx
    (AIE-1060, US3.6).
    """
    listed = _tools(_server())

    for name in TOOL_NAMES:
        params = [
            p
            for p in inspect.signature(getattr(MemoryTools, name)).parameters.values()
            if p.name != "self"
        ]
        schema = listed[name].input_schema
        assert set(schema.get("properties", {})) == {p.name for p in params}, name
        assert set(schema.get("required", [])) == {
            p.name for p in params if p.default is inspect.Parameter.empty
        }, name
        assert "ctx" not in schema.get("properties", {})


def _kind(prop: Mapping[str, Any]) -> str:
    """Render a JSON-schema property as e.g. "string", "string|null", "array[string]"."""
    options = cast(list[Mapping[str, Any]], prop.get("anyOf", [prop]))
    kinds: list[str] = []
    for option in options:
        kind = cast(str, option["type"])
        if kind == "array":
            kind = f"array[{option['items']['type']}]"
        kinds.append(kind)
    return "|".join(kinds)


PINNED_KINDS: dict[str, dict[str, str]] = {
    "read_file": {"scope": "string", "area": "string", "name": "string"},
    "list_prefix": {"scope": "string", "area": "string|null", "cursor": "string|null"},
    "write_file": {
        "scope": "string",
        "area": "string",
        "name": "string",
        "content": "string",
        "description": "string",
        "aliases": "array[string]",
        "expected_version": "string|null",
    },
    "append_line": {
        "scope": "string",
        "area": "string",
        "name": "string",
        "line": "string",
        "expected_version": "string",
        "aliases": "array[string]|null",
        "description": "string|null",
    },
    "replace_fact": {
        "scope": "string",
        "area": "string",
        "name": "string",
        "old_string": "string",
        "new_string": "string",
        "expected_version": "string",
        "aliases": "array[string]|null",
        "description": "string|null",
    },
    "delete_file": {
        "scope": "string",
        "area": "string",
        "name": "string",
        "expected_version": "string",
    },
}


@pytest.mark.parametrize("tool", list(PINNED_KINDS))
def test_input_schema_types_are_pinned(tool: str) -> None:
    """The schema types of every tool parameter are pinned (AIE-1060, US3.7)."""
    properties = _tools(_server())[tool].input_schema["properties"]

    assert {name: _kind(prop) for name, prop in properties.items()} == PINNED_KINDS[tool]


@pytest.mark.parametrize(
    "prefix", ["", "has space", "a/b", "_lead", "-lead", "trail_", "trail-", "a" * 65]
)
def test_bad_prefix_is_rejected(prefix: str) -> None:
    """An invalid tool_prefix raises ValueError(TOOL_PREFIX_RULE) (AIE-1060, US3.8)."""
    with pytest.raises(ValueError) as caught:
        _server(tool_prefix=prefix)

    assert str(caught.value) == TOOL_PREFIX_RULE


@pytest.mark.parametrize("prefix", ["a", "mixpanel", "a_b-c", "a" * 64])
def test_good_prefix_is_accepted(prefix: str) -> None:
    """Valid prefixes, up to 64 characters, register (AIE-1060, US3.8)."""
    assert set(_tools(_server(tool_prefix=prefix))) == {f"{prefix}_{n}" for n in TOOL_NAMES}


@pytest.mark.parametrize("prefix", [1, b"x"])
def test_non_str_prefix_is_a_type_error(prefix: object) -> None:
    """A tool_prefix whose real type is not str raises TypeError (AIE-1060, US3.9)."""
    with pytest.raises(TypeError) as caught:
        _server(tool_prefix=prefix)

    assert str(caught.value) == f"tool_prefix must be a str or None, not {type(prefix).__name__}"


@pytest.mark.parametrize("product", [42, "", "  ", "a\nb", "a\ud800"])
def test_bad_product_matches_tool_descriptions(product: object) -> None:
    """A bad product raises the same exception as tool_descriptions (AIE-1060, US3.10)."""
    with pytest.raises((TypeError, ValueError)) as expected:
        tool_descriptions(product)  # pyright: ignore[reportArgumentType]
    with pytest.raises((TypeError, ValueError)) as caught:
        _server(product=product)

    assert type(caught.value) is type(expected.value)
    assert str(caught.value) == str(expected.value)


def test_empty_descriptions_fail_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty or whitespace descriptions raise a RuntimeError naming each tool
    and python -OO (AIE-1060, US3.11).
    """
    real = dict(tool_descriptions())
    real["read_file"] = ""
    real["delete_file"] = "  \n"

    def fake(product: str | None = None) -> Mapping[str, str]:
        return real

    monkeypatch.setattr(wmcp, "tool_descriptions", fake)

    with pytest.raises(RuntimeError) as caught:
        _server()

    assert str(caught.value) == (
        "memory tool descriptions are missing or empty for: read_file, delete_file; "
        "the tool docstrings may have been stripped (python -OO)"
    )


def test_missing_description_fails_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    """A description missing from the mapping raises a RuntimeError naming the
    tool (AIE-1060, US3.12).
    """
    real = {k: v for k, v in tool_descriptions().items() if k != "write_file"}

    def fake(product: str | None = None) -> Mapping[str, str]:
        return real

    monkeypatch.setattr(wmcp, "tool_descriptions", fake)

    with pytest.raises(RuntimeError, match="write_file"):
        _server()


def test_python_oo_fails_startup() -> None:
    """Under python -OO, building the server fails with the missing-description
    error (AIE-1060, US3.13).
    """
    code = f"""
import sys
sys.path.insert(0, {str(TESTS_DIR)!r})
from prompts_reference_adopter import REFERENCE_SLOTS
from wenchang.core import MemoryStore
from wenchang.identity import SandboxResolver, Identity
from wenchang.mcp import build_server
from wenchang.scope import ScopePolicy
from wenchang.storage.memory import InMemoryStorage
from wenchang.transport import InProcessClient
build_server(
    slots=REFERENCE_SLOTS,
    client=InProcessClient(MemoryStore(InMemoryStorage())),
    resolver=SandboxResolver(Identity({{}})),
    policy=ScopePolicy({{}}),
    credentials_from_context=lambda ctx: None,
    source="oo",
)
"""
    result = subprocess.run(
        [sys.executable, "-OO", "-c", code],
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
        check=False,
    )

    assert result.returncode != 0
    assert "memory tool descriptions are missing or empty for: get_memory_index" in result.stderr
    assert "python -OO" in result.stderr


async def _async_credentials(ctx: Context[Any, Any]) -> object:
    return None


async def _async_observer(record: ToolCallRecord) -> None:
    return None


BAD_ARGUMENTS: list[tuple[str, object, type[Exception], str]] = [
    ("client", object(), TypeError, "client must satisfy TransportClient"),
    ("policy", {}, TypeError, "policy must be a ScopePolicy, not dict"),
    ("source", 5, TypeError, "source must be a str, not int"),
    ("source", "", ValueError, "source must be non-empty"),
    ("resolver", object(), TypeError, "resolver must satisfy IdentityResolver"),
    ("credentials_from_context", "x", TypeError, "credentials_from_context must be callable"),
    ("on_call", "x", TypeError, "on_call must be callable or None"),
    (
        "credentials_from_context",
        _async_credentials,
        TypeError,
        "credentials_from_context must be a plain function, not async",
    ),
    ("on_call", _async_observer, TypeError, "on_call must be a plain function, not async"),
]


@pytest.mark.parametrize(("argument", "value", "error", "message"), BAD_ARGUMENTS)
def test_build_server_validates_up_front(
    monkeypatch: pytest.MonkeyPatch,
    argument: str,
    value: object,
    error: type[Exception],
    message: str,
) -> None:
    """Each bad argument raises its exact error before any server is created
    (AIE-1060, US3.14).
    """
    created: list[object] = []
    real_server = wmcp.MCPServer

    def recording(*args: Any, **kwargs: Any) -> MCPServer:
        server = real_server(*args, **kwargs)
        created.append(server)
        return server

    monkeypatch.setattr(wmcp, "MCPServer", recording)

    with pytest.raises(error) as caught:
        _server(**{argument: value})

    assert str(caught.value) == message
    assert created == []


def _adopter_server(instructions: str | None = None) -> MCPServer:
    server = MCPServer("host", instructions=instructions)

    def ping() -> str:
        return "pong"

    server.add_tool(ping, name="ping", description="Ping the host.")
    return server


def test_register_on_adopter_server() -> None:
    """register_memory_tools adds the seven tools and the resource to an
    adopter's server, beside its own tools (AIE-1060, US3.15).
    """
    prompt = build_memory_prompt(REFERENCE_SLOTS)
    server = _adopter_server(prompt)

    returned = register_memory_tools(server, prompt=prompt, **_kwargs(product="Mixpanel"))

    async def body(client: Client) -> tuple[dict[str, Any], str, str | None]:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
        read = await client.read_resource(PROMPT_RESOURCE_URI)
        text = cast(Any, read.contents[0]).text
        return tools, text, client.instructions

    tools, text, instructions = _with_client(server, body)
    assert returned is None
    assert set(tools) == {"ping", *TOOL_NAMES}
    for name in TOOL_NAMES:
        assert tools[name].description == tool_descriptions("Mixpanel")[name]
    assert text == prompt
    assert instructions == prompt


@pytest.mark.parametrize(
    ("prompt", "error", "message"),
    [
        (5, TypeError, "prompt must be a str, not int"),
        (None, TypeError, "prompt must be a str, not NoneType"),
        ("", ValueError, "prompt must be non-empty"),
        ("  \n", ValueError, "prompt must be non-empty"),
    ],
)
def test_register_rejects_bad_prompt(prompt: object, error: type[Exception], message: str) -> None:
    """A bad prompt raises and the server gains nothing (AIE-1060, US3.16)."""
    server = _adopter_server()
    before = _snapshot(server)

    with pytest.raises(error) as caught:
        register_memory_tools(server, prompt=prompt, **_kwargs())  # pyright: ignore[reportArgumentType]

    assert str(caught.value) == message
    assert _snapshot(server) == before


REGISTER_BAD_ARGUMENTS = [
    *BAD_ARGUMENTS,
    ("tool_prefix", "a/b", ValueError, TOOL_PREFIX_RULE),
    ("tool_prefix", 1, TypeError, "tool_prefix must be a str or None, not int"),
]


@pytest.mark.parametrize(("argument", "value", "error", "message"), REGISTER_BAD_ARGUMENTS)
def test_register_validates_like_build_server(
    argument: str, value: object, error: type[Exception], message: str
) -> None:
    """register_memory_tools raises build_server's errors and the server gains
    nothing (AIE-1060, US3.17).
    """
    server = _adopter_server()
    before = _snapshot(server)

    with pytest.raises(error) as caught:
        register_memory_tools(server, prompt="p", **_kwargs(**{argument: value}))

    assert str(caught.value) == message
    assert _snapshot(server) == before


def test_register_rejects_non_server() -> None:
    """A server that is not an MCPServer raises TypeError (AIE-1060, US3.17)."""
    with pytest.raises(TypeError) as caught:
        register_memory_tools(object(), prompt="p", **_kwargs())  # pyright: ignore[reportArgumentType]

    assert str(caught.value) == "server must be an MCPServer, not object"


def test_register_rejects_colliding_tool() -> None:
    """An adopter tool named read_file collides; nothing is registered
    (AIE-1060, US3.18).
    """
    server = _adopter_server()
    server.add_tool(lambda: "x", name="read_file", description="Adopter tool.")
    before = _snapshot(server)

    with pytest.raises(ValueError) as caught:
        register_memory_tools(server, prompt="p", **_kwargs())

    assert str(caught.value) == (
        "cannot register memory tools: already registered on the server: read_file"
    )
    assert _snapshot(server) == before


def test_register_rejects_colliding_prefixed_tool() -> None:
    """With tool_prefix="mixpanel", an adopter tool mixpanel_read_file collides
    (AIE-1060, US3.18).
    """
    server = _adopter_server()
    server.add_tool(lambda: "x", name="mixpanel_read_file", description="Adopter tool.")
    before = _snapshot(server)

    with pytest.raises(ValueError, match="mixpanel_read_file"):
        register_memory_tools(server, prompt="p", **_kwargs(tool_prefix="mixpanel"))

    assert _snapshot(server) == before


def test_register_twice_is_rejected() -> None:
    """A second registration names every tool and the resource, and changes
    nothing (AIE-1060, US3.18).
    """
    server = _adopter_server("p")
    register_memory_tools(server, prompt="p", **_kwargs())
    before = _snapshot(server)

    with pytest.raises(ValueError) as caught:
        register_memory_tools(server, prompt="p", **_kwargs())

    assert str(caught.value) == (
        "cannot register memory tools: already registered on the server: "
        + ", ".join(sorted([*TOOL_NAMES, PROMPT_RESOURCE_URI]))
    )
    assert _snapshot(server) == before


@pytest.mark.parametrize("instructions", [None, "Something else."])
def test_register_warns_when_instructions_lack_prompt(
    caplog: pytest.LogCaptureFixture, instructions: str | None
) -> None:
    """Instructions that are None or lack the prompt log one warning
    (AIE-1060, US3.19).
    """
    caplog.set_level(logging.WARNING, logger="wenchang.mcp")

    register_memory_tools(_adopter_server(instructions), prompt="PROMPT", **_kwargs())

    warnings = [r for r in caplog.records if r.name == "wenchang.mcp"]
    assert len(warnings) == 1
    assert warnings[0].levelno == logging.WARNING


def test_register_does_not_warn_when_instructions_contain_prompt(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Instructions containing the prompt log no warning (AIE-1060, US3.19)."""
    caplog.set_level(logging.DEBUG, logger="wenchang.mcp")

    register_memory_tools(_adopter_server("Host text.\n\nPROMPT"), prompt="PROMPT", **_kwargs())

    assert [r for r in caplog.records if r.name == "wenchang.mcp"] == []


def test_memory_instructions_is_the_prompt() -> None:
    """memory_instructions(slots) is the memory prompt and build_server uses it
    as instructions (AIE-1060, US3.20).
    """
    prompt = build_memory_prompt(REFERENCE_SLOTS)

    assert memory_instructions(REFERENCE_SLOTS) == prompt
    assert _server().instructions == prompt


# --- US4: prompt delivery -----------------------------------------------------------


@pytest.mark.parametrize("mode", ["legacy", "auto"])
def test_instructions_are_the_prompt(mode: str) -> None:
    """The client sees the memory prompt as instructions, through the initialize
    handshake and through discover (AIE-1060, US4.1, US4.2).
    """

    async def body(client: Client) -> str | None:
        return client.instructions

    assert _with_client(_server(), body, mode=mode) == build_memory_prompt(REFERENCE_SLOTS)


def test_prompt_resource_is_listed() -> None:
    """Exactly one listed resource is the prompt, as text/markdown (AIE-1060, US4.3)."""

    async def body(client: Client) -> list[Any]:
        return (await client.list_resources()).resources

    resources = [r for r in _with_client(_server(), body) if str(r.uri) == PROMPT_RESOURCE_URI]

    assert len(resources) == 1
    assert resources[0].mime_type == "text/markdown"


def test_prompt_resource_serves_the_prompt() -> None:
    """Reading the resource returns exactly the memory prompt (AIE-1060, US4.4)."""

    async def body(client: Client) -> list[Any]:
        return (await client.read_resource(PROMPT_RESOURCE_URI)).contents

    contents = _with_client(_server(), body)

    assert len(contents) == 1
    assert contents[0].text == build_memory_prompt(REFERENCE_SLOTS)


def test_prompt_is_built_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """build_memory_prompt runs once across a build, two clients, and four
    resource reads (AIE-1060, US4.5).
    """
    calls: list[object] = []

    def counting(slots: Any) -> str:
        calls.append(slots)
        return build_memory_prompt(slots)

    monkeypatch.setattr(wmcp, "build_memory_prompt", counting)
    server = _server()

    async def body(client: Client) -> None:
        await client.read_resource(PROMPT_RESOURCE_URI)
        await client.read_resource(PROMPT_RESOURCE_URI)

    _with_client(server, body)
    _with_client(server, body)
    assert len(calls) == 1


def test_bad_slots_is_a_type_error() -> None:
    """slots that are not PromptSlots raise TypeError (AIE-1060, US4.6)."""
    with pytest.raises(TypeError, match="slots must be PromptSlots"):
        _server(slots="not slots")


# --- US5: calls ---------------------------------------------------------------------


def _alice(client: InProcessClient) -> MemoryTools:
    return bind_tools(client, _UserResolver(), "alice", POLICY, source="mcp-smoke")


def test_write_then_read_round_trip() -> None:
    """write_file and read_file results equal render_result of a direct read,
    as structured content and as JSON text (AIE-1060, US5.1).
    """
    transport = _client()
    server = _server(client=transport)

    async def body(client: Client) -> tuple[CallToolResult, CallToolResult]:
        written = await _call(client, "write_file", "alice", **_write_args())
        read = await _call(client, "read_file", "alice", **FILE)
        return written, read

    written, read = _with_client(server, body)
    direct = render_result(_alice(transport).read_file("user", "notes", "today"))

    for result in (written, read):
        assert result.is_error is False
        assert result.structured_content == direct
        assert json.loads(_text(result)) == direct


def test_delete_renders_ok() -> None:
    """A successful delete_file renders {"ok": True} (AIE-1060, US5.2)."""

    async def body(client: Client) -> CallToolResult:
        written = _payload(await _call(client, "write_file", "alice", **_write_args()))
        return await _call(
            client, "delete_file", "alice", **FILE, expected_version=written["version"]
        )

    assert _payload(_with_client(_server(), body)) == {"ok": True}


def test_each_caller_sees_only_their_own_files() -> None:
    """Bob cannot read the file alice wrote at the same (scope, area, name)
    (AIE-1060, US5.3).
    """

    async def body(client: Client) -> tuple[CallToolResult, CallToolResult]:
        written = await _call(client, "write_file", "alice", **_write_args())
        bobs = await _call(client, "read_file", "bob", **FILE)
        return written, bobs

    written, bobs = _with_client(_server(), body)

    assert "u-alice" in _payload(written)["path"]
    assert bobs.is_error is True
    assert _payload(bobs)["error"] == "NotFoundError"


def test_every_call_binds_its_own_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each call binds a new MemoryTools with that call's credentials, and the
    resolver runs once per call (AIE-1060, US5.4).
    """
    bound: list[tuple[object, MemoryTools]] = []

    def recording(*args: Any, **kwargs: Any) -> MemoryTools:
        tools = bind_tools(*args, **kwargs)
        bound.append((args[2], tools))
        return tools

    monkeypatch.setattr(wmcp, "bind_tools", recording)
    resolver = _UserResolver()
    server = _server(resolver=resolver)
    users = ["alice", "bob", "alice", "bob", "alice", "bob"]

    async def body(client: Client) -> None:
        for user in users:
            await _call(client, "read_file", user, **FILE)

    _with_client(server, body)

    assert [credentials for credentials, _ in bound] == users
    assert len({id(tools) for _, tools in bound}) == len(users)
    assert resolver.calls == users


def test_system_write_is_rendered_permanent() -> None:
    """A write to the system area renders the same RestrictedScopeError as a
    direct call (AIE-1060, US5.5).
    """
    transport = _client()
    args = _write_args(area="system")

    async def body(client: Client) -> CallToolResult:
        return await _call(client, "write_file", "alice", **args)

    result = _with_client(_server(client=transport), body)
    with pytest.raises(Exception) as direct:
        _alice(transport).write_file(**cast(Any, args))

    assert result.is_error is True
    assert result.structured_content == render_error(direct.value)
    assert _payload(result)["category"] == "permanent"


def test_missing_file_is_rendered_recoverable() -> None:
    """read_file of a missing file is a recoverable NotFoundError (AIE-1060, US5.6)."""

    async def body(client: Client) -> CallToolResult:
        return await _call(client, "read_file", "alice", **FILE)

    result = _with_client(_server(), body)

    assert result.is_error is True
    assert _payload(result)["category"] == "recoverable"
    assert _payload(result)["error"] == "NotFoundError"


def test_credential_extraction_failure_leaks_nothing(caplog: pytest.LogCaptureFixture) -> None:
    """A raising credentials_from_context renders a permanent
    ResolverFailureError, and the exception text appears in neither the result
    nor the logs; one WARNING names the exception type only; the resolver is
    not called (AIE-1060, US5.7).
    """
    caplog.set_level(logging.DEBUG)
    resolver = _UserResolver()

    def leaky(ctx: Context[Any, Any]) -> object:
        raise RuntimeError("secret-token-123")

    async def body(client: Client) -> CallToolResult:
        return await _call(client, "read_file", "alice", **FILE)

    result = _with_client(_server(resolver=resolver, credentials_from_context=leaky), body)

    assert result.is_error is True
    assert _payload(result)["error"] == "ResolverFailureError"
    assert _payload(result)["category"] == "permanent"
    assert "secret-token-123" not in _text(result)
    assert "secret-token-123" not in json.dumps(result.structured_content)
    for record in caplog.records:
        assert "secret-token-123" not in record.getMessage()
        if record.exc_info is not None:
            assert "secret-token-123" not in logging.Formatter().formatException(record.exc_info)
    warnings = [r for r in caplog.records if r.name == "wenchang.mcp"]
    assert len(warnings) == 1
    assert warnings[0].levelno == logging.WARNING
    assert warnings[0].exc_info is None
    assert "RuntimeError" in warnings[0].getMessage()
    assert "read_file" in warnings[0].getMessage()
    assert resolver.calls == []


def test_resolution_failure_is_rendered() -> None:
    """A ResolutionFailure from the resolver renders as ResolverFailureError
    carrying its detail (AIE-1060, US5.8).
    """

    async def body(client: Client) -> CallToolResult:
        return await _call(client, "read_file", "mallory", **FILE)

    result = _with_client(_server(), body)

    assert result.is_error is True
    assert _payload(result)["error"] == "ResolverFailureError"
    assert "no such user" in _payload(result)["message"]


class _BrokenClient(InProcessClient):
    """An in-process client whose read_file raises an off-contract exception."""

    def read_file(self, path: str) -> Any:
        raise KeyError("internal-detail")


def test_off_contract_error_is_internal_and_logged(caplog: pytest.LogCaptureFixture) -> None:
    """An off-contract client exception renders as "internal error" and is
    logged with exc_info on wenchang.mcp (AIE-1060, US5.9).
    """
    caplog.set_level(logging.ERROR, logger="wenchang.mcp")

    async def body(client: Client) -> CallToolResult:
        return await _call(client, "read_file", "alice", **FILE)

    result = _with_client(_server(client=_BrokenClient(MemoryStore(InMemoryStorage()))), body)

    assert result.is_error is True
    assert _payload(result)["category"] == "internal"
    assert _payload(result)["message"] == "internal error"
    errors = [r for r in caplog.records if r.name == "wenchang.mcp"]
    assert len(errors) == 1
    assert errors[0].levelno == logging.ERROR
    assert errors[0].exc_info is not None


def test_source_is_stamped() -> None:
    """The configured source is stamped on writes (AIE-1060, US5.10)."""

    async def body(client: Client) -> CallToolResult:
        return await _call(client, "write_file", "alice", **_write_args())

    assert "mcp-smoke" in _payload(_with_client(_server(), body))["sources"]


def test_prefixed_tool_forwards() -> None:
    """mixpanel_read_file forwards to read_file (AIE-1060, US5.11)."""

    async def body(client: Client) -> CallToolResult:
        await _call(client, "mixpanel_write_file", "alice", **_write_args())
        return await _call(client, "mixpanel_read_file", "alice", **FILE)

    result = _with_client(_server(tool_prefix="mixpanel"), body)

    assert result.is_error is False
    assert _payload(result)["content"] == "- [stated] Prefers tea\n"


@pytest.mark.parametrize(
    ("arguments", "named"),
    [
        ({"scope": 5, "area": "notes", "name": "today"}, "scope"),
        ({"scope": "user", "area": "notes"}, "name"),
    ],
)
def test_schema_invalid_arguments_bypass_rendering(
    arguments: dict[str, object], named: str
) -> None:
    """Wrong-type and missing arguments are rejected by MCP before the wrapper:
    is_error with text naming the argument and no structured content
    (AIE-1060, US5.12).
    """

    async def body(client: Client) -> CallToolResult:
        return await client.call_tool("read_file", arguments, meta={META_KEY: "alice"})

    result = _with_client(_server(), body)

    assert result.is_error is True
    assert result.structured_content is None
    assert named in _text(result)


def test_null_area_is_pre_parsed_to_none() -> None:
    """Pins an mcp quirk, expected to fail when mcp stops pre-parsing: area="null"
    arrives as None and lists the whole scope (AIE-1060, US5.13).
    """

    async def body(client: Client) -> CallToolResult:
        await _call(client, "write_file", "alice", **_write_args("a"))
        await _call(client, "write_file", "alice", **_write_args("b", area="people"))
        return await _call(client, "list_prefix", "alice", scope="user", area="null")

    result = _with_client(_server(), body)

    assert result.is_error is False
    assert {entry["area"] for entry in _payload(result)["entries"]} == {"notes", "people"}


def test_null_description_is_pre_parsed_to_no_change() -> None:
    """Pins an mcp quirk, expected to fail when mcp stops pre-parsing:
    description="null" on append_line leaves the description unchanged
    (AIE-1060, US5.14).
    """

    async def body(client: Client) -> CallToolResult:
        written = _payload(
            await _call(client, "write_file", "alice", **_write_args(description="d1"))
        )
        return await _call(
            client,
            "append_line",
            "alice",
            **FILE,
            line="- [stated] Also coffee",
            expected_version=written["version"],
            description="null",
        )

    result = _with_client(_server(), body)

    assert result.is_error is False
    assert _payload(result)["description"] == "d1"


def test_list_shaped_area_is_a_schema_error() -> None:
    """area="[1]" pre-parses to a list and fails schema validation
    (AIE-1060, US5.15).
    """

    async def body(client: Client) -> CallToolResult:
        return await _call(client, "list_prefix", "alice", scope="user", area="[1]")

    result = _with_client(_server(), body)

    assert result.is_error is True
    assert result.structured_content is None
    assert "area" in _text(result)


# --- US6.4 and US6.5: concurrent calls (end-to-end smoke checks) ----------------------

CONCURRENT = 8


def _concurrently(
    server: MCPServer,
    setup: Callable[[Client], Awaitable[dict[str, Any]]],
    make_args: Callable[[int, dict[str, Any]], dict[str, object]],
) -> list[CallToolResult]:
    async def body(client: Client) -> list[CallToolResult]:
        state = await setup(client)
        go = anyio.Event()
        results: list[CallToolResult] = []

        async def one(i: int) -> None:
            await go.wait()
            results.append(await _call(client, "write_file", "alice", **make_args(i, state)))

        async with anyio.create_task_group() as group:
            for i in range(CONCURRENT):
                group.start_soon(one, i)
            go.set()
        return results

    return _with_client(server, body)


def test_concurrent_writes_at_one_version_have_one_winner() -> None:
    """Concurrent write_file calls at the same expected_version: exactly one
    wins, the rest get a recoverable VersionConflictError carrying the winner's
    version (AIE-1060, US6.4).
    """

    setup_version: list[str] = []

    async def setup(client: Client) -> dict[str, Any]:
        state = _payload(await _call(client, "write_file", "alice", **_write_args()))
        setup_version.append(state["version"])
        return state

    results = _concurrently(
        _server(),
        setup,
        lambda i, state: _write_args(
            content=f"- [stated] v{i}\n", expected_version=state["version"]
        ),
    )

    winners = [_payload(r) for r in results if r.is_error is False]
    losers = [_payload(r) for r in results if r.is_error is True]
    assert len(winners) == 1
    assert len(losers) == CONCURRENT - 1
    for loser in losers:
        assert loser["error"] == "VersionConflictError"
        assert loser["category"] == "recoverable"
        assert loser["version"] == winners[0]["version"]
    assert winners[0]["version"] != setup_version[0]


def test_concurrent_creates_mint_distinct_versions() -> None:
    """Concurrent creates of distinct files all succeed with distinct versions
    (AIE-1060, US6.5).
    """

    async def setup(client: Client) -> dict[str, Any]:
        return {}

    results = _concurrently(_server(), setup, lambda i, _: _write_args(f"file-{i}"))

    assert all(r.is_error is False for r in results)
    assert len({_payload(r)["version"] for r in results}) == CONCURRENT


# --- US7: on_call observer ----------------------------------------------------------


def test_tool_call_record_shape() -> None:
    """ToolCallRecord is a frozen dataclass with tool, arguments, result,
    is_error, request_id, and duration_s (AIE-1060, US7.1).
    """
    assert is_dataclass(ToolCallRecord)
    assert [f.name for f in fields(ToolCallRecord)] == [
        "tool",
        "arguments",
        "result",
        "is_error",
        "request_id",
        "duration_s",
    ]
    record = ToolCallRecord("t", {}, {}, False, "1", 0.0)
    with pytest.raises(FrozenInstanceError):
        record.tool = "u"  # pyright: ignore[reportAttributeAccessIssue]


def test_record_result_does_not_alias_structured_content() -> None:
    """An observer mutating a nested list in the record's result while the call
    is in flight does not change what the client receives (AIE-1060, US7.1).
    """

    def observer(record: ToolCallRecord) -> None:
        cast(list[str], record.result["aliases"]).append("from-observer")

    async def body(client: Client) -> CallToolResult:
        return await _call(client, "write_file", "alice", **_write_args())

    result = _with_client(_server(on_call=observer), body)

    assert _payload(result)["aliases"] == ["tea"]


def test_record_for_successful_prefixed_call() -> None:
    """A successful mixpanel_read_file produces one record with the registered
    name, the received arguments, and the rendered result (AIE-1060, US7.2).
    """
    records: list[ToolCallRecord] = []
    server = _server(tool_prefix="mixpanel", on_call=records.append)

    async def body(client: Client) -> CallToolResult:
        await _call(client, "mixpanel_write_file", "alice", **_write_args())
        records.clear()
        return await _call(client, "mixpanel_read_file", "alice", **FILE)

    result = _with_client(server, body)

    assert len(records) == 1
    assert records[0].tool == "mixpanel_read_file"
    assert dict(records[0].arguments) == FILE
    assert dict(records[0].result) == result.structured_content
    assert records[0].is_error is False
    assert isinstance(records[0].duration_s, float)
    assert records[0].duration_s >= 0


def test_records_carry_distinct_request_ids() -> None:
    """Each record carries its MCP request's id, so records arriving in
    completion order can be correlated (AIE-1060, US7.7).
    """
    records: list[ToolCallRecord] = []
    server = _server(on_call=records.append)

    async def reads(client: Client) -> None:
        async with anyio.create_task_group() as group:
            for _ in range(4):
                group.start_soon(_read, client)

    _with_client(server, reads)

    assert len(records) == 4
    assert all(isinstance(r.request_id, str) and r.request_id for r in records)
    assert len({r.request_id for r in records}) == 4


async def _read(client: Client) -> None:
    await _call(client, "read_file", "alice", **FILE)


def test_records_for_failed_calls() -> None:
    """A NotFoundError call and a credential-extraction failure each produce a
    record with is_error True (AIE-1060, US7.3).
    """
    records: list[ToolCallRecord] = []

    def creds(ctx: Context[Any, Any]) -> object:
        user = _from_meta(ctx)
        if user == "broken":
            raise RuntimeError("no credentials")
        return user

    server = _server(on_call=records.append, credentials_from_context=creds)

    async def body(client: Client) -> list[CallToolResult]:
        return [
            await _call(client, "read_file", "alice", **FILE),
            await _call(client, "read_file", "broken", **FILE),
        ]

    results = _with_client(server, body)

    assert len(records) == 2
    for record, result in zip(records, results, strict=True):
        assert record.is_error is True
        assert dict(record.result) == result.structured_content
    assert records[0].result["error"] == "NotFoundError"
    assert records[1].result["error"] == "ResolverFailureError"


def test_schema_rejected_call_produces_no_record() -> None:
    """A call MCP rejects during argument validation never reaches the wrapper,
    so it produces no record (AIE-1060, US7.4).
    """
    records: list[ToolCallRecord] = []

    async def body(client: Client) -> CallToolResult:
        return await client.call_tool(
            "read_file", {"scope": 5, "area": "a", "name": "n"}, meta={META_KEY: "alice"}
        )

    result = _with_client(_server(on_call=records.append), body)

    assert result.is_error is True
    assert records == []


def test_failing_observer_does_not_reach_client(caplog: pytest.LogCaptureFixture) -> None:
    """An on_call that raises is logged at ERROR; the client still gets the
    normal result, without the observer's message (AIE-1060, US7.5).
    """
    caplog.set_level(logging.ERROR, logger="wenchang.mcp")

    def observer(record: ToolCallRecord) -> None:
        raise RuntimeError("observer-secret")

    async def body(client: Client) -> CallToolResult:
        return await _call(client, "write_file", "alice", **_write_args())

    result = _with_client(_server(on_call=observer), body)

    assert result.is_error is False
    assert "observer-secret" not in _text(result)
    errors = [r for r in caplog.records if r.name == "wenchang.mcp"]
    assert len(errors) == 1
    assert errors[0].levelno == logging.ERROR


def test_no_observer_by_default() -> None:
    """With on_call=None, calls work as usual (AIE-1060, US7.6)."""
    assert "on_call" in inspect.signature(build_server).parameters
    assert inspect.signature(build_server).parameters["on_call"].default is None

    async def body(client: Client) -> CallToolResult:
        return await _call(client, "write_file", "alice", **_write_args())

    assert _with_client(_server(), body).is_error is False
