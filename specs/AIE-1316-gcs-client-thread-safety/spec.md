AIE-1316

# Feature Specification: Verify GCS storage.Client thread-safety for the MCP adapter

**Linear issue**: AIE-1316 — Verify GCS storage.Client thread-safety for the MCP adapter

**Feature Branch**: `AIE-1316-gcs-client-thread-safety`

**Created**: 2026-11-02

**Status**: Draft

**Input**: The MCP adapter shares one `google.cloud.storage.Client` (via
`GcsStorage`) across its worker threads. Google does not document that client
as thread-safe. The docs tell adopters to use one client per thread as a
stopgap. Determine whether sharing is safe; if not, add a per-thread client or
serialization plus a concurrency test; update the storage docs to match.

## Research / verdict

**Verdict: sharing one `storage.Client` (and its `Bucket`, and one
`GcsStorage`) across threads is safe for wenchang's usage. No locking and no
per-thread client is added.** This is a verification issue: behavior does not
change; tests and docs do.

Source evidence (google-cloud-storage 3.14.1, google-auth, requests, as
installed in `.venv`):

1. google-cloud-storage shares one Client across threads internally:
   `transfer_manager.py` with `worker_type=THREAD` passes the same
   Client/Blob to a `ThreadPoolExecutor` and calls `client._http` from each
   worker (`_upload_part`, ~line 1262: "maybe_pickled_client is either a
   Client (for threads)"). This is an internal precedent in
   google-cloud-storage, not an API contract.
2. The Client's only per-call mutable structure, the batch stack
   (`client._batch_stack`), is a `google.cloud._helpers._LocalStack`, which is
   thread-local. Its bucket metadata cache (`_bucket_metadata_cache.py`) is a
   lock-guarded "Thread-safe LRU cache". wenchang uses neither batches nor
   anything else that mutates client state per call.
   The metadata cache's `get_or_queue_fetch` and `check_and_evict` spawn
   daemon threads that call `client.get_bucket` and `bucket.exists` on the
   shared client. That is more concurrent use of the same client, consistent
   with the verdict. It is gated on `HAS_OPENTELEMETRY` (True in `.venv`,
   because opentelemetry is installed), `enable_otel_traces` (False by
   default; env var `ENABLE_GCS_PYTHON_CLIENT_OTEL_TRACES`), and bucket
   metadata not being disabled. The emulator tests therefore take the non-OTel
   path; production with OTel tracing enabled may take this path.
3. `google.auth.transport.requests.AuthorizedSession.request` passes the
   refresh-attempt counter as a kwarg "to maintain thread-safety" and copies
   headers per request. Credential refresh (`Credentials._blocking_refresh`)
   is unlocked: concurrent threads with an expired token may each refresh,
   which is redundant but benign (each gets a valid token). This is both read
   from source and tested (AC6).
4. `Client._http` creates the `AuthorizedSession` lazily without a lock:
   concurrent first use may build two sessions and keep one; the other serves
   one request and is dropped. Benign and silent (AC4 is a smoke test).
5. Connection pooling is urllib3's thread-safe pool. requests does not
   formally document `Session` as thread-safe; this is the residual
   undocumented piece, covered by the stress tests below.
6. `GcsStorage` adds no mutable state: it holds the bucket and builds a new
   `Blob` per call.

Empirical evidence (scratch runs against fake-gcs-server, 2026-11-02; the
AC1 to AC4 tests reproduce them, AC6 reproduces the credential prototype):

- 32 threads x 20 rounds and 64 threads x 10 rounds at
  `sys.setswitchinterval(1e-6)` on one shared client: zero exceptions, every
  read returned its own thread's write and version, every per-prefix list
  count correct, exactly one winner per concurrent create race.
- 30 trials of 16 threads first-using a fresh client concurrently (lazy
  session race): zero errors.
- 30 rounds of 16 threads `put_if_version` with the same expected token:
  exactly one winner each round.
- Concurrent refresh prototype: a Client with credentials that are always
  inside google-auth's refresh window; 241 refreshes, 241 requests, zero
  errors, every request carried a valid `Bearer tok-N` header.

Rejected alternatives:

| Alternative | Why rejected |
| ----------- | ------------ |
| Thread-local client per worker | Unneeded; multiplies connection pools and token refreshes; changes `GcsStorage`'s constructor and public API |
| Lock serializing all GCS calls | Unneeded; would serialize all network I/O for every tool call |

"No new ADR": constitution line 39 requires an ADR for storage/concurrency
semantics; this records a verified guarantee as dated amendments to existing
ADRs 0027 and 0003 (following ADR 0003's 2026-10-08 `InMemoryStorage`
thread-safety note), and CAS/storage semantics are unchanged.

## Summary

- New integration tests, `tests/integration/test_storage_gcs_threads.py`,
  that stress one shared `Client`/`Bucket`/`GcsStorage` from many threads
  against fake-gcs-server, as a permanent regression guard.
- `GcsStorage` class docstring states it is safe to share across threads, as
  is the `Client`/`Bucket` it wraps, because it adds no mutable state. No
  behavior change, no AIE ID in the docstring. (Parallel issue AIE-1317 edits
  error mapping in the same file; keep this change to the class docstring.)
- Docs replace the "one client per thread" stopgap with the verdict and its
  basis, pin the verified version (google-cloud-storage 3.14.1), say the
  integration tests re-verify on dependency upgrades, and state the residual
  caveats.
- Storage semantics (CAS, versions, errors) do not change.

Out of scope: `src/` behavior, the Storage protocol, the transport, tools, and
the in-memory fake.

## Acceptance criteria

Fixtures: the `storage_emulator_host` fixture from
`tests/integration/conftest.py`; a client built as in
`tests/integration/test_storage_gcs.py`
(`Client(project="test", credentials=AnonymousCredentials(),
client_options={"api_endpoint": host})`; AC6 substitutes its own credentials);
a unique bucket per test with best-effort cleanup. Every test shares ONE
`Client`/`Bucket`/`GcsStorage` across all threads (except AC4, which builds
fresh clients).

Common parameters: 16 threads; 5 rounds (AC4: 10 fresh clients);
`threading.Barrier(16, timeout=30)` releases the threads together;
`join(timeout=60)` then assert no thread is alive;
`sys.setswitchinterval(1e-6)` set in a fixture and restored afterward. The
test file runs in well under 30 s. Assertions are on correctness only, never
timing. Tests carry the `integration` marker and cite `AIE-1316`.

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | One `GcsStorage` shared by 16 threads | Each thread, over 5 rounds, does put / get / put_if_version / get / list_page on its own key prefix, then delete_if_version on its own distinct key | No call raises; every get returns that thread's own latest bytes, metadata, and the version token its write returned; each list_page returns exactly that thread's keys; after the delete, get returns `None` and list_page no longer shows the key |
| 2 | A key that does not exist | 16 threads concurrently `put_if_version(key, ..., expected=None)`; repeated over 5 rounds/keys | Exactly one returns a token, the rest raise `PreconditionFailedError`; `get(key)` returns the winner's bytes and token |
| 3 | An existing key at version `v` | 16 threads concurrently `put_if_version(key, ..., expected=v)`; 5 rounds | Exactly one wins, the others raise `PreconditionFailedError`, and the stored object is the winner's |
| 4 | A freshly constructed `Client` that has made no request yet | 16 threads make their first calls through it concurrently; repeated over 10 fresh clients | All succeed and each reads back its own write. This is a smoke test: the lazy-session race is benign and silent, so a dropped session must not fail the test (the test-writer confirms `pyproject` `filterwarnings` has no `error` filter) |
| 5 | One `InProcessClient(MemoryStore(GcsStorage(shared bucket)))`, no index cache (the default) | 16 threads concurrently write distinct files through the public `MemoryStore`/`InProcessClient` API (distinct or shared entities), then read the memory index | No call raises and the index lists every file written |
| 6 | A `Client` built with a custom `google.auth.credentials.Credentials` subclass whose `refresh()` is lock-counted, sets `token=f"tok-{n}"` and sets `expiry` to `utcnow()` (naive UTC), already inside google-auth's refresh window so every request refreshes; `apply()` is overridden to append `headers["authorization"]` after `super().apply()` to record headers. The Client points at the emulator (fake-gcs-server ignores auth) | 16 threads run put then get on their own keys through one shared `GcsStorage` for 5 rounds | No call raises; every read returns its own write; `refresh()` was called more than once (concurrent refreshes happened); every recorded request carried an `Authorization` header of the form `Bearer tok-N` |
| 7 | The change | `make check` and `make test-integration` | Both pass; `GcsStorage` behavior is unchanged |
| 8 | The docs | Read `site-src/integrate-without-mcp.md` (including line 30, "except where Threads says otherwise"), `storage.md`, `status.md`, `ARCHITECTURE.md`, ADRs 0027 and 0003 | None still say the client must not be shared or that thread-safety is unverified; `site/` is regenerated; grep of `site/` and `site-src/` finds no "per thread", "not documented as thread-safe", or "Not guaranteed" strings left over |

Notes:

- fake-gcs-server does not enforce `ifGenerationMatch` on DELETE (see the skip
  in `test_storage_gcs.py`), so one-winner concurrent delete is not tested.
  AC1's deletes are on distinct keys.
- GCS generations are per object, so distinct version tokens across different
  keys is not a GCS guarantee and is not asserted.
- The tests are expected to pass on the current code. Each AC class must be
  shown able to fail (see tasks.md T1).

## Non-functional

- No new dependencies. Tests finish in seconds.
- Docs state the residual caveats honestly: the guarantee rests on an internal
  google-cloud-storage precedent plus these stress tests, not on a documented
  upstream contract; the verified version is google-cloud-storage 3.14.1.
