---
description: "before_specify hook: resolve/create the Spec Kit feature directory, honoring a Linear issue ID (e.g. AIE-1234) in the description."
argument-hint: "<feature description, optionally containing an AIE-XXXX Linear ID>"
---

## User Input

```text
$ARGUMENTS
```

This command is the project's `before_specify` hook, registered in
`.specify/extensions.yml` as `speckit.local.create-feature`.
`/speckit-specify` invokes it automatically during its Pre-Execution Checks,
before writing the spec. It is not normally run standalone.

## What it does

1. Run:

   ```
   .specify/scripts/bash/create-new-feature.sh --json --allow-existing-branch "$ARGUMENTS"
   ```

   This script contains the Linear-ID naming logic: if the description
   (case-insensitively) contains `AIE-<digits>`, the feature directory
   becomes `specs/AIE-<DIGITS>-<slug>/` and the suggested branch name
   becomes `msiebert-AIE-<DIGITS>-<slug>`; otherwise it falls back to
   sequential `specs/NNN-<slug>/` numbering. In non-dry-run mode it also
   creates the directory, copies the spec template into `spec.md`, and
   persists the resolved path to `.specify/feature.json`. That persistence
   is the mechanism `/speckit-plan`, `/speckit-tasks`, and
   `/speckit-implement` use via `check-prerequisites.sh` to find the feature
   directory, independent of the rest of this hook.

2. Parse the script's JSON output: `BRANCH_NAME`, `SPEC_FILE`, `FEATURE_NUM`.

3. Report `BRANCH_NAME` and `FEATURE_NUM` back to `/speckit-specify`, per its
   Pre-Execution Checks contract ("it will have created/switched to a git
   branch and output JSON containing `BRANCH_NAME` and `FEATURE_NUM`").

4. Treat the directory of `SPEC_FILE` as an explicitly provided
   `SPECIFY_FEATURE_DIRECTORY` for the remainder of this `/speckit-specify`
   invocation — this satisfies resolution order priority 1 in
   `/speckit-specify` ("If the user explicitly provided
   `SPECIFY_FEATURE_DIRECTORY` (e.g., via environment variable, argument, or
   configuration), use it as-is") — so `/speckit-specify`'s own
   directory-creation step reuses this directory instead of computing a
   second, conflicting sequentially-numbered one for the same feature.

5. This hook does **not** create or switch git branches itself. For
   `/implement-issue`, branch creation happens earlier, before Spec Kit is
   invoked at all (see `.claude/commands/implement-issue.md`). The
   `BRANCH_NAME` this hook reports is for reference/verification only.

## Done when

- [ ] `create-new-feature.sh` ran and its JSON output was parsed
- [ ] `SPECIFY_FEATURE_DIRECTORY` is treated as explicitly set to the
      script's resolved feature directory for the rest of this
      `/speckit-specify` run
- [ ] `.specify/feature.json` reflects the resolved feature directory
