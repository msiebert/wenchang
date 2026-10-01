# Implementation Plan: Path construction from scope and entity ID

**Linear issue**: AIE-1041 | **Branch**: `AIE-1041-path-construction` | **Date**: 2026-09-30 | **Spec**: [spec.md](spec.md)

## Summary

Add `PathParts`, `build_path`, `build_prefix`, and `parse_path` to
`src/wenchang/paths.py`. All are pure string functions over the existing
segment rule, with `"/"` rejected in inputs. No other module changes.

## Technical Context

Python ≥ 3.12; pytest (`unit` marker); pyright strict; ruff (line length
100). Tests are plain unit tests in `tests/test_paths_build.py`; there is no
storage involvement. The existing `tests/test_paths.py` constants
(`VALID_PATHS`, `MALFORMED_STRUCTURE_PATHS`, `DOT_SEGMENT_PATHS`,
`CONTROL_CHAR_PATHS`, `WRONG_SEGMENT_COUNT_PATHS`, and the rest) may be
imported for the parse and round-trip cases rather than duplicated. Import
as `from test_paths import VALID_PATHS, …`, not `from tests.test_paths import
…`, because `tests/` has no `__init__.py` (see the `storage_conformance`
import in `tests/test_storage_memory.py`).

**Dependency on AIE-1043.** AIE-1043 T1 makes the segment check public as
`paths.is_valid_segment(segment) -> bool`: non-empty, not `"."` or `".."`,
and no `"/"`, backslash, or Unicode control character. It never raises.
AIE-1043 lands first in milestone order, and this issue builds on it with no
separate `"/"` check. `is_valid_path` and `is_valid_prefix` are unchanged.

## Constitution Check

| Principle | Status |
| --------- | ------ |
| I. Tests-first | T1 test-writer → implementer |
| II. Tests not negotiable | Existing `tests/test_paths.py` untouched |
| IV. Strict typing | All signatures fully annotated; `PathParts` fields typed `str` |
| V. Storage only through interface | No storage access |
| VI. Spec fidelity | Matches Notion Section 3 layout; `{root}` omitted per ADR 0007 and the "storage root is the storage instance" invariant |
| VII. Architecture documented | New public functions in `paths` → ARCHITECTURE.md `paths` entry + ADR 0015 |
| VIII. Traceability | Each test docstring cites AIE-1041 and the scenario ID, e.g. (AIE-1041, US2.4) |
| IX. Small PR | One module, one test file |

**Decisions to record in ADR 0015:**

1. Paths are built relative to the storage root. `{root}` from the Notion
   layout is the storage instance and never appears in the string.
2. A name is accepted iff it is non-empty and `name + ".md"` is a valid
   segment, and `".md"` is always appended. Rejecting names ending in `".md"`
   was considered and rejected: `is_valid_path` accepts `"u/e/a/b.md.md"`,
   and rejecting `"b.md"` would break `build_path(**asdict(parse_path(p))) ==
   p`. For the same reason `"."` and `".."` are accepted as names.
3. Construction errors are `ValueError`, not `NotFoundError(INVALID_PATH)`.
   These helpers are called by library code with values it controls.
   Agent-supplied paths keep going through `is_valid_path` in `core`. A
   caller passing agent-supplied values must validate them first or turn the
   `ValueError` into `NotFoundError(INVALID_PATH)`.
4. `paths` stays free of `identity`. A `build_path_for(identity, scope, area,
   name)` convenience was rejected: it would couple a dependency-free module
   to the identity model for a one-expression saving, and the scope lookup
   (and its failure mode for an ungranted scope) belongs to the scope layer.
5. `build_prefix` treats `""` as an invalid segment, not as "omitted". Only
   `None` means omitted. An `area` without an `entity_id` is a `ValueError`
   because the prefix would otherwise silently shift the area into the
   entity-ID position.
6. Builders validate every segment with the shared public
   `is_valid_segment`, which rejects `"/"`, so a builder can never emit a
   path with the wrong segment count.

## Public interface

### `src/wenchang/paths.py`

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class PathParts:
    """The four components of a memory path; `name` excludes the final ".md"."""

    scope: str
    entity_id: str
    area: str
    name: str


def build_path(scope: str, entity_id: str, area: str, name: str) -> str:
    """Return `{scope}/{entity_id}/{area}/{name}.md`.

    Raises ValueError naming the first invalid argument.
    """


def build_prefix(scope: str, entity_id: str | None = None, area: str | None = None) -> str:
    """Return the listing prefix `scope/`, `scope/entity_id/`, or `scope/entity_id/area/`.

    Raises ValueError for an invalid segment or an area without an entity_id.
    """


def parse_path(path: str) -> PathParts:
    """Split a well-formed memory path into its parts.

    Raises ValueError if `not is_valid_path(path)`.
    """
```

Field order of `PathParts` equals the parameter order of `build_path`, so
`build_path(*astuple(parts))` and `build_path(**asdict(parts))` both work.
All parameters are positional-or-keyword.

### Validation rules

Let `seg_ok(s)` be `is_valid_segment(s)` from AIE-1043: not `""`, `"."`, or
`".."`, and no `"/"`, backslash, or Unicode `Cc` character.

| Argument | Valid iff |
| -------- | --------- |
| `scope`, `entity_id`, `area` | `seg_ok(value)` |
| `name` | `value != "" and seg_ok(value + ".md")` |

### Errors

| Call | Condition | Raised |
| ---- | --------- | ------ |
| `build_path` | first invalid argument in order `scope`, `entity_id`, `area`, `name` | `ValueError(f"invalid {arg}: {value!r}")` |
| `build_prefix` | `area is not None and entity_id is None` | `ValueError("area requires entity_id")` (checked first) |
| `build_prefix` | first supplied invalid argument in order `scope`, `entity_id`, `area` | `ValueError(f"invalid {arg}: {value!r}")` |
| `parse_path` | `not is_valid_path(path)` | `ValueError(f"invalid path: {path!r}")` |

Tests should match the message with `pytest.raises(ValueError,
match=r"^invalid scope:")` (and likewise per argument), and
`match="area requires entity_id"` for the missing entity ID. No other
exception type is raised for arguments of the annotated types. `scope` and
`name` are never `None`.

### Algorithm

```text
build_path:
    for arg, value in (("scope", scope), ("entity_id", entity_id), ("area", area)):
        if not seg_ok(value): raise ValueError(f"invalid {arg}: {value!r}")
    if name == "" or not seg_ok(name + ".md"): raise ValueError(f"invalid name: {name!r}")
    return f"{scope}/{entity_id}/{area}/{name}.md"

build_prefix:
    if area is not None and entity_id is None: raise ValueError("area requires entity_id")
    segments = [("scope", scope), ("entity_id", entity_id), ("area", area)] with None entries dropped
    validate each with seg_ok, as in build_path
    return "".join(value + "/" for _, value in segments)

parse_path:
    if not is_valid_path(path): raise ValueError(f"invalid path: {path!r}")
    scope, entity_id, area, last = path.split("/")
    return PathParts(scope, entity_id, area, last[: -len(".md")])
```

### Worked examples

| Call | Result |
| ---- | ------ |
| `build_path("user", "u_42", "preferences", "editor")` | `"user/u_42/preferences/editor.md"` |
| `build_path("u", "e", "a", "b.md")` | `"u/e/a/b.md.md"` |
| `build_path("u", "e", "a", ".")` | `"u/e/a/..md"` |
| `build_path("u/x", "e", "a", "b")` | `ValueError("invalid scope: 'u/x'")` |
| `build_path("u", "e", "a", "")` | `ValueError("invalid name: ''")` |
| `build_prefix("user")` | `"user/"` |
| `build_prefix("user", "u_42", "preferences")` | `"user/u_42/preferences/"` |
| `build_prefix("user", None, "preferences")` | `ValueError("area requires entity_id")` |
| `build_prefix("user", "")` | `ValueError("invalid entity_id: ''")` |
| `build_prefix("bad/", None, "a")` | `ValueError("area requires entity_id")` |
| `build_prefix("u", None, "")` | `ValueError("area requires entity_id")` |
| `parse_path("u/e/a/b.md.md")` | `PathParts("u", "e", "a", "b.md")` |
| `parse_path("u/e/a/b.txt")` | `ValueError("invalid path: 'u/e/a/b.txt'")` |

## Test layout

- `tests/test_paths_build.py` (new, unit). The module docstring cites
  AIE-1041, and each test docstring cites AIE-1041 and its scenario ID, e.g.
  `(AIE-1041, US2.4)`. Parametrized cases for spec
  US1–US4. Round-trip laws are checked over
  `VALID_PATHS` from `tests/test_paths.py` plus the edge names above
  (`"."`, `".."`, `".md"`, `"b.md"`), and every malformed constant from
  `tests/test_paths.py` for `parse_path` rejection. Hypothesis is not a
  project dependency, so no property-based tests.
- FR-006 test: parse `src/wenchang/paths.py` with `ast` and assert it has no
  `import wenchang…` or `from wenchang… import` node.

## Project Structure

```text
specs/AIE-1041-path-construction/   spec.md plan.md tasks.md review-spec.md
src/wenchang/paths.py               # PathParts, build_path, build_prefix, parse_path
tests/test_paths_build.py
ARCHITECTURE.md                     # paths entry
docs/adr/0015-path-construction.md
```

## Complexity Tracking

None.
