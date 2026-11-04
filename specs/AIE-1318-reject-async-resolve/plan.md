# Implementation Plan: AIE-1318 Reject async resolve at registration

**Spec**: `spec.md` · **ADR**: 0044 · **Branch**: `AIE-1318-reject-async-resolve`

## Summary

Add `check_resolver` to `wenchang.identity` and call it from `wenchang.mcp._validate` (covers `register_memory_tools` and `build_server`) and from `bind_tools`, so an async `resolve` fails with `TypeError` before anything is registered or resolved. `resolve_identity` is unchanged.

## Public interface

### `wenchang.identity`

```python
def check_resolver(resolver: object) -> None:
    """Raise TypeError if resolver.resolve is detectably async."""
    # Message, verbatim: "resolver.resolve must be a plain method, not async"
```

The module has no `__all__`; do not add one. Not added to the top-level `wenchang` exports.

Behavior:

1. `try: resolve = getattr(resolver, "resolve") except Exception: return`. A missing attribute (`AttributeError`) or a raising property returns without raising.
2. Raise `TypeError("resolver.resolve must be a plain method, not async")` if any of:
   - `inspect.iscoroutinefunction(resolve)` (async def methods, async static/class methods read through the instance, `functools.partial` of an async function);
   - `inspect.isasyncgenfunction(resolve)`;
   - `resolve` is not a function or method and `inspect.iscoroutinefunction(type(resolve).__call__)` is true (an object with `async def __call__`).
3. Otherwise return `None`.

It never calls `resolve`, never checks `isinstance(resolver, IdentityResolver)`, and does not guard the `inspect` calls beyond step 1 (they do not raise for ordinary objects).

### Call sites and ordering

- `wenchang.mcp._validate` (shared by `register_memory_tools` and `build_server`): `isinstance(resolver, IdentityResolver)` check (`TypeError("resolver must satisfy IdentityResolver")`) -> `check_resolver(resolver)` -> the existing `credentials_from_context` async check -> `check_observer(on_call)`. All run before any tool or resource is registered, so a failure leaves the server with no memory tools and no prompt resource.
- In `_validate`, an async resolver combined with an async `credentials_from_context` raises the resolver `TypeError` first.
- `wenchang.tools.bind_tools`: `check_observer(on_call)` -> `check_resolver(resolver)` -> `resolve_identity(resolver, credentials)`. Signature unchanged. An async `on_call` plus an async `resolve` raises the `on_call` `TypeError`.

### Unchanged

- `resolve_identity`: still the single call into a resolver. A sync `def` that returns a coroutine still yields `ResolverFailureError("Resolver X returned coroutine, not Identity or ResolutionFailure.")`.
- A resolver whose `resolve` attribute access raises still yields `ResolverFailureError` from `bind_tools` (via `resolve_identity`), not `TypeError`.
- `IdentityResolver`, `SandboxResolver`, and the top-level exports.

## Module boundaries

`wenchang.identity` gains one stdlib-only function (`inspect`). `wenchang.tools` and `wenchang.mcp` already import from it. No storage, transport, or scope change.

## Testing approach

Tests go in existing files, with AIE-1318 in each docstring:

- `tests/test_identity.py`: `check_resolver` unit tests (sync returns `None`; each async variant raises; missing/raising `resolve` returns `None`; a counting stub proves `resolve` is never called).
- `tests/test_tools.py`: `bind_tools` rejection, parametrized over the five variants; no `ResolverFailureError`; no never-awaited `RuntimeWarning`: wrap the call in `warnings.catch_warnings(record=True)` with `warnings.simplefilter("always")`, run `gc.collect()`, then assert no recorded `RuntimeWarning` message contains "never awaited" (a call counter cannot prove this, since an async body never runs; do not use `filterwarnings("error")` or `-W error`); sync resolver accepted; raising `resolve` access and sync-returns-coroutine still `ResolverFailureError`; ordering with async `on_call`. Update any existing test that expects `ResolverFailureError` for an async `resolve` to `TypeError`.
- `tests/test_mcp_server.py`: `register_memory_tools` and `build_server` rejection, parametrized over the five variants, with no tools or prompt resource registered after failure; sync resolver accepted; non-`IdentityResolver` still raises the `isinstance` `TypeError` first.

"Nothing registered" in `tests/test_mcp_server.py`: reuse its existing helpers that list the server's tools and resources. `build_server` failure cases assert only the `TypeError`.

Variant fixtures must be pyright-strict clean: type attribute-assigned callables as `object`, or use `cast` at the call site.

Variants (shared helper in each file):

1. `async def resolve(self, credentials)` method;
2. `@staticmethod async def resolve(credentials)`;
3. `self.resolve = functools.partial(async_fn)` instance attribute;
4. `async def resolve` containing `yield` (async generator);
5. `self.resolve = obj` where `obj` has `async def __call__`.

Each variant resolver must still satisfy `isinstance(r, IdentityResolver)` (a `resolve` attribute exists) so `_validate` reaches `check_resolver`.

## Docs

- Source docstrings (done in T2): `bind_tools` (the "`on_call` is checked before the resolver runs" line also mentions the resolver check); `register_memory_tools`, `build_server`, `_validate` where they list what is validated; `IdentityResolver` and its `resolve` docstring ("a plain, non-async method"). No ticket IDs in `src/`.
- `site-src/reference.md` (~line 216, plus the `bind_tools` and `register_memory_tools` parameter sections), `site-src/identity.md` (~lines 42, 88), `site-src/integrate-without-mcp.md` (~lines 32, 95), `site-src/integrate-new-server.md` (resolver parameter row, ~line 22): replace the `ResolverFailureError` statement for async `resolve` with the registration/binding `TypeError`; keep the note that undetectable awaitables still fail at call time.
- ARCHITECTURE.md: identity (~line 567) describe `check_resolver`; `bind_tools` (~lines 990, 993-994, ordering) and `register_memory_tools` (~lines 1258, 1354) describe the new rejection and ordering; add the invariant and error-taxonomy mentions (~lines 1552-1554, 1632).
- ADR `docs/adr/0044-reject-async-resolver.md`: cross-references ADR 0027 (~line 159) and ADR 0014 (amends it for the async case; 0014 is not edited); records the MCP per-call edge case (`check_resolver` runs on every call; a resolver swapped to async after registration becomes a rendered "internal" error with an `ERROR` log; `resolve` read twice per call); decision, `bind_tools` `ResolverFailureError` -> `TypeError` change, best-effort detection, why `resolve_identity` is unchanged.
