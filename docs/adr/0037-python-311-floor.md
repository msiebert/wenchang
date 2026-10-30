# 0037. Python 3.11 floor

Date: 2026-10-30

## Status

Accepted. Amends [ADR 0002](0002-python-tooling-uv-ruff-pyright-pytest.md)
on the supported Python version.

## Context

wenchang declared `requires-python = ">=3.12"` and used PEP 695 syntax
(`type X = ...` aliases and type-parameter lists such as `def f[C](...)`).
The host monorepo is pinned to Python 3.11; its 3.12 bump has not landed.
On 3.11 wenchang failed at import with a syntax error, so the monorepo could
not use it.

## Decision

1. **The supported minimum is Python 3.11.** 3.12 and later keep working.
   `pyproject.toml` sets `requires-python = ">=3.11"`, ruff
   `target-version = "py311"`, and pyright `pythonVersion = "3.11"`.
   `uv.lock` is regenerated; no package versions changed.
2. **No PEP 695 syntax** in `src/`, `evals/`, or `tests/`.
   - `type X = ...` becomes `X: TypeAlias = ...`.
   - Type-parameter lists become module-level private `TypeVar` and
     `ParamSpec` declarations (`_C = TypeVar("_C")`). `IdentityResolver` is
     `Protocol[_C_contra]` with a contravariant TypeVar;
     `ResolverConformance` is `Generic[_C]`. `bind_tools` keeps the same
     public signature.
3. **Enforcement in three layers**, because none covers everything alone:
   - `tests/test_python_floor.py` parses every `.py` under `src/`, `evals/`,
     and `tests/` with `ast.parse(feature_version=(3, 11))`, which rejects
     PEP 695, and asserts the three pyproject settings. It does not catch
     PEP 701 f-string forms (such as a backslash inside an f-string
     expression); `feature_version` does not gate them.
   - Ruff `py311` and pyright `3.11` reject PEP 701 syntax and 3.12-only
     stdlib APIs.
   - The CI `check` job runs `make check` on a 3.11 and 3.12 matrix, so the
     3.11 leg exercises real runtime behavior.
4. **Revisit** when the monorepo moves to 3.12.

## Consequences

- wenchang imports in the 3.11-pinned monorepo with no change in behavior.
- Generics and aliases are more verbose, and `TypeAlias` is evaluated at
  import, so names an alias references must exist at runtime.
- CI cost doubles for the `check` job.
- New 3.12-only syntax fails the AST test, ruff, pyright, or the 3.11 CI leg.
  3.12-only runtime behavior with no syntactic marker is caught only by the
  CI 3.11 leg.
- Reverting to 3.12 later is mechanical: lift the floor and optionally restore
  PEP 695 syntax.

Rejected:

- **Wait for the monorepo's 3.12 bump.** It blocks adoption on a schedule
  outside this repo.
- **Keep 3.12 and add a 3.11 compatibility shim or transpile step.** It adds
  machinery to maintain for a one-time syntax gap.
- **Guard only with the AST test.** It misses PEP 701 f-strings and 3.12-only
  stdlib APIs.
- **A `.python-version` file.** CI selects the interpreter explicitly, and a
  pin would hide the other leg of the matrix locally.
