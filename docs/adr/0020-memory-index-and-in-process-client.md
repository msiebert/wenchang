# 0020. Memory index and in-process client

Date: 2026-10-01

## Status

Accepted

## Context

The Notion spec (Section 5) defines `get_memory_index(scope_map)`: it
"takes a map of scope name to entity ID and returns merged metadata across
every scope in that map, in one call". "The cap is a byte budget on the
returned index, defaulting to 64 KB, configurable. Bytes rather than a file
count, because the cap protects context budget." Under the cap the order is
`system/` areas across all scopes first, then the remaining scopes in an
adopter-supplied priority order that "defaults to flat, in which case this
step is a no-op and everything falls through to recency", then file-level
`last-updated`, most recent first ("Step three is the sole use of the
file-level timestamp"). On reaching the cap the index degrades rather than
truncating silently: it returns a `capped` section listing each prefix not
fully returned with an omitted count, and the agent can `list_prefix` any
capped area.

Section 7 asks for an in-process transport that "calls the core functions
directly with no network. The fastest iteration loop and the simplest
adoption path." Section 10.2 requires the transport suite to check "Index
behavior. get_memory_index fans out over an arbitrary scope map; under the
byte cap it applies the documented ordering and reports every omitted
prefix with a count."

AIE-1046 is the in-process client. ADR 0019 defined `TransportClient`,
`MemoryIndex`, and `CappedPrefix`, and rescoped the implementation of
`MemoryStore.get_memory_index` from the tool-layer issue (AIE-1044) to this
one, because the in-process client cannot pass the index conformance cases
through a method that does not exist. The Notion text leaves open what an
entry costs in bytes, how inclusion behaves at the boundary, how scopes the
priority list does not name are ordered, and what granularity a `capped`
prefix has; this ADR records those choices.

## Decision

Add `MemoryStore.get_memory_index`, two `MemoryStore` construction
settings (`index_max_bytes`, `scope_priority`), and the public cost function
`index_entry_bytes` to `wenchang.core`, and add `InProcessClient` to
`wenchang.transport`. `core` still imports neither `scope` nor `transport`.

1. **`index_max_bytes` and `scope_priority` are `MemoryStore` construction
   settings.** `index_max_bytes` defaults to `DEFAULT_INDEX_MAX_BYTES =
   65536` and must be positive; `scope_priority` defaults to `()`. Both are
   read-only properties. The transport signature takes only `scope_map`
   (ADR 0019), and ADR 0010 made page size construction config for the
   same reason.
   - **Rejected: per-call parameters**, which every transport would have
     to carry and which would let one caller change another's budget.
2. **An entry's cost is `index_entry_bytes(entry)`: the UTF-8 byte length
   of the path, of every key and value in `metadata_to_map(entry.metadata)`,
   and of the version.** It is public so the tool layer and the
   conformance suite can predict the cap exactly. It measures the library's
   canonical rendering, not the bytes stored (extra stored keys cost
   nothing; a non-ASCII alias counts its JSON `\uXXXX` escape) and not a
   tool's rendering, which `core` cannot know. Strings are encoded with
   `errors="surrogatepass"`, so a lone surrogate that passed
   `is_valid_segment` cannot crash the index. An `OverflowError` from
   re-rendering an extreme `last-updated` (one `metadata_from_map` accepts
   but that cannot be converted to UTC, such as
   `0001-01-01T00:00:00+05:00`) becomes
   `MetadataFormatError("last-updated", ...)`, so corrupt metadata
   surfaces as `MetadataFormatError` everywhere in the index.
   `get_memory_index` sizes every ordered entry before the inclusion walk,
   so such an entry raises whether or not the cap would have reached it.
   - **Rejected: sizing lazily during the walk**, which made the raise
     depend on the cap: the same stored data succeeded or failed depending
     on `index_max_bytes`.
   - **Rejected: counting only descriptions and aliases**, which ignores
     the path, the thing the agent needs to act on an entry.
   - **Rejected: counting a rendering the library does not produce** (a
     tool's JSON or markdown), which cannot be computed below the tool
     layer.
3. **Inclusion stops at the first entry that does not fit.** Entries are
   admitted in order while the running total stays `<= index_max_bytes`
   (inclusive). The returned `entries` is then an exact prefix of the full
   ordering, so "under the cap, the documented ordering applies" holds
   literally, and the agent knows everything omitted ranks below
   everything returned. The `capped` section's own size is not charged to
   the budget.
   - **Rejected: best-fit packing**, which admits a low-priority small file
     over a high-priority large one.
4. **`capped` prefixes are areas (`scope/entity/area/`), sorted by string,
   each with its omitted count.** An area prefix is what the agent hands
   to `list_prefix` to recover.
   - **Rejected: per-scope prefixes**, too coarse to act on.
   - **Rejected: per-file entries**, which defeat the cap.
5. **Flat default; listed scopes are tiers in list order; unlisted scopes
   form one trailing tier.** This applies only to non-`system/` entries;
   `system/` entries form one tier ahead of all of them regardless of
   priority. With the empty default every non-`system/` entry is one tier
   ordered by recency, matching Notion's "no-op" wording. A scope named in
   `scope_priority` but absent from the map is ignored.
   - **Rejected: ordering unlisted scopes alphabetically**, which would
     privilege a scope by its name, which Section 3 forbids.
6. **Ties in `last-updated` break by path ascending**, so the order is
   total and the conformance suite can assert exact sequences. The recency
   key is the exact integer microsecond offset from the Unix epoch
   (`(last_updated - epoch) // timedelta(microseconds=1)`).
   - **Rejected: `datetime.timestamp()`**, whose `float` loses microsecond
     resolution for far-future dates and would create false ties.

   6a. **Input validation runs every `TypeError` before any `ValueError`,
   matching ADR 0019 decision 8.** `scope_priority` whose real type is
   `str`, `bytes`, or `bytearray`, or is not a `Sequence`, raises
   `TypeError`: a `str` is a `Sequence[str]` of its characters, so
   `scope_priority="user"` would otherwise silently become four one-letter
   tiers. A non-`str` member raises `TypeError`; members are normalized
   with `str.__str__` and stored as a tuple; then each raises
   `ValueError` if it fails `is_valid_segment` or is a duplicate. For
   `scope_map`: a non-`Mapping` (by real type) raises `TypeError`;
   `items()` is read exactly once; each item that is not exactly a
   2-`tuple` raises `TypeError("scope_map items must be (str, str)
   pairs")`, so a `Mapping` whose `items()` yields other shapes cannot
   escape as an unpacking error; then each non-`str` key or value raises
   `TypeError`; pairs are normalized, sorted by scope, and then each
   raises `ValueError` for an invalid scope, an invalid entity ID, or a
   scope seen twice. The duplicate check means a `Mapping` whose `items()`
   repeats a key, or two keys equal after normalization, cannot cause a
   double fan-out. All of this happens before any storage call.
   - **Rejected: silently de-duplicating `scope_priority`**, which hides a
     configuration error.

   6b. **Pages are drained through the base `MemoryStore.list_prefix`**,
   called explicitly as `MemoryStore.list_prefix(self, prefix, cursor)`
   and looped until `next_cursor is None`, never stopping on an empty page
   (a page of only malformed keys is empty but not final). A subclass
   override of `list_prefix` cannot change the index, and a recording
   subclass sees only the calls a client made.
   - **Rejected: `self.list_prefix`**, which lets an override leak into
     session bootstrap.
7. **The `system/` tier is decided by `parse_path(path).area ==
   INDEX_SYSTEM_AREA`**, a `core`-local `Final` constant `"system"`. A test
   pins it equal to `scope.SYSTEM_AREA` (ADR 0016); only the area segment
   counts, so a scope, entity, or file named `system` is not in the tier.
   `core` cannot import `scope` (the `scope`/`core` independence
   invariant).
   - **Rejected: moving `SYSTEM_AREA` to `paths`**, a wider change than
     this issue needs; noted as a possible follow-up.
8. **`scope_map` validation raises `TypeError`/`ValueError`, not
   `NotFoundError`.** The map comes from `Identity.scope_map`, a
   library-controlled value, the ADR 0015 rule for builders. An empty map
   returns `MemoryIndex()` without touching storage.
9. **`InProcessClient` is a thin wrapper class, and `MemoryStore` also
   satisfies the protocol.** The wrapper gives `transport` a concrete
   reference implementation to name and test, and gives hosts one obvious
   thing to construct. It forwards each of the seven methods by direct
   call with unchanged arguments, returns the store's object itself (except
   `delete_file`, which returns `None` regardless of what a store subclass
   returns, as its annotation promises), and lets every exception propagate
   unwrapped, adding no `__cause__` or `__context__`. Its constructor raises
   `TypeError` unless the argument's real type is a `MemoryStore`, naming
   the type through a guarded helper (`<unnamed>` if `__name__` raises); a
   subclass is accepted so tests can record calls. Its signatures equal the protocol's, checked by
   `inspect.signature(..., eval_str=True)`, as is
   `MemoryStore.get_memory_index`'s.
   - **Rejected: making `MemoryStore` the only client**, which leaves
     `transport` with no implementation and hides the seam.
10. **One integration test runs fan-out and the cap against `GcsStorage`
    on fake-gcs-server**, because `get_memory_index` is the first operation
    that drains `list_page` to exhaustion on a real backend. It is
    coverage rather than a red-first test, since the paging primitive is
    already conformance-tested (ADR 0010). It defines its own `GcsStorage`
    fixture rather than moving the one in
    `tests/integration/test_storage_gcs.py`, so no existing test changes.
11. **The four Section 5 refinements are orchestrator decisions pending
    human review** (below). Each stays inside Notion's text. This ADR also
    realizes ADR 0019's pending item on where the index algorithm is built.

### Orchestrator decisions pending human review

Four of the above refine Section 5 where its text is silent. The
orchestrator made them at spec review without escalation. They are
reversible and are flagged for the human at PR review; this section is
updated once they are confirmed or changed.

- **Byte accounting** (decision 2): an entry costs the UTF-8 bytes of its
  path, its canonical `metadata_to_map` rendering, and its version, as
  computed by `index_entry_bytes`. `core` owns no other rendering, and a
  cap measured on a tool's rendering cannot live below the tool layer.
- **Stop at the first miss** (decision 3): inclusion stops at the first
  entry that does not fit, so `entries` is an exact prefix of the order.
- **Unlisted scopes form one trailing tier** (decision 5), ordered by
  recency after every listed scope.
- **`capped` prefixes are areas** (decision 4), the unit `list_prefix`
  takes to recover.

### Adversarial review

An adversarial code review of the implementation found four defects, each
fixed with a test before merge: the `MetadataFormatError` for an
unrenderable entry depended on whether the cap reached it (now every entry
is sized first, decision 2); a `scope_map` whose `items()` yields
non-pairs escaped as an unpacking error (now the item-shape `TypeError`,
decision 6a); `InProcessClient.delete_file` passed through whatever a store
subclass returned instead of `None`; and its constructor's `TypeError`
read `__name__` unguarded (both decision 9). A mutation-testing coverage
review then ran 48 mutants; 5 real survivors were killed with new tests,
and 3 survivors are equivalent mutants.

## Consequences

`MemoryStore` now implements every operation in `TransportClient`, so both
it and `InProcessClient` satisfy the protocol, and the tool layer (AIE-1044)
and the transport conformance harness and cases (AIE-1047, AIE-1045) have a
working in-process implementation to build and test against. Because
`index_entry_bytes` is public, a conformance case can compute the exact cap
that admits or omits a given entry.

The cap bounds the canonical metadata encoding, not what a tool renders. A
tool that renders entries more verbosely exceeds the cap by a bounded
constant factor; the cap is a tripwire on context budget, not a guarantee
about rendered size. A file's content is bounded by `max_file_bytes`, but
its metadata is not, so one top-ranked entry with an unreasonable alias
list can leave `entries == ()` with everything in `capped`. That is the
cost of stop-at-first-miss; the agent still gets exact prefixes to list.

Every call drains every page of every scope in the map, O(files), and the
cap does not short-circuit the listing because ordering needs the full set.
That is acceptable at the few-hundred-file scale a 64 KB budget implies.
Every collected entry is also sized, including those past the cap, so one
unrenderable file anywhere in the mapped scopes fails the whole index; it
fails the same way at every cap. The
index is not a snapshot (ADR 0010): a file written or deleted while pages
are drained may or may not appear.

`INDEX_SYSTEM_AREA` duplicates `scope.SYSTEM_AREA`, held equal only by a
test, until the constant moves to a module both may import. A future remote
transport must reproduce `get_memory_index`'s `TypeError` and `ValueError`
messages exactly under ADR 0019's error-parity contract.
