# 0044. Conformance case for the file-count cap

Date: 2026-11-02

## Status

Accepted. Supersedes in part [ADR 0039](0039-file-count-cap-per-entity.md)
decision 8 and its "not caught by the conformance suite" consequence. Amends
[ADR 0021](0021-transport-conformance-harness.md) decision 7a and
[ADR 0023](0023-transport-conformance-cases.md)'s "seven fixtures".

## Context

`FileQuotaExceededError` is part of the transport error-parity contract, but
no conformance case exercised it, so a remote transport that dropped or
reshaped it passed the suite. ADR 0039 left it out because the suite had no
cap fixture and a new required fixture would break every adopter's existing
subclass. The suite's rule so far was that every fixture is required from the
first run.

## Decision

1. **An optional eighth fixture, `max_files_per_entity`.** The mixin supplies
   a default returning `None`, through an underscore-named method registered
   with `@pytest.fixture(name="max_files_per_entity")`, so a subclass
   override replaces it and existing subclasses keep working.
2. **`None` skips the new case.** `test_create_at_file_cap_is_quota_exceeded`
   skips, before any store call, when the fixture is `None`. An adopter opts
   in by overriding the fixture with the cap its store was configured with.
3. **Validation.** A non-`None` value must be an exact `int` (not `bool`) of
   at least `MIN_FILES_PER_ENTITY = 32`. `test_client_satisfies_protocol`
   validates it after `list_page_size` and also requires at least
   `list_page_size + 2`, since the pagination cases create
   `list_page_size + 1` files plus the sentinel under one entity. The floor
   is `max(32, list_page_size + 2)`. A bad value fails rather than skips.
4. **The case.** It fills the second sorted scope's entity to the cap, then
   asserts the next create raises `FileQuotaExceededError` with core's exact
   type, category, message, `path`, and `limit`, and that nothing was stored.
   A quota error during the fill fails with a hint naming the fixture.
5. **Error hint.** `expect_error` adds "; check the max_files_per_entity
   fixture" when the expected type is `FileQuotaExceededError`.

## Consequences

- Adopters with a capped store can verify cap parity; adopters who do nothing
  see one skipped case.
- The suite's "every fixture is required" rule now has one named exception.
- The case writes as many files as the cap, so a large cap makes the run
  slower; the floor keeps the case valid and adopters choose the cap.
- A remote that drops or reshapes `FileQuotaExceededError` is caught when the
  fixture is supplied, and still not caught when it is omitted.

Rejected:

- **A required fixture.** It breaks every existing adopter subclass.
- **A default of 500.** It costs 500 writes per run and fails adopters whose
  stores use another cap.
- **A separate capped-client fixture.** It adds a second client for adopters
  to build and wire.
