# Spec Review: AIE-1317 — Map google.api_core RetryError to BackendUnavailableError

## What & why

When GCS client retries are exhausted (~120 s), `RetryError` escapes `GcsStorage` unmapped and tools report an `internal` error rather than the transient `BackendUnavailableError`. We map `RetryError` (and 408 `GoogleAPICallError`) to `BackendUnavailableError(TIMEOUT)` in `_map_backend_error`. No Notion spec section governs this; no Notion deviation.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | Any client call (get_blob, download, upload in put/put_if_version, delete, list_blobs call/mid-iteration) raises `RetryError` (with and without a cause) | storage method runs | `BackendUnavailableError(TIMEOUT)`, `__cause__ is exc` |
| 2 | Client call raises `GoogleAPICallError` with code 408 | storage method runs | `BackendUnavailableError(TIMEOUT)`, `__cause__ is exc` |
| 3 | Stub runs an always-503 function under a real `Retry(timeout=0.05, ...)` | `get()` / `put_if_version()` runs | `BackendUnavailableError(TIMEOUT)`, `__cause__` is `RetryError` (no timing assertions) |
| 4 | `MethodNotImplemented`, or bare `GoogleAPICallError` code 404 / `None` | storage method runs | Propagates unchanged |
| 5 | Existing mappings | change lands | Unchanged; `make check` passes |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| `RetryError` maps to `TIMEOUT` | Derive reason from `RetryError.cause` | Retry deadline elapsed; cause text kept via `str(exc)`; reason only affects wording |
| Map only `RetryError` and 408 | Map all `GoogleAPIError`/`ServerError` | Would make 501 and auth/permission errors look transient (see plan sweep table) |
| One-clause ARCHITECTURE.md edit, no ADR | ADR | Clarifies the existing timeout contract; no new semantics, boundary or API change |
| Add `__cause__ is exc` to shared tests | n/a | Strengthens existing tests; not a Constitution II weakening |

## Files/modules to be touched

- `src/wenchang/storage/gcs.py` (`_map_backend_error`)
- `tests/test_storage_gcs_errors.py`
- `ARCHITECTURE.md` (one clause)

## Open questions / assumptions

- Candidate follow-up issue, to be filed by the human: non-api_core transient types (`google.auth.exceptions.TransportError`, `ChunkedEncodingError`, builtin `ConnectionError`, `InvalidResponse`, a real upload failure mode).

## Risks

- AIE-1316 also edits `gcs.py`; the diff is kept minimal to avoid conflicts.
