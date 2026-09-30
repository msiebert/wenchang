# Spec Review: AIE-1043 — identity resolver interface

## What & why

The library has no notion of users or roles (Notion Section 6). It asks an
adopter-injected resolver who the caller is. This adds `wenchang.identity`:
the `Identity` a resolver returns (scope → entity ID + role), the
`IdentityResolver` protocol, `resolve_identity` as the library's one call
site, and a `SandboxResolver` that returns a fixed identity. Nothing uses it
yet. Path construction (AIE-1041) and the scope checks (AIE-1040/1042) build on it.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | grants `user→(u-1, owner)`, `org→(o-9, member)` | build `Identity` | `scope_map == {"user":"u-1","org":"o-9"}`, `role("org") == "member"` |
| 2 | `Identity` built from a dict | mutate the dict, or the returned `scope_map` | `Identity` unchanged. `grants[...] = ...` raises `TypeError` |
| 3 | equal grants, any order | compare | equal and same hash. Different scope, entity ID, or role compare unequal |
| 3a | an `Identity`, or a module-level subclass instance | `pickle` round-trip, `copy.deepcopy` | equal value of the same type |
| 4 | empty grants | build | valid, `scope_map == {}` |
| 5 | scope not granted | `role(s)` / `entity_id(s)` | `KeyError` |
| 6 | entity ID or scope name is a rejected segment (row 8). Or `role == ""` | build | `ValueError` |
| 6a | non-`str` key, entity ID, role, or detail. Or a non-`ScopeGrant` value, or non-`Mapping` grants | build | `TypeError` |
| 6b | `str` subclass with overridden methods, underlying value `"a/b"` | build | `ValueError`. With a valid value, stored as exact `str` |
| 6c | `Mapping` whose `items()` looks valid but `keys()`/`__getitem__` don't | build `Identity` | rejected. The mapping is read once, and what is validated is what is stored |
| 6d | two keys that normalize to the same plain string | build `Identity` | `ValueError`, no grant silently dropped |
| 7 | `detail == ""` | build `ResolutionFailure` | `ValueError` |
| 8 | `""`, `.`, `..`, `/`, `a/b`, `a\b`, `a\x00b`, `\x7f`, `\x85` | `is_valid_segment` | `False`. `u-1`, `a.b`, `...`, `é`, `a b` give `True` |
| 9 | resolver returns `Identity` | `resolve_identity` | same object returned |
| 10 | resolver returns `ResolutionFailure("token expired")` | `resolve_identity` | `ResolverFailureError` (permanent), detail starts with `"token expired"` |
| 11 | resolver raises `RuntimeError("secret…")` | `resolve_identity` | `ResolverFailureError` naming the class and type, no secret, `__cause__ is None`, `__suppress_context__`. `__context__` is not asserted |
| 11a | resolver raises `ResolverFailureError("x")` or another `WenchangError` | `resolve_identity` | new `ResolverFailureError` naming the class and type. Original not passed through |
| 12 | resolver returns `None` | `resolve_identity` | `ResolverFailureError` naming the class and returned type |
| 12a | returned object whose `__class__`, type `__name__`, or name `__format__` raises. Or a `ResolutionFailure` subclass whose `detail` raises | `resolve_identity` | `ResolverFailureError`. Nothing from the object escapes |
| 13 | resolver raises `KeyboardInterrupt` | `resolve_identity` | propagates |
| 14 | `SandboxResolver(identity)` | `resolve(anything)` | `identity`. `isinstance(r, IdentityResolver)` is true |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| One `ScopeGrant(entity_id, role)` per scope | Two parallel maps | Parallel maps can disagree on keys. `scope_map` still gives the flat shape |
| Failure is a returned `ResolutionFailure` | Resolver raises | Section 10.1 says raising turns degradation into a crash |
| `resolve_identity` also catches any `Exception` and a bad return type, raised `from None` | Let it crash; chain `from exc` | Clean degradation even from a buggy resolver. The original message may carry credentials, so it must not reach tracebacks (**human decision**) |
| Validate scope names and entity IDs with `is_valid_segment`, made public and rejecting `/`. Runtime type checks raise `TypeError` | Validate only at path construction. Trust static types | Catches resolver bugs at the source, including from untyped adopter code. One rule shared with AIE-1041 |
| `Identity.__reduce__` rebuilds `type(self)` from a plain dict | Store a plain dict | mappingproxy keeps the value immutable but can't be pickled. Subclasses survive. `dataclasses.asdict` is unsupported, which is acceptable |
| Adversarial hardening: one-read snapshot, `str.__str__` normalization, `issubclass(type(x), ...)`, guarded detail building | Trust objects a resolver hands back | Resolvers are untrusted adopter code. A lying `Mapping`, `str` subclass, or `__class__` must not bypass validation or escape `resolve_identity` |
| Protocol generic and contravariant in credentials | Fixed credential type | The adopter types its own credentials. `SandboxResolver` takes `object` and fits any `C` |
| Ship `SandboxResolver` now, identity supplied by the adopter (**human decision**) | Built-in default scopes | The protocol needs one implementation to test, and AIE-1039 needs a reference. The library can't know the adopter's scopes |
| All failures permanent (**human decision**) | Transient variant | Matches Section 10.1. A transient flag can be added later without breaking the protocol |
| Recorded in ADR 0014 | — | New public module |

## Files/modules to be touched

- `src/wenchang/paths.py`: `is_valid_segment` made public and rejecting `/`
- `src/wenchang/identity.py` (new)
- `tests/test_paths.py`, `tests/test_identity.py` (new)
- `ARCHITECTURE.md`: the paths entry for the public segment check, and the planned "scope / identity" entry split into an implemented identity module and a planned scope module
- `docs/adr/0014-identity-resolver.md` (new)

## Open questions / assumptions

- None open. The human settled all three questions: failures are permanent-only, the raised exception is not chained, and the sandbox identity is supplied by the adopter.
- Session consistency is a resolver contract, left to the AIE-1039 conformance suite. The library does not cache.
- Rejecting `/` closes the only key-splicing vector. `.` and `..` are already rejected, and storage keys have no traversal semantics.

## Risks

- A resolver's auth backend outage makes memory unavailable for the whole session, with "do not retry".
- Without the chain, a crashing resolver only shows its class and exception type. Adopters debug the resolver directly.
