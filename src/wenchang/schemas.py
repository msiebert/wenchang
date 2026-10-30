"""JSON Schemas for the memory tools' arguments, results, and errors.

tool_schemas(product) gives each tool's ToolSchema: its name, description,
and JSON Schemas (draft 2020-12) for its arguments, its render_result
payload, and the shared render_error payload. Input schemas are derived from
the MemoryTools method signatures; output schemas are chosen by each method's
return annotation from the rendered shapes declared here.

The schemas describe on-contract output. render_result drops a field whose
value has the wrong type, as an off-contract TransportClient can produce, yet
every field is marked required, since an on-contract client always produces
it. The error schema covers wenchang's own error classes: an adopter's
WenchangError subclass validates only if it reuses these attribute names,
types, and reason values.
"""

import inspect
import json
import types
import typing
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, cast

from wenchang.core import ListPage, MemoryFile, MemoryIndex
from wenchang.errors import ErrorCategory, NotFoundReason, RestrictionReason, TransientReason
from wenchang.tools import TOOL_NAMES, MemoryTools, tool_descriptions

__all__ = ["ToolSchema", "error_schema", "tool_schemas"]

_STRING: Final[dict[str, object]] = {"type": "string"}
_NULL: Final[dict[str, object]] = {"type": "null"}
_NULLABLE_STRING: Final[dict[str, object]] = {"anyOf": [_STRING, _NULL]}
_STRING_ARRAY: Final[dict[str, object]] = {"type": "array", "items": _STRING}
_TIMESTAMP: Final[dict[str, object]] = {"type": "string", "format": "date-time"}
_COUNT: Final[dict[str, object]] = {"type": "integer", "minimum": 0}

_ENTRY_FIELDS: Final[dict[str, object]] = {
    "scope": _NULLABLE_STRING,
    "area": _NULLABLE_STRING,
    "name": _NULLABLE_STRING,
    "version": _STRING,
    "description": _STRING,
    "aliases": _STRING_ARRAY,
    "sources": _STRING_ARRAY,
    "last_updated": _TIMESTAMP,
}

# A file as rendered in entries: every field but content.
_ENTRY: Final[dict[str, object]] = {
    "type": "object",
    "properties": _ENTRY_FIELDS,
    "required": list(_ENTRY_FIELDS),
    "additionalProperties": False,
}

_FILE_FIELDS: Final[dict[str, object]] = {
    "scope": _NULLABLE_STRING,
    "area": _NULLABLE_STRING,
    "name": _NULLABLE_STRING,
    "content": _STRING,
    "version": _STRING,
    "description": _STRING,
    "aliases": _STRING_ARRAY,
    "sources": _STRING_ARRAY,
    "last_updated": _TIMESTAMP,
}

_FILE: Final[dict[str, object]] = {
    "type": "object",
    "properties": _FILE_FIELDS,
    "required": list(_FILE_FIELDS),
    "additionalProperties": False,
}

_PAGE: Final[dict[str, object]] = {
    "type": "object",
    "properties": {
        "entries": {"type": "array", "items": _ENTRY},
        "next_cursor": _NULLABLE_STRING,
    },
    "required": ["entries", "next_cursor"],
    "additionalProperties": False,
}

_CAPPED_ROW: Final[dict[str, object]] = {
    "type": "object",
    "properties": {
        "scope": _STRING,
        "area": _NULLABLE_STRING,
        "omitted": {"type": "integer", "minimum": 1},
    },
    "required": ["scope", "area", "omitted"],
    "additionalProperties": False,
}

_INDEX: Final[dict[str, object]] = {
    "type": "object",
    "properties": {
        "entries": {"type": "array", "items": _ENTRY},
        "capped": {"type": "array", "items": _CAPPED_ROW},
    },
    "required": ["entries", "capped"],
    "additionalProperties": False,
}

_OK: Final[dict[str, object]] = {
    "type": "object",
    "properties": {"ok": {"const": True}},
    "required": ["ok"],
    "additionalProperties": False,
}

_ERROR: Final[dict[str, object]] = {
    "type": "object",
    "properties": {
        "error": _STRING,
        "category": {
            "type": "string",
            "enum": [c.value for c in ErrorCategory] + ["internal"],
        },
        "message": _STRING,
        "scope": _STRING,
        "area": _STRING,
        "name": _STRING,
        "content": _STRING,
        "version": _STRING,
        "size": _COUNT,
        "limit": _COUNT,
        "match_count": _COUNT,
        "reason": {
            "type": "string",
            "enum": [
                *(r.value for r in NotFoundReason),
                *(r.value for r in RestrictionReason),
                *(r.value for r in TransientReason),
            ],
        },
        "required_roles": _STRING_ARRAY,
        "argument": _STRING,
    },
    "required": ["error", "category", "message"],
    "additionalProperties": False,
}

# Each rendered shape by the tool method's return annotation.
_OUTPUTS: Final[Mapping[object, dict[str, object]]] = MappingProxyType(
    {
        MemoryIndex: _INDEX,
        MemoryFile: _FILE,
        ListPage: _PAGE,
        type(None): _OK,
    }
)

_DEFAULT_TYPES: Final[tuple[type, ...]] = (type(None), bool, int, float, str)


@dataclass(frozen=True)
class ToolSchema:
    """One memory tool's definition for a host: name, description, and JSON Schemas.

    input describes the tool's arguments; output, the render_result payload on
    success; error, the render_error payload on failure. All are JSON Schema
    draft 2020-12, closed, and describe on-contract output (see module docstring).
    Instances compare by value and are unhashable.
    """

    name: str
    description: str
    input: dict[str, object]
    output: dict[str, object]
    error: dict[str, object]


def tool_schemas(product: str | None = None) -> Mapping[str, ToolSchema]:
    """Each tool's ToolSchema by name, in TOOL_NAMES order.

    description is tool_descriptions(product)[name]. Every call builds fresh dicts.
    """
    descriptions = tool_descriptions(product)
    out: dict[str, ToolSchema] = {}
    for name in TOOL_NAMES:
        method = cast(Callable[..., object], getattr(MemoryTools, name))
        out[name] = ToolSchema(
            name=name,
            description=descriptions[name],
            input=_input_schema(name, method),
            output=_output_schema(name, method),
            error=error_schema(),
        )
    return MappingProxyType(out)


def error_schema() -> dict[str, object]:
    """The JSON Schema of every render_error payload; a fresh dict per call."""
    return _fresh(_ERROR)


def _fresh(schema: dict[str, object]) -> dict[str, object]:
    # A JSON round trip, unlike deepcopy, shares no nested object between two places.
    return cast(dict[str, object], json.loads(json.dumps(schema)))


def _hints(method: Callable[..., object]) -> dict[str, object]:
    # The unwrapped function, so a decorator's own annotations never stand in.
    return typing.get_type_hints(inspect.unwrap(method))


def _input_schema(tool: str, method: Callable[..., object]) -> dict[str, object]:
    hints = _hints(method)
    parameters = list(inspect.signature(method).parameters.values())[1:]
    properties: dict[str, object] = {}
    required: list[str] = []
    for param in parameters:
        if param.kind is not inspect.Parameter.POSITIONAL_OR_KEYWORD:
            raise TypeError(f"no JSON Schema for {tool}.{param.name}: {param.kind.description}")
        annotation = hints.get(param.name, param.annotation)
        schema = _type_schema(tool, param.name, annotation)
        if param.default is inspect.Parameter.empty:
            required.append(param.name)
        else:
            default = cast(object, param.default)
            if type(default) not in _DEFAULT_TYPES:
                raise TypeError(f"no JSON Schema for {tool}.{param.name} default: {default!r}")
            schema["default"] = default
        properties[param.name] = schema
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _type_schema(tool: str, param: str, annotation: object) -> dict[str, object]:
    """The JSON Schema for one parameter annotation; TypeError if it is unmapped."""
    if _is_str(annotation):
        return _fresh(_STRING)
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin is Sequence and len(args) == 1 and _is_str(args[0]):
        return _fresh(_STRING_ARRAY)
    if origin in (typing.Union, types.UnionType) and len(args) == 2 and type(None) in args:
        inner = args[1] if args[0] is type(None) else args[0]
        if inner is not type(None):
            return {"anyOf": [_type_schema(tool, param, inner), _fresh(_NULL)]}
    raise TypeError(f"no JSON Schema for {tool}.{param}: {annotation!r}")


def _is_str(annotation: object) -> bool:
    """True for str and for any NewType whose supertype is str."""
    if annotation is str:
        return True
    return isinstance(annotation, typing.NewType) and annotation.__supertype__ is str


def _output_schema(tool: str, method: Callable[..., object]) -> dict[str, object]:
    annotation = _hints(method).get("return", inspect.Parameter.empty)
    for kind, schema in _OUTPUTS.items():
        if annotation is kind:
            return _fresh(schema)
    raise TypeError(f"no JSON Schema for {tool} result: {annotation!r}")
