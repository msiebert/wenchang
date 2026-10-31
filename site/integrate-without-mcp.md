# Integrate without MCP

The memory tools are methods on a Python object. If your agent runs on another tool framework, or on your own loop over a model API, call them directly. Nothing is registered anywhere until you register it.

## Install

The base package is enough. It needs no `mcp`:

```
pip install "wenchang @ git+https://github.com/msiebert/wenchang"
```

With uv: `uv add "wenchang @ git+https://github.com/msiebert/wenchang"`.

## The tools are methods

`wenchang.tools.bind_tools(client, resolver, credentials, policy, *, source, product=None, on_call=None)` resolves the caller's identity and returns a `MemoryTools` for that identity. On it:

- `tools.tools()` maps each of the seven tool names to its bound method, in `wenchang.tools.TOOL_NAMES` order.
- `tools.descriptions()` maps each name to the description to show the model, with `product` named in each first line. Register this text, not the methods' docstrings.

The methods take the same arguments as the tools in the [reference](reference.md#tools) and return result objects. Nothing else is exposed: no prompt, no registration, no transport.

If you have already resolved the identity yourself, `MemoryTools(client, identity, policy, *, source, product=None, on_call=None)` builds the same object from an `Identity`.

## Bind per request

`bind_tools` calls your resolver once and fixes that identity for the object's lifetime. A multi-tenant service binds per request, or per session if a session has one caller, never once per process. Binding runs the resolver and builds a small object.

The store, the client, the resolver, and the policy are built once per process and shared, except where [Threads](#threads) says otherwise.

If the resolver returns a `ResolutionFailure` or raises, or `resolve` is `async`, `bind_tools` raises `ResolverFailureError` (permanent). Render it like any tool error. The model then has no memory for that request.

The multi-tenant resolver on [Identity](identity.md#example) works here unchanged. Build its `Credentials` from your request and pass them to `bind_tools`; [The same resolver without MCP](identity.md#direct) shows the call.

## Tool schemas

`wenchang.schemas.tool_schemas(product=None)` returns a read-only mapping from tool name to `ToolSchema`, one per tool, in `TOOL_NAMES` order. Give these to your framework instead of writing argument models by hand. `error_schema()` returns the schema shared by every `render_error` payload.

| Field | Type | Contents |
| --- | --- | --- |
| `name` | string | The bare tool name, such as `read_file`. |
| `description` | string | The tool's description, the same as `wenchang.tools.tool_descriptions(product)[name]`. |
| `input` | dict | JSON Schema of the tool's arguments, with defaults for optional ones. |
| `output` | dict | JSON Schema of the `render_result` payload on success. |
| `error` | dict | JSON Schema of the `render_error` payload on failure; the same as `error_schema()`. |

Every schema is JSON Schema draft 2020-12 and closed (`additionalProperties: false`). Each call builds fresh dicts, so you can change them without affecting later calls.

Validate the model's arguments against `input` before calling the method, as most frameworks do from the parameter schema. The method is called with `**arguments`, so a missing or unknown argument raises a `TypeError` that `render_error` reports as an opaque `internal` error. Here `ToolDef` stands in for your framework's tool definition, for one session's tools:

```python
from collections.abc import Callable
from dataclasses import dataclass

from wenchang.core import MemoryStore
from wenchang.identity import Identity, SandboxResolver, ScopeGrant
from wenchang.schemas import tool_schemas
from wenchang.scope import ScopePolicy
from wenchang.storage.memory import InMemoryStorage
from wenchang.tools import MemoryTools, bind_tools, render_error, render_result
from wenchang.transport import InProcessClient


@dataclass
class ToolDef:  # stand-in for your framework's tool definition
    name: str
    description: str
    parameters: dict[str, object]
    handler: Callable[[dict[str, object]], dict[str, object]]


def handler(tools: MemoryTools, name: str) -> Callable[[dict[str, object]], dict[str, object]]:
    method = tools.tools()[name]

    def call(arguments: dict[str, object]) -> dict[str, object]:
        # The framework has already validated `arguments` against `s.input`.
        try:
            return render_result(method(**arguments))  # matches the schema's output
        except Exception as exc:
            return render_error(exc)  # matches the schema's error

    return call


client = InProcessClient(MemoryStore(InMemoryStorage()))
resolver = SandboxResolver(Identity(grants={"user": ScopeGrant("u-tianlong", "owner")}))
tools = bind_tools(client, resolver, None, ScopePolicy({}), source="inkwell-cli", product="Inkwell")

defs: dict[str, ToolDef] = {}
for s in tool_schemas(product="Inkwell").values():
    call = handler(tools, s.name)
    defs[s.name] = ToolDef(name=s.name, description=s.description, parameters=s.input, handler=call)

# A NotFoundError payload, valid against tool_schemas()["read_file"].error.
print(defs["read_file"].handler({"scope": "user", "area": "notes", "name": "tea"}))
```

The schemas assume on-contract output and standard tool-use modes:

- **Every field is required.** An on-contract `TransportClient` always produces every field, so each output field is marked required. `render_result` drops a field whose value has the wrong type, which an off-contract client can produce; strict validation rejects that payload.
- **Errors are wenchang's own.** The error schema covers the error classes wenchang raises. A `WenchangError` subclass of your own validates only if it reuses these attribute names, types, and `reason` values.
- **Input schemas target standard tool use.** They work as-is with Anthropic tool use and OpenAI function calling. OpenAI's strict mode requires every property in `required`, so optional arguments must become required and nullable; Gemini function declarations reject `anyOf`, `additionalProperties`, and `default`. A host using either must transform `input` first.

## Results and errors

Tool methods return result objects and raise exceptions. `wenchang.tools.render_result(value)` turns a return value into the JSON-safe dict to show the model, and `render_error(exc)` turns any exception into the error payload, with the category and repair details described under [errors](reference.md#errors). These are the same payloads the MCP adapter sends. An unexpected exception renders as an `internal` error with a generic message, so internals never reach the model.

## A complete example

This binds per request with an in-memory store, dispatches each call by name with arguments checked against the schema, and renders a result and an error. The asserts show what comes back.

```python
from wenchang.core import MemoryStore
from wenchang.errors import InvalidArgumentError
from wenchang.identity import Identity, ResolutionFailure, ScopeGrant
from wenchang.observer import ToolCallRecord
from wenchang.schemas import tool_schemas
from wenchang.scope import ScopePolicy
from wenchang.storage.memory import InMemoryStorage
from wenchang.tools import bind_tools, render_error, render_result
from wenchang.transport import InProcessClient

USERS = {"tok-tianlong": "u-tianlong", "tok-diya": "u-diya"}  # stand-in for your IdP


class TokenResolver:
    """Maps a bearer token to the caller's grants. Must not raise."""

    def resolve(self, credentials: str | None) -> Identity | ResolutionFailure:
        user_id = USERS.get(credentials or "")
        if user_id is None:
            return ResolutionFailure("Invalid or expired token.")
        return Identity(grants={"user": ScopeGrant(user_id, "owner")})


# Built once per process and shared by every request. InMemoryStorage is safe to share
# across threads; see the Threads section before sharing a GcsStorage.
client = InProcessClient(MemoryStore(InMemoryStorage()))
resolver = TokenResolver()
policy = ScopePolicy({})
schemas = tool_schemas(product="Inkwell")
records: list[ToolCallRecord] = []

# Register these with your framework once: name, description, and parameter schema.
definitions = [
    {"name": s.name, "description": s.description, "input_schema": s.input}
    for s in schemas.values()
]


def check_arguments(name: str, arguments: dict[str, object]) -> None:
    # Your framework normally validates against the input schema; this checks names only.
    schema: dict = schemas[name].input
    for key in arguments:
        if key not in schema["properties"]:
            raise InvalidArgumentError(key, "not a parameter of this tool")
    for key in schema.get("required", []):
        if key not in arguments:
            raise InvalidArgumentError(key, "required")


def run_tool_calls(
    token: str | None, calls: list[tuple[str, dict[str, object]]]
) -> list[dict[str, object]]:
    """Run one request's tool calls as the caller the token names."""
    try:
        # Resolve once per request, never once per process.
        tools = bind_tools(
            client,
            resolver,
            token,
            policy,
            source="inkwell-api",
            product="Inkwell",
            on_call=records.append,
        )
    except Exception as exc:  # ResolverFailureError: no memory for this request
        return [render_error(exc) for _ in calls]
    methods = tools.tools()
    payloads: list[dict[str, object]] = []
    for name, arguments in calls:
        try:
            check_arguments(name, arguments)
            payloads.append(render_result(methods[name](**arguments)))
        except Exception as exc:
            payloads.append(render_error(exc))
    return payloads


created, missing = run_tool_calls(
    "tok-tianlong",
    [
        (
            "write_file",
            {
                "scope": "user",
                "area": "preferences",
                "name": "prose-style",
                "content": "- [stated] Writes in close third person, past tense.\n",
                "description": "Prose style preferences",
                "aliases": ["narration", "voice"],
                "expected_version": None,
            },
        ),
        ("read_file", {"scope": "user", "area": "preferences", "name": "tea"}),
    ],
)
assert created["name"] == "prose-style" and created["sources"] == ["inkwell-api"]
assert missing["error"] == "NotFoundError" and missing["category"] == "recoverable"

[denied] = run_tool_calls("tok-expired", [("get_memory_index", {})])
assert denied["error"] == "ResolverFailureError" and denied["category"] == "permanent"

# One record per tool call; request_id is None for direct calls.
assert [(r.tool, r.is_error, r.request_id) for r in records] == [
    ("write_file", False, None),
    ("read_file", True, None),
]
print(created["version"], missing["message"])
```

## Threads and async hosts

Calls are synchronous. Under `GcsStorage` each one blocks on one or more GCS round trips; `get_memory_index` lists every object in the caller's entities unless an [index cache](storage.md#index-cache) serves it. This section applies to the MCP paths too: the MCP adapter runs tool calls concurrently on worker threads and calls one `client` from all of them.

### What can be shared

| Object | Across threads |
| --- | --- |
| `MemoryStore` | Safe. It sets its fields once in the constructor and never changes them. All its state lives in its storage and its index cache. |
| `InProcessClient` | Safe. It holds only its store. |
| `MemoryTools` | Safe; it never changes after construction. It holds one caller's identity, so share it only within that caller's request. |
| `InMemoryStorage`, `InMemoryIndexCache` | Safe. Each guards its state with a lock. |
| `GcsStorage` | Adds no state of its own: it holds the bucket and builds a new `Blob` for every call. Every call goes through the bucket's `storage.Client`. |
| `google.cloud.storage.Client` and its `Bucket` | Not guaranteed. See below. |
| Your resolver, `IndexCache` functions, `on_call`, and `clock` | Yours. If tool calls run on several threads, as they always do over MCP, each must be safe to call from several threads. |

The index cache's generation tokens already handle readers and writers racing on one entity, across threads and processes; your `get` and `set` need only be safe to call concurrently and linearizable per key ([Guarantees and limits](storage.md#cache-limits)).

**`storage.Client` is not documented as thread-safe.** google-cloud-storage 3.14.1 sends every request from a client through one `google.auth.transport.requests.AuthorizedSession`, a `requests.Session` the client creates on first use without a lock. Neither google-cloud-storage, google-auth, nor requests, as installed, says that one session is safe to share across threads, and wenchang's tests do not cover one client shared across threads. To stay within what is documented, give each thread its own `storage.Client`:

- **Direct calls.** Build the `storage.Client`, bucket, `GcsStorage`, `MemoryStore`, and `InProcessClient` once per thread, for example in a `threading.local`. Give every store the same `IndexCache`, so a write on one thread invalidates the index the others read.
- **MCP.** Pass as `client` a `TransportClient` whose seven methods forward to a per-thread `InProcessClient` built the same way. The protocol is only those seven methods, so a small forwarding class satisfies it.

### Async hosts

An async host must not call wenchang on its event loop. Run each tool call in a worker thread, for example `await asyncio.to_thread(method, **arguments)`. Call `bind_tools` in a worker thread too, `tools = await asyncio.to_thread(bind_tools, client, resolver, credentials, policy, source="inkwell-api")`, because it runs your resolver, which blocks on whatever verification it does. The resolver itself must be a plain synchronous method; an `async def resolve` is never awaited, and `bind_tools` raises `ResolverFailureError` ([Identity](identity.md#contract)).

## Observing calls

`bind_tools(..., on_call=...)` delivers one `ToolCallRecord` per tool call. On this path:

- `tool` is the bare method name, such as `read_file`.
- `arguments` holds every parameter by name, with defaults filled.
- `result` is `render_result` of the return value, or `render_error` of the raised error; `is_error` says which.
- `request_id` is `None`.
- `duration_s` is the wall time of the tool method only.

The observer runs synchronously on the calling thread, before the call returns or raises, so correlate records with a contextvar or thread-local. `bind_tools` checks `on_call` before it runs the resolver. A call Python rejects for its arguments never produces a record. An exception the observer raises is logged at ERROR and swallowed. Records contain memory content, so treat them as sensitive. The [reference](reference.md#telemetry) lists every field.

This observer logs and counts calls without recording arguments or results:

```python
import logging
import threading
from collections import Counter, defaultdict
from contextlib import suppress

from wenchang.core import MemoryStore
from wenchang.errors import NotFoundError
from wenchang.identity import Identity, SandboxResolver, ScopeGrant
from wenchang.observer import ToolCallRecord
from wenchang.scope import ScopePolicy
from wenchang.storage.memory import InMemoryStorage
from wenchang.tools import bind_tools
from wenchang.transport import InProcessClient

log = logging.getLogger("inkwell.memory")

# Stand-ins for your metrics client: a call counter and per-tool latencies.
lock = threading.Lock()
calls: Counter[tuple[str, str]] = Counter()
latencies: defaultdict[str, list[float]] = defaultdict(list)


def on_call(record: ToolCallRecord) -> None:
    # arguments and result carry memory content; log only the call's shape.
    category = record.result.get("category") if record.is_error else None
    log.info(
        "memory tool=%s is_error=%s category=%s duration_s=%.3f",
        record.tool,
        record.is_error,
        category,
        record.duration_s,
    )
    with lock:  # under MCP, observers run on worker threads
        calls[(record.tool, str(category or "ok"))] += 1
        latencies[record.tool].append(record.duration_s)


client = InProcessClient(MemoryStore(InMemoryStorage()))
resolver = SandboxResolver(Identity(grants={"user": ScopeGrant("u-tianlong", "owner")}))
tools = bind_tools(client, resolver, None, ScopePolicy({}), source="inkwell-cli", on_call=on_call)

tools.get_memory_index()  # on_call has run by the time this returns
with suppress(NotFoundError):  # on_call sees it first: is_error=True, category=recoverable
    tools.read_file("user", "preferences", "csv")
print(calls)
```

## What you provide

- **The prompt.** The model needs the memory prompt alongside the tools. Put `build_memory_prompt(slots)` from `wenchang.prompts` in your system prompt; it has `##` headings and no top-level heading. See [Customizing the prompts](prompts.md).
- **Identity.** A resolver and a scope policy. See [Identity and multi-tenant auth](identity.md).
- **Storage.** A `MemoryStore` over `GcsStorage`, or `InMemoryStorage` for tests. See [Storage and operations](storage.md).

---

HTML version: <https://msiebert.github.io/wenchang/integrate-without-mcp.html>
