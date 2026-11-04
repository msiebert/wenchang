# Implementation Plan: Separate error detail from guidance

**Linear issue**: AIE-1320 | **Branch**: `AIE-1320-error-guidance-separator` | **Date**: 2026-11-02 | **Spec**: [spec.md](spec.md)

## Summary

One module: `src/wenchang/errors.py`. Tests in `tests/test_errors.py`,
`tests/test_errors_invalid_argument.py`, `tests/test_identity.py`, and
`tests/test_tools.py`. Docs: ARCHITECTURE.md, ADR 0005, CHANGELOG.md,
`site-src/reference.md` if a quote changes.

## Technical Context

Python ≥ 3.11; pyright strict; ruff 100. No new dependencies, no public API
added or removed, no import-graph change.

## Constitution Check

| Principle | Status |
| --------- | ------ |
| I. Tests-first | T1 test-writer → implementer |
| II. Tests not negotiable | Only the expected values of `test_error_message_format` and `test_invalid_argument_error_str_is_detail_then_guidance` change (spec Allow-test-changes); nothing deleted or skipped |
| Storage via interface only | Unchanged |
| Architecture changes documented | ARCHITECTURE.md errors entry, ADR 0005 decision |

## Public interface (unchanged signatures)

- `WenchangError(detail: str)`; `.detail` is the passed value; `.message`
  and `str(err)` are `f"{_sentence(detail)} {guidance}"` when
  `_sentence(detail)` is non-empty, else `guidance`.
- `ResolverFailureError(detail: str = "")`: the composed detail is
  `f"{_sentence(detail)} Identity could not be resolved; memory is
  unavailable for this session; continue working without memory."`, with
  the prefix and its space omitted when `_sentence(detail)` is empty.
- `BackendUnavailableError(reason, detail: str = "")`: the composed detail
  is `f"{_sentence(detail)} The storage backend timed out."` (or `is
  unavailable.`), prefix omitted when `_sentence(detail)` is empty.
- `InvalidArgumentError(argument, detail)`: composes `Argument {argument}
  is invalid: {detail}`, or `Argument {argument} is invalid` when `detail`
  is empty or whitespace-only (tested as `_sentence(detail) == ""`, never by
  calling a method on `detail`, which may be a `str` subclass); termination
  comes from the base `message`.
- `_sentence` raises `TypeError` for a non-`str` detail (all callers pass
  `str`, per the annotations); ADR 0005 notes it.

## Design

- Private module function `_sentence(text: str) -> str` in `errors.py`:
  `text = str.rstrip(str.__str__(text))`; return `""` if empty; return
  `text` if `text[-1] in ".!?"`; else `text + "."` (on the exact `str`, so
  no subclass method runs). Tests exercise it only through the public
  classes.
- Rejected: always joining with `". "` (doubles periods on the many details
  that already end with one); a per-call-site fix like AIE-1242 (misses
  adopter-supplied and exception-derived details); terminating in
  `__init__` and storing it in `.detail` (changes an observable attribute
  and breaks `UNGRANTED_DETAIL`).
- `tools.py` unchanged (AIE-1242's period kept; see spec).

## Files

- `src/wenchang/errors.py`
- `tests/test_errors.py`, `tests/test_errors_invalid_argument.py`,
  `tests/test_identity.py`, `tests/test_tools.py`
- `ARCHITECTURE.md`, `docs/adr/0005-error-taxonomy-as-exceptions.md`,
  `CHANGELOG.md`, `site-src/reference.md` (only if a quote changes)
