# Feature Specification: Host-mounting smoke test (MCP server adapter)

**Linear issue**: AIE-1060 | **Branch**: `AIE-1060-host-mounting` | **Date**: 2026-10-08

## Problem

Section 7 of the Notion spec says the library "ships as its own server
instance with the memory tools decorated onto it", which a host picks up
"with no manual wiring", optionally under a namespace prefix. ADR 0022
deferred that server to this issue. The library already has `MemoryTools`,
`bind_tools`, `render_result`, `render_error`, `MemoryTools.descriptions()`
(ADR 0026), and `build_memory_prompt` (ADR 0025). It has no server.

This issue adds five things:

1. **Description source.** A module-level
   `wenchang.tools.tool_descriptions(product=None)` is the session-independent
   source of the tool descriptions. `MemoryTools.descriptions()` delegates to
   it.
2. **MCP adapter.** The adapter `wenchang.mcp` sits behind an optional `mcp`
   extra.
   - `register_memory_tools(server, ...)` adds the seven tools and the
     prompt resource to an `MCPServer` the adopter supplies.
   - `build_server(...)` is a convenience that also constructs the server,
     with the prompt as its `instructions`.
   - Each tool is a thin wrapper. Every call takes credentials from the
     request context, binds that caller's own `MemoryTools`, forwards the
     call, and returns rendered output.
   - An optional `on_call` observer sees every wrapper call.
3. **Prompt delivery.** The assembled prompt is the server's `instructions`
   and is also served as an MCP resource.
4. **Thread-safe in-memory storage.** `InMemoryStorage` becomes
   thread-safe, because MCPServer runs tool calls concurrently on worker
   threads.
5. **Smoke test.** A smoke test drives a real MCP client against the server.

## User stories and acceptance criteria

These terms are used throughout:

- **`REFERENCE_SLOTS`** is the fixture in `tests/prompts_reference_adopter.py`.
- **"The server"** means `build_server(...)` over an
  `InProcessClient(MemoryStore(InMemoryStorage()))`.
- **"A client"** means `mcp.client.Client(server)` over the in-memory
  transport, unless a criterion says stdio.
- **Credentials.** The tests' `credentials_from_context` reads
  `ctx.request_context.meta["test/user"]`. The test resolver maps `"alice"`
  and `"bob"` to identities with different `user` entity IDs.

### US1: `tool_descriptions` is the session-independent description source

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1.1 | `wenchang.tools` | import | `tool_descriptions` is in `__all__` with the signature `(product: str \| None = None) -> Mapping[str, str]` |
| 1.2 | no product | `tool_descriptions()` | a fresh read-only `types.MappingProxyType`, keys `list(TOOL_NAMES)` in order; each value equals `inspect.cleandoc(getattr(MemoryTools, name).__doc__)` |
| 1.3 | product `P` in `("Mixpanel", "Acme Analytics", "A{b}c")` | `tool_descriptions(P)` | each value equals an independently computed expectation. The first line is `PINNED_FIRST_LINES[name].replace("Mixpanel", P)`, and every later line is the cleandoc'd docstring's own. The expectation is not computed through `descriptions()` |
| 1.4 | a product `MemoryTools` rejects: a non-`str` real type; empty or whitespace-only; containing any `str.splitlines` boundary; a lone surrogate | `tool_descriptions(product)` | raises the same exception type and message as `MemoryTools(..., product=product)` |
| 1.5 | `wenchang.tools.tool_descriptions` monkeypatched to a recording stub | `MemoryTools(..., product="X").descriptions()` | the stub is called once with `"X"`; its return value is returned unchanged |
| 1.6 | one tool's docstring set to `None`, as `python -OO` does | `tool_descriptions()` and `tool_descriptions("Mixpanel")` | that tool's value is `""` in both; no exception; other values unchanged |
| 1.7 | the existing `tests/test_tools_descriptions.py` | run | passes unchanged |

### US2: The `mcp` extra is optional and the core never imports it

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 2.1 | `pyproject.toml` | parse with `tomllib` | `[project.optional-dependencies].mcp` is exactly one requirement on `mcp`, with bounds `>=2.2` and `<3`. `[project].dependencies` names no `mcp`. The `dev` dependency group includes `mcp` |
| 2.2 | a fresh interpreter (`subprocess.run` with an explicit timeout) | import `wenchang` and every module that `pkgutil.walk_packages` finds under it, except `wenchang.mcp` | no `mcp` or `mcp.*` module is in `sys.modules` |
| 2.3 | a fresh interpreter in which `import mcp` fails (`sys.modules["mcp"] = None` before the import) | `import wenchang.mcp` | raises `ImportError` whose message contains `wenchang[mcp]` |

### US3: Registration with no manual wiring, and startup checks

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 3.1 | `wenchang.mcp` | import | `__all__` is exactly `["PROMPT_RESOURCE_URI", "ToolCallRecord", "build_server", "register_memory_tools"]`. Every parameter of `build_server`, and every parameter of `register_memory_tools` after `server`, is keyword-only |
| 3.2 | the server with no `tool_prefix` | a client calls `list_tools()` | the tool names are exactly the set of `TOOL_NAMES` |
| 3.3 | the server with `tool_prefix="mixpanel"` | `list_tools()` | the tool names are exactly `{"mixpanel_" + n for n in TOOL_NAMES}` |
| 3.4 | the server with product `None` and with `"Mixpanel"`, each with and without a prefix | `list_tools()` | each tool's `description` equals `tool_descriptions(product)[n]`, where `n` is the unprefixed name |
| 3.5 | product `"Mixpanel"` | `list_tools()` | each description's first line contains `"Mixpanel"` |
| 3.6 | the server | `list_tools()` | for each tool, `set(input_schema["properties"])` equals the parameters of the `MemoryTools` method of that name, minus `self`. `set(input_schema.get("required", []))` equals the subset of those parameters with no default. No schema has a `ctx` property |
| 3.7 | the server | `list_tools()` | these schema types are pinned: <br>• **Strings:** `scope`, `area`, `name`, `content`, `line`, `old_string`, `new_string`, and `expected_version` on `append_line`, `replace_fact`, and `delete_file` are `{"type": "string"}`. <br>• **String or null:** `expected_version` on `write_file`, `area` and `cursor` on `list_prefix`, and `description` on `append_line` and `replace_fact`. <br>• **Array of strings:** `aliases` on `write_file`. <br>• **Array of strings or null:** `aliases` on `append_line` and `replace_fact` |
| 3.8 | a `tool_prefix` that is `""`, `"has space"`, `"a/b"`, `"_lead"`, `"-lead"`, `"trail_"`, `"trail-"`, or 65 characters long | `build_server(...)` | raises `ValueError(TOOL_PREFIX_RULE)`. The message is exactly the text in plan.md. Prefixes like `"a"`, `"mixpanel"`, `"a_b-c"`, and a 64-character prefix are accepted |
| 3.9 | a `tool_prefix` whose real type is not `str` (`1`, `b"x"`) | `build_server(...)` | raises `TypeError("tool_prefix must be a str or None, not <type>")` |
| 3.10 | a product `tool_descriptions` rejects | `build_server(...)` | raises the same exception as `tool_descriptions(product)` |
| 3.11 | `wenchang.mcp.tool_descriptions` monkeypatched to return `""` for `read_file` and `"  \n"` for `delete_file` | `build_server(...)` | raises `RuntimeError`. The message names `read_file` and `delete_file` and mentions `python -OO`, in the form given in plan.md |
| 3.12 | `wenchang.mcp.tool_descriptions` monkeypatched to omit `write_file` | `build_server(...)` | raises `RuntimeError` naming `write_file` |
| 3.13 | a `python -OO` subprocess (`subprocess.run`, explicit timeout, script path from `Path(__file__)`) | build the server with `REFERENCE_SLOTS` | exits non-zero; stderr contains the US3.11 message |
| 3.14 | one bad argument at a time | `build_server(...)` | raises before any server is created. See the table after US3 |
| 3.15 | an adopter-built `MCPServer("host", instructions=prompt)` that already has an adopter tool `ping`, where `prompt = build_memory_prompt(REFERENCE_SLOTS)` | `register_memory_tools(server, prompt=prompt, ...)`, then connect a client | `list_tools()` has `ping` plus the seven memory tools, with descriptions as in US3.4. The resource serves `prompt`. `client.instructions == prompt`. The function returns `None` |
| 3.16 | `register_memory_tools` with `prompt` not a `str`, or empty or whitespace-only | call | raises `TypeError("prompt must be a str, not <type>")` or `ValueError("prompt must be non-empty")`. The server gains no tools |
| 3.17 | `register_memory_tools` given any bad argument from US3.8 to US3.14 | call | raises the same exception as `build_server`, and the server gains no tools or resources |

US3.14 cases. Each row changes one argument; the others are valid.

| Argument | Value | Exception |
| -------- | ----- | --------- |
| `client` | `object()` | `TypeError("client must satisfy TransportClient")` |
| `policy` | `{}` | `TypeError("policy must be a ScopePolicy, not dict")` |
| `source` | `5` | `TypeError("source must be a str, not int")` |
| `source` | `""` | `ValueError("source must be non-empty")` |
| `resolver` | `object()` | `TypeError("resolver must satisfy IdentityResolver")` |
| `credentials_from_context` | `"x"` | `TypeError("credentials_from_context must be callable")` |
| `on_call` | `"x"` | `TypeError("on_call must be callable or None")` |

The first four messages are exactly what `MemoryTools` raises.

### US4: The prompt is delivered as `instructions` and as a resource

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 4.1 | the server with `REFERENCE_SLOTS` | a client connects with `mode="legacy"` (the initialize handshake) | `client.instructions == build_memory_prompt(REFERENCE_SLOTS)`, which is `InitializeResult.instructions` |
| 4.2 | the same server | a client connects with the default mode (discover) | `client.instructions == build_memory_prompt(REFERENCE_SLOTS)` |
| 4.3 | the server | `list_resources()` | exactly one resource has `uri == PROMPT_RESOURCE_URI` (`"wenchang://memory-prompt"`) and `mime_type == "text/markdown"` |
| 4.4 | the server | `read_resource(PROMPT_RESOURCE_URI)` | exactly one text content, with `text == build_memory_prompt(REFERENCE_SLOTS)` |
| 4.5 | `wenchang.mcp.build_memory_prompt` wrapped with a counter | build the server, connect two clients, call `read_resource` twice from each | the counter is 1 |
| 4.6 | `slots` whose real type is not `PromptSlots` | `build_server(...)` | raises `TypeError` from `build_memory_prompt` |

### US5: Each call binds the caller's own `MemoryTools` and forwards it

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 5.1 | the server | as alice, call `write_file` and then `read_file` through the client | each result has `is_error` false. Each `structured_content` equals `render_result(direct.read_file(...))`, where `direct` is a `MemoryTools` bound to alice over the same transport client, read after the server call. `content` is one text item whose JSON parses to `structured_content` |
| 5.2 | the server | a successful `delete_file` | `structured_content == {"ok": True}` |
| 5.3 | alice has written `user/notes/today` | bob calls `read_file("user", "notes", "today")` | `is_error` is true and `error == "NotFoundError"`. The stored path is under alice's entity ID |
| 5.4 | `wenchang.mcp.bind_tools` wrapped with a recorder, plus a counting resolver | N tool calls, alternating alice and bob | `bind_tools` ran N times, each with that call's credentials. The N returned `MemoryTools` are distinct objects. The resolver ran N times |
| 5.5 | the server | a write to the `system` area | `is_error` is true. `structured_content` equals `render_error` of the same `RestrictedScopeError`, with `category == "permanent"` |
| 5.6 | the server | `read_file` of a missing file | `is_error` is true, `category == "recoverable"`, and `error == "NotFoundError"` |
| 5.7 | `credentials_from_context` raises `RuntimeError("secret-token-123")`, with `caplog` at `DEBUG` | any tool call | `is_error` is true, `error == "ResolverFailureError"`, and `category == "permanent"`. `secret-token-123` appears nowhere in the result text, `structured_content`, or any captured log record's message or formatted `exc_info`. The resolver was not called |
| 5.8 | a resolver returning `ResolutionFailure("no such user")` | any tool call | `is_error` is true, `error == "ResolverFailureError"`, and the message contains `"no such user"` |
| 5.9 | a transport client whose `read_file` raises `KeyError("internal-detail")` | `read_file` through the server | `is_error` is true, `category == "internal"`, and `message == "internal error"`. A record is logged on logger `wenchang.mcp` at `ERROR` with `exc_info` |
| 5.10 | `source="mcp-smoke"` | `write_file` through the server | the file's `sources` contain `"mcp-smoke"` |
| 5.11 | `tool_prefix="mixpanel"` | call `mixpanel_read_file` | forwards to `read_file` like the unprefixed server |
| 5.12 | the server | call `read_file` with `scope=5`, and separately with `name` omitted | `is_error` is true and `structured_content is None`. The text content names the argument (`scope`, `name`). This is the MCP schema-validation path, which bypasses `render_error` (ADR 0027) |
| 5.13 | alice has files in `user/notes` and `user/people` | `list_prefix(scope="user", area="null")` | lists both areas, as if `area` were omitted. MCP pre-parses `"null"` to `None` (ADR 0027) |
| 5.14 | alice's file with description `"d1"` | `append_line(..., description="null")` | succeeds, and the stored description is still `"d1"` |
| 5.15 | `list_prefix(scope="user", area="[1]")` | call | `is_error` is true, `structured_content is None`, and the text names `area` |

### US6: Concurrency

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 6.1 | an `InMemoryStorage` and 8 threads behind a barrier | each calls `put_if_version(key, ..., expected=None)` | exactly one succeeds; the other 7 raise `PreconditionFailedError` |
| 6.2 | an `InMemoryStorage` and 8 threads × 50 `put` calls to distinct keys | run | all 400 returned tokens are distinct |
| 6.3 | an `InMemoryStorage` holding a key at version `v`, and 8 threads behind a barrier | each calls `put_if_version(key, ..., expected=v)` | exactly one succeeds, and the stored version is the one it returned |
| 6.4 | alice's file at version `v` | 8 concurrent `write_file` calls at `expected_version=v`, through one client in an `anyio` task group | exactly one has `is_error` false. The other 7 are `error == "VersionConflictError"` with `category == "recoverable"`, and their `version` equals the winner's. The winner's version differs from `v` |
| 6.5 | 8 concurrent `write_file` calls creating 8 different files (`expected_version=None`) | through the client | all succeed, and the 8 versions are distinct |

### US7: The `on_call` observer

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 7.1 | `ToolCallRecord` | inspect | it is a frozen dataclass with fields `tool: str`, `arguments: Mapping[str, object]`, `result: Mapping[str, object]`, and `is_error: bool` |
| 7.2 | `on_call` appending to a list, and `tool_prefix="mixpanel"` | a successful `mixpanel_read_file(scope, area, name)` | one record. `tool == "mixpanel_read_file"`. `arguments == {"scope": ..., "area": ..., "name": ...}` (the arguments the wrapper received, `ctx` excluded). `result == structured_content`. `is_error is False` |
| 7.3 | the same | a call failing with `NotFoundError`, and one failing in `credentials_from_context` | one record each, with `is_error is True` and `result` equal to that call's `structured_content` |
| 7.4 | the same | a call rejected by MCP schema validation (US5.12) | no record. ADR 0027 says these never reach the wrapper |
| 7.5 | `on_call` raising `RuntimeError` | a successful call | the client still gets the normal result. One record is logged on `wenchang.mcp` at `ERROR` |
| 7.6 | `on_call=None` (the default) | calls | they work as in US5 |

### US8: Stdio

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 8.1 | `tests/mcp_stdio_server.py`, which builds the server over an in-memory store with `REFERENCE_SLOTS` and a `SandboxResolver` and calls `server.run("stdio")` | a client launches it through `StdioServerParameters` (path from `Path(__file__)`, 30 s `anyio.fail_after`) | `list_tools()` returns the seven names. `client.instructions == build_memory_prompt(REFERENCE_SLOTS)`. A `write_file` then `read_file` round trip succeeds |

### US9: Documentation

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 9.1 | ADR 0027 | read | records the decisions listed after this table |
| 9.2 | ADR 0022 | read | dated notes point to ADR 0027. **Decision 2:** binding is per tool call through the MCP adapter, which supersedes "resolved once per session" and the rejection of per-use resolution. **Decision 12:** the server now exists. **Decision 13:** at the MCP surface, schema validation precedes it |
| 9.3 | ADR 0026 | read | dated notes point to ADR 0027. **Decision 3:** a module-level `tool_descriptions(product)` now exists, which supersedes its rejection. **Decisions 5 and 6:** they point to `tool_descriptions` and `register_memory_tools` |
| 9.4 | ADR 0003 | read | a dated note says `InMemoryStorage` is thread-safe, with a pointer to ADR 0027 |
| 9.5 | ARCHITECTURE.md | read | it has: <br>• an `mcp` module entry, covering `register_memory_tools`, `build_server`, `ToolCallRecord`, and `on_call`; <br>• a diagram node and edges for `mcp`; <br>• `tool_descriptions` in the `tools` entry; <br>• a note on the optional extra; <br>• one sentence that `InMemoryStorage` is thread-safe; <br>• the thread-safety requirement on a `TransportClient` served by `mcp` |
| 9.6 | README | read | a "Serving over MCP" section shows `build_server` and `register_memory_tools` with `credentials_from_context` and `tool_prefix`, and running over stdio. It says `credentials_from_context` returns the raw credential, the resolver verifies it, and `ctx.headers` and `_meta` are never an identity assertion. It notes the `"null"` pre-parse |
| 9.7 | `docs/product/glossary.md` | read | it has a "Host adapter" entry |

US9.1: ADR 0027 records these decisions.

- **Dependency.** The `mcp` 2.x `MCPServer`, which is FastMCP renamed.
- **Registration.** Tools are registered with explicit `name=` and
  `description=`.
- **Per-call binding.** It is the only reading under the stateless
  2026-07-28 protocol. The legacy-only private
  `request_context.session._connection` is not usable. A "memory is
  unavailable for this session" `ResolverFailureError` may now surface
  mid-conversation.
- **Credentials.** `credentials_from_context` returns raw credentials, and
  the resolver verifies them.
- **Concurrency.** Calls run concurrently on worker threads, so the
  `TransportClient` must be thread-safe. `InMemoryStorage` is made
  thread-safe.
- **Prefix rule.** The `tool_prefix` naming rule.
- **Prompt delivery.** The prompt is the server's `instructions` and is
  served as a resource.
- **Adopter servers.** `register_memory_tools` works on an adopter's own
  server, which is the closest equivalent of Section 7's "mount".
- **Observer.** The `on_call` observer.
- **Startup check.** The check for missing or empty descriptions.
- **Public API.** `tool_descriptions` becomes public.
- **Deviations at the MCP surface.** Schema validation runs before
  `render_error` and ADR 0022 decision 13. The `"null"` pre-parse is one
  such case.
- **Rejected alternatives.** These are listed, including the local gRPC
  client from the issue text.

## Out of scope

- **gRPC.** There is no production gRPC transport and no gRPC client. The
  issue's first paragraph mentions a minimal local gRPC client. The
  2026-10-08 requirements make a real MCP client the smoke-test driver.
  This deviation from the issue text is recorded in ADR 0027.
- **Server composition.** Mounting into a parent server is out of scope,
  because `mcp` 2.x has no compose API. `register_memory_tools` on the
  adopter's own server is the equivalent.
- **Deployment concerns.** Authentication middleware, HTTP deployment, and
  caching of resolved identities are out of scope.
- **`ToolAnnotations`** (`readOnlyHint`, `destructiveHint`) are a
  follow-up.
- **`GcsStorage` thread-safety** is not verified here. It is a follow-up,
  noted as a risk.
- **Existing text.** Tool docstrings, `TOOL_NAMES`, and the prompt text do
  not change.
