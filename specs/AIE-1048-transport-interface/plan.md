# Implementation Plan: Abstract transport client interface

**Linear issue**: AIE-1048 | **Branch**: `AIE-1048-transport-interface` | **Date**: 2026-10-01 | **Spec**: [spec.md](spec.md)

## Summary

Add `src/wenchang/transport.py` with the `TransportClient` protocol. Add
`CappedPrefix` and `MemoryIndex` to `src/wenchang/core.py`. Two new test
files. No behavior change anywhere.

## Technical Context

Python ≥ 3.12; pyright strict; ruff line length 100. `wenchang.transport`
imports `typing.Protocol`, `typing.runtime_checkable`,
`collections.abc.Mapping`, and from `wenchang`: `core` (`MemoryFile`,
`ListPage`, `ListCursor`, `MemoryIndex`), `file_format` (`FileMetadata`),
`version_token` (`VersionToken`). `core` gains `is_valid_prefix` usage
(already imported from `paths`) for `CappedPrefix` validation.

## Constitution Check

| Principle | Status |
| --------- | ------ |
| I. Tests-first | T1, T2 each test-writer → implementer |
| II. Tests not negotiable | No existing test changes |
| IV. Strict typing | Protocol methods fully annotated; `...` bodies |
| V. Storage only through interface | No storage access |
| VI. Spec fidelity | Implements §7's interface list including `get_memory_index` (§5). Index types defined ahead of the core method: ADR 0019 |
| VII. Architecture documented | New public module and two core types → ARCHITECTURE.md + ADR 0019 |
| VIII. Traceability | Test docstrings cite AIE-1048; shipped modules cite none |
| IX. Small PR | One new module, two dataclasses, two test files |

**Decisions to record in ADR 0019:**

1. **A `Protocol`, not an ABC.** Matches `Storage` and `IdentityResolver`.
   An adopter's gRPC client needs no base class from this package, and
   `MemoryStore` itself may satisfy it structurally once it grows
   `get_memory_index`. Rejected: an ABC with `@abstractmethod`, which forces
   inheritance and adds nothing a type checker doesn't already enforce.
2. **Signatures mirror `MemoryStore` exactly, pinned by a test.** Notion §7
   says the interface "mirrors the core API"; an exact mirror means the tool
   layer is written once against `TransportClient` and the in-process client
   can be a pure pass-through. Rejected: a flatter transport-friendly shape
   (e.g. `metadata` as a dict), which would make the remote transport's
   reshaping leak into the in-process path and defeat §10.2's parity goal.
3. **`get_memory_index` is in the protocol now.** §7 lists it; §10.2 tests
   it through the transport suite. Its return type `MemoryIndex` and the
   `CappedPrefix` row type are defined in `core` in this issue, because the
   method is core API (§5) and the client returns core's value unchanged.
   `MemoryStore.get_memory_index` itself is implemented in AIE-1046 (the
   in-process client must pass the index conformance cases), with the byte
   cap, priority order, and `capped` semantics stated on AIE-1044. Rejected:
   a six-method protocol with the index added later, which would ship a
   contract §7 says is incomplete and force a second protocol change.
4. **Index entries reuse `FileEntry`.** The index is "merged metadata",
   which is exactly path + metadata + version. Rejected: a new `IndexEntry`
   type duplicating `FileEntry`.
5. **Synchronous.** Matches core. Rejected: async methods, which would force
   every in-process caller through an event loop for no I/O gain; a remote
   client can block on its RPC like `GcsStorage` blocks on HTTP.
6. **Identity-agnostic; credentials bind at client construction.**
   `get_memory_index` takes `Mapping[str, str]`, the `Identity.scope_map`
   shape. No method carries identity or credentials: the tool layer
   resolves identity and calls `scope.check_write` before any mutating
   client call (ARCHITECTURE: `tools --> scope`, `tools --> transport`). A
   remote client authenticates with whatever it was constructed with (per
   session or connection), so the server can enforce scope on its side
   without a per-call identity parameter, and the protocol never needs
   one. Rejected: an `identity` parameter on every method, which would make
   the in-process pass-through carry a value `MemoryStore` ignores.
7. **Error parity is a documented contract covering every exception type
   core raises for well-typed arguments.** Python cannot type raised
   exceptions; the protocol docstring states that each mirrored method
   raises exactly the exception types the matching `MemoryStore` method
   raises, with equal attributes and message: the `wenchang.errors`
   taxonomy (same category and payload) and the non-taxonomy types,
   including `ValueError` (empty `source` or `old_string`, non-fact `line`,
   malformed or foreign `cursor`), `MetadataFormatError`, and
   `UnicodeDecodeError`. Failures of the transport itself (RPC timeout,
   refused connection, crashed server) have no core equivalent and surface
   as `BackendUnavailableError` with the matching `TransientReason`, as
   `GcsStorage` already does for its backend. Wrongly typed arguments are
   outside the contract. This reads Notion §10.2's "every error"
   literally. AIE-1045 asserts it. Rejected: folding the non-taxonomy
   errors into a `wenchang.errors` category for remote transports, which
   would be a §10.2 deviation and would let the in-process and remote paths
   diverge on exactly the cases §10.2 says are most likely to diverge.
   Also rejected: letting a transport library's own exception (e.g.
   `grpc.RpcError`) propagate, which the tool layer could not categorize.
8. **`CappedPrefix` and `MemoryIndex` validate types at construction**, as
   `identity` does (ADR 0014 §9), because a remote client builds them from
   deserialized data. Real-type checks (`issubclass(type(x), ...)`) for
   the two scalars, which are then normalized; exact types for the two
   container fields and their members (a `tuple`, `FileEntry`, or
   `CappedPrefix` subclass can lie through `__iter__`, `__getattribute__`,
   `__eq__`, or `__hash__`, defeating the duplicate checks or equality),
   `bool` rejected for `omitted`, `str` subclass prefix normalized with
   `str.__str__`, `int` subclass `omitted` normalized with `int.__index__`
   before the `<= 0` check, duplicate `capped` prefixes and duplicate
   `entries` paths rejected. Member contents are not validated:
   `FileEntry` validates nothing, and hardening the existing core value
   types (`MemoryFile`, `FileEntry`, `ListPage`, which a remote client also
   builds from deserialized data) is out of scope; their correctness is an
   AIE-1045 parity case. Rejected: leaving the two new types unvalidated,
   which would make the one shape this issue introduces the one a remote
   client can corrupt silently.

## Public interface

### `src/wenchang/core.py` additions

Placed after `ListPage`:

```python
@dataclass(frozen=True)
class CappedPrefix:
    """A prefix the memory index could not return in full.

    `omitted` is how many files under `prefix` were left out. The agent can
    call `list_prefix(prefix)` to page through them.
    """

    prefix: str
    omitted: int

    def __post_init__(self) -> None:
        # In order:
        # TypeError if not issubclass(type(self.prefix), str)
        # TypeError if issubclass(type(self.omitted), bool) or not issubclass(type(self.omitted), int)
        # object.__setattr__(self, "prefix", str.__str__(self.prefix))      # exact str
        # object.__setattr__(self, "omitted", int.__index__(self.omitted))  # exact int
        # ValueError(f"invalid prefix: {self.prefix!r}") if not is_valid_prefix(self.prefix)
        # ValueError(f"omitted must be positive, got {self.omitted}") if self.omitted <= 0
        ...


@dataclass(frozen=True)
class MemoryIndex:
    """Merged metadata across every scope in a scope map, in load order.

    `entries` is already ordered: system/ areas across all scopes first;
    then the remaining scopes in the configured priority order, or as one
    tier if none is configured; within each tier by last-updated, most
    recent first. `capped` lists every prefix not fully returned once the
    byte budget was reached; an empty `capped` means the index is complete.
    """

    entries: tuple[FileEntry, ...] = ()
    capped: tuple[CappedPrefix, ...] = ()

    def __post_init__(self) -> None:
        # TypeError if type(self.entries) is not tuple, or type(self.capped) is not tuple
        # TypeError for any entries member with type(e) is not FileEntry
        # TypeError for any capped member with type(c) is not CappedPrefix
        # ValueError(f"duplicate entry path: {p!r}") if two entries share a path
        # ValueError(f"duplicate capped prefix: {p!r}") if two capped members share a prefix
        ...
```

Default `__eq__` and `__hash__` (tuples of frozen dataclasses are
hashable; `FileMetadata` holds a `tuple`, a `frozenset`, and a `datetime`,
all hashable). `__post_init__` on a frozen dataclass assigns the
normalized `prefix` and `omitted` via `object.__setattr__`, as `identity`
does.

### `src/wenchang/transport.py`

```python
"""Transport-agnostic client contract mirroring the core API.

The tool layer calls a `TransportClient`; a concrete implementation is
injected at startup. The in-process implementation calls `MemoryStore`
directly; a remote implementation (for example gRPC) calls a service that
wraps one. Both must be behaviorally indistinguishable, which the transport
conformance suite in `wenchang.testing` checks.
"""

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from wenchang.core import ListCursor, ListPage, MemoryFile, MemoryIndex
from wenchang.file_format import FileMetadata
from wenchang.version_token import VersionToken

__all__ = ["TransportClient"]


@runtime_checkable
class TransportClient(Protocol):
    """The seven memory operations over any transport.

    Each of the six operations that `MemoryStore` already implements mirrors
    the `MemoryStore` method of the same name: the same parameters, the same
    return type, and, for well-typed arguments, exactly the same exception
    types with equal attributes and message. That covers the
    `wenchang.errors` taxonomy (same category, same payload) and the
    non-taxonomy errors core raises, including `ValueError` for an empty
    `source` or `old_string`, a `line` that is not a fact line, or a
    malformed or foreign `cursor`; `MetadataFormatError` for corrupt stored
    metadata; and `UnicodeDecodeError` for a non-UTF-8 body. A client never
    reshapes an error into its own vocabulary: a version conflict is a
    `VersionConflictError` carrying current content and version whether it
    came from an in-process call or a remote one. A failure of the
    transport itself (a timeout, a refused connection, a crashed server)
    surfaces as `BackendUnavailableError` with the matching
    `TransientReason`. `get_memory_index` follows
    `MemoryStore.get_memory_index` the same way.
    """

    def read_file(self, path: str) -> MemoryFile:
        """Return the file at `path` with its metadata and version token."""
        ...

    def write_file(
        self,
        path: str,
        content: str,
        metadata: FileMetadata,
        expected_version: VersionToken | None,
        *,
        source: str,
    ) -> MemoryFile:
        """Replace the whole file, or create it when `expected_version` is None."""
        ...

    def append_line(
        self, path: str, line: str, expected_version: VersionToken, *, source: str
    ) -> MemoryFile:
        """Append one fact line to an existing file at `expected_version`."""
        ...

    def replace_fact(
        self,
        path: str,
        old_string: str,
        new_string: str,
        expected_version: VersionToken,
        *,
        source: str,
    ) -> MemoryFile:
        """Replace the unique occurrence of `old_string` with `new_string`."""
        ...

    def list_prefix(self, prefix: str, cursor: ListCursor | None = None) -> ListPage:
        """Return one page of file metadata under `prefix`, without content."""
        ...

    def delete_file(self, path: str, expected_version: VersionToken) -> None:
        """Delete the file at `path` if it is still at `expected_version`."""
        ...

    def get_memory_index(self, scope_map: Mapping[str, str]) -> MemoryIndex:
        """Return merged metadata across every scope in `scope_map`, byte-capped."""
        ...
```

The implementer copies the six existing signatures from `core.py`
verbatim (parameter names, kinds, defaults, annotations), because the
parity test compares `inspect.signature(..., eval_str=True)` objects.
`core.py` has no `from __future__ import annotations` and no string
annotations; `transport.py` must have neither, and must import its
annotation types at module level (not under `TYPE_CHECKING`), so the
evaluated annotations are the same objects. `Mapping` is
`collections.abc.Mapping`. Verified: `ListCursor` and `VersionToken` are
the same `NewType` objects when imported, `VersionToken | None` unions
compare equal, and `self` is unannotated on both sides.

### ARCHITECTURE.md

`transport` moves from *(planned)* to implemented: the protocol, the
mirror rule, error parity including the non-taxonomy types,
identity-agnosticism with credentials bound at client construction, and
that nothing calls it yet. `core` gains `CappedPrefix` and `MemoryIndex`
with a note that `get_memory_index` remains *(planned)* for AIE-1046. The
sentence "the tool and transport layers will call `resolve_identity`" is
corrected to the tool layer only. The diagram keeps
`tools --> transport --> core`.

## Test layout

Both files carry `pytestmark = pytest.mark.unit` and docstrings citing
AIE-1048 and the scenario ID.

- `tests/test_transport_protocol.py` (US1, US2, US4):
  - US1.1–2: import, `__all__`, method-name set computed as `{n for n, v in
    vars(TransportClient).items() if callable(v) and not
    n.startswith("_")}` (not `dir()`, whose Protocol internals vary by
    Python version; not `get_protocol_members`, which is 3.13+).
  - US1.3: parametrized over the six names, `inspect.signature(getattr(
    TransportClient, m), eval_str=True) == inspect.signature(getattr(
    MemoryStore, m), eval_str=True)`.
  - US1.4: `inspect.signature(TransportClient.get_memory_index,
    eval_str=True) == inspect.signature(_Ref.get_memory_index,
    eval_str=True)` where `_Ref` is a local class with `def
    get_memory_index(self, scope_map: Mapping[str, str]) -> MemoryIndex:
    raise NotImplementedError`, `Mapping` from `collections.abc`. A method
    is used because its `self` needs no annotation under pyright strict
    and compares equal to the Protocol method's unannotated `self`; a
    module-level `def _ref(self: object, ...)` does not compare equal, and
    an unannotated one fails strict mode.
  - US1.5: every method `__doc__` non-empty; class `__doc__` contains
    `MemoryStore`, `wenchang.errors`, `ValueError`, `MetadataFormatError`,
    `UnicodeDecodeError`, `BackendUnavailableError`.
  - US2.1: a local `_FullClient` with seven trivial methods (raising
    `NotImplementedError`) passes `isinstance`; `client: TransportClient =
    _FullClient()` as a module-level annotated assignment type-checks under
    `make typecheck`. Bind the instance to `candidate: object` before
    `isinstance`, as `tests/test_identity.py` does.
  - US2.2: parametrized over the seven names, a class built with
    `type("Partial", (), namespace)` whose namespace maps every *other*
    method name to one annotated stub `def _stub(self: object, *args:
    object, **kwargs: object) -> NoReturn` fails `isinstance`. Lambdas in
    the namespace fail pyright strict (`reportUnknownLambdaType`).
  - US2.3: `TransportClient()` raises `TypeError`.
  - US4.1–2: `ast` scan of `transport.py` (imports, no `TYPE_CHECKING`
    guard, no `__future__`) and `core.py` import nodes.
  - US4.3: regex scan of `src/wenchang/**/*.py` for `AIE-\d+`.
- `tests/test_core_index_types.py` (US3): construction, frozenness,
  `TypeError` then `ValueError` ordering (incl. the mixed case
  `CappedPrefix("", True)`), `bool` rejection, `str`-subclass and
  `int`-subclass normalization (stored types are exactly `str` and `int`;
  an `int` subclass whose `__le__` lies is still rejected when its value is
  non-positive), exact-`tuple` check (a `tuple` subclass raises
  `TypeError`), member type checks, duplicate capped prefix, duplicate
  entry path, defaults, equality and hash, inequality.

## Project Structure

```text
specs/AIE-1048-transport-interface/   spec.md plan.md tasks.md review-spec.md review-pr.md
src/wenchang/transport.py              # new
src/wenchang/core.py                   # CappedPrefix, MemoryIndex
tests/test_transport_protocol.py       # new
tests/test_core_index_types.py         # new
ARCHITECTURE.md
docs/adr/0019-transport-client-interface.md
```

## Complexity Tracking

None.
