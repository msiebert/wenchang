# Customize

wenchang owns the generic memory prompt, the tools, and the storage rules. You supply what is specific to your deployment: who the caller is, which scopes exist and who may write them, the text that tells the agent about them, and where bytes live.

For a complete, realistic configuration, read the reference adopter, [`evals/reference_adopter.py`](https://github.com/msiebert/wenchang/blob/main/evals/reference_adopter.py). It defines three scopes (`user`, `project`, `organization`), prompt slots, a write policy, four identities, and seed content, and imports only public wenchang modules. The examples below are based on it and have been run.

## Scopes and identity

A **scope** is a visibility tier you define, such as `user`, `project`, or `organization`. Scope names are plain path segments; wenchang has no built-in scopes. Within a scope, an **entity ID** says whose copy it is: `user/u-ada/...` and `user/u-grace/...` are different users' private memory.

### Identity, ScopeGrant

`wenchang.identity.Identity(grants)` is what a resolver returns: a mapping from scope name to `ScopeGrant(entity_id, role)`. Both strings must be valid path segments (non-empty, no `/`, no backslash, no control characters, not `.` or `..`), and the role must be non-empty. Roles are your own vocabulary (`owner`, `member`, `admin`). An identity can reach only the scopes it holds grants for, and only its own entity within each.

- `identity.scope_map`: scope name to entity ID, as a new dict.
- `identity.entity_id(scope)` and `identity.role(scope)`: raise `KeyError` if not granted.

### IdentityResolver

`IdentityResolver[C]` is a protocol with one method: `resolve(credentials: C) -> Identity | ResolutionFailure`. It turns whatever your `credentials_from_context` returns into an `Identity`. Rules:

- It must not raise. Report bad or unverifiable credentials as `ResolutionFailure(detail)`. The `detail` is shown to the agent, so it must never contain credentials.
- Identical credentials must give an equal result within a session.
- It runs on every tool call. Cache inside it if resolution is expensive.

If a resolver raises or returns something else, the call fails with a permanent `ResolverFailureError` that reports only the exception type, never its message.

`SandboxResolver(identity)` returns one fixed identity for any credentials. Use it for sandboxes and tests.

### ScopePolicy

`wenchang.scope.ScopePolicy(write_roles)` maps a scope to the `frozenset` of roles allowed to write it. A scope absent from the mapping is unrestricted. The policy restricts writes only: reads are never role-restricted. A role outside the set gets a permanent `RestrictedScopeError` with reason `role_required` and the permitted roles in `required_roles`. The `system/` area is read-only in every scope regardless of policy.

```python
from collections.abc import Mapping
from dataclasses import dataclass

from wenchang.identity import Identity, ResolutionFailure, ScopeGrant, resolve_identity
from wenchang.scope import ScopePolicy


@dataclass(frozen=True)
class Session:
    user_id: str
    project_id: str
    org_id: str
    org_role: str  # "member", "admin", or "owner"


class TokenResolver:
    """Maps a bearer token to an Identity. Must not raise."""

    def __init__(self, sessions: Mapping[str, Session]) -> None:
        self._sessions = sessions

    def resolve(self, credentials: str | None) -> Identity | ResolutionFailure:
        session = self._sessions.get(credentials or "")
        if session is None:
            return ResolutionFailure("Unknown or missing credential.")
        return Identity(
            grants={
                "user": ScopeGrant(session.user_id, "owner"),
                "project": ScopeGrant(session.project_id, "member"),
                "organization": ScopeGrant(session.org_id, session.org_role),
            }
        )


# Only admins and owners may write the organization scope; user and project are open.
policy = ScopePolicy({"organization": frozenset({"admin", "owner"})})

resolver = TokenResolver({"tok-ada": Session("u-ada", "p-checkout", "o-acme", "member")})
identity = resolve_identity(resolver, "tok-ada")
print(identity.scope_map)  # {'user': 'u-ada', 'project': 'p-checkout', 'organization': 'o-acme'}
print(policy.permitted_roles("organization"), policy.permitted_roles("user"))
```

### Credentials over HTTP

`credentials_from_context(ctx)` is a plain (non-async) function that returns the caller's raw credentials from the MCP request. Over HTTP transports `ctx.headers` carries the request headers; on stdio it is `None`, so a stdio server reads its credential from process configuration instead (for example an environment variable that your own script reads). Headers are client-supplied: return the raw credential and let the resolver verify it. If `credentials_from_context` raises, the call fails with a permanent "memory unavailable" error, and only the exception type is logged.

```python
from mcp.server.mcpserver import Context

from wenchang.core import MemoryStore
from wenchang.identity import Identity, ResolutionFailure, ScopeGrant
from wenchang.mcp import build_server
from wenchang.prompts import PromptSlots
from wenchang.scope import ScopePolicy
from wenchang.storage.memory import InMemoryStorage
from wenchang.transport import InProcessClient


class BearerResolver:
    """Verifies a bearer token and returns the caller's grants. Must not raise."""

    def resolve(self, credentials: str | None) -> Identity | ResolutionFailure:
        if credentials != "Bearer secret-token":  # replace with real verification
            return ResolutionFailure("Missing or invalid bearer token.")
        return Identity(grants={"user": ScopeGrant("u-ada", "owner")})


def credentials_from_context(ctx: Context) -> str | None:
    # Headers are client-supplied: return the raw credential and let the resolver verify it.
    return (ctx.headers or {}).get("authorization")


server = build_server(
    slots=PromptSlots(
        purpose="You have persistent memory of your work with this user.",
        scope_guidance=(
            "There is one scope, user, and it is private to the person you are talking with."
        ),
        seed_areas="- user: preferences, workflows\n\nEvery scope also has a `system/` area.",
    ),
    client=InProcessClient(MemoryStore(InMemoryStorage())),
    resolver=BearerResolver(),
    policy=ScopePolicy({}),
    credentials_from_context=credentials_from_context,
    source="my-service",
)

if __name__ == "__main__":
    server.run("streamable-http")
```

This snippet builds the server; it was not run against a live HTTP client.

## Prompt slots

`wenchang.prompts.PromptSlots` holds the adopter-specific text inserted into the generic prompt. All fields are strings, stored stripped, and must not be empty or whitespace-only.

| Field | Required | What to put there |
| --- | --- | --- |
| `purpose` | yes | One or two sentences naming the product and when to use memory. Opens the first section, "Memory". |
| `scope_guidance` | yes | Which scopes exist, which are shared and which private, who may write each, and any ask-before-write, contradiction, containment, or scope-test rules, with examples. |
| `seed_areas` | yes | Starting area names per scope as lowercase slugs, and which scopes have a `system/` area. |
| `systems_of_record` | no (default `None`) | Which systems hold canonical information and how to refer to their objects. `None` omits the whole section. |

The generic sections refer only to "shared scope", "private scope", and "the `system/` area", so `scope_guidance` must say which of your scopes are shared and which are private. Slots state deployment facts only; the generic sections already say that areas are extensible, what `system/` means, and that systems of record are never copied into memory.

`build_memory_prompt(slots)` returns markdown with `##` headings and no H1, so a host can nest it in its own system prompt. `SECTION_ORDER` lists the section ids in assembly order; sections with an empty body are skipped.

| Section id (`SECTION_ORDER`) | Heading in the prompt |
| --- | --- |
| `overview` | Memory (your `purpose`, then the generic overview) |
| `scope_guidance` | Scopes (your text) |
| `seed_areas` | Seed areas (your text) |
| `systems_of_record` | Systems of record (generic principle, then your text; omitted when `None`) |
| `applying_memory` | Applying memory |
| `remembering` | Deciding what to remember |
| `privacy` | What never to store |
| `filing` | Filing |
| `write_mechanics` | Choosing a write tool |
| `curated_content` | Curated content |
| `forgetting` | Forgetting |

```python
from wenchang.prompts import SECTION_ORDER, PromptSlots, build_memory_prompt

slots = PromptSlots(
    purpose=(
        "You have persistent memory of your work in Acme Analytics: reference it and save to it "
        "with these tools whenever you work with Acme."
    ),
    scope_guidance=(
        "There are two scopes: user and project.\n\n"
        "- user is private: it belongs to the person you are talking with.\n"
        "- project is shared with every member of the current project; any member may write to "
        "it.\n\n"
        "Before saving a new fact to project, ask the user and name the scope. If a new fact "
        "contradicts one stored in project, show the stored fact, say what conflicts, and ask "
        "which to keep."
    ),
    seed_areas=(
        "- user: preferences, workflows, people\n"
        "- project: metrics, conventions, glossary\n\n"
        "Every scope also has a `system/` area."
    ),
    # Optional. None omits the whole section.
    systems_of_record=(
        "- Dashboards are objects with IDs; refer to one by name and ID, and store what it is "
        "used for and what people have said about it."
    ),
)

print(SECTION_ORDER)
prompt = build_memory_prompt(slots)
print([line for line in prompt.splitlines() if line.startswith("## ")])
```

Scope priority is not a slot: it is `MemoryStore(scope_priority=...)`, and it orders only the capped startup index.

## Product, tool prefix, and source

These three arguments (to `build_server`, `register_memory_tools`, and `bind_tools`) name your deployment:

- **`product`** (optional): names your product in the first line of each tool description, so each tool says whose memory it is. With `product="Mixpanel"`, `append_line` begins "Add one fact line to the end of an existing Mixpanel memory file."; without it, descriptions are the tools' docstrings. It must be one non-empty line.
- **`tool_prefix`** (optional, MCP only): registers the tools as `{tool_prefix}_get_memory_index`, `{tool_prefix}_read_file`, and so on. It must be 1 to 64 characters of letters, digits, `_`, or `-`, starting and ending with a letter or digit. Useful when an existing server already has tools of those names or hosts several memories.
- **`source`** (required, non-empty): the surface name stamped into each written file's `sources` metadata, so you can tell which product surface wrote what.

## Store limits

`wenchang.core.MemoryStore(storage, *, max_file_bytes=16384, clock=..., list_page_size=100, index_max_bytes=65536, scope_priority=())`:

| Argument | Default | Effect |
| --- | --- | --- |
| `max_file_bytes` | `16384` | UTF-8 size ceiling for one file's content. A larger write raises `OversizeWriteError` with the size and the limit; the prompt tells the agent to split into narrower files. |
| `index_max_bytes` | `65536` | Byte budget for the startup index (each entry counts its path, metadata, and version). Entries beyond it are reported under `capped` by area prefix, to be paged with `list_prefix`. |
| `list_page_size` | `100` | Entries per `list_prefix` page. |
| `scope_priority` | `()` | Scopes in the order the capped index keeps them. Unlisted scopes rank after listed ones; with none configured, every scope ranks equally. `system/` areas always come first. |
| `clock` | UTC now | Returns timezone-aware datetimes; stamps `last_updated`. Pass a deterministic clock in tests. |

`max_file_bytes`, `list_page_size`, and `index_max_bytes` must be positive. `scope_priority` entries must be distinct valid path segments.

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

## Storage backends

`wenchang.storage.Storage` is the only way the rest of wenchang touches bytes. It is a structural protocol over objects with a flat string key, bytes, a flat string metadata map, and an opaque version token:

| Method | Contract |
| --- | --- |
| `get(key)` | The object at exactly `key`, or `None`. |
| `put(key, data, metadata)` | Unconditional atomic replace; returns a new version token. |
| `put_if_version(key, data, metadata, expected)` | Replace only if the current version equals `expected`; `expected=None` means create, and must not exist. Otherwise raises `PreconditionFailedError` and changes nothing. |
| `delete_if_version(key, expected)` | Delete only at `expected`; otherwise `PreconditionFailedError`. |
| `list_page(prefix, start_after, limit)` | Up to `limit` objects whose key starts with `prefix`, ascending by key, never reading bodies. |

Backends may raise `BackendUnavailableError` for timeouts and outages.

- **`GcsStorage(bucket)`** in `wenchang.storage.gcs` is the production backend. It takes a `google.cloud.storage.Bucket`. One bucket is one storage instance. Metadata is GCS custom object metadata, the version is the object's generation, and conditional writes use generation preconditions. See the [quickstart](quickstart.md#gcs).
- **`InMemoryStorage()`** in `wenchang.storage.memory` is a thread-safe in-process fake. Its tokens are a shared counter, like generations. For tests and trials.

## Transport

The tool layer calls a `wenchang.transport.TransportClient`, a protocol that mirrors `MemoryStore`'s seven operations (`read_file`, `write_file`, `append_line`, `replace_fact`, `list_prefix`, `delete_file`, `get_memory_index`). Implementations must be behaviorally indistinguishable: the same results and the same exception types and payloads, with a failure of the transport itself surfacing as `BackendUnavailableError`.

`InProcessClient(store)` calls a `MemoryStore` directly, with no network hop. It is the only client shipped; a remote transport is planned. The client you pass to the MCP adapter must be thread-safe, because tool calls run concurrently on worker threads.

## Embed in an existing MCP server

`build_server` creates a new `MCPServer`. To add memory to a server you already run, with your own auth, middleware, and tools, use `register_memory_tools`. It adds the seven tools and the `wenchang://memory-prompt` resource, and raises before registering anything if an argument is invalid or a tool name or the resource URI is already registered.

Pass the same text as the server's `instructions` that you pass as `prompt`: `memory_instructions(slots)` returns it. If the server's instructions do not contain the prompt, a warning is logged.

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

log = logging.getLogger("memory.calls")

slots = PromptSlots(
    purpose="You have persistent memory of your work with this user.",
    scope_guidance=(
        "There is one scope, user, and it is private to the person you are talking with."
    ),
    seed_areas="- user: preferences, workflows\n\nEvery scope also has a `system/` area.",
)
identity = Identity(grants={"user": ScopeGrant("u-me", "owner")})


def credentials_from_context(ctx: Context) -> str | None:
    # Over HTTP, return the raw credential and let your resolver verify it.
    # ctx.headers is None on stdio.
    return (ctx.headers or {}).get("authorization")


def on_call(record: ToolCallRecord) -> None:
    # Runs on worker threads after every call; keep it fast and thread-safe.
    log.info("%s error=%s %.3fs", record.tool, record.is_error, record.duration_s)


prompt = memory_instructions(slots)

# Your existing server, with your own tools and middleware.
server = MCPServer("my-host", instructions=prompt)

register_memory_tools(
    server,
    prompt=prompt,
    client=InProcessClient(MemoryStore(InMemoryStorage())),
    resolver=SandboxResolver(identity),
    policy=ScopePolicy({}),
    credentials_from_context=credentials_from_context,
    source="my-host",
    product="Acme",
    tool_prefix="acme",  # tools are registered as acme_read_file, acme_write_file, ...
    on_call=on_call,
)
```

## Telemetry

`on_call`, if given, receives a `wenchang.mcp.ToolCallRecord` after every memory tool call:

| Field | Meaning |
| --- | --- |
| `tool` | Registered tool name, prefix included. |
| `arguments` | The arguments the wrapper received (read-only mapping). |
| `result` | A copy of the payload sent to the client (read-only mapping). |
| `is_error` | Whether the payload is a rendered error. |
| `request_id` | The MCP request's ID, for correlating records that arrive in completion order. |
| `duration_s` | Wall time of the wrapper, on a monotonic clock. |

The callback runs on worker threads, so it must be a plain function (not async), fast, and thread-safe. An exception it raises is logged and swallowed. Calls the MCP layer rejects during argument validation never produce a record. Records contain the agent's arguments and results, which include memory content: treat them as sensitive.

## Using the tools without MCP

`wenchang.tools.bind_tools(client, resolver, credentials, policy, *, source, product=None)` resolves the identity and returns a `MemoryTools` for one session. `tools.tools()` is the seven bound methods by name; `tools.descriptions()` is the description for each, with the product named in the first line. Register each tool with its description from `descriptions()` rather than its docstring. `render_result` and `render_error` (in `wenchang.tools`) produce the JSON-safe dicts the MCP adapter returns.

```python
from wenchang.core import MemoryStore
from wenchang.identity import Identity, SandboxResolver, ScopeGrant
from wenchang.scope import ScopePolicy
from wenchang.storage.memory import InMemoryStorage
from wenchang.tools import bind_tools
from wenchang.transport import InProcessClient

client = InProcessClient(MemoryStore(InMemoryStorage()))
resolver = SandboxResolver(Identity(grants={"user": ScopeGrant("u-me", "owner")}))

# One MemoryTools per session; resolving the identity happens here.
tools = bind_tools(client, resolver, None, ScopePolicy({}), source="my-agent", product="Acme")

descriptions = tools.descriptions()  # tool name -> description, product named in the first line
for name, fn in tools.tools().items():  # the seven tools, as bound methods
    print(name, fn.__name__, "-", descriptions[name].splitlines()[0])

print(tools.get_memory_index())
```

## Conformance suites

`pip install "wenchang[testing]"` (adds `pytest`) provides two pytest mixins in `wenchang.testing` for code you write:

- **`ResolverConformance[C]`** checks an `IdentityResolver`. Supply fixtures `resolver`, `valid_credentials`, `invalid_credentials` (call `pytest.skip` if your resolver accepts everything), `policy`, `expected_scopes`, and `known_roles`.
- **`TransportConformance`** checks a `TransportClient`. Supply fixtures `client` (fresh and empty per test), `source`, `scope_map` (at least two writable scopes), `max_file_bytes` (at least 64), `index_max_bytes` (at least 1024), `scope_priority`, and `list_page_size`. Within one test the client's writes must stamp strictly increasing `last_updated` values.

Name your subclasses with a `Test` prefix. Passing every test defines a conforming implementation. This example passes against the shipped `InProcessClient`:

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

POLICY = ScopePolicy({"org": frozenset({"admin", "owner"})})


class MyResolver:
    def resolve(self, credentials: str) -> Identity | ResolutionFailure:
        if credentials != "good-token":
            return ResolutionFailure("unknown token")
        return Identity(
            grants={"user": ScopeGrant("u-1", "owner"), "org": ScopeGrant("o-9", "admin")}
        )


class TestMyResolver(ResolverConformance[str]):
    @pytest.fixture
    def resolver(self) -> IdentityResolver[str]:
        return MyResolver()

    @pytest.fixture
    def valid_credentials(self) -> str:
        return "good-token"

    @pytest.fixture
    def invalid_credentials(self) -> str:
        return "bad-token"

    @pytest.fixture
    def policy(self) -> ScopePolicy:
        return POLICY

    @pytest.fixture
    def expected_scopes(self) -> frozenset[str]:
        return frozenset({"user", "org"})

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
                scope_priority=("user", "org"),
                list_page_size=2,
            )
        )

    @pytest.fixture
    def source(self) -> str:
        return "conformance"

    @pytest.fixture
    def scope_map(self) -> Mapping[str, str]:
        return {"user": "u-1", "org": "o-9"}

    @pytest.fixture
    def max_file_bytes(self) -> int:
        return 256

    @pytest.fixture
    def index_max_bytes(self) -> int:
        return 4096

    @pytest.fixture
    def scope_priority(self) -> tuple[str, ...]:
        return ("user", "org")

    @pytest.fixture
    def list_page_size(self) -> int:
        return 2
```

---

HTML version: <https://msiebert.github.io/wenchang/customize.html>
