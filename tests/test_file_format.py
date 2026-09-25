"""Tests for confidence labels, fact line parsing/formatting, and body parsing.

Covers AIE-1031.
"""

import dataclasses
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta, timezone

import pytest

from wenchang.file_format import (
    ALIASES_KEY,
    DESCRIPTION_KEY,
    LAST_UPDATED_KEY,
    SOURCES_KEY,
    BodyLine,
    ConfidenceLabel,
    Fact,
    FileMetadata,
    MetadataFormatError,
    format_fact,
    metadata_from_map,
    metadata_to_map,
    parse_body,
    parse_fact,
    serialize_body,
)

PARSE_NONE_LINES = [
    "- [Stated] a",
    "- [guessed] a",
    "[stated] a",
    "- [stated]a",
    "- [stated]",
    "- [stated] ",
    "- [stated]    ",
    "  - [stated] a",
    "* [stated] a",
    "# Heading",
    "",
]

PARSE_SOME_ROWS: tuple[tuple[str, ConfidenceLabel, str], ...] = (
    ("- [stated] a", ConfidenceLabel.STATED, "a"),
    ("- [stated]   a", ConfidenceLabel.STATED, "  a"),
    ("- [stated] [observed] a", ConfidenceLabel.STATED, "[observed] a"),
    ("- [stated] a\r", ConfidenceLabel.STATED, "a\r"),
)

ROUND_TRIP_TEXTS = (
    "activation means the second purchase",
    "café ✓ naïve 日本語",
    "  leading spaces",
    "[bracketed] text",
)


@pytest.mark.unit
def test_confidence_label_has_exactly_four_members() -> None:
    """ConfidenceLabel has exactly the four expected lowercase values (AIE-1031)."""
    assert {member.value for member in ConfidenceLabel} == {
        "stated",
        "observed",
        "inferred",
        "system",
    }
    assert len(ConfidenceLabel) == 4


@pytest.mark.unit
def test_parse_fact_activation_example() -> None:
    """A stated fact line parses to a Fact with matching label and text (AIE-1031, US1-1)."""
    fact = parse_fact("- [stated] activation means the second purchase")
    assert fact == Fact(ConfidenceLabel.STATED, "activation means the second purchase")


@pytest.mark.unit
@pytest.mark.parametrize("label", list(ConfidenceLabel), ids=lambda label: label.value)
def test_parse_fact_each_label_matches(label: ConfidenceLabel) -> None:
    """Each of the four labels parses to a fact with the matching label (AIE-1031, US1-2)."""
    fact = parse_fact(f"- [{label.value}] some text")
    assert fact == Fact(label, "some text")


@pytest.mark.unit
@pytest.mark.parametrize(("line", "label", "text"), PARSE_SOME_ROWS)
def test_parse_fact_matching_lines(line: str, label: ConfidenceLabel, text: str) -> None:
    """Each documented matching line parses to the expected Fact (AIE-1031)."""
    assert parse_fact(line) == Fact(label, text)


@pytest.mark.unit
@pytest.mark.parametrize("line", PARSE_NONE_LINES)
def test_parse_fact_non_matching_lines_return_none(line: str) -> None:
    """Lines with a bad label, missing marker, or no text return None (AIE-1031, US1-4)."""
    assert parse_fact(line) is None


@pytest.mark.unit
def test_parse_fact_never_raises_for_str_without_newline() -> None:
    """parse_fact never raises for a str without a newline, even if malformed (AIE-1031)."""
    for line in [*PARSE_NONE_LINES, "- [stated] valid"]:
        parse_fact(line)


@pytest.mark.unit
@pytest.mark.parametrize("label", list(ConfidenceLabel), ids=lambda label: label.value)
def test_format_fact(label: ConfidenceLabel) -> None:
    """format_fact renders '- [<label>] <text>' (AIE-1031, US1-5)."""
    fact = Fact(label, "some text")
    assert format_fact(fact) == f"- [{label.value}] some text"


@pytest.mark.unit
def test_fact_construction_rejects_newline_in_text() -> None:
    """Constructing a Fact with a newline in the text raises ValueError (AIE-1031, US1-6)."""
    with pytest.raises(ValueError):
        Fact(ConfidenceLabel.STATED, "line one\nline two")


@pytest.mark.unit
@pytest.mark.parametrize("text", ["", "   ", "\t"])
def test_fact_construction_rejects_empty_or_whitespace_only_text(text: str) -> None:
    """Constructing a Fact with empty or whitespace-only text raises ValueError
    (AIE-1031, US1-6).
    """
    with pytest.raises(ValueError):
        Fact(ConfidenceLabel.STATED, text)


@pytest.mark.unit
def test_fact_is_frozen() -> None:
    """Fact is a frozen dataclass; assigning an attribute raises (AIE-1031)."""
    fact = Fact(ConfidenceLabel.STATED, "some text")
    with pytest.raises(dataclasses.FrozenInstanceError):
        fact.text = "other text"  # type: ignore[misc]


@pytest.mark.unit
@pytest.mark.parametrize("label", list(ConfidenceLabel), ids=lambda label: label.value)
def test_round_trip_across_labels(label: ConfidenceLabel) -> None:
    """parse_fact(format_fact(f)) == f holds for each label (AIE-1031)."""
    fact = Fact(label, "some text")
    assert parse_fact(format_fact(fact)) == fact


@pytest.mark.unit
@pytest.mark.parametrize("text", ROUND_TRIP_TEXTS)
def test_round_trip_across_texts(text: str) -> None:
    """parse_fact(format_fact(f)) == f holds for unicode, leading-space, and
    bracketed text (AIE-1031).
    """
    fact = Fact(ConfidenceLabel.STATED, text)
    assert parse_fact(format_fact(fact)) == fact


BODY_ROUND_TRIP_TEXTS = (
    "",
    "\n",
    "a\n",
    "a",
    "a b",
    "- [stated] a",
    "- [stated] a\n- [observed] b",
    "# Heading\n\n- [stated] a\n\nSome prose line.\n",
    "café ✓ naïve 日本語\n- [stated] café",
    "a\r\nb",
    "line one\r\nline two\r\n",
    "a\n\n\nb",
    "- [Stated] x",
    "- [stated]x",
    "  - [stated] x",
    "- [stated] a\r\nb",
)


@pytest.mark.unit
def test_parse_body_mixed_content_returns_non_fact_lines_verbatim() -> None:
    """A heading, blank line, and prose among fact lines parse to str elements in
    their original positions, with text unchanged (AIE-1031, US1-3).
    """
    body = "# Heading\n\n- [stated] a\nSome prose line.\n- [observed] b"
    assert parse_body(body) == (
        "# Heading",
        "",
        Fact(ConfidenceLabel.STATED, "a"),
        "Some prose line.",
        Fact(ConfidenceLabel.OBSERVED, "b"),
    )


@pytest.mark.unit
@pytest.mark.parametrize("body", BODY_ROUND_TRIP_TEXTS)
def test_serialize_body_of_parse_body_round_trips(body: str) -> None:
    """serialize_body(parse_body(s)) == s for a broad corpus of body strings,
    including unicode, "\\r\\n" endings, consecutive blank lines, and near-miss
    fact syntax (AIE-1031, US2-1, US2-4).
    """
    assert serialize_body(parse_body(body)) == body


@pytest.mark.unit
def test_parse_body_preserves_trailing_newline_presence() -> None:
    """Trailing newline presence versus absence yields different, correctly
    round-tripping results (AIE-1031, US2-2).
    """
    assert parse_body("a\nb") == ("a", "b")
    assert parse_body("a\nb\n") == ("a", "b", "")
    assert serialize_body(parse_body("a\nb")) == "a\nb"
    assert serialize_body(parse_body("a\nb\n")) == "a\nb\n"


@pytest.mark.unit
def test_empty_body_round_trips_to_empty_string() -> None:
    """An empty body round-trips through parse_body/serialize_body to "" (AIE-1031, US2-3)."""
    assert parse_body("") == ("",)
    assert serialize_body(parse_body("")) == ""


@pytest.mark.unit
def test_serialize_body_of_caller_built_sequence_round_trips_to_same_tuple() -> None:
    """serialize_body then parse_body of a caller-built sequence of Facts and
    other strs returns the same tuple (AIE-1031, US2-5).
    """
    lines: tuple[BodyLine, ...] = (
        "# Heading",
        "",
        Fact(ConfidenceLabel.STATED, "a"),
        "prose",
        Fact(ConfidenceLabel.SYSTEM, "z"),
    )
    assert parse_body(serialize_body(lines)) == lines


@pytest.mark.unit
def test_serialize_body_rejects_str_element_containing_newline() -> None:
    """serialize_body raises ValueError when a str element contains "\\n" (AIE-1031, US2-6)."""
    with pytest.raises(ValueError):
        serialize_body(["a\nb"])


@pytest.mark.unit
def test_serialize_body_rejects_str_element_that_parses_as_fact() -> None:
    """serialize_body raises ValueError when a str element would itself parse as a
    fact line (AIE-1031, US2-6).
    """
    with pytest.raises(ValueError):
        serialize_body(["- [stated] x"])


@pytest.mark.unit
def test_serialize_body_rejects_empty_sequence() -> None:
    """serialize_body raises ValueError for an empty sequence of lines (AIE-1031, US2-6)."""
    with pytest.raises(ValueError):
        serialize_body([])


@pytest.mark.unit
def test_parse_body_of_empty_string_is_single_empty_element() -> None:
    """parse_body("") is the one-tuple ("",), not an empty tuple (AIE-1031)."""
    assert parse_body("") == ("",)


@pytest.mark.unit
def test_parse_body_of_lone_newline_is_two_empty_elements() -> None:
    """parse_body("\\n") is ("", "") (AIE-1031)."""
    assert parse_body("\n") == ("", "")


@pytest.mark.unit
def test_parse_body_keeps_carriage_return_on_the_line() -> None:
    """Splitting on "\\n" only means a "\\r" before it stays attached to the
    preceding line's text (AIE-1031).
    """
    assert parse_body("- [stated] a\r\nb") == (Fact(ConfidenceLabel.STATED, "a\r"), "b")


@pytest.mark.unit
def test_parse_body_never_uses_splitlines_semantics() -> None:
    """parse_body never splits on characters that str.splitlines treats as line
    boundaries but "\\n".split does not, e.g. a plain space (AIE-1031).
    """
    assert parse_body("a b") == ("a b",)


METADATA_ROWS: tuple[FileMetadata, ...] = (
    FileMetadata(
        description="",
        aliases=(),
        sources=frozenset(),
        last_updated=datetime(2020, 1, 1, tzinfo=UTC),
    ),
    FileMetadata(
        description="a plain description",
        aliases=("alpha", "beta"),
        sources=frozenset({"src-a", "src-b"}),
        last_updated=datetime(2026, 9, 25, 19, 21, 38, tzinfo=UTC),
    ),
    FileMetadata(
        description="café ✓ naïve 日本語",
        aliases=("a,b", 'quote " mark', "[bracket]", "café"),
        sources=frozenset({"a,b", 'quote " mark', "[bracket]", "café"}),
        last_updated=datetime(2026, 9, 25, 19, 21, 38, 123456, tzinfo=UTC),
    ),
)


@pytest.mark.unit
def test_metadata_to_map_has_exactly_the_four_keys() -> None:
    """metadata_to_map returns exactly the four documented keys, each a str
    (AIE-1031, US3-1).
    """
    values = metadata_to_map(METADATA_ROWS[1])
    assert set(values) == {DESCRIPTION_KEY, ALIASES_KEY, SOURCES_KEY, LAST_UPDATED_KEY}
    assert all(isinstance(value, str) for value in values.values())


@pytest.mark.unit
@pytest.mark.parametrize("metadata", METADATA_ROWS)
def test_metadata_round_trips_through_map(metadata: FileMetadata) -> None:
    """metadata_from_map(metadata_to_map(m)) == m for a variety of metadata
    (AIE-1031, US3-2).
    """
    assert metadata_from_map(metadata_to_map(metadata)) == metadata


@pytest.mark.unit
def test_aliases_and_sources_with_special_characters_round_trip_unchanged() -> None:
    """Aliases and sources containing commas, quotes, brackets, and unicode
    round-trip unchanged (AIE-1031, US3-3).
    """
    metadata = METADATA_ROWS[2]
    values = metadata_to_map(metadata)
    assert json.loads(values[ALIASES_KEY]) == list(metadata.aliases)
    assert json.loads(values[SOURCES_KEY]) == sorted(metadata.sources)
    assert metadata_from_map(values) == metadata


@pytest.mark.unit
def test_metadata_to_map_preserves_alias_order() -> None:
    """The order of aliases is preserved in the encoded map value (AIE-1031, US3-4)."""
    metadata = FileMetadata(
        description="",
        aliases=("zebra", "apple", "mango"),
        sources=frozenset(),
        last_updated=datetime(2026, 1, 1, tzinfo=UTC),
    )
    values = metadata_to_map(metadata)
    assert json.loads(values[ALIASES_KEY]) == ["zebra", "apple", "mango"]


@pytest.mark.unit
def test_metadata_to_map_sources_deduplicated_and_sorted() -> None:
    """Sources built from a frozenset with duplicate literal entries appear once
    and are encoded in sorted order (AIE-1031, US3-5).
    """
    metadata = FileMetadata(
        description="",
        aliases=(),
        sources=frozenset(["a", "a", "b"]),
        last_updated=datetime(2026, 1, 1, tzinfo=UTC),
    )
    values = metadata_to_map(metadata)
    assert json.loads(values[SOURCES_KEY]) == ["a", "b"]


@pytest.mark.unit
def test_last_updated_aware_round_trips_to_same_instant() -> None:
    """An aware last_updated round-trips to the same instant (AIE-1031, US3-6)."""
    metadata = FileMetadata(
        description="",
        aliases=(),
        sources=frozenset(),
        last_updated=datetime(2026, 9, 25, 19, 21, 38, tzinfo=UTC),
    )
    assert metadata_from_map(metadata_to_map(metadata)).last_updated == metadata.last_updated


@pytest.mark.unit
def test_last_updated_map_value_is_iso_utc_with_z_without_microseconds() -> None:
    """last-updated with zero microseconds encodes as an exact UTC ISO 8601 string
    with "Z" and no fractional part (AIE-1031, US3-6).
    """
    metadata = FileMetadata(
        description="",
        aliases=(),
        sources=frozenset(),
        last_updated=datetime(2026, 9, 25, 19, 21, 38, tzinfo=UTC),
    )
    values = metadata_to_map(metadata)
    assert values[LAST_UPDATED_KEY] == "2026-09-25T19:21:38Z"


@pytest.mark.unit
def test_last_updated_map_value_is_iso_utc_with_z_with_microseconds() -> None:
    """last-updated with non-zero microseconds encodes as an exact UTC ISO 8601
    string with "Z" and the fractional part (AIE-1031, US3-6).
    """
    metadata = FileMetadata(
        description="",
        aliases=(),
        sources=frozenset(),
        last_updated=datetime(2026, 9, 25, 19, 21, 38, 123456, tzinfo=UTC),
    )
    values = metadata_to_map(metadata)
    assert values[LAST_UPDATED_KEY] == "2026-09-25T19:21:38.123456Z"


@pytest.mark.unit
def test_last_updated_non_utc_offset_encodes_as_same_instant_in_utc() -> None:
    """A non-UTC aware last_updated encodes as the same instant expressed in UTC
    (AIE-1031, US3-6).
    """
    non_utc = timezone(timedelta(hours=5, minutes=30))
    metadata = FileMetadata(
        description="",
        aliases=(),
        sources=frozenset(),
        last_updated=datetime(2026, 9, 26, 0, 51, 38, tzinfo=non_utc),
    )
    values = metadata_to_map(metadata)
    assert values[LAST_UPDATED_KEY] == "2026-09-25T19:21:38Z"


@pytest.mark.unit
def test_naive_last_updated_raises_value_error_at_construction() -> None:
    """Constructing FileMetadata with a naive last_updated raises ValueError
    (AIE-1031, US3-7).
    """
    with pytest.raises(ValueError):
        FileMetadata(
            description="",
            aliases=(),
            sources=frozenset(),
            last_updated=datetime(2026, 1, 1),
        )


@pytest.mark.unit
@pytest.mark.parametrize("bad_char", ["\n", "\r"])
def test_description_with_newline_or_cr_raises_value_error_at_construction(
    bad_char: str,
) -> None:
    """Constructing FileMetadata with "\\n" or "\\r" in description raises
    ValueError (AIE-1031, US3-8).
    """
    with pytest.raises(ValueError):
        FileMetadata(
            description=f"bad{bad_char}text",
            aliases=(),
            sources=frozenset(),
            last_updated=datetime(2026, 1, 1, tzinfo=UTC),
        )


VALID_MAP: dict[str, str] = {
    DESCRIPTION_KEY: "a description",
    ALIASES_KEY: json.dumps(["a", "b"]),
    SOURCES_KEY: json.dumps(["x", "y"]),
    LAST_UPDATED_KEY: "2026-09-25T19:21:38Z",
}


@pytest.mark.unit
@pytest.mark.parametrize(
    "missing_key", [DESCRIPTION_KEY, ALIASES_KEY, SOURCES_KEY, LAST_UPDATED_KEY]
)
def test_metadata_from_map_missing_key_raises_with_key_named(missing_key: str) -> None:
    """A map missing any of the four keys raises MetadataFormatError naming that
    key (AIE-1031, US3-9).
    """
    values = {key: value for key, value in VALID_MAP.items() if key != missing_key}
    with pytest.raises(MetadataFormatError) as exc_info:
        metadata_from_map(values)
    assert exc_info.value.key == missing_key
    assert missing_key in str(exc_info.value)


@pytest.mark.unit
@pytest.mark.parametrize(
    "bad_aliases",
    ["not json", json.dumps({"a": 1}), json.dumps(["a", 2])],
)
def test_metadata_from_map_undecodable_aliases_raises_with_aliases_key(
    bad_aliases: str,
) -> None:
    """Aliases that aren't JSON, aren't a JSON list, or contain a non-string
    element raise MetadataFormatError with key "aliases" (AIE-1031, US3-9).
    """
    values = {**VALID_MAP, ALIASES_KEY: bad_aliases}
    with pytest.raises(MetadataFormatError) as exc_info:
        metadata_from_map(values)
    assert exc_info.value.key == ALIASES_KEY


@pytest.mark.unit
@pytest.mark.parametrize(
    "bad_sources",
    ["not json", json.dumps({"a": 1}), json.dumps(["a", 2])],
)
def test_metadata_from_map_undecodable_sources_raises_with_sources_key(
    bad_sources: str,
) -> None:
    """Sources that aren't JSON, aren't a JSON list, or contain a non-string
    element raise MetadataFormatError with key "sources" (AIE-1031, US3-9).
    """
    values = {**VALID_MAP, SOURCES_KEY: bad_sources}
    with pytest.raises(MetadataFormatError) as exc_info:
        metadata_from_map(values)
    assert exc_info.value.key == SOURCES_KEY


@pytest.mark.unit
def test_metadata_from_map_non_iso_last_updated_raises_with_last_updated_key() -> None:
    """A last-updated value that isn't ISO-parseable raises MetadataFormatError
    with key "last-updated" (AIE-1031, US3-9).
    """
    values = {**VALID_MAP, LAST_UPDATED_KEY: "not a timestamp"}
    with pytest.raises(MetadataFormatError) as exc_info:
        metadata_from_map(values)
    assert exc_info.value.key == LAST_UPDATED_KEY


@pytest.mark.unit
def test_metadata_from_map_naive_last_updated_raises_with_last_updated_key() -> None:
    """A last-updated value that is ISO but lacks a UTC offset raises
    MetadataFormatError with key "last-updated" (AIE-1031, US3-9).
    """
    values = {**VALID_MAP, LAST_UPDATED_KEY: "2026-09-25T19:21:38"}
    with pytest.raises(MetadataFormatError) as exc_info:
        metadata_from_map(values)
    assert exc_info.value.key == LAST_UPDATED_KEY


@pytest.mark.unit
def test_metadata_from_map_description_with_newline_raises_with_description_key() -> None:
    """A description value containing "\\n" raises MetadataFormatError with key
    "description" (AIE-1031, US3-9).
    """
    values = {**VALID_MAP, DESCRIPTION_KEY: "bad\ntext"}
    with pytest.raises(MetadataFormatError) as exc_info:
        metadata_from_map(values)
    assert exc_info.value.key == DESCRIPTION_KEY


@pytest.mark.unit
def test_metadata_from_map_ignores_extra_keys() -> None:
    """metadata_from_map ignores keys beyond the four documented ones
    (AIE-1031, US3-10).
    """
    values: Mapping[str, str] = {**VALID_MAP, "extra-key": "ignored"}
    metadata = metadata_from_map(values)
    assert metadata.description == "a description"


@pytest.mark.unit
def test_empty_aliases_and_sources_round_trip_empty() -> None:
    """Empty aliases and sources round-trip to empty on both sides (AIE-1031, US3-11)."""
    metadata = FileMetadata(
        description="",
        aliases=(),
        sources=frozenset(),
        last_updated=datetime(2026, 1, 1, tzinfo=UTC),
    )
    values = metadata_to_map(metadata)
    assert json.loads(values[ALIASES_KEY]) == []
    assert json.loads(values[SOURCES_KEY]) == []
    round_tripped = metadata_from_map(values)
    assert round_tripped.aliases == ()
    assert round_tripped.sources == frozenset()


@pytest.mark.unit
def test_empty_string_alias_and_source_round_trip_unchanged() -> None:
    """An empty-string alias and an empty-string source construct without error
    and round-trip unchanged (AIE-1031).
    """
    metadata = FileMetadata(
        description="",
        aliases=("", "x"),
        sources=frozenset({""}),
        last_updated=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert metadata_from_map(metadata_to_map(metadata)) == metadata


@pytest.mark.unit
def test_metadata_format_error_is_value_error_subclass() -> None:
    """MetadataFormatError is a subclass of ValueError (AIE-1031)."""
    assert issubclass(MetadataFormatError, ValueError)


@pytest.mark.unit
def test_file_metadata_is_frozen() -> None:
    """FileMetadata is a frozen dataclass; assigning an attribute raises
    (AIE-1031).
    """
    metadata = FileMetadata(
        description="",
        aliases=(),
        sources=frozenset(),
        last_updated=datetime(2026, 1, 1, tzinfo=UTC),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        metadata.description = "other"  # type: ignore[misc]
