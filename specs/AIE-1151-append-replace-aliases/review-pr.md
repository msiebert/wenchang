# PR Review: AIE-1151 — Optional aliases and description on append_line and replace_fact

## What changed & why

Notion §8.1 asks every write to add the names a subject will later be
looked up by, and asks agents to add or change one fact with `append_line` /
`replace_fact` rather than rewrite the file. Before this change only
`write_file` could touch `aliases` and `description`, and it replaces both,
so an agent appending a fact that mentions a new nickname had to do a full
rewrite to record it. On 2026-10-05 you chose an API change over prompt-only
guidance or relaxing alias upkeep.

`append_line` and `replace_fact` now take optional `aliases` and
`description` at every layer: core `MemoryStore`, `TransportClient` /
`InProcessClient`, and the tools.

- `aliases` is a **union**: the stored aliases first, exactly as stored, then
  each given alias not already present, in given order. Exact string
  equality, no normalization. These calls never remove an alias; that stays
  `write_file`'s job.
- `description`, when not `None`, replaces the stored one.
- `None` (the default) leaves the field unchanged.
- The metadata goes into the **same conditional put** as the content, so
  one lock and one token per file (§5) holds and there is still no
  metadata-only operation.
- Core raises `TypeError` / `ValueError` for bad values before any storage
  call. The tools raise `InvalidArgumentError` through the same `_aliases` /
  new shared `_description` helpers `write_file` uses, after `check_write`.
- `wenchang.testing.TransportConformance` gains six cases plus
  `MSG_DESCRIPTION_NEWLINE`.

Files: `src/wenchang/core.py`, `transport.py`, `tools.py`,
`testing/transport_conformance.py`; tests listed below; ADR 0024,
`ARCHITECTURE.md`, glossary.

**Test doubles.** The `TransportClient` protocol change means every test
double that implements it (in `test_transport_protocol.py`,
`test_tools.py`, `test_tools_descriptions.py`, `test_tools_end_to_end.py`,
`test_transport_conformance_self.py`,
`test_transport_conformance_cases_self.py`) gained the two parameters and
forwards them. The only removed test lines are those old signatures, imports,
and module docstrings. No assertion was deleted or loosened.

**Forwarding table.** The `_CALLS` table in `tests/test_transport_inprocess.py`
(L110) now passes `aliases` and `description` explicitly in the
`append_line` / `replace_fact` rows. That keeps the exact-equality assertion
`store.calls == [(name, args, kwargs)]` in
`test_value_methods_forward_unchanged` (L202) as strict as before; this is
not a weakening. Keyword identity (`is`) and explicit-`None` forwarding are
separate new tests (L294, L324).

## Acceptance criteria → tests

Abbreviations: `ca` = `tests/test_core_append_line.py`, `cr` =
`tests/test_core_replace_fact.py`, `t` = `tests/test_tools.py`, `d` =
`tests/test_tools_descriptions.py`, `e2e` = `tests/test_tools_end_to_end.py`,
`ip` = `tests/test_transport_inprocess.py`, `tp` =
`tests/test_transport_protocol.py`, `cs` =
`tests/test_transport_conformance_cases_self.py`, `ref` =
`tests/test_transport_conformance_reference.py`, `msg` =
`tests/test_transport_conformance_messages.py`, `tc` =
`src/wenchang/testing/transport_conformance.py`. Line numbers are as of
`b68a7b3`. New test docstrings cite "AIE-1151, USx.y".

`make check` at the PR head: lint and typecheck clean; **3038 passed, 6
skipped** (the existing resolver-conformance skips), 41 deselected
(integration).

### US1 — core `append_line`

| # | Test(s) |
| - | ------- |
| 1.1 | `ca::test_append_line_unions_aliases_in_order_dropping_duplicates` (L801); empty alias accepted in `::test_append_line_accepts_empty_alias_and_empty_description` (L916) |
| 1.2 | `ca::test_append_line_description_replaces_stored_and_leaves_aliases` (L819); empty description in L916 |
| 1.3 | `ca::test_append_line_aliases_and_description_commit_in_one_put` (L835) |
| 1.4 | `ca::test_append_line_absent_arguments_leave_metadata_unchanged` (L868) |
| 1.5 | `ca::test_append_line_aliases_all_present_leaves_aliases_unchanged` (L889) |
| 1.6 | `ca::test_append_line_normalizes_str_subclass_alias_with_exact_comparison` (L901) |
| 1.7 | `ca::test_append_line_bad_aliases_container_raises_type_error_without_storage` (L942) |
| 1.8 | `ca::test_append_line_non_str_alias_entry_raises_type_error_without_storage` (L963) |
| 1.9 | `ca::test_append_line_non_str_description_raises_type_error_without_storage` (L981) |
| 1.10 | `ca::test_append_line_multiline_description_raises_value_error_without_storage` (L996) |
| 1.11 | `ca::test_append_line_normalizes_str_subclass_description` (L1012) |
| 1.12 | `ca::test_append_line_invalid_path_wins_over_bad_aliases` (L1028), `::test_append_line_existing_value_error_wins_over_bad_aliases` (L1052), `::test_append_line_new_argument_errors_in_order` (L1092) |
| 1.13 | `ca::test_append_line_landed_retry_with_new_metadata_returns_success` (L1114) |
| 1.14 | `ca::test_append_line_same_bytes_different_metadata_map_conflicts` (L1171) |
| 1.15 | `ca::test_append_line_keeps_stored_duplicate_aliases_as_stored` (L1189) |

### US2 — core `replace_fact`

| # | Test(s) |
| - | ------- |
| 2.1 | `cr::test_replace_fact_unions_aliases_and_replaces_description_in_one_put` (L962), `::test_replace_fact_normalizes_str_subclass_alias_and_description` (L985) |
| 2.2 | `cr::test_replace_fact_absent_arguments_leave_metadata_unchanged` (L1012) |
| 2.3 | `cr::test_replace_fact_stale_reapply_unions_onto_current_aliases` (L1032) |
| 2.4 | `cr::test_replace_fact_union_uses_the_committing_attempts_read` (L1052) |
| 2.5 | `cr::test_replace_fact_bad_aliases_or_description_raise_without_storage` (L1109) |
| 2.6 | `cr::test_replace_fact_invalid_path_wins_over_bad_aliases` (L1135), `::test_replace_fact_existing_value_error_wins_over_bad_aliases` (L1160), `::test_replace_fact_new_argument_errors_in_order` (L1193) |
| 2.7 | `cr::test_replace_fact_match_error_leaves_content_and_metadata_unchanged` (L1215), `::test_replace_fact_version_conflict_leaves_content_and_metadata_unchanged` (L1231) |
| 2.8 (pending human) | `cr::test_replace_fact_stale_reapply_overwrites_concurrent_description` (L1248) |
| 2.9 (pending human) | `cr::test_replace_fact_old_equals_new_with_aliases_changes_only_metadata` (L1262) |

### US3 — transport

| # | Test(s) |
| - | ------- |
| 3.1 | `tp::test_method_signature_matches_memory_store` (L171) and `ip::test_client_signature_matches_protocol` (L417), existing and unchanged |
| 3.2 | `ip::test_alias_and_description_keywords_forward_by_identity` (L294) |
| 3.3 | `ip::test_omitted_alias_and_description_forward_as_none` (L324) |
| 3.4 | L294 and L324, both parametrized over `append_line` and `replace_fact` |
| 3.5 | `ip::test_exceptions_propagate_unchanged` (L261), existing; its `_CALLS` rows now include the new keywords |
| 3.6 | `tp` L206 `test_class_docstring_lists_description_line_break_value_error`; docstring at `src/wenchang/transport.py` L37-38 |

### US4 — tools

| # | Test(s) |
| - | ------- |
| 4.1 | `t::test_fact_tool_forwards_aliases_tuple_and_description_as_keywords` (L1507), `::test_fact_tool_accepts_aliases_and_description_positionally` (L1529), `::test_fact_tool_forwards_empty_aliases_as_empty_tuple` (L1562) |
| 4.2 | `t::test_fact_tool_forwards_none_when_metadata_not_given` (L1546) |
| 4.3 | L1507, L1529, L1546, each parametrized over both tools |
| 4.4 | `t::test_fact_tool_malformed_aliases_match_write_file` (L1575), `::test_fact_tool_wrong_type_aliases_detail` (L1601) |
| 4.5 | `t::test_fact_tool_unencodable_alias_is_chained` (L1617); also L1575 |
| 4.6 | `t::test_fact_tool_wrong_type_description` (L1631) |
| 4.7 | `t::test_fact_tool_description_with_newline` (L1648) |
| 4.8 | `t::test_fact_tool_description_with_line_boundary` (L1665) |
| 4.9 | `t::test_fact_tool_unencodable_description_is_chained` (L1682) |
| 4.10 | `t::test_fact_tool_str_subclass_metadata_is_forwarded_as_exact_str` (L1698) |
| 4.11 | `t::test_fact_tool_check_write_precedes_metadata_checks` (L1722) |
| 4.12 | `t::test_earlier_argument_error_precedes_metadata_errors` (L1750), `::test_aliases_error_precedes_description_error` (L1762) |
| 4.13 | Existing `write_file` tests in `t`, unchanged and passing; L1575 compares the fact tools' alias errors to `write_file`'s |
| 4.14 | `t::test_fact_tool_signature_has_optional_aliases_and_description` (L1496), plus L1529 |
| 4.15 | `e2e::test_append_line_unions_aliases_and_replaces_description_end_to_end` (L197) |

### US5 — tool descriptions

| # | Test(s) |
| - | ------- |
| 5.1 | `d::test_fact_docstring_explains_aliases_and_description` (L240) |
| 5.2 | Existing: `d::test_tools_module_cites_no_linear_ids` (L288), `tp::test_library_cites_no_linear_ids` (L274), `ip::test_library_cites_no_linear_ids` (L479), `tests/test_testing_package.py::test_testing_package_cites_no_linear_ids` (L218) and `::test_transport_conformance_cites_no_linear_ids` (L439) |

### US6 — conformance suite

Each case runs for `InProcessClient` through
`ref::TestInProcessClient` (L122), and against the reference and forwarding
clients in `cs::test_reference_client_passes_aliases_description_case`
(L1552).

| # | Case (in `tc`) | Broken-client test(s) |
| - | -------------- | ---------------------- |
| 6.1 | `test_append_unions_aliases` (L2506) | `cs::test_aliases_replaced_instead_of_unioned_fails` (L1620) |
| 6.2 | `test_append_replaces_description` (L2533) | `cs::test_description_ignored_fails` (L1662), `::test_description_changing_aliases_fails` (L1690) |
| 6.3 | `test_replace_fact_unions_aliases_and_replaces_description` (L2558) | L1620, L1662 |
| 6.4 | `test_omitted_aliases_and_description_leave_metadata_unchanged` (L2592) | `cs::test_omitted_arguments_changing_metadata_fails` (L1747) |
| 6.5 | `test_replace_fact_reapply_unions_onto_current_aliases` (L2635) | `cs::test_reapply_unioning_onto_stale_aliases_fails` (L1829) |
| 6.6 | `test_alias_and_description_argument_errors_match_core` (L2665) | `cs::test_alias_and_description_argument_error_drift_fails` (L1976) |
| 6.7 | — | `ref::test_suite_public_methods_are_exactly_the_listed_cases` (L175), `ALIASES_DESCRIPTION_CASES` |
| 6.8 | `MSG_DESCRIPTION_NEWLINE` (L103) | `msg::test_append_line_description_newline_message_matches` (L148), `::test_replace_fact_description_newline_message_matches` (L162) |

### US7 — docs (no tests)

| # | Where |
| - | ----- |
| 7.1 | `docs/adr/0024-append-replace-aliases-description.md` |
| 7.2 | `ARCHITECTURE.md`: **core**, **transport**, **tools**, and **testing** module-map entries, and the "One lock, one token per file" key invariant |
| 7.3 | `docs/product/glossary.md`, **Aliases** (L156) |

All 58 criteria are mapped. No test exists for 7.1, 7.2, or 7.3
(docs). 3.1, 3.5, 4.13, and 5.2 rely on existing tests, which pass
unchanged.

## Architecture / ADR changes

- New [ADR 0024](../../docs/adr/0024-append-replace-aliases-description.md):
  signatures at all three layers, union semantics, commit in one put, core
  versus tool validation, the `write_file` precedence shift, error-parity
  scope, the six conformance cases, the Notion §5 deviation, rejected
  alternatives, and the two pending-human defaults.
- `ARCHITECTURE.md`: the core, transport, tools, and testing entries plus the
  one-lock, one-token invariant describe the new arguments.
- `docs/product/glossary.md`, **Aliases**: `append_line` / `replace_fact` add
  aliases; only `write_file` removes them.

## Deviations from spec

- **Notion §5 signatures** list `append_line(path, line, expected_version)`
  and `replace_fact(path, old_string, new_string, expected_version)` with no
  metadata arguments. The extension is deliberate (ADR 0024 decision 10): it
  is the only way to satisfy §8.1's alias upkeep and write mechanics together
  without a metadata-only operation, which §5 forbids. Calls that omit the
  new arguments behave exactly as before.
- None from spec.md / plan.md.

## Design decisions

- **Union, not replace.** If the call replaced aliases, a fact write would
  have to resend every alias and would silently drop any it forgot.
- **Union computed on the committing attempt's read.** Concurrent alias
  additions survive a stale-token `replace_fact` re-apply or a
  precondition-failure retry (US2.3, US2.4).
- **Error parity scope.** Only the newline `ValueError` joins the
  `TransportClient` well-typed parity list. Wrongly typed arguments are
  checked by type only in conformance (ADR 0019 decision 7, ADR 0023
  decision 8).
- **`write_file` check precedence.** `write_file` now uses the shared
  `_description` helper at its existing position (after `content`, before
  `aliases`). That helper includes the `\n` / `\r` check that used to run
  later, at `FileMetadata` construction. So a description with a newline is
  now reported before a bad `aliases` or `expected_version`. No existing
  test pinned that combination; ADR 0024 decision 7 records it.

## Orchestrator defaults pending human

- **US2.8:** a stale-token `replace_fact` that re-applies (match still
  unique) with a `description` overwrites a description another writer
  committed since the caller's read. Last writer wins, as it already does for
  content outside the quoted span. Aliases are unioned, so none are lost.
  Alternative: raise `VersionConflictError` on a stale token whenever
  `description` is given.
- **US2.9:** `replace_fact(p, s, s, v, aliases=...)` (`old_string ==
  new_string`) changes only metadata. It still goes through the same
  content-write path, the same conditional put, and the same token, so §5's
  one lock, one token holds and the API gains no metadata-only operation.
  Alternative: reject `old_string == new_string`, which would be a new
  public-API rule.

## Adversarial review findings

Spec review: two rounds (see review-spec.md). Round 1 caught a transport
docstring that would have widened error parity to wrongly typed arguments
(contradicting ADR 0019 decision 7), phrase pins fragile to line wrapping,
and two unstated behaviors now recorded as orchestrator defaults (US2.8,
US2.9).

Build: the implementer flagged one T1 test that asserted zero plain `put`
calls although `InMemoryStorage.put_if_version` calls `put` internally; the
test-writer fixed the counter to count only direct `put` calls, keeping the
one-conditional-write assertion.

Code review, round 1: reviewer A (correctness) PASS with 3 NITs: an
iterator that raises inside an aliases `Sequence` escapes unchanged (same as
`write_file`; left as is); an extra "wrong content" phrase in one
conformance case (harmless); the quadratic dedup scan (irrelevant at alias
sizes). Reviewer B (coverage/docs) PASS with 4 NITs, all fixed: the
replace_fact argument-order test gained description-type/value cases and an
exact-type assert; a test now pins the documented `write_file` precedence
(newline description before bad aliases/expected_version); this file's
test-double list wrongly named `test_transport_conformance_messages.py`; an
ADR 0024 sentence overstated what the argument-errors case checks.

## Look closely at

- `MemoryStore.append_line`'s landed-retry check (US1.13 / US1.14) now
  compares a metadata map that includes the new aliases and description. A
  retry that landed with different metadata is a conflict, not a success.
- `replace_fact` retries: the union and description are recomputed from each
  attempt's read, not the caller's (US2.4).
- Every adopter `TransportClient` must accept the two new keyword parameters
  and union exactly as core does to pass the six new conformance cases.

## Follow-ups

- Confirm or change the US2.8 and US2.9 defaults.
- Prompt text (AIE-1049, AIE-1051) can now require alias upkeep on fact
  writes.

## Final tool docstrings

`MemoryTools.append_line`:

```text
Add one fact line to the end of an existing memory file.

`scope` is one of the scopes available in this session, `area` is the
folder inside it, and `name` is the file name without `.md`. `line`
must be a single fact line with a leading bracketed label, one of
`[stated]`, `[observed]`, `[inferred]`, or `[system]`, for example
`- [stated] Prefers tea`. Pass the version you read as
`expected_version`. The per-file byte ceiling applies to the result.
The `system/` area is read-only. Areas are lowercase ASCII slugs.

Optional `aliases` are added to the file's existing aliases and
never removed; to drop an alias, use `write_file`, which replaces
the whole set. An optional one-line `description` replaces the
stored one.

A version conflict is routine: someone else changed the file since
you read it. The error carries the current content and version;
merge your change into it and retry with that version.
```

`MemoryTools.replace_fact`:

```text
Change one fact in a memory file by quoting the text to replace.

`scope` is one of the scopes available in this session, `area` is the
folder inside it, and `name` is the file name without `.md`.
`old_string` must match the file's content exactly once; if it matches
zero or several times, the error carries the current content and
version so you can quote a longer, unique span. `new_string` replaces
it. Pass the version you read as `expected_version`. The per-file
byte ceiling applies to the result. The `system/` area is read-only.
Areas are lowercase ASCII slugs.

Optional `aliases` are added to the file's existing aliases and
never removed; to drop an alias, use `write_file`, which replaces
the whole set. An optional one-line `description` replaces the
stored one.

A version conflict is routine: someone else changed the file since
you read it. The error carries the current content and version;
merge your change into it and retry with that version.
```

Final gate (spec-reviewer): PASS with one SHOULD-FIX, now fixed (US3.6 had
no test; `tests/test_transport_protocol.py` now pins the docstring phrase),
and two NITs: spec status updated to Implemented; ADR 0024 decision 11 stays
pending human confirmation at this PR.

