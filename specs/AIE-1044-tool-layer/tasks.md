# Tasks: Tool layer

**Linear issue**: AIE-1044 | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

Each task runs test-writer (failing tests), then implementer (make them
pass), then a green `make check`, in order. Branch is based on
`AIE-1048-transport-interface`; confirm `wenchang.transport.TransportClient`
imports before T1.

## T1 — InvalidArgumentError

Add `InvalidArgumentError` to `src/wenchang/errors.py` per plan.md.

Acceptance: spec US4.4, in new `tests/test_errors_invalid_argument.py`.
Covers FR-004's error-class half.

## T2 — MemoryTools, bind_tools, path building, forwarding, checks, conversions

Create `src/wenchang/tools.py` per plan.md, with scope-relative tool
signatures, the grant check and `build_path`/`build_prefix` path building
(`_path`, `_prefix`, `_entity` reading `identity.grants[scope].entity_id`
directly), the one wrong-type rule and UTF-8 checks (`_exact`,
`_encodable`), and the agent-facing docstrings from the plan's table.

Acceptance: spec US1.1–7, US2.1–9, US3.0–11, US4.1–3, US4.5–6, US6.1–3, in
new `tests/test_tools.py`; and US5.1–8 in new
`tests/test_tools_descriptions.py` (written in the same task so the
docstrings land with the code). Covers FR-001 (tool half), FR-002,
FR-003, FR-004's conversion half, FR-005, FR-006, FR-007, FR-008.

## T3 — End-to-end

test-writer adds `tests/test_tools_end_to_end.py` (SC-002) over the
tests-only `_StoreClient` wrapping a real `MemoryStore` and
`InMemoryStorage`, using `(scope, area, name)` arguments. The rendering assertions in SC-002 land in T4 (after
`render_*` exist); T3 covers the tool calls and rejections. Expected green
on the first run if T2 is correct; any failure routes to the implementer.

## T4 — Rendering helpers

Add `render_result` and `render_error` to `src/wenchang/tools.py` per
plan.md decision 11 and its interface sketch.

Acceptance: spec US7.1–12 (including US7.5a) in new `tests/test_tools_render.py`, plus
SC-002's rendering half added to `tests/test_tools_end_to_end.py`
(each result through `render_result`, each error through `render_error`,
`json.dumps` succeeds). Covers FR-001 (render half), FR-009.

## T5 — Docs

doc-updater updates ARCHITECTURE.md (tools implemented with scope-relative
arguments and own-entity reads, rendering helpers, errors entry, diagram
prose including `tools --> paths`, invariant), writes
`docs/adr/0022-tool-layer.md` from plan.md's thirteen decisions (recording
the human decisions of 2026-10-02 as decided and spec.md's items 3–5 as
orchestrator calls pending PR review), notes in ADR 0016's consequence
that the tool-layer tests now exist, notes in ADR 0017 (or in ADR 0022
referencing it) that read scoping is decided as own-entity-only, updates
the glossary if needed, and drafts `review-pr.md`.
