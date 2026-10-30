"""Tests for wenchang.index_cache: IndexCache configuration and InMemoryIndexCache.

Covers AIE-1293, US1.1-US1.4 and US8.1-US8.3.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from wenchang.index_cache import DEFAULT_KEY_PREFIX, IndexCache, InMemoryIndexCache

pytestmark = pytest.mark.unit

T = timedelta(minutes=5)
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _get(key: str) -> str | None:
    return None


def _set(key: str, value: str, ttl: timedelta | None) -> None:
    return None


class _Clock:
    """A settable clock."""

    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class _SpoofedTimedelta:
    """Not a timedelta, but claims to be one via __class__."""

    @property
    def __class__(self) -> type:  # pyright: ignore[reportIncompatibleMethodOverride]
        return timedelta


class _SpoofedStr:
    """Not a str, but claims to be one via __class__."""

    @property
    def __class__(self) -> type:  # pyright: ignore[reportIncompatibleMethodOverride]
        return str


class _Str(str):
    """A str subclass."""


class _LyingStr(str):
    """A str subclass whose __str__ lies."""

    def __str__(self) -> str:
        return "evil"


# --- US1: configuration -------------------------------------------------------


def test_defaults() -> None:
    """ttl defaults to None and key_prefix to "wenchang:index:" (AIE-1293, US1.1)."""
    config = IndexCache(get=_get, set=_set)

    assert config.ttl is None
    assert config.key_prefix == "wenchang:index:"
    assert DEFAULT_KEY_PREFIX == "wenchang:index:"
    assert config.get is _get
    assert config.set is _set


def test_given_ttl_is_stored_as_given() -> None:
    """A positive ttl is stored as the same object (AIE-1293, US1.1)."""
    config = IndexCache(get=_get, set=_set, ttl=T)

    assert config.ttl is T


_BAD_TYPE_ARGS: dict[str, dict[str, Any]] = {
    "get_not_callable": {"get": "nope"},
    "get_none": {"get": None},
    "set_not_callable": {"set": 3},
    "set_none": {"set": None},
    "ttl_int": {"ttl": 300},
    "ttl_float": {"ttl": 1.5},
    "ttl_datetime": {"ttl": T0},
    "ttl_spoofed_timedelta": {"ttl": _SpoofedTimedelta()},
    "key_prefix_bytes": {"key_prefix": b"p:"},
    "key_prefix_none": {"key_prefix": None},
    "key_prefix_spoofed_str": {"key_prefix": _SpoofedStr()},
}


@pytest.mark.parametrize("overrides", list(_BAD_TYPE_ARGS.values()), ids=list(_BAD_TYPE_ARGS))
def test_wrong_types_raise_type_error(overrides: dict[str, Any]) -> None:
    """Non-callable get/set, a ttl that is not None or a real timedelta, or a
    key_prefix that is not a real str raises TypeError (AIE-1293, US1.2).
    """
    kwargs: dict[str, Any] = {"get": _get, "set": _set, **overrides}

    with pytest.raises(TypeError):
        IndexCache(**kwargs)


def test_type_error_precedes_value_error() -> None:
    """A wrongly typed key_prefix with a non-positive ttl raises TypeError, not
    ValueError (AIE-1293, US1.2, US1.3).
    """
    with pytest.raises(TypeError):
        IndexCache(get=_get, set=_set, ttl=timedelta(0), key_prefix=cast(Any, 5))


@pytest.mark.parametrize(
    "ttl",
    [timedelta(0), timedelta(seconds=-1), timedelta(microseconds=-1)],
    ids=["zero", "negative_seconds", "negative_microsecond"],
)
def test_non_positive_ttl_raises_value_error(ttl: timedelta) -> None:
    """ttl <= timedelta(0) raises ValueError (AIE-1293, US1.3)."""
    with pytest.raises(ValueError):
        IndexCache(get=_get, set=_set, ttl=ttl)


def test_smallest_positive_ttl_is_accepted() -> None:
    """A one-microsecond ttl is positive and accepted (AIE-1293, US1.3)."""
    ttl = timedelta(microseconds=1)

    assert IndexCache(get=_get, set=_set, ttl=ttl).ttl == ttl


@pytest.mark.parametrize("prefix", [_Str("p:"), _LyingStr("p:")], ids=["subclass", "lying"])
def test_str_subclass_key_prefix_is_stored_as_exact_str(prefix: str) -> None:
    """A str-subclass key_prefix is stored as an exact str with the same
    characters (AIE-1293, US1.4).
    """
    config = IndexCache(get=_get, set=_set, key_prefix=prefix)

    assert type(config.key_prefix) is str
    assert str.__str__(config.key_prefix) == "p:"


# --- US8: InMemoryIndexCache --------------------------------------------------


def test_in_memory_set_without_ttl_never_expires() -> None:
    """set(k, v, None) then get(k) returns v, even far in the future
    (AIE-1293, US8.1).
    """
    clock = _Clock(T0)
    cache = InMemoryIndexCache(clock=clock)

    cache.set("k", "v", None)
    assert cache.get("k") == "v"

    clock.now = T0 + timedelta(days=36500)
    assert cache.get("k") == "v"


def test_in_memory_set_overwrites() -> None:
    """A second set replaces the value (AIE-1293, US8.1)."""
    cache = InMemoryIndexCache(clock=_Clock(T0))

    cache.set("k", "v1", None)
    cache.set("k", "v2", None)

    assert cache.get("k") == "v2"


def test_in_memory_expires_at_exactly_ttl() -> None:
    """An entry set with ttl T is present just before T elapses and None at
    exactly T later (AIE-1293, US8.2).
    """
    clock = _Clock(T0)
    cache = InMemoryIndexCache(clock=clock)

    cache.set("k", "v", T)

    clock.now = T0 + T - timedelta(microseconds=1)
    assert cache.get("k") == "v"

    clock.now = T0 + T
    assert cache.get("k") is None


def test_in_memory_expired_entry_stays_gone() -> None:
    """Once expired, an entry is not returned even if the clock moves back
    (AIE-1293, US8.2).
    """
    clock = _Clock(T0)
    cache = InMemoryIndexCache(clock=clock)
    cache.set("k", "v", T)

    clock.now = T0 + T
    assert cache.get("k") is None

    clock.now = T0
    assert cache.get("k") is None


def test_in_memory_reset_ttl_restarts_expiry() -> None:
    """Re-setting a key restarts its expiry from the new set time
    (AIE-1293, US8.2).
    """
    clock = _Clock(T0)
    cache = InMemoryIndexCache(clock=clock)
    cache.set("k", "v1", T)

    clock.now = T0 + T / 2
    cache.set("k", "v2", T)

    clock.now = T0 + T
    assert cache.get("k") == "v2"

    clock.now = T0 + T / 2 + T
    assert cache.get("k") is None


def test_in_memory_missing_key_is_none() -> None:
    """get of a key never set returns None (AIE-1293, US8.3)."""
    cache = InMemoryIndexCache(clock=_Clock(T0))

    assert cache.get("missing") is None


def test_in_memory_default_clock_works_with_index_cache() -> None:
    """InMemoryIndexCache() with the default clock plugs into IndexCache
    (AIE-1293, US8.1).
    """
    cache = InMemoryIndexCache()
    getter: Callable[[str], str | None] = cache.get
    setter: Callable[[str, str, timedelta | None], None] = cache.set
    config = IndexCache(get=getter, set=setter, ttl=T)

    config.set("k", "v", config.ttl)

    assert config.get("k") == "v"
