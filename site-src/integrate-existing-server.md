# Integrate: an existing mcp 2.x server

`build_server` creates a new server. To add memory to an `MCPServer` you already run, with your own tools, auth, and middleware, call `wenchang.mcp.register_memory_tools(server, ...)`. It adds the seven memory tools and the `wenchang://memory-prompt` resource to that server.

<!--html-->
<div class="callout callout-warn"><strong>Compatibility: mcp 2.x <code>MCPServer</code> only.</strong> The <code>mcp</code> extra installs <code>mcp&gt;=2.2,&lt;3</code>, and the adapter targets <code>mcp.server.mcpserver.MCPServer</code>. FastMCP servers and mcp 1.x servers do not work: with mcp 1.x installed, importing <code>wenchang.mcp</code> raises <code>ImportError</code>, and <code>register_memory_tools</code> raises <code>TypeError("server must be an MCPServer, not ...")</code> for any other server type, before it registers anything. For another framework, see <a href="integrate-without-mcp.html">Integrate without MCP</a>.</div>
<!--/html-->
<!--md-->
> **Compatibility: mcp 2.x `MCPServer` only.** The `mcp` extra installs `mcp>=2.2,<3`, and the adapter targets `mcp.server.mcpserver.MCPServer`. FastMCP servers and mcp 1.x servers do not work: with mcp 1.x installed, importing `wenchang.mcp` raises `ImportError`, and `register_memory_tools` raises `TypeError("server must be an MCPServer, not ...")` for any other server type, before it registers anything. For another framework, see [Integrate without MCP](integrate-without-mcp.md).
<!--/md-->

Install with the extra: `pip install "wenchang[mcp] @ git+https://github.com/msiebert/wenchang"`.

## Register the tools {#register}

`register_memory_tools` takes the server, then keyword arguments: `prompt`, `client`, `resolver`, `policy`, `credentials_from_context`, `source`, and optionally `product`, `tool_prefix`, and `on_call`. They mean the same as for [`build_server`](integrate-new-server.md#arguments), except that you pass the prompt text instead of the slots.

<!--include python custom_embed.py-->

## The prompt {#prompt}

The agent needs the memory prompt as well as the tools. `memory_instructions(slots)` returns it. Pass the same text as the server's `instructions` and as `prompt`; `prompt` is what the `wenchang://memory-prompt` resource serves, for clients that ignore `instructions`. If your server already has instructions, include the memory prompt in them; [Customizing the prompts](prompts.md#fixed) shows how to append sections of your own.

After registering, `register_memory_tools` checks the server's `instructions`. If they do not contain `prompt`, it logs a warning on the `wenchang.mcp` logger and registers anyway.

## Name collisions {#collisions}

`MCPServer` only logs a duplicate tool or resource, so `register_memory_tools` checks first. If any memory tool name or the resource URI is already registered on the server, it raises `ValueError("cannot register memory tools: already registered on the server: ...")`, naming each collision, and registers nothing. Set `tool_prefix` to register the tools as `{tool_prefix}_read_file` and so on. The resource URI has no prefix, so a server holds one memory prompt resource.

Any invalid argument also raises before anything is registered.

## Credentials and observing calls {#calls}

Each tool call reads credentials with your `credentials_from_context`, resolves them, and binds that caller's tools, exactly as on a [new server](integrate-new-server.md#credentials). Your own auth middleware can reject a request before it reaches wenchang; whatever reaches `credentials_from_context` still goes through your resolver. Tool calls run concurrently on worker threads and share `client`; see [Threads](integrate-without-mcp.md#threads) for what is safe to share.

`on_call` behaves as on a new server: `tool` is the registered name, prefix included, `request_id` is the MCP request's ID, and the observer runs on worker threads. See [Observing calls](integrate-new-server.md#on-call) and the [field reference](reference.md#telemetry).

## Next {#next}

- [Identity and multi-tenant auth](identity.md): the resolver behind `credentials_from_context`.
- [Integrate without MCP](integrate-without-mcp.md): the same tools in another framework.
