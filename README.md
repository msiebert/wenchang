# wenchang

A Python library giving AI agents persistent, self-organizing memory: a
virtual filesystem of markdown files stored in GCS, exposed as tools
(`read_file`, `write_file`, `append_line`, `replace_fact`, `list_prefix`,
`delete_file`, `get_memory_index`) with optimistic concurrency, scope-based
authorization, and a transport-agnostic tool layer.

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
[tests/prompts_reference_adopter.py](tests/prompts_reference_adopter.py),
including a reference `purpose`; the design is in
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

## Docs

- [AGENTS.md](AGENTS.md) — commands, workflow, rules
- [ARCHITECTURE.md](ARCHITECTURE.md) — module map, invariants, diagrams
- [docs/](docs/) — product overview, glossary, ADRs
