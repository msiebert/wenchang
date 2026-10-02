# Tasks: Shared transport conformance harness

**Linear issue**: AIE-1047 | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

Each task runs test-writer (failing tests), then implementer (make them
pass), then a green `make check`, in order. Branch is based on
`AIE-1046-inprocess-client`. **Precondition, checked by the orchestrator
before T1**: the branch is rebased onto the final AIE-1046 commit, so
`docs/adr/0020-*.md` exists and `wenchang.transport.InProcessClient` and
`MemoryStore.get_memory_index` import.

## T1 — Helpers and packaging

Create `src/wenchang/testing/transport_conformance.py` with the module
docstring, constants, `_name`, `_short`, the fixture checks,
`probe_path`, `sentinel_path`, `require_fresh`, `expect_error`, and the
four canonical readers; export `TransportConformance` (an empty class
for now) from `wenchang.testing`.

Acceptance: spec US1.6, US2.1–2.7 (helper-level tests in new
`tests/test_transport_conformance_self.py`) and US5.1–5.2, US5.4
(additions to `tests/test_testing_package.py`). Covers FR-002–FR-007.

## T2 — Baseline cases and reference run

Add the five `test_*` methods to `TransportConformance` per plan.md.

Acceptance: spec US1.1, US1.5, US3.1–3.5 in new
`tests/test_transport_conformance_reference.py`, plus US5.3 (method-name
set) in `tests/test_testing_package.py`. Covers FR-001.

## T3 — Self-tests: the harness bites

Test-writer only unless a self-test exposes a harness defect.

Acceptance: spec US1.2–1.4, US4.1–4.10 in
`tests/test_transport_conformance_self.py`. Covers SC-001's failing half.

## T4 — Docs

doc-updater updates ARCHITECTURE.md (`testing` and `transport` entries),
writes `docs/adr/0021-transport-conformance-harness.md` from plan.md's
ten decisions (decision 10 as an open question for the human with the
three options and the recommendation), updates the glossary if a term is
new, and drafts `review-pr.md`.
