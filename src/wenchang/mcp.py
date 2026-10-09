"""MCP server adapter: the memory tools and prompt on an mcp MCPServer.

register_memory_tools adds the seven memory tools and the prompt resource to
an adopter's MCPServer; build_server constructs one with the prompt as its
instructions. Every tool call reads the caller's credentials from the
request, binds that caller's own MemoryTools, forwards the call, and returns
render_result or render_error output.

Requires the optional extra: pip install 'wenchang[mcp]'.
"""

import copy
import importlib.util
import inspect
import json
import logging
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, cast

# mcp is an optional dependency; tell a missing install from an incompatible one.
if importlib.util.find_spec("mcp") is None:
    raise ImportError("wenchang.mcp requires the optional 'mcp' extra: pip install 'wenchang[mcp]'")
try:
    from mcp.server.mcpserver import Context, MCPServer
    from mcp.types import CallToolResult, TextContent
except ImportError as exc:
    raise ImportError(
        "wenchang.mcp requires mcp>=2.2,<3, and the installed mcp is incompatible: "
        "pip install 'wenchang[mcp]'"
    ) from exc

import wenchang
from wenchang.core import ListCursor, ListPage, MemoryFile, MemoryIndex
from wenchang.errors import ResolverFailureError
from wenchang.identity import Identity, IdentityResolver
from wenchang.prompts import PromptSlots, build_memory_prompt
from wenchang.scope import ScopePolicy
from wenchang.tools import (
    TOOL_NAMES,
    MemoryTools,
    bind_tools,
    render_error,
    render_result,
    tool_descriptions,
)
from wenchang.transport import TransportClient
from wenchang.version_token import VersionToken

__all__ = [
    "PROMPT_RESOURCE_URI",
    "ToolCallRecord",
    "build_server",
    "memory_instructions",
    "register_memory_tools",
]

PROMPT_RESOURCE_URI: Final[str] = "wenchang://memory-prompt"

_TOOL_PREFIX_RULE: Final[str] = (
    "tool_prefix must be 1-64 characters of A-Z, a-z, 0-9, '_' or '-', "
    "starting and ending with a letter or digit"
)
_TOOL_PREFIX: Final = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9_-]{0,62}[A-Za-z0-9])?")

_log = logging.getLogger("wenchang.mcp")

type _Result = MemoryFile | ListPage | MemoryIndex | None

# Wrappers annotate ctx as Context directly: MCPServer detects the injected
# parameter by annotation and does not see through a type alias.


@dataclass(frozen=True)
class ToolCallRecord:
    """One memory tool call as the MCP adapter handled it.

    tool is the registered name, prefix included; arguments are what the
    wrapper received; result is a copy of the payload sent to the client;
    request_id is the MCP request's id, for correlating records that arrive
    in completion order; duration_s is the wrapper's wall time on a
    monotonic clock. Calls MCP rejects during argument validation never
    produce a record. Records compare by value and are unhashable, because
    arguments and result are mappings.
    """

    tool: str
    arguments: Mapping[str, object]
    result: Mapping[str, object]
    is_error: bool
    request_id: str
    duration_s: float


def memory_instructions(slots: PromptSlots) -> str:
    """The text to pass as an MCPServer's instructions: the memory prompt."""
    return build_memory_prompt(slots)


def _type_name(t: type) -> str:
    # A metaclass may make __name__ raise or return a str subclass.
    try:
        return str.__str__(t.__name__)
    except Exception:
        return "<unnamed>"


def _validate[C](
    *,
    client: TransportClient,
    resolver: IdentityResolver[C],
    policy: ScopePolicy,
    credentials_from_context: Callable[[Context[Any, Any]], C],
    source: str,
    product: str | None,
    tool_prefix: str | None,
    on_call: Callable[[ToolCallRecord], None] | None,
) -> tuple[dict[str, str], Mapping[str, str]]:
    """Check the arguments; return registered name by tool name, and the descriptions."""
    # Reuses MemoryTools' checks and messages for client, policy, source, and product.
    MemoryTools(client, Identity({}), policy, source=source, product=product)
    if not isinstance(cast(object, resolver), IdentityResolver):
        raise TypeError("resolver must satisfy IdentityResolver")
    if not callable(cast(object, credentials_from_context)):
        raise TypeError("credentials_from_context must be callable")
    # Tools run on worker threads and call these synchronously.
    if inspect.iscoroutinefunction(credentials_from_context):
        raise TypeError("credentials_from_context must be a plain function, not async")
    if on_call is not None and not callable(cast(object, on_call)):
        raise TypeError("on_call must be callable or None")
    if inspect.iscoroutinefunction(on_call):
        raise TypeError("on_call must be a plain function, not async")
    if tool_prefix is not None:
        if not issubclass(type(cast(object, tool_prefix)), str):
            raise TypeError(
                f"tool_prefix must be a str or None, not {_type_name(type(tool_prefix))}"
            )
        tool_prefix = str.__str__(tool_prefix)
        if _TOOL_PREFIX.fullmatch(tool_prefix) is None:
            raise ValueError(_TOOL_PREFIX_RULE)
    names = {name: name if tool_prefix is None else f"{tool_prefix}_{name}" for name in TOOL_NAMES}
    descriptions = tool_descriptions(product)
    missing = [
        name for name in TOOL_NAMES if name not in descriptions or not descriptions[name].strip()
    ]
    if missing:
        raise RuntimeError(
            f"memory tool descriptions are missing or empty for: {', '.join(missing)}; "
            "the tool docstrings may have been stripped (python -OO)"
        )
    return names, descriptions


def register_memory_tools[C](
    server: MCPServer,
    *,
    prompt: str,
    client: TransportClient,
    resolver: IdentityResolver[C],
    policy: ScopePolicy,
    credentials_from_context: Callable[[Context[Any, Any]], C],
    source: str,
    product: str | None = None,
    tool_prefix: str | None = None,
    on_call: Callable[[ToolCallRecord], None] | None = None,
) -> None:
    """Add the seven memory tools and the prompt resource to server.

    prompt is memory_instructions(slots); pass the same text as the server's
    instructions. credentials_from_context returns the caller's raw
    credentials, which resolver verifies; each call binds its own
    MemoryTools. Tool calls run concurrently on worker threads, so client
    must be thread-safe, and on_call, if given, runs on those threads after
    each call and must be thread-safe and fast. Raises before registering
    anything if an argument is invalid or a name is already registered.
    """
    if not issubclass(type(cast(object, server)), MCPServer):
        raise TypeError(f"server must be an MCPServer, not {_type_name(type(server))}")
    names, descriptions = _validate(
        client=client,
        resolver=resolver,
        policy=policy,
        credentials_from_context=credentials_from_context,
        source=source,
        product=product,
        tool_prefix=tool_prefix,
        on_call=on_call,
    )
    if not issubclass(type(cast(object, prompt)), str):
        raise TypeError(f"prompt must be a str, not {_type_name(type(prompt))}")
    prompt = str.__str__(prompt)
    if not prompt.strip():
        raise ValueError("prompt must be non-empty")
    # MCPServer only logs a duplicate tool or resource, so collisions are checked first.
    # The managers are private mcp attributes; the mcp<3 pin keeps them stable.
    existing_tools = {tool.name for tool in server._tool_manager.list_tools()}  # pyright: ignore[reportPrivateUsage]
    existing_resources = {
        str(resource.uri)
        for resource in server._resource_manager.list_resources()  # pyright: ignore[reportPrivateUsage]
    }
    tool_hits = [n for n in names.values() if n in existing_tools]
    uri_hits = [PROMPT_RESOURCE_URI] if PROMPT_RESOURCE_URI in existing_resources else []
    collisions = sorted([*tool_hits, *uri_hits])
    if collisions:
        raise ValueError(
            "cannot register memory tools: already registered on the server: "
            + ", ".join(collisions)
        )

    def read_prompt() -> str:
        return prompt

    server.resource(
        PROMPT_RESOURCE_URI,
        name="memory_prompt",
        title="Memory prompt",
        description="The memory system prompt; the same text as the server instructions.",
        mime_type="text/markdown",
    )(read_prompt)

    def call(
        name: str,
        ctx: Context[Any, Any],
        arguments: Mapping[str, object],
        op: Callable[[MemoryTools], _Result],
    ) -> CallToolResult:
        tool = names[name]
        started = time.monotonic()
        payload, is_error = _run(ctx, op, tool)
        duration = time.monotonic() - started
        result = CallToolResult(
            content=[TextContent(type="text", text=json.dumps(payload))],
            structured_content=payload,
            is_error=is_error,
        )
        if on_call is not None:
            record = ToolCallRecord(
                tool,
                MappingProxyType(copy.deepcopy(dict(arguments))),
                MappingProxyType(copy.deepcopy(payload)),
                is_error,
                ctx.request_id,
                duration,
            )
            try:
                on_call(record)
            except Exception:
                _log.error("on_call observer failed for %s", tool, exc_info=True)
        return result

    def _run(
        ctx: Context[Any, Any], op: Callable[[MemoryTools], _Result], tool: str
    ) -> tuple[dict[str, object], bool]:
        failed_type: str | None = None
        credentials: C | None = None
        try:
            credentials = credentials_from_context(ctx)
        except Exception as exc:
            failed_type = _type_name(type(exc))
        # Handled outside the except block so the original exception is not kept as context;
        # only its type is logged, since its message may carry the credential.
        if failed_type is not None:
            _log.warning("memory tool %s: credentials_from_context raised %s", tool, failed_type)
            failure = ResolverFailureError("Credentials could not be read from the request.")
            return render_error(failure), True
        try:
            tools = bind_tools(
                client,
                resolver,
                cast(C, credentials),
                policy,
                source=source,
                product=product,
            )
            return render_result(op(tools)), False
        except Exception as exc:
            payload = render_error(exc)
            if payload["category"] == "internal":
                _log.error("memory tool %s failed", tool, exc_info=exc)
            return payload, True

    def get_memory_index(*, ctx: Context[Any, Any]) -> CallToolResult:
        return call("get_memory_index", ctx, {}, lambda tools: tools.get_memory_index())

    def read_file(scope: str, area: str, name: str, *, ctx: Context[Any, Any]) -> CallToolResult:
        return call(
            "read_file",
            ctx,
            {"scope": scope, "area": area, "name": name},
            lambda tools: tools.read_file(scope, area, name),
        )

    def list_prefix(
        scope: str,
        area: str | None = None,
        cursor: ListCursor | None = None,
        *,
        ctx: Context[Any, Any],
    ) -> CallToolResult:
        return call(
            "list_prefix",
            ctx,
            {"scope": scope, "area": area, "cursor": cursor},
            lambda tools: tools.list_prefix(scope, area, cursor),
        )

    def write_file(
        scope: str,
        area: str,
        name: str,
        content: str,
        description: str,
        aliases: Sequence[str],
        expected_version: VersionToken | None,
        *,
        ctx: Context[Any, Any],
    ) -> CallToolResult:
        return call(
            "write_file",
            ctx,
            {
                "scope": scope,
                "area": area,
                "name": name,
                "content": content,
                "description": description,
                "aliases": aliases,
                "expected_version": expected_version,
            },
            lambda tools: tools.write_file(
                scope, area, name, content, description, aliases, expected_version
            ),
        )

    def append_line(
        scope: str,
        area: str,
        name: str,
        line: str,
        expected_version: VersionToken,
        aliases: Sequence[str] | None = None,
        description: str | None = None,
        *,
        ctx: Context[Any, Any],
    ) -> CallToolResult:
        return call(
            "append_line",
            ctx,
            {
                "scope": scope,
                "area": area,
                "name": name,
                "line": line,
                "expected_version": expected_version,
                "aliases": aliases,
                "description": description,
            },
            lambda tools: tools.append_line(
                scope, area, name, line, expected_version, aliases, description
            ),
        )

    def replace_fact(
        scope: str,
        area: str,
        name: str,
        old_string: str,
        new_string: str,
        expected_version: VersionToken,
        aliases: Sequence[str] | None = None,
        description: str | None = None,
        *,
        ctx: Context[Any, Any],
    ) -> CallToolResult:
        return call(
            "replace_fact",
            ctx,
            {
                "scope": scope,
                "area": area,
                "name": name,
                "old_string": old_string,
                "new_string": new_string,
                "expected_version": expected_version,
                "aliases": aliases,
                "description": description,
            },
            lambda tools: tools.replace_fact(
                scope, area, name, old_string, new_string, expected_version, aliases, description
            ),
        )

    def delete_file(
        scope: str, area: str, name: str, expected_version: VersionToken, *, ctx: Context[Any, Any]
    ) -> CallToolResult:
        return call(
            "delete_file",
            ctx,
            {"scope": scope, "area": area, "name": name, "expected_version": expected_version},
            lambda tools: tools.delete_file(scope, area, name, expected_version),
        )

    wrappers: dict[str, Callable[..., CallToolResult]] = {
        "get_memory_index": get_memory_index,
        "read_file": read_file,
        "list_prefix": list_prefix,
        "write_file": write_file,
        "append_line": append_line,
        "replace_fact": replace_fact,
        "delete_file": delete_file,
    }
    for name in TOOL_NAMES:
        server.add_tool(wrappers[name], name=names[name], description=descriptions[name])

    instructions = server.instructions
    if instructions is None or prompt not in instructions:
        _log.warning(
            "server instructions do not include the memory prompt; "
            "pass memory_instructions(slots) as instructions"
        )


def build_server[C](
    *,
    slots: PromptSlots,
    client: TransportClient,
    resolver: IdentityResolver[C],
    policy: ScopePolicy,
    credentials_from_context: Callable[[Context[Any, Any]], C],
    source: str,
    product: str | None = None,
    tool_prefix: str | None = None,
    on_call: Callable[[ToolCallRecord], None] | None = None,
    name: str = "wenchang",
) -> MCPServer:
    """Return an MCPServer with the memory prompt as instructions and the memory tools.

    See register_memory_tools for the arguments and the threading contract;
    serve it over stdio with server.run("stdio").
    """
    _validate(
        client=client,
        resolver=resolver,
        policy=policy,
        credentials_from_context=credentials_from_context,
        source=source,
        product=product,
        tool_prefix=tool_prefix,
        on_call=on_call,
    )
    prompt = memory_instructions(slots)
    server = MCPServer(name, instructions=prompt, version=wenchang.__version__)
    register_memory_tools(
        server,
        prompt=prompt,
        client=client,
        resolver=resolver,
        policy=policy,
        credentials_from_context=credentials_from_context,
        source=source,
        product=product,
        tool_prefix=tool_prefix,
        on_call=on_call,
    )
    return server
