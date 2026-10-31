# Integrate: an existing mcp 2.x server

`build_server` creates a new server. To add memory to an `MCPServer` you already run, with your own tools, auth, and middleware, call `wenchang.mcp.register_memory_tools(server, ...)`. It adds the seven memory tools and the `wenchang://memory-prompt` resource to that server.

> **Compatibility: mcp 2.x `MCPServer` only.** The `mcp` extra installs `mcp>=2.2,<3`, and the adapter targets `mcp.server.mcpserver.MCPServer`. FastMCP servers and mcp 1.x servers do not work: with mcp 1.x installed, importing `wenchang.mcp` raises `ImportError`, and `register_memory_tools` raises `TypeError("server must be an MCPServer, not ...")` for any other server type, before it registers anything. For another framework, see [Integrate without MCP](integrate-without-mcp.md).

Install with the extra: `pip install "wenchang[mcp] @ git+https://github.com/msiebert/wenchang"`.

## Register the tools

`register_memory_tools` takes the server, then keyword arguments: `prompt`, `client`, `resolver`, `policy`, `credentials_from_context`, `source`, and optionally `product`, `tool_prefix`, and `on_call`. They mean the same as for [`build_server`](integrate-new-server.md#arguments), except that you pass the prompt text instead of the slots.

```python
import logging

from mcp.server.mcpserver import Context, MCPServer

from wenchang.core import MemoryStore
from wenchang.identity import Identity, SandboxResolver, ScopeGrant
from wenchang.mcp import ToolCallRecord, memory_instructions, register_memory_tools
from wenchang.prompts import PromptSlots
from wenchang.scope import ScopePolicy
from wenchang.storage.memory import InMemoryStorage
from wenchang.transport import InProcessClient

log = logging.getLogger("inkwell.calls")

slots = PromptSlots(
    purpose="You have persistent memory of your work helping an author write a novel.",
    scope_guidance=(
        "There is one scope, user, and it is private to the author you are talking with."
    ),
    seed_areas="- user: preferences, workflows, research\n\nEvery scope also has a `system/` area.",
)
identity = Identity(grants={"user": ScopeGrant("u-tianlong", "owner")})


def credentials_from_context(ctx: Context) -> str | None:
    # Over HTTP, return the raw credential and let your resolver verify it.
    # ctx.headers is None on stdio.
    return (ctx.headers or {}).get("authorization")


def on_call(record: ToolCallRecord) -> None:
    # Runs on worker threads after every call; keep it fast and thread-safe.
    log.info("%s error=%s %.3fs", record.tool, record.is_error, record.duration_s)


prompt = memory_instructions(slots)

# Your existing server, with your own tools and middleware.
server = MCPServer("hanlin-tools", instructions=prompt)

register_memory_tools(
    server,
    prompt=prompt,
    client=InProcessClient(MemoryStore(InMemoryStorage())),
    resolver=SandboxResolver(identity),
    policy=ScopePolicy({}),
    credentials_from_context=credentials_from_context,
    source="hanlin-tools",
    product="Inkwell",
    tool_prefix="inkwell",  # tools are registered as inkwell_read_file, inkwell_write_file, ...
    on_call=on_call,
)
```

## The prompt

The agent needs the memory prompt as well as the tools. `memory_instructions(slots)` returns it. Pass the same text as the server's `instructions` and as `prompt`; `prompt` is what the `wenchang://memory-prompt` resource serves, for clients that ignore `instructions`. If your server already has instructions, include the memory prompt in them; [Customizing the prompts](prompts.md#fixed) shows how to append sections of your own.

After registering, `register_memory_tools` checks the server's `instructions`. If they do not contain `prompt`, it logs a warning on the `wenchang.mcp` logger and registers anyway.

## Name collisions

`MCPServer` only logs a duplicate tool or resource, so `register_memory_tools` checks first. If any memory tool name or the resource URI is already registered on the server, it raises `ValueError("cannot register memory tools: already registered on the server: ...")`, naming each collision, and registers nothing. Set `tool_prefix` to register the tools as `{tool_prefix}_read_file` and so on. The resource URI has no prefix, so a server holds one memory prompt resource.

Any invalid argument also raises before anything is registered.

## Credentials and observing calls

Each tool call reads credentials with your `credentials_from_context`, resolves them, and binds that caller's tools, exactly as on a [new server](integrate-new-server.md#credentials). Your own auth middleware can reject a request before it reaches wenchang; whatever reaches `credentials_from_context` still goes through your resolver. Tool calls run concurrently on worker threads, so `client` must be thread-safe.

`on_call` behaves as on a new server: `tool` is the registered name, prefix included, `request_id` is the MCP request's ID, and the observer runs on worker threads. See [Observing calls](integrate-new-server.md#on-call) and the [field reference](reference.md#telemetry).

## Next

- [Identity and multi-tenant auth](identity.md): the resolver behind `credentials_from_context`.
- [Integrate without MCP](integrate-without-mcp.md): the same tools in another framework.

---

HTML version: <https://msiebert.github.io/wenchang/integrate-existing-server.html>
