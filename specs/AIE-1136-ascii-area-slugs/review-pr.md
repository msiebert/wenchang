# PR Review: AIE-1136 — ASCII slug areas at the tool layer

## What changed & why

The AIE-1044 code review left one point open in ADR 0022: an agent could
write to areas that look like `system`. `scope.check_not_system` compares
the area to `system` exactly (ADR 0016 decision 2), and `paths` accepts any
segment without a `Cc` character. That made `System`, `ѕystem` (Cyrillic
`ѕ`), and `sys` + U+200B + `tem` ordinary writable areas. On 2026-10-02 you
chose **"ASCII slug areas"**. The tool layer now narrows what an agent can
address:

- `area` must fully match `[a-z0-9][a-z0-9_-]*` (`_AREA_SLUG`, using
  `fullmatch`, so a trailing newline can't slip past the way it can with
  `$`).
- `name` stays Unicode but must not contain a `Cf` character, `\u2028` /
  `\u2029` (categories `Zl` / `Zp`), or a noncharacter (U+FDD0–U+FDEF, or a
  code point whose low 16 bits are `FFFE` / `FFFF`).
- A violation raises `InvalidArgumentError("area" | "name")` directly. It
  has no `__cause__` and makes no `check_write` or client call.

Core `paths`, `scope`, storage, and the transport are unchanged. Files:
`src/wenchang/tools.py` (`_check_area_slug`, `_check_name_chars`, and
`_is_forbidden_name_char` are called from `_path` / `_prefix`, plus a
docstring sentence on each area-taking tool) and `tests/test_tools.py`
(six new tests). No existing test changed.

## Acceptance criteria → tests

`t` = `tests/test_tools.py`. Line numbers are as of commit `fe4fdaf`. New
test docstrings cite AIE-1136.

`make check` at `fe4fdaf`: lint and typecheck clean; 2131 passed, 6 skipped
(the pre-existing resolver-conformance skips), 39 deselected (integration).

| Acceptance criterion | Test(s) |
| -------------------- | ------- |
| US1.1 slug areas accepted on every area-taking tool | `t::test_slug_area_is_accepted` (L842; `notes`, `notes-2`, `a_b`, `9lives` × all six `SCOPE_TOOLS`) |
| US1.1 `system` passes the slug rule and still hits `SYSTEM_READ_ONLY` on mutations | `t::test_system_area_is_read_only` (L1001), `::test_read_file_may_read_system_area` (L545), `::test_bad_description_in_system_area_is_restricted` (L1087) |
| US1.2 non-slug area → `InvalidArgumentError("area")`, rule in detail, no `__cause__`, no `check_write` or client call, `list_prefix` included | `t::test_non_slug_area_is_invalid_argument` (L829; `System`, Cyrillic `ѕystem`, zero-width `sys` + U+200B + `tem`, `notes.v2`, `Notes`, `-leading`, `_leading`, CJK, `a b` × all six `SCOPE_TOOLS`) |
| US1.3 `""`, `..`, `a/b` keep the chained builder `ValueError` | `t::test_invalid_area_is_invalid_argument` (L657, unchanged from AIE-1044) |
| US2.1 Unicode names accepted | `t::test_unicode_name_is_accepted` (L871; `Übersicht`, `日本語`, `my notes` × `NAME_TOOLS`) |
| US2.2 name with `Cf` / separator / noncharacter → `InvalidArgumentError("name")`, no `__cause__`, no `check_write` or client call | `t::test_name_with_invisible_or_separator_char_is_invalid_argument` (L856; U+200B, U+200D, U+2060, U+202E, U+FEFF, U+2028, U+2029, U+FFFE × `NAME_TOOLS`) |
| US3.1 ungranted scope beats bad area | `t::test_grant_check_precedes_area_slug_check` (L884) |
| US3.2 bad area beats bad name | No direct test. `_path` calls `_check_area_slug` before `_check_name_chars` (see Look closely at) |
| US3.3 bad area / name on a mutating tool: no `check_write`, no client | `t::test_area_slug_check_precedes_check_write` (L893, `org` scope where the member would get `ROLE_REQUIRED`); `harness.log == []` in L829 and L856 |
| US3.4 valid area, then `check_write` before other argument errors | `t::test_check_write_precedes_argument_validation` (L962, unchanged) |
| US4.1–4.3 ADR, ARCHITECTURE.md, glossary | Docs, listed below |
| US4.4 docstrings say areas are lowercase ASCII slugs | Not pinned by a phrase test; the sentence is in all six area-taking docstrings |

## Architecture / ADR changes

- [ADR 0022](../../docs/adr/0022-tool-layer.md) gets **decision 14**: the
  slug and name rules, the check order, and the rejected alternatives
  (NFKC plus casefold, `Cf`-only rejection, restricting core `paths`).
  Consequences now say lookalike `system` areas are not writable through
  the tools, and the lookalike item is gone from the open points.
- `ARCHITECTURE.md`, **tools** entry: the check order includes "the `area`
  and `name` rules" between path building and `check_write`. A new
  paragraph states the slug regex, the name rule, the error shape, and
  that core is unaffected.
- `docs/product/glossary.md`, **Scope-relative address**: states the area
  slug and name rules, and says the narrowing belongs to the tools, not
  core.

## Deviations from spec

None remain. Spec US1.2 / US2.2 and plan.md were aligned to the shipped
error details: the area detail states the slug rule in prose and echoes
the value via `repr` (`area '<value>' must be a lowercase slug: a-z0-9
first, then a-z0-9, '-' or '_'`), and the name detail names the offending
code point (`U+XXXX`).

## Decisions to confirm

- **Check order: after path building, before `check_write`.** The slug and
  name checks run after `build_path` / `build_prefix` have returned, so
  `""`, `..`, and `a/b` still fail inside the builder. Their
  `InvalidArgumentError` stays chained from its `ValueError`, and the
  AIE-1044 tests (`test_invalid_area_is_invalid_argument` L657,
  `test_invalid_name_is_invalid_argument` L670) stand unchanged. Putting the
  check first would have made those errors cause-less and broken the tests.
  It runs before `check_write`, so a non-slug area is never reported as a
  role or `system` error, and `system` itself still reaches
  `SYSTEM_READ_ONLY`.
- **Reads and `list_prefix` are covered too, not just mutations.** The
  check lives in `_path` / `_prefix`, so `read_file` and
  `list_prefix(scope, area)` reject non-slug areas the same way. As a
  result, **a file stored before this change under a non-slug area (say
  `Notes/` or `notes.v2/`) can't be read through the tools.** It can still
  appear in `list_prefix(scope)` with no area and in `get_memory_index`,
  since neither validates the areas they return, but an agent that maps
  such a path to `read_file(scope, area, name)` gets
  `InvalidArgumentError("area")`. Core and the transport can still read it.
  The spec puts migration out of scope; ADR 0022 decision 14 records the
  consequence.

## Look closely at

- **The slug check also forbids uppercase and dots.** Pre-existing areas
  like `Notes` or `notes.v2` become unreachable by tools, as described
  above. Is that acceptable for any adopter data, or should there be a
  migration or listing filter?
- **Coverage is thinner than the spec's example lists.** Spec US1.2 also
  names `SYSTEM`, `system` + U+00AD, `a.b`, `café`, and fullwidth
  `ｓystem`. Spec US2.2 also names U+00AD, U+FDD0, and U+1FFFF. None of
  these are parametrized, so the noncharacter range branch and the
  low-16-bits `FFFF` branch (as opposed to `FFFE`) are untested. US3.2
  (area before name) and the US4.4 docstring sentence have no direct test.
- **`_is_forbidden_name_char`** uses `category in ("Cf", "Zl", "Zp")` for
  the format and separator rule. `Zl` and `Zp` are exactly U+2028 and
  U+2029, which matches spec. Lone surrogates never reach it because
  `_encodable` rejects them first.
- **Lookalikes inside `name`** (such as a Cyrillic letter) are allowed on
  purpose. Only `area` decides `system/` read-only status.

## Follow-ups

- If you want the spec's full example lists covered, add those cases to
  `BAD_AREA_SLUGS` / `BAD_NAME_CHARS`, plus an area-before-name ordering
  test and a docstring phrase test for "lowercase ASCII slugs".
- Decide how adopters with non-slug areas already stored reach that data
  through the tools (a migration, or a documented core-only path).
- The milestone-4 prompt text should tell the agent that areas are
  lowercase ASCII slugs.
