# Wenchang Constitution

## Core Principles

### I. Tests-First
Acceptance criteria are written as Given/When/Then before implementation.
Each becomes a failing test before any implementation code is written for it.
No implementation commit lands without its test already present and red.

### II. Tests Are Not Negotiable
Never delete, skip, `xfail`, or otherwise weaken an existing test to make a
change land, unless the spec for the issue being worked explicitly requires
the behavior change. A test that no longer reflects the spec is updated to
match the new spec text, not silenced.

### III. `make check` Is the Gate
`make check` (lint + typecheck + unit tests) passing is the definition of
done for any change. Nothing merges with it red.

### IV. Strict Typing
All code is strictly typed; `uv run pyright` runs clean. Public functions and
methods carry full type annotations. No untyped escape hatches without a
documented reason.

### V. Storage Only Through the Interface
All persistence goes through the internal storage interface — no module talks
to GCS directly except the interface's own implementation. The in-memory fake
used in unit tests must match real GCS semantics exactly, including
generation-based preconditions (`ifGenerationMatch`) and version-conflict
behavior, so tests passing against the fake predicts passing against GCS.

### VI. Spec Fidelity
The Notion spec ("Agent Memory Library Specification") is the source of
truth. Where an implementation must deviate from it — for practicality,
ambiguity, or a discovered flaw — the deviation is recorded in an ADR
(`docs/adr/`) before or alongside the change, not left implicit in code.

### VII. Architecture Stays Documented
Any change to the public API, module boundaries, storage/concurrency
semantics, or scope-enforcement rules requires both an ADR and an update to
`ARCHITECTURE.md` in the same PR. If neither changed, the PR didn't touch
those surfaces.

### VIII. Traceability
Every unit of work traces to a Linear issue (`AIE-XXXX`): in the spec
directory name (`specs/AIE-XXXX-slug/`), in commit messages, in the PR title,
and in test docstrings for the tests added to satisfy that issue's acceptance
criteria.

### IX. Small, Single-Issue PRs
One Linear issue per PR. A PR that grows to cover unrelated issues is split
before merge.

### X. Ask, Don't Guess
When acceptance criteria are ambiguous or silent on a case the implementation
must handle, stop and ask a human rather than inferring intent. Guessing
wrong here is more expensive than a short pause.

## Governance

This constitution supersedes ad hoc practice. Any PR that touches the areas
in Principle VII must show the corresponding ADR/ARCHITECTURE update, or
justify in the PR description why none was needed. Amendments to this
document require a PR against it, reviewed like any other change.

**Version**: 1.0.0 | **Ratified**: 2026-09-23 | **Last Amended**: 2026-09-23
