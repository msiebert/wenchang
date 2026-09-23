# 0002. Python tooling: uv, ruff, pyright, pytest

Date: 2026-09-23

## Status

Accepted

## Context

The project needs a dependency manager, formatter/linter, type checker, and
test runner. The tools should be fast, low-configuration, and give a single
gate (`make check`) that hooks and CI can call.

## Decision

- **uv** for dependency management and virtual environments (`pyproject.toml`
  + `uv.lock`), with dev tools as a `dev` dependency group.
- **ruff** for both linting and formatting, with rule set `E`, `F`, `I`,
  `UP`, `B`, `SIM`, `RUF`.
- **pyright** in strict mode over `src/` and `tests/`.
- **pytest** with `unit` and `integration` markers; `integration` requires a
  running fake-gcs-server emulator and is excluded by default
  (`addopts = -m "not integration"`), with `--strict-markers` so a typo in a
  marker fails loudly instead of silently matching everything.

## Consequences

One toolchain covers formatting, linting, and typing with minimal
configuration. Integration tests are opt-in, so `make check` and default
`pytest` runs never require Docker or network access. A future contributor
adding a new marker must register it or the run fails.
