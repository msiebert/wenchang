# Feature Specification: clear exception context when resolve_identity re-raises

**Linear issue**: AIE-1137 — Clear exception context when resolve_identity re-raises

**Feature Branch**: `AIE-1137-resolver-context`

**Created**: 2026-10-02

**Status**: Draft

**Input**: Linear AIE-1137. Follows `resolve_identity` (AIE-1043, ADR 0014
decision 3), which raises `ResolverFailureError ... from None`.

## Summary

`raise ... from None` sets `__cause__` to `None` and `__suppress_context__`
to `True`, but `__context__` still references the resolver's exception.
`traceback.format_exception` with `chain=True` respects the suppression, but
code that walks `__context__` directly can still reach the original
exception and its message, which may contain credentials. Examples are host
logging, error reporters, and debuggers. The fix is to raise every
`ResolverFailureError` `from None` after its try/except has exited, so the
resolver's exception is never recorded as `__context__`.

No public API change, no storage change, no message change.

Out of scope: any other module's `from None` raises (e.g. `scope`,
`core`), and the resolver conformance suite.

## User Scenarios & Testing *(mandatory)*

The "user" is a host application that logs or reports a
`ResolverFailureError` from `resolve_identity`.

### User Story 1 - No resolver internals reachable from the error (Priority: P1)

**Acceptance Scenarios**: for each failure path below, **When**
`resolve_identity(resolver, "creds")` raises `ResolverFailureError`,
**Then** `__cause__ is None`, `__context__ is None`, and
`__suppress_context__ is True`. Where the resolver raised an exception,
`"".join(traceback.format_exception(err))` also does not contain that
exception's message.

| # | Failure path | Resolver behavior | Traceback check |
| - | ------------ | ----------------- | --------------- |
| 1 | resolver raised | `resolve` raises `RuntimeError("SECRET-TOKEN")` | yes |
| 2 | `ResolutionFailure` returned | returns `ResolutionFailure("token expired")` | no (nothing raised) |
| 3 | `ResolutionFailure.detail` raised | returns a `ResolutionFailure` subclass whose `detail` raises `RuntimeError("SECRET-TOKEN")` | yes |
| 4 | wrong return type | returns `42` | no (nothing raised) |

Existing AIE-1043 tests keep passing unchanged: messages, categories, and
`BaseException` pass-through behave as before.

### Edge Cases

- Rows 2 and 4 have no resolver exception to leak, but they are covered
  anyway, so every failure path behaves the same.
- If `resolve_identity` is called while the caller is already handling an
  exception of its own, that exception becomes `__context__` as usual. It
  is the caller's, not a resolver internal, and it is left alone.
- A `BaseException` that is not an `Exception` still propagates unchanged
  and untouched.

## Requirements *(mandatory)*

- **FR-001**: Every `ResolverFailureError` raised by `resolve_identity`
  MUST have `__cause__ is None` and `__suppress_context__ is True`, and
  its `__context__` MUST NOT be any exception raised during resolution.
  When the caller isn't handling an exception, `__context__ is None`.
- **FR-002**: Error messages, categories, and the public signature of
  `resolve_identity` MUST be unchanged.

## Success Criteria *(mandatory)*

- **SC-001**: The four-row table above passes as one parametrized test, and
  the traceback test passes for rows 1 and 3.
- **SC-002**: `make check` passes.
