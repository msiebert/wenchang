# 0016. Read-only enforcement for the `system/` area

Date: 2026-09-30

## Status

Accepted

## Context

Notion Section 3 says that within any scope, the area named `system/` holds
content a human deliberately curated and is read-only to the agent,
"enforced at the tool layer" by "an exact string check, so it is
hard-enforced rather than instructed". The same section says `system/` is
refreshed by wholesale prefix rewrite, and "the seeding job owns the entire
prefix and replaces it end to end". Section 5 classifies a restricted-scope
write as permanent, with an error that names the scope and the reason.
Section 1 principle 2 asks for enforcement at the tool layer wherever the
check is exact.

AIE-1040 asks for that rejection for all callers regardless of role. The
pieces it needs already exist: `RestrictedScopeError` and
`RestrictionReason.SYSTEM_READ_ONLY` in `wenchang.errors`, and `parse_path`
in `wenchang.paths` (ADR 0015). The tool layer does not exist yet (AIE-1044),
and the role-gated write restriction (AIE-1042) will live in the same
module.

Two requirements pull against each other. The agent must never write
`system/`, and the seeding job must keep writing `system/` through `core`.

## Decision

Add `src/wenchang/scope.py` with `SYSTEM_AREA: Final = "system"`,
`is_system_path(path) -> bool`, and `check_not_system(path) -> None`, all
pure functions over `paths.is_valid_path` and `paths.parse_path`. No other
module changes.

1. **The check is a standalone function the tool layer calls, not a guard
   inside `MemoryStore`.** The seeding job refreshes `system/` by wholesale
   rewrite through `core`, so `core` must accept `system/` writes. Rejected
   alternatives: checking in `MemoryStore` behind a bypass flag, since a flag
   is an argument the agent path could be made to pass, and a privileged
   store instance. Section 3 also places enforcement at the tool layer.
   A test pins `core`'s behavior (create, replace, `append_line`,
   `replace_fact`, and `delete_file` all succeed on
   `org/o_1/system/policy.md`), so a later change can't wire the check into
   `core` by accident.
2. **The match is exact equality of the area segment with `"system"`.**
   There is no case folding, Unicode normalization, or prefix match on the
   segment, so `System`, `systems`, and Cyrillic, fullwidth, zero-width,
   no-break-space, and combining-mark look-alikes are ordinary writable
   areas. Section 3 asks for an exact string check. Rejected alternatives:
   normalizing, which would widen a hard rule into a fuzzy one, and a raw
   `"/system/" in path` substring test, which would also match a scope or
   entity ID named `system`.
3. **Only the area position counts.** A scope, entity ID, or file name called
   `system` is not restricted, because Section 3 restricts "the area named
   `system/`" within any scope.
4. **`check_not_system` takes only `path`.** It accepts no identity, role, or
   bypass argument, so no caller can be exempted. The role-gated check
   (AIE-1042) is separate and takes an identity. AIE-1042's composite
   `check_write(path, identity, policy)` calls `check_not_system` first, so
   the order is invalid path, then `system/`, then scope not granted, then
   role. Rejected alternative: a role-aware exemption, which contradicts
   "regardless of role".
5. **A malformed path raises `NotFoundError(path, INVALID_PATH)` before the
   `system/` check.** Approved by the human at spec review, 2026-09-30. This
   is the same error `core` gives, so a malformed path such as
   `u/e/system/x.txt` gets the recoverable error, and the corrected path then
   hits the permanent rejection. `is_system_path` never raises and returns
   False for malformed input, matching the predicate convention of
   `is_valid_path`. Rejected alternatives: running the read-only check first,
   and raising `ValueError` (the `paths` builders' convention), since this
   function receives agent-supplied paths, not values library code controls.
6. **No prefix-level check.** Approved by the human at spec review,
   2026-09-30. No `is_system_prefix` predicate is added, because no
   agent-facing operation writes by prefix, and the seeding job's prefix
   rewrite runs through `core`, which is unrestricted. Rejected alternative:
   shipping the predicate now. Adding one later does not change this
   interface.
7. **`scope` sits beside `core`, not inside it.** ARCHITECTURE.md's diagram
   edge `core --> scope` becomes `tools --> scope`, and the `scope` node
   moves out of the Core subgraph. `scope` imports only `errors` and `paths`,
   never `core` or `storage`, and `core` never imports `scope`. Tests assert
   both import directions by parsing the source with `ast`.

## Consequences

The tool layer has one exact, identity-free call that rejects every write to
`system/` with a permanent `RestrictedScopeError` naming the scope. No role
can bypass it, and a look-alike area name can't slip past or be falsely
caught.

Nothing is enforced yet. Until AIE-1044 wires the check into the tool layer,
no code in the library calls `check_not_system`, and `system/` can be written
through `core` by anyone holding a `MemoryStore`. That is intended for the
seeding job, which keeps writing `system/` through `core` with no extra
privilege, but it means the read-only guarantee holds only once every
mutating tool calls the check (directly or through AIE-1042's
`check_write`).

Because enforcement lives outside `core`, each new mutating tool must
remember to call the check. The import-boundary tests stop the check from
being moved into `core`, but they cannot detect a tool that forgets it;
AIE-1044's tests must cover that.

Reads and listings of `system/` are unaffected.
