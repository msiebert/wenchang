# Implementation Plan: Error taxonomy definition

**Linear issue**: AIE-1030 | **Branch**: `AIE-1030-error-taxonomy` | **Date**: 2026-09-24 | **Spec**: [spec.md](spec.md)

## Summary

Add `wenchang.errors`: an exception hierarchy with one base class, one class
per category (recoverable / permanent / transient), and one concrete class
per error kind in the Notion spec's Section 5. Each class carries its
category, its repair material as typed read-only attributes, and a message
that ends with its category's fixed next-action guidance. Add
`wenchang.version_token.VersionToken`, the opaque version-token type the
errors carry and every later core API function will use.

## Technical Context

**Language/Version**: Python ≥ 3.12

**Primary Dependencies**: standard library only (`enum.StrEnum`,
`typing.NewType`, `typing.ClassVar`)

**Storage**: N/A — no storage access in this issue

**Testing**: pytest, `@pytest.mark.unit`; pyright strict; ruff

**Project Type**: library

**Constraints**: no imports from storage, transport, or any agent framework
(FR-007)

## Constitution Check

| Principle | Status |
| --------- | ------ |
| I. Tests-first | Each task is test-writer → implementer |
| IV. Strict typing | All public attributes and constructors fully annotated |
| V. Storage only through interface | N/A — no storage |
| VI. Spec fidelity | Deviations below go in an ADR |
| VII. Architecture documented | New public module `wenchang.errors` → ARCHITECTURE.md update + ADR |
| VIII. Traceability | Test docstrings reference AIE-1030 |

**Recorded deviations / additions to the Notion spec (ADR required):**

1. Errors are Python exceptions, not returned values.
2. `ReplaceFactMatchError` also carries the current version token.
3. `VersionConflictError` carries content and version, not metadata (the
   metadata type arrives with AIE-1031).

## Public interface

Module `src/wenchang/version_token.py`:

```python
from typing import NewType

VersionToken = NewType("VersionToken", str)
"""Opaque version identifier. Callers store and return it; never parse,
compare, or order it."""
```

Module `src/wenchang/errors.py`:

```python
from enum import StrEnum
from typing import ClassVar

from wenchang.version_token import VersionToken


class ErrorCategory(StrEnum):
    RECOVERABLE = "recoverable"
    PERMANENT = "permanent"
    TRANSIENT = "transient"


class WenchangError(Exception):
    """Base of every library error."""

    category: ClassVar[ErrorCategory]
    guidance: ClassVar[str]  # fixed next-action text for the category

    def __init__(self, detail: str) -> None: ...
    # str(err) == err.message == f"{detail} {type(err).guidance}"
    @property
    def message(self) -> str: ...


class RecoverableError(WenchangError): ...  # category = RECOVERABLE


class PermanentError(WenchangError): ...  # category = PERMANENT


class TransientError(WenchangError): ...  # category = TRANSIENT
```

The three category classes set `category` and `guidance`. Concrete classes
inherit both and supply only `detail`. `WenchangError` and the category
classes are not meant to be raised directly, but constructing them with a
detail string is allowed (tests may do so).

Category guidance text must satisfy spec User Story 3:

- `RecoverableError.guidance`: routine framing; tells the caller to use the
  details above to correct the call and retry in the same turn, without
  asking the user. Must not contain "fail" in any form (case-insensitive).
- `PermanentError.guidance`: states retrying will not succeed and the
  caller must not retry. Must contain the phrase "do not retry"
  (case-insensitive).
- `TransientError.guidance`: states retrying is appropriate; version-guarded
  calls are safe to retry because a landed first attempt comes back as a
  version conflict; a retried `append_line` may duplicate a line, which can
  be removed by ordinary editing. Must contain "retry", "version conflict",
  "append_line", and "duplicate" (case-insensitive).

### Recoverable kinds

```python
class VersionConflictError(RecoverableError):
    def __init__(self, path: str, content: str, version: VersionToken) -> None: ...

    path: str  # read-only attributes (set once in __init__)
    content: str
    version: VersionToken


class OversizeWriteError(RecoverableError):
    def __init__(self, path: str, size: int, limit: int) -> None: ...

    # ValueError if size < 0 or limit < 0
    path: str
    size: int  # bytes
    limit: int  # bytes


class ReplaceFactMatchError(RecoverableError):
    def __init__(
        self, path: str, content: str, version: VersionToken, match_count: int
    ) -> None: ...

    # ValueError if match_count < 0 or match_count == 1
    path: str
    content: str
    version: VersionToken
    match_count: int
    # message: count 0 → tells caller to correct/widen old_string so it matches;
    #          count ≥ 2 → tells caller to narrow old_string (add surrounding
    #          text) so it matches exactly one span. Message includes the count.


class NotFoundReason(StrEnum):
    INVALID_PATH = "invalid_path"  # not a valid memory location → fix the path
    FILE_ABSENT = "file_absent"  # valid location, no file yet → may create it


class NotFoundError(RecoverableError):
    def __init__(self, path: str, reason: NotFoundReason) -> None: ...

    path: str
    reason: NotFoundReason
    # message: INVALID_PATH → contains "correct the path";
    #          FILE_ABSENT → contains "create" (the file may be created)
```

### Permanent kinds

```python
class RestrictionReason(StrEnum):
    SYSTEM_READ_ONLY = "system_read_only"
    ROLE_REQUIRED = "role_required"


class RestrictedScopeError(PermanentError):
    def __init__(
        self,
        path: str,
        scope: str,
        reason: RestrictionReason,
        required_role: str | None = None,
    ) -> None: ...

    # ValueError if reason is ROLE_REQUIRED and required_role is None
    path: str
    scope: str
    reason: RestrictionReason
    required_role: str | None
    # message names the scope; SYSTEM_READ_ONLY → contains "system/" and
    # "read-only"; ROLE_REQUIRED → contains the required role name.


class ResolverFailureError(PermanentError):
    def __init__(self, detail: str = "") -> None: ...

    # message states memory is unavailable for this session and the caller
    # should continue without memory: contains "unavailable" and
    # "without memory" (case-insensitive).
```

### Transient kinds

```python
class TransientReason(StrEnum):
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"


class BackendUnavailableError(TransientError):
    def __init__(self, reason: TransientReason, detail: str = "") -> None: ...

    reason: TransientReason
```

### Exports

Everything above is importable from `wenchang.errors` (and `VersionToken`
from `wenchang.version_token`). Nothing is re-exported from `wenchang`
top-level in this issue.

## Project Structure

```text
specs/AIE-1030-error-taxonomy/
├── spec.md
├── plan.md
├── tasks.md
└── review-spec.md

src/wenchang/
├── version_token.py   # new
└── errors.py          # new

tests/
└── test_errors.py     # new
```

## Complexity Tracking

None.
