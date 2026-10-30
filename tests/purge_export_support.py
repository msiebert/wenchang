"""Shared fixtures for the entity purge and export tests.

`RecordingStorage` (the spec's `H`) wraps an `InMemoryStorage` (`S`),
logs every call in order, and runs per-method hooks. Seed helpers write
with `Storage.put` so they can include shapes core would refuse.

Import with a bare `from purge_export_support import ...`, like
`storage_conformance`.
"""

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta

from wenchang.file_format import FileMetadata, metadata_to_map
from wenchang.index_cache import DEFAULT_KEY_PREFIX, IndexCache, InMemoryIndexCache
from wenchang.storage import ListedObject, Storage, StoredObject
from wenchang.storage.memory import InMemoryStorage
from wenchang.version_token import VersionToken

SECRET_ENTITY = "ent-q7zx-erasure"

BODY = b"- [stated] alpha fact\n"
NON_UTF8 = b"\xff\xfe\x00 not utf-8 \xc3\x28"
CORRUPT_METADATA: dict[str, str] = {"aliases": "not json"}

# Relative to "{scope}/{entity_id}/", in ascending key order.
SEED_SUFFIXES = (
    "notes/a.md",
    "notes/b.md",
    "notes/bin.md",
    "odd-key",
    "prefs/c.md",
    "system/rules.md",
)
VALID_SUFFIXES = tuple(s for s in SEED_SUFFIXES if s != "prefs/c.md")
# Readable through read_file with their original content.
READABLE_SUFFIXES = ("notes/a.md", "notes/b.md", "system/rules.md")

NEIGHBOURS = (
    "user/u10/notes/a.md",
    "user/u2/notes/a.md",
    "project/u1/notes/a.md",
    "user-archive/u1/notes/a.md",
)

Call = tuple[str, tuple[object, ...]]


def description_for(suffix: str) -> str:
    return f"desc-{suffix.replace('/', '-')}-zq9"


def alias_for(suffix: str) -> str:
    return f"alias-{suffix.replace('/', '-')}-zq9"


def valid_metadata(description: str = "d", aliases: tuple[str, ...] = ()) -> dict[str, str]:
    return metadata_to_map(
        FileMetadata(
            description=description,
            aliases=aliases,
            sources=frozenset({"seed"}),
            last_updated=datetime(2024, 1, 1, tzinfo=UTC),
        )
    )


def _seed_object(storage: Storage, key: str, suffix: str, *, corrupt: bool) -> VersionToken:
    data = NON_UTF8 if suffix == "notes/bin.md" else BODY
    if corrupt and suffix == "prefs/c.md":
        metadata = dict(CORRUPT_METADATA)
    else:
        metadata = valid_metadata(description_for(suffix), (alias_for(suffix),))
    return storage.put(key, data, metadata)


def seed_entity(
    storage: Storage, scope: str = "user", entity_id: str = "u1"
) -> dict[str, VersionToken]:
    """Seed E: six objects, one with corrupt metadata. Returns key -> version."""
    prefix = f"{scope}/{entity_id}/"
    return {prefix + s: _seed_object(storage, prefix + s, s, corrupt=True) for s in SEED_SUFFIXES}


def seed_valid_entity(
    storage: Storage, scope: str = "user", entity_id: str = "u1"
) -> dict[str, VersionToken]:
    """Seed E_valid: E minus prefs/c.md, all metadata well-formed."""
    prefix = f"{scope}/{entity_id}/"
    return {prefix + s: _seed_object(storage, prefix + s, s, corrupt=False) for s in VALID_SUFFIXES}


def seed_many(
    storage: Storage, count: int = 7, scope: str = "user", entity_id: str = "u1"
) -> list[str]:
    """Seed `count` valid objects; returns their keys in ascending order."""
    keys = [f"{scope}/{entity_id}/notes/n{i:02d}.md" for i in range(count)]
    for key in keys:
        storage.put(key, BODY, valid_metadata())
    return keys


def seed_neighbours(storage: Storage) -> None:
    for key in NEIGHBOURS:
        storage.put(key, BODY, valid_metadata(f"neighbour {key}"))


Snapshot = tuple[bytes, dict[str, str], VersionToken]


def snapshot(storage: Storage, keys: Sequence[str]) -> dict[str, Snapshot]:
    """Data, metadata, and version of each key (all must exist)."""
    out: dict[str, Snapshot] = {}
    for key in keys:
        obj = storage.get(key)
        assert obj is not None, key
        out[key] = (obj.data, dict(obj.metadata), obj.version)
    return out


ListHook = Callable[[str, str | None, int], None]
AfterListHook = Callable[[str, str | None, int, Sequence[ListedObject]], None]
KeyHook = Callable[[str], None]
DeleteHook = Callable[[str, VersionToken], None]


class RecordingStorage:
    """The spec's `H`: a call-logging Storage over an InMemoryStorage.

    Hooks run on every call to their method; each hook can raise to inject
    an exception. `count(method)` is the number of calls so far, including
    the current one while a hook runs.
    """

    def __init__(self, inner: InMemoryStorage | None = None) -> None:
        self.inner = inner if inner is not None else InMemoryStorage()
        self.calls: list[Call] = []
        self.before_list: ListHook | None = None
        self.after_list: AfterListHook | None = None
        self.before_get: KeyHook | None = None
        self.before_delete: DeleteHook | None = None

    def count(self, method: str) -> int:
        return sum(1 for name, _ in self.calls if name == method)

    def calls_to(self, method: str) -> list[tuple[object, ...]]:
        return [args for name, args in self.calls if name == method]

    def storage_calls(self) -> list[Call]:
        return [c for c in self.calls if not c[0].startswith("cache.")]

    def get(self, key: str) -> StoredObject | None:
        self.calls.append(("get", (key,)))
        if self.before_get is not None:
            self.before_get(key)
        return self.inner.get(key)

    def put(self, key: str, data: bytes, metadata: Mapping[str, str]) -> VersionToken:
        self.calls.append(("put", (key, data, dict(metadata))))
        return self.inner.put(key, data, metadata)

    def put_if_version(
        self,
        key: str,
        data: bytes,
        metadata: Mapping[str, str],
        expected: VersionToken | None,
    ) -> VersionToken:
        self.calls.append(("put_if_version", (key, data, dict(metadata), expected)))
        return self.inner.put_if_version(key, data, metadata, expected)

    def list_page(self, prefix: str, start_after: str | None, limit: int) -> Sequence[ListedObject]:
        self.calls.append(("list_page", (prefix, start_after, limit)))
        if self.before_list is not None:
            self.before_list(prefix, start_after, limit)
        result = self.inner.list_page(prefix, start_after, limit)
        if self.after_list is not None:
            self.after_list(prefix, start_after, limit, result)
        return result

    def delete_if_version(self, key: str, expected: VersionToken) -> None:
        self.calls.append(("delete_if_version", (key, expected)))
        if self.before_delete is not None:
            self.before_delete(key, expected)
        self.inner.delete_if_version(key, expected)


class LoggingCache:
    """InMemoryIndexCache wrapper that logs `set` calls into H's call log."""

    def __init__(self, log: list[Call], inner: InMemoryIndexCache | None = None) -> None:
        self.inner = inner if inner is not None else InMemoryIndexCache()
        self.log = log
        self.set_raises: BaseException | None = None

    def get(self, key: str) -> str | None:
        return self.inner.get(key)

    def set(self, key: str, value: str, ttl: timedelta | None) -> None:
        self.log.append(("cache.set", (key,)))
        if self.set_raises is not None:
            raise self.set_raises
        self.inner.set(key, value, ttl)

    def raw(self, key: str) -> str | None:
        return self.inner.get(key)

    def config(self) -> IndexCache:
        return IndexCache(get=self.get, set=self.set)


def token_key(scope: str, entity_id: str) -> str:
    return f"{DEFAULT_KEY_PREFIX}v1:token:{scope}/{entity_id}"


def listing_key(scope: str, entity_id: str) -> str:
    return f"{DEFAULT_KEY_PREFIX}v1:listing:{scope}/{entity_id}"
