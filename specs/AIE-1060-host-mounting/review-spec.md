# Spec Review: AIE-1060: Host-mounting smoke test (MCP server adapter)

## What & why

ADR 0022 deferred the server that Section 7 describes to this issue. This
issue builds it. It adds a new adapter, `wenchang.mcp`, available through an
optional `mcp` extra.

- `register_memory_tools(server, ...)` adds the seven memory tools and the
  prompt resource to an MCP server the adopter supplies.
- `build_server(...)` constructs the server for you, with the prompt as its
  `instructions`.

Each tool call works like this:

1. It reads the caller's credentials from the request.
2. It binds that caller's own `MemoryTools`.
3. It forwards the call and returns `render_result` or `render_error`
   output.
4. It reports the call to an optional `on_call` observer, which AIE-1170's
   eval grader uses.

Supporting changes:

- Descriptions come from a new public `tool_descriptions(product)`.
- `InMemoryStorage` becomes thread-safe, because MCP runs tool calls
  concurrently.
- A real MCP client smoke-tests the whole surface.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| US1 | `tool_descriptions(product)` | called | Same text as before. `MemoryTools.descriptions()` delegates to it. A missing docstring gives `""` |
| US2 | pyproject / fresh interpreter | inspect / import | `mcp` is only an extra plus a dev dependency, and the core never imports it. Without it, `import wenchang.mcp` gives a clear `ImportError` |
| US3 | `build_server` / `register_memory_tools` | `list_tools()` | Seven names, with the prefix when set. Descriptions equal `tool_descriptions`. Schemas mirror the methods, with pinned types. Every bad argument fails at build with exact messages, including a real `python -OO` run |
| US4 | the server | connect, legacy and discover | `instructions` equals the prompt. Resource `wenchang://memory-prompt` serves the same text, which is built once |
| US5 | two users | tool calls | Per-call identity isolation. Results and errors are rendered, with `is_error` set. Credential failures leak nothing, including in logs. MCP schema errors and the `"null"` pre-parse are pinned |
| US6 | concurrent calls | storage threads / MCP task group | CAS holds: one winner, the rest get `VersionConflictError`, and tokens are distinct |
| US7 | `on_call` | every wrapper call | Records the tool, arguments, rendered result, and `is_error`. Schema-rejected calls are not recorded. A failing observer doesn't break the call |
| US8 | stdio subprocess | real client | Tools, instructions, and a round trip work |
| US9 | docs | read | ADR 0027; notes in ADRs 0003, 0022, and 0026; ARCHITECTURE; README; glossary |

Full Given/When/Then is in [spec.md](spec.md): 67 numbered criteria.

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| Use `mcp>=2.2,<3` with `MCPServer` | `mcp<2` `FastMCP`; `fastmcp` | FastMCP was renamed in 2.x, and 1.x is the legacy protocol line |
| Bind per tool call through `credentials_from_context(ctx)`, which returns the raw credential for the resolver to verify | session-id cache; credentials cache; shared binding | The 2026-07-28 protocol is stateless. The legacy `_connection` object is private |
| `register_memory_tools` on the adopter's server, with `build_server` as a thin wrapper | `build_server` only | Adopters keep auth, middleware, and lifespan. This is the nearest thing to Section 7's "mount" |
| `on_call(ToolCallRecord)` observer | none; MCP middleware | Gives the eval grader an MCP-layer trace of validation and rendering |
| Lock in `InMemoryStorage`, and require a thread-safe `TransportClient` | serialize calls in the adapter | MCP runs sync tools concurrently. The fake must match GCS CAS under concurrency (Constitution V) |
| Register with explicit `description=`; wrappers have no docstrings; startup check for empty descriptions | setting `__doc__` | `description=""` silently falls back to the docstring, so the check is load-bearing |
| Prefix `[A-Za-z0-9](?:[A-Za-z0-9_-]{0,62}[A-Za-z0-9])?`, joined with `_` | dotted or slash separators | Stays inside MCP's name character set and length limit |
| Return `CallToolResult` with JSON text, `structured_content`, and `is_error` | plain dict | Clients can tell failures apart |

## Files/modules to be touched

- `pyproject.toml` and `uv.lock`.
- `src/wenchang/tools.py`, `src/wenchang/storage/memory.py`, and the new
  `src/wenchang/mcp.py`.
- New tests: `tests/test_storage_memory_threads.py`,
  `tests/test_mcp_packaging.py`, `tests/test_mcp_server.py`,
  `tests/test_mcp_stdio.py`, and `tests/mcp_stdio_server.py`.
  `tests/test_tools_descriptions.py` gains new tests.
- Docs: new ADR 0027, notes in ADRs 0003, 0022, and 0026,
  `ARCHITECTURE.md`, `README.md`, and the glossary.

## Open questions / assumptions (for the human)

- **No gRPC client (deviation from the issue text).** The issue's first
  paragraph asks for "a minimal local gRPC client". The 2026-10-08 update
  requires a real MCP client, and that is what drives the smoke test. No
  gRPC code is written. ADR 0027 records this as a rejected alternative.
- **Per-call binding supersedes two earlier decisions.**
  - ADR 0022 decision 2 said identity is "resolved once per session".
    Identity is now resolved on every call, so the resolver runs every call,
    and "memory is unavailable" can surface mid-conversation.
  - ADR 0026 decision 3 rejected a module-level function taking a product.
    `tool_descriptions` is now that function.
  - Both get dated notes.
- **MCP-surface deviations from ADR 0022 decision 13.** MCP validates
  argument types before the wrapper runs.
  - Wrong-type and missing arguments return pydantic text with no category.
  - The string `"null"` pre-parses to `None` for nullable parameters, for
    example `list_prefix(area="null")` and `append_line(description="null")`.
    This is documented and pinned by tests, not rejected.
- **`mcp` 2.x rather than the literal "FastMCP".** `MCPServer` is the
  renamed FastMCP.
- **Unprefixed names in descriptions.** With a prefix set, descriptions
  still mention the unprefixed tool names.

## Follow-ups

- `ToolAnnotations` (`readOnlyHint`, `destructiveHint`) on the seven tools.
- Verify `GcsStorage` thread-safety under concurrent MCP calls.

## Risks

- `mcp` 2.x moves fast, and 2.3.0 is six days old. The `<3` bound plus the
  lockfile limit the exposure, and the smoke test catches drift.
- The resolver runs once per call, which adds latency when it is remote.

## Adversarial review

**Round 1: FAIL** (3 blocking, 7 should-fix, 5 nits). All are folded in.

- **B1. Concurrency.** Calls run in parallel on worker threads, which broke
  CAS in `InMemoryStorage`. Fixed with a lock, US6.1 to US6.5, and the
  thread-safety requirement in ADR 0027.
- **B2. Superseded ADR decisions.** ADR 0022 decision 2 and ADR 0026
  decision 3 now get dated notes (US9.2, US9.3). ADR 0027 records the
  mid-conversation `ResolverFailureError`.
- **B3. Schema-invalid arguments and the `"null"` pre-parse.** Both are
  recorded as MCP-surface deviations and pinned (US5.12 to US5.15). The
  README carries a note.
- **Should-fix items:**
  - The gRPC deviation is flagged.
  - Up-front validation is added (US3.14).
  - `register_memory_tools` (US3.15 to US3.17) and `on_call` (US7) are
    added.
  - US1.3 now uses an independent expectation.
  - US5.7 now checks that the secret is absent from the logs.
  - The credentials wording is fixed.
  - A note explains the `description=""` fallback.
- **Nits:**
  - `walk_packages` replaces the hand-written module list.
  - Subprocess timeouts and `Path(__file__)` are used.
  - The prefix may not end with `_` or `-`, and is capped at 64 characters.
  - More schema pins.
  - `bind_tools` is a module global.
