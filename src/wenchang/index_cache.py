"""Optional adopter-supplied cache for MemoryStore.get_memory_index."""

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, cast

CacheGet = Callable[[str], str | None]
CacheSet = Callable[[str, str, timedelta | None], None]

DEFAULT_KEY_PREFIX: Final = "wenchang:index:"


def _type_name(t: type) -> str:
    # A metaclass may make __name__ raise or return a str subclass.
    try:
        return str.__str__(t.__name__)
    except Exception:
        return "<unnamed>"


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class IndexCache:
    """Cache configuration for MemoryStore's memory index.

    `get(key)` returns the value last `set` for `key`, or None if absent or
    expired. `set(key, value, ttl)` stores `value` expiring `ttl` from now
    (None: no expiry). Both are required, since `set` is how the library
    invalidates, and both must be linearizable per key; neither needs to be
    atomic across keys. Values are opaque strs.

    With `ttl=None`, a swallowed invalidation failure or a write that
    bypasses the cache leaves an entity stale with no bound; use a finite
    `ttl` in production. Keys carry no storage identity, so stores over
    different storage roots sharing one cache need distinct `key_prefix`es.
    """

    get: CacheGet
    set: CacheSet
    ttl: timedelta | None = None
    key_prefix: str = DEFAULT_KEY_PREFIX

    def __post_init__(self) -> None:
        get = cast(object, self.get)
        set_ = cast(object, self.set)
        ttl = cast(object, self.ttl)
        key_prefix = cast(object, self.key_prefix)
        if not callable(get):
            raise TypeError(f"get must be callable, not {_type_name(type(get))}")
        if not callable(set_):
            raise TypeError(f"set must be callable, not {_type_name(type(set_))}")
        # Real-type checks: a spoofed __class__ must not pass.
        if ttl is not None and not issubclass(type(ttl), timedelta):
            raise TypeError(f"ttl must be a timedelta or None, not {_type_name(type(ttl))}")
        if not issubclass(type(key_prefix), str):
            raise TypeError(f"key_prefix must be a str, not {_type_name(type(key_prefix))}")
        object.__setattr__(self, "key_prefix", str.__str__(cast(str, key_prefix)))
        if ttl is not None and cast(timedelta, ttl) <= timedelta(0):
            raise ValueError("ttl must be positive")


class InMemoryIndexCache:
    """Thread-safe in-process cache for tests and single-process adopters.

    Multi-instance hosts need a shared cache. Expired entries are dropped
    only when read, so with `ttl=None` the cache grows without bound.

    Usage: `cache = InMemoryIndexCache()`, then
    `IndexCache(get=cache.get, set=cache.set, ttl=timedelta(minutes=5))`.
    """

    def __init__(self, *, clock: Callable[[], datetime] = _utc_now) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[str, datetime | None]] = {}

    def get(self, key: str) -> str | None:
        """The value for `key`, or None if absent or expired."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if expires_at is not None and self._clock() >= expires_at:
                del self._entries[key]
                return None
            return value

    def set(self, key: str, value: str, ttl: timedelta | None) -> None:
        """Store `value` under `key`, expiring `ttl` from now (None: never)."""
        with self._lock:
            expires_at = None if ttl is None else self._clock() + ttl
            self._entries[key] = (value, expires_at)
