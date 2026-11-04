# Feature Specification: Separate error detail from guidance

**Linear issue**: AIE-1320 — Add a separator between error detail and guidance

**Feature Branch**: `AIE-1320-error-guidance-separator`

**Created**: 2026-11-02

**Status**: Draft

Allow-test-changes: two tests assert the run-on form this issue fixes, and
only their expected values change to the terminated form:
`tests/test_errors.py::test_error_message_format` (`f"{detail} {guidance}"`
becomes `f"{detail}. {guidance}"`) and
`tests/test_errors_invalid_argument.py::test_invalid_argument_error_str_is_detail_then_guidance`
(`Argument cursor is invalid: bad {guidance}` becomes `... bad. {guidance}`).
No test is deleted, skipped, or weakened.

**Input**: `WenchangError.message` is `f"{detail} {guidance}"`. When the
detail does not end with terminal punctuation, two sentences run together,
e.g. `Argument old_string is invalid: old_string must not be empty This is
normal coordination ...`. The same happens inside `ResolverFailureError`
(an adopter's `ResolutionFailure.detail` such as `token expired` runs into
`Identity could not be resolved ...`) and `BackendUnavailableError` (a GCS
exception string runs into `The storage backend timed out.`). AIE-1242
patched one case by ending the unknown-scope detail in `tools.py` with a
period.

## Summary

One private helper in `wenchang.errors` ends a text fragment as a sentence.
It first takes the exact `str` value (`str.__str__`) and calls only `str`
methods unbound, so a `str` subclass overriding `rstrip`, `endswith`, or
`__add__` cannot change or break the result. It strips trailing whitespace
(everything `str.rstrip()` strips, newlines included; interior text
untouched), returns `""` if nothing
is left, and otherwise appends `.` unless the last character is `.`, `!`, or
`?`. The check is on the raw last character only: `...` counts as
terminated, while a closing quote or bracket after a period (`(see x.)`)
gets a `.` appended. It is applied at every place where an
instance-specific fragment is joined to following fixed text:

1. `WenchangError.message`: the detail, then a space, then the class
   guidance. This covers every error class, including
   `InvalidArgumentError` (detail `Argument {argument} is invalid:
   {detail}`) and `ResolutionFailure` details surfaced through
   `ResolverFailureError`.
2. `ResolverFailureError(detail)`: the optional caller detail before
   `Identity could not be resolved; ...`.
3. `BackendUnavailableError(reason, detail)`: the optional caller detail
   before `The storage backend timed out.` / `... is unavailable.`

`InvalidArgumentError` with an empty or whitespace-only detail composes
`Argument {argument} is invalid` (no colon), which renders as `Argument
{argument} is invalid.` rather than `invalid:.`. The tool layer passes
`str(exc)` details that can be empty.

The `detail` attribute keeps the value passed to `WenchangError.__init__`,
unterminated; only the rendered message changes. For classes that compose
their own detail (`InvalidArgumentError`, `ResolverFailureError`,
`BackendUnavailableError`, and the fixed-text classes) that is the composed
string. For `ResolverFailureError` and `BackendUnavailableError` the
composed string includes the terminated caller prefix, e.g.
`ResolverFailureError("token expired").detail` is `token expired. Identity
could not be resolved; ...`. Already-punctuated
details render byte-for-byte as today, so every fixed-text error
(`VersionConflictError`, `OversizeWriteError`, `FileQuotaExceededError`,
`ReplaceFactMatchError`, `NotFoundError`, `RestrictedScopeError`) is
unchanged.

AIE-1242's trailing period in the unknown-scope detail stays: the helper
makes it redundant for the message, but removing it would change the
observable `InvalidArgumentError.detail` attribute (asserted by
`tests/test_tools.py::UNGRANTED_DETAIL`) for no rendered benefit.

## Acceptance criteria

### US1 — base message

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1.1 | each category class (`RecoverableError`, `PermanentError`, `TransientError`) built with detail `something went wrong` | render `str(err)` / `err.message` | `something went wrong. {guidance}` |
| 1.2 | detail ending in `.`, `!`, or `?` (e.g. `Done.`, `Stop!`, `Why?`) | render | detail unchanged, then one space, then guidance (no doubled punctuation) |
| 1.3 | detail with trailing whitespace, e.g. `something went wrong  ` or `Done. ` | render | trailing whitespace removed, then terminated as in 1.1/1.2; exactly one space before guidance |
| 1.4 | empty or whitespace-only detail | render | message is exactly the guidance (no leading space, no lone `.`) |
| 1.5 | a category class built directly with `something went wrong` | read `err.detail` | `something went wrong` (not terminated) |
| 1.6 | detail ending in other punctuation (`;`, `,`, `)`, `'`) | render | `.` appended, e.g. `... '-' or '_'.` |
| 1.7 | detail ending in `...` | render | no `.` appended |
| 1.8 | detail ending `(see x.)` | render | `(see x.). {guidance}` (raw last-character rule) |
| 1.9 | detail `line one\nline two\n` | render | `line one\nline two. {guidance}` (trailing newline stripped, interior kept) |
| 1.10 | detail is a `str` subclass whose `rstrip`, `endswith`, and `__add__` raise | render | same message as the equal plain `str`; nothing raises |

### US2 — InvalidArgumentError

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 2.1 | `InvalidArgumentError("old_string", "old_string must not be empty")` | render | exactly `Argument old_string is invalid: old_string must not be empty. ` + `RecoverableError.guidance` |
| 2.2 | the tool layer's unknown-scope error (detail already ends `available scopes: org, user.`) | render | unchanged: `... available scopes: org, user. This is normal coordination ...` |
| 2.3 | an unpunctuated tool-layer rejection reaching the agent (e.g. `replace_fact` with empty `old_string`) | the tool raises | the rendered message contains `old_string must not be empty. This is normal coordination` |
| 2.4 | `InvalidArgumentError("cursor", "")` and `InvalidArgumentError("cursor", "  ")` | construct and render | `.detail == "Argument cursor is invalid"`; message exactly `Argument cursor is invalid. ` + guidance |

### US3 — ResolverFailureError and ResolutionFailure

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 3.1 | `ResolverFailureError("token expired")` | render | exactly `token expired. Identity could not be resolved; memory is unavailable for this session; continue working without memory. Do not retry: retrying will not succeed.` |
| 3.2 | a resolver returning `ResolutionFailure("token expired")` | `resolve_identity` raises (test in `tests/test_identity.py`) | the error's full `message` equals the 3.1 string |
| 3.3 | `ResolverFailureError()` and `ResolverFailureError("Credentials could not be read from the request.")` | render | unchanged from today |
| 3.4 | `ResolverFailureError("   ")` | render | same as `ResolverFailureError()` |
| 3.5 | `ResolverFailureError` detail is a `str` subclass whose `rstrip`/`endswith`/`__add__` raise | render | same message as the equal plain `str` |
| 3.6 | `ResolverFailureError("token expired")` | read `.detail` | starts with `token expired. Identity could not be resolved` |

### US4 — BackendUnavailableError

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 4.1 | `BackendUnavailableError(TIMEOUT, "deadline exceeded")` | render | exactly `deadline exceeded. The storage backend timed out. ` + `TransientError.guidance` |
| 4.2 | same with `UNAVAILABLE` | render | `deadline exceeded. The storage backend is unavailable. ...` |
| 4.3 | detail `""` (default) or whitespace-only | render | `The storage backend timed out. ...` with no leading space |
| 4.4 | detail already ending in `.` | render | no doubled period |
| 4.5 | multi-line detail `HTTP 503\nService Unavailable\n` | render | `HTTP 503\nService Unavailable. The storage backend ...` |

### US5 — unchanged fixed-text errors

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 5.1 | the existing exact-literal message tests (e.g. `test_file_quota_exceeded_error_message_is_exact_literal`) | run | pass unmodified |

### US6 — docs

| # | Then |
| - | ---- |
| 6.1 | ARCHITECTURE.md `errors` entry states that `message` is the detail ended as a sentence (`.` appended unless it ends with `.`, `!`, `?`; trailing whitespace stripped; empty detail gives the guidance alone), then a space, then the guidance; that the optional `ResolverFailureError` / `BackendUnavailableError` detail is terminated the same way; and that a blank `InvalidArgumentError` detail composes `Argument {argument} is invalid` |
| 6.2 | ADR 0005 records this as an added decision |
| 6.3 | `site-src/reference.md` and other docs quoting rendered messages stay accurate (no quoted rendered message changes; `site-src/reference.md`'s `InvalidArgumentError` format sentence gains the sentence ending and blank case). `site/` is generated and not hand-edited |
| 6.4 | CHANGELOG `[Unreleased]` gets a `Fixed` entry |

## Out of scope

- Rewording any detail or guidance text.
- The unknown-scope message when the identity has no grants (`available scopes: .`).
- Transport rendering (it renders `message`, so it inherits the fix).
