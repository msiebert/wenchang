# PR Review: AIE-1317 — Map RetryError to BackendUnavailableError

## What changed & why

When GCS client retries are exhausted (~120 s), `google.api_core.exceptions.RetryError` escaped `GcsStorage` unmapped, so tools reported an `internal` error instead of the transient `BackendUnavailableError` callers are told to retry. `_map_backend_error` in `src/wenchang/storage/gcs.py` now maps `RetryError` and a bare `GoogleAPICallError` with code 408 (api_core has no dedicated class) to `BackendUnavailableError(TIMEOUT)`. All call sites already route through the mapper and chain with `from exc`, so there is no call-site change.

## Acceptance criteria → tests

All in `tests/test_storage_gcs_errors.py`.

| Acceptance criterion | Test(s) |
| -------------------- | ------- |
| AC1: `RetryError` (cause set, and `None`) on any client call maps to `BackendUnavailableError(TIMEOUT)`, `__cause__ is exc` | Shared parametrized `TIMEOUT_EXCEPTIONS` tests: `test_get_blob_timeout_exceptions_map_to_backend_unavailable_timeout`, `test_download_as_bytes_timeout_exceptions_...`, `test_upload_from_string_timeout_exceptions_...`, `test_put_if_version_upload_timeout_exceptions_...`, `test_delete_if_version_timeout_exceptions_...`, `test_list_blobs_timeout_exceptions_...`, `test_list_blobs_mid_iteration_timeout_exceptions_...` |
| AC2: bare `GoogleAPICallError` with code 408 maps to `TIMEOUT`, `__cause__ is exc` | Same parametrized tests (the `from_http_status(408, ...)` entry) |
| AC3: a real api_core `Retry` that exhausts surfaces as `TIMEOUT` with `RetryError` cause | `test_get_retry_exhaustion_maps_to_backend_unavailable_timeout`, `test_put_if_version_retry_exhaustion_maps_to_backend_unavailable_timeout` |
| AC4: `MethodNotImplemented` (501) and bare `GoogleAPICallError` with code 404 or `None` propagate unchanged | `test_method_not_implemented_from_get_blob_propagates_unchanged`, `test_method_not_implemented_from_upload_propagates_unchanged`, `test_bare_api_call_error_from_get_blob_propagates_unchanged`, `test_bare_api_call_error_from_upload_propagates_unchanged` (404 and `None` cases) |
| AC5: existing mappings unchanged, `make check` passes | Existing unavailable/timeout/propagation tests unchanged; the `__cause__ is exc` assertion was added to the shared timeout tests, which strengthens them |

## api_core sweep

- Already mapped: `DeadlineExceeded`, `GatewayTimeout`, `ServiceUnavailable`, `InternalServerError`, `BadGateway`, `TooManyRequests` (incl. `ResourceExhausted`).
- Newly mapped: `RetryError`, bare `GoogleAPICallError` code 408.
- Deliberately not mapped: grpc-only `Unknown`/`DataLoss`; `Aborted` and 409 conflicts (not transient); `Cancelled` (client-side); `MethodNotImplemented` (501) and 4xx auth/permission/bad-request/precondition classes (permanent); redirections; `DuplicateCredentialArgs` (configuration). Mapping all `GoogleAPIError`/`ServerError` was rejected because it would make 501 and auth errors look transient.

## Architecture / ADR changes

- `ARCHITECTURE.md`, `GcsStorage` storage bullet: one clause now says client timeouts include exhausted client retries and HTTP 408.
- No ADR. This clarifies the existing "client timeouts map to `BackendUnavailableError`" contract. It adds no new semantics and changes no module boundary, public API or storage-protocol behavior. No Notion spec section governs GCS exception classification.
- Glossary unchanged: no product term changed.

## Deviations from spec

- None.

## Look closely at

- `RetryError` always maps to `TIMEOUT`, including the empty-cause `RetryError("Unknown error", None)`. api_core raises it only when the retry deadline elapses; the cause text is kept via `str(exc)`. The reason affects wording only.
- The 408 check relies on `exc.code`; `from_http_status(408, ...)` returns a bare `GoogleAPICallError`.
- The AC3 tests use a real `Retry` with a 0.05 s timeout and assert type, reason and cause, never elapsed time.
- AIE-1316 also edits `gcs.py`, so watch for merge overlap in `_map_backend_error`.

## Follow-ups

- Candidate issue, to be filed by the human: transient non-api_core types that google-cloud-storage's own retry predicate treats as retryable but are still unmapped. These are `google.auth.exceptions.TransportError`, requests `ChunkedEncodingError`, `http.client`/`urllib3` errors, builtin `ConnectionError`, and `google.cloud.storage.exceptions.InvalidResponse` (a real upload failure mode).
- Changing retry deadlines is out of scope.

## Risks

- Low. The change only widens the set of errors classed as transient. The exposure is a 408 that is actually permanent, which is unlikely.
