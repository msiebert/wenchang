# wenchang: Agent Memory Library

## What it is

wenchang gives an AI agent persistent, self-organizing memory: a virtual
filesystem of plain markdown files, exposed to the agent as a small set of
tools (`read_file`, `write_file`, `append_line`, `replace_fact`,
`list_prefix`, `delete_file`, `get_memory_index`). The agent decides what to
file and where; the library supplies mechanism — storage, optimistic
concurrency, authorization hooks — and ships instruction text describing
how to use that mechanism well. It imposes no schema on what gets written.

## Who it's for

Teams building AI agents (chat assistants, coding agents, analytics
copilots) that need memory to persist across sessions and be shared,
selectively, across scopes such as a user, a project, or an organization.
An adopter integrates the library by supplying an identity resolver (who is
calling, and with what role) and, optionally, scope-specific configuration
text (Section 8 of the spec). No swappable storage backend is provided —
GCS is assumed as the backing store.

## Source of truth

- Specification (Notion):
  https://app.notion.com/p/mxpnl/Agent-Memory-Library-Specification-3dfe0ba925628152ab48f7dde5cd7e28
- Linear project:
  https://linear.app/mixpanel/project/agent-memory-library-650c358823cc/overview
  (issue prefix `AIE-`)

This repository's docs (ARCHITECTURE.md, AGENTS.md, this file) summarize and
track the spec; where they disagree, the Notion doc governs.

## Milestones

| Milestone | Spec section(s) |
|---|---|
| 1. Core library API and concurrency | §4 File format and metadata, §5 Core library API |
| 2. Identity resolver and scope model | §3 The scope model, §6 The identity resolver interface |
| 3. Transport interface, in-process implementation, and tool layer | §7 Transport and deployment, §5 API surface (tool mirroring) |
| 4. Prompt layer content | §8 The prompt layer |
| 5. Integration and conformance close-out | §9 Reference adopter configuration, §10 Conformance |
