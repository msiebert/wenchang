"""Validation for memory file paths and prefixes.

A well-formed path is exactly `{scope}/{entity_id}/{area}/{name}.md`: four
non-empty segments, none of them "." or "..", none containing a backslash or
a Unicode control character, with the final segment ending in ".md" and
longer than ".md".

A well-formed prefix is 1-3 valid segments, each followed by "/" (e.g.
`"scope/"` or `"scope/entity_id/"`).
"""

import unicodedata

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
