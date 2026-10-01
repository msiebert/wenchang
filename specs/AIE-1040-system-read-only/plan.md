# Implementation Plan: Read-only enforcement for the system/ area

**Linear issue**: AIE-1040 | **Branch**: `AIE-1040-system-read-only` | **Date**: 2026-09-30 | **Spec**: [spec.md](spec.md)

## Summary

Add `src/wenchang/scope.py` with `SYSTEM_AREA`, `is_system_path`, and
`check_not_system`. All are pure functions over `paths.is_valid_path` and
`paths.parse_path`. The check is called by the tool layer directly or through
AIE-1042's `check_write`. No other module changes, and `MemoryStore` does not
call the new check.

## Technical Context

Python ≥ 3.12; pytest (`unit` marker); pyright strict; ruff (line length
100). Tests are unit tests in `tests/test_scope_system.py`. Only US4 touches
a `MemoryStore`, over `InMemoryStorage`, set up the same way as
`tests/test_core_write_file.py`.

**Dependency on AIE-1041.** `paths.parse_path(path) -> PathParts(scope,
entity_id, area, name)` raises `ValueError` iff `not is_valid_path(path)`.
AIE-1041 lands first in milestone order. If AIE-1042 has already created
`scope.py`, add these definitions to it rather than replacing it.

## Constitution Check

| Principle | Status |
| --------- | ------ |
| I. Tests-first | T1 test-writer → implementer |
| II. Tests not negotiable | No existing test changes |
| IV. Strict typing | Signatures fully annotated. `SYSTEM_AREA` is `Final` |
| V. Storage only through interface | No storage access in `scope`. The US4 test uses `InMemoryStorage` through `MemoryStore` |
| VI. Spec fidelity | Matches Notion Sections 1, 3, and 5: exact path check at the tool layer, permanent error naming scope and reason. Leaving core unrestricted follows "the seeding job owns the entire prefix" and is recorded in ADR 0016 |
| VII. Architecture documented | New public module → ARCHITECTURE.md `scope` entry and diagram edge + ADR 0016 |
| VIII. Traceability | Module docstring and each test docstring cite AIE-1040 and the scenario ID, e.g. (AIE-1040, US2.2) |
| IX. Small PR | One new module, one new test file |

**Decisions to record in ADR 0016:**

1. The check is a standalone function the tool layer calls, not a guard
   inside `MemoryStore`. The seeding job refreshes `system/` by wholesale
   rewrite through core, so core must accept `system/` writes. Rejected:
   checking in `MemoryStore` with a bypass flag or a privileged store
   instance. A flag is an argument the agent path could be made to pass, and
   Section 3 places enforcement at the tool layer. US4 pins core's behavior
   so a later change can't wire the check in by accident.
2. The match is exact equality of the area segment with `"system"`. There is
   no case folding, Unicode normalization, or prefix match on the segment, so
   `"System"`, `"systems"`, and Cyrillic look-alikes are ordinary writable
   areas. Section 3 calls for an exact string check. Rejected: normalizing,
   which would widen a hard rule into a fuzzy one, and a raw
   `"/system/" in path` substring test, which would also match a scope or
   entity ID named `system`.
3. Only the area position counts. A scope or entity ID named `system` is not
   restricted, because Section 3 restricts "the area named `system/`" within
   any scope.
4. `check_not_system` takes only `path`. No identity or role is accepted, so
   no caller can be exempted. The role-gated check (AIE-1042) is separate and
   takes an identity. AIE-1042's composite `check_write(path, identity,
   policy)` calls `check_not_system` first, so the order is invalid path,
   then system, then not granted, then role.
5. Malformed paths raise `NotFoundError(INVALID_PATH)` before the system
   check, the same error core gives. `is_system_path` never raises and
   returns False for them, matching `is_valid_path`. Rejected: raising
   `ValueError` (the `paths` builders' convention), since this function
   receives agent-supplied paths, not library-controlled values.
6. No `is_system_prefix` predicate. No agent-facing operation writes by
   prefix. Adding one later does not change this interface.
7. ARCHITECTURE.md's diagram edge `core --> scope` becomes `tools --> scope`,
   and the `scope` node moves out of the Core subgraph. Core does not depend
   on `scope`.

## Public interface

### `src/wenchang/scope.py`

```python
from typing import Final

from wenchang.errors import NotFoundError, NotFoundReason, RestrictedScopeError, RestrictionReason
from wenchang.paths import is_valid_path, parse_path

SYSTEM_AREA: Final = "system"


def is_system_path(path: str) -> bool:
    """Return True iff path is a valid memory path whose area is exactly `system`.

    Never raises for any str input.
    """


def check_not_system(path: str) -> None:
    """Reject a write to the read-only `system/` area of any scope.

    Raises NotFoundError(INVALID_PATH) for a malformed path, and
    RestrictedScopeError(SYSTEM_READ_ONLY) naming the path's scope if its
    area is `system`.
    """
```

Module docstring, in substance: "Write restrictions enforced at the tool
layer. `system/` holds curated content and is read-only to every caller of
these checks. Core does not apply them, so seeding can rewrite `system/`."

### Errors

| Input | Result |
| ----- | ------ |
| `not is_valid_path(path)` | `NotFoundError(path, NotFoundReason.INVALID_PATH)` |
| valid, `parse_path(path).area == "system"` | `RestrictedScopeError(path, scope=parse_path(path).scope, reason=RestrictionReason.SYSTEM_READ_ONLY)` |
| valid, any other area | returns `None` |

The role argument is left at its default. AIE-1042 renames `required_role` to
`required_roles`, so tests assert `getattr(err, "required_role", None) is None
and getattr(err, "required_roles", None) is None`, which passes in either
merge order. `RestrictedScopeError`'s
message is `"{path} is in scope {scope}; the system/ area of scope {scope} is
read-only (curated content). Do not retry: retrying will not succeed."`.
Tests assert `f"scope {err.scope}"` and `"read-only"` appear in `str(err)`,
not the full string.

### Algorithm

```text
is_system_path:
    return is_valid_path(path) and parse_path(path).area == SYSTEM_AREA

check_not_system:
    if not is_valid_path(path): raise NotFoundError(path, NotFoundReason.INVALID_PATH)
    parts = parse_path(path)
    if parts.area == SYSTEM_AREA:
        raise RestrictedScopeError(path, parts.scope, RestrictionReason.SYSTEM_READ_ONLY)
```

### Worked examples

| Call | Result |
| ---- | ------ |
| `check_not_system("user/u_42/system/policy.md")` | `RestrictedScopeError`, `scope == "user"` |
| `check_not_system("system/e/system/x.md")` | `RestrictedScopeError`, `scope == "system"` |
| `check_not_system("user/u_42/preferences/editor.md")` | `None` |
| `check_not_system("u/e/System/x.md")` | `None` |
| `check_not_system("system/e/a/x.md")` | `None` |
| `check_not_system("u/e/system/x.txt")` | `NotFoundError`, `INVALID_PATH` |
| `check_not_system("u/e/system/sub/x.md")` | `NotFoundError`, `INVALID_PATH` |
| `is_system_path("u/e/system/x.md")` | `True` |
| `is_system_path("u/e/system/")` | `False` |

## Test layout

- `tests/test_scope_system.py` (new, unit). The module docstring and each
  test docstring cite AIE-1040 and the scenario ID, e.g. (AIE-1040, US2.2).
  - US1–US3 as parametrized cases over the paths in spec.md. The malformed
    cases import `MALFORMED_STRUCTURE_PATHS`, `DOT_SEGMENT_PATHS`,
    `CONTROL_CHAR_PATHS`, `WRONG_SEGMENT_COUNT_PATHS`, and `BAD_NAME_PATHS`
    from `tests/test_paths.py` rather than duplicating them.
  - If `VALID_PATHS` from `tests/test_paths.py` is reused,
    `system/x/system/a.md` is a rejection case (area `system`). Every other
    entry is accepted.
  - The Edge Cases equivalence is one parametrized test over the union of
    all US1–US3 paths: `check_not_system` raises `RestrictedScopeError` iff
    `is_system_path` is True.
  - US1.5 asserts `list(inspect.signature(check_not_system).parameters) ==
    ["path"]`.
  - US4 runs the full mutating sequence on `"org/o_1/system/policy.md"`
    through `MemoryStore`: create with `expected_version=None`, replace at the
    returned version, `append_line`, `replace_fact`, then `delete_file` at the
    current version. Setup follows `tests/test_core_write_file.py`.
  - FR-006: parse `src/wenchang/scope.py` and `src/wenchang/core.py` with
    `ast`; assert scope has no import of `wenchang.core`/`wenchang.storage`
    and core has no import of `wenchang.scope`.
  - `SYSTEM_AREA == "system"` is asserted once.

## Project Structure

```text
specs/AIE-1040-system-read-only/   spec.md plan.md tasks.md review-spec.md
src/wenchang/scope.py              # new: SYSTEM_AREA, is_system_path, check_not_system
tests/test_scope_system.py         # new
ARCHITECTURE.md                    # scope entry, diagram edge, system/ invariant
docs/adr/0016-system-read-only-enforcement.md
```

## Complexity Tracking

None.
