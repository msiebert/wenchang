# Implementation Plan: In-process transport client and memory index

**Linear issue**: AIE-1046 | **Branch**: `AIE-1046-inprocess-client` | **Date**: 2026-10-01 | **Spec**: [spec.md](spec.md)

## Summary

Add `get_memory_index`, two constructor settings, and `index_entry_bytes`
to `src/wenchang/core.py`. Add `InProcessClient` to
`src/wenchang/transport.py`. Three new test files plus one integration
test. Based on branch `AIE-1048-transport-interface`; PR targets that
branch until it merges.

## Technical Context

Python ≥ 3.12; pyright strict; ruff 100. `core` already imports `paths`
(`is_valid_path`, `is_valid_prefix`) and `file_format`
(`metadata_from_map`, `metadata_to_map`); it gains `build_prefix`,
`parse_path`, `is_valid_segment` from `paths`. `core` must not import
`scope`, so the `system` area name is a `core`-local constant.

## Constitution Check

| Principle | Status |
| --------- | ------ |
| I. Tests-first | T1–T4 each test-writer → implementer |
| II. Tests not negotiable | No existing test changes |
| IV. Strict typing | Full annotations; `cast(object, ...)` for runtime type checks as in AIE-1048 |
| V. Storage only through interface | Uses `list_prefix` → `Storage.list_page` only |
| VI. Spec fidelity | §5 index semantics implemented literally; byte accounting, stop-at-first-miss, prefix granularity, and flat-tier rule are refinements recorded in ADR 0020 |
| VII. Architecture documented | ARCHITECTURE.md core/transport entries, invariants; ADR 0020 |
| VIII. Traceability | Test docstrings cite AIE-1046; shipped modules cite none |
| IX. Small PR | Two modules touched, one feature each |

**Decisions to record in ADR 0020:**

1. **`index_max_bytes` and `scope_priority` are `MemoryStore` construction
   settings.** The transport signature takes only `scope_map` (ADR 0019),
   and ADR 0010 made page size construction config for the same reason.
   Rejected: per-call parameters, which every transport would have to
   carry and which would let one caller change another's budget.
2. **Entry cost is `index_entry_bytes`: UTF-8 bytes of path + every
   metadata map key and value + version.** A public function, so the tool
   layer and the conformance suite can predict the cap exactly. It measures
   the library's canonical rendering (`metadata_to_map`), not the bytes
   stored (extra stored keys cost nothing, non-ASCII aliases count their
   JSON escape) and not a tool's rendering, which core cannot know.
   Strings are encoded with `surrogatepass` so a lone surrogate that
   passed `is_valid_segment` cannot crash the index. An `OverflowError`
   from re-rendering an extreme `last-updated` becomes
   `MetadataFormatError`, keeping US1.7's "corrupt metadata raises
   `MetadataFormatError`" exact. Rejected: counting only descriptions and
   aliases (ignores the path, which is what the agent needs to act);
   counting a rendering the library does not produce.
3. **Inclusion stops at the first entry that does not fit.** The returned
   `entries` is then an exact prefix of the full ordering, so "under the
   cap, the documented ordering applies" holds literally and the agent
   knows that everything omitted ranks below everything returned.
   Rejected: best-fit packing, which admits a low-priority small file
   over a high-priority large one.
4. **Capped prefixes are areas (`scope/entity/area/`), sorted by string.**
   An area prefix is what the agent hands to `list_prefix` to recover.
   Rejected: per-scope prefixes (too coarse to act on), per-file
   (defeats the cap).
5. **Flat default; listed scopes are tiers in list order; unlisted scopes
   form one trailing tier.** Notion says priority "defaults to flat, in
   which case this step is a no-op and everything falls through to
   recency". A scope named in `scope_priority` but absent from the map is
   ignored; a duplicate is a `ValueError`. Rejected: alphabetical
   ordering of unlisted scopes, which would privilege a scope by name,
   which §3 forbids.
6. **Ties in `last-updated` break by path ascending**, so the order is
   total and the conformance suite can assert exact sequences. The
   timestamp key is an exact integer microsecond offset from the epoch,
   not `datetime.timestamp()`, whose float loses microsecond resolution
   for far-future dates and would create false ties.
6a. **`scope_priority` rejects a bare `str`, `bytes`, or `bytearray` with
   `TypeError`.** A `str` is a `Sequence[str]` of its characters;
   `scope_priority="user"` would silently become four one-letter tiers.
   Validation order for both `scope_priority` and `scope_map` is: every
   `TypeError` check, then normalization, then every `ValueError` check,
   matching ADR 0019 decision 8. `scope_map` is read once via `items()`,
   and a duplicate scope after normalization is a `ValueError`, so a lying
   `Mapping` cannot cause a double fan-out.
6b. **Pages are drained through the base `MemoryStore.list_prefix`**, so
   a subclass override cannot change the index and a recording subclass
   sees only the calls a client made. Rejected: `self.list_prefix`, which
   lets an override leak into bootstrap.
7. **The `system/` tier is decided by `parse_path(path).area ==
   "system"`**, via a `core`-local `Final` constant `INDEX_SYSTEM_AREA =
   "system"`; a test pins it equal to `scope.SYSTEM_AREA`. `core` cannot
   import `scope` (ARCHITECTURE invariant). Rejected: moving `SYSTEM_AREA`
   to `paths`, a wider change than this issue needs (noted as a possible
   follow-up).
8. **`scope_map` validation raises `TypeError`/`ValueError`, not
   `NotFoundError`.** The map comes from `Identity.scope_map`, a
   library-controlled value (ADR 0015 rule). Empty map → `MemoryIndex()`
   without touching storage.
9. **`InProcessClient` is a thin wrapper class, and `MemoryStore` also
   satisfies the protocol.** The wrapper gives the transport module a
   concrete reference implementation to name and test, and gives hosts one
   obvious thing to construct. It forwards by direct method call, returning
   the store's object unchanged and letting every exception propagate
   unwrapped. Rejected: making `MemoryStore` the only client, which leaves
   `transport` with no implementation and hides the seam.
10. **Integration coverage.** One fan-out-and-cap test runs against
    `GcsStorage` and fake-gcs-server, because `get_memory_index` is the
    first operation that drains `list_page` to exhaustion. It is coverage
    rather than a red-first test (the paging primitive is already
    conformance-tested, ADR 0010), and it defines its own `GcsStorage`
    fixture rather than moving the one in
    `tests/integration/test_storage_gcs.py`, so no existing test changes.
11. **The four §5 refinements are orchestrator decisions pending human
    review**: canonical-rendering byte accounting, stop-at-first-miss,
    one trailing tier for unlisted scopes, and area-level `capped`
    prefixes. Each stays inside Notion's text; the ADR records them as
    pending, as ADR 0019 did, and closes ADR 0019's open item on where the
    index algorithm is built.

## Public interface

### `src/wenchang/core.py`

```python
DEFAULT_INDEX_MAX_BYTES: int = 64 * 1024
INDEX_SYSTEM_AREA: Final = "system"  # equals scope.SYSTEM_AREA; core must not import scope


def index_entry_bytes(entry: FileEntry) -> int:
    """UTF-8 size of an index entry: path, every metadata key and value, and version."""
    # def _n(s: str) -> int: return len(s.encode("utf-8", "surrogatepass"))
    # try: rendered = metadata_to_map(entry.metadata)
    # except OverflowError as exc: raise MetadataFormatError(LAST_UPDATED_KEY, "...") from exc
    # return _n(entry.path) + sum(_n(k) + _n(v) for k, v in rendered.items()) + _n(entry.version)


class MemoryStore:
    def __init__(
        self,
        storage: Storage,
        *,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
        clock: Callable[[], datetime] = _utc_now,
        list_page_size: int = DEFAULT_LIST_PAGE_SIZE,
        index_max_bytes: int = DEFAULT_INDEX_MAX_BYTES,
        scope_priority: Sequence[str] = (),
    ) -> None:
        # ValueError("index_max_bytes must be positive") if index_max_bytes <= 0
        # scope_priority, in order (all TypeError before any ValueError):
        #   TypeError if issubclass(type(x), (str, bytes, bytearray)) or not issubclass(type(x), Sequence)
        #   members = [str.__str__(s) for s in x after TypeError if not issubclass(type(s), str)]
        #   for s in members: ValueError(f"invalid scope_priority entry: {s!r}") if not
        #     is_valid_segment(s); ValueError(f"duplicate scope_priority entry: {s!r}") if seen
        #   self._scope_priority = tuple(members)
        ...

    @property
    def index_max_bytes(self) -> int: ...

    @property
    def scope_priority(self) -> tuple[str, ...]: ...

    def get_memory_index(self, scope_map: Mapping[str, str]) -> MemoryIndex:
        """Merged metadata across every scope in `scope_map`, ordered and byte-capped.

        Order: system/ areas across all scopes first; then scopes in
        `scope_priority` order, unlisted scopes last as one tier; within a
        tier by last-updated, most recent first, then by path. Entries are
        included in that order until the next one would exceed
        `index_max_bytes`; the rest are reported in `capped` by area prefix.
        """
```

Algorithm:

1. Validate, in this order, before any storage call:
   - `TypeError` if `not issubclass(type(scope_map), Mapping)` (real type;
     `collections.abc.Mapping` registers `dict` and `MappingProxyType`).
   - `raw = list(scope_map.items())`, read exactly once.
   - For each `(k, v)` in `raw` order: `TypeError(f"scope_map key must be
     str, got {name}")` if `not issubclass(type(k), str)`;
     `TypeError(f"scope_map value must be str, got {name}")` likewise for
     `v`; collect `(str.__str__(k), str.__str__(v))`.
   - `pairs = sorted(normalized)` (plain `str` tuples; no lying `__lt__`
     possible after normalization).
   - For each `(scope, entity_id)` in `pairs`: `ValueError(f"invalid
     scope: {scope!r}")` if `not is_valid_segment(scope)`;
     `ValueError(f"invalid entity_id: {entity_id!r}")`; `ValueError(
     f"duplicate scope: {scope!r}")` if `scope` was already seen.
   - If `pairs` is empty, return `MemoryIndex()` here.
2. For each pair, `prefix = build_prefix(scope, entity_id)`; drain pages
   with `page = MemoryStore.list_prefix(self, prefix, cursor)` (the base
   method, so a subclass override of `list_prefix` cannot alter the
   index), looping until `page.next_cursor is None`, never breaking on an
   empty `page.entries`. Collect `FileEntry` values.
3. Sort key for entry `e` with `parts = parse_path(e.path)`:
   `(0 if parts.area == INDEX_SYSTEM_AREA else 1, tier, -micros, e.path)`
   where `tier = 0` for system entries and otherwise
   `priority_index.get(parts.scope, len(self._scope_priority))`
   (`priority_index = {s: i for i, s in enumerate(self._scope_priority)}`),
   and `micros = (e.metadata.last_updated - _EPOCH) // timedelta(
   microseconds=1)` with `_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)`, an
   exact `int` (aware subtraction handles any offset). No floats.
4. Walk the sorted list with `total = 0`; for each entry `size =
   index_entry_bytes(e)`; if `total + size <= self._index_max_bytes`,
   include and add; otherwise stop. Everything from the first miss on is
   omitted.
5. Count omitted entries by `build_prefix(parts.scope, parts.entity_id,
   parts.area)`; `capped = tuple(CappedPrefix(p, n) for p, n in
   sorted(counts.items()))`.
6. Return `MemoryIndex(entries=tuple(included), capped=capped)`.

`index_entry_bytes` encodes every string with `.encode("utf-8",
"surrogatepass")` and wraps the `metadata_to_map` call: `except
OverflowError as exc: raise MetadataFormatError(LAST_UPDATED_KEY,
"last-updated cannot be rendered in UTC") from exc`. `LAST_UPDATED_KEY`
is imported from `file_format`.

Update the `MemoryStore` class docstring to list `get_memory_index`.

### `src/wenchang/transport.py`

```python
from wenchang.core import ListCursor, ListPage, MemoryFile, MemoryIndex, MemoryStore

__all__ = ["InProcessClient", "TransportClient"]


class InProcessClient:
    """A TransportClient that calls a MemoryStore directly, with no network hop.

    Every method forwards its arguments unchanged and returns the store's
    result; every exception propagates as raised.
    """

    def __init__(self, store: MemoryStore) -> None:
        # TypeError if not issubclass(type(store), MemoryStore)
        self._store = store

    @property
    def store(self) -> MemoryStore: ...

    # seven methods, signatures identical to TransportClient's, each `return self._store.<m>(...)`
```

`transport` imports `MemoryStore` from `core`; the US6.1 import rule is
unchanged. No `isinstance` registration is needed; structural typing makes
both `InProcessClient` and `MemoryStore` satisfy `TransportClient`.

### ARCHITECTURE.md

`core`: `get_memory_index` implemented, with the settings, the ordering,
the cap rule, `index_entry_bytes`, `INDEX_SYSTEM_AREA`, and the validation
rules. `transport`: `InProcessClient`; `MemoryStore` satisfies the
protocol. Bird's-eye: the in-process implementation exists; tools still
planned. Diagram: `transport --> core` unchanged. Key invariants: add "The
index cap is a byte budget over `index_entry_bytes`, inclusive, applied as
a prefix of the documented order." Fix ADR 0010's stale "`get_memory_index`
(AIE-1044)" note with an update line pointing to ADR 0019/0020.

## Test layout

All files: `pytestmark = pytest.mark.unit` (integration file:
`pytest.mark.integration`), docstrings cite AIE-1046 and scenario IDs.

- `tests/test_core_index_bytes.py` (US1.10–11, US3.1, US6.2, FR-003):
  exact arithmetic for the reference entry (85), the `é` alias (93) and
  `é` description cases; a lone-surrogate path counts 3 bytes and raises
  nothing; the `0001-01-01T00:00:00+05:00` stored timestamp raises
  `MetadataFormatError` with `key == "last-updated"`; version length
  counts; `INDEX_SYSTEM_AREA == scope.SYSTEM_AREA` (imports `scope` in
  the test only).
- `tests/test_core_get_memory_index.py` (US1.1–9, US1.12, US2, US3.2–8,
  US4): helpers `_seed(storage, path, last_updated)` and
  `_new_store(storage, **settings)`; a `_NeverCalledStorage` whose every
  method raises `AssertionError` (US1.4, US4.4, US4.5); a
  `_NoGetStorage` wrapping `InMemoryStorage` whose `get` raises
  `AssertionError` (US1.8); a `_StubStorage` whose `list_page` raises
  `BackendUnavailableError` (US1.7); a `MemoryStore` subclass overriding
  `list_prefix` to return an empty page (US1.12); sizes computed with
  `index_entry_bytes` to set caps exactly (US3.2–3); the validation-order
  cases with exact messages (US4.2, US4.5).
- `tests/test_transport_inprocess.py` (US5, US6.1, US6.3): a
  `_RecordingStore(MemoryStore)` subclass overriding each method to record
  `(name, args, kwargs)` and return a per-method sentinel object (or raise
  the configured exception), with `delete_file` recording and returning
  `None`; identity (`is`) assertions on the six value-returning methods;
  freshly constructed exceptions re-raised with `is` and `__cause__ is
  None` / `__context__ is None`; the end-to-end sequence against two fresh
  `InMemoryStorage`s; `InProcessClient(object())` → `TypeError`;
  unbound-attribute signature equality for all seven plus
  `MemoryStore.get_memory_index`; module-level `_A: TransportClient =
  InProcessClient(...)` and `_B: TransportClient = MemoryStore(...)`; the
  `ast` import scan extended from AIE-1048's test to assert the allowed
  set is unchanged and `MemoryStore` now comes from `wenchang.core`.
- `tests/integration/test_gcs_memory_index.py` (SC-002): its own
  `GcsStorage` fixture (copied from `test_storage_gcs.py`), seeds files via
  `GcsStorage.put`, forces `list_page_size=2`, asserts all entries drained
  and one capped scenario. Expected green on arrival.

## Project Structure

```text
specs/AIE-1046-inprocess-client/        spec.md plan.md tasks.md review-spec.md review-pr.md
src/wenchang/core.py                    # settings, index_entry_bytes, get_memory_index
src/wenchang/transport.py               # InProcessClient
tests/test_core_index_bytes.py          # new
tests/test_core_get_memory_index.py     # new
tests/test_transport_inprocess.py       # new
tests/integration/test_gcs_memory_index.py  # new
ARCHITECTURE.md                         # core, transport entries; "six operations" → seven
docs/adr/0020-memory-index-and-in-process-client.md
docs/adr/0010-list-prefix-pagination.md  # update line
docs/adr/0019-transport-client-interface.md  # pending item on index location closed by 0020
docs/product/glossary.md                # memory index: cap rule, entry cost
```

## Complexity Tracking

None.
