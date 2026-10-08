# Plan: Host-mounting smoke test (MCP server adapter)

**Linear issue**: AIE-1060 | **Spec**: [spec.md](spec.md)

## Dependency choice

Use the official `mcp` package, 2.x line: `mcp>=2.2,<3`. The orchestrator
accepted this choice at the spec checkpoint.

- **Versions.** The lock resolves to 2.3.0, released 2026-10-02. Version
  2.2.0 was released 2026-09-07.
- **FastMCP is renamed.** In `mcp` 2.x, FastMCP is renamed `MCPServer`
  (`mcp.server.mcpserver.MCPServer`), and importing `mcp.server.fastmcp`
  raises.
- **Rejected: `mcp<2`.** Version 1.30 still ships `FastMCP`, but it is the
  legacy line, and clients speak the 2026-07-28 protocol that 2.x
  implements.
- **Rejected: standalone `fastmcp`.** It is a third-party framework with a
  heavier dependency tree.

Changes to `pyproject.toml`:

- `[project.optional-dependencies]` gains `mcp = ["mcp>=2.2,<3"]`.
- The `dev` group gains `"mcp>=2.2,<3"`, so `make check` runs the smoke
  test.
- `uv.lock` is regenerated with `uv add --optional mcp "mcp>=2.2,<3"` and
  `uv add --dev "mcp>=2.2,<3"`, then committed.

Facts verified against `mcp` 2.2.0 and 2.3.0, in my prototype and in the
spec reviewer's probes:

- **Explicit descriptions.** `MCPServer.add_tool(fn, name=, description=)`
  takes an explicit description. **An empty `description=""` silently falls
  back to the wrapper's docstring.** The wrappers carry no docstrings, so the
  startup empty-description check is load-bearing, not cosmetic.
- **Context injection.** A parameter annotated `Context` is injected and
  left out of the input schema, including when it is keyword-only.
- **Schema generation.**
  - A `NewType` over `str` renders as `{"type": "string"}`.
  - `X | None` renders as `anyOf` X or null.
  - Parameters without a default are listed in `required`.
- **Worker threads.** Sync tool functions run on worker threads through
  `anyio.to_thread.run_sync`. **Parallel `call_tool` requests execute
  concurrently** in every transport and mode combination: in-memory and
  stdio, legacy and discover. The `TransportClient` must therefore be
  thread-safe; see Concurrency below.
- **Tool results.** A tool returning `mcp.types.CallToolResult` passes
  through unchanged, including `is_error`, and publishes no output schema.
- **Argument validation runs before the wrapper.** A wrong-type or missing
  argument returns `is_error=True` with pydantic text only: no
  `structured_content` and no category. The text names the argument.
- **JSON pre-parse.** For a parameter whose annotation is not exactly `str`,
  mcp first tries to JSON-parse a string argument.
  - `"null"` becomes `None`. So `list_prefix(area="null")` arrives as
    `area=None`. `description="null"` on `append_line` and `replace_fact`
    arrives as `None`, which means "no change".
  - `"[1]"` becomes a list and then fails validation.
  - A digit string such as `"123"` stays a string for a string-typed
    parameter, so version tokens, which are digit strings, are unaffected.
- **Instructions.** `MCPServer(instructions=...)` reaches
  `Client.instructions` in both legacy mode (`InitializeResult.instructions`)
  and discover mode. `MCPServer.instructions` is a read-only property, so it
  can only be set at construction.
- **Resources.** `@server.resource(uri, mime_type=...)` serves text, and
  `Client.read_resource` returns it.
- **Request metadata.** `Client.call_tool(..., meta={...})` arrives as
  `ctx.request_context.meta`. `Context.headers` carries HTTP headers on HTTP
  transports and is `None` on stdio. Neither is an identity assertion.
- **Sessions.** `ctx.session` is a different object on every request.
  - Under the 2026-07-28 protocol, which the client negotiates by default,
    there is no per-connection object or session id.
  - In legacy handshake mode, a per-connection object with a `.state` dict
    does exist, at `ctx.request_context.session._connection`. It is private
    and absent under the modern protocol, so it is not usable.
- **`python -OO`.** `import mcp` and `MCPServer` both work under `python -OO`.

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

- **Validation.** `product` is validated by the existing `_product` helper,
  so the errors are identical to those of `MemoryTools`.
- **Rendering.** For each name, `doc = getattr(MemoryTools, name).__doc__`.
  - If `doc` is `None`, the value is `""`, with or without a product.
  - Otherwise the value is `inspect.cleandoc(doc)`. With a product, its
    first line is replaced from `_FIRST_LINE_TEMPLATES`.
- **Return value.** A fresh `MappingProxyType` on each call.
- **Delegation.** `MemoryTools.descriptions()` becomes
  `return tool_descriptions(self._product)`. The module global is looked up
  at call time, as US1.5 requires.
- **Module docstring.** It gains one clause naming `tool_descriptions`.

### `wenchang.storage.memory.InMemoryStorage` (changed)

- **Lock.** `__init__` creates `self._lock = threading.Lock()`. `get`,
  `put`, `put_if_version`, `delete_if_version`, and `list_page` each hold it
  for their whole body.
- **No re-entrant locking.** `put_if_version` holds the lock, so it must not
  call the public `put`. Both call a private `_put_locked` that assumes the
  lock is already held.
- **Semantics unchanged.** The class docstring gains one sentence: "Safe to
  call from multiple threads."

### `wenchang.mcp` (new, `src/wenchang/mcp.py`)

```python
"""MCP server adapter: the memory tools and prompt on an mcp MCPServer.

Requires the optional extra: pip install 'wenchang[mcp]'.
"""

try:
    from mcp.server.mcpserver import Context, MCPServer
    from mcp.types import CallToolResult, TextContent
except ImportError as exc:  # optional dependency
    raise ImportError(
        "wenchang.mcp requires the optional 'mcp' extra: pip install 'wenchang[mcp]'"
    ) from exc

__all__ = [
    "PROMPT_RESOURCE_URI", "ToolCallRecord", "build_server", "memory_instructions",
    "register_memory_tools",
]

PROMPT_RESOURCE_URI: Final[str] = "wenchang://memory-prompt"

TOOL_PREFIX_RULE: Final[str] = (
    "tool_prefix must be 1-64 characters of A-Z, a-z, 0-9, '_' or '-', "
    "starting and ending with a letter or digit"
)
_TOOL_PREFIX: Final = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9_-]{0,62}[A-Za-z0-9])?")

@dataclass(frozen=True)
class ToolCallRecord:
    """One memory tool call as the MCP adapter handled it."""

    tool: str                       # registered name, prefix included
    arguments: Mapping[str, object] # what the wrapper received, ctx excluded
    result: Mapping[str, object]    # the rendered payload sent as structured_content
    is_error: bool

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

    prompt is build_memory_prompt's output; pass the same text as the
    server's instructions. Each tool call reads the caller's credentials
    with credentials_from_context, binds that caller's own MemoryTools, and
    returns render_result or render_error output. client is called from
    worker threads concurrently and must be thread-safe.
    """

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
    """Return an MCPServer with the memory prompt as instructions and the memory tools."""
```

`TOOL_PREFIX_RULE` is not in `__all__`. Tests import it as a module constant
to compare messages.

**`register_memory_tools` validates everything first, in this order.** The
first failure raises, and `server` is left untouched.

1. **`client`, `policy`, `source`, `product`.** Construct
   `MemoryTools(client, Identity({}), policy, source=source, product=product)`
   once and discard it. This reuses the constructor's exact messages (ADR
   0022 decision 2, ADR 0026 decision 3).
2. **`resolver`.** If `isinstance(resolver, IdentityResolver)` is false,
   raise `TypeError("resolver must satisfy IdentityResolver")`.
3. **`credentials_from_context`.** If `callable(...)` is false, raise
   `TypeError("credentials_from_context must be callable")`.
4. **`on_call`.** If it is neither `None` nor callable, raise
   `TypeError("on_call must be callable or None")`.
5. **`tool_prefix`.** `None` means no prefix.
   - A non-`str` real type raises
     `TypeError(f"tool_prefix must be a str or None, not {type_name}")`.
   - A value that fails `_TOOL_PREFIX.fullmatch` raises
     `ValueError(TOOL_PREFIX_RULE)`.
   - The registered name is `f"{tool_prefix}_{name}"`. The longest possible
     name is 64 + 1 + 16 = 81 characters, which fits MCP's 128-character
     limit.
6. **`prompt`.**
   - A non-`str` real type raises `TypeError("prompt must be a str, not <type>")`.
   - A value that is empty after `strip()` raises
     `ValueError("prompt must be non-empty")`.
7. **Descriptions.** Call `descriptions = tool_descriptions(product)`, then
   collect every name in `TOOL_NAMES` that is missing from `descriptions` or
   whose value is `""` after `strip()`. If there are any, raise:
   `RuntimeError(f"memory tool descriptions are missing or empty for: {', '.join(missing)}; "
   "the tool docstrings may have been stripped (python -OO)")`.

**Then it registers:**

1. The resource, with `server.resource(PROMPT_RESOURCE_URI, name="memory_prompt",
   title="Memory prompt", description="The memory system prompt; the same
   text as the server instructions.", mime_type="text/markdown")` wrapped
   around a function that returns the captured `prompt`.
2. The seven wrappers, in `TOOL_NAMES` order, each with
   `server.add_tool(fn, name=prefixed, description=descriptions[name])`.

**`build_server`:**

1. Runs the same steps 1 to 5 and 7 first, through a shared private
   `_validate(...)`. A bad argument therefore raises before
   `build_memory_prompt` runs and before any server exists (US3.14).
2. Calls `prompt = build_memory_prompt(slots)` once. A wrong `slots` type
   raises `TypeError` (US4.6).
3. Creates `server = MCPServer(name, instructions=prompt, version=wenchang.__version__)`.
4. Calls `register_memory_tools(server, prompt=prompt, ...)` and returns
   `server`. The second validation pass is cheap and keeps the code simple.

#### Wrappers

Each wrapper is a module-private sync function closed over the registration
arguments.

- **No docstring.** Wrappers carry no docstrings.
- **Mirrored signature.** Parameters mirror the `MemoryTools` method of the
  same name exactly: names, order, annotations, and defaults.
- **Context.** Each wrapper adds a keyword-only `ctx: Context[Any, Any]`.
- **Return type.** Every wrapper returns `CallToolResult`.
- **Arguments for `on_call`.** Each wrapper builds `arguments` from its own
  parameters, excluding `ctx`.

```python
def read_file(scope: str, area: str, name: str, *, ctx: Context[Any, Any]) -> CallToolResult:
    return call("read_file", ctx, {"scope": scope, "area": area, "name": name},
                lambda tools: tools.read_file(scope, area, name))

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

The wrappers are written by hand rather than generated by copying
signatures. That keeps them readable and checked by pyright, and US3.6 and
US3.7 catch any drift.

#### `call(tool, ctx, arguments, op)`

`tool` is the registered, prefixed name. Steps:

1. **Read the credentials.** `credentials = credentials_from_context(ctx)`.
   - On any `Exception`, the payload is
     `render_error(ResolverFailureError("Credentials could not be read from the request."))`.
   - The error is built inside the `except` block and rendered outside it,
     so the original exception is never rendered, logged, or chained
     (US5.7).
2. **Bind and run.** Inside a `try`:
   `tools = bind_tools(client, resolver, credentials, policy, source=source, product=product)`,
   then `payload = render_result(op(tools))`.
   - `bind_tools` is looked up as a `wenchang.mcp` module global, imported
     at the top with `from wenchang.tools import bind_tools`. That lets
     US5.4 wrap it with `monkeypatch.setattr("wenchang.mcp.bind_tools", ...)`.
   - On `except Exception as exc`, `payload = render_error(exc)`. If
     `payload["category"] == "internal"`, call
     `_log.error("memory tool %s failed", tool, exc_info=exc)` on
     `_log = logging.getLogger("wenchang.mcp")` (US5.9).
3. **Build the result.**
   `result = CallToolResult(content=[TextContent(type="text", text=json.dumps(payload))], structured_content=payload, is_error=is_error)`.
4. **Notify the observer.** If `on_call` is set, call
   `on_call(ToolCallRecord(tool, MappingProxyType(dict(arguments)), payload, is_error))`.
   If it raises, call
   `_log.error("on_call observer failed for %s", tool, exc_info=True)` and
   return the result anyway (US7.5).
5. **Return** `result`.

Calls that fail schema validation never reach `call`. They produce no
observer record and bypass `render_error` (US5.12, US5.15, US7.4).

### Session model

The wrappers call `bind_tools` once per tool call.

- **Per-call identity.** Identity is resolved from that call's credentials,
  and no `MemoryTools` outlives the call. This is the only reading the
  stateless 2026-07-28 protocol allows, and it can never share one identity
  across callers. The orchestrator accepted it at the spec checkpoint.
- **Credential source.** `credentials_from_context` returns the raw
  credential, for example a bearer token taken from `ctx.headers`, and the
  resolver verifies it. The adapter never treats headers or `_meta` as an
  identity assertion. The stdio dev server returns a constant, and the
  tests read `ctx.request_context.meta`.
- **Cost.** The resolver runs on every call. A resolver may cache
  internally, since it must already be consistent within a session (ADR
  0014).
- **Mid-conversation failure.** A `ResolverFailureError` ("memory is
  unavailable for this session") can now surface in the middle of a
  conversation, not only at session start. The agent is told to continue
  without memory either way.
- **Superseded decision.** This supersedes ADR 0022 decision 2 ("resolved
  once per session", and its rejection of "resolving lazily on first use").
  A dated note goes on that decision.

Rejected alternatives:

- **Cache keyed by session id.** There is no stable id under the modern
  protocol, and the legacy `_connection` object is private.
- **Cache keyed by credentials.** It would hold credentials in memory and
  require them to be hashable.
- **One shared binding.** It would share one identity across callers.
- **Credentials as a tool argument.** The agent would control them (ADR 0022
  decision 2).

### Concurrency

MCPServer runs tool calls concurrently on worker threads, so
`register_memory_tools` calls the `TransportClient` concurrently. The client
must be thread-safe, and ADR 0027 states that as an adopter requirement.

- **`InProcessClient` and `MemoryStore`.** They hold no mutable state of
  their own across calls. Their read-check-write sequences rely on storage
  compare-and-swap (CAS), so their thread-safety reduces to the `Storage`
  implementation's.
- **`InMemoryStorage`** becomes thread-safe through the lock above.
- **`GcsStorage`.** Its preconditions are enforced server-side, but the
  thread-safety of the `google-cloud-storage` client object is not verified
  here. That is a follow-up.

### Stdio

The server is a plain `MCPServer`, so `server.run("stdio")` serves it with
no new API.

- `tests/mcp_stdio_server.py` is a test-only script used by US8.1.
- AIE-1170 builds its own entry point the same way, or calls
  `register_memory_tools` on its own server.

### Round 2 additions

These additions take precedence over the text above where they differ.

**`memory_instructions(slots: PromptSlots) -> str`** is public. It returns
`build_memory_prompt(slots)`, the text to pass as a server's
`instructions`. `build_server` calls it once, so US4.5's counter on
`build_memory_prompt` still reads 1. An adopter builds its own server like
this:

```python
prompt = memory_instructions(slots)
server = MCPServer("host", instructions=prompt)
register_memory_tools(server, prompt=prompt, ...)
```

**Validation order in `register_memory_tools`.**

- **Step 0: the server.** `server` is checked before step 1. If
  `issubclass(type(server), MCPServer)` is false, it raises
  `TypeError(f"server must be an MCPServer, not {type_name}")`.
- **Step 8: collisions.** This step runs after step 7.
  - It computes the seven target names (prefixed) and `PROMPT_RESOURCE_URI`.
  - It reads the existing tool names with
    `server._tool_manager.get_tool(n) is not None`, and the existing
    resource with the resource manager's `get_resource` or its `_resources`
    mapping. The implementation checks which of the two is synchronous.
  - Both are private `mcp` attributes. A comment cites the `mcp<3` pin.
  - It does not use `MCPServer.list_tools()`, because that method is async
    and `register_memory_tools` is sync. It may run before any event loop
    exists, or inside one.
  - If anything collides, it raises
    `ValueError(f"cannot register memory tools: already registered on the server: {', '.join(sorted(collisions))}")`.
    `collisions` holds tool names and, when the resource collides, the URI.
  - Nothing is registered before this check passes.
  - Rationale: `mcp` 2.3.0 `ToolManager.add_tool` and `ResourceManager`
    only log a warning on a duplicate. A collision would otherwise silently
    keep the adopter's tool and drop the memory tool, or the reverse.

**Instructions warning.** After a successful registration, it logs at
`WARNING` on `wenchang.mcp` when `server.instructions` is `None`, or does
not contain `prompt` as a substring:

```
_log.warning("server instructions do not include the memory prompt; pass memory_instructions(slots) as instructions")
```

**The `on_call` observer.**

- **Record contents.** `ToolCallRecord.result` is
  `MappingProxyType(copy.deepcopy(payload))`, and `arguments` is
  `MappingProxyType(copy.deepcopy(dict(arguments)))`. So nothing in a
  record aliases the `structured_content` sent to the client, and nested
  lists stay independent.
- **Threading.** The docstrings of `register_memory_tools`, `build_server`,
  and `ToolCallRecord` state the threading contract, and so does ADR 0027.
  `on_call` runs on the tool call's worker thread, possibly concurrently
  with other calls, and delays the response until it returns. It must
  therefore be thread-safe and fast.
- **Exceptions.** An exception from `on_call` is logged and never reaches
  the client, as US7.5 requires.

**Testing the race (US6.1 to US6.3).**

- **US6.1 and US6.3.** These replace `storage._objects` with a
  `_SlowDict(dict)` whose `get` calls `time.sleep(0.005)` before
  delegating. They reach into the private attribute, which is deliberate
  and noted in the test docstring. Without the lock, every thread passes
  the version check during the sleep. With the lock, the threads serialize.
- **US6.2.** A fixture saves `sys.getswitchinterval()`, sets `1e-6`, and
  restores the saved value in `finally`. It runs 20 rounds.
- **Proving the fix.** All three are run against the unlocked code first,
  and their failures are recorded in the PR review. US6.4 and US6.5 are
  end-to-end smoke checks only.
- **Regression check.** T2 also runs `tests/test_core_append_line.py`,
  whose `_CountingStorage` subclasses or wraps `InMemoryStorage`, to check
  that the lock does not break it.

## Module boundaries

- **`wenchang.mcp` imports:**
  - `mcp.server.mcpserver` and `mcp.types`;
  - `wenchang`, for `__version__`;
  - `wenchang.tools`, `wenchang.prompts`, `wenchang.identity`,
    `wenchang.scope`, `wenchang.transport`, and `wenchang.errors`;
  - `wenchang.core`, for types;
  - `wenchang.version_token`.
- **No other `wenchang` module** imports `wenchang.mcp` or `mcp` (US2.2).
- **`wenchang.tools`** gains no imports.
- **`wenchang.storage.memory`** gains `threading`.

## Files

| File | Change |
| ---- | ------ |
| `pyproject.toml`, `uv.lock` | `mcp` extra and dev group |
| `src/wenchang/tools.py` | `tool_descriptions`; `descriptions()` delegates to it; `__all__` |
| `src/wenchang/storage/memory.py` | lock |
| `src/wenchang/mcp.py` | new adapter |
| `tests/test_tools_descriptions.py` | US1 tests appended; no existing test changes |
| `tests/test_storage_memory_threads.py` | US6.1 to US6.3 |
| `tests/test_mcp_packaging.py` | US2 |
| `tests/test_mcp_server.py` | US3, US4, US5, US6.4 and US6.5, and US7, against a real `mcp.client.Client` |
| `tests/test_mcp_stdio.py`, `tests/mcp_stdio_server.py` | US8 |
| `docs/adr/0027-mcp-host-adapter.md` | new |
| ADRs `0003`, `0022`, `0026` | dated notes |
| `ARCHITECTURE.md`, `README.md`, `docs/product/glossary.md` | US9 |

Test-harness notes:

- **No asyncio plugin.** The repo has no pytest-asyncio, so each async test
  body runs with `anyio.run(...)` from a sync test function. `anyio` comes
  with `mcp`.
- **No `importorskip`.** No `tests/test_mcp_*.py` module uses
  `pytest.importorskip`. The dev group always has `mcp`, and a missing extra
  must fail loudly.

## Testing notes

- **US1.3** builds its expectation independently: `PINNED_FIRST_LINES`
  (already in the test module) with `"Mixpanel"` replaced by `P`, followed by
  the cleandoc'd docstring's later lines.
- **US3.6** derives the expected parameters from
  `inspect.signature(getattr(MemoryTools, n))`, minus `self`. A parameter is
  required when its `default is inspect.Parameter.empty`.
- **Subprocess tests (US2.2, US2.3, US3.13)** use
  `subprocess.run([sys.executable, ...], timeout=60, capture_output=True)`,
  with paths from `Path(__file__).resolve()`.
  - US3.13 inserts the tests directory into `sys.path` so it can import
    `prompts_reference_adopter`.
  - US2.2 enumerates `pkgutil.walk_packages(wenchang.__path__, "wenchang.")`
    inside the subprocess, skipping `wenchang.mcp`.
- **US6.4** writes alice's file once, then starts 8 `call_tool` requests in
  one `anyio` task group gated on an `anyio.Event`. This is the concurrency
  shape the spec reviewer measured.
- **US8.1** launches `sys.executable` with the helper script through
  `StdioServerParameters`, under `anyio.fail_after(30)`.

## ADR and ARCHITECTURE changes

- **ADR 0027, "MCP host adapter".** It records every decision listed in spec
  US9.1. Its rejected alternatives are:
  - the session-id cache;
  - a shared binding;
  - credentials as tool arguments;
  - `mcp<2` and `fastmcp`;
  - setting `__doc__`;
  - generated signatures;
  - the local gRPC client. This is a deviation from the issue text: the
    2026-10-08 requirement to drive a real MCP client supersedes it.
- **Dated notes on earlier ADRs:**
  - ADR 0022, decisions 2, 12, and 13;
  - ADR 0026, decisions 3, 5, and 6;
  - ADR 0003, stating that `InMemoryStorage` is thread-safe.
- **ARCHITECTURE.md:**
  - a new `mcp` module entry;
  - diagram edges `mcp --> tools` and `mcp --> prompts`;
  - `tool_descriptions` in the `tools` entry;
  - a note on the optional extra;
  - the thread-safety sentence in the storage entry.

## Constitution check

- **Tests first.** Every acceptance criterion maps to a test (tasks.md), and
  no existing test changes.
- **ADR and ARCHITECTURE.md required (Principle VII).** The public API
  changes, with `tool_descriptions` and the new `wenchang.mcp` module, and
  storage changes, with `InMemoryStorage` thread-safety. The storage
  semantics themselves do not change.
- **Principle V is upheld.** The fake now matches GCS under concurrent CAS.
- **Strict pyright** covers the new module. `Context[Any, Any]` is the only
  use of `Any`, because `MCPServer` is generic over lifespan and request
  types that the adapter does not use.
