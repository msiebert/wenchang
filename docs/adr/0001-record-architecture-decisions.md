# 0001. Record architecture decisions

Date: 2026-09-23

## Status

Accepted

## Context

wenchang will accumulate decisions about module boundaries, public API
shape, and storage semantics over its lifetime. Without a record, later
contributors re-litigate settled questions or violate constraints for
reasons that are no longer visible.

## Decision

We use Architecture Decision Records, in the MADR-style format captured in
[0000-template.md](0000-template.md), stored under `docs/adr/` and numbered
sequentially. AGENTS.md requires a new ADR whenever a change alters module
boundaries, the public API, or storage semantics.

## Consequences

Decisions and their rationale are discoverable in one place, alongside the
code. Every such change carries a small, mandatory documentation cost.
