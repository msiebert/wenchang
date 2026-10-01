# Spec Review: AIE-1039 — resolver conformance suite

## What & why

Notion Section 10 says passing a shipped conformance suite defines a correct
resolver. This adds `wenchang.testing.ResolverConformance[C]`, a pytest
mixin an adopter subclasses with six fixtures: resolver, valid and invalid
credentials, their `ScopePolicy`, expected scopes, and known roles. Its
twelve tests cover every Section 10.1 clause plus paths, `system/`, and
write restriction. pytest becomes an optional extra, `wenchang[testing]`.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | resolver returns an `Identity` granting `expected_scopes` | suite runs | valid-credential tests pass |
| 2 | raises, returns `ResolutionFailure`, `None`, empty grants, or wrong scopes for valid creds | valid test | fails with a named key phrase, never errors. A raised exception stays as `__context__` |
| 3 | raises, returns `Identity`, or `None` for invalid creds | invalid tests | fail with the resolver's own phrase, never pytest's "DID NOT RAISE". `ResolutionFailure` passes, and `resolve_identity` gives a permanent error |
| 4 | `invalid_credentials` fixture calls `pytest.skip` | suite runs | three invalid-credential tests skip, the rest run |
| 5 | a later resolve differs or raises | consistency test | fails naming the call. Invalid-cred failure `detail` may differ |
| 6 | a granted role, or a policy role, not in `known_roles` (e.g. `Admin` vs `admin`) | role test | fails. Non-`frozenset` `known_roles` / `expected_scopes` fail as bad fixtures |
| 7 | every granted scope | path test | path valid and round-trips, prefix valid and contains it. Each has its own phrase |
| 8 | own and foreign entity under `system/`, and an ungranted scope | system test | `SYSTEM_READ_ONLY`, pinning system before not-granted |
| 9 | own entity under `notes/` | policy test | `None`, or `ROLE_REQUIRED` with the policy's role set, as the policy predicts |
| 10 | foreign entity, an ungranted scope, or a restricted ungranted scope (`team`) | not-granted tests | `NOT_GRANTED` |
| 11 | `SandboxResolver`, permitted and lacking role | suite runs | pass, invalid tests skipped |
| 12 | token-lookup resolver | suite runs | all pass, none skipped |
| 13 | `check_write`, `resolve_identity`, or a path function patched to misbehave | affected tests | fail per an explicit matrix, including non-`RestrictedScopeError` exceptions. Proves they bite |
| 14 | any module outside `wenchang.testing` | ast scan and a subprocess with pytest blocked | no `pytest` or `wenchang.testing` import, and every module imports |
| 15 | `wenchang.testing` | scan | no Linear IDs, no pytest marks. `pyproject.toml` has the `testing` extra |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| Ship in `src/wenchang/testing/` | `tests/`; separate distribution; auto-loaded pytest plugin | Adopters run it, so it must be installed. One package, explicit subclassing |
| pytest as optional extra, top-level import | Plain `assert`, no pytest; `unittest` | Installed modules aren't assert-rewritten, so bare asserts have no message and `-O` strips them. No skip either |
| Report with `pytest.fail(message)` naming resolver and key phrase | Bare `assert` | Readable adopter failures. Self-tests match the phrase |
| Six required fixtures, generic in `C` | Optional `expected_scopes`; class flag for "no invalid creds" | A missing fixture errors loudly. Skip-in-fixture needs no extra knob |
| `known_roles` fixture checks granted roles and policy roles | Role in `permitted_roles`; role non-empty only | `ScopePolicy` lists only writer roles. The policy side catches a typo that makes a scope unwritable. The other checks are wrong or tautological |
| Three resolves of the same object, by value | Deep-copy credentials; compare failure details | Credentials may not copy. Details may carry timestamps |
| Contract checks call `resolver.resolve`, not `resolve_identity` | Go through the library entry point | `resolve_identity` hides a raise, the very crash Section 10.1 names |
| Self-tests call methods directly, expect `pytest.fail.Exception` | `pytester` subprocess | Faster, no plugin. Reference runs already cover collection and skip |
| Adversarial hardening: judge a canonical base `Identity` rebuilt from stored grants (`invalid Identity` if that fails). Type tests via `issubclass(type(x), ...)`. `"<unnamed>"` name fallback. Fixtures copied to a plain `frozenset` of exact `str` | Trust the returned objects' `__eq__`, `role()`, `entity_id()` | Code review found subclasses with a lying `__eq__` or overridden accessors passed all twelve tests. The suite now reads what the library reads |
| Recorded in ADR 0018 | — | New public subpackage and packaging extra |

## Files/modules to be touched

- `pyproject.toml`: `testing` extra. `uv.lock` regenerated
- `src/wenchang/testing/__init__.py`, `resolver_conformance.py` (new)
- `tests/test_resolver_conformance_reference.py`, `test_resolver_conformance_self.py`, `test_testing_package.py` (new)
- `ARCHITECTURE.md`, `docs/adr/0018-resolver-conformance-suite.md`

## Open questions / assumptions

- None open. The human settled all three questions on 2026-09-30:
  - `known_roles` is a required fixture, which makes Section 10.1's roles clause testable.
  - A caught resolver exception stays attached as context in suite failures. This deliberately differs from the library's `from None` rule in ADR 0014, and ADR 0018 decision 3 records the contrast.
  - `expected_scopes` is required.
- Needs all four sibling issues merged first.
- **Allowed skip (spec Allow-test-changes).** The two `SandboxResolver` reference classes skip the three invalid-credential methods through their `invalid_credentials` fixture. `SandboxResolver` accepts every credential by design, and this is the documented adopter convention. The token-lookup class runs those methods unskipped. No other skip or xfail is allowed.

## Risks

- Tests 7–10 cannot fail for a valid `Identity`. They guard the library in the adopter's configuration, and self-tests prove they bite only by patching. A no-op `check_write` with a fully permitted identity passes the own-entity test, so the member identity carries that proof.
- `pytest` becomes part of the public contract. A pytest major release could break adopters' suite runs.
