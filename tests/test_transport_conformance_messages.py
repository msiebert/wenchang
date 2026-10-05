"""Drift test: the suite's pinned argument-error messages equal core's.

Covers AIE-1045, US5.6, US6.5, US9.4, US10.3, US10.5, US11 (FR-004): every
(method, cause) pair for write_file, replace_fact, append_line, list_prefix, and
get_memory_index is provoked on a real MemoryStore and
str(exc) must equal the module constant exactly. AIE-1151, US6.8 adds the
description-newline message for append_line and replace_fact.
"""

from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from wenchang.core import ListCursor, MemoryFile, MemoryStore
from wenchang.file_format import FileMetadata
from wenchang.storage.memory import InMemoryStorage
from wenchang.testing.transport_conformance import (
    MSG_APPEND_ARGS,
    MSG_DESCRIPTION_NEWLINE,
    MSG_FOREIGN_CURSOR,
    MSG_INVALID_ENTITY,
    MSG_INVALID_SCOPE,
    MSG_MALFORMED_CURSOR,
    MSG_REPLACE_ARGS,
    MSG_WRITE_ARGS,
)

pytestmark = pytest.mark.unit

PATH = "org/o-9/notes/conformance-probe.md"
CONTENT = "- [stated] alpha\n"
SOURCE = "conformance"


def _store_with_file() -> tuple[MemoryStore, MemoryFile]:
    store = MemoryStore(InMemoryStorage())
    metadata = FileMetadata("d", ("x",), frozenset(), datetime(2024, 1, 1, tzinfo=UTC))
    written = store.write_file(PATH, CONTENT, metadata, None, source=SOURCE)
    return store, written


def _message(call: Callable[[MemoryStore, MemoryFile], object]) -> str:
    store, written = _store_with_file()
    with pytest.raises(ValueError) as exc_info:
        call(store, written)
    return str(exc_info.value)


def test_replace_fact_empty_old_string_message_matches() -> None:
    """replace_fact with empty old_string raises exactly MSG_REPLACE_ARGS (AIE-1045, US5.6)."""
    message = _message(lambda s, w: s.replace_fact(PATH, "", "beta", w.version, source=SOURCE))

    assert message == MSG_REPLACE_ARGS


def test_replace_fact_empty_source_message_matches() -> None:
    """replace_fact with empty source raises exactly MSG_REPLACE_ARGS (AIE-1045, US10.3)."""
    message = _message(lambda s, w: s.replace_fact(PATH, "alpha", "beta", w.version, source=""))

    assert message == MSG_REPLACE_ARGS


def test_append_line_empty_source_message_matches() -> None:
    """append_line with empty source raises exactly MSG_APPEND_ARGS (AIE-1045, US10.3)."""
    message = _message(lambda s, w: s.append_line(PATH, "- [stated] beta", w.version, source=""))

    assert message == MSG_APPEND_ARGS


def test_append_line_non_fact_line_message_matches() -> None:
    """append_line with a non-fact line raises exactly MSG_APPEND_ARGS (AIE-1045, US6.5)."""
    message = _message(lambda s, w: s.append_line(PATH, "not a fact", w.version, source=SOURCE))

    assert message == MSG_APPEND_ARGS


def test_append_line_two_line_line_message_matches() -> None:
    """append_line with a two-line line raises exactly MSG_APPEND_ARGS (AIE-1045, US6.5)."""
    message = _message(
        lambda s, w: s.append_line(PATH, "- [stated] a\n- [stated] b", w.version, source=SOURCE)
    )

    assert message == MSG_APPEND_ARGS


NOTES_PREFIX = "user/u-1/notes/"
INDEX_PREFIX = "user/u-1/conformance-index/"


def test_list_prefix_malformed_cursor_message_matches() -> None:
    """list_prefix with a malformed cursor raises exactly MSG_MALFORMED_CURSOR (AIE-1045, US9.4)."""
    store = MemoryStore(InMemoryStorage())
    cursor = ListCursor("!!!")

    with pytest.raises(ValueError) as exc_info:
        store.list_prefix(NOTES_PREFIX, cursor)

    assert str(exc_info.value) == MSG_MALFORMED_CURSOR.format(cursor=cursor)


def test_list_prefix_foreign_cursor_message_matches() -> None:
    """A cursor issued for another prefix raises exactly MSG_FOREIGN_CURSOR (AIE-1045, US9.4)."""
    store = MemoryStore(InMemoryStorage(), list_page_size=1)
    metadata = FileMetadata("d", ("x",), frozenset(), datetime(2024, 1, 1, tzinfo=UTC))
    for stem in ("a", "b"):
        store.write_file(f"{NOTES_PREFIX}{stem}.md", CONTENT, metadata, None, source=SOURCE)
    cursor = store.list_prefix(NOTES_PREFIX).next_cursor
    assert cursor is not None

    with pytest.raises(ValueError) as exc_info:
        store.list_prefix(INDEX_PREFIX, cursor)

    assert str(exc_info.value) == MSG_FOREIGN_CURSOR.format(cursor=cursor, prefix=INDEX_PREFIX)


def test_write_file_empty_source_message_matches() -> None:
    """write_file with empty source raises exactly MSG_WRITE_ARGS (AIE-1045, US10.3)."""
    store = MemoryStore(InMemoryStorage())
    metadata = FileMetadata("d", ("x",), frozenset(), datetime(2024, 1, 1, tzinfo=UTC))

    with pytest.raises(ValueError) as exc_info:
        store.write_file(PATH, CONTENT, metadata, None, source="")

    assert str(exc_info.value) == MSG_WRITE_ARGS


def test_get_memory_index_invalid_scope_message_matches() -> None:
    """An invalid scope raises exactly MSG_INVALID_SCOPE, formatted (AIE-1045, US10.5)."""
    store = MemoryStore(InMemoryStorage())

    with pytest.raises(ValueError) as exc_info:
        store.get_memory_index({"a/": "x"})

    assert str(exc_info.value) == MSG_INVALID_SCOPE.format(scope="a/")


def test_get_memory_index_invalid_entity_message_matches() -> None:
    """An invalid entity_id raises exactly MSG_INVALID_ENTITY, formatted (AIE-1045, US10.5)."""
    store = MemoryStore(InMemoryStorage())

    with pytest.raises(ValueError) as exc_info:
        store.get_memory_index({"a": "x/"})

    assert str(exc_info.value) == MSG_INVALID_ENTITY.format(entity_id="x/")


def test_append_line_description_newline_message_matches() -> None:
    """append_line with a multi-line description raises exactly MSG_DESCRIPTION_NEWLINE.

    (AIE-1151, US6.8)
    """
    message = _message(
        lambda s, w: s.append_line(
            PATH, "- [stated] beta", w.version, source=SOURCE, description="a\nb"
        )
    )

    assert message == MSG_DESCRIPTION_NEWLINE


def test_replace_fact_description_newline_message_matches() -> None:
    """replace_fact with a multi-line description raises exactly MSG_DESCRIPTION_NEWLINE.

    (AIE-1151, US6.8)
    """
    message = _message(
        lambda s, w: s.replace_fact(
            PATH, "alpha", "beta", w.version, source=SOURCE, description="a\nb"
        )
    )

    assert message == MSG_DESCRIPTION_NEWLINE
