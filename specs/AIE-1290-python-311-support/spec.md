# Feature Specification: Support Python 3.11

**Linear**: AIE-1290

**Feature Branch**: `AIE-1290-python-311-support`

**Created**: 2026-10-30

**Status**: Implemented

**Input**: The Mixpanel monorepo is pinned to Python 3.11 (its 3.12 bump is in progress but not landed). wenchang declares `requires-python = ">=3.12"` and uses PEP 695 syntax, so it fails at import on 3.11. Support 3.11 so wenchang can be imported in the monorepo.

## Decisions already made (not reopened)

- Backport now rather than wait for the monorepo's 3.12 bump.
- The supported floor becomes 3.11; 3.12 and later keep working.
- No public behavior changes: this is a syntax and packaging change.
- Out of scope: `scripts/build_site.py` (standalone uv script with its own `requires-python` header) and `site-src/`.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Import wenchang on Python 3.11 (Priority: P1)

A monorepo developer on Python 3.11 installs wenchang and imports it.

**Why this priority**: The whole point of the issue.

**Independent Test**: In a 3.11 environment with the `mcp` extra, import `wenchang`, `wenchang.tools`, `wenchang.mcp`, `wenchang.testing`.

**Acceptance Scenarios**:

1. **Given** a Python 3.11 interpreter, **When** `wenchang`, `wenchang.tools`, `wenchang.mcp`, and `wenchang.testing` are imported (with the `mcp` extra installed), **Then** every import succeeds.
2. **Given** `bind_tools`, **When** its signature is inspected and the existing `tests/test_tools.py` run, **Then** the parameters (including keyword-only `source` and `product`) and return type are unchanged and the tests pass unweakened.

---

### User Story 2 - The repo is checked on both versions (Priority: P1)

A contributor's `make check` and CI prove 3.11 works and that 3.12 still does.

**Why this priority**: Without it 3.11 support regresses silently.

**Independent Test**: `uv sync --python 3.11 && make check`, and the same on 3.12.

**Acceptance Scenarios**:

1. **Given** the repo synced on 3.11 (`uv sync --python 3.11`), **When** `make check` runs, **Then** lint, pyright (`pythonVersion` 3.11), and all non-integration tests pass; and the same holds on 3.12.
2. **Given** `.github/workflows/ci.yml`, **When** CI runs, **Then** the `check` job runs `make check` on both 3.11 and 3.12.

---

### User Story 3 - 3.12-only syntax cannot creep back (Priority: P1)

**Why this priority**: PEP 695 is easy to reintroduce and `make check` on the default interpreter would not notice.

**Independent Test**: The regression-guard test.

**Acceptance Scenarios**:

1. **Given** any `.py` file in `src/`, `evals/`, or `tests/` that uses PEP 695 syntax (`type` statements, type-parameter lists), **When** the test suite runs, **Then** the regression-guard test fails naming that file.
2. **Given** `pyproject.toml`, **When** the packaging test reads it, **Then** `requires-python` is `">=3.11"`, ruff `target-version` is `"py311"`, and pyright `pythonVersion` is `"3.11"`.

---

### User Story 4 - The floor is recorded (Priority: P2)

**Acceptance Scenarios**:

1. **Given** `docs/adr/`, **When** listed, **Then** ADR 0037 exists recording 3.11 as the supported minimum and the no-PEP-695 rule.

---

### Edge Cases

- `X: TypeAlias = ...` is evaluated eagerly, unlike a `type` statement. Names it references must exist at runtime before the alias (not only under `TYPE_CHECKING`); forward references are quoted.
- `uv.lock` must resolve for 3.11; dependency versions may differ for 3.11 markers.
- `ast.parse(..., feature_version=(3, 11))` rejects PEP 695 syntax but does not catch 3.12-only stdlib APIs or PEP 701 f-string forms (e.g. a backslash inside an f-string expression); ruff `py311` and pyright 3.11 cover those, and the CI 3.11 leg runs everything for real. One such f-string in `evals/report.py` was hoisted to a constant.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Every PEP 695 type-parameter list in `src/`, `evals/`, and `tests/` MUST become module-level private `TypeVar`/`ParamSpec` declarations; public signatures are otherwise unchanged. Sites: `bind_tools` (`src/wenchang/tools.py`, `_C`), `IdentityResolver` (`src/wenchang/identity.py`, now `Protocol[_C_contra]` with a contravariant TypeVar), `src/wenchang/mcp.py`, `ResolverConformance(Generic[_C])` (`src/wenchang/testing/resolver_conformance.py`), `src/wenchang/testing/transport_conformance.py`, `evals/graders.py`, and `tests/test_evals_server.py`, `test_mcp_server.py`, `test_resolver_conformance_self.py`, `test_tools.py`, `test_transport_conformance_self.py`.
- **FR-002**: Every `type X = ...` alias in `src/`, `evals/`, and `tests/` MUST become `X: TypeAlias = ...` using `typing.TypeAlias`. Sites: `src/wenchang/mcp.py`, `src/wenchang/file_format.py` (`BodyLine`), `src/wenchang/testing/transport_conformance.py`, `evals/scenario.py` (`Assertion`), `tests/test_tools.py` (`_Call`), `tests/test_reference_adopter_end_to_end.py` (`_Loc`). The full site list was found by the guard test, not by the original plan.
- **FR-002a**: Any other 3.12-only construct MUST be removed. Found: a backslash inside an f-string expression (PEP 701) in `evals/report.py`, hoisted to a constant.
- **FR-003**: `pyproject.toml` MUST set `requires-python = ">=3.11"`, ruff `target-version = "py311"`, pyright `pythonVersion = "3.11"`; `uv.lock` MUST be regenerated.
- **FR-004**: A pytest test MUST parse every `.py` under `src/`, `evals/`, `tests/` with `ast.parse(source, feature_version=(3, 11))` and fail naming each file that does not parse; another MUST assert the three pyproject settings.
- **FR-005**: The CI `check` job MUST run on a Python matrix of 3.11 and 3.12 (for example `uv sync --locked --python ${{ matrix.python }}`).
- **FR-006**: ADR 0037 MUST record the 3.11 floor and the no-PEP-695 rule.
- **FR-007**: `make check` MUST pass on 3.11 and 3.12.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Importing the four modules succeeds on 3.11.
- **SC-002**: `make check` is green on 3.11 and 3.12.
- **SC-003**: `rg '^\s*type \w+(\[.*\])? =' src evals tests` finds no PEP 695 aliases, and `rg 'def \w+\['` finds no type-parameter lists.

## Assumptions

- `enum.StrEnum`, `typing.Self`, and `tomllib` already exist on 3.11; there is no `typing.override`, `itertools.batched`, or other 3.12-only stdlib use (pyright at 3.11 confirms).
- ARCHITECTURE.md states no Python version today, so it needs no change (verified).
- Decided with the human: CI matrix approved; no `.python-version` file.
- Public behavior of every tool is unchanged; no tool or error text changes.
