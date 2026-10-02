# Spec Review: AIE-1137 — clear exception context when resolve_identity re-raises

## What & why

`resolve_identity` raises `ResolverFailureError ... from None`. That hides
the resolver's exception in standard tracebacks, but `__context__` still
points to it. Logging or reporting code that walks `__context__` can
therefore reach the original message, which may carry credentials. This
change raises every failure after its try/except has exited, so the
resolver's exception is never recorded as `__context__`. There is no API, message,
or storage change.

## Acceptance criteria

Each row asserts `__cause__ is None`, `__context__ is None`, and
`__suppress_context__ is True`.

| # | Failure path | Resolver does | Also: marker absent from `format_exception` |
| - | ------------ | ------------- | ------------------------------------------- |
| 1 | resolver raised | raises `RuntimeError("SECRET-TOKEN")` | yes |
| 2 | `ResolutionFailure` returned | returns `ResolutionFailure("token expired")` | — |
| 3 | `ResolutionFailure.detail` raised | returns a failure whose `detail` raises `RuntimeError("SECRET-TOKEN")` | yes |
| 4 | wrong return type | returns `42` | — |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| Build the error inside `except`, raise it after the try/except exits | Set `__context__ = None` before `raise error` | Python overwrites `__context__` at raise time inside a handler, so a pre-raise clear does nothing (verified) |
| Raise outside the handler, not a wrapper that catches, clears, and re-raises | Wrapper | The wrapper would also drop a caller's own in-flight exception. Raising outside the handler excludes only the resolver's |
| `from None` on all four raises, including wrong type | Only where an exception was handled | `__cause__ is None` and `__suppress_context__ is True` on every path |

## Files/modules to be touched

- `src/wenchang/identity.py` — `resolve_identity` only
- `tests/test_identity.py` — two new parametrized tests
- `docs/adr/0014-identity-resolver.md` — update note
- `ARCHITECTURE.md` — identity entry and identity invariant, one clause each

## Open questions / assumptions

- None open. The chosen approach doesn't touch a caller's own exception
  chain. If `resolve_identity` is called inside the caller's `except`
  block, that exception becomes `__context__` as usual. It is not a
  resolver internal. The tests call `resolve_identity` outside any
  handler, which is why they can assert `__context__ is None`.

## Risks

- Low. Other modules' `from None` raises still leave `__context__` set. They
  don't handle credentials, but the same pattern exists there.
