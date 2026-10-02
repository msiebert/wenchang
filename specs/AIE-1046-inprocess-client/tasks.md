# Tasks: In-process transport client and memory index

**Linear issue**: AIE-1046 | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

Each task runs test-writer (failing tests), then implementer (make them
pass), then a green `make check`, in order. Branch is based on
`AIE-1048-transport-interface`. **Precondition, checked by the
orchestrator before T1:** the branch is rebased onto the final AIE-1048
commit, so that `docs/adr/0019-transport-client-interface.md` exists,
`wenchang.transport.TransportClient` and `wenchang.core.MemoryIndex`
import, `MemoryIndex(entries=(<FileEntry subclass instance>,))` raises
`TypeError`, and `tests/test_transport_protocol.py` contains the
top-level-imports assertion. If any fails, rebase first.

## T1 — Entry byte accounting

Add `DEFAULT_INDEX_MAX_BYTES`, `INDEX_SYSTEM_AREA`, and
`index_entry_bytes` to `src/wenchang/core.py`.

Acceptance: spec US1.10–11, US3.1, and US6.2, in new
`tests/test_core_index_bytes.py`. Covers FR-003.

## T2 — Constructor settings and get_memory_index

Add `index_max_bytes` and `scope_priority` to `MemoryStore.__init__` with
properties, and implement `get_memory_index` per plan.md.

Acceptance: spec US1.1–9, US1.12, US2.1–6, US3.2–8, US4.1–7, in new
`tests/test_core_get_memory_index.py`. Covers FR-001, FR-002.

## T3 — InProcessClient

Add `InProcessClient` to `src/wenchang/transport.py`.

Acceptance: spec US5.1–6, US6.1, US6.3, in new
`tests/test_transport_inprocess.py`. Covers FR-004, FR-005, FR-006.

## T4 — Integration test

test-writer adds `tests/integration/test_gcs_memory_index.py` (SC-002).
Orchestrator runs `make emulator-up` then `make test-integration`. No
implementation expected; if it fails, the implementer fixes `core`.

## T5 — Docs

doc-updater updates ARCHITECTURE.md, writes
`docs/adr/0020-memory-index-and-in-process-client.md` from plan.md's
decisions 1–11 (including 6a and 6b), appends an update line to ADR 0010
pointing the index work at ADR 0019/0020, closes ADR 0019's pending item
on where the index is built, updates the glossary (memory index entry:
cap rule, entry cost), and drafts `review-pr.md`.
