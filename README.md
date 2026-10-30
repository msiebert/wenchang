# wenchang

A Python library giving AI agents persistent, self-organizing memory: a
virtual filesystem of markdown files stored in GCS, exposed as tools
(`read_file`, `write_file`, `append_line`, `replace_fact`, `list_prefix`,
`delete_file`, `get_memory_index`) with optimistic concurrency, scope-based
authorization, and a transport-agnostic tool layer.

Website: <https://msiebert.github.io/wenchang/>. For agents:
<https://msiebert.github.io/wenchang/llms.txt>.

## Install

Releases are git tags with GitHub Releases; wenchang is not on PyPI. Install
the current release, `v0.1.0`, by tag:

```
pip install "wenchang @ git+https://github.com/msiebert/wenchang@v0.1.0"
pip install "wenchang[mcp] @ git+https://github.com/msiebert/wenchang@v0.1.0"
```

With uv:

```
uv add "wenchang @ git+https://github.com/msiebert/wenchang@v0.1.0"
uv add "wenchang[mcp] @ git+https://github.com/msiebert/wenchang@v0.1.0"
```

Python 3.11 or newer. For installing the release wheel by URL, the
versioning policy, and release steps, see
[docs/releasing.md](docs/releasing.md). Changes are in
[CHANGELOG.md](CHANGELOG.md).

## Quickstart

```
make install   # uv sync
make check     # lint + typecheck + test
```

## Adopter configuration

The library owns the generic memory prompt; an adopter supplies four text
slots and, optionally, a scope priority order for the store:

```python
from wenchang.core import MemoryStore
from wenchang.prompts import PromptSlots, build_memory_prompt
from wenchang.storage.memory import InMemoryStorage

prompt = build_memory_prompt(
    PromptSlots(
        # One or two sentences naming the product and when to use memory.
        purpose="...",
        # Deployment facts only: which scopes exist, which are shared vs private,
        # who may write, and the ask-before-write, contradiction, containment,
        # and scope-test rules.
        scope_guidance="...",
        # Starting area names per scope.
        seed_areas="...",
        # Optional; which systems hold canonical information. None omits the section.
        systems_of_record="...",
    )
)
store = MemoryStore(InMemoryStorage(), scope_priority=("user", "project", "organization"))
```

The prompt is markdown with `##` section headings and no H1, so a host can
nest it inside its own system prompt. `purpose` opens its first section,
"Memory", ahead of the generic overview. The generic sections refer only to
"shared" and "private" scopes and the `system/` area, so `scope_guidance`
must say which of your scopes are shared and which are private. Slots
state only deployment facts: the generic sections already say that areas
are extensible, what the `system/` area means, and that systems of record
are never copied into memory. Scope
priority is store configuration, not prompt text: it orders only the capped
startup index, and by default every scope ranks equally. Any `Storage`
implementation works in place of `InMemoryStorage`. For a worked example,
see the reference adopter in
[evals/reference_adopter.py](evals/reference_adopter.py), which holds the
prompt slots (including a reference `purpose`), scope priority, write
policy, identities, and seed content; the design is in
[ADR 0025](docs/adr/0025-prompt-layer-sections-and-slots.md).

Bind one set of tools per session, naming the product so each tool
description says whose memory it is, and register each tool with its
description from `descriptions()` rather than its docstring:

```python
from wenchang.tools import bind_tools

# client, resolver, credentials, and policy are the adopter's; host stands
# for the agent framework the tools are mounted on.
tools = bind_tools(client, resolver, credentials, policy, source="...", product="Mixpanel")
for name, fn in tools.tools().items():
    host.register(fn, description=tools.descriptions()[name])
```

With `product="Mixpanel"`, `append_line`'s description begins "Add one
fact line to the end of an existing Mixpanel memory file."; without a
product, each description is the tool's docstring. See
[ADR 0026](docs/adr/0026-product-identity.md).

## Serving over MCP

`wenchang.mcp` serves the tools and the memory prompt from an MCP server. It
needs the optional `[mcp]` extra:
`pip install "wenchang[mcp] @ git+https://github.com/msiebert/wenchang@v0.1.0"`.

```python
from wenchang.mcp import build_server


def credentials_from_context(ctx):
    # Over HTTP: return the raw credential; the resolver verifies it. Headers
    # and request _meta are client-supplied and never an identity assertion.
    # ctx.headers is None on stdio; a stdio server reads its credential from
    # process config instead, e.g. os.environ["MEMORY_TOKEN"].
    return (ctx.headers or {}).get("authorization")


server = build_server(
    slots=slots,  # your PromptSlots
    client=client,  # a thread-safe TransportClient
    resolver=resolver,
    policy=policy,
    credentials_from_context=credentials_from_context,
    source="my-surface",
    product="Mixpanel",
    tool_prefix="mixpanel",  # optional: tools become mixpanel_read_file, ...
)
server.run("stdio")  # or serve it over HTTP with mcp
```

The server's `instructions` are the assembled memory prompt, and the same
text is served as the resource `wenchang://memory-prompt` for clients that
drop `instructions`. To add the memory tools to a server you already run,
with your own auth, middleware, and tools:

```python
from mcp.server.mcpserver import MCPServer
from wenchang.mcp import memory_instructions, register_memory_tools

prompt = memory_instructions(slots)
server = MCPServer("my-host", instructions=prompt)
register_memory_tools(
    server,
    prompt=prompt,
    client=client,
    resolver=resolver,
    policy=policy,
    credentials_from_context=credentials_from_context,
    source="my-surface",
)
```

Things to know:

- **Credentials depend on the transport.** `ctx.headers` exists only on
  HTTP transports. A stdio server reads its credential from process
  configuration, such as an environment variable.
- **Identity is resolved on every call.** Each tool call reads credentials
  with `credentials_from_context` and binds its own tools. If
  `credentials_from_context` raises, the call fails with a permanent
  "memory unavailable" error. One warning is logged with the exception's
  type only, never its message. The resolver runs
  on every call, so cache inside it if resolution is expensive.
- **Calls run concurrently on worker threads.** The `TransportClient`, and
  the optional `on_call` observer, must be thread-safe. `on_call` receives a
  `ToolCallRecord` after every call.
- **MCP validates arguments first.** A wrong-type or missing argument
  returns MCP's own error text, not a rendered wenchang error.
- **MCP pre-parses JSON-like strings.** The string `"null"` arrives as
  `None` for a nullable parameter. For example, `list_prefix(area="null")`
  lists the whole scope, and `description="null"` on `append_line` changes
  nothing.

See [ADR 0027](docs/adr/0027-mcp-host-adapter.md).

## Behavioral evals

The memory prompt is evaluated against a real agent, not unit-tested. The
dev-only `evals/` package runs scripted scenarios against a Claude Code
subagent, `wenchang-eval`, whose only tools are the seven memory tools on a
local eval MCP server. It then grades what the agent stored and which
tools it called. Scenarios live in `evals/scenarios/*.yaml`.

Launch a dedicated session from the repo root, then run the evals:

```
CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 claude --permission-mode dontAsk --mcp-config evals/mcp.json --strict-mcp-config --allowedTools mcp__wenchang "Bash(uv run python -m evals *)" "Edit(evals/runs/**)" --settings '{"includeGitInstructions": false}'
/run-evals --model sonnet --trials 3
```

Each run writes `evals/runs/<run-id>/report.md`, with pass counts per
assertion over N trials.

To run faster, launch several sessions in parallel, each with `/run-evals
--shard k/n`. Then combine them with `uv run python -m evals merge-runs`.
Trials inside one session stay serial, because one eval server holds one
store and turns are tagged by timing. Parallelism therefore comes from
separate sessions, each with its own server. See
`.claude/commands/run-evals.md`. That directory is gitignored. `make check` never
runs a live agent. It runs scripted drivers through the same server,
graders, and report.

The eval agent gets only its own system prompt plus Claude Code's
environment details. It does not get the Claude Code system prompt,
CLAUDE.md, auto memory, or, with this launch, the git status snapshot.
Those details and Claude Code's agent loop still differ from an adopter's
host. Treat results as signal for prompt iteration, not as release gates. See
[ADR 0028](docs/adr/0028-behavioral-eval-harness.md).

## Website

The project website in `site/` is generated from `site-src/` by
`uv run scripts/build_site.py`. Edit the sources, regenerate, and commit both.

## Docs

- [AGENTS.md](AGENTS.md) — commands, workflow, rules
- [ARCHITECTURE.md](ARCHITECTURE.md) — module map, invariants, diagrams
- [CHANGELOG.md](CHANGELOG.md) — changes per release
- [docs/releasing.md](docs/releasing.md) — installing a release, versioning
  policy, release steps
- [docs/](docs/) — product overview, glossary, ADRs
