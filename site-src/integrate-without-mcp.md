# Integrate without MCP

The memory tools are methods on a Python object. If your agent runs on another tool framework, or on your own loop over a model API, call them directly. Nothing is registered anywhere until you register it.

## Install {#install}

The base package is enough. It needs no `mcp`:

```
pip install "wenchang @ git+https://github.com/msiebert/wenchang"
```

With uv: `uv add "wenchang @ git+https://github.com/msiebert/wenchang"`.

## The tools are methods {#methods}

`wenchang.tools.bind_tools(client, resolver, credentials, policy, *, source, product=None, on_call=None)` resolves the caller's identity and returns a `MemoryTools` for that identity. On it:

- `tools.tools()` maps each of the seven tool names to its bound method, in `wenchang.tools.TOOL_NAMES` order.
- `tools.descriptions()` maps each name to the description to show the model, with `product` named in each first line. Register this text, not the methods' docstrings.

The methods take the same arguments as the tools in the [reference](reference.md#tools) and return result objects. Nothing else is exposed: no prompt, no registration, no transport.

If you have already resolved the identity yourself, `MemoryTools(client, identity, policy, *, source, product=None, on_call=None)` builds the same object from an `Identity`.

## Bind per request {#per-request}

`bind_tools` calls your resolver once and fixes that identity for the object's lifetime. A multi-tenant service binds per request, or per session if a session has one caller, never once per process. Binding runs the resolver and builds a small object.

The store, the client, the resolver, and the policy are built once per process and shared.

If the resolver returns a `ResolutionFailure` or raises, `bind_tools` raises `ResolverFailureError` (permanent). Render it like any tool error. The model then has no memory for that request.

## Tool schemas {#schemas}

`wenchang.schemas.tool_schemas(product=None)` returns a read-only mapping from tool name to `ToolSchema`, one per tool, in `TOOL_NAMES` order. Give these to your framework instead of writing argument models by hand. `error_schema()` returns the schema shared by every `render_error` payload.

| Field | Type | Contents |
| --- | --- | --- |
| `name` | string | The bare tool name, such as `read_file`. |
| `description` | string | The tool's description, the same as `tool_descriptions(product)[name]`. |
| `input` | dict | JSON Schema of the tool's arguments, with defaults for optional ones. |
| `output` | dict | JSON Schema of the `render_result` payload on success. |
| `error` | dict | JSON Schema of the `render_error` payload on failure; the same as `error_schema()`. |

Every schema is JSON Schema draft 2020-12 and closed (`additionalProperties: false`). Each call builds fresh dicts, so you can change them without affecting later calls.

Validate the model's arguments against `input` before calling the method, as most frameworks do from the parameter schema. The method is called with `**arguments`, so a missing or unknown argument raises a `TypeError` that `render_error` reports as an opaque `internal` error. Here `ToolDef` stands in for your framework's tool definition, for one session's tools:

<!--include python custom_schemas.py-->

The schemas assume on-contract output and standard tool-use modes:

- **Every field is required.** An on-contract `TransportClient` always produces every field, so each output field is marked required. `render_result` drops a field whose value has the wrong type, which an off-contract client can produce; strict validation rejects that payload.
- **Errors are wenchang's own.** The error schema covers the error classes wenchang raises. A `WenchangError` subclass of your own validates only if it reuses these attribute names, types, and `reason` values.
- **Input schemas target standard tool use.** They work as-is with Anthropic tool use and OpenAI function calling. OpenAI's strict mode requires every property in `required`, so optional arguments must become required and nullable; Gemini function declarations reject `anyOf`, `additionalProperties`, and `default`. A host using either must transform `input` first.

## Results and errors {#results}

Tool methods return result objects and raise exceptions. `wenchang.tools.render_result(value)` turns a return value into the JSON-safe dict to show the model, and `render_error(exc)` turns any exception into the error payload, with the category and repair details described under [errors](reference.md#errors). These are the same payloads the MCP adapter sends. An unexpected exception renders as an `internal` error with a generic message, so internals never reach the model.

## A complete example {#example}

This binds per request with an in-memory store, dispatches each call by name with arguments checked against the schema, and renders a result and an error. The asserts show what comes back.

<!--include python integrate_direct.py-->

## Threads and async hosts {#threads}

Calls are synchronous. Under `GcsStorage` each one blocks on one or more GCS round trips; `get_memory_index` lists every object in the caller's entities unless an [index cache](storage.md#index-cache) serves it. If your host runs tool calls from several threads, the store and client you share must be safe to call from several threads; `InMemoryStorage` is. An async host runs each call in a worker thread, for example `await asyncio.to_thread(method, **arguments)`, so it does not block the event loop.

## Observing calls {#on-call}

`bind_tools(..., on_call=...)` delivers one `ToolCallRecord` per tool call. On this path:

- `tool` is the bare method name, such as `read_file`.
- `arguments` holds every parameter by name, with defaults filled.
- `result` is `render_result` of the return value, or `render_error` of the raised error; `is_error` says which.
- `request_id` is `None`.
- `duration_s` is the wall time of the tool method only.

The observer runs synchronously on the calling thread, before the call returns or raises, so correlate records with a contextvar or thread-local. `bind_tools` checks `on_call` before it runs the resolver. A call Python rejects for its arguments never produces a record. An exception the observer raises is logged at ERROR and swallowed. Records contain memory content, so treat them as sensitive. The [reference](reference.md#telemetry) lists every field.

This observer logs and counts calls without recording arguments or results:

<!--include python custom_observer.py-->

## What you provide {#provide}

- **The prompt.** The model needs the memory prompt alongside the tools. Put `build_memory_prompt(slots)` from `wenchang.prompts` in your system prompt; it has `##` headings and no top-level heading. See [Customizing the prompts](prompts.md).
- **Identity.** A resolver and a scope policy. See [Identity and multi-tenant auth](identity.md).
- **Storage.** A `MemoryStore` over `GcsStorage`, or `InMemoryStorage` for tests. See [Storage and operations](storage.md).
