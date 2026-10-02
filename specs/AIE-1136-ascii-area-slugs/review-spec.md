# Spec Review: AIE-1136 — ASCII slug areas

## What & why

The tool layer blocks writes to `system/` by exact string comparison, and
core `paths` accepts any non-control Unicode, so `System`, Cyrillic
`ѕystem`, and `sys` + zero-width space + `tem` are writable areas that look
like `system/`. This restricts the agent-supplied `area` to an ASCII slug
(`^[a-z0-9][a-z0-9_-]*$`) and rejects invisible / noncharacter code points
in `name`, in `wenchang.tools` only. Core paths, storage, and transport are
unchanged.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| US1 | area `notes`, `system`, `a-b`, `2026-q4` / area `System`, `ѕystem`, `sys` + U+200B + `tem`, `-a`, `a.b`, `café`, fullwidth | any area-taking tool, `list_prefix` included | accepted (`system` still hits `SYSTEM_READ_ONLY`) / `InvalidArgumentError("area")`, detail states the slug rule in prose and echoes the value, no `__cause__`, no `check_write`, no client call; `""`/`..`/`a/b` keep the `build_path` cause |
| US2 | name `café`, `日本語`, `Notes` / name with `Cf`, U+2028/9, noncharacter | file tool | accepted / `InvalidArgumentError("name")` naming the code point, no cause, no client call |
| US3 | combined bad arguments | call | scope → path building → area → name → `check_write` → other args → client |
| US4 | docs | read | ADR 0022 decision 14 and open point removed; ARCHITECTURE.md, glossary, tool docstrings state the rule |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| **ASCII slug areas** (human decision 2026-10-02) | NFKC + casefold compare; invisibles-only; restricting in core `paths` | Slug closes case, cross-script, and invisible lookalikes at once; NFKC misses `ѕystem`; invisibles-only leaves `System`; core change breaks stored data |
| `name` stays Unicode, minus `Cf`, U+2028/9, noncharacters | Slug names too | Names are human titles; the `system/` risk is in `area` |
| Rule applies to every area-taking tool, reads included (orchestrator call) | Mutating tools only | One addressing rule; check sits in the shared `_path` / `_prefix` |
| Runs after path building, before `check_write`; raised with no cause | Before path building | Keeps AIE-1044's chained errors for `""` / `..` / `a/b` unchanged |

## Files/modules to be touched

- `src/wenchang/tools.py`, `tests/test_tools.py`
- `docs/adr/0022-tool-layer.md`, `ARCHITECTURE.md`, `docs/product/glossary.md`

## Open questions / assumptions

- Applying the rule to reads means files stored under a non-slug area
  (written outside the tools) are no longer reachable through the tools.
  None exist via the tools today. Flag at the PR if reads should stay
  permissive.

## Risks

- An adopter's seed areas must be slugs to be usable through the tools.
