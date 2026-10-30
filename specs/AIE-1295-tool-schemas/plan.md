# Implementation Plan: Export tool input/output schemas

**Linear**: AIE-1295 · **Spec**: `specs/AIE-1295-tool-schemas/spec.md` · **ADR**: 0042

## Summary

New module `src/wenchang/schemas.py` exports JSON Schema (draft 2020-12) for each memory tool's arguments, its successful `render_result` payload, and the shared `render_error` payload. Input schemas are derived from the `MemoryTools` method signatures; output schemas are chosen by each method's return annotation from shapes declared once in the module. No runtime dependency; `render_*`, tool signatures, and `wenchang.mcp` are unchanged.

## Public interface

```python
# src/wenchang/schemas.py
__all__ = ["ToolSchema", "error_schema", "tool_schemas"]


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


def error_schema() -> dict[str, object]:
    """The JSON Schema of every render_error payload; a fresh dict per call."""
```

- `tool_schemas` returns a `MappingProxyType` over a fresh `dict` (as `tool_descriptions` does). `product` is validated by `tool_descriptions` (same exceptions/messages).
- `ToolSchema.error == error_schema()` for every tool.
- Nothing is added to `wenchang/__init__.py`.

## Derivation

### Input (from `inspect.signature(getattr(MemoryTools, name))`, skipping `self`; annotations resolved with `typing.get_type_hints`)

Type map (closed; anything else raises `TypeError(f"no JSON Schema for {name}.{param}: {annotation!r}")` — message text not pinned by tests):

| Annotation | Schema |
| --- | --- |
| `str`, `VersionToken`, `ListCursor` (any `NewType` whose `__supertype__` is `str`) | `{"type": "string"}` |
| `Sequence[str]` (`collections.abc.Sequence`) | `{"type": "array", "items": {"type": "string"}}` |
| `T | None` where `T` is mapped (matched by `typing.get_origin(ann) in (typing.Union, types.UnionType)` with exactly two args, one being `type(None)`) | `{"anyOf": [<T schema>, {"type": "null"}]}` |

A parameter with a default adds `"default": <value>`; the value must be `None`, `bool`, `int`, `float`, or `str`, else `TypeError`. Parameters must be positional-or-keyword (else `TypeError`).

Tool input schema:

```json
{"type": "object", "properties": {<param>: <schema>, ...}, "required": [<params without default, signature order>], "additionalProperties": false}
```

`properties` insertion order is signature order.

### Output (from the method's return annotation)

| Return annotation | Output schema |
| --- | --- |
| `MemoryIndex` | INDEX |
| `MemoryFile` | FILE |
| `ListPage` | PAGE |
| `type(None)` (what `get_type_hints` yields for `-> None`) | OK |

Anything else raises `TypeError`. `"format": "date-time"` on `last_updated` is documentation only; tests validate without format checking and assert the timestamp pattern directly.

## Exact schemas

Shorthands: `S = {"type": "string"}`, `S? = {"anyOf": [{"type": "string"}, {"type": "null"}]}`, `ARR = {"type": "array", "items": {"type": "string"}}`, `TS = {"type": "string", "format": "date-time"}`.

ENTRY (a file without content, in `entries`):

```json
{"type": "object",
 "properties": {"scope": S?, "area": S?, "name": S?, "version": S, "description": S,
                "aliases": ARR, "sources": ARR, "last_updated": TS},
 "required": ["scope", "area", "name", "version", "description", "aliases", "sources", "last_updated"],
 "additionalProperties": false}
```

FILE: ENTRY with `"content": S` added to `properties` after `name`, and `"content"` added to `required` after `"name"`.

PAGE:

```json
{"type": "object",
 "properties": {"entries": {"type": "array", "items": ENTRY}, "next_cursor": S?},
 "required": ["entries", "next_cursor"], "additionalProperties": false}
```

INDEX:

```json
{"type": "object",
 "properties": {
   "entries": {"type": "array", "items": ENTRY},
   "capped": {"type": "array", "items": {
       "type": "object",
       "properties": {"scope": S, "area": S?, "omitted": {"type": "integer", "minimum": 1}},
       "required": ["scope", "area", "omitted"], "additionalProperties": false}}},
 "required": ["entries", "capped"], "additionalProperties": false}
```

OK:

```json
{"type": "object", "properties": {"ok": {"const": true}}, "required": ["ok"], "additionalProperties": false}
```

ERROR (`error_schema()`):

```json
{"type": "object",
 "properties": {
   "error": S,
   "category": {"type": "string", "enum": ["recoverable", "permanent", "transient", "internal"]},
   "message": S,
   "scope": S, "area": S, "name": S,
   "content": S, "version": S,
   "size": {"type": "integer", "minimum": 0},
   "limit": {"type": "integer", "minimum": 0},
   "match_count": {"type": "integer", "minimum": 0},
   "reason": {"type": "string", "enum": ["invalid_path", "file_absent", "system_read_only", "role_required", "not_granted", "timeout", "unavailable"]},
   "required_roles": {"type": "array", "items": S},
   "argument": S},
 "required": ["error", "category", "message"],
 "additionalProperties": false}
```

The `category` enum is built as `[c.value for c in ErrorCategory] + ["internal"]`; the `reason` enum as the values of `NotFoundReason`, `RestrictionReason`, `TransientReason` in that order. Every other literal above is declared once in `schemas.py` as private module constants and deep-copied per call.

Resulting tool → (input properties, output):

| Tool | Input properties (kind; `*` = required) | Output |
| --- | --- | --- |
| get_memory_index | — | INDEX |
| read_file | scope* S, area* S, name* S | FILE |
| list_prefix | scope* S, area S? default null, cursor S? default null | PAGE |
| write_file | scope* S, area* S, name* S, content* S, description* S, aliases* ARR, expected_version* S? (no default) | FILE |
| append_line | scope* S, area* S, name* S, line* S, expected_version* S, aliases ARR-or-null default null, description S? default null | FILE |
| replace_fact | scope* S, area* S, name* S, old_string* S, new_string* S, expected_version* S, aliases ARR-or-null default null, description S? default null | FILE |
| delete_file | scope* S, area* S, name* S, expected_version* S | OK |

ARR-or-null = `{"anyOf": [ARR, {"type": "null"}]}`.

## Snapshot file

`tests/snapshots/tool_schemas.json` (2-space indent, trailing newline):

```json
{"tools": {"<name>": {"input": ..., "output": ...}, ...}, "error": <error_schema()>}
```

for `tool_schemas()`, tools in `TOOL_NAMES` order. Descriptions and per-tool `error` copies are not in the snapshot (US1.2 and US1.6 cover them), so docstring edits never touch it. The test compares parsed JSON to `{"tools": {n: {"input": s.input, "output": s.output} for n, s in tool_schemas().items()}, "error": error_schema()}`, and also compares `list(s.input["properties"])` per tool with the key order of the parsed snapshot (`json.load` preserves object order), so property order is pinned. On mismatch the assertion message names the file and says to update it deliberately (no regeneration script). The test-writer writes this file by hand from this plan, not by calling the implementation.

## Module layering

`wenchang.schemas` imports `wenchang.tools` (`TOOL_NAMES`, `MemoryTools`, `tool_descriptions`), `wenchang.core` (`MemoryFile`, `ListPage`, `MemoryIndex`, `ListCursor`), `wenchang.errors` (`ErrorCategory`, the three reason enums), `wenchang.version_token`. Nothing imports `wenchang.schemas`. Top-level imports only.

## Tests (new files)

- `tests/test_schemas.py` — US1, US2.1, US3, US4 (jsonschema `Draft202012Validator`).
- `tests/test_schemas_mcp.py` — US2.2 (imports `wenchang.mcp`; reuse the `_server()`/`_tools()` pattern from `tests/test_mcp_server.py`, copying the small `_kind` helper rather than importing test internals).
- `tests/snapshots/tool_schemas.json` — US1.4.

## Dependencies

`pyproject.toml` `[dependency-groups].dev` gains `"jsonschema>=4.20"` and `"types-jsonschema>=4.20"`; `uv lock` updates `uv.lock`. Done by the implementer as T001, before the tests are written.

## Module docstring (required content)

The `schemas` module docstring states that the schemas describe on-contract output, and that the error schema covers wenchang's own error classes: an adopter's `WenchangError` subclass validates only if it reuses these attribute names, types, and `reason` values.

## Docs

- ADR `docs/adr/0042-exported-tool-schemas.md`.
- ARCHITECTURE.md: module map entry for `schemas`; one sentence in the `tools` entry pointing to it.
- README: a short adopter example (`for s in tool_schemas(product=...).values(): ToolDef(name=s.name, description=s.description, parameters=s.input, ...)` in neutral pseudo-code).
- Glossary: no new term.

## Docs site

A self-contained `## Tool schemas` section in `site-src/reference.md` (an h2, so the page's `tool_cards` post-processing leaves it alone), placed after the tool entries and before errors, so AIE-1297 can relocate it whole. Contents:

- What `tool_schemas(product=None)` returns (`ToolSchema` with `name`, `description`, `input`, `output`, `error`; JSON Schema draft 2020-12, closed, fresh per call) and what `error_schema()` returns.
- An example feeding each `ToolSchema` into a host's tool definition: a framework-neutral `ToolDef(name=s.name, description=s.description, parameters=s.input)` sketch, forwarding the call to `MemoryTools` and returning `render_result`/`render_error`, whose payloads match `s.output`/`s.error`. A runnable example goes in `site-src/snippets/` and is included with `<!--include python NAME.py-->`.
- The caveats: the error schema covers wenchang's own error classes, and every field is required for on-contract output.
- Install lines are unpinned (`pip install wenchang`).

Regenerate `site/` with `uv run scripts/build_site.py` and commit both.

## Risks

- Snapshot churn on every signature or rendered-shape change (intended); docstring edits do not touch it.
- An off-contract `TransportClient` can make `render_result` drop a required field; adopters validating strictly would reject that payload. Documented.
