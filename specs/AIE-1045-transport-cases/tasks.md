# Tasks: Transport conformance test cases

**Linear issue**: AIE-1045 | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

Each task runs test-writer (red tests), then implementer (case methods in
`src/wenchang/testing/transport_conformance.py`), then a green `make
check`. The red test for each task is the method-name set in
`tests/test_transport_conformance_reference.py` listing the task's cases
before they exist, plus the group's broken-client self-test. Branch is
based on `AIE-1047-transport-harness`; precondition: rebased onto its
final commit (ADR 0021 present).

## T1 — Round trip, atomicity, tokens (US1–US3)

Test-writer: add the US1–US3 method names to the method-name set; write
their broken-client self-tests in new
`tests/test_transport_conformance_cases_self.py`. Implementer: the eleven
case methods and the private helpers `_meta`, `_write`, `_read`,
`_conflict` (callable-taking, no token parameters; `_seed` already
exists).

## T2 — Conflicts, replace-fact, append (US4–US6)

Same pattern: sixteen case methods; `_ABSENT_TOKEN` (plain constant);
the message constants `MSG_REPLACE_ARGS`, `MSG_APPEND_ARGS`. Test-writer
also writes the drift test in new
`tests/test_transport_conformance_messages.py` covering every
(method, cause) pair for those two constants (empty `old_string`, empty
`source` on `replace_fact` and on `append_line`, non-fact line, two-line
line). `tests/test_testing_package.py` is unchanged.

## T3 — Enforcement, index, listing (US7, US8, US9)

Eleven case methods incl. `test_system_area_write_is_accepted_at_transport`
(human decision (a)); `INDEX_AREA`, `PROBE_STEM_3`, cursor message
constants; drift test extended for both cursor causes. Self-test: a
client that rejects the `system/` write fails `unexpected error`.

## T4 — Error parity (US10)

Five case methods (incl. US10.5
`test_get_memory_index_argument_errors_match_core`); `MSG_WRITE_ARGS`,
`MSG_INVALID_SCOPE`, `MSG_INVALID_ENTITY`; drift test extended to empty
`source` on `write_file`, invalid scope, and invalid entity_id. The
US10.5 `TypeError` cases are type only (no constants, not in the drift
test); duplicate scope is not tested (plan decision 8).

## T5 — Docs

doc-updater updates ARCHITECTURE.md (incl. the invariant "scope is
enforced only at the tool layer; the transport accepts every write"),
writes `docs/adr/0023-transport-conformance-cases.md` from plan.md's
eight decisions (decision 7 recorded as the human's decision of
2026-10-02; decision 8 records the duplicate-scope exclusion and why
`TypeError` texts are not pinned), verifies that ADR 0019's "Update
(2026-10-02)" amendment and ADR 0021's record of decision (a) are
present (ADR 0023 cites the existing amendment; neither is edited), and
drafts `review-pr.md`.
