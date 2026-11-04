# Plan: Map RetryError to BackendUnavailableError (AIE-1317)

## Interface

No public API or storage-protocol change. `_map_backend_error(exc: Exception) -> BackendUnavailableError | None` in `src/wenchang/storage/gcs.py` gains two `TIMEOUT` cases:

- `isinstance(exc, RetryError)`
- `isinstance(exc, GoogleAPICallError) and exc.code == 408`

All call sites already route through `_map_backend_error` and chain with `from exc`, so no call-site change. Keep the diff minimal: AIE-1316 also edits `gcs.py`.

## Rationale

api_core raises `RetryError` only when the retry deadline elapses (`RetryFailureReason.TIMEOUT`); for a non-retryable error the default exception factory re-raises the original exception. So `RetryError` means the retry deadline elapsed, hence `TIMEOUT`. The cause's text is preserved in the detail via `str(exc)`. The reason only affects message wording; guidance is the same for both `TransientReason`s. The `RetryError("Unknown error", None)` empty-list path still maps to `TIMEOUT`.

Rejected:
- Deriving the reason from `RetryError.cause`: the user-visible fact is the deadline expiring, and the reason changes only wording; extra complexity.
- Mapping all `GoogleAPIError`/`ServerError`: would wrongly make 501 and auth/permission errors transient.

## api_core sweep

| Status | Classes | Reason |
| ------ | ------- | ------ |
| Already mapped | `DeadlineExceeded`, `GatewayTimeout`, `ServiceUnavailable`, `InternalServerError`, `BadGateway`, `TooManyRequests`, `ResourceExhausted` (a `TooManyRequests` subclass) | |
| Newly mapped | `RetryError`, bare `GoogleAPICallError` with code 408 | Deadline elapsed / request timeout |
| Not mapped | `Unknown`, `DataLoss` | grpc-only |
| Not mapped | `Aborted`, `AlreadyExists`/`Conflict` (409) | Not retried by GCS's own predicate; conflicts are not transient |
| Not mapped | `Cancelled` (499) | Client-side |
| Not mapped | `MethodNotImplemented` (501) and all 4xx auth/permission/bad-request/precondition classes | Permanent |
| Not mapped | Redirection classes | Not failures |
| Not mapped | `DuplicateCredentialArgs` | Configuration |

## Tests

In `tests/test_storage_gcs_errors.py`:
- Add `RetryError("m", ServiceUnavailable("x"))`, `RetryError("m", None)` and a 408 `GoogleAPICallError` to `TIMEOUT_EXCEPTIONS`, covering every client-call path.
- Add `assert excinfo.value.__cause__ is exc` to the shared parametrized TIMEOUT tests. This strengthens existing tests (it also checks chaining for the existing entries), so it is not a Constitution II weakening.
- Add the real-`Retry` exhaustion tests per spec AC3 (`get`, `put_if_version`).
- Add propagates-unchanged tests per AC4 (`MethodNotImplemented` via `get_blob` and `upload_from_string`; bare `GoogleAPICallError` code 404 and `None`).

## Docs

One-clause ARCHITECTURE.md tweak in the `GcsStorage` storage bullet: "client timeouts, including exhausted client retries". This clarifies the existing "client timeouts -> `BackendUnavailableError`" contract: no new semantics, no boundary or API change, so no ADR (governance's justify-in-PR applies; review-pr.md states this).
