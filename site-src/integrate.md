# Choose an integration path

The memory tools are plain Python methods. There are three ways to put them in front of an agent. All three share the same store, identity resolver, scope policy, and prompt; they differ only in who registers the tools and how a call reaches them.

| Path | Use it when | Entry point |
| --- | --- | --- |
| [A new MCP server](integrate-new-server.md) | You want a standalone memory server for an MCP client such as Claude Code, over stdio or HTTP. | `wenchang.mcp.build_server` |
| [An existing MCP server](integrate-existing-server.md) | You already run an mcp 2.x `MCPServer` with your own tools, auth, and middleware, and want memory on it. | `wenchang.mcp.register_memory_tools` |
| [Without MCP](integrate-without-mcp.md) | Your agent uses another tool framework, or calls a model API directly with its own tool loop. | `wenchang.tools.bind_tools` |

The MCP paths need the `mcp` extra and work only with mcp 2.x `MCPServer`. The path without MCP needs only the base package.

Whichever path you take:

- [Concepts](concepts.md) explains paths, scopes, files, versions, and limits.
- [Identity and multi-tenant auth](identity.md) explains how a caller becomes a set of scopes.
- [Customizing the prompts](prompts.md) explains the prompt the agent needs alongside the tools.
- [Storage and operations](storage.md) covers the bucket, costs, caching, and erasure.
