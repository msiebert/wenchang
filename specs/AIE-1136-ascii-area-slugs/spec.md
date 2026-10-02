# Feature Specification: ASCII slug areas at the tool layer

**Linear issue**: AIE-1136 — Restrict tool-layer area names to ASCII slugs

**Feature Branch**: `AIE-1136-ascii-area-slugs`

**Created**: 2026-10-02

**Status**: Draft — human decision recorded 2026-10-02 (option "ASCII slug
areas").

**Input**: ADR 0022 left one point open after the AIE-1044 adversarial code
review: lookalike `system` areas are writable. `scope.check_not_system`
compares the area to `system` exactly (ADR 0016 decision 2), and `paths`
accepts any segment without a `Cc` character. So `System`, `ѕystem` (with a
Cyrillic `ѕ`), and `sys` + U+200B + `tem` are ordinary writable areas that
can look like `system/` to a human or a model.

## Summary

The tool layer restricts the agent-supplied `area` to an ASCII slug and
rejects invisible and non-character code points in `name`. Core `paths`,
storage semantics, and the transport are unchanged; only what the agent can
address through `wenchang.tools` narrows.

- `area` must match `^[a-z0-9][a-z0-9_-]*$`.
- `name` stays Unicode but must not contain a `Cf` (format) character,
  `\u2028` / `\u2029`, or a Unicode noncharacter (U+FDD0–U+FDEF, and any
  code point whose low 16 bits are `FFFE` or `FFFF`).
- A violation raises `InvalidArgumentError("area" | "name", detail)` with no
  `__cause__` and no client call. The area detail states the slug rule in
  prose and echoes the value; the name detail names the offending code
  point.
- The check runs after the scope-grant check and path building, and before
  `check_write`. It lives in `_path` / `_prefix`, so it applies to every
  tool that takes `area` / `name`, reads and `list_prefix(scope, area)`
  included.

## Human decision (2026-10-02)

Option **"ASCII slug areas"**. Rejected alternatives:

| Alternative | Why rejected |
| ----------- | ------------ |
| NFKC + casefold compare against `system` | Catches `System` and compatibility forms but misses cross-script confusables (`ѕystem`) |
| Reject invisibles (`Cf`) only | Leaves `System` and Cyrillic lookalikes writable |
| Restrict segments in core `paths` | Changes storage semantics and makes existing stored data invalid |

## User stories and acceptance criteria

### US1 — area is an ASCII slug

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1.1 | area in `notes`, `system`, `a`, `0`, `a-b`, `a_b`, `2026-q4`, `x9_y-z` | any area-taking tool | accepted; `system` still reaches `check_write` and raises `RestrictedScopeError(SYSTEM_READ_ONLY)` for mutations |
| 1.2 | area in `System`, `SYSTEM`, `ѕystem` (Cyrillic), `sys` + U+200B + `tem`, `system` + U+00AD, `-a`, `_a`, `a b`, `a.b`, `café`, `ｓystem` (fullwidth) | any area-taking tool (incl. `list_prefix(scope, area)`) | `InvalidArgumentError(argument="area")`, detail `area '<value>' must be a lowercase slug: a-z0-9 first, then a-z0-9, '-' or '_'` (value via `repr`); `__cause__ is None`; no client call; no `check_write` |
| 1.3 | area `""`, `".."`, `"a/b"` | any area-taking tool | unchanged from AIE-1044: `InvalidArgumentError("area")` chained from the `build_path` / `build_prefix` `ValueError` |

### US2 — name rejects invisibles

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 2.1 | name in `a`, `Notes`, `café`, `日本語`, `a b`, `a.b`, `ѕ` | file tool | accepted |
| 2.2 | name containing U+200B, U+200D, U+FEFF, U+00AD, U+202E, U+2060 (`Cf`), U+2028, U+2029, U+FDD0, U+FFFE, U+1FFFF | file tool | `InvalidArgumentError(argument="name")`, detail `name must not contain invisible, separator, or noncharacter U+XXXX` naming the first offending code point; `__cause__ is None`; no client call; no `check_write` |

### US3 — ordering

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 3.1 | ungranted scope and bad area | call | scope error wins (`argument="scope"`) |
| 3.2 | non-slug area and a name that passes core `paths` but breaks the name rule (e.g. contains U+200B) | file tool | `argument="area"` (area checked before name). A core-invalid name (e.g. `x/y`) is reported by `build_path` first, per the documented order |
| 3.3 | bad area / name on a mutating tool | call | `check_write` spy not called; client not called |
| 3.4 | valid slug area, invalid other argument (e.g. non-fact `line`) | mutating tool | `check_write` runs first, then that argument's error (unchanged order) |

### US4 — docs

| # | Then |
| - | ---- |
| 4.1 | ADR 0022 records the decision and drops the lookalike item from its open points |
| 4.2 | ARCHITECTURE.md `tools` entry states the slug and name rules and the check order |
| 4.3 | Glossary "Scope-relative address" states the area and name rules |
| 4.4 | Tool docstrings say `area` is a lowercase ASCII slug (no Linear IDs) |

## Out of scope

- Core `paths`, `scope`, storage, and transport behavior.
- Migrating or rejecting existing stored files with non-slug areas; they
  stay readable through core and the transport, but not through the tools.
