# 0008. Conditional put and write_file semantics

Date: 2026-09-28

## Status

Accepted

## Context

AIE-1033 delivers `write_file`, the second core API function, and the
conditional put the storage layer needs to support it (`put` stayed
unconditional per ADR 0007). Several points needed a decision beyond a
literal reading of the Notion spec and the Linear issue text; all were
raised and resolved at the spec checkpoint on 2026-09-28.

## Decision

- **`expected_version=None` means "create; must not exist," and the
  parameter has no default.** Creating a file is the one mutating call with
  no prior token to hold, and GCS expresses it natively
  (`ifGenerationMatch=0`). Making the parameter required, with no default
  that would mean "unconditional," forces every caller to state which case
  it means. Rejected alternative: a separate `create_file` call, which would
  duplicate the path/size/stamping logic `write_file` already has to do.
- **A non-`None` token against an absent file raises
  `NotFoundError(FILE_ABSENT)`, not `VersionConflictError`.** There is no
  current content to return in that case, and the correction is to create
  the file, not to merge. Rejected alternative: `VersionConflictError` with
  empty content, which would be indistinguishable from a real conflict at an
  empty file.
- **The storage protocol gets its own `put_if_version`; `put` stays
  unconditional.** `PreconditionFailedError` is a new, plain `Exception`
  subclass (not `WenchangError`) — an internal signal between storage and
  `core`, never surfaced to agents. Storage reports the failed precondition;
  `core` is the layer that decodes content and builds
  `VersionConflictError`, consistent with storage having no knowledge of the
  error taxonomy. Rejected alternatives: adding an optional precondition to
  `put` itself (would need a sentinel for "no precondition" and touch every
  existing caller); having storage raise `VersionConflictError` directly
  (would put taxonomy knowledge in the storage layer).
- **An unrecognized or non-canonical token is a mismatch (conflict), never a
  parse error.** Callers never parse tokens, so the library cannot ask them
  to supply well-formed ones; any token that doesn't match the current
  version is just wrong, whatever it looks like. In `GcsStorage`
  specifically, a token that isn't the canonical decimal form of a positive
  integer (rejecting `"0"`, `"007"`, `"-1"`, `"abc"`, `""`, matched by
  `^[1-9][0-9]*$`) fails the precondition locally with no client call — this
  keeps `"0"` from ever being read as "must not exist" (that's what
  `expected=None` is for) and keeps the parse in exactly one place. Rejected
  alternative: `int(expected)` and letting GCS reject the resulting
  generation, which would let `"0"` collide with the create-only case and
  would raise on non-numeric strings instead of a precondition failure.
- **The byte ceiling counts the content's UTF-8 bytes only, is inclusive,
  and is checked before storage is consulted.** The ceiling exists so a
  `read_file` response fits in one call; metadata (description, aliases,
  sources) is unbounded by it. Checking size before issuing the conditional
  put means an oversize write is rejected even when the expected version is
  also stale (`OversizeWriteError`, not `VersionConflictError`), and the
  store's `max_file_bytes` is a positive int required at `MemoryStore`
  construction (default 16384; non-positive raises `ValueError`).
- **`core` stamps `last_updated` from an injectable clock, overriding the
  caller's value.** Notion says `last-updated` is "refreshed on any write";
  `append_line` and `replace_fact` (both later work) have no metadata
  argument at all, so `core` has to stamp there regardless, and doing it
  uniformly in `write_file` too means no write path can forget to refresh
  the field. The clock defaults to `datetime.now(UTC)` and is injected for
  deterministic tests; a naive datetime from the clock is rejected by
  `FileMetadata`'s own validation (`ValueError`), and nothing is written.
  `sources` is stored as supplied — stamping which calling surface wrote is
  the tool layer's job (AIE-1044), out of scope here.

## Consequences

`write_file` and the conditional put can be tested end-to-end against
`InMemoryStorage`, and the same conformance suite
(`tests/storage_conformance.py`) that already held `get`/`put` identical
across `InMemoryStorage` and `GcsStorage` (ADR 0007) now also covers
`put_if_version`, including the "create only if absent" and
unrecognized/non-numeric-token cases, against both. Because widening the
`Storage` protocol with a new abstract method breaks `GcsStorage` under
pyright strict until it implements `put_if_version`, the storage-layer task
(T1) and the GCS implementation task (T2) landed as one commit rather than
strictly test-then-implement per file; the GCS-specific stub tests in
`tests/test_storage_gcs_errors.py` for `put_if_version` were consequently
written and merged alongside the implementation rather than run red first.
This supersedes ADR 0007's "`put` is unconditional in this issue"
consequence: `put` itself is unchanged, but the protocol it sits beside no
longer lacks a precondition path. `system/` read-only enforcement (AIE-1040)
and role-gated scope enforcement (AIE-1042) remain out of scope; `system/`
paths are writable by `write_file` until those land.
