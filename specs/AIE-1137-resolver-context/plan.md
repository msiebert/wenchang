# Implementation Plan: clear exception context when resolve_identity re-raises

**Linear issue**: AIE-1137 | **Branch**: `AIE-1137-resolver-context` | **Date**: 2026-10-02 | **Spec**: [spec.md](spec.md)

## Summary

Make sure no `ResolverFailureError` that leaves `resolve_identity` carries
the resolver's exception as `__context__`. Each one is raised `from None`,
after its try/except has exited. The change is
confined to `src/wenchang/identity.py`, plus tests in `tests/test_identity.py`.

## Mechanism (load-bearing)

Setting `error.__context__ = None` **before** `raise error` inside an
`except` block does not work. When an exception is raised, CPython sets its
`__context__` to the exception currently being handled, which overwrites
the cleared value. (Verified: the context is still the original
`ValueError` after a pre-raise clear.)

So `resolve_identity` raises outside the `except` block. Each handler only
builds the `ResolverFailureError` into a local variable. The raise happens
after the try/except has exited, when the resolver's exception is no longer
being handled, so Python doesn't record it as `__context__`:

```python
raised: ResolverFailureError | None = None
try:
    result = cast(object, resolver.resolve(credentials))
except Exception as exc:
    raised = ResolverFailureError(f"Resolver {name} raised {_type_name(type(exc))}.")
if raised is not None:
    raise raised from None
```

The `ResolutionFailure.detail` guard already builds `error` inside its
try/except and raises it afterwards. Every raise uses `from None`, including
the wrong-type raise, so `__cause__` is `None` and `__suppress_context__` is
`True` on all four paths.

This clears only the resolver's exception. If the caller calls
`resolve_identity` while handling an exception of its own, that exception
becomes `__context__` as usual, so the caller's chain is left alone. It is
the caller's own exception, not a resolver internal, so nothing leaks.

Rejected: a wrapper that catches `ResolverFailureError`, clears
`__context__`, and re-raises with a bare `raise`. It works, but it also
drops the caller's in-flight exception from the chain. A `BaseException`
that is not an `Exception` still propagates unchanged.

## Constitution Check

| Principle | Status |
| --------- | ------ |
| I. Tests-first | T1 test-writer → implementer |
| II. Tests not negotiable | No existing test changes. New tests only |
| IV. Strict typing | No signature change |
| V. Storage only through interface | No storage access |
| VI. Spec fidelity | Strengthens ADR 0014 decision 3. No Notion spec deviation |
| VII. Architecture documented | ADR 0014 gets an update note. ARCHITECTURE.md identity entry and invariant get one clause each |
| VIII. Traceability | Test docstrings cite AIE-1137 |
| IX. Small PR | One module, one test file |

## Test layout

`tests/test_identity.py` (new tests, unit):

- `test_resolver_failure_error_carries_no_cause_or_context`: parametrized
  over the four spec rows.
- `test_resolver_failure_traceback_omits_original_exception_message`:
  rows 1 and 3, asserting the marker is absent from
  `traceback.format_exception(err)`.

## Complexity Tracking

None.
