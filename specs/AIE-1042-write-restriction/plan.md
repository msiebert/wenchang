# Implementation Plan: write-restriction enforcement for role-gated scopes

**Linear issue**: AIE-1042 | **Branch**: `AIE-1042-write-restriction` | **Date**: 2026-09-30 | **Spec**: [spec.md](spec.md)

## Summary

Change `RestrictedScopeError` to carry `required_roles: frozenset[str] |
None` and add `RestrictionReason.NOT_GRANTED`. Add `ScopePolicy`,
`check_write_allowed`, and `check_write` to `src/wenchang/scope.py`. All
checks are pure functions over an already-resolved `Identity`. Nothing is
wired into `MemoryStore` or any read path.

## Technical Context

Python ≥ 3.12; pytest (`unit` marker); pyright strict; ruff (line length
100). `wenchang.scope` imports `wenchang.errors`, `wenchang.identity`, and
`wenchang.paths` only. Nothing imports it yet. AIE-1044 will call
`check_write` from the tool layer.

**Dependencies, all landing first in milestone order:**

- AIE-1043: `Identity`, `ScopeGrant`, `identity.grants` (a read-only
  mapping, so `.get(scope)` is the non-raising lookup), and
  `paths.is_valid_segment`.
- AIE-1041: `paths.parse_path(path) -> PathParts(scope, entity_id, area,
  name)`, raising `ValueError` iff `not is_valid_path(path)`.
- AIE-1040: creates `src/wenchang/scope.py` with `SYSTEM_AREA`,
  `is_system_path`, and `check_not_system(path: str) -> None`. That function
  raises `NotFoundError(path, INVALID_PATH)` for a malformed path and
  `RestrictedScopeError(path, scope, SYSTEM_READ_ONLY)` when the area segment
  is exactly `"system"`. A scope named `"system"` is not restricted by it.

## Constitution Check

| Principle | Status |
| --------- | ------ |
| I. Tests-first | T1–T3 each test-writer → implementer |
| II. Tests not negotiable | `tests/test_errors.py` `RestrictedScopeError` / `RestrictionReason` expectations updated to the new spec text (spec Allow-test-changes). None deleted or skipped |
| IV. Strict typing | All signatures fully annotated |
| V. Storage only through interface | No storage access |
| VI. Spec fidelity | Matches Notion Sections 3, 5, 6, 9, 10.1. The not-granted check goes beyond the issue text and is recorded in ADR 0017 |
| VII. Architecture documented | Public error-type change, new public `scope` functions, and scope-enforcement rules → ADR 0017 and ARCHITECTURE.md. The ARCHITECTURE.md changes are the `errors` entry, the `scope` entry, the error-taxonomy Permanent bullet (add not-granted), and a new Key invariants bullet: writes are bound to the caller's granted scope and entity and gated by `ScopePolicy`. AIE-1040 owns the diagram edge change (`core --> scope` becomes `tools --> scope`), and this issue does not touch the diagram |
| VIII. Traceability | Each test docstring cites AIE-1042 and its scenario ID, e.g. `(AIE-1042, US3.2)` |
| IX. Small PR | Two modules, two test files |

**Decisions to record in ADR 0017:**

1. **Adopter configuration is `ScopePolicy(write_roles: Mapping[str,
   frozenset[str]])`**, mapping each write-restricted scope to the roles
   permitted to write it. Absent means unrestricted. A set, because Section 9
   permits more than one role (admin or owner). Rejected: a single required
   role per scope, which cannot express Section 9. Also rejected: a role
   hierarchy ("owner ≥ admin ≥ member"), since roles are opaque to the
   library and the adopter can list every permitted role. Scope names match
   the resolver's grant keys by exact string equality. A policy key that
   matches no resolver scope restricts nothing, so a misspelled or
   differently cased key fails open. Rejected: normalizing names, which the
   segment rule doesn't do anywhere else, and rejecting unknown keys, which
   isn't possible because the policy is built without an identity.
2. **`RestrictedScopeError` takes `required_roles: frozenset[str] | None`**,
   replacing `required_role: str | None`. The message lists the roles sorted,
   so it is deterministic. Rejected: keeping `required_role: str` and passing
   a pre-joined string (`"admin or owner"`), which loses structure a caller
   might inspect and puts rendering in every raise site. This is a breaking
   rename with no alias. Nothing outside `tests/test_errors.py` uses the old
   keyword.
3. **New `RestrictionReason.NOT_GRANTED`** for a write whose scope the caller
   has no grant for, or whose entity ID differs from the caller's entity ID
   in that scope. Without it, a caller with a permitted role in `org` could
   write into any other organization's prefix just by naming it: the role
   check alone does not bind a write to the resolved entity. Permanent, since
   retrying cannot succeed. Rejected: `NotFoundError(INVALID_PATH)`, which is
   recoverable and would invite the agent to probe other entities' paths.
4. **The two not-granted sub-cases share one reason and one message.** The
   agent's next action is the same, and a message distinguishing them would
   either need an extra constructor argument or reveal the caller's own
   entity ID. Rejected: two reasons (`SCOPE_NOT_GRANTED`,
   `ENTITY_MISMATCH`).
5. **Check order is invalid path → `system/` → not granted → role**, the first
   applicable error winning. `system/` first because it holds regardless of
   identity and gives the most specific reason. Not-granted before role, so a
   role message never implies that gaining a role would open another entity's
   prefix.
6. **Two entry points.** `check_write` is the one the tool layer calls.
   `check_write_allowed` (grant and role only) stays public so each check is
   testable on its own, and so an adopter's admin tooling can apply the role
   rules without the `system/` rule. The risk is that tool code calls
   `check_write_allowed` by mistake and skips the `system/` check. Its
   docstring says so explicitly, and AIE-1044 must call `check_write`.
7. **Enforcement lives in `scope`, called by the tool layer, not
   `MemoryStore`.** The seeding job and admin tooling write `system/` and
   restricted scopes through core. Wiring into tools is AIE-1044.
8. **Reads and listing are never checked**, per the issue text, including
   reads of ungranted scopes or entities. Read scoping, if any, belongs to
   the tool layer.
9. **Inputs are type-checked at runtime.** `ScopePolicy` may be built from a
   config file, as `Identity` may be built from resolver output (ADR 0014).
   So it raises `TypeError` on wrongly typed input rather than silently
   coercing it, and it accepts only `frozenset` role sets. For the same
   reason, `RestrictedScopeError` rejects a non-`frozenset` `required_roles`,
   since a leftover positional `"admin"` would otherwise render as
   `"a, d, i, m, n"`.
10. **`ScopePolicy` defines `__reduce__`**, as `Identity` does (ADR 0014
    decision 8), so `pickle` and `copy.deepcopy` round-trip through the
    constructor despite the `MappingProxyType` field. `dataclasses.asdict`
    is unsupported for the same reason as for `Identity`.
11. **Adversarial hardening.** An adversarial review of the finished code
    showed that `str` and `frozenset` subclasses could override methods to
    mislead the checks. The rules adopted:
    - `check_write` and `check_write_allowed` reject a non-`str` path with
      `TypeError`. They normalize a `str` path to an exact `str` with
      `str.__str__` before any parsing, so a subclass with a lying `split`
      or `__ne__` can't bypass the entity or `system/` checks.
    - `ScopePolicy` normalizes each scope key and role to an exact `str`.
      It stores only the normalized copies, runs the empty-set check on the
      normalized set, and rejects keys that collide after normalization.
    - Container types are checked by real type,
      `issubclass(type(x), frozenset)`, rather than `isinstance`, which
      consults a spoofable `__class__`.
    - `RestrictedScopeError` rejects non-`str` members of `required_roles`
      with `TypeError`.

    Rejected: trusting the annotated types. The policy may come from config
    and the path from an agent, and the check is a security boundary.

## Public interface

### `src/wenchang/errors.py`

```python
class RestrictionReason(StrEnum):
    """Why a scope is closed to the write the caller attempted."""

    SYSTEM_READ_ONLY = "system_read_only"
    ROLE_REQUIRED = "role_required"
    NOT_GRANTED = "not_granted"


class RestrictedScopeError(PermanentError):
    """A path falls within a scope the caller cannot write to."""

    def __init__(
        self,
        path: str,
        scope: str,
        reason: RestrictionReason,
        required_roles: frozenset[str] | None = None,
    ) -> None: ...
```

Attributes: `path`, `scope`, `reason`, and `required_roles`. `required_roles`
is a normalized copy, a plain `frozenset` of exact `str`, equal by value to
the argument.
The `required_role` attribute and keyword no longer exist.

Checked in this order, first failure wins:

| Condition | Raised |
| --------- | ------ |
| `required_roles is not None and not issubclass(type(required_roles), frozenset)` | `TypeError("required_roles must be a frozenset or None")` |
| any member of `required_roles` `not isinstance(member, str)` | `TypeError("required_roles must be a frozenset of str")` |
| `reason is ROLE_REQUIRED` and `required_roles` is `None` or empty | `ValueError("required_roles must be non-empty when reason is ROLE_REQUIRED")` |
| `reason is not ROLE_REQUIRED` and `required_roles is not None` | `ValueError("required_roles is only allowed when reason is ROLE_REQUIRED")` |

`detail` by reason (the message is `f"{detail} {PermanentError.guidance}"`,
as for every `WenchangError`):

| Reason | `detail` |
| ------ | -------- |
| `SYSTEM_READ_ONLY` | unchanged from today |
| `ROLE_REQUIRED` | `f"{path} is in scope {scope}; scope {scope} is role-gated and the caller lacks a permitted role ({roles})."` where `roles = ", ".join(sorted(required_roles))` |
| `NOT_GRANTED` | `f"{path} is in scope {scope}; the caller's identity does not include this entity in scope {scope}."` |

Tests should assert on attributes and on substrings (`"org"`, `"admin,
owner"`, the path), not the full detail string.

### `src/wenchang/scope.py`

```python
@dataclass(frozen=True)
class ScopePolicy:
    """The adopter's scope configuration: permitted writer roles per restricted scope.

    A scope absent from `write_roles` is unrestricted. Scope names match the
    resolver's grant keys by exact string equality; a key that matches no
    resolver scope restricts nothing.
    """

    write_roles: Mapping[str, frozenset[str]]

    def __reduce__(self) -> tuple[type["ScopePolicy"], tuple[dict[str, frozenset[str]]]]:
        return (ScopePolicy, (dict(self.write_roles),))

    def is_write_restricted(self, scope: str) -> bool:
        """True iff `scope` has an entry in `write_roles`."""

    def permitted_roles(self, scope: str) -> frozenset[str] | None:
        """The roles permitted to write `scope`, or None if it is unrestricted."""
```

- `__post_init__` runs these checks in this order and raises on the first
  failure. Check 1 runs once. Checks 2–7 run for each `(scope, roles)` entry
  in the mapping's iteration order, all of one entry's checks before the
  next entry's:

  | # | Condition | Raised |
  | - | --------- | ------ |
  | 1 | `not isinstance(write_roles, Mapping)` | `TypeError("write_roles must be a Mapping")` |
  | 2 | `not isinstance(scope, str)` | `TypeError(f"scope name must be a str: {scope!r}")` |
  | 3 | `not is_valid_segment(scope)`, on `scope = str.__str__(scope)` | `ValueError(f"invalid scope: {scope!r}")` |
  | 4 | `not issubclass(type(roles), frozenset)` | `TypeError(f"roles for scope {scope!r} must be a frozenset")` |
  | 5 | any role `not isinstance(role, str)` | `TypeError(f"roles for scope {scope!r} must be str")` |
  | 6 | `len(normalized) == 0`, where `normalized = frozenset(str.__str__(r) for r in roles)` | `ValueError(f"scope {scope!r} has no permitted roles")` |
  | 7 | `"" in normalized` | `ValueError(f"scope {scope!r} has an empty role")` |
  | 8 | normalized `scope` already seen | `ValueError(f"duplicate scope after normalization: {scope!r}")` |

  Each scope key and role is normalized to an exact `str`. The stored mapping
  holds only the normalized scopes and role sets, never the caller's objects.
  Check 6 runs on the normalized copy, so a `frozenset` subclass whose
  `__len__` lies can't pass it. Check 8 catches two `str`-subclass keys
  that normalize to the same scope.

  `Mapping` is `collections.abc.Mapping`. Check 4 accepts only `frozenset`,
  so a `set`, `list`, or `str` is rejected, and a `str` is never read as a
  set of characters. The messages in checks 5 and 7 don't name the role, so
  the result doesn't depend on the set's iteration order. Tests should match
  the exception type and a message prefix. As in `Identity`, bind the
  argument and its items as `object` first (e.g. `raw: object =
  self.write_roles` and `items: list[tuple[object, object]]`), so the runtime
  checks stay clean under pyright strict.
- `__reduce__` makes `pickle` and `copy.deepcopy` rebuild through the
  constructor, re-running validation (spec US1.9).

  Once every check passes, it stores `MappingProxyType(snapshot)`, the dict
  of normalized entries, via `object.__setattr__`. So `write_roles` is
  read-only (`TypeError` on item assignment) and independent of the caller's
  dict.
- `__eq__` is the dataclass default (proxies compare by content).
  `__hash__` is explicit: `hash(frozenset(self.write_roles.items()))`, as for
  `Identity`.
- No scope name is special-cased, including `"system"`.

```python
def check_write_allowed(path: str, identity: Identity, policy: ScopePolicy) -> None:
    """Raise unless `identity` may write `path` under `policy`.

    Checks that the path is well formed, that it lies under the caller's own
    entity in a granted scope, and that the caller's role there is permitted.
    Does not check the system/ area. Tool code must call check_write instead.
    """


def check_write(path: str, identity: Identity, policy: ScopePolicy) -> None:
    """Raise unless a mutating call on `path` may proceed.

    The tool layer calls this before every mutating call. Runs the system/
    check, then check_write_allowed.
    """
```

Errors, in check order (the first applicable one is raised):

| # | Condition | Raised | `check_write_allowed` | `check_write` |
| - | --------- | ------ | --------------------- | ------------- |
| 1 | `not is_valid_path(path)` | `NotFoundError(path, NotFoundReason.INVALID_PATH)` | yes | yes |
| 2 | `parse_path(path).area == SYSTEM_AREA` (via `check_not_system`) | `RestrictedScopeError(path, scope, SYSTEM_READ_ONLY)` | no | yes |
| 3 | `parts.scope not in identity.grants` | `RestrictedScopeError(path, scope, NOT_GRANTED)` | yes | yes |
| 3 | `identity.grants[parts.scope].entity_id != parts.entity_id` | `RestrictedScopeError(path, scope, NOT_GRANTED)` | yes | yes |
| 4 | `policy.permitted_roles(scope)` is a set not containing the caller's role | `RestrictedScopeError(path, scope, ROLE_REQUIRED, required_roles=that set)` | yes | yes |

A non-`str` path raises `TypeError` before row 1. A `str` subclass is
normalized to an exact `str` first, and the error's `path` is that exact
`str`. Neither function raises anything else for `str` input, and neither consults
storage or a resolver. `required_roles` on the error is the policy's own
frozenset (equal by value, identity not asserted).

### Algorithm

```text
check_write_allowed(path, identity, policy):
    if not isinstance(path, str): raise TypeError("path must be a str")
    path = str.__str__(path)        # exact str; a subclass's overrides are gone
    try: parts = parse_path(path)
    except ValueError: raise NotFoundError(path, INVALID_PATH) from None
    grant = identity.grants.get(parts.scope)
    if grant is None or grant.entity_id != parts.entity_id:
        raise RestrictedScopeError(path, parts.scope, NOT_GRANTED)
    permitted = policy.permitted_roles(parts.scope)
    if permitted is not None and grant.role not in permitted:
        raise RestrictedScopeError(path, parts.scope, ROLE_REQUIRED, required_roles=permitted)

check_write(path, identity, policy):
    if not isinstance(path, str): raise TypeError("path must be a str")
    path = str.__str__(path)
    check_not_system(path)          # raises INVALID_PATH first, then SYSTEM_READ_ONLY
    check_write_allowed(path, identity, policy)
```

### Worked examples

With the spec fixtures, `policy = ScopePolicy({"org": frozenset({"admin",
"owner"}), "team": frozenset({"admin"})})` and grants `{"user":
ScopeGrant("u-1", "member"), "org": ScopeGrant("o-9", "member"), "project":
ScopeGrant("p-3", "member")}`. The full precedence case list is spec US4.4.

| Call | Result |
| ---- | ------ |
| `check_write("project/p-3/notes/a.md", ...)` | `None` |
| `check_write("org/o-9/notes/a.md", ...)` | `ROLE_REQUIRED`, `required_roles={"admin","owner"}` |
| same, role `owner` in `org` | `None` |
| `check_write("org/o-8/notes/a.md", ...)` | `NOT_GRANTED` (not `ROLE_REQUIRED`) |
| `check_write("team/t-1/notes/a.md", ...)` | `NOT_GRANTED` |
| `check_write("project/p-3/system/a.md", ...)` | `SYSTEM_READ_ONLY` |
| `check_write_allowed("project/p-3/system/a.md", ...)` | `None` |
| `check_write("team/t-1/system/a.md", ...)` | `SYSTEM_READ_ONLY` |
| `check_write("org/o-9/notes", ...)` | `NotFoundError(INVALID_PATH)` |

## Test layout

- `tests/test_errors.py`: exactly the changes enumerated in the spec's
  Allow-test-changes line, plus new tests for US5.1–3. With the new
  `NOT_GRANTED` factory in `PERMANENT_ERROR_FACTORIES`, the existing
  permanent-guidance tests cover US5.5.
- `tests/test_scope_system.py`: only the one assertion change named in the
  spec's Allow-test-changes line.
- `tests/test_scope_write_restriction.py` (new, unit), module docstring
  citing AIE-1042: spec US1–US4. Builds `Identity` / `ScopeGrant` directly;
  no resolver or storage is needed. The US4.4 table is the parametrized
  case list, used verbatim, one row per case, run against both
  `check_write` and `check_write_allowed`. For each row returning `None`, the
  test also asserts the SC-001 property stated under the table. US1.7 is a
  parametrized `TypeError` table.
- Docstrings cite the issue and scenario, e.g. `(AIE-1042, US3.2)`.
- Pyright suppressions the tests need, each narrowly scoped to one line:
  - US1.2 item assignment on `policy.write_roles` needs
    `# pyright: ignore[reportIndexIssue]`.
  - The wrongly typed `ScopePolicy` arguments in US1.7 need
    `# pyright: ignore[reportArgumentType]`.
  - The wrongly typed `required_roles` in US5.2 needs
    `# pyright: ignore[reportArgumentType]`.

## Project Structure

```text
specs/AIE-1042-write-restriction/  spec.md plan.md tasks.md
src/wenchang/errors.py             # required_roles, NOT_GRANTED
src/wenchang/scope.py              # ScopePolicy, check_write_allowed, check_write
tests/test_errors.py
tests/test_scope_write_restriction.py
ARCHITECTURE.md                    # errors and scope entries, write-restriction invariant
docs/adr/0017-write-restriction-enforcement.md
```

## Complexity Tracking

None.
