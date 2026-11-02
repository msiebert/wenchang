# 0042. Exported tool schemas

Date: 2026-10-30

## Status

Accepted.

## Context

Adopters building tool definitions for a host framework need an input and
output schema for each of the seven memory tools. Without an export they
copy them by hand from the `MemoryTools` signatures and from the dicts
`render_result` and `render_error` return, and the copies drift. The
schemas should come from the same source the tools use, and a test should
fail when a signature or rendered shape changes without the schema.

## Decision

1. **JSON Schema (draft 2020-12) `dict`s, not pydantic models.** The core
   package has no pydantic, and every tool-definition framework accepts
   JSON Schema (pydantic-ai `parameters_json_schema`, MCP
   `inputSchema`/`outputSchema`, Anthropic and OpenAI `input_schema`).
   Hand-written pydantic classes would be a second source that drifts;
   classes built with `create_model` give adopters no static types. None
   are shipped, not even behind the `[mcp]` extra.
2. **New module `wenchang.schemas`**, public names `ToolSchema`,
   `tool_schemas(product=None)`, and `error_schema()`. It imports `tools`,
   `core`, and `errors`; nothing imports it, and it is not re-exported from
   the package root.
   - `ToolSchema(name, description, input, output, error)` is a frozen
     dataclass of plain `dict`s; instances compare by value and are
     unhashable.
   - `tool_schemas` returns a read-only mapping in `TOOL_NAMES` order;
     `description` is `tool_descriptions(product)[name]`, so `product` is
     validated exactly as there.
   - Every call returns fresh objects; mutating one result never affects
     another. Every object schema is closed (`additionalProperties: false`).
3. **Inputs are derived from the `MemoryTools` signatures** at call time,
   through `inspect.unwrap` of the observer decorator so its own
   annotations never stand in. The type map is closed: `str` and any
   `NewType` over `str` map to a string, `Sequence[str]` to a string array,
   and `T | None` to `anyOf` of `T` and null. A parameter without a default
   is required; a default becomes `"default"` and must be `None`, `bool`,
   `int`, `float`, or `str`. Anything else, including a non
   positional-or-keyword parameter, raises `TypeError`.
4. **Outputs are chosen by return annotation** (`MemoryIndex`,
   `MemoryFile`, `ListPage`, `None`) from rendered shapes declared once in
   `wenchang.schemas`; an unmapped annotation raises `TypeError`.
   `last_updated` carries `format: date-time` as documentation.
5. **One flat error schema** shared by every tool, not a per-class union:
   `error`, `category`, and `message` are required, and every optional
   field `render_error` can emit is declared. The `category` enum is
   `ErrorCategory`'s values plus `"internal"`; the `reason` enum is the
   values of `NotFoundReason`, `RestrictionReason`, and `TransientReason`.
   Both are generated, so they cannot drift from the taxonomy.
6. **The error schema covers wenchang's own error classes.** An adopter's
   `WenchangError` subclass validates only if it reuses these attribute
   names, types, and `reason` values.
7. **Required fields describe on-contract output.** `render_result` drops a
   field whose value has the wrong type, which an off-contract
   `TransportClient` can produce; the schema still marks every field
   required, since an on-contract client always produces it.
8. **Drift guards, in tests.**
   - A committed snapshot (`tests/snapshots/tool_schemas.json`) of each
     tool's `input` and `output` plus the error schema, with property order
     pinned. Descriptions are excluded, so docstring and prompt edits never
     fail it; any signature change does.
   - Real renders from an in-process session, plus edge and failure cases,
     validate against the closed schemas, and the union of rendered keys
     must equal each schema's declared properties, so the schema neither
     misses nor invents a field.
   - A walk of `WenchangError` subclasses defined in `wenchang` modules
     fails until each concrete class has a rendering fixture.
   - The input schemas the MCP adapter registers are cross-checked against
     the export (property names, required set, kind per property).
9. **`jsonschema` and `types-jsonschema` are dev-only.** No runtime
   dependency is added; `render_result`, `render_error`, the tool
   signatures, and `wenchang.mcp` are unchanged.

## Consequences

- Adopters build tool definitions from one call and stay current by
  upgrading wenchang.
- Every tool signature or rendered-shape change must update the snapshot
  or the declared shape in the same change; that churn is intended.
- A new parameter type, default type, return type, or error class fails
  loudly until it is mapped or given a fixture.
- Adopters validating results strictly may reject a payload from an
  off-contract client, and an adopter error subclass with its own fields
  fails the error schema.
- Parameter-level descriptions are not exported; the tool description
  documents parameters, as it does for MCP.

Follow-ups:

- A pydantic model generator built from this export, for adopters who want
  classes.
- Advertising each tool's `outputSchema` from the MCP adapter.

Rejected:

- **Shipping pydantic models**, in core or behind `[mcp]`: a runtime
  dependency or a second, drifting source.
- **A per-error-class union**: adopter and transport subclasses render with
  their own `error` names and would never match it.
- **Hand-declared input schemas**: a second copy of the signatures.
