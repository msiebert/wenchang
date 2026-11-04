# PR Review: AIE-1320 — Add a separator between error detail and guidance

## What changed & why

`WenchangError.message` used to join detail and guidance with a bare space, so an unpunctuated detail ran on into the guidance (`old_string must not be empty This is normal coordination ...`). The message now ends the detail as a sentence (trailing whitespace stripped, `.` appended unless it ends in `.`, `!`, `?`, or `...`), then a space, then the guidance; a blank detail yields the guidance alone. `InvalidArgumentError`, `ResolverFailureError`, and `BackendUnavailableError` use the same helper for their composed text. `.detail` stays unterminated.

## Acceptance criteria → tests

Files: `E` = tests/test_errors.py, `IA` = tests/test_errors_invalid_argument.py, `T` = tests/test_tools.py, `I` = tests/test_identity.py.

| Acceptance criterion | Test(s) |
| -------------------- | ------- |
| 1.1 each category: `detail. guidance` | `E::test_message_terminates_detail_for_each_category`, `E::test_error_message_format` |
| 1.2 `.`/`!`/`?` kept, no doubling | `E::test_message_keeps_terminal_punctuation` |
| 1.3 trailing whitespace stripped, one space | `E::test_message_strips_trailing_whitespace` |
| 1.4 blank detail gives guidance alone | `E::test_message_blank_detail_is_guidance_alone` |
| 1.5 `.detail` not terminated | `E::test_detail_attribute_is_not_terminated` |
| 1.6 other punctuation gets `.` | `E::test_message_terminates_other_punctuation` |
| 1.7 `...` not extended | `E::test_message_ellipsis_counts_as_terminated` |
| 1.8 raw last character (`(see x.)`) | `E::test_message_uses_raw_last_character` |
| 1.9 trailing newline stripped, interior kept | `E::test_message_strips_trailing_newline_keeps_interior` |
| 1.10 hostile `str` subclass | `E::test_message_ignores_str_subclass_method_overrides` |
| 2.1 `InvalidArgumentError` detail terminated | `IA::test_invalid_argument_error_detail_is_ended_as_sentence` |
| 2.2 already-terminated unknown-scope unchanged | `IA::test_invalid_argument_error_already_terminated_detail_unchanged` |
| 2.3 tool-layer `old_string` rejection | `T::test_empty_old_string_message_separates_detail_from_guidance` |
| 2.4 blank detail drops the colon | `IA::test_invalid_argument_error_blank_detail_omits_colon` |
| 3.1 `ResolverFailureError("token expired")` | `E::test_resolver_failure_error_terminates_caller_detail` |
| 3.2 `resolve_identity` with `ResolutionFailure` | `I::test_resolution_failure_message_separates_detail_from_following_text` |
| 3.3 no detail / terminated detail unchanged | `E::test_resolver_failure_error_unchanged_cases` |
| 3.4 whitespace-only equals no detail | `E::test_resolver_failure_error_blank_detail_matches_no_detail` |
| 3.5 hostile `str` subclass | `E::test_resolver_failure_error_ignores_str_subclass_method_overrides` |
| 3.6 `.detail` starts with terminated prefix | `E::test_resolver_failure_error_detail_attribute_includes_terminated_prefix` |
| 4.1, 4.2 timeout / unavailable reasons | `E::test_backend_unavailable_error_terminates_caller_detail` |
| 4.3 blank detail, no leading space | `E::test_backend_unavailable_error_blank_detail_has_no_prefix` |
| 4.4 no doubled period | `E::test_backend_unavailable_error_terminated_detail_not_doubled` |
| 4.5 multi-line detail | `E::test_backend_unavailable_error_multiline_detail` |
| 5.1 exact-literal tests pass unmodified | existing `test_file_quota_exceeded_error_message_is_exact_literal` etc. (unchanged) |
| 6.1-6.4 docs | ARCHITECTURE.md, ADR 0005, `site-src/reference.md`, CHANGELOG (no tests) |
| Added beyond spec: non-str detail rejected | `E::test_non_str_detail_raises_type_error`, `IA::test_invalid_argument_error_rejects_non_str_detail`, `IA::test_invalid_argument_error_str_subclass_detail_uses_real_value` |

## Architecture / ADR changes

- `docs/adr/0005-error-taxonomy-as-exceptions.md`: added decision for the sentence-ending rule and the `TypeError` on a non-str detail.
- `ARCHITECTURE.md` `errors` entry: describes the message composition, the matching rule for the optional `ResolverFailureError` / `BackendUnavailableError` detail, and the blank `InvalidArgumentError` form.
- CHANGELOG `[Unreleased]` `Fixed` entry; `site-src/reference.md` format sentence updated. `site/` regenerated with `scripts/build_site.py` (only `reference.md`/`.html` and `llms-full.txt` changed).

## Deviations from spec

- Behavior change: a non-str detail now raises `TypeError` at construction (documented in ADR 0005).
- Out-of-plan change: `resolve_identity` (`identity.py`) formats the `ResolutionFailure` detail inside its `try`, keeping the ADR 0014 fallback for a detail whose `__format__` raises (covered by `test_failure_detail_with_raising_format_becomes_resolver_failure_error`).
- Kept AIE-1242's trailing period in `tools.py`; removing it would change the observable `.detail`.

## Look closely at

- The termination helper in `src/wenchang/errors.py`: raw last-character rule, `...` handling, and `str.__str__`-style normalization so a subclass cannot spoof the message.
- `InvalidArgumentError` normalizing `detail` with `str.__str__` (a subclass's `__format__` cannot change the message).
- The `identity.py` try-block move.
- Adversarial review: spec round 1 found a second existing test asserting the run-on form (added to Allow-test-changes), a blank detail rendering `invalid:.` (fixed by dropping the colon), no `str`-subclass hardening, and an under-specified termination rule; round 2 passed. Code review (spec-fidelity and correctness) passed with no blocking findings; applied follow-ups were the non-str `TypeError` test and the `str.__str__` normalization.
- `make check`: 5883 passed, 18 skipped.

## Follow-ups

- AIE-1322 adds a conformance case asserting a rendered `FileQuotaExceededError`; its detail already ends in a period, so its rendering is unchanged.
