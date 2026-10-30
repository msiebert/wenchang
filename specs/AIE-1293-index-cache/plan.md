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
atomic across keys. Values are opaque `str`s.

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
shared cache.

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
  `set(token_key, uuid4().hex, ttl)`; an exception from `set` propagates.
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
  equal to the uncached one. Decode failure of any kind (bad JSON, missing
  key, wrong type, `FileMetadata` construction error, naive datetime,
  `VersionToken`/path not `str`) → treated as a miss.
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

`_cache_get` / `_cache_set` catch `Exception` (not `BaseException`), log
`WARNING` on `logging.getLogger("wenchang.core")` naming the key and the
exception type, and return `None` / do nothing.

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

`invalidate_index` (public, propagating) is the hook for AIE-1291's purge
and for adopters' out-of-band writers.

## Test plan (files)

- `tests/test_index_cache.py` — US1.1–1.4, US8.1–8.3.
- `tests/test_core_index_cache.py` — US1.5–1.6, US2–US7, using a test-local
  `Storage` wrapper over `InMemoryStorage` that counts `list_page` calls by
  prefix and can run a callback inside `list_page` or raise from
  `put_if_version`/`delete_if_version`; `caplog` for warnings; threads +
  `threading.Barrier` for 5.3.
- `tests/test_transport_conformance_cached.py` (or a second subclass in the
  existing reference run) — US8.4.

## Docs

- `docs/adr/0040-index-cache.md`: decision, rejected alternatives, token
  protocol and proof sketch, ttl bound, consistency requirement, failure
  policy, out-of-band writers, `invalidate_index` hook.
- `ARCHITECTURE.md`: new `index_cache` module entry; `core` entry gains
  `index_cache` and `invalidate_index`; concurrency section notes the cache.
- `specs/AIE-1293-index-cache/review-pr.md`.
