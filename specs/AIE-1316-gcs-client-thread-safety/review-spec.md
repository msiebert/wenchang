# Spec Review: AIE-1316 — Verify GCS storage.Client thread-safety

## What & why

The MCP adapter shares one `google.cloud.storage.Client` (via `GcsStorage`)
across worker threads, and the docs told adopters to use one client per thread
because Google does not document the client as thread-safe. Source reading and
stress runs against fake-gcs-server show sharing is safe for wenchang's usage,
so no code changes: we add threaded integration tests as a regression guard,
a `GcsStorage` docstring, and docs that state the verdict and residual caveats.

## Acceptance criteria (condensed; full table in spec.md)

All with 16 threads, 5 rounds (AC4: 10 fresh clients), barrier timeout 30 s,
join timeout 60 s, `setswitchinterval(1e-6)`; correctness assertions only.

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | One `GcsStorage`, 16 threads | put/get/put_if_version/get/list_page on own prefixes, then delete_if_version on own key | No errors; each thread reads its own bytes, metadata, token; lists exactly its keys; after delete, get is `None` and list omits it |
| 2 | A missing key | 16 threads `put_if_version(expected=None)` | One winner; rest `PreconditionFailedError`; stored object is the winner's |
| 3 | A key at version `v` | 16 threads `put_if_version(expected=v)` | One winner; rest `PreconditionFailedError` |
| 4 | A fresh client, no request yet | 16 threads first-use it together | All succeed, each reads its own write (smoke test; dropped sessions must not fail it) |
| 5 | `InProcessClient(MemoryStore(GcsStorage))`, no cache | Threads write distinct files, then read the index | No errors; index lists every file |
| 6 | Credentials always inside the refresh window, lock-counted `refresh()` | 16 threads put then get on own keys | No errors; own reads; `refresh()` called more than once; every request has `Bearer tok-N` |
| 7 | The change | `make check`, `make test-integration` | Pass; behavior unchanged |
| 8 | The docs | Read them; grep for stale phrases | No "one client per thread" or "not verified" claims; `site/` regenerated |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | --------------------- | --- |
| Keep one shared client, add no synchronization | Thread-local client per worker; lock around all GCS calls | google-cloud-storage shares a client across threads internally (a precedent, not an API contract); per-call mutable state is thread-local or lock-guarded; a per-thread client multiplies pools and token refreshes and changes `GcsStorage`'s constructor; a lock serializes all network I/O |
| Guard with integration tests, including concurrent credential refresh | Docs-only change | The undocumented pieces (requests `Session`, unlocked refresh) need a regression check; tests re-verify on dependency upgrades |
| Show tests can fail via a named in-test sabotage per AC class | Reasoning only | Tests pass on first run, so only a recorded red run proves they bite |
| Amend ADRs 0027 and 0003, no new ADR | New ADR | Constitution line 39 requires an ADR for storage/concurrency semantics; this records a verified guarantee on existing ADRs, following ADR 0003's 2026-10-08 note precedent; CAS/storage semantics are unchanged |

## Files/modules to be touched

- New `tests/integration/test_storage_gcs_threads.py`.
- `src/wenchang/storage/gcs.py` (class docstring only, no AIE ID).
- `site-src/integrate-without-mcp.md`, `storage.md`, `status.md`,
  `snippets/integrate_direct.py`; regenerated `site/`.
- `ARCHITECTURE.md`; `docs/adr/0027-mcp-host-adapter.md` and
  `docs/adr/0003-storage-interface-with-in-memory-fake-and-gcs-emulator.md`
  (amendments).

## Open questions / assumptions

- No one-winner concurrent-delete test: fake-gcs-server does not enforce
  `ifGenerationMatch` on DELETE. AC1 deletes distinct keys.
- Distinct version tokens across different keys is not asserted (GCS
  generations are per object).
- The verdict covers wenchang's usage (no batches, no per-call client
  mutation), not arbitrary use of `storage.Client`; pinned to
  google-cloud-storage 3.14.1.
- `pyproject` `filterwarnings` is believed to have no `error` filter; the
  test-writer confirms.

## Risks

- Guarantee rests on upstream implementation details, not a documented
  contract; requests does not formally document `Session` thread-safety.
- Concurrent expired-token refresh may issue duplicate refresh requests
  (redundant, benign, tested by AC6); documented.
- With OpenTelemetry tracing enabled, the client's bucket metadata cache makes
  background calls on the shared client; consistent with the verdict but not
  exercised by the emulator tests.
- Stress tests are probabilistic; they complement, not replace, the source
  analysis.
