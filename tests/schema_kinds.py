"""Shared helper that summarizes a JSON-schema property's type as a short string.

Import with a bare `from schema_kinds import schema_kind`, like
`storage_conformance`: `tests/` has no `__init__.py`.
"""

from collections.abc import Mapping
from typing import Any, cast


def schema_kind(prop: Mapping[str, Any]) -> str:
    """Render a JSON-schema property as e.g. "string", "string|null", "array[string]"."""
    options = cast(list[Mapping[str, Any]], prop.get("anyOf", [prop]))
    kinds: list[str] = []
    for option in options:
        kind = cast(str, option["type"])
        if kind == "array":
            kind = f"array[{option['items']['type']}]"
        kinds.append(kind)
    return "|".join(kinds)
