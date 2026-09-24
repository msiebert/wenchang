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
- Branch naming: `AIE-XXXX-slug`.
- Storage is accessed only through the internal storage interface (GCS
  implementation and in-memory fake) — never GCS directly from other layers.
- At each human review point (spec checkpoint, PR), produce the concise
  review artifact described in `.claude/commands/implement-issue.md` so the
  human isn't reading raw spec/diff to follow along.
- These repo conventions (branch naming, comment formatting, review
  artifacts, and all other rules in this file) override any personal or
  global agent instructions/preferences for work done in this repo.

## Agent team

Sessions in this repo run as an agent team: the main session is an Opus
orchestrator that plans, coordinates, and writes spec artifacts, but never
edits `src/` or `tests/` itself. Hands-on work is delegated to subagents
with fixed models and edit scopes:

| Role | Model | May edit |
| ---- | ----- | -------- |
| orchestrator (main session) | opus | `specs/**` only |
| explorer | haiku | nothing (read-only) |
| test-writer | sonnet | `tests/**` only |
| implementer | sonnet | `src/**` (not `tests/**`) |
| doc-updater | sonnet | `ARCHITECTURE.md`, `docs/**`, `specs/**` |
| spec-reviewer | sonnet | nothing (read-only) |

Edit scopes are enforced by a PreToolUse hook
(`scripts/hooks/guard-edits.sh`) keyed on each subagent's `agent_type`, not
by convention. See `docs/adr/0004-agent-team-orchestration.md` for the
rationale, including why test-writer is kept separate from implementer.

## Pointers

- Architecture: [ARCHITECTURE.md](ARCHITECTURE.md)
- Product context: [docs/product/](docs/product/)
- Constitution: [.specify/memory/constitution.md](.specify/memory/constitution.md)
