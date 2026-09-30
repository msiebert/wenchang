# PR Review: AIE-1040 — Read-only enforcement for the `system/` area

## What changed & why

Notion Section 3 makes the `system/` area of every scope read-only to the
agent, enforced at the tool layer by an exact check. This PR adds the new
module `src/wenchang/scope.py` with `SYSTEM_AREA`, `is_system_path(path)`, and
`check_not_system(path)`. The check raises a permanent
`RestrictedScopeError(SYSTEM_READ_ONLY)` naming the scope when the area segment
is exactly `system`. It takes no identity, so no role can bypass it.
`MemoryStore` is deliberately left unrestricted so the seeding job can keep
rewriting `system/` through `core`. Tools call the check directly or through
AIE-1042's `check_write`. Wiring it into the tools is AIE-1044. No existing
source or test file changes.

## Acceptance criteria → tests

All tests are in `tests/test_scope_system.py`.

| Acceptance criterion (Given/When/Then) | Test(s) |
| --------------------------------------- | ------- |
| US1.1: `user/u_42/system/policy.md` → `RestrictedScopeError`, `scope == "user"`, `SYSTEM_READ_ONLY`, permanent, no role; `is_system_path` True | `test_check_not_system_rejects_primary_path` |
| US1.2: `system` area under any scope/entity (incl. scope `system`) → rejected, `scope` = first segment | `test_check_not_system_rejects_any_scope_and_entity`, `test_valid_paths_system_entry_rejected` |
| US1.3: any valid name under `system` (`..md`, `a.md.md`) → rejected | `test_check_not_system_rejects_any_name` |
| US1.4: message names the scope and says read-only | `test_rejection_message_names_scope_and_read_only` |
| US1.5: only parameter is `path` | `test_check_not_system_takes_only_path` |
| US2.1: `user/u_42/preferences/editor.md` and every non-system `VALID_PATHS` entry → `None`, not system | `test_check_not_system_allows_primary_path`, `test_other_valid_paths_allowed` |
| US2.2: look-alike areas (case, suffix/prefix, Cyrillic, fullwidth, ZWSP, NBSP, combining mark) → `None` | `test_lookalike_areas_allowed` |
| US2.3: `system` as scope, entity ID, or name → `None` | `test_system_outside_area_position_allowed` |
| US3.1: every malformed path → `NotFoundError(INVALID_PATH)`, never `RestrictedScopeError`/`ValueError` | `test_malformed_path_raises_invalid_path` |
| US3.2: `is_system_path` False and never raises for malformed/odd input; emoji path valid and allowed | `test_is_system_path_false_for_malformed`, `test_emoji_path_allowed` |
| US4.1: `MemoryStore` create, replace, `append_line`, `replace_fact`, `delete_file` all succeed on `org/o_1/system/policy.md` | `test_core_accepts_system_paths_for_seeding` |
| Edge Cases: raises restricted iff `is_system_path`, repeatable, over every US1–US3 path | `test_check_raises_restricted_iff_is_system_path` |
| Edge Cases: a scope named `system` is not restricted | `test_scope_named_system_not_restricted` |
| FR-001: `SYSTEM_AREA == "system"` | `test_system_area_constant` |
| FR-002: `is_system_path` exact, never raises | `test_check_not_system_rejects_primary_path`, `test_lookalike_areas_allowed`, `test_is_system_path_false_for_malformed` |
| FR-003: `check_not_system` error order and results | `test_malformed_path_raises_invalid_path`, `test_check_not_system_rejects_primary_path`, `test_check_not_system_allows_primary_path` |
| FR-004: no identity/role/bypass argument | `test_check_not_system_takes_only_path` |
| FR-005: `MemoryStore` does not apply the check | `test_core_accepts_system_paths_for_seeding` |
| FR-006: `scope` imports neither `core` nor `storage`; `core` does not import `scope` | `test_scope_does_not_import_core_or_storage`, `test_core_does_not_import_scope` |

## Architecture / ADR changes

- New [ADR 0016](../../docs/adr/0016-system-read-only-enforcement.md): check
  at the tool layer rather than in `MemoryStore`, exact area equality, area
  position only, path-only signature, invalid path before read-only, no prefix
  check, and `scope` beside `core`.
- `ARCHITECTURE.md`: the **scope** module-map entry moves from planned to
  implemented (AIE-1042's role-gated check is still planned in the same
  module). The bird's-eye count goes from seven to eight modules. In the
  diagram, `scope` moves out of the Core subgraph and `core --> scope` becomes
  `tools --> scope`. The `system/` key invariant is reworded to name
  `scope.check_not_system` and the exact area match, and a new invariant
  records the import boundary between `scope` and `core`.
- `docs/product/glossary.md`: the "System area" entry names
  `scope.check_not_system` and notes that `core` does not apply it.

## Deviations from spec

- None.

## Look closely at

- `test_core_accepts_system_paths_for_seeding`: this is the pin that keeps
  seeding working. It runs every mutating `MemoryStore` operation on a
  `system/` path and fails if any raises `RestrictedScopeError`. Confirm it
  covers the full create → replace → append → replace_fact → delete sequence.
- Exact-equality near-miss coverage in `LOOKALIKE_AREAS` and
  `NON_AREA_SYSTEM_PATHS`. The Unicode look-alikes are built with `chr(...)`,
  so check that each one really is a distinct valid segment. The test asserts
  `is_valid_path` and `area != "system"` before checking the result.
- The AST import-boundary tests (`_imported_modules`, `_imports_any`). They
  catch `import x` and `from x import y` anywhere in the module, including
  inside functions. They do not catch dynamic `importlib` imports, which is
  acceptable for this boundary.
- `check_not_system` gets its malformed-path branch by catching `parse_path`'s
  `ValueError` rather than calling `is_valid_path` first. This matches
  plan.md because `parse_path` raises iff `not is_valid_path`.

## Follow-ups

- AIE-1042: add the role-gated check and the composite `check_write(path,
  identity, policy)` to `scope.py`, calling `check_not_system` first. It also
  renames `required_role`, and the tests here check both names.
- AIE-1044: wire the check into every mutating tool. Until then nothing
  calls it, so `system/` has no protection at the tool layer.
