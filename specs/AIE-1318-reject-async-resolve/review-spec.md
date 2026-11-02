# Spec Review: AIE-1318 — Reject async resolve at registration

## What & why

`register_memory_tools` accepts a resolver with `async def resolve`; calling it returns a coroutine, so the failure appears at call time. Add `check_resolver` in `wenchang.identity` and reject detectably async `resolve` with `TypeError` at registration (`register_memory_tools`, `build_server`) and at `bind_tools`, mirroring how `check_observer` rejects async `on_call`.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | resolver with `async def resolve` | `register_memory_tools` / `build_server` | `TypeError("resolver.resolve must be a plain method, not async")`; no tools or prompt resource registered |
| 2 | same | `bind_tools` | same `TypeError`; no `ResolverFailureError`; no never-awaited `RuntimeWarning` |
| 3 | async staticmethod, partial of async fn, async generator, object with `async def __call__` | any of the three entry points | all rejected (parametrized) |
| 4 | sync resolver (`SandboxResolver`) | any entry point | accepted as before |
| 5 | `resolve` access raises, or sync `resolve` returns a coroutine | `bind_tools` | `ResolverFailureError`, unchanged |
| 6 | `check_resolver` called directly | sync / each async variant / missing or raising `resolve` | `None` / raises / `None`; `resolve` never invoked |
| 7 | async `on_call` and async `resolve` | `bind_tools` | the `on_call` `TypeError` first |
| 8 | non-`IdentityResolver`; or async resolver plus async `credentials_from_context` | `_validate` | the `isinstance` `TypeError` first; the resolver `TypeError` before the credentials one |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| `check_resolver` in `wenchang.identity`, not top-level exported | Inline check in `_validate`; export publicly | One check shared by `mcp` and `tools`; keeps the public surface unchanged |
| Also check in `bind_tools`, raising `TypeError` | Leave `bind_tools` as `ResolverFailureError` | A misconfigured resolver is a programmer error and should fail loudly like `on_call`, not be rendered to the agent |
| `resolve_identity` unchanged | Check there too | It stays the one call into a resolver and still reports undetectable returned coroutines as `ResolverFailureError` |
| Best-effort detection: coroutine function, async generator function, async `__call__`; never calls `resolve` | Call and inspect the result | Calling has side effects and leaves un-awaited coroutines |
| Unreadable `resolve` returns silently | Raise `TypeError` | Call-time handling already reports it; one failure path |

## Files/modules to be touched

- `src/wenchang/identity.py`, `src/wenchang/mcp.py`, `src/wenchang/tools.py`
- `tests/test_identity.py`, `tests/test_tools.py`, `tests/test_mcp_server.py`
- `site-src/reference.md`, `site-src/identity.md`, `site-src/integrate-without-mcp.md`, `ARCHITECTURE.md`, `docs/adr/0044-reject-async-resolver.md` (new)

## Open questions / assumptions

- Decided: `bind_tools` behavior for async `resolve` changes from `ResolverFailureError` to `TypeError`; recorded in ADR 0044.
- Assumption: the three entry points above are the only ones that take a resolver.

## Risks

- Behavior change for adopters who relied on `ResolverFailureError` from `bind_tools` for async `resolve`; pre-1.0 and a programmer-error case.
- MCP per-call path runs `check_resolver` on every call; a resolver swapped to async after registration becomes a rendered "internal" error with an `ERROR` log (untested; recorded in ADR 0044).
- Detection is best effort: a sync `def` returning a coroutine still fails at call time.
