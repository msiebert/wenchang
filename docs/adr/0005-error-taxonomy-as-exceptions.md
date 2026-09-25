# 0005. Error taxonomy as exceptions

Date: 2026-09-25

## Status

Accepted

## Context

The Notion spec's Section 5 defines a three-category error taxonomy
(recoverable / permanent / transient) by what the caller should do next, and
describes some recoverable kinds as "returns current content" alongside a
count. AIE-1030 turns that into a concrete Python vocabulary
(`wenchang.errors`, `wenchang.version_token`) ahead of any core API function
that raises these errors, and several points needed a decision or diverge
from a literal reading of the spec text.

## Decision

- **Errors are raised as Python exceptions**, one class per category
  (`RecoverableError`, `PermanentError`, `TransientError`, all deriving from
  base `WenchangError`), rather than returned result values. The spec's
  "returns current content" is satisfied by the exception instance carrying
  that content as an attribute (e.g. `VersionConflictError.content`).
- **Guidance text is fixed per category, not per instance.** Each category
  class sets a class-level `guidance` string describing the next action;
  every concrete error's `message` is its instance-specific `detail`
  followed by that fixed text. This keeps the required wording (User Story
  3) consistent in one place instead of duplicated across concrete kinds.
- **`ReplaceFactMatchError` carries the current version token**, not just
  content and match count as the Notion text lists, so the caller can retry
  with a version guard without an extra read.
- **`VersionConflictError` carries content and version but not file
  metadata.** The metadata type doesn't exist yet (it arrives with
  AIE-1031); adding a `metadata` attribute later is additive and won't break
  callers.
- **`NotFoundError` distinguishes two reasons** via `NotFoundReason`:
  `invalid_path` (the path does not resolve to a valid memory location —
  malformed, or outside any scope) versus `file_absent` (a valid location
  with no file yet). This resolves an ambiguity in "no such path" in the
  Notion spec; confirmed with the human at the AIE-1030 spec checkpoint.
- **`VersionToken` lives in its own module** (`wenchang.version_token`), a
  `NewType` over `str`, rather than inside `wenchang.errors`, because every
  later core API function needs it and importing it shouldn't require
  importing the error hierarchy.
- **Error serialization across a transport** (Section 10.2's error parity
  requirement) is deferred to the transport issues (AIE-1045/1048); this
  issue defines only the in-process Python exception vocabulary.

## Consequences

Callers use ordinary `try`/`except` and can branch on category without
knowing every concrete kind, or catch a specific kind for its repair
material. Fixing guidance text per category means a future wording change
only touches three places, not every concrete error. Deferring metadata on
`VersionConflictError` and error-transport serialization means those are
tracked as explicit follow-ups (AIE-1031, AIE-1045/1048) rather than
guessed at now. The two extra `NotFoundReason`/repair-material choices are
deviations from a literal reading of the Notion spec text and are recorded
here rather than left implicit in code.
