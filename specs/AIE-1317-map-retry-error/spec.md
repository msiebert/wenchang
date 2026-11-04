# Feature Specification: Map google.api_core RetryError to BackendUnavailableError

**Linear**: AIE-1317

**Status**: Draft

## Problem

When GCS client retries are exhausted (~120 s), `google.api_core.exceptions.RetryError` escapes `GcsStorage` (`_map_backend_error` in `src/wenchang/storage/gcs.py`) unmapped. Tools then report it as an `internal` error instead of the transient `BackendUnavailableError` callers are told to retry.

No Notion spec section governs GCS exception classification, so there is no Notion deviation.

## Scope

In: map `RetryError`, and the 408 `GoogleAPICallError` (api_core has no dedicated class), to `BackendUnavailableError(TIMEOUT)` in the GCS storage layer. No public API or storage-protocol change.

Out (candidate follow-up issue, to be filed by the human; none is filed from this run):
- Transient non-api_core types that google-cloud-storage's own retry predicate treats as retryable but are unmapped today: `google.auth.exceptions.TransportError`, requests `ChunkedEncodingError`, `http.client`/`urllib3` errors, builtin `ConnectionError`, `google.cloud.storage.exceptions.InvalidResponse` (a real upload failure mode).
- grpc-only `Unknown`/`DataLoss` (never raised by the JSON API client).
- Changing retry deadlines.

## Acceptance Criteria

1. **Given** any `GcsStorage` client call (`get_blob`, `download_as_bytes`, `upload_from_string` in `put` and `put_if_version`, `blob.delete` in `delete_if_version`, `list_blobs` call and mid-iteration) raises `RetryError` (both `RetryError("m", ServiceUnavailable("x"))` and `RetryError("m", None)`), **When** the storage method runs, **Then** it raises `BackendUnavailableError` with reason `TransientReason.TIMEOUT`, chained `from` the `RetryError` (`__cause__ is exc`).
2. **Given** a client call raises a `GoogleAPICallError` whose `code` is 408 (`from_http_status(408, ...)` returns a bare `GoogleAPICallError`), **When** the storage method runs, **Then** it raises `BackendUnavailableError(TIMEOUT)` with `__cause__ is exc`.
3. **Given** the stub's `get_blob` (and `upload_from_string` for `put_if_version`) calls `Retry(predicate=if_exception_type(ServiceUnavailable), initial=0.001, maximum=0.002, timeout=0.05)(always_raise_503)()` (real api_core `Retry`; `timeout=`, not the deprecated `deadline=`), **When** `get()` (and `put_if_version()`) runs, **Then** `BackendUnavailableError(TIMEOUT)` is raised and `isinstance(__cause__, RetryError)`. The test asserts type, reason and cause, never elapsed time.
4. **Given** `get_blob` or `upload_from_string` raises `MethodNotImplemented` (501), **When** the storage method runs, **Then** it propagates unchanged. Boundary cases: a bare `GoogleAPICallError` with code 404 and with code `None` also propagate unchanged (mapping is not broadened to all `ServerError`/`GoogleAPIError`).
5. **Given** the existing mappings, **When** the change lands, **Then** they are unchanged and `make check` passes.
