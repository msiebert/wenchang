# Implementation Plan: ASCII slug areas at the tool layer

**Linear issue**: AIE-1136 | **Branch**: `AIE-1136-ascii-area-slugs` | **Date**: 2026-10-02 | **Spec**: [spec.md](spec.md)

## Summary

One module: `src/wenchang/tools.py`. Tests in `tests/test_tools.py`. Docs:
ADR 0022, ARCHITECTURE.md, glossary.

## Technical Context

Python ≥ 3.12; pyright strict; ruff 100. Uses stdlib `re` and
`unicodedata` only. No new dependencies; no import-graph change within
`wenchang`.

## Constitution Check

| Principle | Status |
| --------- | ------ |
| I. Tests-first | T1 test-writer → implementer |
| II. Tests not negotiable | No existing test weakened; AIE-1044 US2/US4 area cases (`""`, `..`, `a/b`) keep their `__cause__` |
| Storage via interface only | Unchanged |
| Architecture changes documented | ADR 0022 decision 14, ARCHITECTURE.md, glossary |

## Design

- Module constant `_AREA_SLUG = re.compile(r"[a-z0-9][a-z0-9_-]*")`, matched
  with `fullmatch` (no `$`-before-newline pitfall).
- `_check_area_slug(area)`: if `_AREA_SLUG.fullmatch(area)` is `None`,
  raise `InvalidArgumentError("area", f"area {area!r} must be a lowercase
  slug: a-z0-9 first, then a-z0-9, '-' or '_'")`. The `repr` shows
  invisible characters as escapes.
- `_check_name_chars(name)`: for the first character where
  `_is_forbidden_name_char(c)` (`unicodedata.category(c)` in `Cf`, `Zl`,
  `Zp`, i.e. format characters plus `\u2028` / `\u2029`; or `0xFDD0 <=
  ord(c) <= 0xFDEF`; or `ord(c) & 0xFFFE == 0xFFFE`), raise
  `InvalidArgumentError("name", f"name must not contain invisible,
  separator, or noncharacter U+{ord(c):04X}")`.
- Both raise directly (no `from`), so `__cause__` is `None`.
- Placement: in `_path`, after `build_path` returns (its `ValueError`
  conversion unchanged), call `_check_area_slug` then `_check_name_chars`;
  in `_prefix`, after `build_prefix` returns, call `_check_area_slug` when
  `area` is not `None`. Both helpers run before every caller's `check_write`, so the
  order is: type/UTF-8 checks → grant → path building → area/name rules →
  `check_write` → remaining arguments → client.
- Docstrings: each area-taking tool's docstring says "Areas are lowercase
  ASCII slugs."

## Files

- `src/wenchang/tools.py`
- `tests/test_tools.py`
- `docs/adr/0022-tool-layer.md`, `ARCHITECTURE.md`, `docs/product/glossary.md`
