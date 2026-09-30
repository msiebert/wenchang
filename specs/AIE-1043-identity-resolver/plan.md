# Implementation Plan: identity resolver interface

**Linear issue**: AIE-1043 | **Branch**: `AIE-1043-identity-resolver` | **Date**: 2026-09-30 | **Spec**: [spec.md](spec.md)

## Summary

Make `paths.is_valid_segment` public, then add `wenchang.identity`: three
frozen value types, a generic runtime-checkable `IdentityResolver` protocol,
`resolve_identity` (the only place the library calls a resolver), and
`SandboxResolver`. No other module changes behavior.

## Technical Context

Python ≥ 3.12 (PEP 695 generics); pytest; pyright strict; ruff (line length
100). `wenchang.identity` imports only `wenchang.errors` and
`wenchang.paths`. Nothing imports it yet. AIE-1041 path construction depends
on the public `is_valid_segment`. The AIE-1040/1042 checks in the planned
`scope` module will consume `Identity`.

## Constitution Check

| Principle | Status |
| --------- | ------ |
| I. Tests-first | T1, T2 each test-writer → implementer |
| IV. Strict typing | All signatures fully annotated. Generic protocol checked under pyright strict |
| V. Storage only through interface | Not touched |
| VI. Spec fidelity | Matches Notion Sections 6 and 10.1. The defensive catch of a raising resolver goes beyond the spec and is recorded in ADR 0014 |
| VII. Architecture documented | New public module and new public `paths` function → ARCHITECTURE.md + ADR 0014 |
| VIII. Traceability | Test docstrings reference AIE-1043 |

**Decisions to record in ADR 0014:**

1. The identity model is `Identity(grants: Mapping[str, ScopeGrant])`, one
   grant per scope carrying `entity_id` and `role`. Rejected: two parallel
   maps (scope → entity ID, scope → role), which can disagree on keys.
   `scope_map` still gives the plain scope → entity-ID shape the API uses.
2. Resolvers signal failure by returning `ResolutionFailure`, not by
   raising, per Section 10.1. Rejected: a resolver-raised exception type, which
   the spec calls out as turning degradation into a crash.
3. `resolve_identity` also catches any `Exception` a resolver raises, and any
   wrongly typed return, converting both to `ResolverFailureError`. The
   message names only the resolver class and the exception or return type,
   because the exception message may carry credentials. It is raised
   `from None`: `__cause__` is None and `__suppress_context__` is True, so
   standard traceback rendering omits the original exception. `__context__`
   still references it per Python semantics. Tests MUST NOT assert
   `__context__ is None`. A resolver that raises a `WenchangError`, including
   `ResolverFailureError`, gets the same treatment: the original is not passed
   through and its detail is not reused, since its message is equally
   untrusted. `BaseException`s that aren't `Exception`s propagate. Rejected: letting
   contract violations crash, since the whole point of the contract is clean
   degradation, and AIE-1039 checks conformance separately. Also rejected:
   chaining with `from exc`, which would aid debugging but let a credential
   in the original message reach logged tracebacks. Adopters debug their own
   resolver directly.
4. Identity values are validated at construction with the path segment rule
   (`is_valid_segment`, made public), so a resolver cannot hand back a scope
   name or entity ID that would produce a traversal or malformed path.
   Resolvers are adopter code that may be untyped, so construction also
   checks types at runtime. A non-`str` key, entity ID, or role, or a
   non-`ScopeGrant` value, raises `TypeError`. A well-typed but invalid value
   raises `ValueError`. Rejected: validating later in path construction only,
   which would surface a resolver bug as a path error far from its cause.
   Also rejected: trusting static types alone, since a `None` entity ID
   would otherwise crash inside `is_valid_segment` with an unrelated error.
5. `IdentityResolver` is generic in the credentials type (contravariant), so an
   adopter's resolver is typed against its own credential shape and the
   library never names one. `SandboxResolver.resolve` takes `object`, so it
   satisfies `IdentityResolver[C]` for every `C`.
6. `SandboxResolver` ships in this issue as the reference implementation.
   The protocol is otherwise untestable, and AIE-1039's conformance suite needs
   a known-good resolver to run against.
7. `identity` is a separate module from the planned `scope` module. Identity is
   the injected-dependency boundary. Enforcement consumes it. Enforcement is
   called by the tool layer, not `MemoryStore`, so the seeding job can still
   write `system/` through core.
8. `Identity` stores its grants as a `MappingProxyType`, which cannot be
   pickled, so `Identity` defines `__reduce__` to rebuild from a plain dict.
   Pickle and `copy.deepcopy` round-trip, re-running validation. As a
   consequence, `dataclasses.asdict(identity)` raises `TypeError`, because it
   deep-copies the mappingproxy field without calling `__reduce__`. That is
   acceptable: nothing in the library serializes identities by field, and
   `scope_map` or `dict(identity.grants)` give the plain shapes. Rejected:
   storing a plain dict, which would let callers mutate a frozen value.
9. **Adversarial hardening.** Resolvers are untrusted adopter code, so the
   value types and `resolve_identity` do not trust the objects they receive:
   - `Identity` reads `grants` once (`snapshot = dict(grants)`) and validates
     and stores that snapshot. A `Mapping` whose `items()` disagrees with
     `keys()` / `__getitem__` cannot pass validation with one view and store
     the other.
   - Every `str` value is normalized to an exact `str` via
     `str.__str__(value)` before validation and storage. This covers scope
     names, `entity_id`, `role`, and `ResolutionFailure.detail`. A `str`
     subclass overriding `__eq__`, `__contains__`, `split`, and the like
     cannot defeat the segment rule, and nothing downstream ever holds one.
     Two keys that normalize to the same string raise `ValueError` rather
     than silently dropping a grant.
   - `ResolutionFailure` checks `detail` is a `str` (`TypeError`), like the
     other fields.
   - `resolve_identity` type-tests the result with `issubclass(type(result),
     ...)`, which never consults the object's `__class__`, unlike
     `isinstance`. It builds every failure detail inside a guard, so an
     exception raised by a resolver-supplied object or type, e.g. from
     `__name__` or `__format__`, cannot escape.
   - `Identity.__reduce__` returns `type(self)`, so subclasses survive pickle
     and deepcopy.

## Public interface

### `src/wenchang/paths.py`

```python
def is_valid_segment(segment: str) -> bool:
    """Return True iff segment is one valid path segment.

    Non-empty, not "." or "..", and no "/", backslash, or Unicode control
    character. Never raises for any str input.
    """
```

This is the existing `_is_valid_segment`, renamed. `is_valid_path` and
`is_valid_prefix` call it. Note that the existing check does not reject `/`
because it is only ever applied to already-split segments. **The public
function must also return False for any segment containing `/`**, since
`Identity` passes unsplit strings. That addition does not change
`is_valid_path` or `is_valid_prefix`, which never pass a `/`.

### `src/wenchang/identity.py`

```python
@dataclass(frozen=True)
class ScopeGrant:
    """The caller's entity ID and role within one scope."""

    entity_id: str
    role: str
```

`__post_init__`, in order: bind each field as `object`. A non-`str`
`entity_id` or `role` raises `TypeError`. Each is normalized with
`str.__str__(value)` and stored back via `object.__setattr__`. Then `not
is_valid_segment(entity_id)` raises `ValueError`, and `role == ""` raises
`ValueError`, both checked on the normalized values. Hashable and equal by
value (dataclass default).

```python
@dataclass(frozen=True)
class Identity:
    """What a resolver returns: the caller's grant in each scope it can reach."""

    grants: Mapping[str, ScopeGrant]

    @property
    def scope_map(self) -> dict[str, str]:
        """Scope name → entity ID, as a new dict on each call."""

    def entity_id(self, scope: str) -> str:
        """The caller's entity ID in `scope`. Raises KeyError if not granted."""

    def role(self, scope: str) -> str:
        """The caller's role in `scope`. Raises KeyError if not granted."""

    def __reduce__(self) -> tuple[type["Identity"], tuple[dict[str, ScopeGrant]]]:
        return (type(self), (dict(self.grants),))
```

- `__post_init__` first rejects a non-`Mapping` `grants` with `TypeError`.
  It then takes one snapshot, `snapshot: dict[object, object] =
  dict(self.grants)`, and never reads `self.grants` again. It iterates the
  snapshot's items. For each item, a non-`str` key raises `TypeError`. The
  key is normalized with `str.__str__(key)`, and a normalized key failing
  `is_valid_segment` raises `ValueError`, as does a normalized key already
  seen. A value that is not a `ScopeGrant` raises `TypeError`, checked with
  `issubclass(type(value), ScopeGrant)`. The first failure wins. It then
  stores `MappingProxyType` over the normalized dict via
  `object.__setattr__`. So `identity.grants` is read-only (`TypeError` on
  item assignment) and independent of the caller's mapping.
- `__reduce__` makes `pickle` and `copy.deepcopy` rebuild through the
  constructor of the instance's own class (verified for `Identity`), so a
  module-level subclass keeps its type. `dataclasses.asdict` is unsupported
  (ADR decision 8).
- `__eq__` is the dataclass default. It compares the proxies, which compare
  by content, so insertion order does not matter.
- `__hash__` is defined explicitly as `hash(frozenset(self.grants.items()))`.
  The dataclass decorator keeps an explicit `__hash__` (verified).
- `"scope" in identity.grants` and `identity.grants.get(scope)` are the
  non-raising lookups for later issues.

```python
@dataclass(frozen=True)
class ResolutionFailure:
    """A resolver's report that credentials could not be resolved.

    `detail` is shown to the agent and must never contain credentials.
    """

    detail: str
```

`__post_init__`: a non-`str` `detail` raises `TypeError`. It is normalized
with `str.__str__(detail)` and stored back via `object.__setattr__`. Then
`detail == ""` raises `ValueError`. The no-credentials rule is documented,
not enforced.

```python
@runtime_checkable
class IdentityResolver[C](Protocol):
    """Turns caller credentials into an Identity. Injected by the adopter."""

    def resolve(self, credentials: C) -> Identity | ResolutionFailure:
        """Resolve `credentials`.

        Must not raise: report bad or unverifiable credentials as a
        ResolutionFailure. Identical credentials must give an equal result
        within a session.
        """
        ...
```

`C` is inferred contravariant. `runtime_checkable` checks only that a
`resolve` attribute exists.

```python
def resolve_identity[C](resolver: IdentityResolver[C], credentials: C) -> Identity:
    """Resolve `credentials` with `resolver`, raising ResolverFailureError on failure."""
```

| Resolver outcome | Result |
| ---------------- | ------ |
| returns `Identity` | that same object returned |
| returns `ResolutionFailure(d)` | `ResolverFailureError(d)` |
| returns a `ResolutionFailure` subclass whose `detail` raises when read or formatted | `ResolverFailureError(f"Resolver {name} returned an invalid ResolutionFailure.")` raised `from None` |
| raises `exc`, an `Exception` | `ResolverFailureError(f"Resolver {type(resolver).__name__} raised {type(exc).__name__}.")` raised `from None` |
| returns anything else, `r` | `ResolverFailureError(f"Resolver {type(resolver).__name__} returned {type(r).__name__}, not Identity or ResolutionFailure.")` |
| raises a non-`Exception` `BaseException` | propagates unchanged |

`ResolverFailureError.detail` is the full message, starting with the string
passed in. Tests should assert `startswith` on it, or that the class and type
names appear and a secret does not.

Type names in these details come from a guarded helper, `_type_name(t:
type) -> str`. It returns `str.__str__(t.__name__)`, or `"<unnamed>"` if
that raises any `Exception`, including a non-`str` `__name__`. The resolver's
own type name is read the same way. So the message format above is fixed
and nothing a resolver supplies can raise while it is built.

Algorithm:

```text
try: result = cast(object, resolver.resolve(credentials))
except Exception as exc: raise ResolverFailureError(<raised detail>) from None
if issubclass(type(result), Identity): return cast(Identity, result)
if issubclass(type(result), ResolutionFailure):
    raise ResolverFailureError(cast(ResolutionFailure, result).detail)
raise ResolverFailureError(<returned detail>)
```

`issubclass(type(result), ...)` never consults `result.__class__`. `isinstance`
does, so a `__class__` property that raises would escape. The returned object
is still the one the resolver built, unchanged.

Bind `result = cast(object, resolver.resolve(credentials))`. Without the
widening, pyright strict reports the second `isinstance` as
`reportUnnecessaryIsInstance`, which fails `make typecheck`. With the
`issubclass(type(result), ...)` form, pyright strict does not narrow `result`
at all (verified). So each branch casts explicitly, as shown above. Without
the casts, strict mode reports `reportReturnType` and
`reportAttributeAccessIssue`. A declared
annotation (`result: object = resolver.resolve(credentials)`) does not
widen: pyright narrows the variable to the assigned value's declared type
on assignment, so the error remains (verified during implementation). The
`except Exception` clause catches `WenchangError` subclasses like any other
exception (spec US3.6).

```python
class SandboxResolver:
    """Returns one fixed Identity for any credentials. For sandboxes and tests."""

    def __init__(self, identity: Identity) -> None: ...

    def resolve(self, credentials: object) -> Identity: ...
```

## Test layout

- `tests/test_paths.py`: add `is_valid_segment` cases (US2.5–6), including `/`,
  and confirm existing path/prefix tests still pass unchanged.
- `tests/test_identity.py` (new, unit): US1, US2.1–4, US2.7–9, US3, US4.
  Resolver doubles are small local classes: one returning a fixed value, one
  raising `RuntimeError("secret-token-xyz")`, one raising
  `ResolverFailureError("x")`, one returning `None`, one raising
  `KeyboardInterrupt`.
- The None-returning double declares `def resolve(self, credentials: object)
  -> Identity | ResolutionFailure` and returns
  `None  # pyright: ignore[reportReturnType]`. For US4.2, bind
  `candidate: object = SandboxResolver(identity)` before the `isinstance`
  check.
- The US2.7–9 `TypeError` cases pass wrongly typed arguments on purpose. Each
  gets a narrow `# pyright: ignore[reportArgumentType]`.

## Project Structure

```text
specs/AIE-1043-identity-resolver/   spec.md plan.md tasks.md review-spec.md
src/wenchang/paths.py               # is_valid_segment made public, rejects "/"
src/wenchang/identity.py            # new
tests/test_paths.py
tests/test_identity.py              # new
ARCHITECTURE.md
docs/adr/0014-identity-resolver.md  # new
```

ARCHITECTURE.md updates (doc-updater, after T2):

1. The **paths** entry documents the public `is_valid_segment` and its rule,
   including that it rejects `/`.
2. The **scope / identity (planned)** entry is split. A new implemented
   **identity** entry covers the value types, the protocol, `resolve_identity`,
   and `SandboxResolver`.
3. A **scope (planned)** entry keeps path construction and write-restriction /
   `system/` enforcement, noting that it consumes `Identity` and is called by
   the tool layer, not `MemoryStore`.

## Resolved questions

- Transient resolver failures: permanent-only, per Section 10.1. A transient
  variant could be added to `ResolutionFailure` later without breaking the
  protocol.
- Exception chaining: `from None` (human decision, 2026-09-30).
- Sandbox constants: supplied by the adopter at construction.

## Complexity Tracking

None.
