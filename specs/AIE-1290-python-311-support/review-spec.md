# Spec Review: AIE-1290 - Support Python 3.11

## What & why

The Mixpanel monorepo is pinned to Python 3.11, but wenchang requires 3.12 and uses 3.12-only syntax (PEP 695), so it cannot be imported there. We replace that syntax with 3.11-compatible equivalents, lower the supported floor to 3.11, and test on both 3.11 and 3.12. No behavior changes.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | Python 3.11 | `wenchang`, `.tools`, `.mcp`, `.testing` imported (mcp extra) | imports succeed |
| 2 | Repo synced on 3.11 (and 3.12) | `make check` | lint, pyright 3.11, non-integration tests pass |
| 3 | A `.py` in src/evals/tests with PEP 695 syntax | tests run | guard test fails naming the file |
| 4 | `pyproject.toml` | packaging test reads it | `>=3.11`, ruff `py311`, pyright `3.11` |
| 5 | `bind_tools` | existing tests run | same signature and behavior, tests unweakened |
| 6 | CI | check job runs | `make check` on 3.11 and 3.12 |
| 7 | `docs/adr/` | listed | ADR 0037 records the floor |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| Generic `bind_tools` uses module-level `_C = TypeVar("_C")` | none | Smallest change; public signature otherwise identical |
| `type X = ...` becomes `X: TypeAlias = ...` | `typing_extensions.TypeAliasType` | Stdlib only; no new runtime dependency |
| Floor 3.11 in `requires-python`, ruff, pyright | Keep pyright at 3.12 | Pyright strict at 3.11 rejects 3.12-only syntax and stdlib APIs |
| AST `feature_version=(3, 11)` guard test plus pyproject test | Rely on CI alone | Runs in `make check`; faster feedback |
| CI matrix 3.11 and 3.12 | Pin `.python-version` to 3.11 | Exercises 3.11 for real without dropping 3.12 |
| New ADR 0037 | none | Records the floor and the no-PEP-695 rule |

## Files/modules to be touched

- `src/wenchang/{tools.py,mcp.py,file_format.py,testing/transport_conformance.py}`, `evals/scenario.py`
- `pyproject.toml`, `uv.lock`, `.github/workflows/ci.yml`
- Tests: new `tests/test_python_floor.py`; syntax-only alias change in `tests/test_tools.py`, `tests/test_reference_adopter_end_to_end.py`
- Later: `docs/adr/0037-python-311-floor.md`. ARCHITECTURE.md and glossary unchanged.

## Open questions / assumptions

1. Is a CI matrix (doubling the `check` job) OK?
2. Should `.python-version` be added? Recommend no (it would silently stop exercising 3.12).
3. Assumed ADR number 0037 (latest is 0036).

## Risks

- `uv.lock` may resolve different dependency versions under 3.11 markers.
- `TypeAlias` is evaluated eagerly; names imported only under `TYPE_CHECKING` could fail at import and need quoting.
- The AST guard catches syntax only; 3.12-only stdlib APIs are caught by pyright at 3.11 and the 3.11 CI leg.
