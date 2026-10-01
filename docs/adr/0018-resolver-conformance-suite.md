# 0018. Resolver conformance suite

Date: 2026-09-30

## Status

Accepted

## Context

Notion Section 10 says an adopter implements two interfaces, the identity
resolver and the transport client, and that "the library ships an
executable conformance suite for each. Passing defines a correct
implementation." Section 10.1 lists the resolver's obligations. For valid
credentials it returns a scope-name-to-entity-ID map and a role per scope.
It never raises on bad credentials, and instead returns a resolution
failure that the library converts into a permanent error. It is consistent
within a session. It returns roles the adopter's scope configuration
references, so write-restriction checks are decidable.

AIE-1039 asks for that suite for the resolver. It must also cover path
construction, `system/` read-only enforcement, and write restriction. The
pieces it checks already exist: `Identity`, `IdentityResolver`,
`resolve_identity`, and `SandboxResolver` (ADR 0014); `build_path`,
`build_prefix`, and `parse_path` (ADR 0015); `check_not_system` (ADR 0016);
and `ScopePolicy` and `check_write` (ADR 0017). The repo's existing storage
conformance suite lives in `tests/`, which is not installed, so adopters
could not run it.

## Decision

Add the installed subpackage `wenchang.testing`, exporting the generic
pytest mixin `ResolverConformance[C]` with twelve test methods, and add the
optional extra `testing = ["pytest>=8.3"]`. No existing module changes.

1. **The suite ships inside the installed package as `wenchang.testing`.**
   Adopters run it against their own resolver, so it cannot live under
   `tests/`. The storage suite (`tests/storage_conformance.py`) stays in
   `tests/` because storage is not an adopter surface. Rejected
   alternatives:
   - A separate `wenchang-testing` distribution, which adds a second
     version to keep in lockstep for one module.
   - A pytest plugin entry point that auto-registers fixtures. It would load
     into every adopter test session and hide the contract.
2. **pytest is an optional extra, `wenchang[testing]`, imported at the top
   of the suite module.** Only `wenchang.testing` imports pytest, and the
   library never imports `wenchang.testing`, so `import wenchang` works
   without pytest. Rejected alternatives:
   - A pytest-free suite of plain `assert`s. An installed module is not
     assertion-rewritten, so a bare `assert` fails with no message, and
     `python -O` strips it. It also cannot skip.
   - A `unittest.TestCase` base, which has no fixtures and diverges from
     the storage-suite precedent.
3. **Violations are reported with `pytest.fail(message)`, never `assert`,
   and a caught exception stays attached as context.** Each message names
   the resolver class and contains a fixed key phrase, so an adopter sees
   what broke and the self-tests can match it. `pytest.fail` is raised
   inside the `except` block, so the resolver's exception becomes the
   failure's `__context__` and pytest shows it. This deliberately differs
   from ADR 0014, where `resolve_identity` raises `from None` so no
   credential-bearing message reaches a rendered traceback. Here the adopter
   is debugging their own resolver with their own test credentials.
   Approved by the human at spec review, 2026-09-30. Rejected alternative:
   suppressing context with `from None`, which hides the cause of the
   failure from the person who needs it.
4. **The contract is a generic mixin plus six required fixtures:**
   `resolver`, `valid_credentials`, `invalid_credentials`, `policy`,
   `expected_scopes`, and `known_roles`. The mixin is generic in `C` so an
   adopter's `IdentityResolver[MyCreds]` type-checks cleanly. A missing
   fixture is a pytest collection error, which forces an explicit choice.
   `expected_scopes` is required. Approved by the human at spec review,
   2026-09-30. Rejected alternatives:
   - An optional `expected_scopes`. Checking only that grants are non-empty
     would pass a resolver that silently drops a scope.
   - A `has_invalid_credentials` class flag. A resolver that accepts every
     credential instead has its `invalid_credentials` fixture call
     `pytest.skip`. That is idiomatic, adds no knob, and skips exactly the
     three methods that take the fixture.
5. **Roles are decidable when every granted role, and every role the policy
   permits, is in `known_roles`.** Section 10.1 wants roles "the adopter's
   scope configuration references". `ScopePolicy` lists only the roles
   permitted to write, so it cannot say whether `"member"` is a real role or
   a typo. The adopter supplies the full set in the required `known_roles`
   fixture. Approved by the human at spec review, 2026-09-30. The policy
   side catches a typo such as `"Admin"` in the policy against a resolver's
   `"admin"`, which would leave the scope unwritable by anyone. A known
   role the policy never mentions, such as `member`, is legitimate. Both
   frozenset fixtures are checked to be `frozenset`s of `str` first, because
   a `str` `known_roles` would turn `in` into a substring test. Rejected
   alternatives:
   - Requiring each granted role to be in `permitted_roles`, which would
     demand that every caller can write.
   - Asserting only that each role is non-empty, which `ScopeGrant` already
     guarantees.
6. **Consistency is three resolves of the same credentials object,
   compared by value.** Invalid credentials must give a `ResolutionFailure`
   every time, with any `detail`. Rejected alternatives:
   - Resolving a deep copy, since credentials may hold uncopyable handles.
   - Comparing failure details, which may carry timestamps.
7. **The suite calls `resolver.resolve` directly for contract checks, and
   `resolve_identity` only for the conversion check.** `resolve_identity`
   converts a raise into `ResolverFailureError`, which would hide the one
   violation Section 10.1 calls a crash. Rejected alternative: going
   through the library entry point for every check.
8. **The path and enforcement tests run the adopter's identity and policy
   end to end, even though a valid `Identity` cannot fail them.** `Identity`
   validates every segment and the scope checks are pure, so these tests
   fail only if the library regresses. They are in the suite because the
   issue names them, and they catch a library regression in the adopter's
   own configuration. The self-tests prove they can fail by patching the
   module-level names they call (`build_path`, `build_prefix`,
   `parse_path`, `check_write`). Rejected alternative: leaving them out as
   unreachable.
9. **The self-tests call mixin methods directly and expect
   `pytest.fail.Exception`.** Rejected alternative: `pytester` subprocess
   runs, which are slower and need the plugin enabled. The reference runs
   against `SandboxResolver` and a token-lookup resolver already exercise
   collection and skipping end to end.
10. **Adversarial hardening: the suite judges the values the library
    reads, not the resolver's own objects.** Code review after spec review
    found that a resolver could pass all twelve methods by returning an
    `Identity` or `ScopeGrant` subclass with a lying `__eq__` or an
    overridden `role()` or `entity_id()`. Such a resolver reports one
    identity to the suite and another to the library, so passing would not
    mean conforming. The rules adopted:
    - Every resolved `Identity` is canonicalized: the suite rebuilds it as
      a base `Identity` of base `ScopeGrant`s from the stored grants'
      attributes, `Identity({s: ScopeGrant(g.entity_id, g.role) for s, g
      in result.grants.items()})`. Any `Exception` while rebuilding fails
      with the key phrase `invalid Identity`. The entry-point test
      canonicalizes the `resolve_identity` result the same way. Every later
      comparison and read uses the canonical value, which is what the
      library's own checks read.
    - Result types are tested with `issubclass(type(result), ...)`, not
      `isinstance`, as `resolve_identity` does (ADR 0014), so a spoofed
      `__class__` fails as the wrong type.
    - Resolver and exception type names are read through a guarded helper
      that falls back to `"<unnamed>"` if `__name__` raises, so a hostile
      metaclass cannot make the suite error instead of fail.
    - `expected_scopes` and `known_roles` are copied to plain `frozenset`s
      of exact `str` (`type(item) is str`), and a failure names the
      offending member's type.

    Rejected alternative: trusting the returned objects' own equality and
    accessors. That is simpler, but a conformance suite that a hostile or
    buggy subclass can satisfy does not define correctness.

The shipped module cites no Linear IDs and applies no pytest marks, so an
adopter running `--strict-markers` never hits an unregistered mark.
Adopters mark their own `Test` subclass.

## Consequences

An adopter verifies a resolver by subclassing `ResolverConformance` and
supplying six fixtures. Every failure names the resolver class and the
broken clause.

pytest becomes an optional extra, `wenchang[testing]`. Through
`wenchang.testing` it is part of the public contract, so a pytest major
release could break adopters' suite runs. The core library still imports
without pytest. `tests/test_testing_package.py` enforces this with an
`ast` scan of every module outside `wenchang.testing`, and with a
subprocess that blocks `pytest` in `sys.modules` and imports every other
module.

The suite's own self-tests prove each failure path fires. Each one patches
a resolver or library function into a known defect and requires the
matching key phrase, including an explicit matrix of patched `check_write`
behaviors across the four enforcement tests. Because the suite is trusted
as the definition of correctness, a change to it needs a matching
self-test. Hostile-resolver self-tests pin the decision 10 hardening.

`SandboxResolver` skips the three invalid-credential tests by design,
because it accepts every credential. Both of its reference runs (permitted
role and lacking role) report those three as skipped. The token-lookup
reference run covers them unskipped. Adopters with an accept-everything
resolver follow the same `pytest.skip` convention.

Leaving exception context attached means a suite failure's traceback can
show the resolver's own exception message. That is acceptable for an
adopter's test credentials. The library's runtime path still raises
`from None`.

The transport conformance suite (AIE-1045, AIE-1047) is out of scope here.
It is expected to reuse this shape under `wenchang.testing`.
