# Spec Review: AIE-1295 — Export tool input/output schemas

## What & why

Adopters wiring the memory tools into their own tool framework copy argument and result shapes by hand from `MemoryTools` and `render_result`/`render_error`, and the copies drift. A new `wenchang.schemas` module exports, per tool, a name, description, and JSON Schemas for its input, success output, and error output, derived from the tool signatures and from shapes declared once next to the renderers' tests. A committed snapshot plus validation of real renders makes any unacknowledged change fail.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | `tool_schemas(product)` | read | one `ToolSchema` per tool in `TOOL_NAMES` order; description = `tool_descriptions(product)` |
| 2 | every schema | `check_schema` (draft 2020-12) | valid, JSON-serializable, fresh per call |
| 3 | the export | compared to `tests/snapshots/tool_schemas.json` | equal |
| 4 | each tool's input schema | vs. `MemoryTools` signature and MCP-registered schema | same params, required set, defaults, kinds |
| 5 | real `render_result` payloads for all tools (incl. paged, capped, malformed path, empty aliases/description/entries/capped) | validated | valid; union of keys = declared properties |
| 6 | one fixture per concrete error class (completeness-checked), plus internal errors | `render_error` validated | valid; union of keys = declared properties; enums generated from the taxonomy |
| 7 | docs | read | ADR 0042, ARCHITECTURE `schemas` entry, README snippet |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| JSON Schema dicts, no pydantic models | pydantic classes in core; classes behind `[mcp]` extra; `create_model` at runtime | core has no pydantic dep; every ToolDef framework takes JSON Schema; hand classes would be a second drifting source; dynamic models give no static types |
| New `wenchang.schemas` module above `tools` | `tools.tool_schemas()` | keeps the 780-line `tools` module focused; no import cycle |
| Inputs derived from signatures via a closed type map | hand-written input schemas; reuse MCP/pydantic generation | "same source"; core can't import mcp/pydantic; unknown types raise |
| Outputs chosen by return annotation from declared shapes | derive from renderer code | renderer is defensive code, not data; declared shapes + closed validation catch drift both ways |
| One flat error schema | per-class `oneOf` keyed by `error` | adopters/transports raise their own `WenchangError` subclasses with other names |
| Fields required even though off-contract clients can drop them | all-optional | describes the real contract; optional would make adopters' models useless |
| Snapshot holds per-tool input/output + one error schema, property order pinned | include descriptions | docstring (prompt) fixes must not fail `make check`; descriptions are checked against `tool_descriptions` instead |
| Error schema covers wenchang's own error classes | open schema for adopter subclasses | adopter subclasses validate only if they reuse these attribute names, types, and reasons (orchestrator decision) |

## Files/modules to be touched

- `src/wenchang/schemas.py` (new)
- `tests/test_schemas.py`, `tests/test_schemas_mcp.py`, `tests/snapshots/tool_schemas.json` (new)
- `pyproject.toml`, `uv.lock` (dev group: `jsonschema`, `types-jsonschema`)
- `docs/adr/0042-exported-tool-schemas.md`, `ARCHITECTURE.md`, `README.md`

## Open questions / assumptions

- Resolved (orchestrator, 2026-10-30): JSON Schema only; a pydantic generator from this export is a follow-up.
- Resolved: MCP tools keep no `outputSchema`; advertising one is a follow-up.
- Resolved: parameter-level descriptions are not exported.

## Risks

- Snapshot churn on every signature or rendered-shape edit (intended).
- Strict adopter validators could reject an off-contract client's payload with a dropped field.
- Sibling PRs: #54's `FileQuotaExceededError` needs a fixture after rebase (completeness test enforces it); #53's `functools.wraps` wrapper keeps `inspect.signature` intact.
