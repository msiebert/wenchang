"""Tests for MemoryStore with an IndexCache: cached get_memory_index,
invalidation, concurrency, ttl, and cache failures.

Covers AIE-1293, US1.5-US1.6 and US2-US7.
"""

import json
import logging
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from wenchang.core import FileEntry, MemoryFile, MemoryIndex, MemoryStore, index_entry_bytes
from wenchang.errors import (
    BackendUnavailableError,
    NotFoundError,
    TransientReason,
    VersionConflictError,
)
from wenchang.file_format import FileMetadata, MetadataFormatError, metadata_to_map
from wenchang.index_cache import DEFAULT_KEY_PREFIX, IndexCache, InMemoryIndexCache
from wenchang.storage import ListedObject, PreconditionFailedError, Storage, StoredObject
from wenchang.storage.memory import InMemoryStorage
from wenchang.version_token import VersionToken

pytestmark = pytest.mark.unit

T = timedelta(minutes=5)
T0 = datetime(2026, 1, 1, tzinfo=UTC)
T1 = datetime(2024, 1, 1, tzinfo=UTC)
T2 = datetime(2024, 2, 1, tzinfo=UTC)
T3 = datetime(2024, 3, 1, tzinfo=UTC)

MAP2: dict[str, str] = {"user": "u1", "project": "p1"}
USER_PREFIX = "user/u1/"
PROJECT_PREFIX = "project/p1/"
A_PATH = "user/u1/notes/a.md"
B_PATH = "user/u1/notes/b.md"
C_PATH = "project/p1/notes/c.md"
NEW_PATH = "user/u1/notes/new.md"
BODY = "- [stated] alpha fact\n"


def _token_key(scope: str, entity_id: str, prefix: str = DEFAULT_KEY_PREFIX) -> str:
    return f"{prefix}v1:token:{scope}/{entity_id}"


def _listing_key(scope: str, entity_id: str, prefix: str = DEFAULT_KEY_PREFIX) -> str:
    return f"{prefix}v1:listing:{scope}/{entity_id}"


USER_TOKEN = _token_key("user", "u1")
USER_LISTING = _listing_key("user", "u1")


class _Clock:
    """A settable, advanceable clock."""

    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, by: timedelta) -> None:
        self.now += by


def _pop_matching(hooks: dict[str, Callable[[], None]], key: str) -> Callable[[], None] | None:
    for prefix in list(hooks):
        if key.startswith(prefix):
            return hooks.pop(prefix)
    return None


class _HookStorage:
    """Storage wrapper that counts list_page calls by prefix and runs one-shot hooks.

    `after_list[prefix]` runs inside list_page after the inner result is
    captured; `before_put[key_prefix]` / `before_delete[key_prefix]` run
    before delegating. `put_raises` / `delete_raises` raise on every call.
    """

    def __init__(self, inner: InMemoryStorage | None = None) -> None:
        self.inner = inner if inner is not None else InMemoryStorage()
        self.list_calls: list[str] = []
        self.after_list: dict[str, Callable[[], None]] = {}
        self.before_put: dict[str, Callable[[], None]] = {}
        self.before_delete: dict[str, Callable[[], None]] = {}
        self.put_raises: BaseException | None = None
        self.delete_raises: BaseException | None = None

    def count(self, prefix: str) -> int:
        return self.list_calls.count(prefix)

    def get(self, key: str) -> StoredObject | None:
        return self.inner.get(key)

    def put(self, key: str, data: bytes, metadata: Mapping[str, str]) -> VersionToken:
        return self.inner.put(key, data, metadata)

    def put_if_version(
        self,
        key: str,
        data: bytes,
        metadata: Mapping[str, str],
        expected: VersionToken | None,
    ) -> VersionToken:
        hook = _pop_matching(self.before_put, key)
        if hook is not None:
            hook()
        if self.put_raises is not None:
            raise self.put_raises
        return self.inner.put_if_version(key, data, metadata, expected)

    def list_page(self, prefix: str, start_after: str | None, limit: int) -> Sequence[ListedObject]:
        self.list_calls.append(prefix)
        result = self.inner.list_page(prefix, start_after, limit)
        hook = self.after_list.pop(prefix, None)
        if hook is not None:
            hook()
        return result

    def delete_if_version(self, key: str, expected: VersionToken) -> None:
        hook = _pop_matching(self.before_delete, key)
        if hook is not None:
            hook()
        if self.delete_raises is not None:
            raise self.delete_raises
        self.inner.delete_if_version(key, expected)


class _CacheWrapper:
    """Cache wrapper over InMemoryIndexCache with hooks, scripted gets, and a log.

    `before_get[key]` / `before_set[key]` run once before delegating.
    `scripted[key]` is returned from get instead of the stored value.
    `delete(key)` makes the key absent until it is next set.
    """

    def __init__(self, inner: InMemoryIndexCache) -> None:
        self.inner = inner
        self.before_get: dict[str, Callable[[], None]] = {}
        self.before_set: dict[str, Callable[[], None]] = {}
        self.scripted: dict[str, object] = {}
        self.deleted: set[str] = set()
        self.gets: list[str] = []
        self.sets: list[tuple[str, str, timedelta | None]] = []
        self.get_raises: BaseException | None = None
        self.set_raises: BaseException | None = None

    def get(self, key: str) -> str | None:
        self.gets.append(key)
        hook = self.before_get.pop(key, None)
        if hook is not None:
            hook()
        if self.get_raises is not None:
            raise self.get_raises
        if key in self.scripted:
            return cast(str | None, self.scripted[key])
        if key in self.deleted:
            return None
        return self.inner.get(key)

    def set(self, key: str, value: str, ttl: timedelta | None) -> None:
        self.sets.append((key, value, ttl))
        hook = self.before_set.pop(key, None)
        if hook is not None:
            hook()
        if self.set_raises is not None:
            raise self.set_raises
        self.deleted.discard(key)
        self.inner.set(key, value, ttl)

    def delete(self, key: str) -> None:
        self.deleted.add(key)

    def raw(self, key: str) -> str | None:
        """The stored value, bypassing hooks, scripts, and the log."""
        return None if key in self.deleted else self.inner.get(key)


@dataclass
class _Env:
    storage: _HookStorage
    clock: _Clock
    cache: InMemoryIndexCache
    wrapper: _CacheWrapper
    config: IndexCache
    store: MemoryStore

    def uncached(self, scope_map: Mapping[str, str] = MAP2, **settings: Any) -> MemoryIndex:
        """The index from a cacheless store over the same storage, uncounted."""
        return MemoryStore(self.storage.inner, **settings).get_memory_index(scope_map)


def _env(
    ttl: timedelta | None = T,
    *,
    storage: _HookStorage | None = None,
    cache: InMemoryIndexCache | None = None,
    clock: _Clock | None = None,
    key_prefix: str = DEFAULT_KEY_PREFIX,
    **settings: Any,
) -> _Env:
    clock = clock if clock is not None else _Clock(T0)
    storage = storage if storage is not None else _HookStorage()
    cache = cache if cache is not None else InMemoryIndexCache(clock=clock)
    wrapper = _CacheWrapper(cache)
    config = IndexCache(get=wrapper.get, set=wrapper.set, ttl=ttl, key_prefix=key_prefix)
    store = MemoryStore(storage, index_cache=config, **settings)
    return _Env(storage, clock, cache, wrapper, config, store)


def _metadata(
    description: str = "d",
    aliases: tuple[str, ...] = (),
    last_updated: datetime = T1,
) -> FileMetadata:
    return FileMetadata(
        description=description,
        aliases=aliases,
        sources=frozenset({"t"}),
        last_updated=last_updated,
    )


def _seed(
    storage: Storage,
    path: str,
    *,
    body: str = BODY,
    description: str = "d",
    aliases: tuple[str, ...] = (),
    last_updated: datetime = T1,
) -> VersionToken:
    return storage.put(
        path, body.encode("utf-8"), metadata_to_map(_metadata(description, aliases, last_updated))
    )


def _seed_standard(storage: Storage) -> None:
    _seed(storage, A_PATH, last_updated=T1)
    _seed(storage, B_PATH, last_updated=T2)
    _seed(storage, C_PATH, last_updated=T3)


def _standard_env(ttl: timedelta | None = T, **settings: Any) -> _Env:
    env = _env(ttl, **settings)
    _seed_standard(env.storage.inner)
    return env


def _paths(index: MemoryIndex) -> list[str]:
    return [e.path for e in index.entries]


def _find(index: MemoryIndex, path: str) -> FileEntry | None:
    for entry in index.entries:
        if entry.path == path:
            return entry
    return None


def _version(storage: Storage, path: str) -> VersionToken:
    obj = storage.get(path)
    assert obj is not None
    return obj.version


def _warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "wenchang.core" and r.levelno == logging.WARNING]


class _SpoofedIndexCache:
    """Not an IndexCache, but claims to be one via __class__."""

    @property
    def __class__(self) -> type:  # pyright: ignore[reportIncompatibleMethodOverride]
        return IndexCache


class _DuckIndexCache:
    """Has IndexCache's attributes but is not an IndexCache."""

    def __init__(self) -> None:
        self.ttl = None
        self.key_prefix = DEFAULT_KEY_PREFIX

    def get(self, key: str) -> str | None:
        return None

    def set(self, key: str, value: str, ttl: timedelta | None) -> None:
        return None


class _SpoofedStr:
    """Not a str, but claims to be one via __class__."""

    @property
    def __class__(self) -> type:  # pyright: ignore[reportIncompatibleMethodOverride]
        return str


class _CacheBoom(Exception):
    """A cache failure."""


class _Abort(BaseException):
    """A BaseException that is not an Exception."""


# --- US1: configuration -------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [object(), "cache", _SpoofedIndexCache(), _DuckIndexCache()],
    ids=["object", "str", "spoofed_class", "duck_typed"],
)
def test_store_rejects_non_index_cache(bad: object) -> None:
    """index_cache that is not None and not really an IndexCache raises
    TypeError (AIE-1293, US1.5).
    """
    with pytest.raises(TypeError):
        MemoryStore(InMemoryStorage(), index_cache=cast(Any, bad))


def test_store_index_cache_type_error_precedes_value_error() -> None:
    """A bad index_cache raises TypeError even alongside an invalid
    max_file_bytes (AIE-1293, US1.5).
    """
    with pytest.raises(TypeError):
        MemoryStore(InMemoryStorage(), index_cache=cast(Any, object()), max_file_bytes=0)


def test_store_index_cache_property() -> None:
    """index_cache is None by default and the given object otherwise
    (AIE-1293, US1.6).
    """
    assert MemoryStore(InMemoryStorage()).index_cache is None
    assert MemoryStore(InMemoryStorage(), index_cache=None).index_cache is None

    env = _env()
    assert env.store.index_cache is env.config


# --- US2: no cache ------------------------------------------------------------


def test_no_cache_lists_every_call() -> None:
    """Without a cache each call lists both scopes and results are equal
    (AIE-1293, US2.1).
    """
    storage = _HookStorage()
    _seed_standard(storage.inner)
    store = MemoryStore(storage)

    first = store.get_memory_index(MAP2)
    assert storage.count(USER_PREFIX) >= 1
    assert storage.count(PROJECT_PREFIX) >= 1
    storage.list_calls.clear()

    second = store.get_memory_index(MAP2)
    assert storage.count(USER_PREFIX) >= 1
    assert storage.count(PROJECT_PREFIX) >= 1
    assert first == second


def test_no_cache_invalidate_index_is_a_no_op() -> None:
    """invalidate_index without a cache returns None (AIE-1293, US2.2)."""
    store = MemoryStore(InMemoryStorage())

    assert store.invalidate_index("user", "u1") is None


def test_no_cache_invalidate_index_still_validates() -> None:
    """invalidate_index without a cache still rejects an invalid scope
    (AIE-1293, US2.2, US4.8).
    """
    store = MemoryStore(InMemoryStorage())

    with pytest.raises(ValueError, match=r"^invalid scope: "):
        store.invalidate_index("", "u1")


# --- US3: repeated call does not re-list --------------------------------------


def test_second_call_makes_no_list_page_calls() -> None:
    """With no writes between, the 2nd call makes zero list_page calls and
    returns an equal index (AIE-1293, US3.1).
    """
    env = _standard_env()

    first = env.store.get_memory_index(MAP2)
    assert env.storage.count(USER_PREFIX) >= 1
    assert env.storage.count(PROJECT_PREFIX) >= 1
    env.storage.list_calls.clear()

    second = env.store.get_memory_index(MAP2)

    assert env.storage.list_calls == []
    assert first == second == env.uncached()


def test_empty_entity_is_cached() -> None:
    """An entity with no files is cached too: the 2nd call makes zero
    list_page calls and has no entries for it (AIE-1293, US3.2).
    """
    env = _env()
    _seed(env.storage.inner, A_PATH)

    first = env.store.get_memory_index(MAP2)
    env.storage.list_calls.clear()
    second = env.store.get_memory_index(MAP2)

    assert env.storage.list_calls == []
    assert first == second
    assert not any(p.startswith(PROJECT_PREFIX) for p in _paths(second))
    assert _paths(second) == [A_PATH]


def test_cached_index_equals_uncached_with_cap_priority_and_offsets() -> None:
    """With system/ areas, several scopes, a scope_priority, a cap, and a
    non-UTC last_updated, uncached, first cached, and second cached indexes
    are equal, with the same utcoffset per entry (AIE-1293, US3.3).
    """
    offset_path = "user/u1/system/s.md"
    offset_stamp = "2024-06-01T12:00:00+05:30"
    scope_map = {"user": "u1", "project": "p1", "org": "o1"}
    priority = ("project", "user")

    env0 = _env()
    inner = env0.storage.inner
    offset_map = metadata_to_map(_metadata("offset"))
    offset_map["last-updated"] = offset_stamp
    inner.put(offset_path, b"- [stated] s\n", offset_map)
    _seed(inner, "project/p1/system/t.md", last_updated=T1)
    _seed(inner, "user/u1/notes/a.md", description="a" * 40, last_updated=T2)
    _seed(inner, "project/p1/notes/b.md", description="b" * 40, last_updated=T3)
    _seed(inner, "org/o1/notes/c.md", description="c" * 40, last_updated=T3)
    _seed(inner, "org/o1/notes/d.md", description="d" * 40, last_updated=T1)

    full = env0.uncached(scope_map, scope_priority=priority, index_max_bytes=10**6)
    cap = sum(index_entry_bytes(e) for e in full.entries[:3])
    settings: dict[str, Any] = {"scope_priority": priority, "index_max_bytes": cap}

    uncached = env0.uncached(scope_map, **settings)
    assert uncached.capped != ()
    offset_entry = _find(uncached, offset_path)
    assert offset_entry is not None
    assert offset_entry.metadata.last_updated.utcoffset() == timedelta(hours=5, minutes=30)

    env = _env(storage=env0.storage, **settings)
    first = env.store.get_memory_index(scope_map)
    env.storage.list_calls.clear()
    second = env.store.get_memory_index(scope_map)

    assert env.storage.list_calls == []
    assert first == uncached
    assert second == uncached
    for got in (first, second):
        for entry, expected in zip(got.entries, uncached.entries, strict=True):
            assert entry.path == expected.path
            assert (
                entry.metadata.last_updated.utcoffset()
                == expected.metadata.last_updated.utcoffset()
            )


def test_multi_page_listing_is_cached() -> None:
    """Files spanning more pages than list_page_size are all present and the
    2nd call makes zero list_page calls (AIE-1293, US3.4).
    """
    env = _env(list_page_size=2)
    paths = [f"user/u1/notes/{i}.md" for i in range(5)]
    for path in paths:
        _seed(env.storage.inner, path)

    first = env.store.get_memory_index({"user": "u1"})
    assert env.storage.count(USER_PREFIX) >= 3
    env.storage.list_calls.clear()
    second = env.store.get_memory_index({"user": "u1"})

    assert env.storage.list_calls == []
    assert sorted(_paths(second)) == sorted(paths)
    assert first == second


def test_malformed_key_absent_from_cached_index() -> None:
    """A key that is not a well-formed memory path is absent from both the
    listing and the cached result (AIE-1293, US3.5).
    """
    env = _env()
    _seed(env.storage.inner, A_PATH)
    _seed(env.storage.inner, "user/u1/notes/x.txt")
    _seed(env.storage.inner, "user/u1/deep/er/y.md")

    first = env.store.get_memory_index({"user": "u1"})
    second = env.store.get_memory_index({"user": "u1"})

    assert _paths(first) == [A_PATH]
    assert _paths(second) == [A_PATH]


# --- US4: writes and deletes are visible on the next call ---------------------


def _write_create(env: _Env) -> MemoryFile:
    return env.store.write_file(NEW_PATH, BODY, _metadata("new"), None, source="t")


def _write_replace(env: _Env) -> MemoryFile:
    version = _version(env.storage.inner, A_PATH)
    return env.store.write_file(
        A_PATH, "- [stated] replaced\n", _metadata("replaced", ("ra",)), version, source="w"
    )


def _append(env: _Env) -> MemoryFile:
    version = _version(env.storage.inner, A_PATH)
    return env.store.append_line(
        A_PATH,
        "- [stated] appended",
        version,
        source="ap",
        aliases=["appended-alias"],
        description="appended desc",
    )


def _replace_fact(env: _Env) -> MemoryFile:
    version = _version(env.storage.inner, A_PATH)
    return env.store.replace_fact(
        A_PATH,
        "alpha",
        "beta",
        version,
        source="rf",
        aliases=["rf-alias"],
        description="rf desc",
    )


def _delete(env: _Env) -> None:
    env.store.delete_file(A_PATH, _version(env.storage.inner, A_PATH))


_UPDATES: dict[str, Callable[[_Env], MemoryFile]] = {
    "write_replace": _write_replace,
    "append_line": _append,
    "replace_fact": _replace_fact,
}

_MUTATIONS: dict[str, Callable[[_Env], object]] = {
    "write_create": _write_create,
    **_UPDATES,
    "delete_file": _delete,
}


def test_create_visible_on_next_index() -> None:
    """A write_file create under user/u1 appears in the next index
    (AIE-1293, US4.1).
    """
    env = _standard_env()
    env.store.get_memory_index(MAP2)

    written = _write_create(env)
    index = env.store.get_memory_index(MAP2)

    entry = _find(index, NEW_PATH)
    assert entry is not None
    assert entry.version == written.version
    assert index == env.uncached()


@pytest.mark.parametrize("update", list(_UPDATES.values()), ids=list(_UPDATES))
def test_update_visible_on_next_index(update: Callable[[_Env], MemoryFile]) -> None:
    """write_file (replace), append_line, and replace_fact each show their new
    version and metadata in the next index (AIE-1293, US4.2).
    """
    env = _standard_env()
    env.store.get_memory_index(MAP2)

    written = update(env)
    index = env.store.get_memory_index(MAP2)

    entry = _find(index, A_PATH)
    assert entry is not None
    assert entry.version == written.version
    assert entry.metadata == written.metadata
    assert index == env.uncached()


def test_delete_tombstones_listing_and_omits_file() -> None:
    """After delete_file the raw listing value has none of the deleted file's
    path, description, or aliases, and the next index omits it
    (AIE-1293, US4.3).
    """
    env = _env()
    gone = "user/u1/notes/gone.md"
    version = _seed(env.storage.inner, gone, description="gone-desc-zq", aliases=("gone-alias-zq",))
    _seed(env.storage.inner, A_PATH)
    _seed(env.storage.inner, C_PATH)
    env.store.get_memory_index(MAP2)
    before = env.wrapper.raw(USER_LISTING)
    assert before is not None
    assert gone in before

    env.store.delete_file(gone, version)

    raw = env.wrapper.raw(USER_LISTING)
    if raw is not None:
        for secret in (gone, "gone-desc-zq", "gone-alias-zq"):
            assert secret not in raw
    index = env.store.get_memory_index(MAP2)
    assert _find(index, gone) is None
    assert index == env.uncached()


@pytest.mark.parametrize("mutation", list(_MUTATIONS.values()), ids=list(_MUTATIONS))
def test_mutation_relists_only_its_entity(mutation: Callable[[_Env], object]) -> None:
    """After any mutation to user/u1, the next index lists user/u1/ and makes
    zero list_page calls for project/p1/ (AIE-1293, US4.4).
    """
    env = _standard_env()
    env.store.get_memory_index(MAP2)

    mutation(env)
    env.storage.list_calls.clear()
    index = env.store.get_memory_index(MAP2)

    assert env.storage.count(USER_PREFIX) >= 1
    assert env.storage.count(PROJECT_PREFIX) == 0
    assert index == env.uncached()


_Failure = tuple[Callable[[], BaseException], tuple[type[BaseException], ...]]

# A create whose precondition fails re-reads, finds no file, and raises NotFoundError.
_FAILURES: dict[str, _Failure] = {
    "precondition": (
        lambda: PreconditionFailedError(A_PATH),
        (VersionConflictError, NotFoundError),
    ),
    "backend": (
        lambda: BackendUnavailableError(TransientReason.UNAVAILABLE),
        (BackendUnavailableError,),
    ),
}


@pytest.mark.parametrize("failure", list(_FAILURES.values()), ids=list(_FAILURES))
@pytest.mark.parametrize("mutation", list(_MUTATIONS.values()), ids=list(_MUTATIONS))
def test_failed_mutation_still_invalidates(
    mutation: Callable[[_Env], object], failure: _Failure
) -> None:
    """A mutation whose storage call raises still replaces the entity's token,
    and the next index re-lists user/u1/ (AIE-1293, US4.5).
    """
    make_error, expected = failure
    env = _standard_env()
    env.store.get_memory_index(MAP2)
    token_before = env.wrapper.raw(USER_TOKEN)
    assert token_before is not None
    env.storage.put_raises = make_error()
    env.storage.delete_raises = make_error()

    with pytest.raises(expected):
        mutation(env)

    env.storage.put_raises = None
    env.storage.delete_raises = None
    token_after = env.wrapper.raw(USER_TOKEN)
    assert token_after is not None
    assert token_after != token_before
    env.storage.list_calls.clear()
    index = env.store.get_memory_index(MAP2)
    assert env.storage.count(USER_PREFIX) >= 1
    assert index == env.uncached()


def test_replace_fact_retry_reflects_committed_version() -> None:
    """replace_fact succeeding on its 2nd attempt after a concurrent write is
    reflected in the next index (AIE-1293, US4.6).
    """
    env = _standard_env()
    env.store.get_memory_index(MAP2)
    original = _version(env.storage.inner, A_PATH)

    def concurrent_write() -> None:
        _seed(env.storage.inner, A_PATH, body=BODY + "- [stated] other\n", description="c")

    env.storage.before_put[A_PATH] = concurrent_write
    written = env.store.replace_fact(A_PATH, "alpha", "beta", original, source="rf")
    assert "other" in written.content

    index = env.store.get_memory_index(MAP2)
    entry = _find(index, A_PATH)
    assert entry is not None
    assert entry.version == written.version
    assert entry.metadata == written.metadata
    assert index == env.uncached()


def test_invalidate_index_tombstones_and_relists_only_that_entity() -> None:
    """invalidate_index clears every old entry's path, description, and
    aliases from the raw listing value, and the next index re-lists only
    user/u1/ (AIE-1293, US4.7).
    """
    env = _env()
    _seed(env.storage.inner, A_PATH, description="desc-a-zq", aliases=("alias-a-zq",))
    _seed(env.storage.inner, B_PATH, description="desc-b-zq", aliases=("alias-b-zq",))
    _seed(env.storage.inner, C_PATH)
    env.store.get_memory_index(MAP2)
    before = env.wrapper.raw(USER_LISTING)
    assert before is not None
    assert A_PATH in before

    env.store.invalidate_index("user", "u1")

    raw = env.wrapper.raw(USER_LISTING)
    if raw is not None:
        for secret in (A_PATH, B_PATH, "desc-a-zq", "desc-b-zq", "alias-a-zq", "alias-b-zq"):
            assert secret not in raw
    env.storage.list_calls.clear()
    index = env.store.get_memory_index(MAP2)
    assert env.storage.count(USER_PREFIX) >= 1
    assert env.storage.count(PROJECT_PREFIX) == 0
    assert index == env.uncached()


@pytest.mark.parametrize(
    ("scope", "entity_id", "message"),
    [
        ("", "u1", r"^invalid scope: ''$"),
        ("a/b", "u1", r"^invalid scope: 'a/b'$"),
        ("..", "u1", r"^invalid scope: '\.\.'$"),
        ("user", "", r"^invalid entity_id: ''$"),
        ("user", "u/1", r"^invalid entity_id: 'u/1'$"),
        ("user", "u\n1", r"^invalid entity_id: 'u\\n1'$"),
    ],
)
def test_invalidate_index_rejects_invalid_segments(
    scope: str, entity_id: str, message: str
) -> None:
    """An invalid scope or entity_id raises ValueError naming it, with no
    cache call (AIE-1293, US4.8).
    """
    env = _env()

    with pytest.raises(ValueError, match=message):
        env.store.invalidate_index(scope, entity_id)

    assert env.wrapper.gets == []
    assert env.wrapper.sets == []


@pytest.mark.parametrize(
    ("scope", "entity_id"),
    [(1, "u1"), ("user", None), (b"user", "u1"), (_SpoofedStr(), "u1"), ("user", _SpoofedStr())],
    ids=["int_scope", "none_entity", "bytes_scope", "spoofed_scope", "spoofed_entity"],
)
def test_invalidate_index_rejects_non_str(scope: object, entity_id: object) -> None:
    """A non-str scope or entity_id raises TypeError with no cache call
    (AIE-1293, US4.8).
    """
    env = _env()

    with pytest.raises(TypeError):
        env.store.invalidate_index(cast(Any, scope), cast(Any, entity_id))

    assert env.wrapper.gets == []
    assert env.wrapper.sets == []


# --- US5: concurrency ---------------------------------------------------------


def test_write_during_listing_is_seen_by_next_call() -> None:
    """A write committed (with invalidation) while user/u1/ is being listed is
    absent from that result but present on the next call, which re-lists
    (AIE-1293, US5.1).
    """
    env = _standard_env()

    def write() -> None:
        _write_create(env)

    env.storage.after_list[USER_PREFIX] = write
    first = env.store.get_memory_index(MAP2)
    assert _find(first, NEW_PATH) is None

    env.storage.list_calls.clear()
    second = env.store.get_memory_index(MAP2)
    assert env.storage.count(USER_PREFIX) >= 1
    assert _find(second, NEW_PATH) is not None
    assert second == env.uncached()


def test_delete_during_listing_is_seen_by_next_call() -> None:
    """A delete committed while user/u1/ is being listed leaves the file in
    that result; the next call re-lists and omits it (AIE-1293, US5.2).
    """
    env = _standard_env()

    def delete() -> None:
        _delete(env)

    env.storage.after_list[USER_PREFIX] = delete
    first = env.store.get_memory_index(MAP2)
    assert _find(first, A_PATH) is not None

    env.storage.list_calls.clear()
    second = env.store.get_memory_index(MAP2)
    assert env.storage.count(USER_PREFIX) >= 1
    assert _find(second, A_PATH) is None
    assert second == env.uncached()


def test_threaded_writers_and_reader_converge() -> None:
    """Two writers appending and replacing facts on one entity while a reader
    indexes in a loop: the final cached index equals the uncached one
    (AIE-1293, US5.3).
    """
    env = _env(clock=_Clock(T0))
    path = A_PATH
    _seed(env.storage.inner, path, body="- [stated] w0 [w0:0]\n- [stated] w1 [w1:0]\n")
    _seed(env.storage.inner, C_PATH)
    rounds = 20
    barrier = threading.Barrier(3, timeout=5)
    done = threading.Event()
    errors: list[BaseException] = []

    def reader() -> None:
        try:
            barrier.wait()
            while not done.is_set():
                env.store.get_memory_index(MAP2)
        except BaseException as error:
            errors.append(error)

    def writer(k: int) -> None:
        try:
            barrier.wait()
            counter = 0
            for i in range(rounds):
                while True:
                    current = env.store.read_file(path)
                    try:
                        if i % 2 == 0:
                            env.store.append_line(
                                path, f"- [stated] w{k} append {i}", current.version, source=f"w{k}"
                            )
                        else:
                            env.store.replace_fact(
                                path,
                                f"[w{k}:{counter}]",
                                f"[w{k}:{counter + 1}]",
                                current.version,
                                source=f"w{k}",
                            )
                            counter += 1
                        break
                    except VersionConflictError:
                        continue
        except BaseException as error:
            errors.append(error)

    threads = [
        threading.Thread(target=writer, args=(0,)),
        threading.Thread(target=writer, args=(1,)),
    ]
    reader_thread = threading.Thread(target=reader)
    for thread in [*threads, reader_thread]:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    done.set()
    reader_thread.join(timeout=10)

    assert not any(t.is_alive() for t in [*threads, reader_thread])
    assert errors == []
    final = env.store.get_memory_index(MAP2)
    assert final == MemoryStore(env.storage.inner).get_memory_index(MAP2)
    content = env.store.read_file(path).content
    assert f"[w0:{rounds // 2}]" in content
    assert f"[w1:{rounds // 2}]" in content


def test_two_hosts_share_cache() -> None:
    """Two stores over the same storage and cache: a write through one is
    visible in the other's next index (AIE-1293, US5.4).
    """
    env2 = _standard_env()
    env1 = _env(storage=env2.storage, cache=env2.cache, clock=env2.clock)
    env2.store.get_memory_index(MAP2)
    env2.store.get_memory_index(MAP2)

    written = _write_create(env1)
    index = env2.store.get_memory_index(MAP2)

    entry = _find(index, NEW_PATH)
    assert entry is not None
    assert entry.version == written.version
    assert index == env2.uncached()


def _run_nested_reader_on_token_set(env: _Env) -> list[MemoryIndex]:
    """Force two readers that both saw no token: the outer reader's token set
    for user/u1 first runs a full inner index. Returns [inner, outer].
    """
    inner: list[MemoryIndex] = []

    def nested() -> None:
        inner.append(env.store.get_memory_index(MAP2))

    env.wrapper.before_set[USER_TOKEN] = nested
    outer = env.store.get_memory_index(MAP2)
    assert len(inner) == 1
    return [inner[0], outer]


def test_racing_first_readers_both_correct_then_hit() -> None:
    """Two readers that both saw no token each return correct results, and a
    3rd call hits for user/u1/ (AIE-1293, US5.5).
    """
    env = _standard_env()
    expected = env.uncached()

    inner, outer = _run_nested_reader_on_token_set(env)

    assert inner == expected
    assert outer == expected
    env.storage.list_calls.clear()
    third = env.store.get_memory_index(MAP2)
    assert env.storage.count(USER_PREFIX) == 0
    assert third == expected


def test_racing_first_readers_stale_store_landing_last_is_ignored() -> None:
    """If the inner reader's listing (tagged with the overwritten token) lands
    last, the 3rd call re-lists and is correct, and the 4th hits
    (AIE-1293, US5.5b).
    """
    env = _standard_env()
    expected = env.uncached()

    _run_nested_reader_on_token_set(env)
    listing_sets = [value for key, value, _ in env.wrapper.sets if key == USER_LISTING]
    assert len(listing_sets) == 2
    env.cache.set(USER_LISTING, listing_sets[0], T)

    env.storage.list_calls.clear()
    third = env.store.get_memory_index(MAP2)
    assert env.storage.count(USER_PREFIX) >= 1
    assert third == expected

    env.storage.list_calls.clear()
    fourth = env.store.get_memory_index(MAP2)
    assert env.storage.list_calls == []
    assert fourth == expected


@pytest.mark.parametrize("mode", ["create", "replace"])
def test_index_during_put_does_not_hide_write(mode: str) -> None:
    """A full index run inside put_if_version, before the real put, does not
    hide the write from the next index: invalidation follows the storage call
    (AIE-1293, US5.6).
    """
    env = _standard_env()

    def index_now() -> None:
        env.store.get_memory_index(MAP2)

    env.storage.before_put[USER_PREFIX] = index_now
    written = _write_create(env) if mode == "create" else _write_replace(env)
    assert env.storage.before_put == {}

    index = env.store.get_memory_index(MAP2)
    entry = _find(index, written.path)
    assert entry is not None
    assert entry.version == written.version
    assert index == env.uncached()


def test_index_during_delete_does_not_hide_delete() -> None:
    """A full index run inside delete_if_version, before the real delete, does
    not keep the file in the next index (AIE-1293, US5.7).
    """
    env = _standard_env()

    def index_now() -> None:
        env.store.get_memory_index(MAP2)

    env.storage.before_delete[USER_PREFIX] = index_now
    _delete(env)
    assert env.storage.before_delete == {}

    index = env.store.get_memory_index(MAP2)
    assert _find(index, A_PATH) is None
    assert index == env.uncached()


def test_lost_token_key_relists() -> None:
    """If only user/u1's token key is lost, the next index re-lists it and is
    correct (AIE-1293, US5.8).
    """
    env = _standard_env()
    env.store.get_memory_index(MAP2)
    _seed(env.storage.inner, NEW_PATH)

    env.wrapper.delete(USER_TOKEN)
    env.storage.list_calls.clear()
    index = env.store.get_memory_index(MAP2)

    assert env.storage.count(USER_PREFIX) >= 1
    assert index == env.uncached()


def test_lost_listing_key_relists_and_keeps_token() -> None:
    """If only the listing key is lost, the next index re-lists, leaves the
    token unchanged, and a further call hits (AIE-1293, US5.9).
    """
    env = _standard_env()
    env.store.get_memory_index(MAP2)
    token = env.wrapper.raw(USER_TOKEN)
    assert token is not None

    env.wrapper.delete(USER_LISTING)
    env.storage.list_calls.clear()
    index = env.store.get_memory_index(MAP2)

    assert env.storage.count(USER_PREFIX) >= 1
    assert index == env.uncached()
    assert env.wrapper.raw(USER_TOKEN) == token

    env.storage.list_calls.clear()
    again = env.store.get_memory_index(MAP2)
    assert env.storage.list_calls == []
    assert again == index


def test_token_expiring_before_listing_relists() -> None:
    """When the token key expires before the listing key (set later), the next
    index re-lists user/u1/ and is correct (AIE-1293, US5.10).
    """
    env = _standard_env()
    d = T / 2

    def advance() -> None:
        env.clock.advance(d)

    env.storage.after_list[USER_PREFIX] = advance
    env.store.get_memory_index(MAP2)
    assert env.clock.now == T0 + d
    # An out-of-band write makes a wrongly served stale listing visible.
    _seed(env.storage.inner, NEW_PATH)

    env.clock.now = T0 + T
    assert env.cache.get(USER_TOKEN) is None
    assert env.cache.get(USER_LISTING) is not None
    env.storage.list_calls.clear()
    index = env.store.get_memory_index(MAP2)

    assert env.storage.count(USER_PREFIX) >= 1
    assert _find(index, NEW_PATH) is not None
    assert index == env.uncached()


def test_distinct_key_prefixes_isolate_storage_roots() -> None:
    """Two stores over different storage sharing one cache with prefixes "a:"
    and "b:" only ever show their own files (AIE-1293, US5.11).
    """
    clock = _Clock(T0)
    cache = InMemoryIndexCache(clock=clock)
    env_a = _env(cache=cache, clock=clock, key_prefix="a:")
    env_b = _env(cache=cache, clock=clock, key_prefix="b:")
    _seed(env_a.storage.inner, "user/u1/notes/only-a.md")
    _seed(env_b.storage.inner, "user/u1/notes/only-b.md")

    for _ in range(2):
        assert env_a.store.get_memory_index(MAP2) == env_a.uncached()
        assert env_b.store.get_memory_index(MAP2) == env_b.uncached()
    assert cache.get(_token_key("user", "u1", "a:")) is not None
    assert cache.get(_token_key("user", "u1", "b:")) is not None

    env_a.store.write_file("user/u1/notes/new-a.md", BODY, _metadata(), None, source="t")
    env_b.store.write_file("user/u1/notes/new-b.md", BODY, _metadata(), None, source="t")

    for _ in range(2):
        index_a = env_a.store.get_memory_index(MAP2)
        index_b = env_b.store.get_memory_index(MAP2)
        assert index_a == env_a.uncached()
        assert index_b == env_b.uncached()
        assert sorted(_paths(index_a)) == ["user/u1/notes/new-a.md", "user/u1/notes/only-a.md"]
        assert sorted(_paths(index_b)) == ["user/u1/notes/new-b.md", "user/u1/notes/only-b.md"]


# --- US6: ttl and out-of-band writers -----------------------------------------


def _cached_then_out_of_band_write(env: _Env) -> None:
    env.store.get_memory_index(MAP2)
    MemoryStore(env.storage).write_file(NEW_PATH, BODY, _metadata(), None, source="oob")
    env.storage.list_calls.clear()


def test_out_of_band_write_is_stale_within_ttl() -> None:
    """A write through a cacheless store is not visible before ttl elapses,
    and the index makes zero list_page calls (AIE-1293, US6.1).
    """
    env = _standard_env(ttl=T)
    _cached_then_out_of_band_write(env)

    env.clock.advance(T - timedelta(seconds=1))
    index = env.store.get_memory_index(MAP2)

    assert env.storage.list_calls == []
    assert _find(index, NEW_PATH) is None


def test_out_of_band_write_visible_after_ttl() -> None:
    """Past ttl, the out-of-band write is visible (AIE-1293, US6.2)."""
    env = _standard_env(ttl=T)
    _cached_then_out_of_band_write(env)

    env.clock.advance(T + timedelta(seconds=1))
    index = env.store.get_memory_index(MAP2)

    assert _find(index, NEW_PATH) is not None
    assert index == env.uncached()


def test_out_of_band_write_visible_after_invalidate_index() -> None:
    """invalidate_index makes the out-of-band write visible (AIE-1293, US6.3)."""
    env = _standard_env(ttl=T)
    _cached_then_out_of_band_write(env)

    env.store.invalidate_index("user", "u1")
    index = env.store.get_memory_index(MAP2)

    assert _find(index, NEW_PATH) is not None
    assert index == env.uncached()


@pytest.mark.parametrize("ttl", [None, T, timedelta(seconds=7)], ids=["none", "T", "7s"])
def test_every_set_receives_configured_ttl(ttl: timedelta | None) -> None:
    """Every cache set, from indexing, mutations, and invalidate_index,
    receives ttl exactly as configured (AIE-1293, US6.4).
    """
    env = _standard_env(ttl=ttl)

    env.store.get_memory_index(MAP2)
    _write_create(env)
    _append(env)
    _replace_fact(env)
    _write_replace(env)
    env.store.get_memory_index(MAP2)
    _delete(env)
    env.store.invalidate_index("project", "p1")
    env.store.get_memory_index(MAP2)

    assert len(env.wrapper.sets) >= 10
    for _, _, got in env.wrapper.sets:
        assert got is ttl


# --- US7: cache failures and bad values ---------------------------------------

SECRET_MAP: dict[str, str] = {"user": "zq-secret-ent-1", "project": "zq-secret-ent-2"}


def test_get_failure_falls_back_and_logs_scope_not_entity(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A raising get yields the correct index from storage and logs a WARNING
    on wenchang.core naming the scope, never the entity ID (AIE-1293, US7.1).
    """
    caplog.set_level(logging.DEBUG)
    env = _env()
    _seed(env.storage.inner, "user/zq-secret-ent-1/notes/a.md")
    _seed(env.storage.inner, "project/zq-secret-ent-2/notes/b.md")
    env.wrapper.get_raises = _CacheBoom("cache down")

    index = env.store.get_memory_index(SECRET_MAP)

    assert index == env.uncached(SECRET_MAP)
    assert env.storage.count("user/zq-secret-ent-1/") >= 1
    warnings = _warnings(caplog)
    assert warnings
    messages = [r.getMessage() for r in warnings]
    assert any("user" in m for m in messages)
    assert any("project" in m for m in messages)
    for record in caplog.records:
        assert "zq-secret" not in record.getMessage()
    assert "zq-secret" not in caplog.text


def test_bytes_from_get_is_a_logged_miss(caplog: pytest.LogCaptureFixture) -> None:
    """A get returning bytes (a valid encoding as bytes) is logged and treated
    as a miss; storage is listed and the result is correct (AIE-1293, US7.1b).
    """
    caplog.set_level(logging.WARNING, logger="wenchang.core")
    env = _standard_env()
    env.store.get_memory_index(MAP2)
    token = env.wrapper.raw(USER_TOKEN)
    listing = env.wrapper.raw(USER_LISTING)
    assert token is not None
    assert listing is not None
    env.wrapper.scripted[USER_TOKEN] = token.encode("utf-8")
    env.wrapper.scripted[USER_LISTING] = listing.encode("utf-8")
    _seed(env.storage.inner, NEW_PATH)

    env.storage.list_calls.clear()
    index = env.store.get_memory_index(MAP2)

    assert env.storage.count(USER_PREFIX) >= 1
    assert index == env.uncached()
    assert any("user" in r.getMessage() for r in _warnings(caplog))
    assert "u1" not in caplog.text


def test_set_failure_does_not_fail_index_or_write(caplog: pytest.LogCaptureFixture) -> None:
    """A raising set leaves get_memory_index and write_file returning normally
    with correct results, and logs warnings (AIE-1293, US7.2).
    """
    caplog.set_level(logging.WARNING, logger="wenchang.core")
    env = _standard_env()
    env.wrapper.set_raises = _CacheBoom("cache down")

    first = env.store.get_memory_index(MAP2)
    assert first == env.uncached()
    assert _warnings(caplog)
    caplog.clear()

    written = _write_create(env)
    assert env.storage.inner.get(NEW_PATH) is not None
    assert written.path == NEW_PATH
    assert _warnings(caplog)

    second = env.store.get_memory_index(MAP2)
    assert _find(second, NEW_PATH) is not None
    assert second == env.uncached()


def test_set_failure_does_not_mask_mutation_error(caplog: pytest.LogCaptureFixture) -> None:
    """A raising set during a failed mutation's invalidation does not replace
    the mutation's own exception (AIE-1293, US7.2).
    """
    caplog.set_level(logging.WARNING, logger="wenchang.core")
    env = _standard_env()
    env.wrapper.set_raises = _CacheBoom("cache down")
    error = BackendUnavailableError(TransientReason.UNAVAILABLE)
    env.storage.put_raises = error

    with pytest.raises(BackendUnavailableError) as excinfo:
        _write_create(env)

    assert excinfo.value is error


def test_invalidate_index_propagates_set_failure() -> None:
    """invalidate_index propagates the cache's exception (AIE-1293, US7.3)."""
    env = _env()
    boom = _CacheBoom("cache down")
    env.wrapper.set_raises = boom

    with pytest.raises(_CacheBoom) as excinfo:
        env.store.invalidate_index("user", "u1")

    assert excinfo.value is boom


def _encode_listing(token: str, entries: Sequence[Mapping[str, object]]) -> str:
    return json.dumps({"token": token, "entries": list(entries)}, separators=(",", ":"))


def _entry_dict(entry: FileEntry) -> dict[str, object]:
    return {
        "path": entry.path,
        "version": entry.version,
        "description": entry.metadata.description,
        "aliases": list(entry.metadata.aliases),
        "sources": sorted(entry.metadata.sources),
        "last_updated": entry.metadata.last_updated.isoformat(),
    }


def _user_entry_dicts(env: _Env) -> list[dict[str, object]]:
    index = env.uncached({"user": "u1"})
    return [_entry_dict(e) for e in index.entries]


def _with(entries: list[dict[str, object]], i: int, **changes: object) -> list[dict[str, object]]:
    out = [dict(e) for e in entries]
    out[i].update(changes)
    return out


_CRAFTED: dict[str, Callable[[str, list[dict[str, object]]], str]] = {
    "garbage": lambda tok, es: "not json {",
    "empty": lambda tok, es: "",
    "json_list": lambda tok, es: json.dumps([tok, es]),
    "json_string": lambda tok, es: json.dumps(tok),
    "missing_entries": lambda tok, es: json.dumps({"token": tok}),
    "entries_not_list": lambda tok, es: json.dumps({"token": tok, "entries": {"a": 1}}),
    "entry_not_object": lambda tok, es: _encode_listing(tok, cast(Any, ["x"])),
    "entry_missing_field": lambda tok, es: _encode_listing(
        tok, [{k: v for k, v in es[0].items() if k != "version"}, *es[1:]]
    ),
    "version_int": lambda tok, es: _encode_listing(tok, _with(es, 0, version=5)),
    "path_int": lambda tok, es: _encode_listing(tok, _with(es, 0, path=7)),
    "description_int": lambda tok, es: _encode_listing(tok, _with(es, 0, description=3)),
    "aliases_string": lambda tok, es: _encode_listing(tok, _with(es, 0, aliases="al")),
    "aliases_member_int": lambda tok, es: _encode_listing(tok, _with(es, 0, aliases=[1])),
    "sources_member_null": lambda tok, es: _encode_listing(tok, _with(es, 0, sources=[None])),
    "last_updated_int": lambda tok, es: _encode_listing(tok, _with(es, 0, last_updated=0)),
    "last_updated_garbage": lambda tok, es: _encode_listing(tok, _with(es, 0, last_updated="x")),
    "naive_last_updated": lambda tok, es: _encode_listing(
        tok, _with(es, 0, last_updated="2024-01-01T00:00:00")
    ),
    "description_newline": lambda tok, es: _encode_listing(tok, _with(es, 0, description="a\nb")),
    "invalid_path": lambda tok, es: _encode_listing(
        tok, [*es, {**es[0], "path": "user/u1/notes/x.txt"}]
    ),
    "foreign_entity_path": lambda tok, es: _encode_listing(
        tok, [*es, {**es[0], "path": "user/u2/notes/a.md"}]
    ),
    "foreign_scope_path": lambda tok, es: _encode_listing(
        tok, [*es, {**es[0], "path": "project/p1/notes/zz.md"}]
    ),
    "prefix_lookalike_path": lambda tok, es: _encode_listing(
        tok, [*es, {**es[0], "path": "user/u10/notes/a.md"}]
    ),
    "duplicate_path": lambda tok, es: _encode_listing(tok, [*es, es[0]]),
}


@pytest.mark.parametrize("craft", list(_CRAFTED.values()), ids=list(_CRAFTED))
def test_invalid_listing_value_is_a_miss(
    craft: Callable[[str, list[dict[str, object]]], str],
) -> None:
    """A listing value under the current token that is not a valid encoding is
    treated as a miss: storage is listed and the result is correct
    (AIE-1293, US7.4).
    """
    env = _standard_env()
    env.store.get_memory_index(MAP2)
    token = env.wrapper.raw(USER_TOKEN)
    assert token is not None
    env.cache.set(USER_LISTING, craft(token, _user_entry_dicts(env)), None)

    env.storage.list_calls.clear()
    index = env.store.get_memory_index(MAP2)

    assert env.storage.count(USER_PREFIX) >= 1
    assert index == env.uncached()


def test_tombstone_under_current_token_is_a_miss() -> None:
    """The tombstone written by invalidate_index, put back under the current
    token, is treated as a miss (AIE-1293, US7.4).
    """
    env = _standard_env()
    env.store.get_memory_index(MAP2)
    token = env.wrapper.raw(USER_TOKEN)
    assert token is not None
    env.store.invalidate_index("user", "u1")
    tombstone = env.wrapper.raw(USER_LISTING)
    assert tombstone is not None
    env.cache.set(USER_TOKEN, token, None)

    env.storage.list_calls.clear()
    index = env.store.get_memory_index(MAP2)

    assert env.storage.count(USER_PREFIX) >= 1
    assert index == env.uncached()


def test_well_formed_crafted_listing_is_a_hit() -> None:
    """Control for the invalid-value cases: a value in the documented shape
    under the current token is served without listing (AIE-1293, US7.4).
    """
    env = _standard_env()
    env.store.get_memory_index(MAP2)
    token = env.wrapper.raw(USER_TOKEN)
    assert token is not None
    env.cache.set(USER_LISTING, _encode_listing(token, _user_entry_dicts(env)), None)

    env.storage.list_calls.clear()
    index = env.store.get_memory_index(MAP2)

    assert env.storage.list_calls == []
    assert index == env.uncached()


def test_corrupt_metadata_raises_and_stores_nothing() -> None:
    """Corrupt stored metadata raises MetadataFormatError on every call and
    nothing is stored under the listing key (AIE-1293, US7.5).
    """
    env = _env()
    _seed(env.storage.inner, B_PATH)
    bad = metadata_to_map(_metadata())
    del bad["description"]
    env.storage.inner.put(A_PATH, b"body", bad)

    for _ in range(2):
        with pytest.raises(MetadataFormatError):
            env.store.get_memory_index(MAP2)

    assert env.wrapper.raw(USER_LISTING) is None
    assert all(key != USER_LISTING for key, _, _ in env.wrapper.sets)


def test_base_exception_from_get_propagates() -> None:
    """A BaseException that is not an Exception from get propagates
    (AIE-1293, US7.6).
    """
    env = _standard_env()
    env.wrapper.get_raises = _Abort()

    with pytest.raises(_Abort):
        env.store.get_memory_index(MAP2)


def test_base_exception_from_set_propagates() -> None:
    """A BaseException that is not an Exception from set propagates
    (AIE-1293, US7.6).
    """
    env = _standard_env()
    env.wrapper.set_raises = _Abort()

    with pytest.raises(_Abort):
        env.store.get_memory_index(MAP2)


_BAD_SCOPE_MAPS: dict[str, object] = {
    "empty_scope": {"": "u1"},
    "slash_scope": {"a/b": "u1"},
    "empty_entity": {"user": ""},
    "slash_entity": {"user": "u/1"},
    "int_entity": {"user": 1},
    "int_scope": {1: "u1"},
    "not_mapping": ["user"],
    "none": None,
}


@pytest.mark.parametrize("scope_map", list(_BAD_SCOPE_MAPS.values()), ids=list(_BAD_SCOPE_MAPS))
def test_invalid_scope_map_errors_match_uncached_with_no_cache_call(scope_map: object) -> None:
    """An invalid scope_map raises the same error as a cacheless store, with no
    cache call (AIE-1293, US7.7).
    """
    env = _env()

    with pytest.raises((TypeError, ValueError)) as expected:
        MemoryStore(InMemoryStorage()).get_memory_index(cast(Any, scope_map))
    with pytest.raises(expected.type) as got:
        env.store.get_memory_index(cast(Any, scope_map))

    assert type(got.value) is expected.type
    assert str(got.value) == str(expected.value)
    assert env.wrapper.gets == []
    assert env.wrapper.sets == []


def test_empty_scope_map_makes_no_cache_call() -> None:
    """An empty scope_map returns an empty index with no cache call
    (AIE-1293, US7.7).
    """
    env = _env()

    assert env.store.get_memory_index({}) == MemoryIndex()
    assert env.wrapper.gets == []
    assert env.wrapper.sets == []
