---
description: Implement a Linear issue end-to-end through Spec Kit, with a human checkpoint before any code is written.
argument-hint: AIE-XXXX
---

Implement Linear issue `$ARGUMENTS` (format `AIE-XXXX`). This is an
orchestration script: **you (the main session) plan, coordinate, and write
the judgment-heavy spec artifacts yourself; you never edit `src/` or
`tests/` yourself** — that is hook-enforced (`scripts/hooks/guard-edits.sh`
denies Edit/Write under those paths for the orchestrator's own agent type).
All hands-on code and test writing is delegated to the `test-writer` and
`implementer` subagents. Work through these steps in order. Do not skip the
checkpoint in step (c).

Every delegation prompt you write for a subagent must be self-contained —
subagents start with no memory of this conversation. Include, at minimum:
the Linear ID, the spec directory path (`specs/AIE-XXXX-slug/`), the
specific task/acceptance-criteria text it needs (don't make it re-derive
this from spec.md), any constraints relevant to that step, and the report
format you expect back.

## (a) Gather context

You do this step yourself; delegate individual lookups to the `explorer`
subagent (read-only, runs in parallel) when you need to locate existing code
or prior art rather than searching yourself.

1. Fetch the issue via `mcp__claude_ai_Linear__get_issue` and its comments via
   `mcp__claude_ai_Linear__list_comments`.
2. Identify the Notion spec section it corresponds to (the project's Spec Doc
   link, or a section referenced in the issue description) and fetch it with
   `mcp__claude_ai_Notion__notion-fetch`.
3. Note the issue's milestone and any sibling issues that look like
   dependencies, even though Linear may show no formal blocking links.
4. If you need to know where related code already lives, delegate to
   `explorer` with the specific question — don't explore `src/` yourself
   beyond what's needed to write the spec.

## (b) Branch and spec directory setup

You do this step yourself. Do it before running any Spec Kit command:

1. Ensure a clean working tree (`git status`). Stash or ask the user how to
   handle any uncommitted changes before continuing.
2. `git checkout main`.
3. `git pull --ff-only`. This is not run with any flag that skips
   confirmation — the user may be prompted (e.g. for credentials) since this
   talks to the remote; that's expected.
4. `git checkout -b AIE-XXXX-<slug>` (substituting the real issue number and
   a short slug for the feature), per this repo's branch-naming convention
   (see `AGENTS.md`).
5. Run `.specify/scripts/bash/create-new-feature.sh --json "AIE-XXXX <short
   feature description>"` (or trust the `before_specify` hook registered in
   `.specify/extensions.yml` to run it automatically when `/speckit-specify`
   is invoked next — either path calls the same script). Because the
   description contains the Linear ID, the script names the spec directory
   `specs/AIE-XXXX-slug/` and persists that path to `.specify/feature.json`.
6. Verify `specs/AIE-XXXX-*/` now exists before continuing. If it does not,
   stop and investigate rather than proceeding with a mis-named or missing
   spec directory.

## (c) Run the Spec Kit flow

You write `spec.md` and `review-spec.md` yourself — these are the
judgment-heavy artifacts the human reviews, and both live under `specs/`,
which you're allowed to edit directly.

1. Run `/speckit-specify` for this feature. Its `before_specify` hook
   (`.specify/extensions.yml` → `speckit-local-create-feature`) re-resolves
   the same `specs/AIE-XXXX-slug/` directory created in step (b), so
   `/speckit-specify` writes into it rather than creating a new
   sequentially-numbered one.
2. Write `spec.md` with acceptance criteria as explicit Given/When/Then
   statements, sourced from the Linear issue and the Notion spec section —
   translate prose acceptance criteria into concrete testable statements even
   when the issue itself doesn't phrase them that way. Include the Linear ID
   at the top of spec.md.
3. Run `/speckit-plan`, then `/speckit-tasks`. `plan.md` must describe the
   public interface (function/class signatures, module boundaries) in enough
   detail that `test-writer` can write tests from it without reading `src/`.
4. If the issue is large or its acceptance criteria are ambiguous, also run
   `/speckit-clarify` before planning, and `/speckit-analyze` after tasks are
   generated.

## (d) CHECKPOINT — stop here for human approval

Write `specs/AIE-XXXX-slug/review-spec.md` from
`docs/templates/review-spec-template.md`, filled in with: what will be built
and why (plain language), the Given/When/Then acceptance criteria, key design
decisions and the alternatives rejected, the files/modules to be touched,
open questions/assumptions needing the human's call, and risks. Keep it to
one screen.

If the Artifact tool is available in this session, publish `review-spec.md`
as a concise HTML artifact and give the human the link. Otherwise, present
the markdown directly.

Do **not** write any implementation code before the human approves. Wait for
an explicit go-ahead.

After approval, ask (do not assume) whether to write the approved acceptance
criteria back to the Linear issue as a comment. Only do this with explicit
confirmation. Comments are posted plainly, with no special prefix.

## (e) Implement, tests-first — per task in tasks.md, in order

For each task in `tasks.md`, in order:

1. **Delegate to `test-writer`** (model sonnet). Prompt must include: the
   Linear ID, `specs/AIE-XXXX-slug/` path, this task's text and its
   Given/When/Then acceptance criteria (quoted, not referenced), the
   relevant public-interface excerpt from `plan.md`, and the instruction to
   write failing tests under `tests/` only, confirm they fail for the right
   reason, and report back file:line + failure output per criterion.
2. **Delegate to `implementer`** (model sonnet), sequentially, only after
   `test-writer` reports back. Prompt must include: the Linear ID, the spec
   dir path, this task's acceptance criteria, the specific failing test
   file(s) from step 1, and the instruction to implement under `src/` only,
   run `make check`, and report done/blocked with files changed. If
   `implementer` reports a test looks wrong, do not have it fix the test —
   decide yourself whether to fix the test (re-delegate to `test-writer`
   with the correction) or escalate to the human.
3. **You verify** `make check` is green (or re-run it yourself) before
   moving to the next task. Never delete, skip, `xfail`, or weaken an
   existing test to make this pass — see the constitution
   (`.specify/memory/constitution.md`) for the exception path.
4. If the change touches storage, also run `make test-integration` against
   the fake-gcs-server emulator (`STORAGE_EMULATOR_HOST=http://localhost:4443`)
   yourself once all tasks are implemented.

Do not run tasks in parallel — each edits the same working tree
sequentially (no worktree isolation is used here; a worktree would branch
from `main` and miss this branch's spec/prior tasks).

## (f) Docs

Delegate to `doc-updater` (model sonnet). Prompt must include: the Linear ID,
the spec dir path, and a summary of what changed (or point it at `git diff
main...HEAD`). It updates `ARCHITECTURE.md` if the diff touches the public
API, module boundaries, storage/concurrency semantics, or scope enforcement;
adds an ADR under `docs/adr/` for any spec deviation or architectural
decision; updates `docs/product/glossary.md` if terms changed; and drafts
`specs/AIE-XXXX-slug/review-pr.md` from `docs/templates/review-pr-template.md`.

## (g) Review

Run the `spec-reviewer` subagent (read-only) against this issue's diff and
spec. For every FAIL it reports, route the fix to the right role yourself:
a missing/wrong test goes back to `test-writer`, a missing implementation
detail or spec deviation goes to `implementer`, a missing doc/ADR goes to
`doc-updater`. Re-run `spec-reviewer` after each fix loop until clean.

## (h) Commit, push, and open the PR

You do this step yourself.

1. Commit with the Linear ID in the message. Branch name is
   `AIE-XXXX-short-slug` per this repo's branch-naming convention (this is
   the branch created in step (b)).
2. Once `spec-reviewer` is clean and `make check` passes, push the branch and
   open the PR yourself — no human approval is required for push or PR
   creation. The PR body must:
   - Link the Linear issue.
   - Link or embed `review-pr.md` (its artifact URL if published via the
     Artifact tool).
   - Include an acceptance-criteria → test mapping table.
   - Include a "Why" section.

## (i) Close out

With explicit confirmation, post a summary comment to the Linear issue,
posted plainly with no special prefix.
