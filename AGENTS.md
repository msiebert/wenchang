# AGENTS.md

wenchang gives AI agents persistent, self-organizing memory: a virtual
filesystem of markdown files in GCS, exposed as tools.

## Commands

- `make install` — `uv sync`
- `make fmt` — format and autofix (ruff)
- `make lint` — check formatting and lint, no fixes
- `make typecheck` — pyright (strict, `src/` and `tests/`)
- `make test` — all non-integration tests (`pytest -m "not integration"`)
- `make test-integration` — integration tests against fake-gcs-server (`make emulator-up` first)
- `make check` — lint + typecheck + test; the definition-of-done gate

## Workflow

- One Linear issue at a time, via `/implement-issue AIE-XXXX`.
- Spec Kit specs live in `specs/AIE-XXXX-slug/`.
- Tests first.

## Rules

- Never delete, skip, or weaken a test unless the issue being worked requires it.
- `make check` must pass before any task is considered finished.
- Changing module boundaries, the public API, or storage semantics requires
  updating ARCHITECTURE.md and adding an ADR in `docs/adr/`.
- Reference the Linear issue ID (`AIE-XXXX`) in commit messages, PR titles,
  and relevant test docstrings.
- Branch naming: `msiebert-AIE-XXXX-slug`.
- Storage is accessed only through the internal storage interface (GCS
  implementation and in-memory fake) — never GCS directly from other layers.

## Pointers

- Architecture: [ARCHITECTURE.md](ARCHITECTURE.md)
- Product context: [docs/product/](docs/product/)
- Constitution: [.specify/memory/constitution.md](.specify/memory/constitution.md)
