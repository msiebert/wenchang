# Spec Review: AIE-1048 — abstract transport client interface

## What & why

Notion §7 says tools call "an abstract client interface" that "mirrors the
core API", with an in-process implementation now and a remote one later.
This adds `wenchang.transport.TransportClient`, a runtime-checkable
`Protocol` with seven methods whose six existing operations are exact
signature mirrors of `MemoryStore`, plus `get_memory_index(scope_map)`. The
index's return types (`MemoryIndex`, `CappedPrefix`) are added to `core`.
Nothing implements or calls the protocol yet: AIE-1046 (in-process client
and `MemoryStore.get_memory_index`), AIE-1044 (tools), AIE-1047/1045
(conformance) build on it.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | `wenchang.transport` | import | exports `TransportClient` in `__all__`; method names are exactly the seven |
| 2 | each of the six existing ops | compare `inspect.signature(..., eval_str=True)` | identical to `MemoryStore.<m>` |
| 3 | `get_memory_index` | inspect | `(self, scope_map: Mapping[str, str]) -> MemoryIndex` |
| 4 | protocol docstrings | read | every method documented; class docstring states error parity for well-typed arguments: exactly the exception types `MemoryStore` raises, incl. `ValueError`, `MetadataFormatError`, `UnicodeDecodeError`; transport failures → `BackendUnavailableError` |
| 5 | a class with all seven methods | `isinstance(x, TransportClient)` | `True`; pyright accepts the assignment (via `make typecheck`) |
| 6 | a class missing any one method | `isinstance` | `False` (parametrized) |
| 7 | `TransportClient()` | instantiate | `TypeError` |
| 8 | `CappedPrefix("user/u-1/notes/", 12)` | build | frozen; `omitted <= 0` or an invalid prefix → `ValueError`; non-`str` prefix or non-`int`/`bool` omitted → `TypeError` first; `str`/`int` subclasses stored as exact types |
| 9 | `MemoryIndex()` | build | frozen; `entries == ()` and `capped == ()`; non-exact-`tuple` fields or non-exact-type members (subclasses included) → `TypeError`; duplicate capped prefix or entry path → `ValueError`; equal values hash equal |
| 10 | `transport.py`, `core.py` | `ast` scan | transport imports only `core`, `file_format`, `version_token` from `wenchang`, at module level, no `__future__`; core does not import transport; no `AIE-\d+` under `src/` |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| `Protocol`, runtime-checkable | ABC with abstract methods | Matches `Storage` and `IdentityResolver`; a gRPC client needs no base class; `MemoryStore` may satisfy it structurally later |
| Exact signature mirror of `MemoryStore`, pinned by a test | Transport-friendly flattened shapes | Tool layer is written once; in-process client is a pure pass-through; §10.2 parity |
| `get_memory_index` in the protocol now; `MemoryIndex`/`CappedPrefix` defined in `core` here; core method implemented in AIE-1046 | Six-method protocol, index later | §7 lists it, §10.2 tests it; shipping an incomplete contract forces a second protocol change. **Sequencing call**: AIE-1044's index semantics are implemented under AIE-1046 so the in-process client can pass the suite; AIE-1044 stays tool-layer only |
| Index entries reuse `FileEntry` | New `IndexEntry` | "Merged metadata" is exactly path + metadata + version |
| Synchronous | async | Matches core; a remote client blocks on RPC like `GcsStorage` blocks on HTTP |
| Identity-agnostic (`Mapping[str, str]` scope map); a remote client binds credentials at construction, never per call | `identity` parameter on every method | Transport never sees grants; tool layer checks writes first; the in-process pass-through would carry a value core ignores |
| Error parity covers every exception type core raises, incl. `ValueError`/`MetadataFormatError`/`UnicodeDecodeError` | Fold non-taxonomy errors into a category for remote clients | §10.2 says "every error"; folding would be a deviation on exactly the cases most likely to diverge |
| `CappedPrefix`/`MemoryIndex` validate types at construction | Leave the two new types unvalidated; harden `MemoryFile`/`FileEntry`/`ListPage` too | A remote client builds them from deserialized data; follows ADR 0014 §9. Existing core value types are out of scope; their remote correctness is an AIE-1045 parity case |
| Recorded in ADR 0019 | — | New public module and core types |

## Files/modules to be touched

- `src/wenchang/transport.py` (new)
- `src/wenchang/core.py`: `CappedPrefix`, `MemoryIndex`
- `tests/test_transport_protocol.py`, `tests/test_core_index_types.py` (new)
- `ARCHITECTURE.md`, `docs/adr/0019-transport-client-interface.md`

## Open questions / assumptions

- Sync-only is assumed. Flag if the host framework will need async tools;
  a wrapper or a separate async protocol would be a later, additive change.
- The scope-priority order and index byte cap are `MemoryStore`
  configuration (AIE-1046), not transport parameters.
- **Orchestrator calls made without escalation** (reversible; flag at the
  PR if you disagree, and the ADR gets approval wording only after you
  sign off):
  1. **Error parity binds every future remote transport**: for well-typed
     arguments, a remote client must reproduce `ValueError`,
     `MetadataFormatError`, and `UnicodeDecodeError` exactly (type,
     attributes, message), and must map its own transport failures to
     `BackendUnavailableError`. This is §10.2 read literally.
  2. The index algorithm written on AIE-1044 is built under AIE-1046 so the
     in-process client can pass the suite; AIE-1044 is tools only.
  3. A remote client binds credentials once at construction, never per
     call, so the protocol stays identity-free.

## Risks

- `runtime_checkable` checks presence, not signatures; a client with a
  wrong signature passes `isinstance`. Mitigated by pyright for typed
  adopters and by the conformance suite for behavior.
- Defining `MemoryIndex` before its producer means its field shape is fixed
  from AIE-1048; AIE-1046 may need to extend it (additively).
