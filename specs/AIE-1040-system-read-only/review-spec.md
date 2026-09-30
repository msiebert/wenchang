# Spec Review: AIE-1040 — read-only enforcement for `system/`

## What & why

Notion Section 3 says the `system/` area of every scope holds curated content
and is read-only to the agent, enforced at the tool layer by an exact path
check. This adds `wenchang.scope.check_not_system(path)`, which raises a
permanent `RestrictedScopeError(SYSTEM_READ_ONLY)` for any path whose area is
exactly `system`. It takes no identity, so no role bypasses it. Core is left
unrestricted so the seeding job can keep rewriting `system/`. Tools call it
directly or through AIE-1042's `check_write`. Wiring is AIE-1044.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| US1.1–3 | `user/u_42/system/policy.md`, any scope/entity/name under `system` | `check_not_system` | `RestrictedScopeError`, `scope` = first segment, permanent; `is_system_path` True |
| US1.4 | that error | `str(err)` | contains `scope user` and `read-only` |
| US1.5 | signature | inspect | only parameter is `path` |
| US2.1 | `user/u_42/preferences/editor.md` | check | `None`; `is_system_path` False |
| US2.2 | area `System`, `systems`, Cyrillic/fullwidth/zero-width/NBSP/combining look-alikes | check | `None`: exact match only |
| US2.3 | `system` as scope, entity ID, or name | check | `None` |
| US3.1 | every malformed path, incl. `u/e/system/x.txt`, `u/e/sys/tem/x.md` | check | `NotFoundError(INVALID_PATH)`, never restricted |
| US3.2 | malformed or odd strings | `is_system_path` | False, never raises |
| US4.1 | `MemoryStore`, `org/o_1/system/policy.md` | create, replace, append, replace_fact, delete | all succeed |
| Edge | every path above | both functions | raises restricted iff `is_system_path` |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| Standalone check called by tools, not `MemoryStore` | Guard in core with bypass flag or privileged store | Seeding writes `system/` through core; Section 3 puts enforcement at the tool layer |
| Exact equality of the area segment | Case folding, normalization, `"/system/" in path` | Section 3 demands an exact check; substring would hit scopes/entities named `system` |
| No identity argument | Role-aware exemption | "Regardless of role" is the point of the issue |
| Invalid path first → `INVALID_PATH` (**settled by human**) | Read-only first | Same error core gives |
| No `is_system_prefix` (**settled by human**) | Ship it now | Nothing writes by prefix; addable later |
| Recorded in ADR 0016 | — | AIE-1042 is ADR 0017 |

## Files/modules to be touched

- `src/wenchang/scope.py` (new; AIE-1042 adds to it)
- `tests/test_scope_system.py` (new)
- `ARCHITECTURE.md`, `docs/adr/0016-system-read-only-enforcement.md`

## Open questions / assumptions

- None open. Requires AIE-1041's `parse_path` on the base branch; T1 stops if absent.
- A scope literally named `system` is writable (Section 3 restricts the area).

## Risks

- Nothing calls the check until AIE-1044, so `system/` is unprotected until then.
- AIE-1042 renames `required_role`; tests check both names via `getattr` so either merge order passes.
