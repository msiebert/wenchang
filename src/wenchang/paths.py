"""Validation, construction, and parsing of memory file paths and prefixes.

A well-formed path is exactly `{scope}/{entity_id}/{area}/{name}.md`: four
non-empty segments, none of them "." or "..", none containing a backslash or
a Unicode control character, with the final segment ending in ".md" and
longer than ".md".

A well-formed prefix is 1-3 valid segments, each followed by "/" (e.g.
`"scope/"` or `"scope/entity_id/"`).

`build_path` and `build_prefix` assemble paths and prefixes from their parts,
raising ValueError for any invalid part; `parse_path` splits a well-formed path
back into a `PathParts`. Paths are relative to the storage root.
"""

import unicodedata
from dataclasses import dataclass

_MD_SUFFIX = ".md"


def is_valid_segment(segment: str) -> bool:
    """Return True iff segment is one valid path segment.

    Non-empty, not "." or "..", and no "/", backslash, or Unicode control
    character. Never raises for any str input.
    """
    if segment == "" or segment in (".", ".."):
        return False
    if "/" in segment or "\\" in segment:
        return False
    return all(unicodedata.category(char) != "Cc" for char in segment)


def is_valid_path(path: str) -> bool:
    """Return True iff path is a well-formed `{scope}/{entity_id}/{area}/{name}.md` path.

    Never raises for any str input.
    """
    segments = path.split("/")
    if len(segments) != 4:
        return False
    if not all(is_valid_segment(segment) for segment in segments):
        return False
    name = segments[-1]
    return name.endswith(_MD_SUFFIX) and len(name) > len(_MD_SUFFIX)


def is_valid_prefix(prefix: str) -> bool:
    """Return True iff prefix is 1-3 valid segments, each followed by '/'.

    Never raises for any str input.
    """
    if not prefix.endswith("/"):
        return False
    segments = prefix[:-1].split("/")
    if not 1 <= len(segments) <= 3:
        return False
    return all(is_valid_segment(segment) for segment in segments)


@dataclass(frozen=True)
class PathParts:
    """The four components of a memory path; `name` excludes the final ".md"."""

    scope: str
    entity_id: str
    area: str
    name: str


def _check_segment(arg: str, value: str) -> None:
    if not is_valid_segment(value):
        raise ValueError(f"invalid {arg}: {value!r}")


def build_path(scope: str, entity_id: str, area: str, name: str) -> str:
    """Return `{scope}/{entity_id}/{area}/{name}.md`.

    Raises ValueError naming the first invalid argument.
    """
    _check_segment("scope", scope)
    _check_segment("entity_id", entity_id)
    _check_segment("area", area)
    if name == "" or not is_valid_segment(name + _MD_SUFFIX):
        raise ValueError(f"invalid name: {name!r}")
    return f"{scope}/{entity_id}/{area}/{name}{_MD_SUFFIX}"


def build_prefix(scope: str, entity_id: str | None = None, area: str | None = None) -> str:
    """Return the listing prefix `scope/`, `scope/entity_id/`, or `scope/entity_id/area/`.

    Raises ValueError for an invalid segment or an area without an entity_id.
    """
    if area is not None and entity_id is None:
        raise ValueError("area requires entity_id")
    segments: list[tuple[str, str]] = [
        ("scope", scope),
        *(
            (arg, value)
            for arg, value in (("entity_id", entity_id), ("area", area))
            if value is not None
        ),
    ]
    for arg, value in segments:
        _check_segment(arg, value)
    return "".join(value + "/" for _, value in segments)


def parse_path(path: str) -> PathParts:
    """Split a well-formed memory path into its parts.

    Raises ValueError if `not is_valid_path(path)`.
    """
    if not is_valid_path(path):
        raise ValueError(f"invalid path: {path!r}")
    scope, entity_id, area, last = path.split("/")
    return PathParts(scope, entity_id, area, last[: -len(_MD_SUFFIX)])
