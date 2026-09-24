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

## Docs

- [AGENTS.md](AGENTS.md) — commands, workflow, rules
- [ARCHITECTURE.md](ARCHITECTURE.md) — module map, invariants, diagrams
- [docs/](docs/) — product overview, glossary, ADRs
