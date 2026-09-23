---
description: Implement a Linear issue end-to-end through Spec Kit, with a human checkpoint before any code is written.
argument-hint: AIE-XXXX
---

Implement Linear issue `$ARGUMENTS` (format `AIE-XXXX`). Work through these
steps in order. Do not skip the checkpoint in step (c).

## (a) Gather context

1. Fetch the issue via `mcp__claude_ai_Linear__get_issue` and its comments via
   `mcp__claude_ai_Linear__list_comments`.
2. Identify the Notion spec section it corresponds to (the project's Spec Doc
   link, or a section referenced in the issue description) and fetch it with
   `mcp__claude_ai_Notion__notion-fetch`.
3. Note the issue's milestone and any sibling issues that look like
   dependencies, even though Linear may show no formal blocking links.

## (b) Branch and spec directory setup

Do this before running any Spec Kit command:

1. Ensure a clean working tree (`git status`). Stash or ask the user how to
   handle any uncommitted changes before continuing.
2. `git checkout main`.
3. `git pull --ff-only`. This is not run with any flag that skips
   confirmation — the user may be prompted (e.g. for credentials) since this
   talks to the remote; that's expected.
4. `git checkout -b msiebert-AIE-XXXX-<slug>` (substituting the real issue
   number and a short slug for the feature), per the user's branch-naming
   convention.
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
3. Run `/speckit-plan`, then `/speckit-tasks`.
4. If the issue is large or its acceptance criteria are ambiguous, also run
   `/speckit-clarify` before planning, and `/speckit-analyze` after tasks are
   generated.

## (d) CHECKPOINT — stop here for human approval

Present to the human:
- The acceptance criteria (Given/When/Then) from spec.md.
- A short summary of plan.md and tasks.md.

Do **not** write any implementation code before the human approves. Wait for
an explicit go-ahead.

After approval, ask (do not assume) whether to write the approved acceptance
criteria back to the Linear issue as a comment. Only do this with explicit
confirmation, and any comment posted must begin with:

```
Response by The Claudefather:
```

## (e) Implement, tests-first

1. Run `/speckit-implement` to work through `tasks.md`. For each task, write
   the failing test(s) for its acceptance criteria first, confirm they fail,
   then implement until green.
2. Never delete, skip, `xfail`, or weaken an existing test to make this
   pass — see the constitution
   (`.specify/memory/constitution.md`) for the exception path.
3. Run `make check` until it's green.
4. If the change touches storage, also run `make test-integration` against
   the fake-gcs-server emulator (`STORAGE_EMULATOR_HOST=http://localhost:4443`).

## (f) Docs

If the change touches the public API, module boundaries, storage/concurrency
semantics, or scope enforcement, update `ARCHITECTURE.md` and add an ADR
under `docs/adr/`.

## (g) Review

Run the `spec-reviewer` subagent against this issue's diff and spec. Address
every FAIL it reports, then re-run it until clean.

## (h) Commit

Commit with the Linear ID in the message. Ask the human before pushing or
opening a PR — do not push or open a PR unprompted. Branch name should be
`msiebert-AIE-XXXX-short-slug` per the user's branch-naming convention (this
is the branch created in step (b)).

The PR body must:
- Link the Linear issue.
- Include an acceptance-criteria → test mapping table.
- Include a "Why" section.

## (i) Close out

With explicit confirmation, post a summary comment to the Linear issue,
prefixed with:

```
Response by The Claudefather:
```
