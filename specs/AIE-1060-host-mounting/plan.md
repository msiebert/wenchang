# Plan: Host-mounting smoke test (MCP server adapter)

**Linear issue**: AIE-1060 | **Spec**: [spec.md](spec.md)

## Dependency choice

- Use the official `mcp` package, 2.x line: `mcp>=2.2,<3`. The lock resolves
  2.3.0, released 2026-10-02. 2.2.0 was released 2026-09-07.
- In `mcp` 2.x, FastMCP is renamed `MCPServer`, at
  `mcp.server.mcpserver.MCPServer`. Importing `mcp.server.fastmcp` raises
  and points to the migration guide. `MCPServer` is the same decorator-style
  server the issue calls FastMCP.
- Rejected: `mcp<2` (1.30, which still ships `FastMCP`). It is the legacy
  line, and clients now speak the 2026-07-28 protocol that 2.x implements.
- Rejected: the standalone `fastmcp` package. It is a third-party framework
  with a larger dependency tree, and the brief prefers the official package.
- `pyproject.toml` changes:
  - `[project.optional-dependencies]` gains `mcp = ["mcp>=2.2,<3"]`.
  - The `dev` group gains `"mcp>=2.2,<3"` so `make check` runs the smoke
    test.
  - `uv.lock` is regenerated with `uv add --optional mcp "mcp>=2.2,<3"` and
    `uv add --dev "mcp>=2.2,<3"`, then committed.

Facts verified against `mcp` 2.3.0 in a scratch prototype:

- `MCPServer.add_tool(fn, name=, description=)` takes an explicit
  description. The wrapper's docstring is not used.
- A parameter annotated `Context` is injected and left out of the input
  schema, including when it is keyword-only.
- A `NewType` over `str` renders as `{"type": "string"}`. `Sequence[str] |
  None` renders as `anyOf` array-of-string or null. Parameters without a
  default are `required`.
- A sync tool function runs on a worker thread through
  `anyio.to_thread.run_sync`, so blocking storage calls don't block the
  event loop.
- A tool returning `mcp.types.CallToolResult` passes it through unchanged,
  including `is_error`, and publishes no output schema.
- `MCPServer(instructions=...)` reaches `Client.instructions` both in
  legacy mode (`InitializeResult.instructions`) and in discover mode.
- `@server.resource(uri, mime_type=...)` serves text, and
  `Client.read_resource` returns it.
- `Client.call_tool(..., meta={...})` arrives as
  `ctx.request_context.meta`. `Context.headers` carries HTTP headers on HTTP
  transports and is `None` on stdio.
- `ctx.session` is a different object on every request, even within one
  client connection and in legacy mode. The 2026-07-28 protocol is
  stateless, so there is no per-connection session object or id to key a
  cache on.
- `import mcp` and `MCPServer` work under `python -OO`.

## Public interface

### `wenchang.tools` (changed)

```python
__all__ = [
    "TOOL_NAMES", "MemoryTools", "bind_tools", "render_error", "render_result",
    "tool_descriptions",
]

def tool_descriptions(product: str | None = None) -> Mapping[str, str]:
    """Each tool's description by name, in TOOL_NAMES order.

    With a product, each first line names it. A tool whose docstring is
    missing, as under python -OO, has an empty description.
    """
```

- `product` is validated by the existing `_product` helper, so its
  exceptions and messages match `MemoryTools` (US1.4).
- For each name, `doc = getattr(MemoryTools, name).__doc__`. If `doc` is
  `None`, the value is `""`, with or without a product. Otherwise the value
  is the existing rendering: `inspect.cleandoc(doc)`, with the first line
  replaced from `_FIRST_LINE_TEMPLATES` when a product is set.
- It returns a fresh `MappingProxyType` on each call.
- `MemoryTools.descriptions()` becomes
  `return tool_descriptions(self._product)`. The module global is looked up
  at call time, so the US1.5 monkeypatch works. Its docstring stays as it
  is.
- `MemoryTools` must be defined before `tool_descriptions` runs. That holds
  because the function body looks the class up at call time.
- The module docstring gains one clause naming `tool_descriptions`.

### `wenchang.mcp` (new, `src/wenchang/mcp.py`)

```python
"""MCP server adapter: the memory tools and prompt served by an mcp MCPServer.

Requires the optional extra: pip install 'wenchang[mcp]'.
"""

try:
    from mcp.server.mcpserver import Context, MCPServer
    from mcp.types import CallToolResult, TextContent
except ImportError as exc:  # optional dependency
    raise ImportError(
        "wenchang.mcp requires the optional 'mcp' extra: pip install 'wenchang[mcp]'"
    ) from exc

__all__ = ["PROMPT_RESOURCE_URI", "build_server"]

PROMPT_RESOURCE_URI: Final[str] = "wenchang://memory-prompt"

def build_server[C](
    *,
    client: TransportClient,
    resolver: IdentityResolver[C],
    policy: ScopePolicy,
    slots: PromptSlots,
    credentials_from_context: Callable[[Context[Any, Any]], C],
    source: str,
    product: str | None = None,
    tool_prefix: str | None = None,
    name: str = "wenchang",
) -> MCPServer:
    """Return an MCPServer serving the memory tools and prompt.

    Each tool call reads the caller's credentials with
    credentials_from_context, binds that caller's own MemoryTools, and
    returns render_result or render_error output.
    """
```

`build_server` runs these steps in order. Each failing step raises, and no
server is returned.

1. Validate `tool_prefix` (US3.8, US3.9).
   - `None` means no prefix.
   - A non-`str` real type raises
     `TypeError(f"tool_prefix must be a str or None, not {type_name}")`.
   - A value failing `re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", prefix)`
     raises `ValueError("tool_prefix must match [A-Za-z0-9][A-Za-z0-9_-]*")`.
   - The registered name is `f"{tool_prefix}_{name}"`.
2. Call `descriptions = tool_descriptions(product)`. This validates
   `product` (US3.10).
3. Check for missing descriptions (US3.11 to US3.13). Collect every name in
   `TOOL_NAMES` that is missing from `descriptions` or whose value is
   `""` after `strip()`. If any exist, raise:
   `RuntimeError(f"memory tool descriptions are missing or empty for: {', '.join(missing)}; "
   "the tool docstrings may have been stripped (python -OO)")`.
4. Call `prompt = build_memory_prompt(slots)` once. A wrong `slots` type
   raises `TypeError` (US4.6).
5. Create `server = MCPServer(name, instructions=prompt, version=wenchang.__version__)`.
6. Register the resource with
   `@server.resource(PROMPT_RESOURCE_URI, name="memory_prompt", title="Memory prompt",
   description="The memory system prompt; the same text as the server instructions.",
   mime_type="text/markdown")`. The handler returns the captured `prompt`
   string and never rebuilds it (US4.5).
7. Register the seven wrappers, in `TOOL_NAMES` order, with
   `server.add_tool(fn, name=prefixed, description=descriptions[name])`.

`source` and the `client`, `resolver`, and `policy` types are validated
when `bind_tools` runs. They are passed through unchanged, so a bad
`source` surfaces on the first call as a rendered `internal` error. Fail
fast at build instead: construct
`MemoryTools(client, Identity({}), policy, source=source, product=product)`
once and discard it. This reuses the constructor's adopter-side checks
(ADR 0022 decision 2) without resolving anyone.

#### Wrappers

Each wrapper is a module-private sync function closed over the build
arguments. Its parameters mirror the `MemoryTools` method of the same name
exactly: names, order, annotations, and defaults. A keyword-only
`ctx: Context[Any, Any]` is added, which MCPServer injects and leaves out of
the schema. Every wrapper returns `CallToolResult`. For example:

```python
def read_file(scope: str, area: str, name: str, *, ctx: Context[Any, Any]) -> CallToolResult:
    return call(ctx, lambda tools: tools.read_file(scope, area, name))

def list_prefix(
    scope: str, area: str | None = None, cursor: ListCursor | None = None,
    *, ctx: Context[Any, Any],
) -> CallToolResult: ...

def write_file(
    scope: str, area: str, name: str, content: str, description: str,
    aliases: Sequence[str], expected_version: VersionToken | None,
    *, ctx: Context[Any, Any],
) -> CallToolResult: ...
```

`append_line`, `replace_fact`, `delete_file`, and `get_memory_index` follow
the same pattern. Each wrapper is written out by hand, not generated with
`inspect.signature` copying. That keeps them readable and pyright-checked.
US3.6 catches drift.

#### `call(ctx, op)`

1. `credentials = credentials_from_context(ctx)`. On any `Exception`,
   return an error result rendered from
   `ResolverFailureError("Credentials could not be read from the request.")`.
   The original exception is never rendered, logged, or chained (US5.7).
   It is suppressed the same way `resolve_identity` does it: the error is
   built inside `except` and raised or rendered outside it.
2. In a `try`, call `tools = bind_tools(client, resolver, credentials,
   policy, source=source, product=product)`, then `value = op(tools)`,
   then return an ok result rendered from `render_result(value)`.
3. On `except Exception as exc`, compute `payload = render_error(exc)`. If
   `payload["category"] == "internal"`, call
   `_log.error("memory tool %s failed", tool_name, exc_info=exc)` on
   `logging.getLogger("wenchang.mcp")`. Then return an error result with
   that payload (US5.9).

The ok result is
`CallToolResult(content=[TextContent(type="text", text=json.dumps(payload))],
structured_content=payload)`. The error result is the same with
`is_error=True`.

`get_memory_index` is a tool too, so the agent's bootstrap call binds like
any other call.

### Session model

The tool path calls `bind_tools` once per tool call. Every call resolves
identity from that call's credentials, and no `MemoryTools` outlives the
call. That is stricter than one binding per session, and it can never share
an identity across callers, which is the hard requirement. A
`credentials_from_context` callable keeps transport details out of the
library:

- an HTTP adopter reads a verified token from `ctx.headers` or its auth
  layer;
- the stdio dev server returns a constant;
- the tests read `ctx.request_context.meta`.

Rejected alternatives:

- **A cache keyed by MCP session id.** Under the 2026-07-28 protocol in
  `mcp` 2.x there is no stable per-connection session object or id (see
  above). A cache keyed on credentials would hold credentials in memory
  and need them hashable.
- **One shared binding created at build.** It shares one identity across
  callers.
- **Credentials as a tool argument.** The agent would control them, which
  ADR 0022 decision 2 rejected.

Cost: the resolver runs on every call. A resolver may cache internally,
because it must already be consistent within a session (ADR 0014). This
goes into ADR 0027.

### Stdio

The server is a plain `MCPServer`, so `server.run("stdio")` serves it. No
new API is needed. `tests/mcp_stdio_server.py` is a test-only script used
by US6.1. AIE-1170 builds its own entry point the same way.

## Module boundaries

- `wenchang.mcp` imports `mcp`, `wenchang` (for `__version__`),
  `wenchang.tools`, `wenchang.prompts`, `wenchang.identity`,
  `wenchang.scope`, `wenchang.transport`, `wenchang.errors`,
  `wenchang.core` (types), and `wenchang.version_token`.
- No other `wenchang` module imports `wenchang.mcp` or `mcp` (US2.2).
- `wenchang.tools` gains no import.

## Files

| File | Change |
| ---- | ------ |
| `pyproject.toml`, `uv.lock` | `mcp` extra and dev group |
| `src/wenchang/tools.py` | `tool_descriptions`; `descriptions()` delegates; `__all__` |
| `src/wenchang/mcp.py` | new adapter |
| `tests/test_tools_descriptions.py` | append US1 tests (no existing test changed) |
| `tests/test_mcp_packaging.py` | US2 (subprocess import checks, pyproject) |
| `tests/test_mcp_server.py` | US3, US4, US5 smoke tests with a real `mcp.client.Client` |
| `tests/test_mcp_stdio.py`, `tests/mcp_stdio_server.py` | US6 |
| `docs/adr/0027-mcp-host-adapter.md` | new ADR |
| `docs/adr/0022-tool-layer.md`, `docs/adr/0026-product-identity.md` | dated notes |
| `ARCHITECTURE.md`, `README.md`, `docs/product/glossary.md` | US7 |

The tests are async. The repo has no pytest-asyncio, so each async test
body runs with `anyio.run(...)`, a dependency of `mcp`, from a sync test
function. That adds no new test plugin. `tests/test_mcp_*.py` modules use
`pytest.importorskip` nowhere: the dev group always has `mcp`, and a
missing extra must fail loudly.

## Testing notes

- Expected schema parameters come from
  `inspect.signature(getattr(MemoryTools, n))`, minus `self`. Required
  parameters are those whose `default is inspect.Parameter.empty`.
- US3.13 and US2.2/2.3 run `sys.executable` in a subprocess, with
  `-OO` for 3.13. The subprocess imports
  `tests/prompts_reference_adopter.py` by inserting the tests directory into
  `sys.path`.
- US6.1 launches `sys.executable tests/mcp_stdio_server.py` through
  `StdioServerParameters`, with a 30 s overall timeout through
  `anyio.fail_after`.

## ADR and ARCHITECTURE changes

- ADR 0027, "MCP host adapter", covers the dependency choice, explicit
  descriptions, the session model, the prefix, prompt delivery, the
  `-OO` check, `tool_descriptions`, and the deviation from Section 7's
  "mount".
- ADR 0022 gets a dated note on decision 12. ADR 0026 gets dated notes on
  decisions 5 and 6.
- ARCHITECTURE.md gets a new `mcp` module entry and an `mcp --> tools` and
  `mcp --> prompts` edge in the diagram. The `tools` entry mentions
  `tool_descriptions`. A dependency note covers the optional extra.

## Constitution check

- Tests come first, and every acceptance criterion maps to a test (tasks.md).
- No existing test changes.
- The public API changes: `tool_descriptions` and the new `wenchang.mcp`
  module. That needs an ADR plus ARCHITECTURE.md (Principle VII). Storage
  semantics don't change.
- Strict pyright covers the new module. `Context[Any, Any]` is the only use
  of `Any`, because `MCPServer` is generic over lifespan and request types
  the adapter doesn't use.
