# 0044. Reject an async resolver at registration and binding

Date: 2026-11-02

## Status

Accepted. Amends [ADR 0014](0014-identity-resolver.md) for the async case; its
`resolve_identity` behavior is otherwise unchanged. Extends the startup checks
in [ADR 0027](0027-mcp-host-adapter.md) (line 159, which rejects async
`credentials_from_context` and `on_call` but not `resolve`).

## Context

`IdentityResolver.resolve` is a synchronous method, and the library calls it
without awaiting. An adopter who writes `async def resolve` gets a coroutine
back instead of an `Identity`. `resolve_identity` reports that as a
`ResolverFailureError` at call time, so the mistake surfaces on the first
request, rendered to the agent as "memory unavailable", and Python also emits a
"coroutine was never awaited" warning. `on_call` and `credentials_from_context`
are already rejected at registration for the same reason.

## Decision

Add `wenchang.identity.check_resolver(resolver) -> None`. It raises
`TypeError("resolver.resolve must be a plain method, not async")` when `resolve`
is detectably async: a coroutine function (including an async static method or a
`functools.partial` of one), an async generator function, or an object whose
type has an async `__call__`. It never calls `resolve`. If reading `resolve`
raises or the attribute is missing, it returns and the existing call-time
handling reports the failure.

It is called from `wenchang.mcp._validate` right after the `IdentityResolver`
`isinstance` check and before the `credentials_from_context` checks, so
`register_memory_tools` and `build_server` fail before anything is registered.
It is also called from `bind_tools` after `check_observer` and before
`resolve_identity`. `resolve_identity` is unchanged. The function is not
exported from the top-level `wenchang` package.

Alternatives rejected:

- **Check only in `register_memory_tools`.** Leaves `bind_tools`, a public entry
  point that takes a resolver, with the call-time failure and the warning.
- **Do nothing and rely on call time.** The failure is late, looks like an
  outage to the agent, and the message does not tell the adopter what to fix.

## Consequences

- `bind_tools` with an async `resolve` now raises `TypeError` where it used to
  raise `ResolverFailureError`. A misconfigured resolver is a programmer error,
  so it fails loudly, as `on_call` does. No existing test asserted the old
  behavior.
- Detection is best effort. A sync `def resolve` that returns a coroutine, or any
  other awaitable the check cannot see, still raises `ResolverFailureError` from
  `resolve_identity` at call time.
- The MCP per-call path calls `bind_tools` inside `except Exception`, so
  `check_resolver` runs on every call and reads `resolve` twice per call. A
  resolver swapped to async after registration renders as an `internal` error
  with an `ERROR` log rather than crashing the server.
- A `resolve` read that raises is still reported at call time as
  `ResolverFailureError`, so one path owns that case.
