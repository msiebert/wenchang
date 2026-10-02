"""Tests for index_entry_bytes and the index constants in wenchang.core (AIE-1046)."""

from datetime import UTC, datetime

import pytest

from wenchang.core import (
    DEFAULT_INDEX_MAX_BYTES,
    INDEX_SYSTEM_AREA,
    FileEntry,
    index_entry_bytes,
)
from wenchang.file_format import (
    FileMetadata,
    MetadataFormatError,
    metadata_from_map,
    metadata_to_map,
)
from wenchang.scope import SYSTEM_AREA
from wenchang.version_token import VersionToken

pytestmark = pytest.mark.unit

_PATH = "user/u-1/notes/a.md"
_LAST_UPDATED = datetime(2024, 1, 1, tzinfo=UTC)


def _entry(
    *,
    path: str = _PATH,
    description: str = "d",
    aliases: tuple[str, ...] = (),
    sources: frozenset[str] = frozenset({"t"}),
    version: str = "7",
) -> FileEntry:
    return FileEntry(
        path=path,
        metadata=FileMetadata(
            description=description,
            aliases=aliases,
            sources=sources,
            last_updated=_LAST_UPDATED,
        ),
        version=VersionToken(version),
    )


def test_reference_entry_costs_85_bytes() -> None:
    """AIE-1046, US3.1: path + metadata keys/values + version sum to 85."""
    assert index_entry_bytes(_entry()) == 19 + (11 + 1) + (7 + 2) + (7 + 5) + (12 + 20) + 1
    assert index_entry_bytes(_entry()) == 85


def test_non_ascii_alias_counts_its_json_escape() -> None:
    """AIE-1046, US3.1: alias "é" renders as '["\\u00e9"]' (10 bytes), total 93."""
    assert metadata_to_map(_entry(aliases=("é",)).metadata)["aliases"] == '["\\u00e9"]'
    assert index_entry_bytes(_entry(aliases=("é",))) == 93


def test_non_ascii_description_counts_utf8_bytes() -> None:
    """AIE-1046, US3.1: description "é" costs 2 bytes, total 86."""
    assert index_entry_bytes(_entry(description="é")) == 86


def test_version_length_counts() -> None:
    """AIE-1046, US3.1: a longer version token adds exactly its extra length."""
    long_version = "1234567890123456"
    assert index_entry_bytes(_entry(version=long_version)) == 85 - 1 + len(long_version)


def test_default_index_max_bytes_is_64_kib() -> None:
    """AIE-1046, US3.1: the default index cap is 64 KiB."""
    assert DEFAULT_INDEX_MAX_BYTES == 65536


def test_unrenderable_last_updated_raises_metadata_format_error() -> None:
    """AIE-1046, US1.10: a last-updated that overflows UTC raises MetadataFormatError."""
    metadata = metadata_from_map(
        {
            "description": "d",
            "aliases": "[]",
            "sources": '["t"]',
            "last-updated": "0001-01-01T00:00:00+05:00",
        }
    )
    entry = FileEntry(path=_PATH, metadata=metadata, version=VersionToken("7"))

    with pytest.raises(MetadataFormatError) as excinfo:
        index_entry_bytes(entry)

    assert excinfo.value.key == "last-updated"


def test_lone_surrogate_in_path_counts_three_bytes() -> None:
    """AIE-1046, US1.11: a lone surrogate in the path adds 3 bytes and raises nothing."""
    base = index_entry_bytes(_entry(path="user/u-1/notes/.md"))
    assert index_entry_bytes(_entry(path="user/u-1/notes/\ud800.md")) == base + 3


def test_lone_surrogate_in_description_counts_three_bytes() -> None:
    """AIE-1046, US1.11: a lone surrogate in the description adds 3 bytes."""
    assert index_entry_bytes(_entry(description="d\ud800")) == 85 + 3


def test_lone_surrogate_in_alias_counts_its_json_escape() -> None:
    """AIE-1046, US1.11: a lone surrogate in an alias counts its 6-byte JSON escape."""
    assert metadata_to_map(_entry(aliases=("\ud800",)).metadata)["aliases"] == '["\\ud800"]'
    assert index_entry_bytes(_entry(aliases=("\ud800",))) == index_entry_bytes(
        _entry(aliases=("a",))
    ) + (6 - 1)
    assert index_entry_bytes(_entry(aliases=("\ud800",))) == 93


def test_lone_surrogate_in_source_counts_its_json_escape() -> None:
    """AIE-1046, US1.11: a lone surrogate in a source counts its 6-byte JSON escape."""
    assert index_entry_bytes(_entry(sources=frozenset({"\ud800"}))) == 85 + (6 - 1)


def test_index_system_area_matches_scope() -> None:
    """AIE-1046, US6.2: core's system area name equals scope.SYSTEM_AREA."""
    assert INDEX_SYSTEM_AREA == SYSTEM_AREA
