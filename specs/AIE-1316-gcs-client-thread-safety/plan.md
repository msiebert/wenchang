# Implementation Plan: AIE-1316 GCS client thread-safety

**Branch**: `AIE-1316-gcs-client-thread-safety` | **Date**: 2026-11-02 | **Spec**: [spec.md](spec.md)

## Summary

Verification issue. Source reading and stress runs found one shared
`storage.Client` safe for wenchang's usage (spec.md, "Research / verdict"). Add
a threaded integration test file as a regression guard, add a class docstring
on `GcsStorage`, and replace the "one client per thread" stopgap in the docs.
No behavior change, no storage-semantics change.

## Technical Context

Python 3.11+, pytest, pyright strict, ruff. No new dependencies (stdlib
`threading`, `sys`). Gate: `make check`, plus `make test-integration` (run
`make emulator-up` first) because storage is exercised.

## Constitution Check

- Tests first: T1 writes the tests; they pass immediately because the behavior
  exists, and each AC class is shown able to fail by a temporary in-test
  sabotage (never `src/` edits).
- Storage only through the `Storage` interface: tests use `GcsStorage` and the
  public `MemoryStore`/`InProcessClient`; GCS is touched directly only to build
  the fixture client and bucket, as `test_storage_gcs.py` does.
- No public API change; ARCHITECTURE.md gets wording changes only. No new ADR
  (justification in spec.md); ADRs 0027 and 0003 get dated amendments.

## Tests (T1)

New `tests/integration/test_storage_gcs_threads.py`, marker `integration`.

- Reuse `storage_emulator_host` (`tests/integration/conftest.py`); build the
  client as in `tests/integration/test_storage_gcs.py`; unique bucket per
  test; best-effort cleanup.
- Constants: 16 threads, 5 rounds (AC4: 10 fresh clients),
  `Barrier(16, timeout=30)`, `join(timeout=60)` then assert no thread alive.
  A fixture sets `sys.setswitchinterval(1e-6)` and restores it. Correctness
  assertions only, no timing; the file runs well under 30 s.
- Helper: run N worker callables via the barrier, join with timeout, assert
  none alive, re-raise collected exceptions.
- Tests map to spec.md AC1 to AC6. AC1 includes a delete_if_version of each
  thread's own distinct key, then get is `None` and list_page omits it. AC4
  builds a fresh `Client` per trial, is a smoke test, and must not fail on
  dropped sessions; confirm `pyproject` `filterwarnings` has no `error`
  filter. AC6 uses a `Credentials` subclass with a lock-counted `refresh()`
  (sets `token=f"tok-{n}"`, `expiry=utcnow()` naive), and `apply()` overridden
  to record `headers["authorization"]` after `super().apply()`; the emulator
  ignores auth.
- AC5 construction, with no index cache (the default):
  - `MemoryStore` is in `src/wenchang/core.py` (class ~line 421, `__init__`
    ~line 434):
    ```python
    def __init__(
        self,
        storage: Storage,
        *,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
        clock: Callable[[], datetime] = _utc_now,
        list_page_size: int = DEFAULT_LIST_PAGE_SIZE,
        index_max_bytes: int = DEFAULT_INDEX_MAX_BYTES,
        scope_priority: Sequence[str] = (),
        max_files_per_entity: int | None = DEFAULT_MAX_FILES_PER_ENTITY,
        index_cache: IndexCache | None = None,
    ) -> None
    ```
  - `InProcessClient(store: MemoryStore)` is in `src/wenchang/transport.py`
    (~line 107).
  - See also `site-src/snippets/integrate_direct.py` for construction.
- No concurrent one-winner delete test (emulator does not enforce
  `ifGenerationMatch` on DELETE).
- The AC1 to AC4 tests reproduce the scratch runs in spec.md.

## Source (T2)

`src/wenchang/storage/gcs.py`: extend the `GcsStorage` class docstring and build
the bucket client's HTTP session in `__init__` (tolerating `Bucket(client=None)`); it
is safe to share across threads, as is the `Client`/`Bucket` it wraps, because
it holds no mutable state (new `Blob` per call). No AIE ID in the docstring.
Do not touch error mapping (AIE-1317 edits it).

## Docs (T3)

- `site-src/integrate-without-mcp.md`, "Threads and async hosts": the
  `GcsStorage` and `google.cloud.storage.Client`/`Bucket` rows become "Safe".
  Replace the "storage.Client is not documented as thread-safe" paragraph and
  the per-thread bullets with a short verdict and its basis: an internal
  precedent in google-cloud-storage (not an API contract) plus wenchang's
  integration tests, which re-verify on dependency upgrades; name the verified
  version (google-cloud-storage 3.14.1, the lockfile's; the declared `>=2.18`
  range is unverified). Residual caveats: requests does not
  formally document `Session` thread-safety; concurrent credential refresh may
  duplicate refresh requests; the client's
  bucket metadata cache starts a daemon thread on the first call per bucket
  that calls `get_bucket` on the shared client, by default and not gated on
  OTel (`DISABLE_GCS_PYTHON_CLIENT_OTEL_BUCKET_METADATA=true` disables it);
  mTLS residual on a 401 with a rotated certificate; the default 10-connection
  pool. `GcsStorage.__init__` builds the client's HTTP session up front.
  Also fix line 30 ("except where Threads says otherwise") if it no longer
  fits.
- `site-src/storage.md` (line 7 sentence), `site-src/status.md` ("Concurrency
  is the caller's concern" bullet), `site-src/snippets/integrate_direct.py`
  (comment near line 25): update to match.
- Regenerate `site/` with `uv run scripts/build_site.py`. Afterward grep
  `site/` and `site-src/` to confirm no "per thread", "not documented as
  thread-safe", or "Not guaranteed" strings remain.
- `ARCHITECTURE.md`: storage bullet (~lines 143-146) and MCP threading section
  (~line 1300) state `GcsStorage` is safe to share across threads.
- ADRs, each with a dated "Amended (2026-11-02, AIE-1316)" note recording the
  verdict and pointing to the tests:
  - `docs/adr/0027-mcp-host-adapter.md`: decision 7 last bullet (~line 151,
    says `GcsStorage` client thread-safety "is not verified here") and
    Consequences (~line 260, "GcsStorage is a follow-up").
  - `docs/adr/0003-storage-interface-with-in-memory-fake-and-gcs-emulator.md`:
    next to its 2026-10-08 `InMemoryStorage` thread-safety note.
- `specs/AIE-1316-gcs-client-thread-safety/review-pr.md` from
  `docs/templates/review-pr-template.md`, including the recorded red output
  from the T1 sabotage runs.

## Risks

- Stress tests assert correctness only (no timing) with generous barrier and
  join timeouts, to avoid flakiness.
- The guarantee rests on upstream implementation details (requests `Session`),
  which can change; the tests are the guard.
