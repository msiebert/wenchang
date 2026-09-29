# 0012. delete_file

Date: 2026-09-29

## Status

Accepted

## Context

AIE-1037 delivers `delete_file`, the "delete the whole file" half of
forgetting (Notion Section 8.1). The `Storage` protocol has no delete
today, so it needs one, and `core` needs to decide what a delete of an
already-absent file means for a caller that can't tell its own landed
retry apart from someone else's delete.

## Decision

- **The `Storage` protocol gains only `delete_if_version(key, expected)` —
  a guarded delete, no unconditional delete.** Every mutation through the
  protocol is already conditional (`put_if_version`); adding an
  unconditional delete would be the one way to remove an object without a
  version check, and nothing in `core` needs it. An absent object or a
  version mismatch both raise the existing `PreconditionFailedError(key)`,
  the same signal `put_if_version` uses for its own precondition failure,
  so no new storage-level exception is needed. `core` re-reads to tell a
  conflict from an absence, the same pattern `write_file` and `append_line`
  already use.
- **`GcsStorage.delete_if_version` rejects a non-canonical token locally**
  (as `put_if_version` does), then calls `blob.delete(if_generation_match=
  int(expected))`. Both GCS's `PreconditionFailed` (wrong generation) and
  `NotFound` (already absent) map to `PreconditionFailedError`; any other
  exception goes through the shared `_map_backend_error`.
- **An already-absent file raises `NotFoundError(FILE_ABSENT)`, not
  idempotent success — including on an identical retry of a delete that
  already landed.** This matches every other mutating call in `core`:
  `write_file`'s `expected_version=None` against an existing file,
  `append_line` and `replace_fact` against a stale token, all surface a
  failure rather than silently treating the caller's intent as satisfied.
  A GCS client-level retry of a landed delete sees `NotFound`, which is
  indistinguishable from someone else having deleted the file first — the
  library cannot tell those apart, and the end state (file gone) is the
  same either way, so it doesn't try. Agent-facing tool wording (AIE-1044)
  should treat "already gone" as done rather than surfacing this as an
  error to the agent.
- **`delete_file` returns `None` and takes no `source`.** There is nothing
  left to version, stamp, or hand back for a file that no longer exists —
  unlike `write_file`, `replace_fact`, and `append_line`, which all return
  the resulting `MemoryFile`.
- **Metadata is not parsed.** `delete_file` never calls
  `metadata_from_map`, so a file with corrupt metadata (which would raise
  `MetadataFormatError` from `read_file`) is still deletable.
- **The stale-token conformance case is skipped for `GcsStorage`
  specifically, not for the suite as a whole.** fake-gcs-server ignores
  `ifGenerationMatch` on `DELETE` requests, so a stale-token delete against
  the emulator succeeds instead of raising `PreconditionFailedError`. The
  shared `test_delete_if_version_with_stale_token_raises_and_leaves_object_
  unchanged` case in `tests/storage_conformance.py` still runs for
  `InMemoryStorage`; `TestGcsStorage` in
  `tests/integration/test_storage_gcs.py` overrides it with
  `pytest.mark.skip`, and the real `GcsStorage` → real-client mapping
  (`PreconditionFailed` → `PreconditionFailedError`) is covered instead by
  a stub-based unit test in `tests/test_storage_gcs_errors.py`
  (`test_delete_if_version_precondition_failed_raises_precondition_failed_error`).
  `GcsStorage.delete_if_version` does pass `if_generation_match` to the
  real client regardless; only the emulator fails to enforce it.

## Consequences

`delete_file` is not idempotent in the sense some callers might expect —
two identical calls in a row raise `NotFoundError(FILE_ABSENT)` on the
second, not `None` both times. Callers (and AIE-1044's tool wording) must
treat that specific error as "already done," not as a failure to surface
to a human. The `Storage` protocol has no unconditional delete, so nothing
above `core` can remove an object without proving it holds the current
version, consistent with every other mutation.

The skipped GCS integration test means the stale-token-rejection behavior
of `delete_if_version` against a real GCS-compatible backend is verified
only by a stub, not by round-tripping through fake-gcs-server. If a future
emulator version starts enforcing `ifGenerationMatch` on `DELETE`, the skip
should be removed.

**Alternatives rejected:**

- **An unconditional `Storage.delete(key)`, guarded only in `core`.**
  Rejected because it would let a bug or a future caller above `core` (or
  a test double) delete an object with no version check at all, the one
  gap in an otherwise fully-guarded protocol.
- **Idempotent-success on an already-absent file** (return `None` instead
  of raising). Simpler for a caller that only wants "make sure this file
  is gone," but inconsistent with how every other mutating call treats a
  precondition it can't satisfy, and it would hide a genuine race (another
  caller's delete) behind the same return value as this caller's own
  retry. Rejected in favor of `FILE_ABSENT`, with the tool layer
  responsible for presenting it as success where that's the right agent
  experience.
- **A new storage-level not-found exception**, distinct from
  `PreconditionFailedError`. Rejected because `core` already re-reads
  after any `PreconditionFailedError` to get current content and version
  for `VersionConflictError`; reusing the same exception for "absent" costs
  nothing extra there and keeps the storage-level exception surface at one
  precondition signal, matching `put_if_version`.
