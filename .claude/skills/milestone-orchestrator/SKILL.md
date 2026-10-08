---
name: milestone-orchestrator
description: Orchestrate an agent team that implements every Linear issue in a project milestone end-to-end — Spec Kit, adversarial spec review, build, adversarial code review, PRs — then produce an artifact explaining the whole milestone. Use when the user runs /milestone-orchestrator or asks to finish/implement an entire milestone with an agent team.
argument-hint: <milestone name>
---

# Milestone Orchestrator

Milestone: **$ARGUMENTS**

If no milestone was given, ask the user which one before doing anything else.

## Your role

You are the orchestrator of an agent team. Use the agent team from the very first
step — do not do the issue work in this session. You plan, sequence, coordinate,
and report. Every worker agent you spawn must run on **Opus** (pass `model: opus`),
overriding any model set in an agent definition.

Repo rules in AGENTS.md still apply: edit scopes are enforced by
`scripts/hooks/guard-edits.sh`, so route edits through the matching role
(test-writer → `tests/**`, implementer → `src/**`, doc-updater → docs/specs).
Never pass `name=` when spawning test-writer, implementer, or doc-updater — the
hook reads the name as the agent type and will block their edits.

## Steps

1. **Load the milestone.** Pull latest `main`. Fetch the milestone's issues from
   Linear and build a dependency graph. Show the user the issue list and the
   planned order/parallelism in a few lines, then proceed.

2. **Per issue** (in parallel where independent, in order where one depends on
   another — start a dependent issue only after its prerequisite is merged or
   its branch is the base):
   1. Run the regular `/implement-issue` steps through Spec Kit
      (spec.md, plan.md, tasks.md in `specs/AIE-XXXX-slug/`).
   2. At the spec checkpoint, spin up an **adversarial spec reviewer** whose job
      is to find what's wrong, missing, or ambiguous against the Linear issue and
      the constitution. Iterate until it passes.
   3. Once the spec passes, have the same agent continue and build it — tests
      first, then implementation — until `make check` passes.
   4. Spin up **separate adversarial code reviewers** to review the finished
      diff against the spec (correctness, test coverage, spec fidelity, required
      ARCHITECTURE.md/ADR updates). Have agents fix what they find. `make check`
      must pass afterward.
   5. Open the PR per repo conventions (branch `AIE-XXXX-slug`, issue ID in
      title and commits, review artifact from `.claude/commands/implement-issue.md`).

3. **Escalate only real decisions.** Resolve routine questions yourself using the
   spec, codebase, and sensible defaults. Ask the user when a choice genuinely
   changes product behavior, the public API, or storage semantics.

4. **Keep the user at orchestration level.** Report plans, decisions, and
   outcomes — not raw subagent output.

5. **Final artifact.** When every issue is done, create an artifact that explains
   the entire milestone: what each issue delivered, how the pieces fit together
   architecturally, key decisions and spec deviations (with ADRs), what the
   adversarial reviews caught, PR links, and any open follow-ups.
