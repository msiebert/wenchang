# Implementation Plan: AIE-1290 Support Python 3.11

**Branch**: `AIE-1290-python-311-support` | **Date**: 2026-10-30 | **Spec**: [spec.md](spec.md)

## Summary

Remove the PEP 695 syntax (type-parameter lists and `type` aliases; more files than first planned, found by the guard test) and one PEP 701 f-string so the code parses and imports on 3.11, lower the declared and tooled Python floor to 3.11, guard against regressions with an AST test, and run CI on 3.11 and 3.12. No public behavior changes.

## Technical Context

Python 3.11 floor (3.12 still supported), pytest, pyright strict, ruff, uv. No new dependencies. Gate: `make check` (constitution III).

## Constitution Check

- I/II Tests-first, tests not weakened: new tests land first and fail on `src/` and `evals/`. The two `type` to `TypeAlias` conversions in `tests/` are syntax-only; no assertion changes.
- IV Strict typing: pyright strict now runs at 3.11, which is stricter about syntax and stdlib APIs.
- V Storage only through the interface: untouched.
- VI Spec fidelity: no deviation from the Notion spec; the floor is recorded in a new ADR.
- VII Architecture documented: no module boundary, API, or storage change; ARCHITECTURE.md states no Python version, so unchanged. ADR 0037 added.
- VIII Traceability: tests cite `AIE-1290, USx.y`.
- IX Single issue: yes.
- XI Review artifacts: review-spec.md now, review-pr.md at PR.

Result: pass, no complexity violations.

## Changes

### Source and evals

- `src/wenchang/tools.py`: add `_C = TypeVar("_C")` at module level; `bind_tools` becomes `def bind_tools(client, resolver: IdentityResolver[_C], credentials: _C, policy, *, source, product=None) -> MemoryTools`. Same parameters, keyword-only `source`/`product`, same return.
- Actual extent beyond `bind_tools`: type-parameter lists became module-level private TypeVars/ParamSpec in `identity.py` (`IdentityResolver` is `Protocol[_C_contra]`, contravariant), `mcp.py`, `testing/resolver_conformance.py` (`ResolverConformance(Generic[_C])`), `testing/transport_conformance.py`, `evals/graders.py`, and five test modules (`test_evals_server`, `test_mcp_server`, `test_resolver_conformance_self`, `test_tools`, `test_transport_conformance_self`).
- A PEP 701 f-string (backslash in an expression) in `evals/report.py` was hoisted to a constant. The AST guard does not catch PEP 701 forms; ruff `py311`, pyright 3.11, and the CI 3.11 leg do.
- `type X = ...` to `X: TypeAlias = ...` (`from typing import TypeAlias`) in `src/wenchang/mcp.py`, `src/wenchang/file_format.py`, `src/wenchang/testing/transport_conformance.py` (four aliases), `evals/scenario.py`.
- `TypeAlias` is evaluated at import. Every name an alias references must be imported at runtime, not only under `TYPE_CHECKING`; quote forward references. Where a name is only imported under `TYPE_CHECKING`, quote the whole right-hand side or move the import (ruff `TCH` may complain; prefer quoting).

### Packaging

- `pyproject.toml`: `requires-python = ">=3.11"`, `[tool.ruff] target-version = "py311"`, `[tool.pyright] pythonVersion = "3.11"`. Run `uv lock`; review the diff for dependency version changes caused by 3.11 markers.

### Tests (tests first)

- New `tests/test_python_floor.py`:
  - Guard: for each `.py` under `src/`, `evals/`, `tests/`, `ast.parse(source, feature_version=(3, 11))`; collect failures and assert the list is empty, naming each file. (CPython's parser rejects `type` statements and type-parameter lists under `feature_version < (3, 12)`.) Implementer should confirm this on the installed interpreter; if the parser does not reject them, fall back to a `ast.walk` check for `ast.TypeAlias` and non-empty `type_params`.
  - Packaging: read `pyproject.toml` with `tomllib`; assert the three settings.
- `tests/test_tools.py` (`_Call`) and `tests/test_reference_adopter_end_to_end.py` (`_Loc`): `type` to `TypeAlias`.

### CI

- `.github/workflows/ci.yml` `check` job: `strategy.matrix.python: ["3.11", "3.12"]`, `uv sync --locked --python ${{ matrix.python }}`, then `make check`. `.python-version` is not added.

### Docs (doc-updater, after implementation)

- `docs/adr/0037-python-311-floor.md`: records 3.11 as the supported minimum, the no-PEP-695 rule, and the three enforcement layers, with rejected alternatives.
- `specs/AIE-1290-python-311-support/review-pr.md`.
- ARCHITECTURE.md and the glossary: no change (no Python version stated; no ADR index).

## Verification

Orchestrator runs `uv sync --python 3.11 && make check`, then `uv sync --python 3.12 && make check`, plus an import smoke test of the four modules on 3.11.

## Project Structure

```text
specs/AIE-1290-python-311-support/
  spec.md plan.md tasks.md review-spec.md
src/wenchang/{tools.py,mcp.py,file_format.py,testing/transport_conformance.py}
evals/scenario.py   pyproject.toml   uv.lock   .github/workflows/ci.yml
tests/test_python_floor.py  tests/test_tools.py  tests/test_reference_adopter_end_to_end.py
docs/adr/0037-python-311-floor.md
```

**Structure Decision**: No new modules; one new test file.

## Complexity Tracking

None.
