"""Validation for memory file paths.

A well-formed path is exactly `{scope}/{entity_id}/{area}/{name}.md`: four
non-empty segments, none of them "." or "..", none containing a backslash or
a Unicode control character, with the final segment ending in ".md" and
longer than ".md".
"""

import unicodedata

_MD_SUFFIX = ".md"


def _is_valid_segment(segment: str) -> bool:
    if segment == "" or segment in (".", ".."):
        return False
    if "\\" in segment:
        return False
    return all(unicodedata.category(char) != "Cc" for char in segment)


def is_valid_path(path: str) -> bool:
    """Return True iff path is a well-formed `{scope}/{entity_id}/{area}/{name}.md` path.

    Never raises for any str input.
    """
    segments = path.split("/")
    if len(segments) != 4:
        return False
    if not all(_is_valid_segment(segment) for segment in segments):
        return False
    name = segments[-1]
    return name.endswith(_MD_SUFFIX) and len(name) > len(_MD_SUFFIX)
