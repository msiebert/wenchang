# PR Review: AIE-1290 — Support Python 3.11

## What changed & why

The host monorepo is pinned to Python 3.11, but wenchang required 3.12 and used PEP 695 syntax, so it failed at import. The floor is now 3.11 (`requires-python`, ruff `py311`, pyright `3.11`, `uv.lock` regenerated with no version changes). All PEP 695 syntax became `TypeAlias` and module-level TypeVars across `src/`, `evals/`, and `tests/`, and one PEP 701 f-string was hoisted. CI runs `make check` on 3.11 and 3.12. No behavior change.

## Acceptance criteria → tests

| Acceptance criterion (Given/When/Then) | Test(s) |
| --------------------------------------- | ------- |
| AC1 Python 3.11: wenchang, tools, mcp, testing import | CI 3.11 leg + manual smoke on 3.11.15 (no unit test can run another interpreter) |
| AC2 `make check` passes on 3.11 and 3.12 | CI `check` matrix; run locally on both |
| AC3 PEP 695 in src/evals/tests fails the suite, naming the file | `tests/test_python_floor.py::test_no_python_312_syntax_in_source_evals_or_tests` |
| AC4 pyproject targets 3.11 | `tests/test_python_floor.py::test_pyproject_targets_python_311` |
| AC5 `bind_tools` signature and behavior unchanged | `tests/test_tools.py` `test_bind_tools_*`, `test_product_is_keyword_only_on_bind_tools` |
| AC6 CI runs both versions | `.github/workflows/ci.yml` `check` job matrix |
| AC7 ADR records the floor | `docs/adr/0037-python-311-floor.md` |

## Architecture / ADR changes

- New [ADR 0037](../../docs/adr/0037-python-311-floor.md). ARCHITECTURE.md is unchanged: it states no Python version.

## Deviations from spec

- None in behavior. The change touched more files than the plan listed (`identity.py`, `resolver_conformance.py`, `evals/graders.py`, `evals/report.py`, five test modules); the guard test found them.

## Look closely at

- `identity.py`: `IdentityResolver` is now `Protocol[_C_contra]` with a contravariant TypeVar; `ResolverConformance` is `Generic[_C]`. Check variance matches the old inferred form.
- `TypeAlias` is eager: confirm no alias references a name imported only under `TYPE_CHECKING`.
- The AST guard does not catch PEP 701 f-strings or 3.12-only stdlib APIs; ruff `py311`, pyright `3.11`, and the CI 3.11 leg cover those.
- `tests/` edits are syntax-only; no assertions changed.

## Follow-ups

- Revisit the floor and the CI matrix when the monorepo moves to 3.12.
