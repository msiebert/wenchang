# PR Review: AIE-1137 — Clear exception context when resolve_identity re-raises

HEAD: `baeb8c8`

## What changed & why

`raise ... from None` hides the resolver's exception from rendered
tracebacks, but `__context__` still pointed at it. Host loggers, error
reporters, and debuggers that walk `__context__` directly could reach the
original message and any credential in it. `resolve_identity` now raises
every `ResolverFailureError` `from None` outside the `except` block, so no
resolver exception is ever recorded as `__context__`. Messages, categories,
and the public API are unchanged.

## Acceptance criteria → tests

All in `tests/test_identity.py`.

| Acceptance criterion (Given/When/Then) | Test(s) |
| --------------------------------------- | ------- |
| Each of the 4 failure paths (raised, `ResolutionFailure` returned, `detail` raised, wrong type) → `__cause__ is None`, `__context__ is None`, `__suppress_context__ is True` | `test_resolver_failure_error_carries_no_cause_or_context[raises\|returns_failure\|failure_detail_raises\|wrong_type]` (L907; cases from `_FAILURE_PATHS`, L898) |
| Rows 1 and 3 → formatted traceback omits the resolver's exception message | `test_resolver_failure_traceback_omits_original_exception_message[raises\|failure_detail_raises]` (L925) |
| Existing AIE-1043 behavior (messages, categories, `BaseException` pass-through) unchanged | Existing `tests/test_identity.py` suite, unmodified |

`make check`: 1503 passed, 6 skipped (pre-existing), 39 deselected.

## Architecture / ADR changes

- [ADR 0014](../../docs/adr/0014-identity-resolver.md): new "Update
  (2026-10-02)" section tightening decision 3, describing the mechanism and
  the rejected wrapper alternative.
- `ARCHITECTURE.md`: identity module entry (every `ResolverFailureError` is
  raised `from None` after its try/except exits) and the credentials
  invariant (no credential-bearing message reachable via traceback or
  exception chain).

## Deviations from spec

- None.

## Look closely at

- **Mechanism** (`src/wenchang/identity.py`, `resolve_identity`): the
  `except` handler only builds the error into a local; `raise raised from
  None` runs after the try/except has exited, when no resolver exception
  is being handled. Setting `__context__ = None` inside the handler would
  not work, since Python resets it at raise time.
- **Rejected alternative**: a wrapper that catches, clears `__context__`,
  and re-raises. It would also drop the caller's own in-flight exception;
  the chosen approach leaves that attached as `__context__`, as usual.
- The wrong-return-type raise gained `from None` for consistency (no
  resolver exception exists on that path).

## Follow-ups

- Other modules' `from None` raises (e.g. `scope`, `core`) have the same
  `__context__` property; out of scope here.
