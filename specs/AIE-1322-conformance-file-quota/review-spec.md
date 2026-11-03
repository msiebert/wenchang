# Spec Review: AIE-1322 — Cover FileQuotaExceededError in the transport conformance suite

Spec checkpoint: adversarial spec-reviewer passed after one revision round. It caught (1) the new fixture's default breaking the public-methods listing test, (2) the floor depending on `list_page_size`, and (3) the existing self-test edits needing `Allow-test-changes`. All three are fixed in spec.md/plan.md.

## What & why

AIE-1292 added a per-entity file cap and `FileQuotaExceededError(path, limit)`, but `TransportConformance` never exercises it. A transport could drop or mis-render that error and still pass. ADR 0039 left the gap because a required cap fixture would break every adopter's suite. This adds an optional fixture, `max_files_per_entity` (default `None`), and one case that fills an entity to the cap and checks the next create raises core's exact error. Without the fixture, the case skips.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| US1.1-2 | Conforming client, store cap N, fixture N | Fill N files under the second sorted scope's entity, then create N+1 | `FileQuotaExceededError` with exact type, RECOVERABLE category, `str()` equal to core's, `path` and `limit` payload; `read_file` gives `FILE_ABSENT` |
| US1.3-6 | Client raising wrong type, payload, message, or category | Case runs | Fails with `wrong error type`, `wrong payload`, `wrong message`, `wrong category` |
| US1.7 | Cap never enforced | Case runs | `FileQuotaExceededError did not raise` plus hint `check the max_files_per_entity fixture` |
| US1.8 | Fixture larger than the real cap | Quota error during fill | `unexpected error: FileQuotaExceededError; check the max_files_per_entity fixture` (exact type only) |
| US1.9 | Client stores the file, then raises | Case runs | Fails at `read_file(<path>)` |
| US2 | Subclass with no fixture | Collected and run | No collection error, old cases unchanged, new case skips naming the fixture (before `require_fresh`, so no writes); protocol test passes |
| US3 | Fixture `None`, or int >= 32 | Validated | Passes |
| US3 | `bool`, non-int, or int < 32 | Protocol case or new case | Fails with `fixture max_files_per_entity` |
| US3.5 | Cap < `list_page_size + 2` | Protocol case | Fails with `must be at least list_page_size + 2 (<n>), got <cap>` (cap 32, page 30 passes) |
| US4 | Reference and cached `InProcessClient` subclasses | Suite runs | Store cap 32, fixture override 32, new case runs unskipped and passes; case is in the public-methods listing |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| Optional fixture, default `None`, defined as `@pytest.fixture(name="max_files_per_entity") def _max_files_per_entity`; case skips when `None` | Required fixture | A required fixture breaks every adopter's existing suite (the reason ADR 0039 left the gap). The underscore name keeps it out of the public-methods listing; subclasses override by `name=` |
| Validation floor `max(32, list_page_size + 2)`, validated after `list_page_size` | Fixed floor of 32 only | Pagination cases create `list_page_size + 1` files plus the sentinel under one entity, so a cap below that breaks other cases |
| Fill the second sorted scope's entity | Fill the first scope's entity | The sentinel lives under the first and counts toward its cap. The second holds nothing else, so exactly N creates reach the cap |
| Message parity against `str(FileQuotaExceededError(path, limit))` from installed core | Hardcoded string; new entry in `test_transport_conformance_messages.py` | Robust to core rendering changes (AIE-1320's separator change) with no suite edit |
| Repo subclasses use a small cap (32) | Default 500; separate capped-client fixture | 500 writes per run, and it fails adopters with other caps. A separate fixture adds adopter surface |
| Hint on `expect_error` did-not-raise and on fill-time quota errors | No hint | Points adopters at a fixture/cap mismatch, as the oversize case does |

## Files/modules to be touched

- `src/wenchang/testing/transport_conformance.py`: `MIN_FILES_PER_ENTITY`, `check_files_per_entity`, the fixture, the new case, the protocol-case check, the `expect_error` hint, and the module docstring.
- New self-tests in `tests/`; existing-test edits (per `Allow-test-changes`) in `tests/test_transport_conformance_{self,cases_self,reference,cached}.py`.
- Docs: ARCHITECTURE.md, new ADR (0044, amending 0021, 0023 and 0039), `review-pr.md`.
- `site-src/reference.md`, plus a regenerated `site/`.

## Open questions / assumptions

- ADR number 0044 is next free and may be renumbered at PR time.
- `wenchang.testing.__all__` stays unchanged, so `tests/test_testing_package.py` needs no edit.
- Cap counting semantics are out of scope (core tests cover them in `tests/test_core_file_cap.py`).

## Risks

- Public testing API grows (fixture, constant, helper, case), and the ARCHITECTURE.md/ADR update is required.
- Adopters see one new skipped test. Adopters who opt in with a wrong cap get the fixture hint.
- Existing self-tests are edited, none weakened or deleted. The fixture count rename (seven to eight) is the main reviewer check.
