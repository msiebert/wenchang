# Spec Review: AIE-1060: Host-mounting smoke test (MCP server adapter)

## What & why

ADR 0022 deferred the server object that Section 7 of the Notion spec
describes to this issue. This issue builds it.

- **Server.** `wenchang.mcp.build_server(...)` returns an MCP server behind
  an optional `mcp` extra.
- **Tools.** Each of the seven tools is a thin wrapper. On every call it
  reads the caller's credentials from the request, binds that caller's own
  `MemoryTools`, forwards the call, and returns `render_result` or
  `render_error` output.
- **Descriptions.** Each tool is registered with an explicit name and the
  description from a new `wenchang.tools.tool_descriptions(product)`.
- **Prompt.** The assembled memory prompt goes out as the server's
  `instructions` and as a resource.
- **Smoke test.** A real MCP client checks names, descriptions, schemas,
  instructions, and the resource.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| US1 | `tool_descriptions(product)` | called | Same text as `MemoryTools.descriptions()`, which now delegates to it. A missing docstring (`-OO`) gives `""` |
| US2 | `pyproject.toml` / a fresh interpreter | inspect or import | `mcp` is only an extra plus a dev dependency. The core never imports `mcp`. `import wenchang.mcp` without it gives an `ImportError` naming `wenchang[mcp]` |
| US3 | `build_server(...)` | client `list_tools()` | Seven names, prefixed when `tool_prefix` is set. Each description equals `tool_descriptions(product)[name]`. Each schema's properties and required set mirror the `MemoryTools` method. A bad prefix fails at build, and so does an empty or missing description, including a real `python -OO` run |
| US4 | the server | connect, legacy and discover | `instructions == build_memory_prompt(slots)`. Resource `wenchang://memory-prompt` serves the same text. The prompt is built once |
| US5 | two users | tool calls | Each call resolves its own identity, so alice's files are invisible to bob. Results and errors match `render_result` and `render_error` with `is_error` set. Credential-extraction failure is a permanent `ResolverFailureError` that leaks nothing. Off-contract errors are logged and shown as `internal error` |
| US6 | stdio subprocess | real client | Tools, instructions, and a round trip work |
| US7 | docs | read | ADR 0027, notes in ADRs 0022 and 0026, ARCHITECTURE, README, glossary |

Full Given/When/Then is in [spec.md](spec.md), 46 numbered criteria.

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| Official `mcp>=2.2,<3`, `MCPServer` | `mcp<2` `FastMCP`; standalone `fastmcp` | 2.x renamed FastMCP to `MCPServer`, and 1.x is the legacy protocol line. The official package is the lighter dependency |
| Explicit `add_tool(name=, description=)` | setting `__doc__` | 2.x supports it directly. Wrapper docstrings play no part |
| Bind per tool call through the caller-supplied `credentials_from_context(ctx) -> C` | cache keyed by MCP session id; one shared binding | The 2026-07-28 protocol is stateless, and `ctx.session` differs on every request. A per-call binding can never share an identity |
| Hand-written wrappers mirroring the method signatures, plus keyword-only `ctx` | generated signatures | Readable and pyright-checked. A schema test catches drift |
| Prefix `f"{prefix}_{name}"`, prefix `[A-Za-z0-9][A-Za-z0-9_-]*` | dotted or slash separators | Stays inside MCP's tool-name character set |
| Results as `CallToolResult`, JSON text plus `structured_content`, with `is_error` for failures | plain dict return | The client can tell failures apart, and no output schema is pinned |
| Prompt in `instructions` plus resource `wenchang://memory-prompt`, built once | only `instructions` | This is what the issue asks for. Some clients drop `instructions` |
| `tool_descriptions` returns `""` for a stripped docstring, and `build_server` raises | raise inside `tool_descriptions` | One clear startup error naming every affected tool |

## Files/modules to be touched

- `pyproject.toml`, `uv.lock`
- `src/wenchang/tools.py`, `src/wenchang/mcp.py` (new)
- `tests/test_tools_descriptions.py` (appended), `tests/test_mcp_packaging.py`, `tests/test_mcp_server.py`, `tests/test_mcp_stdio.py`, `tests/mcp_stdio_server.py`
- `docs/adr/0027-mcp-host-adapter.md` (new), ADR 0022 and 0026 notes, `ARCHITECTURE.md`, `README.md`, `docs/product/glossary.md`

## Open questions / assumptions

- **"Session credentials from the request context".** The mechanism is a
  caller-supplied `credentials_from_context(ctx)`, called on every tool
  call, with no cache. This is an assumption the orchestrator should
  confirm. It means the resolver runs once per call, and resolvers may
  cache internally.
- **gRPC client.** The issue's first paragraph mentions a minimal local
  gRPC client. I read the 2026-10-08 text ("drives a real MCP client")
  as superseding it, so no gRPC code is planned. Confirm.
- **`mcp` 2.x rather than "FastMCP".** `MCPServer` is the renamed FastMCP.
  Pinning 1.x would keep the literal name but use the legacy protocol line.
- **No mount.** `MCPServer` has no mount or compose API. The "mount" is
  `build_server` returning a server, with the prefix applied at
  registration.
- With a prefix, descriptions still mention unprefixed tool names (for
  example `list_prefix(scope, area)`), because they must equal
  `tool_descriptions(product)[name]`.

## Risks

- `mcp` 2.x moves fast: 2.3.0 is six days old. The `<3` bound and the
  lockfile contain this risk. The smoke test fails on schema or
  description drift.
- Running the resolver per call adds latency for a remote resolver.
  ADR 0027 records this.
