# Integrate: a new MCP server

`wenchang.mcp.build_server(...)` returns a new mcp 2.x `MCPServer` that carries the memory prompt as its `instructions`, the seven memory tools, and the prompt resource `wenchang://memory-prompt`. You run it with `server.run(...)`. [Quickstart](quickstart.md) builds one end to end for Claude Code; this page covers every argument and both transports.

<!--html-->
<div class="callout callout-warn"><strong>Compatibility: mcp 2.x <code>MCPServer</code> only.</strong> The <code>mcp</code> extra installs <code>mcp&gt;=2.2,&lt;3</code>, and the adapter targets <code>mcp.server.mcpserver.MCPServer</code>. FastMCP servers and mcp 1.x servers do not work: with mcp 1.x installed, importing <code>wenchang.mcp</code> raises <code>ImportError</code>, and <code>register_memory_tools</code> raises <code>TypeError("server must be an MCPServer, not ...")</code> for any other server type. For another framework, see <a href="integrate-without-mcp.html">Integrate without MCP</a>.</div>
<!--/html-->
<!--md-->
> **Compatibility: mcp 2.x `MCPServer` only.** The `mcp` extra installs `mcp>=2.2,<3`, and the adapter targets `mcp.server.mcpserver.MCPServer`. FastMCP servers and mcp 1.x servers do not work: with mcp 1.x installed, importing `wenchang.mcp` raises `ImportError`, and `register_memory_tools` raises `TypeError("server must be an MCPServer, not ...")` for any other server type. For another framework, see [Integrate without MCP](integrate-without-mcp.md).
<!--/md-->

Install with the extra: `pip install "wenchang[mcp] @ git+https://github.com/msiebert/wenchang"`.

## Arguments {#arguments}

Every argument is keyword-only. `build_server` checks them all before it creates the server, and raises `TypeError` or `ValueError` for a bad one.

| Argument | Required | What it does |
| --- | --- | --- |
| `slots` | yes | A `PromptSlots`. The server's `instructions` are `build_memory_prompt(slots)`. See [Customizing the prompts](prompts.md). |
| `client` | yes | A `TransportClient`, normally `InProcessClient(MemoryStore(...))`. Tool calls run concurrently on worker threads and share it. See [Threads](integrate-without-mcp.md#threads) for what is safe to share. |
| `resolver` | yes | Your `IdentityResolver`. On this path it runs on every tool call. Its `resolve` must be a plain synchronous method. See [Identity](identity.md). |
| `policy` | yes | A `ScopePolicy`: the roles that may write each scope. |
| `credentials_from_context` | yes | A plain (non-async) function that takes the MCP request `Context` and returns the raw credentials your resolver verifies. See [Credentials](#credentials). |
| `source` | yes | The surface name added to each written file's `sources` metadata. Non-empty. |
| `product` | no | Your product's name, put in the first line of each tool description. One non-empty line. |
| `tool_prefix` | no | Registers each tool as `{tool_prefix}_{name}`. 1 to 64 letters, digits, `_` or `-`, starting and ending with a letter or digit. |
| `on_call` | no | A plain function called with a `ToolCallRecord` after every tool call. See [Observing calls](#on-call). |
| `name` | no | The server name. Default `"wenchang"`. |

The server's version is the installed wenchang version. [Names on the tools](prompts.md#naming) has more on `product`, `tool_prefix`, and `source`.

## Credentials {#credentials}

Every tool call runs `credentials_from_context(ctx)`, passes the result to your resolver, and binds that caller's own tools. `ctx.headers` holds the request headers on HTTP and is `None` on stdio. Return the raw value and leave verification to the resolver. If the function raises, the call fails with a permanent `ResolverFailureError`, and only the exception's type is logged, since its message may carry the credential.

## Transports {#transports}

- **stdio.** `server.run("stdio")`. The client starts one server process per session, so identity usually comes from the process environment: a variable holding a token, or the grants themselves for a single-developer setup as in [Quickstart](quickstart.md#server). Return it from `credentials_from_context` as `os.environ.get("MEMORY_TOKEN")` and let the resolver verify it.
- **Streamable HTTP.** `server.run("streamable-http", host="0.0.0.0", port=8000)` serves the MCP endpoint at `/mcp` (mcp's defaults are host `127.0.0.1` and port 8000). Put TLS in front of it. Each request carries its own credentials in headers, so one process serves many callers. The MCP SDK also has its own auth options on `MCPServer` (`auth`, `token_verifier`) if you want requests rejected before they reach wenchang; see the `mcp` documentation. [Identity](identity.md#example) has a complete multi-tenant HTTP server, which has been run against fake-gcs-server and driven by mcp's streamable-HTTP client.

## Observing calls {#on-call}

`on_call` receives a `wenchang.observer.ToolCallRecord` after every tool call (`wenchang.mcp` re-exports it). On this path:

- `tool` is the registered name, prefix included.
- `request_id` is the MCP request's ID, for correlating records that arrive in completion order.
- `duration_s` covers reading credentials, binding, the tool, and rendering.
- It runs on worker threads, so it must be thread-safe and fast.

Calls MCP rejects while validating arguments never produce a record. An exception the observer raises is logged at ERROR and swallowed. The [reference](reference.md#telemetry) lists every field.

## Next {#next}

- [Identity and multi-tenant auth](identity.md): a resolver for real users.
- [Integrate: an existing mcp 2.x server](integrate-existing-server.md): the same tools on a server you already run.
