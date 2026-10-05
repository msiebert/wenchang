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

The library owns the generic memory prompt; an adopter supplies three text
slots and, optionally, a scope priority order for the store:

```python
from wenchang.core import MemoryStore
from wenchang.prompts import PromptSlots, build_memory_prompt
from wenchang.storage.memory import InMemoryStorage

prompt = build_memory_prompt(
    PromptSlots(
        scope_guidance="...",     # which scopes exist, which are shared vs private,
                                  # ask-before-write, contradiction, containment rules
        seed_areas="...",         # starting areas per scope; which are curated system/ areas
        systems_of_record="...",  # optional; None omits the section
    )
)
store = MemoryStore(InMemoryStorage(), scope_priority=("user", "project", "organization"))
```

The prompt is markdown with `##` section headings and no H1, so a host can
nest it inside its own system prompt. The generic sections refer only to
"shared" and "private" scopes and the `system/` area, so `scope_guidance`
must say which of your scopes are shared and which are private. Scope
priority is store configuration, not prompt text: it orders only the capped
startup index, and by default every scope ranks equally. Any `Storage`
implementation works in place of `InMemoryStorage`. For a worked example,
see the reference adopter in
[tests/prompts_reference_adopter.py](tests/prompts_reference_adopter.py);
the design is in
[ADR 0025](docs/adr/0025-prompt-layer-sections-and-slots.md).

## Docs

- [AGENTS.md](AGENTS.md) — commands, workflow, rules
- [ARCHITECTURE.md](ARCHITECTURE.md) — module map, invariants, diagrams
- [docs/](docs/) — product overview, glossary, ADRs
