"""File format for fact lines: confidence-labeled lines within a memory file.

A fact line is a single line of the form `- [<label>] <text>`. The intended
body format is fact lines only; non-fact lines are tolerated as input and
preserved verbatim so a body round-trips losslessly through parse and
serialize even when it contains lines outside the supported format.

File metadata (description, aliases, sources, last-updated) is stored beside
the body as a flat string map, i.e. object custom metadata attached to the
stored file, not inside the markdown body itself.
"""

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

_FACT_LINE_PATTERN = re.compile(r"- \[(stated|observed|inferred|system)\] (.*)")


class ConfidenceLabel(StrEnum):
    """How a fact was established."""

    STATED = "stated"
    OBSERVED = "observed"
    INFERRED = "inferred"
    SYSTEM = "system"


@dataclass(frozen=True)
class Fact:
    """A single confidence-labeled fact line."""

    label: ConfidenceLabel
    text: str

    def __post_init__(self) -> None:
        if "\n" in self.text:
            raise ValueError("Fact text must not contain a newline")
        if self.text.strip() == "":
            raise ValueError("Fact text must not be empty or whitespace-only")


def format_fact(fact: Fact) -> str:
    """Render a Fact as a fact line."""
    return f"- [{fact.label}] {fact.text}"


def parse_fact(line: str) -> Fact | None:
    """Parse a fact line, or return None if the line is not a fact line."""
    match = _FACT_LINE_PATTERN.fullmatch(line)
    if match is None:
        return None
    text = match.group(2)
    if text.strip() == "":
        return None
    return Fact(ConfidenceLabel(match.group(1)), text)


type BodyLine = Fact | str
"""A body line: a Fact, or a str for a non-fact line kept verbatim."""


def parse_body(body: str) -> tuple[BodyLine, ...]:
    """Split a body into lines and parse each as a Fact where possible.

    Splits on "\\n" only, never on other characters str.splitlines treats as
    line boundaries, so the result always has at least one element and
    round-trips through serialize_body.
    """
    return tuple(parse_fact(piece) or piece for piece in body.split("\n"))


def serialize_body(lines: Sequence[BodyLine]) -> str:
    """Render body lines back into a body string, the inverse of parse_body.

    Raises ValueError if lines is empty, if any str element contains "\\n",
    or if any str element would itself parse as a fact line, since none of
    those can have come from parse_body.
    """
    if len(lines) == 0:
        raise ValueError("lines must not be empty")
    rendered: list[str] = []
    for line in lines:
        if isinstance(line, Fact):
            rendered.append(format_fact(line))
            continue
        if "\n" in line:
            raise ValueError("str element must not contain a newline")
        if parse_fact(line) is not None:
            raise ValueError("str element must not itself parse as a fact line")
        rendered.append(line)
    return "\n".join(rendered)


DESCRIPTION_KEY = "description"
ALIASES_KEY = "aliases"
SOURCES_KEY = "sources"
LAST_UPDATED_KEY = "last-updated"


@dataclass(frozen=True)
class FileMetadata:
    """Metadata describing a memory file, stored beside its body."""

    description: str
    aliases: tuple[str, ...]
    sources: frozenset[str]
    last_updated: datetime

    def __post_init__(self) -> None:
        if "\n" in self.description or "\r" in self.description:
            raise ValueError("description must not contain a newline or carriage return")
        if self.last_updated.tzinfo is None or self.last_updated.utcoffset() is None:
            raise ValueError("last_updated must be timezone-aware")


class MetadataFormatError(ValueError):
    """Raised when a metadata map entry is missing or malformed."""

    def __init__(self, key: str, detail: str) -> None:
        super().__init__(f"{key}: {detail}")
        self.key = key


def metadata_to_map(metadata: FileMetadata) -> dict[str, str]:
    """Render FileMetadata as a flat string map for storage as file metadata."""
    last_updated_utc = metadata.last_updated.astimezone(UTC)
    timestamp = last_updated_utc.isoformat().replace("+00:00", "Z")
    return {
        DESCRIPTION_KEY: metadata.description,
        ALIASES_KEY: json.dumps(list(metadata.aliases)),
        SOURCES_KEY: json.dumps(sorted(metadata.sources)),
        LAST_UPDATED_KEY: timestamp,
    }


def _parse_string_list(values: Mapping[str, str], key: str) -> list[str]:
    raw = values[key]
    try:
        decoded: object = json.loads(raw)
    except json.JSONDecodeError as error:
        raise MetadataFormatError(key, f"not valid JSON: {error}") from error
    if not isinstance(decoded, list):
        raise MetadataFormatError(key, "must be a JSON array")
    items: list[str] = []
    for item in decoded:  # pyright: ignore[reportUnknownVariableType]
        if not isinstance(item, str):
            raise MetadataFormatError(key, "all array items must be strings")
        items.append(item)
    return items


def metadata_from_map(values: Mapping[str, str]) -> FileMetadata:
    """Parse a flat string map back into FileMetadata.

    Ignores keys beyond the four documented ones. Raises MetadataFormatError,
    naming the offending key, for a missing key or a malformed value.
    """
    for key in (DESCRIPTION_KEY, ALIASES_KEY, SOURCES_KEY, LAST_UPDATED_KEY):
        if key not in values:
            raise MetadataFormatError(key, "missing required key")

    aliases = tuple(_parse_string_list(values, ALIASES_KEY))
    sources = frozenset(_parse_string_list(values, SOURCES_KEY))

    last_updated_raw = values[LAST_UPDATED_KEY]
    try:
        last_updated = datetime.fromisoformat(last_updated_raw)
    except ValueError as error:
        raise MetadataFormatError(
            LAST_UPDATED_KEY, f"not a valid ISO 8601 timestamp: {error}"
        ) from error
    if last_updated.tzinfo is None or last_updated.utcoffset() is None:
        raise MetadataFormatError(LAST_UPDATED_KEY, "must include a UTC offset")

    try:
        return FileMetadata(
            description=values[DESCRIPTION_KEY],
            aliases=aliases,
            sources=sources,
            last_updated=last_updated,
        )
    except ValueError as error:
        raise MetadataFormatError(DESCRIPTION_KEY, str(error)) from error
