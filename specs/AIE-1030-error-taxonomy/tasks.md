# Tasks: Error taxonomy definition (AIE-1030)

**Input**: [spec.md](spec.md), [plan.md](plan.md)

Tasks run in order. Each is test-writer (tests in `tests/test_errors.py`)
then implementer (`src/wenchang/`). `make check` green after each.

## T1 — Version token, categories, and base hierarchy

Files: `src/wenchang/version_token.py`, `src/wenchang/errors.py`

Build `VersionToken`, `ErrorCategory`, `WenchangError`, `RecoverableError`,
`PermanentError`, `TransientError` with category guidance text per plan.md.

Acceptance:

- `ErrorCategory` has exactly three members: recoverable, permanent,
  transient.
- Each category class reports its category; each is a subclass of
  `WenchangError`, and none is a subclass of another category class.
- `str(err) == err.message` and the message ends with the class's
  `guidance`, preceded by the detail.
- Guidance wording checks from plan.md (recoverable: no "fail"; permanent:
  "do not retry"; transient: "retry", "version conflict", "append_line",
  "duplicate").

## T2 — Recoverable kinds

Build `VersionConflictError`, `OversizeWriteError`, `ReplaceFactMatchError`,
`NotFoundReason`, `NotFoundError`.

Acceptance: spec US1 scenarios 1–3, US2 scenarios 1–7, US3 scenario 1;
edge cases (empty/unicode content unchanged; negative size/limit/count
rejected; match count 1 rejected).

## T3 — Permanent kinds

Build `RestrictionReason`, `RestrictedScopeError`, `ResolverFailureError`.

Acceptance: spec US1 scenario 4, US3 scenarios 2–4; `ROLE_REQUIRED` without
`required_role` rejected.

## T4 — Transient kind

Build `TransientReason`, `BackendUnavailableError`.

Acceptance: spec US1 scenario 5, US3 scenarios 5–6.

## T5 — Docs (doc-updater)

ARCHITECTURE.md: add `errors` module to the module map and link the
taxonomy section to it. ADR for the three recorded deviations in plan.md.
Glossary entries for the three categories if absent. Draft `review-pr.md`.
