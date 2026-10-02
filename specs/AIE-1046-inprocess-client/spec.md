# Feature Specification: In-process transport client and memory index

**Linear issue**: AIE-1046 — https://linear.app/mixpanel/issue/AIE-1046/in-process-transport-client-implementation

**Feature Branch**: `AIE-1046-inprocess-client` (based on `AIE-1048-transport-interface`)

**Created**: 2026-10-01

**Status**: Draft

**Input**: Linear AIE-1046 ("Implement the transport client interface as an
in-process reference implementation, calling directly into the core library
without a network hop. Must pass the shared transport conformance suite."),
the index semantics carried on AIE-1044 and rescoped here by ADR 0019
("get_memory_index fans out over the caller's resolved scope map and
returns merged metadata across every scope, subject to a configurable
byte-budget cap (defaulting to 64 KB). Under the cap, ordering is: system/
areas across all scopes first, then remaining scopes in an adopter-supplied
priority order (optional, defaults to flat), then by file-level
last-updated within any tier, most recent first. On reaching the cap, the
index degrades rather than truncating silently — it returns a capped
section listing each prefix not fully returned with an omitted count, and
the agent can call list_prefix for any capped area."), and Notion:

- §5: `get_memory_index(scope_map)` "takes a map of scope name to entity ID
  and returns merged metadata across every scope in that map, in one call";
  "The cap is a byte budget on the returned index, defaulting to 64 KB,
  configurable. Bytes rather than a file count, because the cap protects
  context budget"; "Step three is the sole use of the file-level
  timestamp."
- §7: "In-process — calls the core functions directly with no network. The
  fastest iteration loop and the simplest adoption path."
- §10.2: "Index behavior. get_memory_index fans out over an arbitrary scope
  map; under the byte cap it applies the documented ordering and reports
  every omitted prefix with a count."

Builds on `TransportClient`, `MemoryIndex`, `CappedPrefix` (AIE-1048, ADR
0019), `MemoryStore` and `list_prefix` (ADR 0007, 0010), `build_prefix` /
`parse_path` (ADR 0015), and `SYSTEM_AREA` (ADR 0016).

## Summary

Two additions.

1. `MemoryStore.get_memory_index(scope_map) -> MemoryIndex`, with two new
   constructor settings, `index_max_bytes` (default 65536) and
   `scope_priority` (default empty). It fans out over every scope in the
   map, drains every page of `list_prefix` under `{scope}/{entity_id}/`,
   orders the merged entries (`system/` areas first, then scopes in
   priority order with unlisted scopes as one trailing tier, then
   `last-updated` descending, then path ascending), and includes entries in
   that order until the next one would push the running byte total over
   the cap. Everything from that point on is omitted and reported in
   `capped`, grouped by `{scope}/{entity_id}/{area}/` prefix with a count.
   A public `index_entry_bytes(entry) -> int` defines what an entry costs,
   so the tool layer and the conformance suite agree with the store.
2. `wenchang.transport.InProcessClient(store)`, a `TransportClient` that
   forwards each of the seven methods to the `MemoryStore` it wraps,
   unchanged. `MemoryStore` itself also satisfies `TransportClient` once it
   has `get_memory_index`.

Out of scope: the tool layer (AIE-1044), the conformance harness and cases
(AIE-1047, AIE-1045), any remote transport, and any change to the six
existing `MemoryStore` operations.

## User Scenarios & Testing *(mandatory)*

Reference fixture used below unless stated: an `InMemoryStorage` seeded
through `storage.put` with `metadata_to_map(...)`, and a `MemoryStore` with
a fixed clock. `_seed(path, last_updated)` seeds a file with description
`"d"`, no aliases, sources `{"t"}`, and the given UTC timestamp.
`scope_map = {"user": "u-1", "org": "o-9"}`. Timestamps `T1 < T2 < T3`.

### User Story 1 - Fan-out and merge (Priority: P1)

**Acceptance Scenarios**:

1. **Given** files `user/u-1/notes/a.md` (T1) and `org/o-9/glossary/b.md`
   (T2), **When** `get_memory_index(scope_map)`, **Then** `entries` holds
   exactly those two as `FileEntry` values equal to what `list_prefix`
   returns for each, and `capped == ()`.
2. **Given** a file under an entity not in the map
   (`user/u-2/notes/c.md`) and a scope not in the map
   (`team/t-1/notes/d.md`), **Then** neither appears.
3. **Given** `list_page_size=2` and five files under `user/u-1/`, **Then**
   all five appear: every page is drained.
4. **Given** an empty `scope_map` and a storage whose every method
   (`list_page` included) raises `AssertionError`, **Then** the result is
   `MemoryIndex()`: storage is never consulted.
5. **Given** a scope with no files, **Then** it contributes nothing and
   raises nothing.
6. **Given** a malformed key under a prefix (`user/u-1/notes/x.txt`),
   **Then** it is skipped, as `list_prefix` skips it. **Given**
   `list_page_size=1`, a malformed key that sorts first, then a valid key,
   **Then** the valid key appears: the drain loop stops only when
   `next_cursor is None`, never on an empty page.
7. **Given** corrupt metadata on a well-formed key, **Then**
   `MetadataFormatError` propagates. **Given** a storage whose
   `list_page` raises `BackendUnavailableError`, **Then** it propagates.
   Neither is wrapped.
8. **Given** a storage whose `get` raises `AssertionError` and whose
   `list_page` works, **Then** the index succeeds: it never reads a body.
9. **Given** `{"user": "u-1"}` and a file `user/u-10/notes/x.md`, **Then**
   it is excluded: the prefix is `user/u-1/`, segment-aligned, and
   `list_prefix` never matches `u-10`.
10. **Given** a stored `last-updated` that `metadata_from_map` accepts but
    `metadata_to_map` cannot re-render (`0001-01-01T00:00:00+05:00`
    overflows `astimezone(UTC)`), **Then** `index_entry_bytes` raises
    `MetadataFormatError("last-updated", ...)`, not `OverflowError`.
11. **Given** a path or description containing a lone surrogate
    (`"\ud800"`, which `is_valid_segment` accepts), **Then**
    `index_entry_bytes` counts it with `encode("utf-8",
    "surrogatepass")` (3 bytes) and raises nothing. **Given** a lone
    surrogate in an alias or source, **Then** it counts its 6-byte
    `\ud800` JSON escape, as `json.dumps` renders it, the same way US3.1
    treats `é`.
12. **Given** a `MemoryStore` subclass that overrides `list_prefix` to
    return nothing, **Then** `get_memory_index` still returns the stored
    files: it drains through `MemoryStore.list_prefix(self, ...)`, so a
    subclass override cannot change the index.

---

### User Story 2 - Ordering (Priority: P1)

**Acceptance Scenarios**:

1. **Given** `user/u-1/system/s.md` (T1), `org/o-9/system/t.md` (T3),
   `user/u-1/notes/n.md` (T3), `org/o-9/notes/m.md` (T2), and no
   `scope_priority`, **Then** `entries` paths are, in order:
   `org/o-9/system/t.md`, `user/u-1/system/s.md`, `user/u-1/notes/n.md`,
   `org/o-9/notes/m.md`. `system/` areas from every scope come first,
   ordered among themselves by `last-updated` descending; the remaining
   entries form one flat tier ordered the same way.
2. **Given** the same files and `scope_priority=("org", "user")`, **Then**
   the order is `org/o-9/system/t.md`, `user/u-1/system/s.md`,
   `org/o-9/notes/m.md`, `user/u-1/notes/n.md`: the `org` note precedes
   the newer `user` note. Priority applies only to non-`system/` entries;
   the two `system/` entries keep recency order regardless of priority.
   (With `("user", "org")` the result equals US2.1, which is why the
   swapped case is the one that discriminates.)
3. **Given** `scope_map = {"user": "u-1", "org": "o-9", "team": "t-1"}`,
   `scope_priority=("org",)`, and files `org/o-9/notes/m.md` (T1),
   `user/u-1/notes/n.md` (T2), `team/t-1/notes/p.md` (T3), **Then** the
   order is `org/o-9/notes/m.md`, `team/t-1/notes/p.md`,
   `user/u-1/notes/n.md`: the listed scope first despite being oldest;
   the two unlisted scopes form one tier ordered by recency, not by name
   (`team` before `user` because T3 > T2).
4. **Given** two entries with equal `last-updated` in the same tier,
   **Then** they are ordered by path ascending. **Given** two timestamps
   that differ by one microsecond, **Then** the newer is first: the sort
   key is the exact integer microsecond offset, not a float.
5. **Given** a scope in `scope_priority` that is absent from `scope_map`,
   **Then** it is ignored.
6. **Given** `scope_map = {"system": "e", "user": "system"}` and files
   `system/e/notes/a.md` (T1), `user/system/notes/b.md` (T2),
   `user/system/notes/system.md` (T3), `user/system/system/c.md` (T1),
   **Then** only `user/system/system/c.md` is in the `system/` tier (first),
   and the other three follow in recency order: `system.md`, `b.md`,
   `a.md`. Only the area segment counts (ADR 0016).

---

### User Story 3 - Byte cap (Priority: P1)

`index_entry_bytes(entry)` is the UTF-8 byte length of `entry.path`, plus
the UTF-8 byte lengths of every key and value in the canonical rendering
`metadata_to_map(entry.metadata)`, plus the UTF-8 byte length of
`entry.version`, all encoded with `errors="surrogatepass"`. It measures
the library's canonical encoding, not the bytes stored (extra stored keys
cost nothing; aliases are re-rendered with `json.dumps` defaults, so a
non-ASCII alias counts its `\uXXXX` escape).

**Acceptance Scenarios**:

1. **Given** a `FileEntry` with path `user/u-1/notes/a.md` (19 bytes),
   metadata whose map is `{"description": "d", "aliases": "[]", "sources":
   '["t"]', "last-updated": "2024-01-01T00:00:00Z"}`, and version `"7"`,
   **Then** `index_entry_bytes` returns `19 + (11+1) + (7+2) + (7+5) +
   (12+20) + 1 = 85`. **Given** alias `"é"` instead of none, **Then** the
   aliases value is `'["\\u00e9"]'` (10 bytes) and the total is `93`.
   **Given** description `"é"`, **Then** it costs 2 bytes (UTF-8), not 1.
2. **Given** `index_max_bytes` exactly equal to the sum of all entries'
   sizes, **Then** every entry is included and `capped == ()`. The cap is
   inclusive.
3. **Given** `index_max_bytes` one less than that sum, **Then** the last
   entry in order is omitted, and `capped ==
   (CappedPrefix("<its scope>/<entity>/<area>/", 1),)`.
4. **Given** entries `e1..e5` in order and a cap that admits `e1` and `e2`
   but not `e3`, where `e4` would fit on its own, **Then** `e3`, `e4`, and
   `e5` are all omitted. Inclusion stops at the first entry that does not
   fit; it never skips ahead to a smaller one, so the returned prefix of
   the ordering is exact.
5. **Given** omitted entries under `user/u-1/notes/` (3), `user/u-1/people/`
   (1), and `org/o-9/notes/` (2), **Then** `capped` is sorted by prefix
   string: `("org/o-9/notes/", 2)`, `("user/u-1/notes/", 3)`,
   `("user/u-1/people/", 1)`.
6. **Given** a cap smaller than the first entry, **Then** `entries == ()`
   and every entry is counted in `capped`.
7. **Given** `index_max_bytes=0` or negative at construction, **Then**
   `ValueError`. The default is `DEFAULT_INDEX_MAX_BYTES == 65536`.
8. **Given** the cap is reached, **Then** the `capped` tuple's own size is
   not counted against the budget. The budget bounds entries only.

---

### User Story 4 - Constructor settings and input validation (Priority: P1)

**Acceptance Scenarios**:

1. **Given** `scope_priority=("user", "org")`, **Then** it is stored as a
   `tuple[str, ...]` readable as `store.scope_priority`, and
   `store.index_max_bytes` returns the cap. Both are read-only properties.
2. **Given** `scope_priority`, validation runs in this order, all
   `TypeError` checks before any `ValueError`: (a) `TypeError` if the
   value's real type is `str`, `bytes`, or `bytearray` (a bare string is a
   `Sequence[str]` of characters and is always a mistake), or if it is not
   a `Sequence`; (b) for each member in order, `TypeError` if its real type
   is not `str`, then normalize with `str.__str__`; (c) for each normalized
   member in order, `ValueError("invalid scope_priority entry: ...")` if
   `not is_valid_segment`, then `ValueError("duplicate scope_priority
   entry: ...")` if already seen. So `("user", "user", 3)` raises
   `TypeError`, and `("a/", "a/")` raises the invalid-entry `ValueError`.
3. **Given** a `scope_priority` given as a `list`, **Then** it is accepted
   and stored as a `tuple`; later mutation of the list has no effect.
4. **Given** a `scope_map` whose real type is not a `Mapping`
   (`issubclass(type(x), Mapping)`, so a spoofed `__class__` fails),
   **Then** `TypeError`, with storage never consulted (every-method-raises
   storage). The `Sequence` check on `scope_priority` uses the same
   real-type rule.
5. **Given** `scope_map`, validation runs in this order, before storage is
   consulted: (a) `items()` is read exactly once into a list; (b) for each
   pair in that order, `TypeError("scope_map key must be str, got ...")` /
   `TypeError("scope_map value must be str, got ...")` if the real type is
   not `str`, then both are normalized with `str.__str__`; (c) the
   normalized pairs are sorted by scope; (d) for each pair in sorted order,
   `ValueError(f"invalid scope: {scope!r}")` if `not
   is_valid_segment(scope)`, then `ValueError(f"invalid entity_id:
   {entity_id!r}")`, then `ValueError(f"duplicate scope: {scope!r}")` if
   the scope was already seen (a `Mapping` whose `items()` repeats a key,
   or two keys equal after normalization). So `{"a/": "x", "b": 1}` raises
   `TypeError`, and `{"a/": "x", "b": "y/"}` raises `invalid scope: 'a/'`.
   These are library-controlled values (an `Identity.scope_map`), so
   `ValueError`, not `NotFoundError`, per ADR 0015.
6. **Given** `scope_map` iteration order `{"org": ..., "user": ...}` versus
   `{"user": ..., "org": ...}`, **Then** the result is identical. Fan-out
   order is by sorted normalized scope name and never affects the output.
7. **Given** `index_max_bytes=True` or `1.5`, **Then** it is accepted, as
   the existing `max_file_bytes` and `list_page_size` knobs accept them;
   only `<= 0` is rejected. Construction settings are library-controlled.

---

### User Story 5 - InProcessClient (Priority: P1)

**Acceptance Scenarios**:

1. **Given** `client = InProcessClient(store)`, **Then**
   `isinstance(client, TransportClient)` is `True`, `client.store is
   store`, and `isinstance(store, TransportClient)` is also `True`. The
   test module also holds `_A: TransportClient = InProcessClient(...)` and
   `_B: TransportClient = MemoryStore(...)` so pyright checks both
   structurally.
2. **Given** each of the six value-returning methods, **When** called on
   the client with arguments, **Then** the return value is the same object
   `store.<m>` returns (identity, not just equality), and the store
   received exactly the same positional and keyword arguments. **Given**
   `delete_file`, **Then** the store received the same arguments and the
   client returns `None`. Verified with a `MemoryStore` subclass that
   records `(name, args, kwargs)` and returns a per-method sentinel object.
3. **Given** `store.<m>` raises a freshly constructed exception, **Then**
   `client.<m>` raises that same object (`is`), and the client adds no
   `__cause__` and no `__context__` of its own. Verified for one
   `wenchang.errors` type, `ValueError`, and `MetadataFormatError`.
4. **Given** an end-to-end round trip through the client against
   `InMemoryStorage` (`write_file`, `read_file`, `append_line`,
   `replace_fact`, `list_prefix`, `delete_file`, `get_memory_index`),
   **Then** every result equals the same sequence run directly on the
   store with a fresh storage.
5. **Given** `InProcessClient(not_a_store)` where the argument's real type
   is not a `MemoryStore` subclass (`issubclass(type(x), MemoryStore)`),
   **Then** `TypeError`. A subclass is accepted so tests can record calls.
6. **Given** the unbound class attributes, **Then**
   `inspect.signature(InProcessClient.<m>, eval_str=True) ==
   inspect.signature(TransportClient.<m>, eval_str=True)` for all seven,
   and `inspect.signature(MemoryStore.get_memory_index, eval_str=True) ==
   inspect.signature(TransportClient.get_memory_index, eval_str=True)`.

---

### User Story 6 - Module boundaries (Priority: P1)

**Acceptance Scenarios**:

1. **Given** `src/wenchang/transport.py`, **Then** its `wenchang` imports
   are only `core`, `file_format`, and `version_token`; it still has no
   `__future__` import and no `TYPE_CHECKING` guard. `core` still does not
   import `transport`.
2. **Given** `src/wenchang/core.py`, **Then** it imports `SYSTEM_AREA`
   from `wenchang.scope`? **No.** `core` must not import `scope`
   (ARCHITECTURE invariant "`scope` and `core` stay independent"). The
   `system` area name used for ordering is compared against the literal
   `"system"` through a `core`-local `Final` constant equal to
   `scope.SYSTEM_AREA`; a test asserts the two are equal.
3. **Given** every file under `src/wenchang/`, **Then** none matches
   `AIE-\d+`.

### Edge Cases

- The index is not a snapshot (ADR 0010): a file written or deleted while
  pages are being drained may or may not appear. Not tested beyond the
  existing `list_prefix` guarantee.
- `last-updated` ties are broken by path so the order is total and
  deterministic; path order within a tie is otherwise meaningless.
- A scope that appears twice in `scope_priority` is a configuration error
  (`ValueError`) rather than silently de-duplicated.
- `index_entry_bytes` measures the library's canonical metadata rendering,
  not the bytes stored and not any tool's rendering. A tool that renders
  more verbosely exceeds the cap by a bounded constant factor; the cap is
  a tripwire, not a guarantee about rendered size.
- One very large top-ranked entry (a `system/` file with a huge alias
  list) can leave `entries == ()` with everything in `capped`. This is the
  cost of stop-at-first-miss. A file's content is bounded by
  `max_file_bytes` but its metadata is not, so the case is reachable only
  by an unreasonable alias list; the index still tells the agent exactly
  what to `list_prefix`.
- `InProcessClient` adds no behavior: no caching, no retry, no validation
  beyond its constructor. A `MemoryStore` subclass is accepted
  (`issubclass(type(store), MemoryStore)`) so tests can record calls.
- `get_memory_index` drains pages through `MemoryStore.list_prefix(self,
  prefix, cursor)` (the base method, called explicitly), so a subclass
  override of `list_prefix` cannot change what the index sees, and a
  recording subclass does not log the internal page calls.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `MemoryStore.__init__` MUST accept keyword-only
  `index_max_bytes: int = DEFAULT_INDEX_MAX_BYTES` and `scope_priority:
  Sequence[str] = ()`, validated per US3.7 and US4.1–3 in the stated
  order, exposed as read-only properties.
- **FR-002**: `MemoryStore.get_memory_index(scope_map: Mapping[str, str])
  -> MemoryIndex` MUST validate input per US4.4–5 in the stated order
  before any storage call, fan out per US1 through the base
  `MemoryStore.list_prefix`, order per US2 with an exact integer
  microsecond sort key, and cap per US3.
- **FR-003**: `wenchang.core.index_entry_bytes(entry: FileEntry) -> int`
  MUST compute the cost per US3's definition (canonical rendering,
  `surrogatepass`), MUST convert an `OverflowError` from re-rendering
  `last-updated` into `MetadataFormatError("last-updated", ...)`, and is
  the only size rule the cap uses.
- **FR-004**: `wenchang.transport.InProcessClient(store: MemoryStore)`
  MUST forward each of the seven methods unchanged (US5.2–3) and be
  exported in `__all__`.
- **FR-005**: `core` MUST NOT import `scope` or `transport`; `transport`
  MUST import from `wenchang` only `core`, `file_format`, and
  `version_token`.
- **FR-006**: Shipped modules MUST cite no Linear IDs. Test docstrings
  MUST cite AIE-1046.

## Success Criteria *(mandatory)*

- **SC-001**: Every scenario has a test; `make check` passes.
- **SC-002**: `make test-integration` passes against fake-gcs-server for
  one fan-out-and-cap scenario (US1.3 and US3.3 on `GcsStorage`), since the
  index drains `list_page` on a real backend. This test is expected green
  on arrival (coverage, not a red-first test): the paging primitive is
  already conformance-tested per ADR 0010. The new file defines its own
  `GcsStorage` fixture, copied from `tests/integration/test_storage_gcs.py`,
  rather than moving the existing one into `conftest.py`, so no existing
  test file changes.

## Assumptions

- "Flat" default priority means every non-`system/` entry is one tier
  ordered by recency, regardless of scope. Listed scopes form one tier
  each, in list order, ahead of a single trailing tier of unlisted scopes.
- The capped-prefix granularity is the area (`scope/entity/area/`),
  because that is what the agent passes to `list_prefix` to recover.
- Inclusion stops at the first entry that does not fit (US3.4). Skipping
  ahead would admit a low-priority small file over a high-priority large
  one and make the returned order not a prefix of the full order.
- `index_max_bytes` and `scope_priority` are `MemoryStore` construction
  settings, like `max_file_bytes` and `list_page_size` (ADR 0010), not
  per-call arguments: the transport signature fixed in AIE-1048 takes only
  `scope_map`.
- **Orchestrator calls on §5 refinements**, decided here and recorded in
  ADR 0020 as pending human review at the PR: (1) the budget counts the
  canonical metadata rendering, because core owns no other rendering and a
  tool-rendering-based cap cannot live below the tool layer; (2)
  stop-at-first-miss rather than best-fit; (3) unlisted scopes form one
  trailing tier; (4) `capped` prefixes are areas. ADR 0020 also closes ADR
  0019's pending item on where the index algorithm is built.
- **Base branch.** This branch must be rebased onto the final
  `AIE-1048-transport-interface` commit (ADR 0019 present, `MemoryIndex`
  rejecting subclass members, the top-level-imports assertion in
  `tests/test_transport_protocol.py`) before T1. tasks.md checks this.
