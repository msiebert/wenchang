# PR Review: AIE-1032 — read_file and the storage layer

## What changed & why

Adds the first core API function, `read_file(path) -> MemoryFile`, plus the
internal storage layer it reads through — no storage issue existed yet, and
`read_file` can't be tested without one, so it's folded into this PR by the
human's earlier call. New modules: `wenchang.paths` (`is_valid_path`, a
syntactic check for `{scope}/{entity_id}/{area}/{name}.md`), `wenchang.storage`
(the `Storage` protocol, `StoredObject`, `InMemoryStorage`, and `GcsStorage`
— the only module importing `google.cloud`), and `wenchang.core`
(`MemoryStore`, `MemoryFile`). One shared conformance suite runs against both
storage implementations, in-memory as a unit test and GCS against
`fake-gcs-server` as an integration test. This PR also includes an unrelated
change to `.claude/commands/implement-issue.md` adding automated Linear
status transitions, at the user's request.

## Acceptance criteria → tests

| # | Given / When / Then | Test(s) |
| - | -------------------- | ------- |
| US1-1 | File at valid path with body B, metadata M; `read_file` returns B, M, path, version | `test_core_read_file.py::test_read_file_returns_stored_content_metadata_path_and_version` |
| US1-2 | Unicode, `\r\n`, trailing/no trailing newline, fact-like markdown, empty body round-trip exactly | `test_core_read_file.py::test_read_file_returns_stored_body_exactly` |
| US1-3 | Metadata with commas/quotes/brackets/unicode and an offset timezone round-trips exactly | `test_core_read_file.py::test_read_file_returns_metadata_with_special_characters_and_offset_timezone` |
| US1-4 | Unchanged file read twice returns equal version tokens | `test_core_read_file.py::test_read_file_returns_equal_version_tokens_for_unchanged_file` |
| US1-5 | Read, overwrite, read again: tokens differ, new content/metadata returned | `test_core_read_file.py::test_read_file_returns_different_version_and_new_content_after_overwrite` |
| US1-6 | Version token is an opaque `VersionToken` (str), no ordering exposed | `test_core_read_file.py::test_read_file_version_is_a_str` |
| US2-1 | Well-formed path, no object → `NotFoundError(FILE_ABSENT)` | `test_core_read_file.py::test_read_file_raises_not_found_file_absent_when_no_object_at_path` |
| US2-2 | Malformed path → `NotFoundError(INVALID_PATH)`, storage not called | `test_core_read_file.py::test_read_file_raises_not_found_invalid_path_without_calling_storage` |
| US2-3 | Every malformed-path shape (empty, leading/trailing `/`, empty segment, `.`/`..`, backslash/control char, wrong segment count, bad final segment) rejected | `test_paths.py::test_malformed_structure_rejected`, `test_dot_segments_rejected`, `test_backslash_and_control_chars_rejected`, `test_wrong_segment_count_rejected`, `test_bad_final_segment_rejected` |
| US2-4 | Well-formed paths (incl. unicode, spaces, mixed case) accepted | `test_paths.py::test_valid_paths_accepted` |
| US2-5 | Differently-cased path is `FILE_ABSENT`, not a match | `test_core_read_file.py::test_read_file_is_case_sensitive_on_path` |
| US3-1 | `BackendUnavailableError` from storage propagates unchanged | `test_core_read_file.py::test_read_file_propagates_backend_unavailable_error_unchanged` |
| US3-2 | GCS timeout → `TIMEOUT`; server-unavailable/internal/connection failure → `UNAVAILABLE` | `test_storage_gcs_errors.py::test_get_blob_timeout_exceptions_map_to_backend_unavailable_timeout`, `test_get_blob_unavailable_exceptions_map_to_backend_unavailable_unavailable`, `test_download_as_bytes_timeout_exceptions_map_to_backend_unavailable_timeout`, `test_download_as_bytes_unavailable_exceptions_map_to_backend_unavailable_unavailable`, `test_upload_from_string_timeout_exceptions_map_to_backend_unavailable_timeout`, `test_upload_from_string_unavailable_exceptions_map_to_backend_unavailable_unavailable`; plus `test_get_retries_once_on_precondition_failed_and_returns_second_generation`, `test_get_returns_none_when_retry_after_not_found_finds_nothing`, `test_get_raises_backend_unavailable_after_three_precondition_failures`, `test_get_passes_matching_generation_to_download_as_bytes` |
| US3-3 | Malformed stored metadata → `MetadataFormatError` naming the key | `test_core_read_file.py::test_read_file_raises_metadata_format_error_naming_missing_key`, `test_read_file_raises_metadata_format_error_naming_malformed_aliases` |
| US3-4 | Non-UTF-8 stored bytes → `ValueError`, not a `WenchangError` | `test_core_read_file.py::test_read_file_raises_value_error_not_wenchang_error_on_invalid_utf8` |
| US4-1 | Fetching a missing key returns `None`, not an error | `storage_conformance.py::test_get_of_missing_key_returns_none` (run by `test_storage_memory.py::TestInMemoryStorage`, `integration/test_storage_gcs.py::TestGcsStorage`) |
| US4-2 | Put bytes + metadata round-trip exactly, including non-ASCII/unicode | `storage_conformance.py::test_put_then_get_round_trips_bytes_and_metadata`, `test_put_then_get_round_trips_empty_bytes_and_empty_metadata` |
| US4-3 | Put returns a token; a later fetch reports the same token | `storage_conformance.py::test_put_returns_token_and_get_reports_same_token`, `test_tokens_are_compared_only_for_equality` |
| US4-4 | Two puts to one key: second token differs, fetch returns second's bytes+metadata together | `storage_conformance.py::test_second_put_to_same_key_yields_different_token_and_new_data` |
| US4-5 | Puts to different keys are independent; a key is not a prefix match | `storage_conformance.py::test_puts_to_different_keys_are_independent`, `test_key_is_not_a_prefix_match_bak_suffix`, `test_key_is_not_a_prefix_match_truncated_key` |
| US4-6 | Mutating a fetched metadata map doesn't affect a later fetch | `storage_conformance.py::test_mutating_callers_metadata_dict_after_put_does_not_affect_storage`; fake-specific: `test_storage_memory.py::test_get_returned_metadata_is_a_mutable_dict_but_mutating_it_does_not_affect_storage` |
| FR-008 | No module outside `storage/gcs.py` imports `google.cloud` | `test_storage_gcs_errors.py::test_no_module_outside_storage_gcs_imports_google_cloud` |

Also covered, not tied to a numbered scenario: `is_valid_path` never raises
(`test_paths.py::test_never_raises_on_arbitrary_input`); an unmapped GCS
exception propagates unchanged (`test_storage_gcs_errors.py::test_unmapped_exception_from_get_blob_propagates_unchanged`,
`test_unmapped_value_error_from_upload_propagates_unchanged`); `put` sets
metadata as a copy with the right content type and returns a generation token
(`test_storage_gcs_errors.py::test_put_sets_metadata_copy_content_type_and_returns_generation_token`);
a real client/emulator round trip (`integration/test_storage_gcs.py::test_put_then_get_round_trips_through_real_client_stack`);
tokens unique across keys and five successive puts
(`storage_conformance.py::test_five_successive_puts_yield_five_distinct_tokens`,
`test_storage_memory.py::test_tokens_are_unique_across_different_keys_within_one_instance`);
`system/` paths are readable, empty content is valid, extra metadata keys are
ignored, and `MemoryFile` is frozen (`test_core_read_file.py::test_read_file_reads_a_system_area_path`,
`test_read_file_allows_empty_content_with_valid_metadata`,
`test_read_file_ignores_extra_metadata_keys`, `test_memory_file_is_frozen`).

## Architecture / ADR changes

- `ARCHITECTURE.md`: the bird's-eye paragraph now counts `paths`, `storage`,
  and `core` as implemented modules. The module map adds `paths`; moves
  `storage` from *(planned)* to implemented (`Storage`/`StoredObject`,
  `InMemoryStorage`, `GcsStorage`, one conformance suite, put still
  unconditional); narrows `core` to `MemoryStore` with `read_file`
  implemented and the rest *(planned)*. Key invariants gain two entries: the
  storage root is the storage instance and paths are relative to it, and
  version-token/generation conversion happens only in `GcsStorage`.
- `docs/adr/0007-core-api-shape-and-storage-layer.md` (new): records the six
  decisions from plan.md (`MemoryStore` methods vs. free functions; `{root}`
  = the storage instance; exactly four path segments; `Storage` speaks
  `VersionToken`, only `GcsStorage` converts; corrupt objects raise
  `ValueError` subclasses; `put` unconditional here, preconditions added with
  `write_file`) plus the GCS `get` pinned-generation retry.
- `docs/product/glossary.md`: adds Memory path and Storage root.

## Deviations from spec

- ADR 0007 interpretations, all confirmed non-spec-contradicting: `MemoryStore`
  as a stateful object rather than free functions (reading "plain functions"
  as "no protocol/server awareness," not a ban on grouping); the storage root
  fixed to one storage instance for now (no key prefix); paths fixed at
  exactly four segments (no nested areas); corrupt objects raising `ValueError`
  subclasses rather than a new taxonomy error, consistent with ADR 0006.
- Per plan.md's Complexity Tracking: the storage layer (protocol, in-memory
  fake, GCS implementation, conformance suite) is folded into this single-issue
  PR rather than split out, because no separate storage issue exists and
  `read_file` is untestable without it. This is the human's earlier decision,
  recorded in plan.md and review-spec.md.

## Look closely at

- `GcsStorage.get`'s pinned-generation retry (`get_blob` → `download_as_bytes`
  with `if_generation_match`, up to 3 attempts, then
  `BackendUnavailableError(UNAVAILABLE)`) — confirm the retry count and the
  choice to surface a persistent race as `UNAVAILABLE` rather than a distinct
  error are the right tradeoff.
- The `pyright: ignore` comments scattered through `storage/gcs.py` and its
  tests, needed because the `google-cloud-storage` SDK lacks type stubs —
  confirm they're narrowly scoped to the untyped calls and don't suppress
  anything else.
- The conformance suite's import style: `tests/storage_conformance.py` is
  imported with a bare `from storage_conformance import ...` (not
  `from tests.storage_conformance import ...`), relying on `tests/conftest.py`
  adding `tests/` to `sys.path` since `tests/` has no `__init__.py` — confirm
  this is the intended pattern for future shared test bases rather than an
  accident of how pytest resolved it.

## Follow-ups

- AIE-1033 (`write_file`): adds a generation-match precondition to `put` and
  the version-conflict path that `read_file`'s callers will need.
- Nested areas: the path validator only accepts exactly one area segment;
  revisit if agents ever need sub-areas (e.g. `taxonomy/events/x.md`).
- A key prefix within a bucket, if multiple storage roots ever need to share
  one GCS bucket; not needed today (ADR 0007).
