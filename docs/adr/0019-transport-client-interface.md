# 0019. Transport client interface

Date: 2026-10-01

## Status

Accepted

## Context

The Notion spec (Section 7) says the agent-facing tool layer is thin and
transport-agnostic: tool bodies "call an abstract client interface" that
"mirrors the core API: read, write, list, append, replace_fact, delete,
get_memory_index", with a concrete implementation injected at startup
(in-process now, remote such as gRPC later), and further transports added
"without touching tool definitions". Section 5 defines
`get_memory_index(scope_map)`: merged metadata across every scope in a
scope-name → entity-ID map, in one call, under a byte cap, in a documented
order, with a `capped` section listing each prefix not fully returned and
its omitted count. Section 10.2 requires the in-process and remote
implementations to be "behaviorally indistinguishable", including "Error
parity. Every error surfaces in the same category with the same payload
across implementations."

AIE-1048 defines that interface so the in-process client (AIE-1046), the
tool layer (AIE-1044), and the transport conformance harness and cases
(AIE-1047, AIE-1045) have one contract to build on. It ships no
implementation and no wiring.

AIE-1044's issue text carries the index semantics (64 KB byte cap,
`system/`-first ordering, optional scope priority, `capped` section). The
in-process client must pass the index conformance cases and cannot pass
through a `MemoryStore.get_memory_index` that does not exist, so the
implementation of `MemoryStore.get_memory_index` is rescoped to AIE-1046,
alongside the in-process client. AIE-1044 is the tool layer only,
including the `get_memory_index` tool that calls the client.

## Decision

Add `wenchang.transport` exporting `TransportClient`, and add the index
value types `CappedPrefix` and `MemoryIndex` to `wenchang.core`.
`transport` imports from `wenchang` only `core`, `file_format`, and
`version_token`; `core` does not import `transport`.

1. **A runtime-checkable `Protocol`, not an ABC.** This matches `Storage`
   and `IdentityResolver`. An adopter's remote client needs no base class
   from this package, and `MemoryStore` may satisfy the protocol
   structurally once it gains `get_memory_index`.
   - **Rejected: an ABC with `@abstractmethod`**, which forces inheritance
     and adds nothing a type checker does not already enforce.
2. **The six existing operations mirror `MemoryStore` exactly, pinned by a
   test.** `read_file`, `write_file`, `append_line`, `replace_fact`,
   `list_prefix`, and `delete_file` have the same parameter names, kinds,
   defaults, annotations, and return types as the `MemoryStore` methods,
   checked by comparing `inspect.signature(..., eval_str=True)` for each
   pair. So the tool layer is written once against `TransportClient`, and
   the in-process client can be a pure pass-through. To keep evaluated
   annotations identical objects, `transport.py` has no `from __future__
   import annotations` and imports its annotation types at module level,
   not under `TYPE_CHECKING`; a test scans for both.
   - **Rejected: a flatter, transport-friendly shape** (e.g. `metadata` as a
     dict), which would leak the remote transport's reshaping into the
     in-process path and defeat Section 10.2's parity goal.
3. **`get_memory_index(scope_map: Mapping[str, str]) -> MemoryIndex` is in
   the protocol now.** Section 7 lists it and Section 10.2 tests it through
   the transport suite. Its return type `MemoryIndex` and row type
   `CappedPrefix` are defined in `core`, because the method is core API
   (Section 5) and a client returns core's value unchanged. Defining them
   now lets the protocol name its return type before
   `MemoryStore.get_memory_index` exists; that method, with the byte cap,
   priority order, and `capped` semantics, is implemented with the
   in-process client, as described in Context.
   - **Rejected: a six-method protocol with the index added later**, which
     would ship a contract Section 7 calls incomplete and force a second
     protocol change.
4. **Index entries reuse `FileEntry`.** The index is merged metadata, which
   is exactly path, metadata, and version. `MemoryIndex.entries` is a
   `tuple[FileEntry, ...]` already in load order (`system/` areas across all
   scopes first; then the remaining scopes in the configured priority order,
   or as one tier if none; within each tier by `last-updated`, most recent
   first); the type does not re-sort or check the order. An empty `capped`
   means the index is complete.
   - **Rejected: a new `IndexEntry` type** duplicating `FileEntry`.
5. **Synchronous.** This matches core. A remote client blocks on its RPC as
   `GcsStorage` blocks on HTTP.
   - **Rejected: async methods**, which would force every in-process caller
     through an event loop for no I/O gain. An async transport, if ever
     needed, is a separate protocol.
6. **Identity-agnostic; credentials bind at client construction.**
   `get_memory_index` takes a plain `Mapping[str, str]`, the
   `Identity.scope_map` shape, and no method carries identity or
   credentials. The tool layer resolves identity and calls
   `scope.check_write` before any mutating client call. A remote client
   authenticates with whatever it was constructed with (per session or
   connection), so a server can enforce scope on its side without a
   per-call identity parameter.
   - **Rejected: an `identity` parameter on every method**, which would
     make the in-process pass-through carry a value `MemoryStore` ignores.
7. **Error parity covers every exception type core raises for well-typed
   arguments.** Python cannot type raised exceptions, so the protocol class
   docstring states the contract: each mirrored method raises exactly the
   exception types the matching `MemoryStore` method raises, with equal
   attributes and message. That covers the `wenchang.errors` taxonomy (same
   category and payload) and the non-taxonomy types: `ValueError` (empty
   `source` or `old_string`, a non-fact `line`, a malformed or foreign
   `cursor`), `MetadataFormatError`, and `UnicodeDecodeError`. A remote
   client may raise the `ValueError` cases locally before any network call,
   as long as type and message match. Failures of the transport itself (RPC
   timeout, refused connection, crashed server) have no core equivalent and
   surface as `BackendUnavailableError` with the matching `TransientReason`,
   as `GcsStorage` already does for its backend. Wrongly typed arguments are
   outside the contract; pyright is the guard there. This reads Section
   10.2's "every error" literally, so it is not a deviation.
   - **Rejected: folding the non-taxonomy errors into a `wenchang.errors`
     category for remote transports**, which would deviate from Section 10.2
     on exactly the cases most likely to diverge.
   - **Rejected: letting a transport library's own exception** (e.g.
     `grpc.RpcError`) propagate, which the tool layer could not categorize.
8. **`CappedPrefix` and `MemoryIndex` validate types at construction**, as
   `identity` does (ADR 0014, decision 9), because a remote client builds
   them from deserialized data. All `TypeError` checks run before any
   `ValueError` check. The two `CappedPrefix` scalars are type-tested by
   real type (`issubclass(type(x), ...)`, never the spoofable `__class__`)
   and then normalized. The two `MemoryIndex` container fields and their
   members must be exact types (`type(x) is tuple`, `FileEntry`, or
   `CappedPrefix`): a subclass of any of them can lie through `__iter__`,
   `__getattribute__`, `__eq__`, or `__hash__`, for example a `FileEntry`
   subclass whose `path` differs on each read, defeating the duplicate
   checks or equality. `bool` is rejected for `omitted`. A `str` subclass
   `prefix` is stored as an exact `str` (`str.__str__`) and an `int`
   subclass `omitted` as an exact `int` (`int.__index__`) before the value
   checks, so a lying `__le__` cannot store a non-positive count. A prefix
   failing `is_valid_prefix`, `omitted <= 0`, duplicate `capped` prefixes,
   and duplicate `entries` paths raise `ValueError`. Member contents are not
   validated: `FileEntry` validates nothing itself.
   - **Rejected: leaving the two new types unvalidated**, which would make
     the one shape this change introduces the one a remote client can
     corrupt silently.
   - **Rejected: accepting `FileEntry` and `CappedPrefix` subclasses as
     members** (real-type `issubclass` checks), the original design. An
     adversarial code review showed a subclass with a lying
     `__getattribute__` or `__eq__` passes the type check and then defeats
     duplicate detection and value equality. Unlike the scalars, a
     dataclass member has no cheap normalization to its base type, so
     exact types are required instead.
   - **Rejected: also hardening `MemoryFile`, `FileEntry`, and `ListPage`**
     here. A remote client builds those from deserialized data too, but
     their correctness across transports is a conformance-suite parity case
     (AIE-1045), not part of this contract.

### Orchestrator decisions pending human review

Three of the above were made by the orchestrator at spec review without
escalation. They are reversible and are flagged for the human at PR
review; this section is updated once they are confirmed or changed.

- **Error parity binds every future remote transport** (decision 7): for
  well-typed arguments a remote client must reproduce `ValueError`,
  `MetadataFormatError`, and `UnicodeDecodeError` exactly (type,
  attributes, message), and map its own failures to
  `BackendUnavailableError`.
- **The index algorithm is built with the in-process client** (decision 3
  and Context): the semantics written on AIE-1044 are implemented under
  AIE-1046; AIE-1044 is tools only. This is realized by
  [ADR 0020](0020-memory-index-and-in-process-client.md), which implements
  `MemoryStore.get_memory_index` alongside `InProcessClient`.
- **A remote client binds credentials once at construction, never per
  call** (decision 6), so the protocol stays identity-free.

## Consequences

Tools (AIE-1044) can be written once against `TransportClient`, and the
in-process client (AIE-1046) can be a pass-through to `MemoryStore`, or
`MemoryStore` itself once it gains `get_memory_index`. Any signature drift
between the protocol and `MemoryStore` fails a test rather than surfacing
in a transport. `runtime_checkable` checks only method presence, so a
client with a wrong signature still passes `isinstance`; pyright catches
that for typed adopters, and the conformance suite (AIE-1047, AIE-1045)
checks behavior and error parity, which no type can express.

Every remote transport carries a real cost: it must serialize and rebuild
non-taxonomy exceptions, including `UnicodeDecodeError` with its offending
bytes and position, and must map all of its own failures to
`BackendUnavailableError`. Because no method carries identity, a remote
transport needs a session- or connection-level authentication story of its
own.

`MemoryIndex`'s field shape is fixed before its producer exists; if
AIE-1046 needs more, it extends the type additively. Remote-built
`CappedPrefix` and `MemoryIndex` values cannot be malformed in type or
uniqueness, but `MemoryFile`, `FileEntry`, and `ListPage` remain
unvalidated and rely on conformance testing. Validation runs only in
`__post_init__`: a `CappedPrefix` built around it (e.g. via
`object.__new__`) is not re-validated by `MemoryIndex`, and a `FileEntry`'s
contents, including a `str`-subclass `path`, are not validated at all. A
legitimate adopter subclass of `FileEntry` or `CappedPrefix` cannot be
placed in a `MemoryIndex`.
