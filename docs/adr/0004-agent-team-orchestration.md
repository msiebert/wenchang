# 0004. Agent team orchestration for AI-driven development

Date: 2026-09-24

## Status

Accepted

## Context

Development in this repo is done by Claude Code sessions working through
`/implement-issue`. A single session doing everything — reading the spec,
writing tests, writing implementation, updating docs, and reviewing its own
diff — has no separation of concerns: the same context that wrote the
implementation also decides whether the tests are adequate and whether the
diff matches the spec, which erodes the value of tests-first development and
of an independent review step (Constitution principles I, II, XI).

We want the main session to stay focused on planning, spec-writing, and
coordination, and to delegate hands-on code/test writing to subagents whose
scope is narrow and mechanically enforced, not just documented.

## Decision

Run every non-trivial session as an agent team:

- **Orchestrator** (main session, model `opus`, set in
  `.claude/settings.json`): gathers context, sets up the branch and spec
  directory, runs the Spec Kit flow, writes `spec.md` and the review
  artifacts (`review-spec.md`, and reviews `review-pr.md`), delegates each
  implementation task, verifies `make check`, and handles commit/push/PR.
  It never edits `src/` or `tests/` itself.
- **explorer** (`model: haiku`, tools `Read, Grep, Glob, Bash`): read-only
  code location and "where is X" lookups, so the orchestrator doesn't spend
  its own context grepping the tree. Runs in parallel with other read-only
  work.
- **test-writer** (`model: sonnet`, tools `Read, Grep, Glob, Edit, Write,
  Bash`): writes failing tests for one task's acceptance criteria, using
  only the public interface described in `plan.md` — not the implementation.
  May only touch `tests/`.
- **implementer** (`model: sonnet`, same tool set): makes one task's
  already-written failing tests pass. May not touch `tests/`. If a test
  looks wrong, it stops and reports to the orchestrator instead of editing
  the test itself.
- **doc-updater** (`model: sonnet`, same tool set): updates
  `ARCHITECTURE.md`, adds ADRs, updates the glossary, and drafts
  `review-pr.md`. May only touch `ARCHITECTURE.md`, `docs/**`, `specs/**`.
- **spec-reviewer** (`model: sonnet`, tools `Read, Grep, Glob, Bash`,
  read-only): reviews the diff against `spec.md` and the Notion spec after
  implementation, gating the PR.

**Why test-writer is separate from implementer:** if the same agent (or
context) writes both the test and the code that satisfies it, there's no
independent check that the test would actually fail without the
implementation, or that it reflects the acceptance criteria rather than
whatever the implementer found convenient to satisfy. Splitting them means
test-writer commits to a red test from the spec's public interface *before*
any implementation exists to shape it, and implementer is held to a target
it didn't choose. This mirrors why `spec-reviewer` is a separate read-only
agent from either.

**Why no worktree isolation:** `isolation: worktree` branches a fresh
worktree from the repo's default branch (`main`). Implementation work here
happens on a feature branch that already has spec artifacts, prior tasks'
code, and possibly prior commits — a worktree rooted at `main` would not
contain any of that. Edit-capable subagents (`test-writer`, `implementer`,
`doc-updater`) therefore run sequentially in the main checkout, not in
worktrees. Only read-only subagents (`explorer`, `spec-reviewer`) can safely
run in parallel, since they don't mutate shared state.

**Enforcement:** edit scope per role is enforced by a PreToolUse hook
(`scripts/hooks/guard-edits.sh`) that reads `agent_type` from the hook
payload and allows/denies `Edit`/`Write` calls by path accordingly. The main
orchestrator session has no `agent_type` in the payload, so the hook denies
its own `Edit`/`Write` outside `specs/**` as well — the orchestrator is a
role like any other for enforcement purposes. Subagent frontmatter itself
carries no path restriction; the hook is the actual gate.

## Consequences

- **Cost**: most tasks now involve at least three model calls (test-writer,
  implementer, spec-reviewer) instead of one, plus explorer lookups. Slower
  and more token-expensive per issue, traded for independent checks at each
  step.
- **Sequential edits**: because edit-capable subagents share the main
  checkout instead of isolated worktrees, they cannot run concurrently
  without risking conflicting writes to the same files. Tasks in `tasks.md`
  are implemented one at a time, in order.
- **Bash is not covered by the hook**: `guard-edits.sh` only inspects
  `Edit`/`Write` tool calls. Any subagent with `Bash` access (all of them,
  for running tests/`make check`) could still write files outside its scope
  via shell redirection or `sed -i`. The hook is a guardrail against
  accidental scope creep during normal tool use, not a hard sandbox against
  an adversarial or malfunctioning agent; each subagent's system prompt
  states its scope explicitly as the primary control, with the hook as
  backstop.
