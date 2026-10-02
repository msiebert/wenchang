# Spec Review: AIE-1046 — in-process client and memory index

## What & why

Notion §7 wants an in-process transport that "calls the core functions
directly with no network", and §5 wants `get_memory_index`, the session
bootstrap that merges metadata across every scope under a 64 KB byte cap.
ADR 0019 assigned the index implementation here so the in-process client
can pass the index conformance cases. This adds
`MemoryStore.get_memory_index` with two construction settings
(`index_max_bytes`, `scope_priority`) and a public `index_entry_bytes`
cost function, plus `transport.InProcessClient`, a pass-through wrapper.
`MemoryStore` itself now satisfies `TransportClient` too.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | files under two scopes in the map, plus files in other entities/scopes | `get_memory_index(scope_map)` | exactly the in-map files, equal to `list_prefix` entries; others absent |
| 2 | `list_page_size=2`, five files | index | all five (pages drained) |
| 3 | empty map | index | `MemoryIndex()`, storage untouched |
| 4 | corrupt metadata / backend failure | index | `MetadataFormatError` / `BackendUnavailableError` propagate unwrapped |
| 5 | mixed `system/` and other areas, no priority | index | all `system/` entries first by recency; rest one flat tier by recency; ties by path |
| 6 | `scope_priority=("org","user")` | index | non-system `org` entries before `user` regardless of age; unlisted scopes one trailing tier |
| 7 | cap equal to total | index | all included, `capped == ()` (inclusive) |
| 8 | cap one byte short | index | last entry omitted; `capped == (CappedPrefix("<scope>/<entity>/<area>/", 1),)` |
| 9 | third entry doesn't fit but fourth would | index | third, fourth, fifth all omitted (stop at first miss) |
| 10 | omitted across three areas | index | `capped` sorted by prefix string with counts |
| 11 | `index_entry_bytes(reference entry)`; `é` alias; `é` description | compute | `85`, `93` (JSON escape), `86` (path + canonical metadata map keys/values + version, UTF-8 with `surrogatepass`) |
| 12 | `index_max_bytes <= 0`; bad `scope_priority` (bare `str`/`bytes`, non-str member, invalid segment, dup) | construct | `ValueError` / `TypeError`, all `TypeError`s first; list accepted and stored as tuple |
| 13 | `scope_map` non-Mapping / non-str key or value / invalid segment / duplicate after normalization | index | `TypeError` / `ValueError`, all `TypeError`s first, storage never called (every-method-raises storage) |
| 13a | storage whose `get` raises; malformed-first page with `list_page_size=1`; `u-10` vs `u-1`; extreme stored timestamp; lone surrogate; `list_prefix` overridden in a subclass | index | never reads bodies; drains past empty pages; prefix-aligned; `MetadataFormatError`; path/description 3 bytes, alias/source 6-byte escape; base method used |
| 14 | `InProcessClient(store)` | each of seven methods | returns the store's object (`is`), same args; exceptions propagate unwrapped; `isinstance(client, TransportClient)` and `isinstance(store, TransportClient)` |
| 15 | `InProcessClient(object())` | construct | `TypeError` |
| 16 | `core.py` | ast | does not import `scope` or `transport`; `INDEX_SYSTEM_AREA == scope.SYSTEM_AREA` |
| 17 | fake-gcs-server | integration | fan-out drains pages and caps correctly on `GcsStorage` |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| Cap and priority are `MemoryStore` construction settings | Per-call parameters | Transport signature is fixed (ADR 0019); matches `list_page_size` (ADR 0010) |
| Entry cost = UTF-8 bytes of path + metadata map keys/values + version, as public `index_entry_bytes` | Count descriptions only; count a JSON rendering | Deterministic, predictable by tools and the conformance suite; measures the only encoding the library defines |
| Stop at the first entry that doesn't fit | Best-fit packing | Returned entries are an exact prefix of the documented order |
| Capped prefixes are areas, sorted by string | Per-scope or per-file | Area is what `list_prefix` takes to recover |
| Flat default; listed scopes tiered in order; unlisted scopes one trailing tier; ties by path | Alphabetical unlisted scopes | §3 forbids privileging a scope by name; total order for exact assertions |
| `core`-local `INDEX_SYSTEM_AREA` pinned equal to `scope.SYSTEM_AREA` by test | `core` imports `scope`; move constant to `paths` | `core`/`scope` independence invariant; wider change deferred |
| `InProcessClient` wrapper plus `MemoryStore` satisfying the protocol | Only `MemoryStore` | A named reference implementation for hosts and the suite |
| Recorded in ADR 0020 | — | Core API growth, new transport implementation |

## Files/modules to be touched

- `src/wenchang/core.py`, `src/wenchang/transport.py`
- `tests/test_core_index_bytes.py`, `tests/test_core_get_memory_index.py`, `tests/test_transport_inprocess.py`, `tests/integration/test_gcs_memory_index.py` (new)
- `ARCHITECTURE.md`, `docs/adr/0020-*.md`, `docs/adr/0010-*.md` (update line), `docs/product/glossary.md`

## Open questions / assumptions

- **Orchestrator calls, decided at this checkpoint without blocking on
  you** (override at the PR; the ADR records them as pending your review):
  1. **Byte accounting** counts the canonical `metadata_to_map` rendering
     plus path and version. Core owns no other rendering; a cap measured
     on the tool's rendering cannot live below the tool layer.
  2. **Stop-at-first-miss**, so returned entries are an exact prefix of
     the order. One pathological entry (huge alias list on a top-ranked
     file) can empty the index; the agent still gets exact `capped`
     prefixes to recover from.
  3. **Unlisted scopes form one trailing tier** after listed scopes.
  4. **`capped` prefixes are areas**, the unit `list_prefix` takes.
- Index is not a snapshot (ADR 0010); unchanged here.
- Branch must be rebased onto the final AIE-1048 commit before building
  (tasks.md precondition).

## Risks

- `index_entry_bytes` measures the canonical `metadata_to_map` rendering,
  not the bytes stored and not what a tool renders; a verbose renderer
  exceeds the cap by a bounded factor. The cap is a tripwire, not a
  context-budget guarantee.
- Draining every page of every scope is O(files); acceptable at the
  ~400-file scale the cap implies, and the cap does not short-circuit the
  listing (ordering needs the full set).
