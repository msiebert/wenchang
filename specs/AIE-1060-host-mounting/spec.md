# Feature Specification: Host-mounting smoke test (MCP server adapter)

**Linear issue**: AIE-1060 | **Branch**: `AIE-1060-host-mounting` | **Date**: 2026-10-08

## Problem

Section 7 of the Notion spec says the library "ships as its own server
instance with the memory tools decorated onto it", which a host picks up
"with no manual wiring", optionally under a namespace prefix. ADR 0022
deferred that server to this issue. The library has `MemoryTools`,
`bind_tools`, `render_result`, `render_error`, `MemoryTools.descriptions()`
(ADR 0026), and `build_memory_prompt` (ADR 0025), but no server.

This issue adds:

1. A module-level `wenchang.tools.tool_descriptions(product=None)`, the
   session-independent source of the tool descriptions, which
   `MemoryTools.descriptions()` delegates to.
2. An MCP server adapter, `wenchang.mcp`, behind an optional `mcp` extra.
   Its seven tools are thin wrappers registered with explicit names and
   descriptions. Each call takes credentials from the request context, binds
   that caller's own `MemoryTools`, forwards the call, and returns rendered
   output.
3. Prompt delivery: the assembled prompt goes out as the server's
   `instructions` and as an MCP resource.
4. A smoke test that drives a real MCP client against the server.

## User stories and acceptance criteria

`REFERENCE_SLOTS` is `tests/prompts_reference_adopter.py`'s fixture. "The
server" means `build_server(...)` over an `InProcessClient(MemoryStore(
InMemoryStorage()))`. "A client" means `mcp.client.Client(server)` (in-memory
transport) unless a criterion says stdio.

### US1: `tool_descriptions` is the session-independent description source

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1.1 | `wenchang.tools` | import | `tool_descriptions` is in `__all__` and has the signature `(product: str \| None = None) -> Mapping[str, str]` |
| 1.2 | no product | `tool_descriptions()` | returns a fresh read-only `types.MappingProxyType` with keys `list(TOOL_NAMES)` in order. Each value equals `inspect.cleandoc(getattr(MemoryTools, name).__doc__)` |
| 1.3 | product `P` in `("Mixpanel", "Acme Analytics", "A{b}c")` | `tool_descriptions(P)` | equals `dict(MemoryTools(..., product=P).descriptions())`. With `"Mixpanel"`, each first line equals the pinned first line in ADR 0026 decision 4 |
| 1.4 | a product that `MemoryTools` rejects (non-`str` real type; empty or whitespace-only; any `str.splitlines` boundary; a lone surrogate) | `tool_descriptions(product)` | raises the same exception type and message that `MemoryTools(..., product=product)` raises |
| 1.5 | `wenchang.tools.tool_descriptions` monkeypatched to a recording stub | `MemoryTools(..., product="X").descriptions()` | the stub is called once with `"X"` and its return value is returned unchanged |
| 1.6 | one tool's docstring set to `None`, as `python -OO` does | `tool_descriptions()` and `tool_descriptions("Mixpanel")` | that tool's value is `""` in both. No exception is raised. The other values are unchanged |
| 1.7 | the existing `tests/test_tools_descriptions.py` | run | passes unchanged |

### US2: The `mcp` extra is optional and the core never imports it

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 2.1 | `pyproject.toml` | parse with `tomllib` | `[project.optional-dependencies].mcp` is exactly one requirement on `mcp` with a lower bound `>=2.2` and an upper bound `<3`. `[project].dependencies` names no `mcp`. The `dev` dependency group includes `mcp` |
| 2.2 | a fresh interpreter | import `wenchang`, `wenchang.core`, `wenchang.tools`, `wenchang.transport`, `wenchang.identity`, `wenchang.scope`, `wenchang.prompts`, `wenchang.storage.memory`, `wenchang.testing` | no module named `mcp` or `mcp.*` is in `sys.modules` |
| 2.3 | a fresh interpreter where `import mcp` fails (`sys.modules["mcp"] = None` before import) | `import wenchang.mcp` | raises `ImportError` whose message contains `wenchang[mcp]` |

### US3: `build_server` registers the seven tools with no manual wiring

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 3.1 | `wenchang.mcp` | import | `__all__` is exactly `["PROMPT_RESOURCE_URI", "build_server"]`. Every `build_server` parameter is keyword-only |
| 3.2 | the server with no `tool_prefix` | a client calls `list_tools()` | the tool names are exactly the set of `TOOL_NAMES` |
| 3.3 | the server with `tool_prefix="mixpanel"` | `list_tools()` | the tool names are exactly `{"mixpanel_" + n for n in TOOL_NAMES}` |
| 3.4 | the server with product `None`, and again with `"Mixpanel"`, each with and without a prefix | `list_tools()` | each tool's `description` equals `tool_descriptions(product)[n]`, where `n` is the unprefixed name |
| 3.5 | the server with product `"Mixpanel"` | `list_tools()` | each description's first line contains `"Mixpanel"` |
| 3.6 | the server | `list_tools()` | for each tool, `set(input_schema["properties"])` equals the parameters of the `MemoryTools` method of that name, minus `self`. `set(input_schema.get("required", []))` equals the subset of those parameters with no default. No schema has a `ctx` property |
| 3.7 | the server | `list_tools()` | the schemas pin these types: `scope`, `area`, `name`, `content`, `line`, `old_string`, and `new_string` are `{"type": "string"}`. `aliases` on `write_file` is an array of strings. `aliases` on `append_line` and `replace_fact` is an array of strings or null. `expected_version` on `write_file` is a string or null |
| 3.8 | `tool_prefix` of `""`, `"has space"`, `"a/b"`, `"_lead"`, or `"-lead"` | `build_server(...)` | raises `ValueError("tool_prefix must match [A-Za-z0-9][A-Za-z0-9_-]*")` |
| 3.9 | `tool_prefix` whose real type is not `str` (`1`, `b"x"`) | `build_server(...)` | raises `TypeError("tool_prefix must be a str or None, not <type>")` |
| 3.10 | a product that `tool_descriptions` rejects | `build_server(...)` | raises the same exception that `tool_descriptions(product)` raises |
| 3.11 | `wenchang.mcp.tool_descriptions` monkeypatched to return `""` for `read_file` and `"  \n"` for `delete_file` | `build_server(...)` | raises `RuntimeError`. The message names `read_file` and `delete_file` and mentions `python -OO`. Its exact form is in plan.md |
| 3.12 | `wenchang.mcp.tool_descriptions` monkeypatched to omit `write_file` | `build_server(...)` | raises `RuntimeError` naming `write_file` |
| 3.13 | a subprocess under `python -OO` | build the server with `REFERENCE_SLOTS` | the process exits non-zero, and stderr contains the US3.11 `RuntimeError` message |

### US4: The prompt is delivered as `instructions` and as a resource

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 4.1 | the server with `REFERENCE_SLOTS` | a client connects with `mode="legacy"` (the `initialize` handshake) | `client.instructions == build_memory_prompt(REFERENCE_SLOTS)`. This is `InitializeResult.instructions` |
| 4.2 | the same server | a client connects with the default mode (`server/discover`) | `client.instructions == build_memory_prompt(REFERENCE_SLOTS)` |
| 4.3 | the server | `list_resources()` | exactly one resource has `uri == PROMPT_RESOURCE_URI` (`"wenchang://memory-prompt"`) and `mime_type == "text/markdown"` |
| 4.4 | the server | `read_resource(PROMPT_RESOURCE_URI)` | returns exactly one text content, and its `text == build_memory_prompt(REFERENCE_SLOTS)` |
| 4.5 | `wenchang.mcp.build_memory_prompt` wrapped with a call counter | build the server, connect two clients, call `read_resource` twice from each | the counter is 1 |
| 4.6 | `slots` whose real type is not `PromptSlots` | `build_server(...)` | raises `TypeError` from `build_memory_prompt` |

### US5: Each call binds the caller's own `MemoryTools` and forwards it

The tests' `credentials_from_context` reads `ctx.request_context.meta["test/user"]`
and the test resolver maps `"alice"` and `"bob"` to identities with
different `user` entity IDs.

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 5.1 | the server | `write_file` and then `read_file` through the client, as alice | each result has `is_error` false. Each `structured_content` equals `render_result(direct.read_file(...))`, where `direct` is a `MemoryTools` bound to alice over the same transport client and the read happens after the server call. `content` is one text item whose JSON parses to `structured_content` |
| 5.2 | the server | `delete_file` succeeds | `structured_content == {"ok": True}` |
| 5.3 | alice has written `user/notes/today` | bob calls `read_file("user", "notes", "today")` | `is_error` is true and `structured_content["error"] == "NotFoundError"`. The stored path is under alice's entity ID |
| 5.4 | a counting resolver | N tool calls, as alice and as bob in turn | the resolver ran exactly N times, each with that call's credentials. No `MemoryTools` is reused across calls |
| 5.5 | the server | a write to the `system` area | `is_error` is true. `structured_content` equals `render_error` of the same `RestrictedScopeError`, with `category == "permanent"` |
| 5.6 | the server | `read_file` of a missing file | `is_error` is true, `category == "recoverable"`, and `error == "NotFoundError"` |
| 5.7 | `credentials_from_context` raises `RuntimeError("secret-token-123")` | any tool call | `is_error` is true, `error == "ResolverFailureError"`, and `category == "permanent"`. The rendered text does not contain `secret-token-123`. The resolver was not called |
| 5.8 | a resolver returning `ResolutionFailure("no such user")` | any tool call | `is_error` is true, `error == "ResolverFailureError"`, and the message contains `"no such user"` |
| 5.9 | a transport client whose `read_file` raises `KeyError("internal-detail")` | `read_file` through the server | `is_error` is true, `category == "internal"`, and `message == "internal error"`. A record is logged on logger `wenchang.mcp` at `ERROR` with `exc_info` |
| 5.10 | `source="mcp-smoke"` | `write_file` through the server | the written file's `sources` contain `"mcp-smoke"` |
| 5.11 | `tool_prefix="mixpanel"` | call `mixpanel_read_file` | forwards to `read_file` like the unprefixed server |

### US6: The server runs over stdio

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 6.1 | `tests/mcp_stdio_server.py`, a script that builds the server over an in-memory store with `REFERENCE_SLOTS` and a `SandboxResolver` and calls `server.run("stdio")` | a client launches it with `StdioServerParameters` | `list_tools()` returns the seven names. `client.instructions == build_memory_prompt(REFERENCE_SLOTS)`. A `write_file` then `read_file` round trip succeeds |

### US7: Documentation

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 7.1 | ADR 0027 | read | records these decisions: the `mcp` 2.x `MCPServer` choice; explicit `name=` and `description=`; the per-call binding and `credentials_from_context`; the prefix rule; `instructions` plus the resource; the startup check for missing descriptions; `tool_descriptions` as public API; and the rejected alternatives |
| 7.2 | ADRs 0022 and 0026 | read | each has a dated note pointing to ADR 0027. ADR 0022 decision 12 says the server now exists. ADR 0026 decisions 5 and 6 point to `tool_descriptions` and `build_server` |
| 7.3 | ARCHITECTURE.md | read | it has a new `mcp` module entry and a node and edge in the module diagram. The `tools` entry lists `tool_descriptions`. Dependencies note the optional extra |
| 7.4 | README | read | a "Serving over MCP" section shows `build_server(...)` with `credentials_from_context` and `tool_prefix`, and running it over stdio |
| 7.5 | `docs/product/glossary.md` | read | it has a "Host adapter" entry |

## Out of scope

- A production gRPC transport or a gRPC client. The issue's first paragraph
  mentions a minimal local gRPC client. The 2026-10-08 requirements make a
  real MCP client the smoke-test driver. See the assumptions in
  review-spec.md.
- Mounting into a parent server. `mcp` 2.x `MCPServer` has no mount or
  compose API. The prefix is applied at registration instead (ADR 0027).
- Authentication middleware, HTTP deployment, or caching resolved
  identities.
- Changing tool docstrings, `TOOL_NAMES`, or the prompt text.
