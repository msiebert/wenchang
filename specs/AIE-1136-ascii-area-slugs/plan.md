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
- `_check_area(area)`: if not `_AREA_SLUG.fullmatch(area)`, raise
  `InvalidArgumentError("area", "area must be a lowercase ASCII slug
  matching ^[a-z0-9][a-z0-9_-]*$")`.
- `_check_name(name)`: reject any character `c` where
  `unicodedata.category(c) == "Cf"`, `c in "\u2028\u2029"`, `0xFDD0 <=
  ord(c) <= 0xFDEF`, or `ord(c) & 0xFFFE == 0xFFFE`. Detail: `"name must not
  contain invisible format characters, line or paragraph separators, or
  Unicode noncharacters"`.
- Both raise directly (no `from`), so `__cause__` is `None`.
- Placement: in `_path`, after `build_path` returns (its `ValueError`
  conversion unchanged), call `_check_area` then `_check_name`; in
  `_prefix`, after `build_prefix` returns, call `_check_area` when `area` is
  not `None`. Both helpers run before every caller's `check_write`, so the
  order is: type/UTF-8 checks → grant → path building → area/name rules →
  `check_write` → remaining arguments → client.
- Docstrings: where they describe `area`, add "a lowercase ASCII slug
  (letters a–z, digits, `-`, `_`; starting with a letter or digit)".

## Files

- `src/wenchang/tools.py`
- `tests/test_tools.py`
- `docs/adr/0022-tool-layer.md`, `ARCHITECTURE.md`, `docs/product/glossary.md`
