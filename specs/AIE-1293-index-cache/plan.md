# Implementation Plan: AIE-1293 Optional adopter-injected index cache

**Branch**: `AIE-1293-index-cache` | **Date**: 2026-10-30 | **Spec**: [spec.md](spec.md)

## Summary

Add `wenchang.index_cache` (config object + in-memory reference cache) and
an optional `index_cache` argument on `MemoryStore`. `get_memory_index`
caches each entity's drained listing under a generation token; every core
mutation attempt replaces that entity's token. No change to storage,
transport, tools, prompts, or mcp.

## Technical Context

Python 3.11+, pytest, pyright strict, ruff. No new dependencies (stdlib
`json`, `uuid`, `logging`, `threading`). Gate: `make check`. Storage is not
touched, so `make test-integration` is not required (run it anyway if the
emulator is up).

## Constitution Check

- Tests first; no existing test weakened. Existing `get_memory_index` tests
  run unchanged against a store without a cache.
- Storage only through the `Storage` protocol: the cache stores no memory
  file data of its own beyond listing metadata, and storage stays the
  source of truth.
- Public API change (new module, new `MemoryStore` argument and method):
  ADR 0040 + ARCHITECTURE.md in the same PR.
- Tests cite `AIE-1293, USx.y`.

## Public interface

### `src/wenchang/index_cache.py` (new; imports nothing from `wenchang`)

```python
CacheGet = Callable[[str], str | None]
CacheSet = Callable[[str, str, timedelta | None], None]

DEFAULT_KEY_PREFIX: Final = "wenchang:index:"

@dataclass(frozen=True)
class IndexCache:
    get: CacheGet
    set: CacheSet
    ttl: timedelta | None = None
    key_prefix: str = DEFAULT_KEY_PREFIX
```

`__post_init__` (all `TypeError`s before any `ValueError`):
`get`/`set` not `callable` → `TypeError`; `ttl` not `None` and
`not issubclass(type(ttl), timedelta)` → `TypeError`; `key_prefix` real type
not `str` → `TypeError`; then `ttl <= timedelta(0)` → `ValueError`.
`key_prefix` is normalized with `str.__str__` (via `object.__setattr__`);
`ttl` is stored as given.

Contract (docstring): `get` returns the value last `set` for the key, or
`None` if absent or expired. `set` stores with expiry `ttl` from now (`None`:
no expiry). Both must be linearizable per key; neither is required to be
atomic across keys. Values are opaque `str`s. Both callables are required
(`set` is how the library invalidates). The docstring also states: with
`ttl=None`, a failed (swallowed) invalidation or a write that bypasses the
cache leaves an entity stale with no bound, so use a finite `ttl` in
production; keys carry no storage identity, so stores over different
storage roots sharing one cache need distinct `key_prefix`es.

```python
class InMemoryIndexCache:
    def __init__(self, *, clock: Callable[[], datetime] = <utc now>) -> None
    def get(self, key: str) -> str | None
    def set(self, key: str, value: str, ttl: timedelta | None) -> None
```

Thread-safe (one `threading.Lock` per instance held across each method).
An entry set at clock time `t0` with `ttl` is returned while
`clock() < t0 + ttl` and is `None` (and dropped) once `clock() >= t0 + ttl`.
Usage: `cache = InMemoryIndexCache(); IndexCache(get=cache.get, set=cache.set, ttl=timedelta(minutes=5))`.
For tests and single-process adopters only; multi-instance hosts need a
shared cache. The docstring states that expired entries are dropped only
when read, and with `ttl=None` the cache grows without bound.

### `src/wenchang/core.py`

```python
class MemoryStore:
    def __init__(self, storage, *, max_file_bytes=..., clock=..., list_page_size=...,
                 index_max_bytes=..., scope_priority=(),
                 index_cache: IndexCache | None = None) -> None
    @property
    def index_cache(self) -> IndexCache | None
    def invalidate_index(self, scope: str, entity_id: str) -> None
```

- Constructor: `index_cache` not `None` and `not issubclass(type(x),
  IndexCache)` → `TypeError`, checked with the other `TypeError`s (before
  any `ValueError`).
- `invalidate_index`: non-`str` (real type) `scope`/`entity_id` →
  `TypeError`; failing `is_valid_segment` → `ValueError(f"invalid scope:
  {scope!r}")` / `ValueError(f"invalid entity_id: {entity_id!r}")`, checked
  before any cache call. No cache → returns `None`. Otherwise
  `set(token_key, uuid4().hex, ttl)`, then `set(listing_key, TOMBSTONE,
  ttl)`; an exception from either `set` propagates (the second is not
  attempted if the first raises). `TOMBSTONE` is a private constant
  (`'{"tombstone":true}'`) that decodes as a miss and holds no entry data.
- Seven core method signatures are unchanged (the transport
  `inspect.signature` parity test must still pass).

### Keys and value (private to core; key format is documented)

- Entity `E = f"{scope}/{entity_id}"`.
- Token key `f"{key_prefix}v1:token:{E}"`, listing key
  `f"{key_prefix}v1:listing:{E}"`.
- Listing value: compact JSON object
  `{"token": str, "entries": [{"path": str, "version": str, "description": str, "aliases": [str], "sources": [str] (sorted), "last_updated": datetime.isoformat()}]}`.
  `last_updated` keeps its stored offset (round-trips exactly with
  `datetime.fromisoformat`), so a hit builds `FileEntry`/`FileMetadata`
  equal to the uncached one. Decode failure of any kind → treated as a
  miss: bad JSON, the tombstone, missing key, wrong type, `FileMetadata`
  construction error, naive datetime, `version`/`path` not `str`, a `path`
  failing `is_valid_path`, a `path` not starting with that entity's
  `build_prefix(scope, entity_id)`, or a `path` repeated within the
  listing.
- Encode failure (any `Exception`) → logged, not stored; the index call
  continues.

### `get_memory_index` with a cache

Argument validation and the empty-map shortcut are unchanged and happen
before any cache call. Then, per `(scope, entity_id)` in sorted order:

1. `token = _cache_get(token_key)`.
2. If `token` is not `None`: `raw = _cache_get(listing_key)`; if it decodes
   and its `"token" == token`, use its entries (hit; no listing).
3. Otherwise (miss): if `token is None`, `token = uuid4().hex` and
   `_cache_set(token_key, token)`. Drain the listing exactly as today
   (`MemoryStore.list_prefix(self, ...)`). Then
   `_cache_set(listing_key, encode(token, entries))`.

Ordering, sizing, cap, and `capped` are computed from the collected
entries exactly as today. A `MetadataFormatError` or
`BackendUnavailableError` during listing propagates; nothing is stored for
that entity.

`_cache_get(scope, key)` / `_cache_set(scope, key, value)` catch
`Exception` (not `BaseException`), log `WARNING` on
`logging.getLogger("wenchang.core")` naming the scope and the exception
type (never the key or entity ID), and return `None` / do nothing.
`_cache_get` also logs a WARNING (scope and result type) and returns `None`
when `get` returns anything whose real type is not `str` (e.g. `bytes`).

**Why it is safe**: a listing is tagged with a token observed (read or
written) before the listing began. A writer replaces the token only after
its storage call. So if the tag still equals the current token, no write
has completed its invalidation since before the listing started, and every
write whose invalidation completed earlier also committed earlier and is in
the listing. A reader that listed before a write and stores afterwards has
a tag the writer has already replaced, so the store is harmless. A lost
token overwrite (two concurrent `set`s on the token key) only replaces one
fresh random token with another, causing at most an extra miss.

### Invalidation in mutations

Private `_invalidate_path(path)`: no cache → return; else parse scope and
entity, `_cache_set(token_key, uuid4().hex)` (logged-and-swallowed on
error). Called in a `finally` around every `put_if_version` /
`delete_if_version` call in `write_file`, `append_line`, `replace_fact`
(every attempt), and `delete_file`, so it runs whether the storage call
returned or raised, before the method returns or raises. It never replaces
or masks the method's own result or exception.

`delete_file`'s invalidation also tombstones: after the token `set`, it
does `_cache_set(listing_key, TOMBSTONE)` (logged-and-swallowed). The other
mutations replace only the token (one `set`); their old listing value is
never served and the next index call for the entity overwrites it.
`invalidate_index` (public, propagating, also tombstones) is the hook for
AIE-1291's purge and for adopters' out-of-band writers.

Remaining race (documented in the `invalidate_index` docstring and ADR
0040, not closed): a reader that listed before a delete or purge can store
its pre-delete listing after the tombstone. Never served (stale tag), it
persists until the entity is re-indexed or `ttl` expires. A finite `ttl` is
required for adopters with erasure obligations; a purge must call
`invalidate_index` after all its deletes finish.

## Test plan (files)

- `tests/test_index_cache.py` — US1.1–1.4, US8.1–8.3.
- `tests/test_core_index_cache.py` — US1.5–1.6, US2–US7, using:
  - a test-local `Storage` wrapper over `InMemoryStorage` that counts
    `list_page` calls by prefix, can run a callback inside `list_page`
    after the inner result is captured, can run a callback inside
    `put_if_version`/`delete_if_version` before delegating, and can raise
    from them;
  - a test-local cache wrapper `W` over `InMemoryIndexCache` that can run
    a callback inside `get`/`set` for a key (before delegating), delete a
    single key, return a scripted value from `get`, and record values set;
  - `caplog` for warnings; threads + `threading.Barrier` for 5.3 (smoke
    test only; the deterministic cases carry the proof).
  Cache keys are built in tests from the documented format
  (`f"{key_prefix}v1:token:{scope}/{entity_id}"`, `...v1:listing:...`).
- `tests/test_transport_conformance_cached.py` (or a second subclass in the
  existing reference run) — US8.4.

## Docs

- `docs/adr/0040-index-cache.md`: decision, rejected alternatives, token
  protocol and proof sketch, ttl bound (and that `ttl=None` is unbounded
  after a failed invalidation or out-of-band write; finite ttl recommended),
  consistency requirement, failure policy, out-of-band writers,
  `invalidate_index` hook and tombstone, distinct `key_prefix` per storage
  root, compatibility with constitution principle V (derived copy of
  listing metadata, never content, never written ahead of storage, every
  miss/failure falls back to storage), privacy (values hold descriptions,
  aliases, sources; keys hold scope names and entity IDs; logs never name
  entity IDs; `delete_file` and `invalidate_index` tombstone the listing,
  but the remaining race above means pre-delete metadata can persist,
  unserved, until re-index or `ttl`; finite `ttl` required for erasure
  obligations; purge calls `invalidate_index` after all deletes).
- `ARCHITECTURE.md`: new `index_cache` module entry; `core` entry gains
  `index_cache` and `invalidate_index`; concurrency section notes the cache.
- `specs/AIE-1293-index-cache/review-pr.md`.
