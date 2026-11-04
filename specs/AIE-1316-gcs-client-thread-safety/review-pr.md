# PR Review: AIE-1316 — Verify GCS storage.Client thread-safety

## What changed & why

Verdict: one shared `storage.Client`, its `Bucket`, and one `GcsStorage` are safe across threads, so the MCP adapter needs no per-thread client or lock. Evidence: source reading of google-cloud-storage 3.14.1 (the lockfile's version; the declared `>=2.18` range is unverified), google-auth, and requests, plus stress tests against fake-gcs-server.

- Tests: `tests/integration/test_storage_gcs_threads.py` and `tests/test_storage_gcs_session.py`.
- Code: `GcsStorage(bucket)` builds the client's HTTP session at construction, because `Client._http` publishes its lazy session before mTLS setup, so concurrent first use could race it.
- Docs: the "one client per thread" stopgap is replaced by the verdict and its caveats.
- Docs: `site-src/reference.md` notes that `GcsStorage(bucket)` builds the HTTP session eagerly, so mTLS configuration errors raise from the constructor, with no network call.

## Acceptance criteria → tests

| Acceptance criterion | Test(s) |
| -------------------- | ------- |
| AC1 mixed operations stay isolated | `test_mixed_operations_on_shared_storage_stay_isolated` |
| AC2 one winner on concurrent create | `test_concurrent_create_has_exactly_one_winner` |
| AC3 one winner on concurrent update | `test_concurrent_update_has_exactly_one_winner` |
| AC4 first use of a fresh client (smoke) | `test_first_use_of_fresh_client_from_many_threads_succeeds` |
| AC5 index through `MemoryStore` | `test_concurrent_writes_through_memory_store_all_appear_in_index` |
| AC6 concurrent credential refresh | `test_concurrent_credential_refresh_serves_valid_headers` |
| AC7 gates | `make check`, `make test-integration` |
| AC8 docs | site-src, `site/`, ARCHITECTURE.md, ADRs 0027 and 0003 |
| AC9 eager session | `tests/test_storage_gcs_session.py` |

Sabotage evidence (each made red, then reverted):

- AC1: reading another thread's key gave `assert None is not None`.
- AC2/AC3: `put_if_version` replaced by `put` gave `assert 16 == 1`.
- AC5: dropping one write gave a set mismatch with an extra `t0-r0.md`.
- AC6: `apply()` skipping the header gave `assert False` on the header regex.

## Architecture / ADR changes

- `ARCHITECTURE.md` storage bullet: shared-client verdict, eager session, pointer to caveats.
- ADR 0027 decision 7 and Consequences, and ADR 0003: dated amendments. No new ADR; CAS and storage semantics are unchanged.

## Deviations from spec

- Review added the eager session build in `GcsStorage.__init__` and AC9, so `src/` is not docs-only. See "Review findings and fixes" in `spec.md`.

## Look closely at

- What reviewers caught: the OTel gating claim was wrong (the background bucket-metadata thread runs by default), the mTLS lazy-session race (fixed in code), the version range, the pool size, AC6 not proving overlap, and hang/cleanup issues in the tests.
- Residual caveats: requests does not document `Session` as thread-safe; duplicate credential refreshes are redundant; on a 401 with a rotated client certificate google-auth reconfigures the shared mTLS session mid-request; above 10 concurrent calls urllib3 discards pooled connections (latency, not correctness).

## Follow-ups

- In production the background bucket-metadata fetch needs `storage.buckets.get`, which `roles/storage.objectUser` lacks. It 403s once per client and caches fallback values. This is harmless but shows in audit logs.
