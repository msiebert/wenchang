# Spec Review: AIE-1042 — write-restriction for role-gated scopes

## What & why

Section 3 lets an adopter mark scopes write-restricted, e.g. organization
writes limited to admin or owner. This adds `ScopePolicy`, which maps each
restricted scope to its permitted roles, and one pure check the tool layer
calls before every mutating call. That check is `check_write`: `system/`
check, then grant/entity, then role. A write outside the caller's own
resolved entity is also rejected, since a role check alone would let an
admin write into any org's prefix. Reads and `MemoryStore` are unchanged.

## Acceptance criteria

Policy `{"org": {"admin","owner"}, "team": {"admin"}}`. Caller: `org`→`o-9` as `member`, `project`→`p-3` as `member`, no `team` grant.

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | policy | `permitted_roles("org")` / `("project")` | `{"admin","owner"}` / `None` |
| 2 | bad scope name, empty role set, or `""` role | build `ScopePolicy` | `ValueError` |
| 2a | non-Mapping, non-str key, non-frozenset value (incl. `set`, `str`), non-str role | build `ScopePolicy` | `TypeError`, checks in fixed order |
| 3 | role `member` | write `org/o-9/...` | `ROLE_REQUIRED`, `required_roles={"admin","owner"}`, message "admin, owner" |
| 4 | role `admin` or `owner` | write `org/o-9/...` | `None` |
| 5 | any role | write `project/p-3/...` (unrestricted) | `None` |
| 6 | no `team` grant | write `team/t-1/...` | `NOT_GRANTED` |
| 7 | entity `p-3` | write `project/p-4/...` | `NOT_GRANTED`, message omits `p-3` |
| 8 | wrong entity and wrong role | write `org/o-8/...` | `NOT_GRANTED`, not `ROLE_REQUIRED` |
| 8a | no `org` grant, or `Identity({})` | write `org/o-9/...` / any path | `NOT_GRANTED`, `required_roles is None` |
| 8b | policy key `"Org"` | write `org/o-9/...` | `None`; keys match exactly |
| 8c | policy | `pickle` / `deepcopy` round-trip | equal policy |
| 9 | granted and permitted | `check_write("project/p-3/system/a.md")` | `SYSTEM_READ_ONLY` (`check_write_allowed` alone: `None`) |
| 10 | malformed path | either check | `NotFoundError(INVALID_PATH)` |
| 11 | several conditions at once | `check_write` / `check_write_allowed` | first of: invalid path → system → not granted → role; 11-row precedence table in spec US4.4 |
| 12 | `ROLE_REQUIRED` with no/empty roles, or other reason with roles | build error | `ValueError` |
| 12a | `required_roles` a `str`, a `set`, or a `frozenset` with a non-str member | build error | `TypeError`, checked first, by real type |
| 14 | non-`str` path | either check | `TypeError` |
| 15 | `str` subclass path with lying `split`/`__ne__` | either check | same result as the plain `str`; normalized via `str.__str__` |
| 16 | `frozenset` subclass whose `__len__` lies about being non-empty | build `ScopePolicy` | `ValueError`; emptiness checked on the normalized copy |
| 13 | `RestrictionReason` | enumerate | exactly `SYSTEM_READ_ONLY`, `ROLE_REQUIRED`, `NOT_GRANTED` |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| Restricted scope → set of permitted roles; absent = open | One required role; role hierarchy | Section 9 needs admin *or* owner; roles are opaque to the library |
| `required_roles: frozenset[str] \| None`, clean rename (**settled 2026-09-30**) | Pre-joined string; deprecated `required_role` alias | Keeps structure; only tests use the old keyword |
| Wrong scope or entity → permanent `NOT_GRANTED` (**settled 2026-09-30**) | Recoverable `NotFoundError`; no check | Role check alone doesn't bind a write to the caller's entity; retry can't succeed |
| One generic `NOT_GRANTED` message for both sub-cases (**settled 2026-09-30**) | Two reasons | Same next action; distinguishing would leak the caller's entity ID |
| Writes only; reads and listing unchecked (**settled 2026-09-30**) | Read check here | Issue text; read scoping belongs to the tool layer (AIE-1044) |
| Order: invalid → system → not granted → role | Role before grant | `system/` needs no identity; a role message shouldn't imply a role opens another entity |
| Check in `scope`, called by tools, not `MemoryStore` | Enforce in core | Seeding and admin tooling write through core |
| Runtime `TypeError` on wrongly typed policy or `required_roles`; `frozenset` only | Coerce with `frozenset(...)` | Policy may come from a config file; `"admin"` would become `{a,d,i,m,n}` |
| `ScopePolicy.__reduce__` for pickle/deepcopy | Leave unsupported | Same as `Identity` (ADR 0014) |
| Adversarial hardening: exact-`str` normalization of paths, scopes, roles; real-type container checks | Trust annotated types | Security boundary; subclasses could override `split`/`__ne__`/`__len__` to bypass checks |

## Files/modules to be touched

- `src/wenchang/errors.py` — `required_roles`, `NOT_GRANTED`
- `src/wenchang/scope.py` — `ScopePolicy`, `check_write_allowed`, `check_write` (module created by AIE-1040)
- `tests/test_errors.py` (updated `RestrictedScopeError`/`RestrictionReason` expectations), `tests/test_scope_system.py` (one vacuous `required_role` assertion becomes `required_roles is None`), `tests/test_scope_write_restriction.py` (new)
- `ARCHITECTURE.md`, `docs/adr/0017-write-restriction-enforcement.md`

## Open questions / assumptions

- None open. All four questions were settled on 2026-09-30 with the defaults above.
- Assumes AIE-1040, AIE-1041, and AIE-1043 land first.
- Assumes the tool layer (AIE-1044) calls `check_write` before `write_file`, `append_line`, `replace_fact`, and `delete_file`.

## Risks

- Nothing enforces anything until AIE-1044 wires `check_write` into the tools.
- The `required_role` rename breaks any out-of-tree caller. There are none today.
- Roles compare case-sensitively. An adopter whose resolver returns `Admin` against a policy of `admin` is denied.
- Scope names match by exact string equality with the resolver's grant keys. A policy key that matches no resolver scope restricts nothing, so a misspelled key fails open.
- `check_write_allowed` skips `system/`. Tool code must call `check_write`, and its docstring says so.
- For AIE-1044, the tool layer must normalize the path once, with an `isinstance` check then `str.__str__`. It must pass that same exact `str` to both `check_write` and storage, or a gap between what is checked and what is written reopens.
