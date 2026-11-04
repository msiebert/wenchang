# Feature Specification: Reject async resolve at registration

**Linear**: AIE-1318

**Feature Branch**: `AIE-1318-reject-async-resolve`

**Created**: 2026-11-02

**Status**: Draft

**Input**: `register_memory_tools` accepts a resolver whose `resolve` is `async def`. Calling it returns a coroutine rather than a scope map, so the failure shows up at call time instead of at registration. Reject coroutine functions (and other awaitable-returning callables where detectable) with a `TypeError` at registration, matching how `on_call` rejects async observers (`check_observer`). Add a test. Consider whether `bind_tools` or other entry points that take a resolver should get the same check, and whether `site-src` docs mention it.

## Decisions already made (not reopened)

- New `check_resolver(resolver: object) -> None` in `wenchang.identity`, not exported from the top-level `wenchang` package.
- `check_resolver` reads `resolver.resolve` with `getattr` inside `try/except Exception`. If the read raises or the attribute is missing, it returns without raising; the existing call-time handling reports that. It never calls `resolve` and does not check protocol conformance.
- Detectable cases (rejected): `inspect.iscoroutinefunction(resolve)` (async def methods, async static/class methods read through the instance, `functools.partial` of an async function), `inspect.isasyncgenfunction(resolve)`, and a non-function callable object whose type's `__call__` is a coroutine function.
- Message, verbatim: `TypeError("resolver.resolve must be a plain method, not async")`.
- `register_memory_tools` and `build_server` reject through `_validate`, right after the existing `isinstance(resolver, IdentityResolver)` check and before anything is registered.
- `bind_tools` also calls `check_resolver`, after `check_observer(on_call)` and before the resolver runs. A misconfigured resolver is a programmer error and fails loudly as `TypeError`, as `on_call` does, rather than being rendered to the agent as `ResolverFailureError`. This changes `bind_tools`' documented behavior for async `resolve` from `ResolverFailureError` to `TypeError`. No existing test asserted the old behavior, so no existing test changes. Other resolver failures in `bind_tools` are unchanged.
- `resolve_identity` is unchanged. It still reports a returned coroutine (undetectable case, e.g. a sync `def` that returns a coroutine) as `ResolverFailureError`.
- Python floor is 3.11, so `inspect.markcoroutinefunction` (3.12+) is not relied on.
- Out of scope: sync-over-async adapters, checking `credentials_from_context` again (already checked), any change to `IdentityResolver` beyond its docstring (no behavior or signature change).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Fail at registration, not at call time (Priority: P1)

An adopter who writes `async def resolve` finds out when they register or bind, with a clear message.

**Why this priority**: The issue's purpose.

**Independent Test**: Pass resolvers with each async variant to each entry point.

**Acceptance Scenarios**:

1. **Given** a resolver whose `resolve` is `async def`, **When** `register_memory_tools` is called, **Then** `TypeError("resolver.resolve must be a plain method, not async")` is raised and the server has no memory tools and no prompt resource registered.
2. **Given** the same resolver, **When** `build_server` is called, **Then** the same `TypeError` is raised.
3. **Given** the same resolver, **When** `bind_tools` is called, **Then** the same `TypeError` is raised, no `ResolverFailureError` is raised, and no "coroutine ... was never awaited" `RuntimeWarning` is emitted.
4. **Given** each variant, **When** passed to each of the three entry points (parametrized), **Then** all raise the `TypeError` of 1.1. Variants: `async def` method; async `staticmethod`; an instance attribute that is `functools.partial` of an async function; an async generator method; an instance attribute that is an object with `async def __call__`.

---

### User Story 2 - Everything else is unchanged (Priority: P1)

**Acceptance Scenarios**:

1. **Given** a sync resolver (e.g. `SandboxResolver`), **When** passed to the three entry points, **Then** each accepts it as before.
2. **Given** a resolver whose `resolve` attribute access raises, **When** `bind_tools` is called, **Then** `ResolverFailureError` is raised (unchanged), not `TypeError`.
3. **Given** a resolver whose sync `resolve` returns a coroutine object, **When** `bind_tools` is called, **Then** `ResolverFailureError` is raised (unchanged).
4. **Given** an existing test of `bind_tools`, `register_memory_tools`, `build_server`, or `resolve_identity`, **When** the suite runs, **Then** it passes unmodified (no existing test asserted `ResolverFailureError` for an `async def resolve`; see SC-002).

---

### User Story 3 - `check_resolver` unit behavior and ordering (Priority: P1)

**Acceptance Scenarios**:

1. **Given** `check_resolver`, **When** called with a sync resolver, **Then** it returns `None`; for each async variant of 1.4 it raises the `TypeError` of 1.1; and `resolve` is never invoked (a counting stub proves it).
2. **Given** an object with no `resolve` attribute, or one whose `resolve` read raises `Exception`, **When** `check_resolver` is called, **Then** it returns `None`.
3. **Given** `bind_tools` with an async `on_call` and an async `resolve`, **When** called, **Then** the `on_call` `TypeError` is raised (`check_observer` runs first).
4. **Given** `_validate` (via `register_memory_tools` or `build_server`) with an object that is not an `IdentityResolver`, **When** called, **Then** the `isinstance` `TypeError` ("resolver must satisfy IdentityResolver") is raised first.
5. **Given** `_validate` with an async resolver and an async `credentials_from_context`, **When** called, **Then** the resolver `TypeError` is raised first.

### Edge Cases

- The MCP per-call path calls `bind_tools` inside `except Exception`, so `check_resolver` runs on every call and reads `resolve` twice per call (benign). A resolver swapped to async after registration surfaces as a rendered "internal" error with an `ERROR` log, not a crash. No test is needed for this.
- A sync `def` that returns a coroutine, or any other awaitable the check cannot see, still fails at call time as `ResolverFailureError`. Detection is best effort.
- A `resolve` read that raises is reported at call time, not at registration, so one failure path owns that case.
- `check_resolver` does not enforce the protocol; a missing `resolve` is the `isinstance` check's job where it applies.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `wenchang.identity` MUST define `check_resolver(resolver: object) -> None` per the decisions above. The module has no `__all__`; do not add one. It MUST NOT be added to the top-level `wenchang` exports.
- **FR-002**: `wenchang.mcp._validate` MUST call `check_resolver(resolver)` immediately after the `IdentityResolver` `isinstance` check, so `register_memory_tools` and `build_server` raise before any tool or resource is registered.
- **FR-003**: `bind_tools` MUST call `check_resolver(resolver)` after `check_observer(on_call)` and before any resolver call.
- **FR-004**: `resolve_identity` MUST remain unchanged.
- **FR-005**: ARCHITECTURE.md, `site-src` pages (`reference.md`, `identity.md`, `integrate-without-mcp.md`, `integrate-new-server.md`), and ADR 0044 MUST describe the new rejection and the `bind_tools` change.
- **FR-006**: `make check` MUST pass.
- **FR-007**: Source docstrings (`bind_tools`, `register_memory_tools`, `build_server`, `_validate`, `IdentityResolver` and its `resolve`) MUST state the resolver check, with no ticket IDs.

## Success Criteria *(mandatory)*

- **SC-001**: An `async def resolve` fails with a clear `TypeError` at registration or binding through every entry point that takes a resolver.
- **SC-002**: Existing tests pass unmodified; no existing test changes, since none asserted `ResolverFailureError` for an `async def resolve`.

## Assumptions

- Entry points that take a resolver are exactly `register_memory_tools`, `build_server` (both via `_validate`), and `bind_tools`; `resolve_identity` is the shared call site and stays a call-time reporter.
- A misconfigured resolver is a programmer error, so `TypeError` is preferred over `ResolverFailureError` at `bind_tools`.
