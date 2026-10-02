# Tasks: Abstract transport client interface

**Linear issue**: AIE-1048 | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

Each task runs test-writer (failing tests), then implementer (make them
pass), then a green `make check`, in order.

## T1 — Index value types in core

Add `CappedPrefix` and `MemoryIndex` to `src/wenchang/core.py` per plan.md.

Acceptance: spec US3.1–6, in new `tests/test_core_index_types.py`. Covers
FR-003.

## T2 — TransportClient protocol

Create `src/wenchang/transport.py` per plan.md.

Acceptance: spec US1.1–5, US2.1–3, US4.1–3, in new
`tests/test_transport_protocol.py`. Covers FR-001, FR-002, FR-004, FR-005.
US4.2 and US4.3 are regression guards that are green before the change;
US2.1's pyright half is enforced by `make typecheck`, not pytest.

## T3 — Docs

doc-updater updates ARCHITECTURE.md (transport implemented; core index
types; `get_memory_index` still planned for AIE-1046; the sentence saying
"the tool and transport layers will call `resolve_identity`" corrected to
the tool layer only), writes `docs/adr/0019-transport-client-interface.md`
from the eight decisions in plan.md including the AIE-1044 → AIE-1046
index rescoping, and drafts `review-pr.md`. The three calls listed under
"Orchestrator calls" in review-spec.md are recorded in the ADR as
orchestrator decisions pending human review at the PR, not as human
approvals; approval wording is added only after the human signs off.
