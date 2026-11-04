# Feature Specification: Cover FileQuotaExceededError in the transport conformance suite

**Linear**: AIE-1322
**Feature Branch**: `AIE-1322-conformance-file-quota`
**Created**: 2026-11-02
**Status**: Draft
**Related**: AIE-1292 (file cap), ADR 0039 (decision 8: conformance gap), ADR 0021, ADR 0023

Allow-test-changes: adding an eighth (optional) fixture to the protocol case
forces edits to existing conformance self-tests, none weakened:
`tests/test_transport_conformance_self.py` (`FIXTURE_ORDER`, `_fixtures`,
the capped reference client, `BAD_FIXTURE_VALUES`, `FIXTURE_PAIRS`,
`BAD_FIXTURES`, and `test_every_case_takes_only_the_seven_fixtures`, renamed to
`..._eight_fixtures` with the eighth entry added);
`tests/test_transport_conformance_cases_self.py` (`_fixtures`, `_reference()`);
`tests/test_transport_conformance_reference.py` and
`tests/test_transport_conformance_cached.py` (store cap, fixture override,
case list, docstrings).

## Summary

AIE-1292 added a per-entity file cap (`MemoryStore(max_files_per_entity=...)`,
default 500) and a recoverable `FileQuotaExceededError(path, limit)`. The
transport conformance suite (`wenchang.testing.TransportConformance`, shipped to
adopters) never exercises it, so a transport could drop, reshape, or mis-render
that error and still pass conformance. ADR 0039 left this gap because a
**required** cap fixture would break every adopter's existing suite.

This feature adds an **optional** fixture, `max_files_per_entity`, defined on
`TransportConformance` with a default of `None`, and one new case that fills an
entity to the cap and asserts the next create raises `FileQuotaExceededError`
with core's exact type, category, message, and payload, storing nothing.
Adopters who do not override the fixture keep a passing suite (the new case
skips, naming the fixture); adopters who report their store's cap get coverage.
The in-repo subclasses (reference `InProcessClient` and cached `InProcessClient`)
configure a small cap and override the fixture so the case runs in this repo.

## User Scenarios & Acceptance Criteria

### US1 — The suite catches a transport that mis-renders FileQuotaExceededError (P1)

An adopter whose client fixture's store has a cap of N sets the
`max_files_per_entity` fixture to N; the suite then fails any client that does
not surface the quota error exactly as core raises it.

1. **Given** a conforming client over a store with `max_files_per_entity=N` and
   the fixture returning N, **When** the new case runs, **Then** it creates N
   files under the second sorted scope's entity (area `notes`) and the (N+1)th
   create raises `FileQuotaExceededError` whose `type` is exactly
   `FileQuotaExceededError`, `category` is `ErrorCategory.RECOVERABLE`,
   `str()` equals `str(FileQuotaExceededError(path, N))` built locally from core,
   `path` equals the attempted path (`str`), and `limit` equals N (`int`), and
   the case passes.
   Failures in US1.3–US1.7 use label `write_file(<p>)` where `<p>` is
   `build_path(second, scope_map[second], "notes", "conformance-probe-<N>")`;
   fill paths use stems `conformance-probe-0` … `conformance-probe-<N-1>`.
2. **Given** the same setup, **When** the over-cap create has been rejected,
   **Then** `read_file` of the attempted path raises `NotFoundError` with reason
   `FILE_ABSENT` (nothing was stored).
3. **Given** a client that raises a different error type at the cap (e.g.
   `OversizeWriteError`, `VersionConflictError`, or a plain `RuntimeError`),
   **When** the case runs, **Then** it fails with the existing key phrase
   `wrong error type`.
4. **Given** a client that raises `FileQuotaExceededError` with a wrong `limit`
   or `path`, **When** the case runs, **Then** it fails with `wrong payload`.
5. **Given** a client whose quota error's `str()` differs from core's (e.g.
   guidance stripped, detail reworded), **When** the case runs, **Then** it
   fails with `wrong message`.
6. **Given** a client whose quota error has the wrong category, **When** the
   case runs, **Then** it fails with `wrong category`.
7. **Given** a client (or store) that never enforces the cap so the (N+1)th
   create succeeds, **When** the case runs, **Then** it fails with
   `FileQuotaExceededError did not raise` and the message includes the hint
   `check the max_files_per_entity fixture`.
8. **Given** a client that raises `FileQuotaExceededError` before N files exist
   (fixture larger than the store's real cap), **When** the case runs, **Then**
   it fails at that fill write with label `write_file(<path>)` and phrase
   `unexpected error: FileQuotaExceededError; check the max_files_per_entity
   fixture`. The check is `type(exc) is FileQuotaExceededError` (a subclass gets
   no hint); any other `Exception` during the fill fails with the usual
   `unexpected error: <Type>` and no hint; `BaseException` propagates.
9. **Given** a client that stores the over-cap file and then raises the correct
   `FileQuotaExceededError`, **When** the case runs, **Then** it fails at
   `read_file(<path>)` (the post-rejection absence check), as the analogous
   oversize "stores then rejects" client does.

### US2 — Existing adopter suites keep passing without changes (P1)

1. **Given** a `TransportConformance` subclass that does not define a
   `max_files_per_entity` fixture, **When** pytest collects and runs it,
   **Then** there is no collection error and every pre-existing case behaves as
   before; the new case calls `pytest.skip` with a reason naming the
   `max_files_per_entity` fixture and how to enable it. The skip happens after
   fixture validation and before `require_fresh`, so a skipped run makes no
   client call that writes.
2. **Given** such a subclass, **When** `test_client_satisfies_protocol` runs,
   **Then** it passes (the `None` default is valid).
3. **Given** the default fixture, **Then** it is defined as
   `@pytest.fixture(name="max_files_per_entity") def _max_files_per_entity(self)`
   so it is not a public suite method (the public-methods listing test keeps
   counting only cases), and a subclass fixture named `max_files_per_entity`
   overrides it.

### US3 — The fixture is validated like the others (P2)

1. **Given** the fixture returns `None`, **When** fixtures are validated,
   **Then** validation passes.
2. **Given** the fixture returns an exact `int` at least
   `MIN_FILES_PER_ENTITY` (32), **When** validated, **Then** validation passes.
3. **Given** the fixture returns a `bool`, a non-int (e.g. `"32"`, `32.0`), or
   an int below `MIN_FILES_PER_ENTITY` (e.g. 0, 31), **When**
   `test_client_satisfies_protocol` or the new case runs, **Then** it fails with
   the existing fixture-check key phrase `fixture max_files_per_entity`.
4. **Given** all fixtures, **When** `test_client_satisfies_protocol` runs,
   **Then** `max_files_per_entity` is validated after `list_page_size`
   (existing fixtures keep their order, so the first bad one reported is
   unchanged for existing failures).
5. **Given** an int fixture value below `list_page_size + 2` (e.g. cap 40 with
   `list_page_size` 40), **When** `test_client_satisfies_protocol` runs,
   **Then** it fails with `<Name>: fixture max_files_per_entity must be at least
   list_page_size + 2 (<n>), got <cap>`, here `... (42), got 40` (the pagination
   cases create `list_page_size + 1` files plus the sentinel under one entity). Cap 32 with
   `list_page_size` 30 passes. The new case itself does not take
   `list_page_size`.

### US4 — Repo transports run the case (P1)

1. **Given** the reference subclass `TestInProcessClient` and the cached
   subclass `TestCachedInProcessClient`, **When** the suite runs, **Then** each
   builds its `MemoryStore` with `max_files_per_entity=32`, overrides the fixture
   to return 32, and the new case runs and passes (not skipped) along with every
   existing case.
2. **Given** `test_suite_public_methods_are_exactly_the_listed_cases`, **When**
   it runs, **Then** the new case name is in the listed set.

## Edge cases

- The sentinel file lives under the first sorted scope's entity and counts
  toward that entity's cap; the case fills the **second** sorted scope's entity,
  which holds nothing else, so exactly N creates reach the cap.
- Files other cases create under one entity: the index-cap case up to 21 (20
  plus one fit probe) under the second entity; the pagination cases
  `list_page_size + 2` (with the sentinel) under the first; others 3 or fewer.
  So the required floor is `max(MIN_FILES_PER_ENTITY, list_page_size + 2)` with
  `MIN_FILES_PER_ENTITY = 32`; a store at that floor passes every other case.
- Message parity is checked against `str(FileQuotaExceededError(path, limit))`
  built from the installed core, never a hardcoded string, so a change to core's
  rendering (e.g. AIE-1320's detail/guidance separator) needs no suite change and
  `tests/test_transport_conformance_messages.py` gets no new entry.

## Out of scope

- Cap counting semantics (system/ exclusion, malformed keys, delete freeing a
  slot, create-on-existing at the cap) — core behavior already tested in
  `tests/test_core_file_cap.py`; transports only forward.
- Making the fixture required.
- Tool-layer/MCP rendering (covered by `tests/test_mcp_server.py`,
  `tests/test_tools_end_to_end.py`).

## Success criteria

- `make check` passes; both in-repo subclasses run the new case unskipped.
- Self-tests show each mis-rendering in US1.3–US1.9 fails the case with the
  stated phrase, and US2/US3 behave as stated.
- Public testing API grows (optional fixture, `MIN_FILES_PER_ENTITY`,
  `check_files_per_entity`), so ARCHITECTURE.md and an ADR are updated
  (constitution VII). No runtime/core/storage change.
