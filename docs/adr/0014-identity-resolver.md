# 0014. Identity resolver interface

Date: 2026-09-30

## Status

Accepted

## Context

The Notion spec (Section 6) says the library has no notion of users,
organizations, or roles. It consumes an adopter-injected resolver that turns
caller credentials into a map of scope name to entity ID plus the caller's
role in each scope. A sandbox resolver returns hardcoded constants; a
production resolver performs a real permission check. Section 10.1
("Resolver conformance") adds that a resolver never raises on bad
credentials: it returns a resolution failure, which the library converts
into the permanent-category `ResolverFailureError`, and it is consistent
within a session.

AIE-1043 defines that boundary so path construction (AIE-1041), `system/`
read-only enforcement (AIE-1040), role-gated write restriction (AIE-1042),
and the resolver conformance suite (AIE-1039) have a concrete type to build
on. Nothing calls it yet; wiring into transport and tools is later work.

## Decision

Add `wenchang.identity` (importing only `wenchang.errors` and
`wenchang.paths`) and make `paths.is_valid_segment` public.

1. **One grant per scope.** The identity model is
   `Identity(grants: Mapping[str, ScopeGrant])`, each `ScopeGrant` carrying
   `entity_id` and `role`. `scope_map` still gives the plain scope →
   entity-ID shape the API uses.
   - **Rejected: two parallel maps** (scope → entity ID, scope → role),
     which can disagree on keys.
2. **Resolvers report failure by returning `ResolutionFailure`**, not by
   raising, per Section 10.1. Every failure is permanent; there is no
   transient resolver outcome, so a production resolver whose own auth
   backend is briefly down still reports `ResolutionFailure`. Approved by
   the human at spec review on 2026-09-30.
   - **Rejected: a resolver-raised exception type**, which the spec calls
     out as turning degradation into a crash.
   - **Rejected: a transient variant.** It can be added to
     `ResolutionFailure` later without breaking the protocol.
3. **`resolve_identity` also converts a raised `Exception` and a wrongly
   typed return into `ResolverFailureError`**, going beyond the spec's
   contract so even a buggy resolver degrades cleanly. The message names
   only the resolver class and the exception or return type, because an
   exception message may carry credentials. The error is raised
   `from None`: `__cause__` is `None` and `__suppress_context__` is `True`,
   so standard traceback rendering omits the original exception, though
   `__context__` still references it per Python semantics. A raised
   `WenchangError`, including `ResolverFailureError`, gets the same
   treatment; the original is not passed through and its detail is not
   reused, since its message is equally untrusted. A `BaseException` that
   is not an `Exception` (`KeyboardInterrupt`, `SystemExit`) propagates
   unchanged. No chaining was approved by the human at spec review on
   2026-09-30.
   - **Rejected: letting contract violations crash.** The point of the
     contract is clean degradation, and AIE-1039 checks conformance
     separately.
   - **Rejected: chaining with `from exc`.** It would aid debugging but let
     a credential in the original message reach logged tracebacks. Adopters
     debug their own resolver directly.
4. **Identity values are validated at construction with the path segment
   rule.** Scope names and entity IDs must pass `is_valid_segment`
   (non-empty, not `.` or `..`, no `/`, backslash, or Unicode `Cc`
   character), so a resolver cannot hand back a value that produces a
   traversal or malformed path. The public function adds the `/` rejection,
   which does not change `is_valid_path` or `is_valid_prefix` since they
   only pass already-split segments. Because resolvers are adopter code that
   may be untyped, construction also checks types at runtime: a non-`str`
   key, entity ID, or role, or a non-`ScopeGrant` value, raises
   `TypeError`; a well-typed but invalid value (or an empty role) raises
   `ValueError`.
   - **Rejected: validating only in path construction**, which would
     surface a resolver bug as a path error far from its cause.
   - **Rejected: trusting static types alone**, since a `None` entity ID
     would otherwise crash inside `is_valid_segment` with an unrelated
     error.
5. **`IdentityResolver[C]` is a runtime-checkable `Protocol`, generic and
   (inferred) contravariant in the credentials type**, so an adopter's
   resolver is typed against its own credential shape and the library never
   names one. `SandboxResolver.resolve` takes `object`, so it satisfies
   `IdentityResolver[C]` for every `C`.
   - **Rejected: a fixed credential type** (e.g. `str` or a mapping), which
     would force adopters to encode their credentials into the library's
     shape.
6. **`SandboxResolver` ships now as the reference implementation**, with
   the identity it returns supplied by the adopter at construction. The
   protocol is otherwise untestable, and AIE-1039's conformance suite needs
   a known-good resolver. Adopter-supplied identity approved by the human at
   spec review on 2026-09-30.
   - **Rejected: built-in default scopes** baked into the library, which
     has no notion of which scopes an adopter defines.
7. **`identity` is a separate module from the planned `scope` module.**
   Identity is the injected-dependency boundary; enforcement consumes it.
   Enforcement is called by the tool layer, not `MemoryStore`, so the
   seeding job can still write `system/` through `core`.
   - **Rejected: one combined scope / identity module**, which would mix the
     adopter-facing contract with library-internal policy.
8. **`Identity` stores its grants as a `MappingProxyType` and defines
   `__reduce__`** to rebuild from a plain dict, since a mappingproxy cannot
   be pickled. `pickle` and `copy.deepcopy` round-trip through the
   constructor, re-running validation. `__hash__` is explicit
   (`hash(frozenset(grants.items()))`); equality is the dataclass default,
   which compares proxies by content, so insertion order does not matter.
   As a consequence `dataclasses.asdict(identity)` raises `TypeError`,
   which is acceptable: nothing serializes identities by field, and
   `scope_map` or `dict(identity.grants)` give the plain shapes.
   - **Rejected: storing a plain dict**, which would let callers mutate a
     frozen value.
9. **Adversarial hardening.** An adversarial code review showed that a
   resolver, as untrusted adopter code, can hand back objects that defeat
   naive checks. The value types and `resolve_identity` therefore trust
   nothing about the objects they receive:
   - **`Identity` snapshots the caller's mapping exactly once.** A
     non-`Mapping` `grants` raises `TypeError`; otherwise `dict(grants)` is
     taken once and that snapshot is what is validated and stored. A
     `Mapping` whose `items()`, `keys()`, and `__getitem__` disagree cannot
     pass validation through one view and store another. Grant values are
     type-tested with `issubclass(type(grant), ScopeGrant)`, so an object
     spoofing `__class__` as `ScopeGrant` raises `TypeError`. Two keys that
     normalize to the same string (e.g. `"a"` and a `str` subclass `"a"`)
     raise `ValueError` ("duplicate scope after normalization") rather than
     one grant being silently dropped.
   - **Every `str`-typed value is normalized to an exact `str`** via
     `str.__str__` before validation and storage: scope keys, `entity_id`,
     `role`, and `ResolutionFailure.detail`. A `str` subclass overriding
     `__contains__`, `__format__`, or similar cannot defeat the segment
     rule, and no stored value is ever a subclass instance.
   - **`ResolutionFailure` rejects a non-`str` `detail` with `TypeError`**,
     matching the other fields.
   - **`resolve_identity` type-tests with `issubclass(type(result), ...)`**
     rather than `isinstance`, which consults the object's own
     (resolver-controlled) `__class__`. The `ResolverFailureError` for a
     returned `ResolutionFailure` is built inside a guard; if reading or
     formatting `detail` raises, it falls back to `"Resolver {name} returned
     an invalid ResolutionFailure."`. Every type name in the
     messages (the resolver's class, a raised exception's type, and a
     wrongly typed return's type) is read through a private
     `_type_name` helper that normalizes with `str.__str__` and falls back
     to `"<unnamed>"` if a metaclass makes `__name__` raise. So a returned
     object's `__class__`, `detail`, or `__format__`, or a type's
     `__name__`, cannot raise out of `resolve_identity`.
   - **`Identity.__reduce__` returns `type(self)`**, so a subclass survives
     `pickle` and `copy.deepcopy` as the same subclass.
   - **Rejected: rejecting `str` subclasses outright.** Benign subclasses
     (e.g. enum-like or typed-string wrappers) are legitimate adopter
     values; normalizing accepts them while removing any overridden
     behavior.
   - **Rejected: leaving contrived cases unhandled.** Each fix is a few
     lines, and the module's guarantee that any `Identity` is safe to
     splice into a path, and that `resolve_identity` only ever yields an
     `Identity` or `ResolverFailureError`, should not depend on resolvers
     being well-behaved.

## Consequences

Later issues have one concrete, validated `Identity` to build paths from and
check roles against, and one call site (`resolve_identity`) whose outcomes
are exactly an `Identity` or a permanent `ResolverFailureError`, except a
non-`Exception` `BaseException`. Any `Identity` is safe to splice into a
memory path segment by construction, even from a hostile `Mapping` or `str`
subclass, and every stored string is an exact `str`. A returned object's
`__class__`, `detail`, or `__format__`, or the `__name__` of the resolver's, a raised exception's, or a returned
type, cannot raise out of `resolve_identity`; such a type is reported
as `<unnamed>`. `Identity` subclasses keep their type across `pickle`
and `copy.deepcopy`. A resolver's auth-backend outage makes
memory unavailable for the whole session with "do not retry" guidance; a
transient outcome would need a later, additive change. Without exception
chaining, a crashing resolver surfaces only its class and exception type, so
adopters debug it directly. Session consistency is a resolver contract left
to the AIE-1039 conformance suite; the library does not cache or verify it.
`dataclasses.asdict` does not work on `Identity`.
