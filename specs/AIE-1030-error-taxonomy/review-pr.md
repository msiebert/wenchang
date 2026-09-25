# PR Review: AIE-1030 — Error taxonomy definition

## What changed & why

Adds `wenchang.errors` and `wenchang.version_token`, the exception vocabulary every
core API function will raise, ahead of the functions themselves. Errors are grouped
into three categories by what the caller does next — recoverable (`RecoverableError`,
fix and retry this turn using data the error carries), permanent (`PermanentError`,
stop, don't retry), transient (`TransientError`, retry is appropriate) — all deriving
from a base `WenchangError`. Each category fixes its next-action guidance text once,
so wording stays consistent across concrete kinds instead of being duplicated per
error. No storage or core API functions are touched; this only defines the vocabulary
seven downstream issues depend on.

## Acceptance criteria → tests

| # | Given / When / Then | Test(s) |
| - | -------------------- | ------- |
| 1 | Any library error reports exactly one category and is catchable as `WenchangError` and as its category class only | `test_error_category_has_exactly_three_members` (tests/test_errors.py:65), `test_error_classes_subclass_wenchang_error` (tests/test_errors.py:92), `test_error_classes_are_siblings_not_related` (tests/test_errors.py:100), `test_every_taxonomy_kind_exists_and_reports_its_category` (tests/test_errors.py:492) |
| 2 | Version conflict (content C, version V) exposes C and V unchanged | `test_version_conflict_error_exposes_content_and_version_unchanged` (tests/test_errors.py:170) |
| 3 | Oversize write (size S, limit L) exposes S and L | `test_oversize_write_error_exposes_size_and_limit` (tests/test_errors.py:181), `test_oversize_write_error_rejects_negative_size_or_limit` (tests/test_errors.py:193) |
| 4 | Replace-fact match failure, count 0 or ≥2, exposes content/version/count; message says widen (0) or narrow (≥2) | `test_replace_fact_match_error_exposes_content_and_version_unchanged` (tests/test_errors.py:201), `test_replace_fact_match_error_zero_matches_tells_caller_to_widen` (tests/test_errors.py:213), `test_replace_fact_match_error_multiple_matches_tells_caller_to_narrow` (tests/test_errors.py:223), `test_replace_fact_match_error_rejects_negative_or_one` (tests/test_errors.py:235) |
| 5 | Not found: invalid path vs. file absent — exposes path + reason; message says correct the path vs. create the file | `test_not_found_reason_has_exactly_two_members` (tests/test_errors.py:242), `test_not_found_error_invalid_path_tells_caller_to_correct_path` (tests/test_errors.py:249), `test_not_found_error_file_absent_tells_caller_it_may_create` (tests/test_errors.py:260) |
| 6 | Any recoverable error message: routine framing, retry same turn, no "fail" wording | `test_recoverable_guidance_wording` (tests/test_errors.py:119), `test_recoverable_error_message_avoids_fail_wording` (tests/test_errors.py:276), `test_recoverable_kinds_are_recoverable_not_other_categories` (tests/test_errors.py:156) |
| 7 | Any permanent error message says "do not retry"; restricted-scope names scope + reason (`system/` read-only or missing role) | `test_permanent_guidance_wording` (tests/test_errors.py:127), `test_permanent_error_message_says_do_not_retry_and_ends_with_guidance` (tests/test_errors.py:320), `test_restricted_scope_error_system_read_only_names_scope_and_reason` (tests/test_errors.py:359), `test_restricted_scope_error_role_required_names_scope_and_role` (tests/test_errors.py:371), `test_permanent_kinds_are_permanent_not_other_categories` (tests/test_errors.py:302) |
| 8 | Resolver failure message: memory unavailable this session, continue without memory | `test_resolver_failure_error_default_message_mentions_unavailable_and_no_memory` (tests/test_errors.py:394), `test_resolver_failure_error_detail_appears_in_message` (tests/test_errors.py:404) |
| 9 | Transient error (timeout / unavailable) message: retry is appropriate; guarded calls safe; retried `append_line` may duplicate a line | `test_transient_guidance_wording` (tests/test_errors.py:133), `test_backend_unavailable_error_message_states_retry_guidance` (tests/test_errors.py:439), `test_backend_unavailable_error_exposes_reason_and_names_it_in_message` (tests/test_errors.py:471), `test_backend_unavailable_error_is_transient_not_other_categories` (tests/test_errors.py:423) |

## Architecture / ADR changes

- `ARCHITECTURE.md`: module map now lists `errors` and `version_token` as implemented
  cross-cutting modules (with the concrete kind list per category), and the
  "Cross-cutting: error taxonomy" section is rewritten to name the actual classes
  instead of describing the taxonomy abstractly.
- `docs/product/glossary.md`: adds Recoverable/Permanent/Transient error entries.
- `docs/adr/0005-error-taxonomy-as-exceptions.md` (new): records the exceptions-not-
  results decision, fixed-per-category guidance text, `ReplaceFactMatchError`
  carrying the version token beyond the Notion text, `VersionConflictError` omitting
  metadata (deferred to AIE-1031), the `NotFoundReason` split, `VersionToken` living
  in its own module, and deferring transport error serialization to AIE-1045/1048.

## Deviations from spec

- See ADR 0005: `ReplaceFactMatchError` carries the version token (Notion text lists
  only content + count) and `NotFoundError`'s two-reason split resolves an ambiguity
  in "no such path," confirmed with the human at the spec checkpoint. Both are
  additive, not spec-contradicting.

## Look closely at

- `PermanentError` guidance wording was corrected mid-task: an earlier draft implied
  the caller could reformulate and retry, which contradicts "stop, do not retry."
  Confirm the current wording in `test_permanent_guidance_wording` and
  `test_permanent_error_message_says_do_not_retry_and_ends_with_guidance` reads as
  unambiguous stop-not-retry, with no retry-adjacent phrasing left over.
- `tests/test_errors.py` is fully pyright-strict; earlier temporary suppressions
  were removed rather than left in. Worth a spot-check that no `# type: ignore` or
  loosened annotations remain.

## Follow-ups

- AIE-1031: add file metadata to `VersionConflictError` once the metadata type exists.
- AIE-1045/1048: transport-layer error serialization (Section 10.2 error parity),
  explicitly out of scope here.
- The core API issues (read_file, write_file, replace_fact, append_line, list_prefix,
  delete_file) now unblocked to raise these error kinds.

`make check` is green: lint, format, pyright strict, and 71 tests pass (0 skipped).
