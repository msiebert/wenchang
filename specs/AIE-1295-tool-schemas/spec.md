# Feature Specification: Export tool input/output schemas

**Linear**: AIE-1295

**Feature Branch**: `AIE-1295-tool-schemas`

**Created**: 2026-10-30

**Status**: Draft

**Input**: Adopters' ToolDefs need input and output models for the seven memory tools. Today they copy them by hand from the `MemoryTools` signatures and from the dicts `render_result` / `render_error` return, so they drift. Export a schema for each tool's input and output, including the error shape, generated from the same source the tools use. Acceptance: every tool has an exported input and output schema; a test fails if a tool signature or rendered result changes without the schema changing too.

## Decisions made in this spec (recorded in ADR 0042)

- **JSON Schema, not pydantic models.** The core package has one runtime dependency (`google-cloud-storage`) and no pydantic. The export is plain JSON Schema (draft 2020-12) `dict`s, which every tool-definition framework accepts (pydantic-ai's `ToolDefinition.parameters_json_schema`, MCP `inputSchema`/`outputSchema`, Anthropic/OpenAI tool `input_schema`). No pydantic classes are shipped, not even behind the `[mcp]` extra: hand-written classes would be a second source that can drift, and dynamically built `create_model` classes give adopters no static types.
- **Public home**: a new module `wenchang.schemas` with `ToolSchema`, `tool_schemas(product=None)`, and `error_schema()`. It sits above `wenchang.tools` (imports it); `tools` does not import it.
- **Input schemas are derived** at call time from `inspect.signature` of each `MemoryTools` method (annotations and defaults), through a closed type map; an annotation outside the map raises `TypeError`, so a new parameter type cannot slip through unmapped.
- **Output schemas are derived from each method's return annotation** (`MemoryFile`, `ListPage`, `MemoryIndex`, `None`) mapped to one declared JSON Schema per rendered shape in `wenchang.schemas`. Those declarations are the single statement of the rendered shape; `render_result`/`render_error` are tested against them with `additionalProperties: false` and full `required` lists.
- **Error shape is one flat schema** shared by every tool, not a per-error-class union: adopters and transports may raise `WenchangError` subclasses with other names, which render with their own `error` name. `category` and `reason` enums are generated from `ErrorCategory` (plus `"internal"`) and the three reason `StrEnum`s, so they cannot drift.
- **Adopter error subclasses (orchestrator decision)**: the error schema covers wenchang's own error classes. An adopter's `WenchangError` subclass validates only if it reuses these attribute names, types, and `reason` values. Stated in this spec, ADR 0042, and the `schemas` module docstring.
- **Required fields describe on-contract output.** `render_result` drops a field whose underlying value has the wrong type (an off-contract `TransportClient`); the schema still marks every field required, since an on-contract client always produces it. Documented in the module docstring and ADR.
- **Drift guard is a committed snapshot** of each tool's `input` and `output` plus the one error schema, with property order pinned (`tests/snapshots/tool_schemas.json`; descriptions excluded so docstring edits never fail it) plus validation of real renders against the export. A signature change alters the derived input schema and fails the snapshot; a render change fails validation.
- **No change to the MCP adapter's registered schemas.** A test cross-checks that the MCP-registered input schemas have the same property names, required sets, and kinds as the exported ones, guarding the adapter's hand-copied wrapper signatures.
- **Test-only dependency**: `jsonschema` and `types-jsonschema` join the `dev` dependency group (jsonschema is already in the lock via `mcp`). No runtime dependency is added.

## Sibling changes this design covers

- AIE-1292 (PR #54) adds `FileQuotaExceededError(path, limit)`: renders `limit` and location, both already in the error schema. The error-class completeness test fails until a fixture for it is added, which happens when this branch is rebased onto a main containing PR #54.
- AIE-1296 (PR #53) wraps each tool method with `functools.wraps`; `inspect.signature` follows `__wrapped__`, so derivation is unchanged. `on_call` is a constructor/`bind_tools` argument, not a tool parameter, so no tool schema changes.
- AIE-1293 (PR #56) changes no tool surface.
- AIE-1291 changes no tool or error surface; its `PurgeIncompleteError` renders as `internal`.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - An adopter builds tool definitions from the export (Priority: P1)

**Independent Test**: call `tool_schemas()` and inspect it without a session, store, or credentials.

**Acceptance Scenarios**:

1. **Given** `tool_schemas()`, **When** its keys are read, **Then** they equal `TOOL_NAMES` in order, and each value is a `ToolSchema` whose `name` equals its key.
2. **Given** `tool_schemas(product="Mixpanel")`, **When** each `description` is read, **Then** it equals `tool_descriptions("Mixpanel")[name]`; with no product it equals `tool_descriptions()[name]`. An invalid product raises exactly what `tool_descriptions` raises.
3. **Given** any `ToolSchema`, **When** `input`, `output`, and `error` are checked with `jsonschema.Draft202012Validator.check_schema`, **Then** each is a valid schema, and `json.dumps` of each succeeds.
4. **Given** `tool_schemas()` and `error_schema()`, **When** compared to the committed snapshot `tests/snapshots/tool_schemas.json` (plan.md gives its exact contents), **Then** each tool's `input` and `output`, and the error schema, are equal to it, and each tool's `list(input["properties"])` matches the snapshot's key order.
5. **Given** two calls to `tool_schemas()`, **When** a nested dict in the first result is mutated, **Then** the second result is unaffected (each call returns fresh plain `dict`s and `list`s); the same holds for `error_schema()`.
6. **Given** every `ToolSchema`, **When** `error` is compared to `error_schema()`, **Then** they are equal.

---

### User Story 2 - Input schemas cannot drift from the tool signatures (Priority: P1)

**Acceptance Scenarios**:

1. **Given** each tool name, **When** its `input` schema is compared to `inspect.signature(getattr(MemoryTools, name))` (excluding `self`), **Then** `properties` keys equal the parameter names in order, `required` lists exactly the parameters without a default in signature order, and each parameter with a default carries that default as `"default"`.
2. **Given** each tool name, **When** the exported `input` schema is compared with the input schema the MCP adapter registers for that tool (`register_memory_tools`, no prefix), **Then** both have the same property names, the same required set, and the same kind per property under the existing `_kind` rendering in `tests/test_mcp_server.py` (`"string"`, `"string|null"`, `"array[string]"`, `"array[string]|null"`).
3. **Given** the snapshot test, **When** a tool parameter is added, removed, renamed, retyped, or has its default changed, **Then** the snapshot test fails (follows from derivation plus US1.4; no separate test).

---

### User Story 3 - Output schemas match what `render_result` produces (Priority: P1)

Results come from a real `MemoryTools` over an `InProcessClient` and `MemoryStore` on in-memory storage, unless stated.

**Acceptance Scenarios**:

1. **Given** a session, **When** `get_memory_index`, `read_file`, `write_file` (create and replace), `append_line` (with and without `aliases`/`description`), `replace_fact`, `list_prefix` (one page with `next_cursor` null), and `delete_file` succeed, **Then** `render_result` of each return value validates against that tool's `output` schema, and every rendered `last_updated` matches `^\d{4}-\d\d-\d\dT.*Z$` (`format: date-time` is documentation only; validation runs without format checking).
1a. **Given** a session, **When** these edge results are rendered — `write_file` with `aliases=[]`, a file written with `description=""`, a `list_prefix` of an empty area (empty `entries`), and a `MemoryIndex` with empty `entries` and empty `capped` (constructed directly or from an identity with no files) — **Then** each validates (empty values keep their keys).
2. **Given** a `list_prefix` whose result has more files than one page (store's list page size set small enough, or enough files written), **When** the first page is rendered, **Then** it has a string `next_cursor` and validates.
3. **Given** a `MemoryIndex` constructed directly with at least one `CappedPrefix` at entity level (`area` null) and one at area level, **When** rendered, **Then** it validates against `get_memory_index`'s `output`.
4. **Given** a `MemoryFile` constructed directly with a path that does not parse, **When** rendered, **Then** `scope`, `area`, and `name` are `None` and it validates against `read_file`'s `output`.
5. **Given** every rendered success payload from US3.1-3.4, **When** the union of its keys per output schema is taken, **Then** it equals that schema's declared `properties` (nested objects included: file entries and capped rows), so the schema declares no field the renderer never produces.
6. **Given** a rendered `read_file` payload with an extra key added, or with `version` removed, **When** validated, **Then** validation fails (the schemas are closed and complete).

---

### User Story 4 - The error schema matches what `render_error` produces (Priority: P1)

**Acceptance Scenarios**:

1. **Given** a fixture table with at least one instance of every concrete wenchang error class (every subclass found by walking `WenchangError.__subclasses__()` recursively, kept only if `cls.__module__ == "wenchang"` or starts with `"wenchang."`, minus `RecoverableError`, `PermanentError`, `TransientError`; test-defined subclasses are thereby excluded), covering every reason member and both `ReplaceFactMatchError` branches (`match_count` 0 and 2), both a parseable and an unparseable path where the class takes a path, and a `RestrictedScopeError` whose path does not parse but whose `scope` is set (renders `scope` without `area`/`name`), **When** the table's classes are compared to the discovered set, **Then** every discovered class has a fixture (a new error class fails this test until a fixture is added).
2. **Given** each fixture, **When** `render_error` of it is validated against `error_schema()`, **Then** it is valid.
3. **Given** `MetadataFormatError`, `UnicodeDecodeError`, a plain `RuntimeError`, and a `WenchangError` subclass whose `category` is not an `ErrorCategory`, **When** rendered and validated, **Then** each is valid with `category == "internal"`.
4. **Given** all payloads from US4.2-4.3, **When** the union of their keys is taken, **Then** it equals the error schema's `properties` keys.
5. **Given** the error schema, **When** its `category` enum is read, **Then** it is `[c.value for c in ErrorCategory] + ["internal"]`; its `reason` enum is the values of `NotFoundReason`, `RestrictionReason`, and `TransientReason`, in that order.
6. **Given** a session, **When** real tool calls fail (`read_file` of an absent file, `write_file` to `system/`, `write_file` with a stale `expected_version`, `read_file` with an invalid `area`, `replace_fact` with an `old_string` that matches nothing), **Then** `render_error` of each raised exception validates against that tool's `error` schema.

---

### User Story 5 - The export is documented (Priority: P2)

**Acceptance Scenarios**:

1. **Given** `docs/adr/`, **When** listed, **Then** ADR 0042 records the JSON-Schema-not-pydantic choice, the derivation sources, the required-fields stance, the flat error schema and the adopter-subclass stance, the snapshot drift guard, and the follow-ups (pydantic generator, MCP `outputSchema`); **and** ARCHITECTURE.md's module map has a `schemas` entry and the `tools` entry points to it; **and** README's adopter section shows `tool_schemas()` in a few lines.

### Edge Cases

- `get_memory_index` has no parameters: its input schema is `{"type": "object", "properties": {}, "required": [], "additionalProperties": false}`.
- `write_file`'s `expected_version: VersionToken | None` has no default: it is required and nullable.
- `NewType`s over `str` (`VersionToken`, `ListCursor`) map to `{"type": "string"}`.
- A default that is not `None`, `str`, `int`, `float`, or `bool` raises `TypeError` during derivation (none exist today).
- `render_result` and `render_error` are unchanged. A field added to `render_error`'s copy list fails US4.2 (closed schema) once any fixture carries it; a declared field no fixture produces fails US4.4.
- `ToolSchema` is a frozen dataclass whose fields are plain `dict`s; like `ToolCallRecord`, instances compare by value and are unhashable.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `wenchang.schemas` MUST export `ToolSchema`, `tool_schemas`, and `error_schema` (its `__all__`), with the exact signatures and outputs in plan.md.
- **FR-002**: Input schemas MUST be derived from the `MemoryTools` method signatures at call time; unmapped annotations or defaults MUST raise `TypeError`.
- **FR-003**: Output schemas MUST be chosen by each method's return annotation from the declared rendered shapes; an unmapped return annotation MUST raise `TypeError`.
- **FR-004**: Every schema MUST be valid JSON Schema draft 2020-12, JSON-serializable, closed (`additionalProperties: false` on every object), and returned as fresh objects per call.
- **FR-005**: No runtime dependency is added; `jsonschema` and `types-jsonschema` are added to the `dev` group only.
- **FR-006**: `render_result`, `render_error`, the tool signatures, and the MCP adapter are unchanged.
- **FR-007**: ADR 0042, ARCHITECTURE.md, and README MUST document the export.

## Success Criteria *(mandatory)*

- **SC-001**: Every acceptance scenario has a passing test; `make check` is green.
- **SC-002**: Changing any tool signature or any rendered field without updating the snapshot/declared schema fails at least one test.

## Assumptions

- Adopters' tool-definition frameworks accept JSON Schema dicts; adopters who need pydantic classes generate them from the export (out of scope here).
- Parameter-level descriptions are not part of the export; the tool description (from `tool_descriptions`) documents parameters, as it does for MCP today.
