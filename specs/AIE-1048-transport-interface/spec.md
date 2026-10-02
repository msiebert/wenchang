# Feature Specification: Abstract transport client interface

**Linear issue**: AIE-1048 — https://linear.app/mixpanel/issue/AIE-1048/abstract-transport-client-interface

**Feature Branch**: `AIE-1048-transport-interface`

**Created**: 2026-10-01

**Status**: Draft

**Input**: Linear AIE-1048 ("Define the abstract transport client interface
that exposes the core library operations (read, write, append,
replace_fact, list, delete) over a transport-agnostic contract, to be
implemented in-process now and remotely (e.g. gRPC) later") and Notion
"Agent Memory Library — Specification":

- Section 7: "The agent-facing tool layer is thin and transport-agnostic.
  Tool bodies contain no logic; they call an abstract client interface and
  format the response. That interface mirrors the core API: read, write,
  list, append, replace_fact, delete, get_memory_index. A concrete
  implementation is injected at startup: in-process ... remote ... Further
  transports are added by writing another implementation, without touching
  tool definitions."
- Section 5: `get_memory_index(scope_map)` "takes a map of scope name to
  entity ID and returns merged metadata across every scope in that map, in
  one call", with a byte cap, a documented ordering, and a `capped` section
  "listing each prefix not fully returned, with an omitted count".
- Section 10.2: in-process and remote implementations "must be behaviorally
  indistinguishable", including "Error parity. Every error surfaces in the
  same category with the same payload across implementations."

Builds on `MemoryStore`, `MemoryFile`, `FileEntry`, `ListPage`,
`ListCursor` (AIE-1032–1037), `FileMetadata` (AIE-1031), `VersionToken`,
and the error taxonomy (AIE-1030).

## Summary

Add a new module `wenchang.transport` exporting `TransportClient`, a
runtime-checkable `Protocol` whose seven methods mirror the core API:
`read_file`, `write_file`, `append_line`, `replace_fact`, `list_prefix`,
`delete_file`, and `get_memory_index`. The six existing operations carry
exactly the signature of the matching `MemoryStore` method, so a conforming
client can be substituted for a `MemoryStore` without the tool layer
noticing. Add the two value types the index operation returns, `MemoryIndex`
and `CappedPrefix`, to `wenchang.core` next to `MemoryFile` and `ListPage`.

The module is a contract only: no implementation, no wiring. The
in-process implementation and `MemoryStore.get_memory_index` are AIE-1046,
the tool layer is AIE-1044, and the conformance harness and cases are
AIE-1047 and AIE-1045.

**Rescoping across the milestone.** AIE-1044's issue text carries the
index semantics (64 KB byte cap, `system/`-first ordering, optional scope
priority, `capped` section). This spec assigns the *implementation* of
`MemoryStore.get_memory_index` to AIE-1046, because the in-process client
must pass the index conformance cases and cannot pass through a method
that does not exist. AIE-1044 is the tool layer only, including the
`get_memory_index` tool that calls the client. Recorded in ADR 0019.

Out of scope: any client implementation, any change to `MemoryStore`'s
existing methods, identity or scope enforcement (the transport is
identity-agnostic; the tool layer checks writes before calling the client),
async variants, and the gRPC transport.

## User Scenarios & Testing *(mandatory)*

The "user" is an adopter writing a transport client, or the tool layer
consuming one. "Mirrors" means `inspect.signature(TransportClient.m,
eval_str=True) == inspect.signature(MemoryStore.m, eval_str=True)`:
identical parameter names, kinds, defaults, annotations, and return
annotation.

### User Story 1 - The protocol mirrors the core API (Priority: P1)

**Acceptance Scenarios**:

1. **Given** `wenchang.transport`, **When** imported, **Then** it exports
   `TransportClient`, listed in `__all__`.
2. **Given** `TransportClient`, **Then** `{n for n, v in
   vars(TransportClient).items() if callable(v) and not
   n.startswith("_")}` is exactly `{read_file, write_file, append_line,
   replace_fact, list_prefix, delete_file, get_memory_index}`.
3. **Given** each of the six existing operations, **Then**
   `TransportClient.<m>` mirrors `MemoryStore.<m>`, including the
   keyword-only `source` on `write_file`, `append_line`, and `replace_fact`,
   the `expected_version: VersionToken | None` on `write_file`, and the
   `cursor: ListCursor | None = None` default on `list_prefix`.
4. **Given** `TransportClient.get_memory_index`, **Then**
   `inspect.signature(TransportClient.get_memory_index, eval_str=True)`
   equals `inspect.signature(_Ref.get_memory_index, eval_str=True)`, where
   `_Ref` is a local test class with the method `def get_memory_index(self,
   scope_map: Mapping[str, str]) -> MemoryIndex` (`Mapping` from
   `collections.abc`; `typing.Mapping[str, str]` does not compare equal).
   A method on a class is used, not a module-level function, because a
   method's `self` needs no annotation under pyright strict and compares
   equal to the Protocol method's unannotated `self`.
5. **Given** every protocol method, **Then** it has a non-empty docstring.
   The class docstring states the error-parity contract: for well-typed
   arguments, each of the six mirrored methods raises exactly the exception
   types the matching `MemoryStore` method raises, with equal attributes
   and message. That includes the `wenchang.errors` taxonomy (same category
   and payload) and the non-taxonomy types core raises, including
   `ValueError` (for example an empty `source` or `old_string`, a non-fact
   `line`, a malformed or foreign `cursor`), `MetadataFormatError`, and
   `UnicodeDecodeError`. Failures of the transport itself (an RPC timeout,
   a refused connection, a crashed server) have no `MemoryStore`
   equivalent and surface as `BackendUnavailableError` with the matching
   `TransientReason`, never as a transport library's own exception type.
   The docstring names `MemoryStore`, `wenchang.errors`, `ValueError`,
   `MetadataFormatError`, `UnicodeDecodeError`, and
   `BackendUnavailableError`. For `get_memory_index`, the error contract is
   whatever `MemoryStore.get_memory_index` defines in AIE-1046.

---

### User Story 2 - Structural conformance (Priority: P1)

**Acceptance Scenarios**:

1. **Given** a class defining all seven methods (bodies may be trivial),
   **When** `isinstance(instance, TransportClient)` is evaluated, **Then** it
   is `True`. Separately, `make typecheck` accepts `client: TransportClient
   = _FullClient()` in the test module; this half is enforced by pyright,
   not by a pytest assertion.
2. **Given** a class missing any one of the seven methods, **Then**
   `isinstance` is `False`. Parametrized over each method name.
3. **Given** `TransportClient`, **When** instantiated directly, **Then**
   `TypeError` is raised (it is a `Protocol`).

---

### User Story 3 - Index value types (Priority: P1)

**Acceptance Scenarios**:

1. **Given** `CappedPrefix("user/u-1/notes/", 12)`, **Then** it is a frozen
   dataclass with `prefix == "user/u-1/notes/"` and `omitted == 12`;
   assigning a field raises `FrozenInstanceError`.
2. **Given** `omitted <= 0`, **When** constructing `CappedPrefix`, **Then**
   `ValueError`. A prefix failing `is_valid_prefix` (e.g. `""`, `"user"`,
   `"user/u-1/notes/x.md"`) raises `ValueError`.
3. **Given** a non-`str` `prefix` (e.g. `None`), or an `omitted` whose
   real type is not `int` (`bool` included: `issubclass(type(x), bool)` is
   rejected; `"3"` and `3.0` are rejected), **Then** `TypeError`, checked
   before the `ValueError` checks: `CappedPrefix("", True)` raises
   `TypeError`, not `ValueError`. A `str` subclass `prefix` is stored as an
   exact `str` (`str.__str__`), and an `int` subclass `omitted` is stored
   as an exact `int` (`int.__index__`), so a subclass with a lying `__le__`
   cannot store a non-positive count; the `<= 0` check runs on the
   normalized value.
4. **Given** `MemoryIndex(entries=(FileEntry(...), ...), capped=())`, **Then**
   it is a frozen dataclass whose `entries` is a `tuple[FileEntry, ...]` and
   `capped` a `tuple[CappedPrefix, ...]`; both default to `()`, so
   `MemoryIndex()` is the empty index.
5. **Given** `entries` or `capped` whose exact type is not `tuple` (a
   `list`, or a `tuple` subclass), **Then** `TypeError`. **Given** an
   `entries` member whose real type is not `FileEntry`, or a `capped`
   member whose real type is not `CappedPrefix`, **Then** `TypeError`.
   **Given** two `capped` members with the same `prefix`, or two `entries`
   members with the same `path`, **Then** `ValueError`. Member *contents*
   are not validated beyond that: `FileEntry` validates nothing itself, and
   the correctness of remote-built `MemoryFile`, `FileEntry`, and
   `ListPage` values is an AIE-1045 parity case.
6. **Given** two `MemoryIndex` values with equal fields, **Then** they are
   equal and hash equal; values differing in any field compare unequal.

---

### User Story 4 - Module boundaries and packaging (Priority: P1)

**Acceptance Scenarios**:

1. **Given** `src/wenchang/transport.py`, **When** parsed with `ast`,
   **Then** its `wenchang` imports are only `wenchang.core`,
   `wenchang.file_format`, and `wenchang.version_token`, none under
   `TYPE_CHECKING`, and the module has no `from __future__ import
   annotations`. It imports nothing from `wenchang.storage`,
   `wenchang.identity`, `wenchang.scope`, `wenchang.testing`, or `google`.
2. **Given** `src/wenchang/core.py`, **Then** it does not import
   `wenchang.transport`. (Regression guard; green before the change.)
3. **Given** every file under `src/wenchang/`, **Then** none matches the
   regex `AIE-\d+`. (Regression guard; green before the change.)

### Edge Cases

- A `Protocol` with `@runtime_checkable` checks method presence only, not
  signatures. Signature mirroring is enforced by the parity test (US1.3),
  not at runtime; the conformance suite (AIE-1045) checks behavior.
- `MemoryStore` will satisfy the protocol structurally once AIE-1046 adds
  `get_memory_index`. That is intended: the in-process client may be a thin
  wrapper or `MemoryStore` itself. AIE-1046's spec adds the positive
  `isinstance` check; this spec does not pin today's gap.
- `scope_map` is a plain `Mapping[str, str]`, the shape `Identity.scope_map`
  returns, not an `Identity`. The transport carries no identity or
  credentials per call; the tool layer resolves identity and checks writes
  before calling the client. A remote client binds whatever it needs to
  authenticate at construction (per session or connection), so the protocol
  stays identity-free.
- Behavior for an empty `scope_map`, a key or value that is not a valid
  segment, or a scope with no files is defined by
  `MemoryStore.get_memory_index` in AIE-1046. This protocol fixes only the
  signature.
- A buggy or hostile client may return the wrong type, raise its own
  exception types, or issue cursors that are not stable across calls. The
  tool layer does not re-validate client return values; return-type,
  error-type, and cursor parity are AIE-1045 conformance cases. The only
  client-built values this issue validates are `CappedPrefix` and
  `MemoryIndex`, since a remote client constructs them from deserialized
  data.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `wenchang.transport` MUST export `TransportClient`, a
  `@runtime_checkable` `typing.Protocol` with exactly the seven methods in
  US1.2.
- **FR-002**: The six existing operations MUST mirror the `MemoryStore`
  signatures exactly (US1.3). `get_memory_index` MUST have the signature in
  US1.4.
- **FR-003**: `wenchang.core` MUST export `CappedPrefix(prefix: str,
  omitted: int)` and `MemoryIndex(entries: tuple[FileEntry, ...] = (),
  capped: tuple[CappedPrefix, ...] = ())`, both frozen dataclasses, with the
  validation in US3.2, US3.3, and US3.5. Member and scalar type checks use
  the real type (`issubclass(type(x), ...)`), never `isinstance`; the two
  container fields require exact `tuple` (`type(x) is tuple`); `str` and
  `int` scalars are normalized to exact types; and `TypeError` precedes
  `ValueError`.
- **FR-004**: The protocol class docstring MUST state the error-parity
  contract exactly as in US1.5, naming the non-taxonomy exception types.
  The module MUST cite no Linear IDs.
- **FR-005**: `wenchang.transport` MUST import from `wenchang` only `core`,
  `file_format`, and `version_token`, at module level (no `TYPE_CHECKING`
  guard, no `from __future__ import annotations`); `core` MUST NOT import
  `transport`.

## Success Criteria *(mandatory)*

- **SC-001**: Every scenario above has a test under `tests/` citing
  AIE-1048, and `make check` passes.

## Assumptions

- Synchronous methods, matching `MemoryStore`. An async transport, if ever
  needed, is a separate protocol; wrapping sync in a thread is the host's
  concern.
- The index types live in `core` because `get_memory_index` is core API
  (Notion §5) and the in-process client returns core's value unchanged;
  defining them here lets the protocol name its return type before the
  core method exists (AIE-1046).
- `MemoryIndex.entries` is already in the documented order (Notion §5:
  `system/` areas first; then remaining scopes in the configured priority
  order, or as one tier if none; within each tier by `last-updated`, most
  recent first). The type does not re-sort or validate ordering.
- Error parity means reproducing, for well-typed arguments, every
  exception type core raises, including `ValueError`,
  `MetadataFormatError`, and `UnicodeDecodeError` (with its attributes, so
  the offending bytes and position travel too). This is Notion §10.2's
  "every error" read literally; no deviation. A remote client may validate
  arguments locally to raise the `ValueError` cases before any network
  call, as long as the type and message match. Wrongly typed arguments
  (`read_file(None)`) are outside the contract: core's behavior there is
  incidental (`AttributeError` from `None.split`), and pyright is the
  guard. Transport-level failures map to `BackendUnavailableError`, which
  is already how `GcsStorage` treats its own backend's failures.
