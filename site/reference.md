# Reference

Version 0.1.0. Everything here is taken from the source: the tool layer (`wenchang.tools`, `wenchang.mcp`), the core store (`wenchang.core`), and the file format (`wenchang.file_format`). For how to assemble a server see [Setup](setup.md); for the prompt see [Customizing the prompts](prompts.md); for auth see [Authorization](authorization.md).

## Concepts

### Path shape

Every memory file is stored at

```
{scope}/{entity_id}/{area}/{name}.md
```

For example `project/p-ninth-examination/characters/lin-qiao.md`. Agents never write the path. The tools take `(scope, area, name)` and the tool layer fills in `entity_id` from the caller's identity grant for that scope, so a caller can only reach its own entities. Results name a file by its `scope`, `area`, and `name`; they never include the storage path.

### Scopes

A scope is an adopter-defined visibility tier. The library defines no scope names; a typical set is `user` (private), `project` (shared), and `organization` (shared, writes need an admin or owner role). A scope must be one of the scopes the session's identity has a grant for; otherwise the call fails with an `InvalidArgumentError` listing the available scopes.

### Areas

An area groups files within a scope. The tool layer requires an area to be a lowercase slug matching `^[a-z0-9][a-z0-9_-]*$`. Areas are created implicitly by writing a file in them. The prompt's `seed_areas` slot suggests starting areas; the agent may create more.

### Names

A name is the file's stem, passed without `.md`. It must be a valid path segment: non-empty, not `.` or `..`, with no `/`, backslash, or control character, and the tool layer additionally rejects invisible, separator, and noncharacter code points. Names must be valid UTF-8.

### The system/ area

Every scope has an area named exactly `system`. It holds curated content that people maintain and replace wholesale. The agent can read it (any area may be read) but every mutating tool refuses it with `RestrictedScopeError` (reason `system_read_only`). Seeding jobs and admin tooling write it through the core `MemoryStore`, which applies no restrictions. In the startup index, `system/` entries come first across all scopes.

### Fact-line format

A memory file body is made of fact lines, one per line:

```
- [stated] Has grey eyes.
```

The pattern is `- [<label>] <text>` with a non-empty text. The label records how the fact is known:

| Label | Meaning |
| --- | --- |
| `stated` | The user told the agent directly. |
| `observed` | The agent saw it in a tool result, session data, or behavior. |
| `inferred` | The agent concluded it from a pattern across several observations. |
| `system` | Curated content. The prompt tells the agent never to write a new `[system]` line. |

`append_line` accepts only a single well-formed fact line. Other lines in a body are tolerated and preserved verbatim. An end date, if the user states one, is written into the fact's text as prose; there are no per-fact timestamps.

### File metadata

Metadata is stored beside the body, as flat string custom metadata on the stored object (in GCS), not inside the markdown.

| Field | Type | Behavior |
| --- | --- | --- |
| `description` | string, one line | What the file is about. Part of the agent's search surface. `write_file` replaces it; `append_line` and `replace_fact` replace it only if one is passed. |
| `aliases` | list of strings, ordered | Other names the subject is looked up by. `write_file` replaces the whole set; `append_line` and `replace_fact` add new aliases, keeping existing ones and their order. |
| `sources` | set of strings | Surface names (the `source` you configure) that have written the file. Only ever grows; returned sorted. |
| `last_updated` | UTC timestamp | Set by the store's clock on every write; rendered as ISO 8601 with a `Z` suffix. |

There is no content search. `description` and `aliases` are the entire search surface; the agent reads the index and matches on them.

### Optimistic concurrency

Every file has an opaque `version` (the GCS generation under `GcsStorage`). Every mutating tool takes `expected_version`, the version the agent read; the write succeeds only if the file is still at that version. `write_file` with `expected_version=null` creates the file and fails if it already exists. A mismatch returns a recoverable `VersionConflictError` carrying the current content and version.

`replace_fact` re-reads and retries up to three times when a concurrent write races it, re-checking the match each time; if the file's version moved but `old_string` still matches exactly once, it applies against the current content. `append_line` has no automatic re-apply: a stale version is a conflict. Versions are opaque: never parse, compare, or order them.

### Limits

| Limit | Default | Where set |
| --- | --- | --- |
| Per-file content size | 16384 bytes (UTF-8) | `MemoryStore(max_file_bytes=...)` |
| Startup index size | 65536 bytes | `MemoryStore(index_max_bytes=...)` |
| `list_prefix` page size | 100 entries | `MemoryStore(list_page_size=...)` |
| `replace_fact` attempts | 3 | fixed |

When the index overflows its budget, the remaining files are reported under `capped` by area, with the count omitted, and the agent pages them with `list_prefix`. Index order: `system/` areas of all scopes first; then scopes in `scope_priority` order (unlisted scopes last, as one tier); within each tier, most recently updated first.

## Tools

Seven tools. With `tool_prefix` set, each is registered as `{tool_prefix}_{name}`. All results are JSON objects; all failures are rendered as described under [errors](#errors). In every tool, `scope`, `area`, and `name` are strings, and `expected_version` is a string (the `version` from a prior result).

Common file object, returned by `read_file`, `write_file`, `append_line`, and `replace_fact`:

| Field | Type | Notes |
| --- | --- | --- |
| `scope`, `area`, `name` | string | Where the file lives. |
| `content` | string | The body. Present on a file; absent on index and list entries. |
| `version` | string | Opaque. Pass as `expected_version`. |
| `description` | string | |
| `aliases` | array of strings | |
| `sources` | array of strings | Sorted. |
| `last_updated` | string | UTC ISO 8601, `Z` suffix. |

### get_memory_index

> Load the metadata index of every memory scope available in this session. Call this first. Each entry gives a file's scope, area, name, metadata, and version, without content.

Call it first in every session.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| (none) | | | |

Returns an object:

| Field | Type | Description |
| --- | --- | --- |
| `entries` | array of file entries | Each is the common file object without `content`, in index order, up to the byte budget. |
| `capped` | array of objects | One per area not fully returned. Empty means the index is complete. |

Each `capped` object has exactly `scope` (string), `area` (string), and `omitted` (integer, files left out). Page a capped area with `list_prefix(scope, area)`.

### read_file

> Read one memory file: its content, metadata, and version. Any area may be read, including `system/`.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `scope` | string | yes | A granted scope. |
| `area` | string | yes | Lowercase slug. |
| `name` | string | yes | File name without `.md`. |

Returns the common file object. If no file exists: `NotFoundError` with reason `file_absent`.

### list_prefix

> List the files in a scope or area, one page at a time, without content. Each page returns entries with metadata and version, and a `next_cursor`; until it is null, pass it back as `cursor` with the same `scope` and `area` for the next page.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `scope` | string | yes | A granted scope. |
| `area` | string or null | no (default `null`) | Restrict to one area; `null` lists the whole scope. |
| `cursor` | string or null | no (default `null`) | The `next_cursor` from the previous page, with the same `scope` and `area`. |

Returns `{"entries": [...], "next_cursor": string | null}`. Entries are the common file object without `content`, in ascending storage order. A malformed cursor, or one from a different prefix, returns `InvalidArgumentError` for `cursor`. Listing is not a snapshot: a file written or deleted between two pages may or may not appear.

### write_file

> Create a memory file or replace one whole. Pass `expected_version=None` to create a file, or the version you read to replace one. `description` (one line) and `aliases` replace the stored values; they are not merged. Content over the per-file byte ceiling is rejected with the current size and the limit; shorten it and retry. A version conflict is routine: merge your change into the content it returns and retry with its version.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `scope` | string | yes | A granted scope the caller may write. |
| `area` | string | yes | Lowercase slug; not `system`. |
| `name` | string | yes | File name without `.md`. |
| `content` | string | yes | The whole new body, at most `max_file_bytes` UTF-8 bytes. |
| `description` | string | yes | One line; replaces the stored value. |
| `aliases` | array of strings | yes | Replaces the stored set (use `[]` for none). |
| `expected_version` | string or null | yes | `null` creates (fails if the file exists); otherwise the version being replaced. |

Returns the common file object. Errors: `VersionConflictError`, `NotFoundError` (`file_absent`, when replacing a file that does not exist), `OversizeWriteError`, `InvalidArgumentError`, `RestrictedScopeError`.

### append_line

> Add one fact line to the end of an existing memory file. `line` is a single fact line with a leading bracketed label (`[stated]`, `[observed]`, `[inferred]`, or `[system]`), as in `- [stated] Prefers tea`. Pass the version you read as `expected_version`. The per-file byte ceiling applies to the result. Optional `aliases` are added to the file's existing aliases and never removed (`write_file` replaces the whole set); an optional one-line `description` replaces the stored one. A version conflict is routine: merge your change into the content it returns and retry with its version.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `scope` | string | yes | A granted scope the caller may write. |
| `area` | string | yes | Lowercase slug; not `system`. |
| `name` | string | yes | Existing file name without `.md`. |
| `line` | string | yes | One fact line, `- [label] text`. Rejected with `InvalidArgumentError` otherwise. |
| `expected_version` | string | yes | The version read. |
| `aliases` | array of strings or null | no (default `null`) | Added to existing aliases, never removed. |
| `description` | string or null | no (default `null`) | Replaces the stored description when given. |

The file must already exist (`NotFoundError` with `file_absent` otherwise). A newline is added before the line if the body does not end with one, and one after. Returns the common file object.

### replace_fact

> Change one fact in a memory file by quoting the text to replace. `old_string` must match the content exactly once; otherwise the error carries the current content and version, so quote a unique span. `new_string` replaces it. Pass the version you read as `expected_version`. The per-file byte ceiling applies to the result. Optional `aliases` are added to the file's existing aliases and never removed (`write_file` replaces the whole set); an optional one-line `description` replaces the stored one. A version conflict is routine: merge your change into the content it returns and retry with its version.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `scope` | string | yes | A granted scope the caller may write. |
| `area` | string | yes | Lowercase slug; not `system`. |
| `name` | string | yes | Existing file name without `.md`. |
| `old_string` | string | yes | Non-empty text that appears exactly once in the file. |
| `new_string` | string | yes | Replacement. An empty string removes the span (to drop a whole fact line, quote the line including its line break). |
| `expected_version` | string | yes | The version read. |
| `aliases` | array of strings or null | no (default `null`) | Added to existing aliases, never removed. |
| `description` | string or null | no (default `null`) | Replaces the stored description when given. |

Zero or several matches return `ReplaceFactMatchError` with the current content, version, and `match_count`. Returns the common file object.

### delete_file

> Delete a memory file. Pass the version you read as `expected_version`. A version conflict is routine: retry with the version it returns only if the file should still go.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `scope` | string | yes | A granted scope the caller may write. |
| `area` | string | yes | Lowercase slug; not `system`. |
| `name` | string | yes | File name without `.md`. |
| `expected_version` | string | yes | The version read. |

Returns `{"ok": true}`. Errors: `VersionConflictError`, `NotFoundError`, `RestrictedScopeError`.

## The memory prompt resource

The server exposes the assembled memory prompt as an MCP resource:

| Property | Value |
| --- | --- |
| URI | `wenchang://memory-prompt` (`wenchang.mcp.PROMPT_RESOURCE_URI`) |
| Name | `memory_prompt` |
| MIME type | `text/markdown` |
| Content | The same text as the server's `instructions`: `build_memory_prompt(slots)`. |

Clients that drop server `instructions` can read the resource instead. The prompt is markdown with `##` headings and no H1; see [Customizing the prompts](prompts.md#fixed) for its sections.

## Errors

A failed tool call returns an MCP error result (`isError` true) whose JSON payload has this shape:

```json
{
  "error": "VersionConflictError",
  "category": "recoverable",
  "message": "...",
  "scope": "...",
  "area": "...",
  "name": "...",
  "content": "...",
  "version": "..."
}
```

`error` is the class name, `category` is `recoverable`, `permanent`, `transient`, or `internal`, and `message` combines the detail with fixed guidance for the category. Extra fields appear only when relevant. When the location parses, the payload carries `scope`, `area`, and `name`, and the message names it as `scope user, area preferences, name csv`. Errors never include a storage path.

| Category | Meaning | What the agent should do |
| --- | --- | --- |
| `recoverable` | Normal coordination. | Correct the call from the attached details and retry in the same turn, without asking the user. |
| `permanent` | The call cannot succeed as given. | Do not retry. |
| `transient` | A temporary condition. | Retry. Version-guarded calls are safe to retry; a retried `append_line` may duplicate a line. |
| `internal` | An unexpected failure, or corrupt stored data. | The payload carries only a generic message (or, for corrupt metadata or a non-UTF-8 body, that error's message). |

| Error | Category | Raised when | Extra fields |
| --- | --- | --- | --- |
| `VersionConflictError` | recoverable | The file changed since it was read. | `content`, `version` (current) |
| `OversizeWriteError` | recoverable | The resulting content exceeds the per-file limit. | `size`, `limit` |
| `ReplaceFactMatchError` | recoverable | `old_string` matched zero spans or more than one. | `content`, `version`, `match_count` |
| `InvalidArgumentError` | recoverable | An argument was rejected: unknown scope, bad area slug, bad name, not a fact line, empty `old_string`, bad cursor, and similar. | `argument` |
| `NotFoundError` | recoverable | The location is invalid (`invalid_path`) or no file exists there (`file_absent`). | `reason` |
| `RestrictedScopeError` | permanent | A write to `system/` (`system_read_only`), or to a scope whose policy requires another role (`role_required`), or outside the caller's grant (`not_granted`). | `scope`, `reason`, and `required_roles` for `role_required` |
| `ResolverFailureError` | permanent | The identity could not be resolved, or `credentials_from_context` raised. Memory is unavailable for the session. | none |
| `BackendUnavailableError` | transient | The storage backend timed out or is unreachable. | `reason` (`timeout` or `unavailable`) |

Notes:

- The tool layer builds each path from the caller's own grants, so over MCP an ungranted scope is reported as `InvalidArgumentError` (naming the available scopes); `not_granted` is raised by the core path check.
- MCP validates arguments before wenchang sees them. A wrong-type or missing argument returns MCP's own error text, not a rendered wenchang error.
- MCP pre-parses JSON-like strings: the string `"null"` arrives as `None` for a nullable parameter. For example `list_prefix(area="null")` lists the whole scope.

## Configuration

### Identity types

`wenchang.identity.Identity(grants)` is what a resolver returns: a mapping from scope name to `ScopeGrant(entity_id, role)`. Scope names and entity IDs must be valid path segments (non-empty, no `/`, no backslash, no control characters, not `.` or `..`). The role must be non-empty. `identity.scope_map` is scope name to entity ID. `identity.entity_id(scope)` and `identity.role(scope)` raise `KeyError` if the scope is not granted.

`IdentityResolver[C]` is a protocol with one method, `resolve(credentials: C) -> Identity | ResolutionFailure`. It must not raise, and the `detail` of a `ResolutionFailure` is shown to the agent. `SandboxResolver(identity)` returns one fixed identity for any credentials, for sandboxes and tests.

`wenchang.scope.ScopePolicy(write_roles)` maps a scope to the `frozenset` of roles allowed to write it. A scope absent from the mapping is unrestricted. `policy.permitted_roles(scope)` returns the set or `None`.

### Store options

`wenchang.core.MemoryStore(storage, *, max_file_bytes=16384, clock=..., list_page_size=100, index_max_bytes=65536, scope_priority=())`. The three size options must be positive. `scope_priority` entries must be distinct valid path segments, and the scopes it lists are kept first when the startup index is capped; unlisted scopes rank after them, and `system/` areas always come first. `clock` returns timezone-aware datetimes and stamps `last_updated`; pass a fixed one in tests. A write over `max_file_bytes` raises `OversizeWriteError`.

```python
from datetime import UTC, datetime

from wenchang.core import MemoryStore
from wenchang.storage.memory import InMemoryStorage
from wenchang.transport import InProcessClient

store = MemoryStore(
    InMemoryStorage(),
    max_file_bytes=8 * 1024,  # default 16384: larger writes raise OversizeWriteError
    index_max_bytes=32 * 1024,  # default 65536: the startup index is capped at this size
    list_page_size=50,  # default 100: entries per list_prefix page
    scope_priority=("user", "project", "organization"),  # which scopes the capped index keeps first
    clock=lambda: datetime.now(UTC),  # must return timezone-aware datetimes
)
client = InProcessClient(store)
print(store.index_max_bytes, store.scope_priority)
```

### Storage backends

`wenchang.storage.Storage` is the only way the rest of wenchang touches bytes. It is a protocol over objects with a string key, bytes, a flat string metadata map, and an opaque version token:

| Method | Contract |
| --- | --- |
| `get(key)` | The object at exactly `key`, or `None`. |
| `put(key, data, metadata)` | Unconditional atomic replace; returns a new version token. |
| `put_if_version(key, data, metadata, expected)` | Replace only if the current version equals `expected`; `expected=None` means create, and must not exist. Otherwise raises `PreconditionFailedError` and changes nothing. |
| `delete_if_version(key, expected)` | Delete only at `expected`; otherwise `PreconditionFailedError`. |
| `list_page(prefix, start_after, limit)` | Up to `limit` objects whose key starts with `prefix`, ascending by key, never reading bodies. |

Backends may raise `BackendUnavailableError` for timeouts and outages. Two ship with the library:

- **`GcsStorage(bucket)`** in `wenchang.storage.gcs` takes a `google.cloud.storage.Bucket`. One bucket is one storage instance. Metadata is GCS custom object metadata, the version is the object's generation, and conditional writes use generation preconditions.
- **`InMemoryStorage()`** in `wenchang.storage.memory` is a thread-safe fake for tests and trials.

### Transport

The tool layer calls a `wenchang.transport.TransportClient`, a protocol that mirrors `MemoryStore`'s seven operations. `InProcessClient(store)` calls a `MemoryStore` directly and is the only client shipped. The client you pass to the MCP adapter must be thread-safe, because tool calls run concurrently on worker threads.

### Add the tools to an existing MCP server

`build_server` creates a new `MCPServer`. To add memory to a server you already run, with your own auth, middleware, and tools, use `register_memory_tools`. It adds the seven tools and the `wenchang://memory-prompt` resource. It raises before registering anything if an argument is invalid or a tool name or the resource URI is already registered. Pass the same text as the server's `instructions` that you pass as `prompt`; `memory_instructions(slots)` returns it. If the server's instructions do not contain the prompt, a warning is logged.

```python
import logging

from mcp.server.mcpserver import Context, MCPServer

from wenchang.core import MemoryStore
from wenchang.identity import Identity, SandboxResolver, ScopeGrant
from wenchang.mcp import ToolCallRecord, memory_instructions, register_memory_tools
from wenchang.prompts import PromptSlots
from wenchang.scope import ScopePolicy
from wenchang.storage.memory import InMemoryStorage
from wenchang.transport import InProcessClient

log = logging.getLogger("inkwell.calls")

slots = PromptSlots(
    purpose="You have persistent memory of your work helping an author write a novel.",
    scope_guidance=(
        "There is one scope, user, and it is private to the author you are talking with."
    ),
    seed_areas="- user: preferences, workflows, research\n\nEvery scope also has a `system/` area.",
)
identity = Identity(grants={"user": ScopeGrant("u-tianlong", "owner")})


def credentials_from_context(ctx: Context) -> str | None:
    # Over HTTP, return the raw credential and let your resolver verify it.
    # ctx.headers is None on stdio.
    return (ctx.headers or {}).get("authorization")


def on_call(record: ToolCallRecord) -> None:
    # Runs on worker threads after every call; keep it fast and thread-safe.
    log.info("%s error=%s %.3fs", record.tool, record.is_error, record.duration_s)


prompt = memory_instructions(slots)

# Your existing server, with your own tools and middleware.
server = MCPServer("hanlin-tools", instructions=prompt)

register_memory_tools(
    server,
    prompt=prompt,
    client=InProcessClient(MemoryStore(InMemoryStorage())),
    resolver=SandboxResolver(identity),
    policy=ScopePolicy({}),
    credentials_from_context=credentials_from_context,
    source="hanlin-tools",
    product="Inkwell",
    tool_prefix="inkwell",  # tools are registered as inkwell_read_file, inkwell_write_file, ...
    on_call=on_call,
)
```

### Telemetry

Both entry points take an `on_call` observer: `register_memory_tools(..., on_call=...)` and `build_server` for MCP, and `bind_tools(..., on_call=...)` (or `MemoryTools(..., on_call=...)`) for direct calls. It receives a `wenchang.observer.ToolCallRecord` after every memory tool call. `wenchang.mcp` re-exports `ToolCallRecord`.

| Field | MCP | Direct call |
| --- | --- | --- |
| `tool` | Registered tool name, prefix included. | Bare method name, such as `read_file`. |
| `arguments` | The arguments the wrapper received. | Every parameter by name, defaults filled. |
| `result` | A copy of the payload sent to the client. | `render_result` of the return value, or `render_error` of the raised error. |
| `is_error` | Whether `result` is a rendered error. | Same. |
| `request_id` | The MCP request's ID, for correlating records that arrive in completion order. | `None`. |
| `duration_s` | Wall time of the wrapper (credentials, binding, the tool, rendering). | Wall time of the tool method only. |

`arguments` and `result` are read-only deep copies, and `duration_s` uses a monotonic clock. Calls rejected during argument validation never produce a record.

`on_call` must be a plain (non-async) function. An exception it raises is logged at ERROR and swallowed; it never changes the tool's result or exception. For direct calls it runs synchronously on the calling thread, before the call returns or raises, so correlate records with a contextvar or thread-local. Under MCP it runs on worker threads, so it must be thread-safe and fast. Records contain memory content, so treat them as sensitive.

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

### Using the tools without MCP

`wenchang.tools.bind_tools(client, resolver, credentials, policy, *, source, product=None, on_call=None)` resolves the identity and returns a `MemoryTools` for one session. `on_call` is a tool-call observer; see [Telemetry](#telemetry). `tools.tools()` is the seven bound methods by name, and `tools.descriptions()` is the description for each. Register each tool with its description from `descriptions()` rather than its docstring. `render_result` and `render_error` in `wenchang.tools` produce the JSON-safe dicts the MCP adapter returns.

```python
from wenchang.core import MemoryStore
from wenchang.identity import Identity, SandboxResolver, ScopeGrant
from wenchang.scope import ScopePolicy
from wenchang.storage.memory import InMemoryStorage
from wenchang.tools import bind_tools
from wenchang.transport import InProcessClient

client = InProcessClient(MemoryStore(InMemoryStorage()))
resolver = SandboxResolver(Identity(grants={"user": ScopeGrant("u-tianlong", "owner")}))

# One MemoryTools per session; resolving the identity happens here.
tools = bind_tools(client, resolver, None, ScopePolicy({}), source="inkwell-cli", product="Inkwell")

descriptions = tools.descriptions()  # tool name -> description, product named in the first line
for name, fn in tools.tools().items():  # the seven tools, as bound methods
    print(name, fn.__name__, "-", descriptions[name].splitlines()[0])

print(tools.get_memory_index())
```

### Conformance suites

`pip install "wenchang[testing]"` adds `pytest` and two mixins in `wenchang.testing`:

- **`ResolverConformance[C]`** checks an `IdentityResolver`. Supply fixtures `resolver`, `valid_credentials`, `invalid_credentials` (call `pytest.skip` if your resolver accepts everything), `policy`, `expected_scopes`, and `known_roles`.
- **`TransportConformance`** checks a `TransportClient`. Supply fixtures `client` (fresh and empty per test), `source`, `scope_map` (at least two writable scopes), `max_file_bytes` (at least 64), `index_max_bytes` (at least 1024), `scope_priority`, and `list_page_size`. Within one test the client's writes must stamp strictly increasing `last_updated` values.

Name your subclasses with a `Test` prefix. This example passes against the shipped `InProcessClient`:

```python
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import pytest

from wenchang.core import MemoryStore
from wenchang.identity import Identity, IdentityResolver, ResolutionFailure, ScopeGrant
from wenchang.scope import ScopePolicy
from wenchang.storage.memory import InMemoryStorage
from wenchang.testing import ResolverConformance, TransportConformance
from wenchang.transport import InProcessClient, TransportClient

POLICY = ScopePolicy({"organization": frozenset({"admin", "owner"})})


class MyResolver:
    def resolve(self, credentials: str) -> Identity | ResolutionFailure:
        if credentials != "tok-tianlong":
            return ResolutionFailure("unknown token")
        return Identity(
            grants={
                "user": ScopeGrant("u-tianlong", "owner"),
                "organization": ScopeGrant("o-hanlin-press", "admin"),
            }
        )


class TestMyResolver(ResolverConformance[str]):
    @pytest.fixture
    def resolver(self) -> IdentityResolver[str]:
        return MyResolver()

    @pytest.fixture
    def valid_credentials(self) -> str:
        return "tok-tianlong"

    @pytest.fixture
    def invalid_credentials(self) -> str:
        return "tok-nobody"

    @pytest.fixture
    def policy(self) -> ScopePolicy:
        return POLICY

    @pytest.fixture
    def expected_scopes(self) -> frozenset[str]:
        return frozenset({"user", "organization"})

    @pytest.fixture
    def known_roles(self) -> frozenset[str]:
        return frozenset({"owner", "admin", "member"})


class _Ticking:
    """A clock whose every call is strictly later than the last."""

    def __init__(self) -> None:
        self._n = 0

    def __call__(self) -> datetime:
        self._n += 1
        return datetime(2024, 1, 1, tzinfo=UTC) + timedelta(microseconds=self._n)


class TestMyClient(TransportConformance):
    @pytest.fixture
    def client(self) -> TransportClient:
        return InProcessClient(
            MemoryStore(
                InMemoryStorage(),
                clock=_Ticking(),
                max_file_bytes=256,
                index_max_bytes=4096,
                scope_priority=("user", "organization"),
                list_page_size=2,
            )
        )

    @pytest.fixture
    def source(self) -> str:
        return "conformance"

    @pytest.fixture
    def scope_map(self) -> Mapping[str, str]:
        return {"user": "u-tianlong", "organization": "o-hanlin-press"}

    @pytest.fixture
    def max_file_bytes(self) -> int:
        return 256

    @pytest.fixture
    def index_max_bytes(self) -> int:
        return 4096

    @pytest.fixture
    def scope_priority(self) -> tuple[str, ...]:
        return ("user", "organization")

    @pytest.fixture
    def list_page_size(self) -> int:
        return 2
```

## Limitations and status

- **Status.** Version 0.1.0, MIT license, Python 3.12 or newer. Installed from git; no PyPI release is documented.
- **A library, not a server.** There is no CLI, console script, or ready-made server binary. You supply the identity resolver, scope policy, prompt slots, and a short server script. The only server in the repository is the dev-only eval server (`python -m evals.server`), which uses in-memory storage.
- **No content search.** Files are found through `description` and `aliases`. The quality of that metadata is what makes recall work.
- **Not snapshots.** `list_prefix` and `get_memory_index` are not point-in-time snapshots: a file written or deleted while an index is being built may or may not appear.
- **Remote transport is planned.** Today the only client is `InProcessClient`; the `TransportClient` protocol is the seam for a remote one.
- **Reads are never role-restricted.** A caller can read any area (including `system/`) of any scope it holds a grant for. `ScopePolicy` gates writes only.
- **Privacy is prompt-level.** The prompt tells the agent to refuse financial account numbers, health diagnoses, and anything indicating the user is a minor, and to be stricter in shared scopes. No tool checks content, so a successful write does not mean the content was safe.
- **Behavior depends on the agent.** Where facts get filed, and how well, is up to the model following the prompt. The repository's behavioral evals run scripted scenarios against a real agent and grade what it stored; they are signal for prompt iteration, not release gates.
- **Tool calls run concurrently** on worker threads, so the transport client (and `on_call`) must be thread-safe.

---

HTML version: <https://msiebert.github.io/wenchang/reference.html>
