# PR Review: AIE-1033 — write_file

## What changed & why

Adds `MemoryStore.write_file(path, content, metadata, expected_version) ->
MemoryFile`, the second core API function, and the conditional put the
storage layer needs to support it: `Storage.put_if_version(key, data,
metadata, expected)`, implemented in both `InMemoryStorage` and
`GcsStorage` (GCS `ifGenerationMatch`), reporting a failed precondition as
`PreconditionFailedError` — an internal signal, not a `WenchangError` —
which `core` translates into `VersionConflictError` or
`NotFoundError(FILE_ABSENT)`. `write_file` also enforces a per-`MemoryStore`
byte ceiling on content (default 16384 bytes, `OversizeWriteError` on
overflow) and stamps `last_updated` from an injectable clock, overriding
whatever the caller supplied. `MemoryStore` gains keyword-only
`max_file_bytes` and `clock` constructor options.

## Acceptance criteria → tests

| # | Given / When / Then | Test(s) |
| - | -------------------- | ------- |
| US1-1 | No file, `write_file(path, C, M, None)` → `MemoryFile` with path/content/metadata/token; `read_file` agrees | `test_core_write_file.py::test_write_file_creates_file_and_read_file_agrees` |
| US1-2 | File exists, `write_file(path, C, M, None)` → `VersionConflictError` with existing content/version; unchanged | `test_core_write_file.py::test_write_file_with_none_expected_conflicts_when_file_exists` |
| US2-1 | File at `V`, write with `V` → new token `≠V`; `read_file` returns new content/metadata | `test_core_write_file.py::test_write_file_updates_with_matching_expected_version` |
| US2-2 | File moved to `V2`, write with stale `V` → `VersionConflictError(path, content@V2, V2)`; unchanged | `test_core_write_file.py::test_write_file_with_stale_expected_version_conflicts` |
| US2-3 | Retry `write_file` with the conflict's version → succeeds | `test_core_write_file.py::test_write_file_retry_with_conflict_version_succeeds` |
| US2-4 | No file, non-`None` expected version → `NotFoundError(FILE_ABSENT)`, nothing written | `test_core_write_file.py::test_write_file_with_expected_version_and_no_file_raises_file_absent` |
| US2-5 | Token no write ever produced (opaque, incl. non-numeric) → `VersionConflictError` with current content/version, never a parse error | `test_core_write_file.py::test_write_file_with_unmatched_expected_version_conflicts_with_current_state` |
| US2-6 | Retry with the same expected version after a landed write → `VersionConflictError` with content equal to what the first attempt wrote | `test_core_write_file.py::test_write_file_retrying_same_successful_call_conflicts_with_own_write` |
| US3-1 | Two successive writes; read returns second's content paired with second's metadata, never mixed | `test_core_write_file.py::test_write_file_sequential_writes_never_mix_content_and_metadata` |
| US3-2 | Any rejected write (invalid path, version conflict, naive clock, file absent, oversize) leaves a following `read_file` identical, including the token | `test_core_write_file.py::test_write_file_invalid_path_leaves_prior_read_behavior_unchanged`, `test_write_file_conflict_leaves_prior_state_including_token_unchanged`, `test_write_file_naive_clock_leaves_prior_state_unchanged`, `test_write_file_file_absent_leaves_prior_state_absent`, `test_write_file_oversize_leaves_existing_file_and_token_unchanged` |
| US3-3 | Content (unicode, `\r\n`, fact-like markdown, no/with trailing newline, empty) and metadata (unicode, commas, quotes, brackets in aliases/sources) round-trip exactly | `test_core_write_file.py::test_write_file_round_trips_content_exactly` (parametrized), `test_write_file_round_trips_metadata_with_special_characters` |
| US4-1 | Content exactly 16384 UTF-8 bytes → accepted | `test_core_write_file.py::test_write_file_at_default_byte_ceiling_succeeds` |
| US4-2 | Content 16385 UTF-8 bytes → `OversizeWriteError(path, size=16385, limit=16384)`, storage not written | `test_core_write_file.py::test_write_file_over_default_byte_ceiling_raises_oversize_and_writes_nothing`, `test_write_file_over_default_byte_ceiling_leaves_path_absent` |
| US4-3 | Size counted in UTF-8 bytes, not characters (5462 `"€"` = 16386 bytes rejected) | `test_core_write_file.py::test_write_file_byte_size_counts_utf8_bytes_not_characters` |
| US4-4 | `max_file_bytes=100`: 101 bytes → `limit==100`; 100 bytes succeed | `test_core_write_file.py::test_write_file_custom_max_file_bytes_rejects_one_byte_over`, `test_write_file_custom_max_file_bytes_accepts_exact_limit` |
| US4-5 | `max_file_bytes` of `0` or negative at construction → `ValueError` | `test_core_write_file.py::test_max_file_bytes_non_positive_raises_value_error_at_construction` (parametrized) |
| US4-6 | Oversize write with a also-stale expected version → `OversizeWriteError`, size checked before storage | `test_core_write_file.py::test_write_file_oversize_with_stale_expected_version_raises_oversize_not_conflict` |
| US5-1 | Clock returns `T`, caller supplies `last_updated=T0≠T` → stored/returned `last_updated==T`; other fields as given | `test_core_write_file.py::test_write_file_stamps_last_updated_from_clock_overriding_caller_value` |
| US5-2 | No clock override → `last_updated` is tz-aware UTC within the call's bounds | `test_core_write_file.py::test_write_file_default_clock_stamps_tz_aware_utc_now` |
| US5-3 | Clock returns a naive datetime → `ValueError`, nothing written | `test_core_write_file.py::test_write_file_naive_clock_raises_value_error_and_writes_nothing` |
| US6-1 | Malformed path → `NotFoundError(INVALID_PATH)`, storage never consulted | `test_core_write_file.py::test_write_file_raises_not_found_invalid_path_without_calling_storage` (parametrized) |
| US6-2 | `BackendUnavailableError` from `put_if_version` or from the follow-up `get` → propagates unchanged | `test_core_write_file.py::test_write_file_propagates_backend_unavailable_error_from_put_unchanged`, `test_write_file_propagates_backend_unavailable_error_from_get_on_conflict_unchanged` |
| US6-3 | GCS: upload fails its generation precondition → storage-level `PreconditionFailedError`, not a GCS exception; timeout/unavailable map as for `get` | `test_storage_gcs_errors.py::test_put_if_version_upload_precondition_failed_raises_precondition_failed_error`, `test_put_if_version_upload_timeout_exceptions_map_to_backend_unavailable_timeout`, `test_put_if_version_upload_unavailable_exceptions_map_to_backend_unavailable_unavailable`, `test_put_if_version_unmapped_exception_from_upload_propagates_unchanged` |
| US7-1 | No object, conditional put with `expected=None` → token; get returns the object | `storage_conformance.py::test_put_if_version_none_on_missing_key_creates_object` |
| US7-2 | Object exists, conditional put with `expected=None` → `PreconditionFailedError`, object unchanged | `storage_conformance.py::test_put_if_version_none_on_existing_key_raises_and_leaves_object_unchanged` |
| US7-3 | Object at `V`, conditional put with `V` → new token, get returns new bytes+metadata together | `storage_conformance.py::test_put_if_version_with_current_token_succeeds_and_returns_new_token` |
| US7-4 | Object at `V2` (after `V`), conditional put with `V` → `PreconditionFailedError`, object unchanged | `storage_conformance.py::test_put_if_version_with_stale_token_raises_and_leaves_object_unchanged` |
| US7-5 | No object, conditional put with a non-`None` token → `PreconditionFailedError`, nothing created | `storage_conformance.py::test_put_if_version_with_foreign_token_on_missing_key_raises_and_stays_missing` |
| US7-6 | Token no put produced (incl. non-numeric) → `PreconditionFailedError` | `storage_conformance.py::test_put_if_version_with_token_no_put_produced_raises_and_leaves_object_unchanged` |

Also covered, not tied to a numbered scenario: `put_if_version` copies the
caller's metadata mapping
(`storage_conformance.py::test_put_if_version_mutating_callers_metadata_dict_after_put_does_not_affect_storage`);
`PreconditionFailedError` is not a `WenchangError`
(`storage_conformance.py::test_precondition_failed_error_is_not_a_wenchang_error`);
a conflict follow-up `get` finding the file deleted, a corrupt stored
object, or non-UTF-8 bytes propagate `NotFoundError(FILE_ABSENT)`,
`MetadataFormatError`, and `UnicodeDecodeError` respectively
(`test_core_write_file.py::test_write_file_conflict_with_absent_follow_up_get_raises_file_absent`,
`test_write_file_conflict_with_corrupt_metadata_on_follow_up_get_propagates`,
`test_write_file_conflict_with_non_utf8_bytes_on_follow_up_get_propagates`);
`DEFAULT_MAX_FILE_BYTES == 16384`
(`test_core_write_file.py::test_default_max_file_bytes_is_16384`); GCS
`put_if_version` passes `if_generation_match=0` for `None` and the parsed
int for a token, and rejects non-canonical tokens (`"abc"`, `"0"`, `"-1"`,
`"007"`, `""`) with no upload call
(`test_storage_gcs_errors.py::test_put_if_version_none_uploads_with_generation_zero_and_returns_token`,
`test_put_if_version_with_token_uploads_with_matching_generation`,
`test_put_if_version_with_non_canonical_token_raises_without_upload`).

## Architecture / ADR changes

- `ARCHITECTURE.md`: the bird's-eye paragraph and `core` module-map entry
  now count `write_file` as implemented alongside `read_file`. The
  `storage` entry documents `put_if_version` (the conditional put,
  `PreconditionFailedError`, token comparison in each implementation,
  GCS's canonical-token requirement). The `core` entry documents
  `max_file_bytes`/`clock` constructor options and `write_file`'s
  behavior (validation order, stamping, conflict translation). Key
  invariants gain three entries: the conditional-put/precondition-failure
  concurrency flow, the byte ceiling, and `last-updated` stamping by
  `core`.
- `docs/adr/0008-conditional-put-and-write-file-semantics.md` (new):
  records the six decisions from plan.md — `expected_version=None` means
  create-only with no default; token-against-absent-file is `FILE_ABSENT`
  not a conflict; `put_if_version`/`PreconditionFailedError` added to the
  protocol with `put` staying unconditional; unrecognized/non-canonical
  tokens are a mismatch, not a parse error (with GCS's regex-gated
  generation parsing); the byte ceiling counts content UTF-8 bytes only,
  inclusive, checked first; `core` stamps `last_updated` from an
  injectable clock. Also records, in Consequences, that T1 (storage
  protocol) and T2 (GCS implementation) landed together because widening
  `Storage` breaks `GcsStorage` under pyright strict until it implements
  `put_if_version`.
- `docs/adr/0007-core-api-shape-and-storage-layer.md`: added a short
  "Update (AIE-1033)" note at the end of Consequences pointing at ADR
  0008, since the "`put` is unconditional in this issue" consequence is
  now superseded by the addition of `put_if_version` (`put` itself is
  unchanged). Decision text left as-is, per this repo's convention of not
  rewriting an accepted ADR's Decision section after the fact.
- `docs/product/glossary.md`: no changes. The two candidate terms
  (precondition failure, byte ceiling) are either already covered
  (the `File` entry already documents the size cap) or are purely
  internal to `storage`↔`core` and never surfaced to an agent or a
  glossary-level product concept, so they don't warrant new entries.

## Deviations from spec

- Per plan.md's Complexity Tracking discussion (none listed) and the
  Constitution Check note on Storage-only-through-interface: T1 (widen the
  `Storage` protocol, `InMemoryStorage.put_if_version`) and T2
  (`GcsStorage.put_if_version`) were implemented together in one commit
  rather than strictly sequential test-then-implement, because adding a
  new abstract method to `Storage` makes `GcsStorage` fail pyright strict
  (missing protocol member) until it implements the method too — there is
  no way to land T1 alone and keep `make check` green. As a direct
  consequence, the T2 GCS-specific stub tests added to
  `tests/test_storage_gcs_errors.py` for `put_if_version` were written and
  merged alongside the implementation, so they never ran red against a
  pre-implementation `GcsStorage`.
- `tests/test_core_read_file.py`'s `_StubStorage` gained a `put_if_version`
  stub (raising `NotImplementedError`, unexercised by those tests) purely
  to keep satisfying the widened `Storage` protocol under pyright strict;
  no read_file behavior changed.
- All other interpretations (create-only `None`, `FILE_ABSENT` vs.
  conflict, unrecognized-token handling, byte-ceiling scope, clock
  stamping) were raised and resolved at the spec checkpoint on
  2026-09-28, per plan.md and review-spec.md, and are recorded in ADR
  0008 rather than being undocumented deviations.

## Look closely at

- `GcsStorage.put_if_version`'s token regex (`^[1-9][0-9]*$`) rejecting
  `"0"`, `"007"`, `"-1"`, `"abc"`, `""` before any client call — confirm
  this is the right boundary and that it can't reject a legitimate
  generation number GCS could ever produce.
- The conflict-translation path in `core.write_file`: on
  `PreconditionFailedError` it calls `storage.get` again, which re-runs
  `metadata_from_map`/UTF-8 decoding and can itself raise
  `MetadataFormatError`/`UnicodeDecodeError` — confirm this second failure
  mode (corrupt object discovered only during conflict handling) is
  acceptable versus, say, wrapping it.
- `last_updated` stamping unconditionally overwrites whatever the caller
  passed in `metadata`, including on a plain replace where the caller
  might have expected their own timestamp to be honored — confirm this
  matches the Notion spec's intent for every future write path
  (`append_line`, `replace_fact`), not just `write_file`.

## Follow-ups

- AIE-1040 (`system/` read-only enforcement) and AIE-1042 (role-gated
  scope enforcement) remain out of scope; `system/` paths are writable by
  `write_file` until those land, per spec Edge Cases.
- AIE-1044 (tool-facing wording): `sources` stamping is the tool layer's
  job, not `core`'s.
- fake-gcs-server's 412 behavior for "token given, object absent" (US7-5)
  is exercised only by the integration suite against the emulator, not by
  a unit test — noted as a risk in review-spec.md.
