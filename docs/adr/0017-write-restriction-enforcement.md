# 0017. Write-restriction enforcement for role-gated scopes

Date: 2026-09-30

## Status

Accepted

## Context

Notion Section 3 lets an adopter mark scopes as write-restricted. It is the
only scope property the library understands, and no scope name is
special-cased. Section 9's reference adopter limits organization writes to
admin *or* owner. Section 10.1 has the resolver return the roles the scope
configuration refers to. Section 6 says tool code uses the resolver's
fields to check write eligibility and to build the path prefix. Section 5
says a restricted-scope write is permanent, with an error naming the scope
and the reason.

AIE-1042 asks that writes be rejected unless the caller's resolved role for
the scope permits writing, and that reads be unaffected. The pieces it
builds on already exist: `Identity` and `ScopeGrant` (ADR 0014),
`parse_path` (ADR 0015), and `check_not_system` in `wenchang.scope` (ADR
0016). `RestrictedScopeError` carried a single `required_role: str | None`,
which can't express "admin or owner".

A role check alone has a gap. A caller whose role in `org` is permitted
could write into any other organization's prefix just by naming it, because
nothing ties the path's entity ID to the caller's grant.

## Decision

Add `ScopePolicy`, `check_write_allowed`, and `check_write` to
`src/wenchang/scope.py`. Change `RestrictedScopeError` to carry
`required_roles: frozenset[str] | None` and add `RestrictionReason.NOT_GRANTED`.
Nothing is wired into `MemoryStore` or any read path.

1. **Adopter configuration is `ScopePolicy(write_roles: Mapping[str,
   frozenset[str]])`.** It maps each write-restricted scope to the roles
   permitted to write it, and a scope that isn't listed is unrestricted. The
   value is a set because Section 9 permits more than one role. Scope names
   match the resolver's grant keys by exact string equality, so a key that
   matches no resolver scope restricts nothing. Rejected alternatives:
   - A single required role per scope, which can't express Section 9.
   - A role hierarchy ("owner ≥ admin ≥ member"). Roles are opaque to the
     library, and the adopter can list every permitted role.
   - Normalizing scope names. The segment rule doesn't normalize anywhere
     else.
   - Rejecting unknown keys. This isn't possible, because the policy is
     built without an identity.
2. **`RestrictedScopeError` takes `required_roles: frozenset[str] | None`,
   replacing `required_role: str | None`.** The message lists the roles
   sorted, so it is deterministic. The rename is clean, with no alias for
   the old keyword or attribute. Approved by the human at spec review,
   2026-09-30. Nothing outside `tests/test_errors.py` used the old name.
   Rejected alternatives: keeping `required_role: str` and passing a
   pre-joined string such as `"admin or owner"`, which loses structure a
   caller might inspect and puts rendering in every raise site; and a
   deprecated `required_role` alias.
3. **New permanent `RestrictionReason.NOT_GRANTED`** covers a write whose
   scope the caller has no grant for, or whose entity ID differs from the
   caller's entity ID in that scope. The reason applies whether or not the
   scope is restricted. It closes the gap described above: a permitted role
   no longer opens another entity's prefix. It is permanent because
   retrying the same call can't succeed. Approved by the human at spec
   review, 2026-09-30. Rejected alternatives: recoverable
   `NotFoundError(INVALID_PATH)`, which would invite the agent to probe
   other entities' paths; and no grant check at all.
4. **Both not-granted sub-cases share one reason and one generic message**:
   "`{path}` is in scope `{scope}`; the caller's identity does not include
   this entity in scope `{scope}`." Approved by the human at spec review,
   2026-09-30. The agent's next action is the same in both cases. A message
   that told them apart would need an extra constructor argument or would
   reveal the caller's own entity ID. The message never echoes the caller's
   entity ID or role. Rejected alternative: two reasons,
   `SCOPE_NOT_GRANTED` and `ENTITY_MISMATCH`.
5. **Check order is invalid path → `system/` → not granted → role**, and
   the first applicable error wins. `system/` goes first because it holds
   regardless of identity and gives the most specific reason. Not-granted
   goes before role so that a role message never implies that gaining a
   role would open another entity's prefix. Rejected alternative: role
   before grant.
6. **Two entry points.** `check_write` (`check_not_system`, then
   `check_write_allowed`) is the one the tool layer calls before every
   mutating call. `check_write_allowed` (grant and role only) stays public
   for two reasons: each check can be tested on its own, and an adopter's
   admin tooling can apply the role rules without the `system/` rule. Its
   docstring says tool code must call `check_write` instead.
7. **Enforcement lives in `scope`, called by the tool layer, not in
   `MemoryStore`.** The seeding job and admin tooling write `system/` and
   restricted scopes through core. Wiring into the tools is AIE-1044.
   Rejected alternative: enforcing in core.
8. **Only writes are checked. Reads and listing are never checked**, as the
   issue text says. This includes reads of ungranted scopes or entities.
   Approved by the human at spec review, 2026-09-30. Read scoping, if any,
   belongs to the tool layer. Rejected alternative: a read check here.
9. **Inputs are type-checked at runtime.** `ScopePolicy` may be built from a
   config file, as `Identity` may be built from resolver output (ADR 0014).
   So it raises `TypeError` on wrongly typed input instead of coercing it,
   and it accepts only `frozenset` role sets. The checks run in a fixed
   order: non-`Mapping`, then per entry: scope type, scope segment
   validity, role-set type, empty role set, role type, empty role, and a
   scope duplicated after `str` normalization. For the same reason,
   `RestrictedScopeError` rejects a non-`frozenset` `required_roles` with
   `TypeError` before its `ValueError` checks. Otherwise a leftover
   positional `"admin"` would render as `a, d, i, m, n`. Rejected
   alternative: coercing with `frozenset(...)`.
10. **`ScopePolicy` defines `__reduce__`**, as `Identity` does (ADR 0014
    decision 8). This lets `pickle` and `copy.deepcopy` rebuild the policy
    through the constructor, re-running validation, even though the field
    is a `MappingProxyType`. `dataclasses.asdict` is unsupported for the
    same reason as for `Identity`. Rejected alternative: leaving pickling
    unsupported.
11. **Adversarial hardening.** An adversarial review of the finished code
    found that `str` and `frozenset` subclasses could override methods to
    mislead the checks. For example, a path `str` subclass whose `split()`
    yields segments with an always-`False` `__ne__` passed the entity
    comparison for another entity's path. A path whose `split()` changes
    between calls could report `notes/` to the `system/` check and a
    different area later. Python callers of the tool layer are untyped at
    runtime, so the annotations don't prevent this. The rules adopted:
    - `check_not_system`, `check_write_allowed`, and `check_write` reject a
      non-`str` path with `TypeError`. They normalize a `str` path to an
      exact `str` with `str.__str__` at entry, before any parsing.
      `check_write` normalizes once and passes that same exact `str` to both
      sub-checks. `is_system_path` returns False for a non-`str`.
    - `ScopePolicy` normalizes each scope key and role to an exact `str`.
      It copies each role set into a real `frozenset` before validating, so
      a lying `__len__` or `__iter__` can't store an empty set. It stores
      only the normalized copies and rejects keys that collide after
      normalization.
    - Container types are checked by real type,
      `issubclass(type(x), frozenset)`, instead of `isinstance`, which
      consults a spoofable `__class__`.
    - `RestrictedScopeError` rejects non-`str` members of `required_roles`
      with `TypeError`, and stores a plain `frozenset` of exact `str`s.

    Rejected alternative: trusting the annotated types, in particular
    trusting that JSON-sourced paths are always exact `str`. That holds for
    today's JSON decoders, but the check is a security boundary, the policy
    may come from config, and any in-process caller can pass a subclass.

    The check only covers the value it saw. A tool that validates one object
    and then passes a different object (or the original subclass) to
    storage reopens the gap, so AIE-1044 must pass storage the same exact
    `str` the check validated.

## Consequences

The tool layer gets one call, `check_write(path, identity, policy)`. It
guarantees that an accepted write lies under the caller's own entity in a
granted scope, outside `system/`, and, in a restricted scope, is made with
a permitted role.

Nothing is enforced yet. Until AIE-1044 wires `check_write` into
`write_file`, `append_line`, `replace_fact`, and `delete_file`, no library
code calls it. Anyone holding a `MemoryStore` can write any scope. As with
ADR 0016, each mutating tool must remember to call the check, and
AIE-1044's tests must cover that. The risk that tool code calls
`check_write_allowed` by mistake and skips `system/` is mitigated only by
its docstring and by review.

Renaming `required_role` to `required_roles` is a breaking change to the
public API of `wenchang.errors`: the old keyword and attribute are gone.
There are no external callers today, and the only in-repo uses were in
`tests/test_errors.py`, which was updated as the spec's Allow-test-changes
list permits.

Role matching is exact and case-sensitive, with no hierarchy. An adopter
whose resolver returns `Admin` against a policy of `admin` is denied, and
must list every permitted role explicitly. Scope-name matching fails open
instead: a policy key that doesn't exactly equal the resolver's scope name
restricts nothing, so adopters must use the resolver's exact scope names.

An identity with no grants can write nothing, and a restricted scope is
always decidable: an ungranted scope is `NOT_GRANTED` and never falls
through to the role check.
