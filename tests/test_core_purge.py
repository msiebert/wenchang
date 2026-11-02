"""Tests for MemoryStore.purge: deletion, passes under concurrent writers, and
index-cache invalidation.

Covers AIE-1291, US1-US3.
"""

import copy
import logging
import pickle
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from purge_export_support import (
    NEIGHBOURS,
    SECRET_ENTITY,
    SEED_SUFFIXES,
    VALID_SUFFIXES,
    LoggingCache,
    RecordingStorage,
    alias_for,
    description_for,
    listing_key,
    seed_entity,
    seed_many,
    seed_neighbours,
    seed_valid_entity,
    snapshot,
    token_key,
    valid_metadata,
)
from wenchang.core import PURGE_MAX_PASSES, MemoryIndex, MemoryStore, PurgeIncompleteError
from wenchang.errors import BackendUnavailableError, NotFoundError, NotFoundReason, TransientReason
from wenchang.file_format import FileMetadata
from wenchang.version_token import VersionToken

pytestmark = pytest.mark.unit

PREFIX = "user/u1/"


class _CacheBoom(Exception):
    """A cache failure."""


class _SpoofedStr:
    """Not a str, but claims to be one via __class__."""

    @property
    def __class__(self) -> type:  # pyright: ignore[reportIncompatibleMethodOverride]
        return str


def _m(h: RecordingStorage) -> MemoryStore:
    return MemoryStore(h, list_page_size=2)


def _mc(h: RecordingStorage, cache: LoggingCache | None = None) -> tuple[MemoryStore, LoggingCache]:
    cache = cache if cache is not None else LoggingCache(h.calls)
    return MemoryStore(h, list_page_size=2, index_cache=cache.config()), cache


def _listed(h: RecordingStorage, prefix: str = PREFIX) -> list[str]:
    return [o.key for o in h.inner.list_page(prefix, None, 100)]


def _restarts(h: RecordingStorage, prefix: str = PREFIX) -> int:
    """list_page calls under `prefix` starting from the beginning."""
    return sum(1 for args in h.calls_to("list_page") if args[0] == prefix and args[1] is None)


def _fresh_writer(h: RecordingStorage, prefix: str = PREFIX) -> None:
    """Install the 2.4 hook: each list_page under `prefix` first writes a fresh key."""
    n = 0

    def hook(p: str, start_after: str | None, limit: int) -> None:
        nonlocal n
        if p != prefix:
            return
        n += 1
        h.inner.put(f"{prefix}zz/fresh-{n:04d}.md", b"- [stated] fresh\n", valid_metadata("fresh"))

    h.before_list = hook


def _on_first_delete(h: RecordingStorage, action: Callable[[str, VersionToken], None]) -> None:
    def hook(key: str, expected: VersionToken) -> None:
        if h.count("delete_if_version") == 1:
            action(key, expected)

    h.before_delete = hook


def _raise_from_delete(h: RecordingStorage, nth: int, error: BaseException) -> None:
    def hook(key: str, expected: VersionToken) -> None:
        if h.count("delete_if_version") >= nth:
            raise error

    h.before_delete = hook


def _secrets(keys: Sequence[str]) -> list[str]:
    out = list(keys)
    for key in keys:
        suffix = key.split("/", 2)[2]
        out += [description_for(suffix), alias_for(suffix)]
    return out


def _cached_valid_env() -> tuple[RecordingStorage, MemoryStore, LoggingCache, str]:
    """MC over E_valid with user/u1's index cached; returns the token before purge."""
    h = RecordingStorage()
    seed_valid_entity(h.inner)
    store, cache = _mc(h)
    store.get_memory_index({"user": "u1"})
    token = cache.raw(token_key("user", "u1"))
    assert token is not None
    listing = cache.raw(listing_key("user", "u1"))
    assert listing is not None
    assert PREFIX + "notes/a.md" in listing
    return h, store, cache, token


# --- US1: purge ---------------------------------------------------------------


def test_purge_deletes_everything_under_prefix() -> None:
    """Purge returns 6 and leaves nothing under user/u1/ (AIE-1291, US1.1)."""
    h = RecordingStorage()
    seed_entity(h.inner)

    assert _m(h).purge("user", "u1") == 6
    assert list(h.inner.list_page(PREFIX, None, 100)) == []


def test_purge_leaves_no_visible_files() -> None:
    """After purge, list_prefix, get_memory_index, and read_file see nothing
    (AIE-1291, US1.2).
    """
    h = RecordingStorage()
    seed_entity(h.inner)
    store = _m(h)

    store.purge("user", "u1")

    page = store.list_prefix(PREFIX)
    assert page.entries == ()
    assert page.next_cursor is None
    assert store.get_memory_index({"user": "u1"}) == MemoryIndex()
    for suffix in (s for s in SEED_SUFFIXES if s != "odd-key"):
        with pytest.raises(NotFoundError) as excinfo:
            store.read_file(PREFIX + suffix)
        assert excinfo.value.reason is NotFoundReason.FILE_ABSENT


def test_purge_leaves_neighbours_unchanged() -> None:
    """Prefix-lookalike and other-scope neighbours keep their data, metadata,
    and version (AIE-1291, US1.3).
    """
    h = RecordingStorage()
    seed_entity(h.inner)
    seed_neighbours(h.inner)
    before = snapshot(h.inner, NEIGHBOURS)

    _m(h).purge("user", "u1")

    assert snapshot(h.inner, NEIGHBOURS) == before


def test_purge_of_empty_entity_returns_zero() -> None:
    """An entity with no objects purges to 0 with no delete call
    (AIE-1291, US1.4).
    """
    h = RecordingStorage()
    seed_neighbours(h.inner)

    assert _m(h).purge("user", "u1") == 0
    assert h.count("delete_if_version") == 0


def test_purge_twice_second_returns_zero() -> None:
    """A second purge returns 0 (AIE-1291, US1.5)."""
    h = RecordingStorage()
    seed_entity(h.inner)
    store = _m(h)

    store.purge("user", "u1")
    assert store.purge("user", "u1") == 0


_NON_STR_ARGS: dict[str, tuple[object, object]] = {
    "int_scope": (1, "u1"),
    "none_entity": ("user", None),
    "bytes_scope": (b"user", "u1"),
    "spoofed_scope": (_SpoofedStr(), "u1"),
    "spoofed_entity": ("user", _SpoofedStr()),
}

_INVALID_SEGMENTS: dict[str, tuple[str, str, str]] = {
    "empty_scope": ("", "u1", r"^invalid scope: ''$"),
    "slash_scope": ("a/b", "u1", r"^invalid scope: 'a/b'$"),
    "dotdot_scope": ("..", "u1", r"^invalid scope: '\.\.'$"),
    "empty_entity": ("user", "", r"^invalid entity_id: ''$"),
    "slash_entity": ("user", "a/b", r"^invalid entity_id: 'a/b'$"),
    "dotdot_entity": ("user", "..", r"^invalid entity_id: '\.\.'$"),
}


@pytest.mark.parametrize(
    ("scope", "entity_id"), list(_NON_STR_ARGS.values()), ids=list(_NON_STR_ARGS)
)
def test_purge_rejects_non_str(scope: object, entity_id: object) -> None:
    """A non-str scope or entity_id raises TypeError with no storage or cache
    call (AIE-1291, US1.6).
    """
    h = RecordingStorage()
    seed_entity(h.inner)
    store, _ = _mc(h)

    with pytest.raises(TypeError):
        store.purge(cast(Any, scope), cast(Any, entity_id))

    assert h.calls == []


@pytest.mark.parametrize(
    ("scope", "entity_id", "message"), list(_INVALID_SEGMENTS.values()), ids=list(_INVALID_SEGMENTS)
)
def test_purge_rejects_invalid_segments(scope: str, entity_id: str, message: str) -> None:
    """A scope or entity_id failing is_valid_segment raises ValueError naming
    it, with no storage or cache call (AIE-1291, US1.7).
    """
    h = RecordingStorage()
    seed_entity(h.inner)
    store, _ = _mc(h)

    with pytest.raises(ValueError, match=message):
        store.purge(scope, entity_id)

    assert h.calls == []


def test_purge_paginates_seven_objects() -> None:
    """Seven objects with page size 2 are all deleted; returns 7
    (AIE-1291, US1.8).
    """
    h = RecordingStorage()
    seed_many(h.inner, 7)

    assert _m(h).purge("user", "u1") == 7
    assert _listed(h) == []


def test_create_after_purge_gets_new_version() -> None:
    """Creating a former path after purge succeeds with a version unlike any
    pre-purge version (AIE-1291, US1.9).
    """
    h = RecordingStorage()
    before = seed_entity(h.inner)
    store = _m(h)
    store.purge("user", "u1")

    metadata = FileMetadata(
        description="recreated",
        aliases=(),
        sources=frozenset({"t"}),
        last_updated=datetime(2024, 5, 1, tzinfo=UTC),
    )
    written = store.write_file(
        PREFIX + "notes/a.md", "- [stated] new\n", metadata, None, source="t"
    )

    assert written.version not in set(before.values())


# --- US2: passes and concurrent writers -----------------------------------------


def test_write_before_cursor_is_deleted_on_next_pass() -> None:
    """A key written behind the pass's cursor during the first delete is
    removed on pass 2; returns 7 (AIE-1291, US2.1).
    """
    h = RecordingStorage()
    seed_entity(h.inner)

    def write(key: str, expected: VersionToken) -> None:
        h.inner.put(PREFIX + "aa/new.md", b"- [stated] new\n", valid_metadata("new"))

    _on_first_delete(h, write)

    assert _m(h).purge("user", "u1") == 7
    assert h.inner.get(PREFIX + "aa/new.md") is None
    assert _listed(h) == []


def test_changed_object_is_deleted_at_new_version_on_next_pass() -> None:
    """An object rewritten before its guarded delete is skipped, then deleted
    at its new version on pass 2; returns 6 (AIE-1291, US2.2).
    """
    h = RecordingStorage()
    seed_entity(h.inner)
    k = PREFIX + "notes/a.md"

    def rewrite(key: str, expected: VersionToken) -> None:
        assert key == k
        h.inner.put(k, b"- [stated] changed\n", valid_metadata("changed"))

    _on_first_delete(h, rewrite)

    assert _m(h).purge("user", "u1") == 6
    assert h.inner.get(k) is None
    assert _listed(h) == []


def test_object_deleted_by_another_writer_is_not_counted() -> None:
    """An object deleted by someone else before purge's delete is skipped
    without error; returns 5 (AIE-1291, US2.3).
    """
    h = RecordingStorage()
    seed_entity(h.inner)
    deleted: list[str] = []

    def delete_first(key: str, expected: VersionToken) -> None:
        h.inner.delete_if_version(key, expected)
        deleted.append(key)

    _on_first_delete(h, delete_first)

    assert _m(h).purge("user", "u1") == 5
    assert deleted
    assert h.inner.get(deleted[0]) is None
    assert _listed(h) == []


def test_relentless_writer_raises_purge_incomplete() -> None:
    """A writer adding a key on every listing makes purge raise
    PurgeIncompleteError after PURGE_MAX_PASSES passes plus the check
    (AIE-1291, US2.4).
    """
    h = RecordingStorage()
    seed_entity(h.inner)
    _fresh_writer(h)

    with pytest.raises(PurgeIncompleteError) as excinfo:
        _m(h).purge("user", "u1")

    assert _restarts(h) == PURGE_MAX_PASSES + 1
    assert excinfo.value.scope == "user"
    assert excinfo.value.entity_id == "u1"
    assert excinfo.value.passes == PURGE_MAX_PASSES


def test_max_passes_bounds_restarts_and_names_passed_value() -> None:
    """max_passes=2 makes 3 restarts and reports 2 passes in the error and
    its message (AIE-1291, US2.4b).
    """
    h = RecordingStorage()
    seed_entity(h.inner)
    _fresh_writer(h)

    with pytest.raises(PurgeIncompleteError) as excinfo:
        _m(h).purge("user", "u1", max_passes=2)

    assert excinfo.value.passes == 2
    assert _restarts(h) == 3
    assert "after 2 passes" in str(excinfo.value)


@pytest.mark.parametrize("bad", [0, -1], ids=["zero", "negative"])
def test_max_passes_not_positive_raises_value_error(bad: int) -> None:
    """max_passes below 1 raises ValueError with no storage or cache call
    (AIE-1291, US2.4c).
    """
    h = RecordingStorage()
    seed_entity(h.inner)
    store, _ = _mc(h)

    with pytest.raises(ValueError, match=r"^max_passes must be positive$"):
        store.purge("user", "u1", max_passes=bad)

    assert h.calls == []


@pytest.mark.parametrize("bad", [True, 1.0, "3"], ids=["bool", "float", "str"])
def test_max_passes_wrong_type_raises_type_error(bad: object) -> None:
    """A bool, float, or str max_passes raises TypeError with no storage or
    cache call (AIE-1291, US2.4c).
    """
    h = RecordingStorage()
    seed_entity(h.inner)
    store, _ = _mc(h)

    with pytest.raises(TypeError):
        store.purge("user", "u1", max_passes=cast(Any, bad))

    assert h.calls == []


def test_type_errors_precede_value_errors() -> None:
    """A bad max_passes type raises TypeError even with an invalid scope
    (AIE-1291, US2.4c).
    """
    h = RecordingStorage()
    store, _ = _mc(h)

    with pytest.raises(TypeError):
        store.purge("", "u1", max_passes=cast(Any, True))

    assert h.calls == []


def test_single_pass_succeeds_without_writer() -> None:
    """max_passes=1 with no writer deletes all 6: one pass, then an empty
    check (AIE-1291, US2.4d).
    """
    h = RecordingStorage()
    seed_entity(h.inner)

    assert _m(h).purge("user", "u1", max_passes=1) == 6
    assert _listed(h) == []


def test_single_pass_misses_write_behind_cursor() -> None:
    """With max_passes=1, a key written behind the cursor is found by the
    check and purge raises with passes == 1 (AIE-1291, US2.4e).
    """
    h = RecordingStorage()
    seed_entity(h.inner)

    def write(key: str, expected: VersionToken) -> None:
        h.inner.put(PREFIX + "aa/late.md", b"- [stated] late\n", valid_metadata("late"))

    _on_first_delete(h, write)

    with pytest.raises(PurgeIncompleteError) as excinfo:
        _m(h).purge("user", "u1", max_passes=1)

    assert excinfo.value.passes == 1
    assert h.inner.get(PREFIX + "aa/late.md") is not None


def test_purge_incomplete_message_omits_entity_id() -> None:
    """PurgeIncompleteError's message names the scope, never the entity ID
    (AIE-1291, US2.4f).
    """
    h = RecordingStorage()
    seed_entity(h.inner, "user", SECRET_ENTITY)
    _fresh_writer(h, f"user/{SECRET_ENTITY}/")

    with pytest.raises(PurgeIncompleteError) as excinfo:
        _m(h).purge("user", SECRET_ENTITY)

    assert "user" in str(excinfo.value)
    assert SECRET_ENTITY not in str(excinfo.value)


def test_purge_incomplete_message_singular_pass() -> None:
    """With passes == 1 the message says "after 1 pass", not "passes"
    (AIE-1291, US2.4e, code review).
    """
    message = str(PurgeIncompleteError("user", "u1", 1))

    assert "after 1 pass" in message
    assert "after 1 passes" not in message


_COPIERS: dict[str, Callable[[PurgeIncompleteError], object]] = {
    "pickle": lambda e: pickle.loads(pickle.dumps(e)),
    "copy": copy.copy,
}


@pytest.mark.parametrize("copier", list(_COPIERS.values()), ids=list(_COPIERS))
def test_purge_incomplete_error_survives_pickle_and_copy(
    copier: Callable[[PurgeIncompleteError], object],
) -> None:
    """PurgeIncompleteError round-trips through pickle and copy.copy with its
    type, fields, and message intact (AIE-1291, code review).
    """
    original = PurgeIncompleteError("user", "u1", 3)

    clone = copier(original)

    assert type(clone) is PurgeIncompleteError
    assert clone.scope == "user"
    assert clone.entity_id == "u1"
    assert clone.passes == 3
    assert str(clone) == str(original)


def test_purge_incomplete_still_invalidates_index() -> None:
    """A purge that raises PurgeIncompleteError still tombstones the cached
    listing and replaces the token (AIE-1291, US2.4g).
    """
    h, store, cache, token_before = _cached_valid_env()
    _fresh_writer(h)

    with pytest.raises(PurgeIncompleteError):
        store.purge("user", "u1")

    raw = cache.raw(listing_key("user", "u1"))
    assert raw is not None
    for secret in _secrets([PREFIX + s for s in VALID_SUFFIXES]):
        assert secret not in raw
    assert cache.raw(token_key("user", "u1")) != token_before


def test_backend_failure_mid_purge_invalidates_and_propagates() -> None:
    """A BackendUnavailableError from the 2nd delete propagates; the 1st
    delete stands and the token changes so the next index re-lists
    (AIE-1291, US2.5).
    """
    h, store, cache, token_before = _cached_valid_env()
    _raise_from_delete(h, 2, BackendUnavailableError(TransientReason.UNAVAILABLE))

    with pytest.raises(BackendUnavailableError):
        store.purge("user", "u1")

    first_deleted = cast(str, h.calls_to("delete_if_version")[0][0])
    assert h.inner.get(first_deleted) is None
    assert cache.raw(token_key("user", "u1")) != token_before

    h.before_delete = None
    restarts_before = _restarts(h)
    index = store.get_memory_index({"user": "u1"})
    assert _restarts(h) > restarts_before
    assert first_deleted not in [e.path for e in index.entries]


def test_keyboard_interrupt_mid_purge_invalidates() -> None:
    """A KeyboardInterrupt from the first delete propagates and the token
    still changes (AIE-1291, US2.6).
    """
    h, store, cache, token_before = _cached_valid_env()
    _raise_from_delete(h, 1, KeyboardInterrupt())

    with pytest.raises(KeyboardInterrupt):
        store.purge("user", "u1")

    assert cache.raw(token_key("user", "u1")) != token_before


# --- US3: index cache -----------------------------------------------------------


def test_purge_drops_entity_from_cached_index_only() -> None:
    """After purge, user/u1 contributes no index entries and project/u1's
    entries are unchanged (AIE-1291, US3.1).
    """
    h = RecordingStorage()
    seed_valid_entity(h.inner)
    h.inner.put("project/u1/notes/a.md", b"- [stated] p\n", valid_metadata("project file"))
    store, _ = _mc(h)
    scope_map = {"user": "u1", "project": "u1"}
    before = store.get_memory_index(scope_map)
    project_before = [e for e in before.entries if e.path.startswith("project/u1/")]
    assert project_before
    assert any(e.path.startswith(PREFIX) for e in before.entries)

    store.purge("user", "u1")
    after = store.get_memory_index(scope_map)

    assert not any(e.path.startswith(PREFIX) for e in after.entries)
    assert [e for e in after.entries if e.path.startswith("project/u1/")] == project_before


def test_purge_tombstones_cached_listing() -> None:
    """After purge the raw listing value holds none of the purged paths,
    descriptions, or aliases (AIE-1291, US3.2).
    """
    _, store, cache, _ = _cached_valid_env()

    store.purge("user", "u1")

    raw = cache.raw(listing_key("user", "u1"))
    assert raw is not None
    for secret in _secrets([PREFIX + s for s in VALID_SUFFIXES]):
        assert secret not in raw


def test_purge_invalidates_once_after_last_storage_call() -> None:
    """Purge sets the token key then the listing key, once each, after its
    last storage call (AIE-1291, US3.3).
    """
    h = RecordingStorage()
    seed_entity(h.inner)
    store, _ = _mc(h)

    store.purge("user", "u1")

    sets = [
        (i, cast(str, args[0])) for i, (name, args) in enumerate(h.calls) if name == "cache.set"
    ]
    assert [key for _, key in sets] == [token_key("user", "u1"), listing_key("user", "u1")]
    last_storage = max(i for i, (name, _) in enumerate(h.calls) if not name.startswith("cache."))
    assert all(i > last_storage for i, _ in sets)


def test_cache_failure_after_successful_purge_propagates() -> None:
    """With a raising cache set, all 6 objects are deleted and then the
    cache's exception propagates (AIE-1291, US3.4).
    """
    h = RecordingStorage()
    seed_entity(h.inner)
    cache = LoggingCache(h.calls)
    boom = _CacheBoom("cache down")
    cache.set_raises = boom
    store, _ = _mc(h, cache)

    with pytest.raises(_CacheBoom) as excinfo:
        store.purge("user", "u1")

    assert excinfo.value is boom
    assert _listed(h) == []
    assert h.count("delete_if_version") == 6


FailureSetup = Callable[[RecordingStorage], tuple[type[BaseException], BaseException | None]]


def _fail_with_backend(h: RecordingStorage) -> tuple[type[BaseException], BaseException | None]:
    error = BackendUnavailableError(TransientReason.UNAVAILABLE)
    _raise_from_delete(h, 1, error)
    return BackendUnavailableError, error


def _fail_incomplete(h: RecordingStorage) -> tuple[type[BaseException], BaseException | None]:
    _fresh_writer(h, f"user/{SECRET_ENTITY}/")
    return PurgeIncompleteError, None


def _fail_with_interrupt(h: RecordingStorage) -> tuple[type[BaseException], BaseException | None]:
    error = KeyboardInterrupt()
    _raise_from_delete(h, 1, error)
    return KeyboardInterrupt, error


_PURGE_FAILURES: dict[str, FailureSetup] = {
    "backend_unavailable": _fail_with_backend,
    "purge_incomplete": _fail_incomplete,
    "keyboard_interrupt": _fail_with_interrupt,
}


@pytest.mark.parametrize("fail", list(_PURGE_FAILURES.values()), ids=list(_PURGE_FAILURES))
def test_cache_failure_after_failed_purge_is_logged(
    caplog: pytest.LogCaptureFixture, fail: FailureSetup
) -> None:
    """When purge fails (backend error, incomplete, or interrupt) and
    invalidation also fails, the purge error wins and one WARNING names the
    scope and cache exception type, never the entity ID (AIE-1291, US3.5).
    """
    caplog.set_level(logging.DEBUG)
    h = RecordingStorage()
    seed_entity(h.inner, "user", SECRET_ENTITY)
    cache = LoggingCache(h.calls)
    cache.set_raises = _CacheBoom("cache down")
    store, _ = _mc(h, cache)
    expected_type, expected_error = fail(h)

    with pytest.raises(BaseException) as excinfo:
        store.purge("user", SECRET_ENTITY)

    assert type(excinfo.value) is expected_type
    if expected_error is not None:
        assert excinfo.value is expected_error
    warnings = [
        r for r in caplog.records if r.name == "wenchang.core" and r.levelno == logging.WARNING
    ]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "user" in message
    assert "_CacheBoom" in message
    for record in caplog.records:
        assert SECRET_ENTITY not in record.getMessage()
    assert SECRET_ENTITY not in caplog.text


def test_purge_without_cache() -> None:
    """Without a cache purge works as in US1 and index_cache is None
    (AIE-1291, US3.6).
    """
    h = RecordingStorage()
    seed_entity(h.inner)
    store = _m(h)

    assert store.index_cache is None
    assert store.purge("user", "u1") == 6
    assert _listed(h) == []
