# PR Review: AIE-1042 — write-restriction enforcement for role-gated scopes

## What changed & why

Adopters can now mark scopes write-restricted (Notion Section 3; Section 9's
"org writes limited to admin or owner"). `ScopePolicy` maps each restricted
scope to its permitted roles. `check_write(path, identity, policy)` is the
single pure check the tool layer will call before every mutating call:
`system/`, then grant/entity, then role. The security point is the
grant/entity check. A role check alone would let a caller with a permitted
role in `org` write into any other org's prefix just by naming it. The new
permanent `NOT_GRANTED` closes that gap, and it is checked before the role.
`RestrictedScopeError` now carries `required_roles: frozenset[str] | None`
so it can say "admin, owner". Reads, listing, and `MemoryStore` are
unchanged.

## Acceptance criteria → tests

`tests/test_scope_write_restriction.py` unless marked `errors:` (`tests/test_errors.py`).

| Acceptance criterion (Given/When/Then) | Test(s) |
| --------------------------------------- | ------- |
| US1.1 policy reports restricted scopes / role sets; absent → `None` | `test_policy_reports_restricted_scopes_and_roles` |
| US1.2 source dict mutation doesn't leak; `write_roles[...] =` → `TypeError` | `test_policy_copies_source_dict`, `test_policy_write_roles_is_read_only` |
| US1.3 invalid scope segment → `ValueError` | `test_policy_rejects_invalid_scope_name` (11 cases) |
| US1.4 empty role set / `""` role → `ValueError` | `test_policy_rejects_empty_roles` |
| US1.5 equal + hash-equal regardless of order; `ScopePolicy({})` restricts nothing | `test_policy_equality_ignores_insertion_order`, `test_empty_policy_restricts_nothing` |
| US1.6 no scope name special-cased (`system`, `org`, `organization`) | `test_policy_treats_every_scope_name_alike` |
| US1.7 wrongly typed input → `TypeError`, fixed check order | `test_policy_rejects_wrongly_typed_input` (19 rows incl. 8 order-pinning rows) |
| US1.8 key `"Org"` etc. restricts nothing (exact match) | `test_policy_key_matches_scope_exactly` |
| US1.9 pickle / deepcopy round-trip | `test_policy_pickle_round_trip`, `test_policy_deepcopy_round_trip` |
| US2.1 `member` in `org` → permanent `ROLE_REQUIRED`, `required_roles={admin,owner}`, message names both; caller role not echoed | `test_member_denied_in_restricted_org`, `test_role_required_message_omits_caller_role` |
| US2.2 `admin` / `owner` in `org` → `None` | `test_permitted_role_allowed_in_restricted_org` |
| US2.3 unrestricted scope accepts any granted role | `test_unrestricted_scope_allows_any_granted_role` |
| US2.4 `Admin` ≠ `admin` | `test_role_match_is_exact` |
| US3.1 ungranted scope (restricted or not) → `NOT_GRANTED`, `required_roles is None` | `test_ungranted_scope_not_granted` |
| US3.2 entity mismatch in unrestricted `project` → `NOT_GRANTED` | `test_entity_mismatch_in_unrestricted_scope_not_granted` |
| US3.3 entity mismatch in restricted `org` → `NOT_GRANTED`, not `ROLE_REQUIRED` | `test_entity_mismatch_in_restricted_scope_not_granted` |
| US3.4 `NOT_GRANTED` message omits caller's entity ID and role | `test_not_granted_message_omits_caller_entity_and_role` |
| US3.5 restricted `org` with no `org` grant → `NOT_GRANTED` | `test_restricted_scope_without_grant_not_granted` |
| US3.6 `Identity({})` writes nothing | `test_empty_identity_not_granted` |
| US4.1 malformed path → `NotFoundError(INVALID_PATH)` from both checks | `test_malformed_path_invalid_path` |
| US4.2 granted `system/` → `check_write` `SYSTEM_READ_ONLY`; `check_write_allowed` `None` | `test_check_write_rejects_granted_system_area` |
| US4.3 system wins over not-granted | `test_check_write_system_wins_over_not_granted` |
| US4.4 15-row precedence table, both functions, SC-001 on every `None` row | `test_check_precedence` (30 cases), `test_precedence_table_shape` |
| US4.5 fully permitted path → `check_write` `None` | `test_check_write_allows_fully_permitted_path` |
| US5.1 role set kept, message lists `admin, owner` sorted | errors: `test_restricted_scope_error_role_required_lists_roles_sorted` |
| US5.2 `ROLE_REQUIRED` with `None`/empty → `ValueError`; non-`frozenset` → `TypeError` first | errors: `test_restricted_scope_error_role_required_rejects_missing_or_empty_roles`, `test_restricted_scope_error_rejects_non_frozenset_roles`, `test_restricted_scope_error_rejects_leftover_positional_role_string`, `test_restricted_scope_error_role_required_without_required_role_rejected` (unchanged) |
| US5.3 other reasons reject `required_roles`; default `None` | errors: `test_restricted_scope_error_other_reasons_reject_required_roles`, `test_restricted_scope_error_required_roles_defaults_to_none`, `test_restricted_scope_error_not_granted_defaults_required_roles_to_none`, `test_restricted_scope_error_not_granted_names_path_and_scope` |
| US5.4 `RestrictionReason` is exactly three members; `NOT_GRANTED == "not_granted"` | errors: `test_restriction_reason_has_exactly_three_members`, `test_restriction_reason_not_granted_value` |
| US5.5 every reason permanent, "do not retry", ends with guidance | errors: `test_restricted_scope_error_every_reason_is_permanent_and_says_do_not_retry`, `test_permanent_kinds_are_permanent_not_other_categories[restricted_scope_not_granted]`, `test_permanent_error_message_says_do_not_retry_and_ends_with_guidance[restricted_scope_not_granted]` |
| Review finding 1: a `str`-subclass path (lying `__ne__` segments, or a `split()` that changes between calls) can't bypass the entity or `system/` check; a benign subclass behaves exactly like `str`; a non-`str` path raises `TypeError` | `test_str_subclass_cannot_bypass_entity_check`, `test_str_subclass_cannot_bypass_system_check`, `test_benign_str_subclass_behaves_like_str` (30 cases over the precedence table), `test_non_str_path_raises_type_error` |
| Review finding 2: message sorts a larger role set | errors: `test_restricted_scope_error_role_required_lists_five_roles_sorted` |
| Review finding 3: an empty role set with a lying `__len__` still raises `ValueError` | `test_policy_rejects_empty_role_set_that_lies_about_len` |
| Review finding 5: `required_roles` spoofing `frozenset` via `__class__`, or holding a non-`str`, raises `TypeError` | errors: `test_restricted_scope_error_rejects_spoofed_frozenset_roles`, `test_restricted_scope_error_rejects_non_str_role` |
| FR-001 `ScopePolicy` immutable/hashable/validated/picklable, exact keys | US1.1–1.9 tests above |
| FR-002 absent scope unrestricted | `test_unrestricted_scope_allows_any_granted_role`, `test_empty_policy_restricts_nothing` |
| FR-003 not granted (scope or entity) | US3.1–3.6 tests above |
| FR-004 `ROLE_REQUIRED` with `required_roles` | `test_member_denied_in_restricted_org`, `test_role_match_is_exact` |
| FR-005 `check_write` order | `test_check_precedence`, `test_check_write_system_wins_over_not_granted` |
| FR-006 malformed path → `INVALID_PATH` | `test_malformed_path_invalid_path` |
| FR-007 no scope name special-cased | `test_policy_treats_every_scope_name_alike` |
| FR-008 `required_roles` type/value rules, `NOT_GRANTED` member | US5 tests above |
| FR-009 `MemoryStore` and reads unchanged | No new test (per spec): AIE-1040's `test_core_does_not_import_scope` / `test_scope_does_not_import_core_or_storage` in `tests/test_scope_system.py`, plus unchanged core tests |
| SC-001 no accepted write outside grant/entity, in `system/`, or without a permitted role | `_assert_sc001` in `test_check_precedence` and `test_check_write_allows_fully_permitted_path` |

## Architecture / ADR changes

- New [ADR 0017](../../docs/adr/0017-write-restriction-enforcement.md): eleven decisions, including decision 11 "Adversarial hardening" (matching plan.md's numbering), four of them approved at spec review on 2026-09-30.
- `ARCHITECTURE.md`:
  - Bird's-eye paragraph: `scope` now does both write checks.
  - **errors** entry: `RestrictedScopeError` signature, construction rules, three reasons.
  - **scope** entry: `ScopePolicy`, `check_write_allowed`, and `check_write`. It now imports `identity`. The "planned" wording is gone.
  - Note under the diagram: `scope` uses the `Identity` type and no resolver. The diagram itself is unchanged.
  - Two new Key invariants: a write is checked against the caller's own grant, and the check order is fixed.
  - Error-taxonomy Permanent bullet: all three reasons.
- `docs/product/glossary.md`: new "write-restricted scope", "scope policy", and "not granted" entries. "Role" and "system area" are updated.

## Deviations from spec

- None from Notion. The not-granted check goes further than the Linear issue text, which only mentions roles. It follows from Section 6 and is recorded in ADR 0017, decisions 3 and 4.
- Breaking public-API rename: `RestrictedScopeError.required_role` becomes `required_roles`, with no alias (ADR 0017, decision 2). There are no external callers.
- `ScopePolicy` also rejects a scope that is duplicated after `str` normalization (`ValueError`, checked after an entry's role checks). This check isn't in plan.md's table. It mirrors `Identity`'s collision check and is recorded in ADR 0017, decision 9.
- The spec authorized changes to existing tests in `tests/test_errors.py`. This is the full list:
  1. The `ROLE_REQUIRED` factory in `PERMANENT_ERROR_FACTORIES` uses `required_roles=frozenset({"admin"})`. A `NOT_GRANTED` factory is inserted after it.
  2. Both `ids=[...]` lists gain `"restricted_scope_not_granted"`.
  3. `test_restriction_reason_has_exactly_two_members` is renamed `..._three_members` and expects `not_granted` and length 3.
  4. `test_restricted_scope_error_exposes_attributes_unchanged` uses and asserts `required_roles`.
  5. `test_restricted_scope_error_required_role_defaults_to_none` is renamed `..._required_roles_defaults_to_none`.
  6. `test_restricted_scope_error_role_required_names_scope_and_role` passes `required_roles`. Its assertions are unchanged.
  7. Changed docstrings cite AIE-1030 and AIE-1042.

  Every other change in that file adds a new test (US5 or a review finding). No test is deleted, skipped, or loosened.

  One more existing test changes. In `tests/test_scope_system.py`, `test_check_not_system_rejects_primary_path` has one assertion rewritten, `getattr(err, "required_role", None) is None` becoming `err.required_roles is None`, because the rename means the old attribute no longer exists. Its docstring now also cites AIE-1042. Nothing else in that file changes.
- Adversarial hardening (ADR 0017, decision 11, plan.md decision 11) came after spec review. It adds `TypeError` for a non-`str` path, exact-`str` normalization at entry, real-type container checks, and `TypeError` for non-`str` `required_roles` members. It narrows accepted input and changes no outcome for a plain `str` (see `test_benign_str_subclass_behaves_like_str`).

## Look closely at

- **The US4.4 precedence table** (`PRECEDENCE_TABLE`, 15 rows, run against both functions = 30 cases). Check it against spec US4.4 row by row. Pay most attention to the rows where the two functions disagree: rows 5–8 (`system/` paths) and the multi-condition invalid rows 1–2 (`.txt` in `system/`).
- **The SC-001 property** (`_assert_sc001`). Every accepted row must have the scope granted, the entity equal to the grant's entity, and the role permitted or the scope unrestricted. For `check_write` it must also not be `system/`. This is the security guarantee, so check that the assertion can't pass vacuously.
- **NOT_GRANTED no-leak assertions**: `test_not_granted_message_omits_caller_entity_and_role` uses the distinctive values `own-entity-7f3` and `role-zq9`, and `test_role_required_message_omits_caller_role` does the same for the caller's role. Also confirm the `NOT_GRANTED` detail in `errors.py` interpolates only `path` and `scope`.
- **The `tests/test_errors.py` diff** (`git diff AIE-1040-system-read-only -- tests/test_errors.py`). Every changed existing line should map to one of the seven items above, and everything else should be new tests.
- **Check versus use, for AIE-1044.** `check_write` validates the exact `str` it made at entry, not the caller's object. The tool layer must pass storage that same exact `str`, for example by normalizing once with `str.__str__` before both the check and the `MemoryStore` call. Passing the original subclass or a re-derived value to storage would reopen the review-finding-1 bypass. Nothing in this PR can enforce that, so AIE-1044's review should confirm it.
- **`check_write_allowed` skips `system/` on purpose.** Its docstring says tool code must call `check_write`, and AIE-1044 must keep to that.

## Follow-ups

- AIE-1044: call `check_write` before `write_file`, `append_line`, `replace_fact`, and `delete_file` in the tool layer, pass storage the same exact `str` the check saw, and test that no mutating tool skips it. Nothing is enforced until then.
- AIE-1039: the resolver conformance suite imports `ScopePolicy`, `check_write`, and `RestrictionReason.NOT_GRANTED`. It runs `check_write` against a resolved identity and the adopter's policy to check that own-entity writes follow the policy and that `system/` writes are rejected. Any change to `check_write`'s outcomes or `required_roles` affects that suite.
