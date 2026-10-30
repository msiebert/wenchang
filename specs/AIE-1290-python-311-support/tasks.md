# Tasks: AIE-1290

Test-first: test-writer writes failing tests (`tests/**` only), then the implementer makes them pass (`src/**`, `evals/**`). Spec refs are `spec.md` user stories.

## T1 - Regression guard and test aliases (US3)

- [x] T1 test-writer: add `tests/test_python_floor.py` with the AST `feature_version=(3, 11)` guard over `src/`, `evals/`, `tests/` (naming each offending file) and the pyproject settings test (`requires-python`, ruff `target-version`, pyright `pythonVersion`). Convert `type _Call` in `tests/test_tools.py` and `type _Loc` in `tests/test_reference_adopter_end_to_end.py` to `TypeAlias` (syntax-only, not a weakening). Expected failing state: guard fails on the `src/` and `evals/` files; pyproject test fails. Done: the guard also surfaced more `tests/` files (five test modules converted, syntax-only).

## T2 - Backport syntax and packaging (US1, US3)

- [x] T2 implementer: rewrite `bind_tools` with a module-level `_C = TypeVar("_C")`; convert the `src/` and `evals/` `type` aliases to `TypeAlias` (watch for names only imported under `TYPE_CHECKING`); set `requires-python = ">=3.11"`, ruff `py311`, pyright `3.11` in `pyproject.toml`; run `uv lock`; `make check` green. Done, with wider scope: also `identity.py`, `mcp.py`, `testing/resolver_conformance.py`, `testing/transport_conformance.py`, `evals/graders.py` type-parameter lists, and the PEP 701 f-string in `evals/report.py`.

## T3 - CI matrix (US2)

- [x] T3 general-purpose agent (`.github/` is outside the role scopes): add a 3.11/3.12 matrix to the `check` job in `.github/workflows/ci.yml` using `uv sync --locked --python ${{ matrix.python }}`. Do not add `.python-version`. Done by a general-purpose agent; matrix approved by the human.

## T4 - Verify (US1, US2)

- [x] T4 orchestrator: `uv sync --python 3.11` then `make check`; `uv sync --python 3.12` then `make check`; import smoke test of `wenchang`, `wenchang.tools`, `wenchang.mcp`, `wenchang.testing` on 3.11.

## T5 - Docs (US4; doc-updater)

- [x] T5a New ADR `docs/adr/0037-python-311-floor.md` from the MADR template.
- [x] T5b `specs/AIE-1290-python-311-support/review-pr.md` with the acceptance-criteria-to-test mapping.

## Order

T1 first (tests fail), then T2. T3 is independent of T1/T2 and can run in parallel. T4 waits for T2 and T3. T5 waits for T4.
