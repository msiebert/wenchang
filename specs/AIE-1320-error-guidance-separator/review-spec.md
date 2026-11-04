# Spec Review: AIE-1320 — Separate error detail from guidance

## What & why

`WenchangError.message` is `f"{detail} {guidance}"`, so a detail without
terminal punctuation runs into the guidance (`... must not be empty This is
normal coordination ...`). The same happens inside `ResolverFailureError` and
`BackendUnavailableError`. One private helper in `wenchang.errors` ends the
detail as a sentence at each join point; already-punctuated details render
unchanged.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| US1 | detail `something went wrong`; or ending `.`/`!`/`?`; or trailing whitespace | render | `.` appended only if missing; whitespace stripped; one space then guidance |
| US1 | empty/whitespace detail; `...`; `(see x.)`; multi-line; `str` subclass with raising methods | render | guidance alone; no `.` after `...`; `.` after `)`; interior kept; same as plain `str` |
| US1 | any category class | read `.detail` | unterminated |
| US2 | `InvalidArgumentError("old_string", "old_string must not be empty")` | render | `... must not be empty. ` + guidance |
| US2 | blank detail | construct, render | `.detail == "Argument cursor is invalid"`, message ends `invalid. ` + guidance |
| US2 | unknown-scope error (already ends in `.`) | render | unchanged |
| US3 | `ResolverFailureError("token expired")` / `ResolutionFailure("token expired")` via `resolve_identity` | render | `token expired. Identity could not be resolved; ...` |
| US3 | no detail, punctuated detail, blank detail | render | unchanged / same as no detail |
| US4 | `BackendUnavailableError(TIMEOUT, "deadline exceeded")` and `UNAVAILABLE` | render | `deadline exceeded. The storage backend timed out. ...` / `is unavailable.` |
| US4 | blank, punctuated, multi-line detail | render | no leading space, no doubled period, trailing newline stripped |
| US5 | existing fixed-text error tests | run | pass unmodified |
| US6 | docs | read | ARCHITECTURE.md, ADR 0005, `site-src/reference.md`, CHANGELOG updated |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| Private `_sentence(text)` ends a fragment as a sentence at every join point | Always join with `". "` | Doubles periods on details that already end with one |
| One shared helper, not a fix at each site | Per-call-site fix (as the unknown-scope period) | Misses adopter-supplied and exception-derived text |
| Terminate in `message`, keep `.detail` unterminated | Store terminated text in `.detail` | Changes an observable attribute; breaks `UNGRANTED_DETAIL` |
| Normalize with `str.__str__`, call `str` methods unbound; non-`str` raises `TypeError` | Call methods on the detail | A `str` subclass override cannot alter or break the message |
| Keep the unknown-scope trailing period in `tools.py` | Remove it | Removal changes `InvalidArgumentError.detail` for no rendered gain |

## Files/modules to be touched

- `src/wenchang/errors.py`
- `tests/test_errors.py`, `tests/test_errors_invalid_argument.py`,
  `tests/test_identity.py`, `tests/test_tools.py`
- `ARCHITECTURE.md`, `docs/adr/0005-error-taxonomy-as-exceptions.md`,
  `CHANGELOG.md`, `site-src/reference.md`

## Open questions / assumptions

- The adversarial spec review replaced the human checkpoint and passed on
  round 2.
- Two existing tests change expected values only (spec Allow-test-changes):
  `test_error_message_format` and
  `test_invalid_argument_error_str_is_detail_then_guidance`. Nothing is
  deleted, skipped, or weakened.
- The check is on the raw last character, so `(see x.)` gets a `.`.
- Out of scope: rewording details or guidance, and the no-grants
  `available scopes: .` message.

## Risks

- A non-`str` detail now raises `TypeError` from the helper; all callers pass
  `str` per their annotations.
- Any adopter matching on the exact old run-on message text sees it change
  for unpunctuated details.
