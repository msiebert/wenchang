# Feature Specification: Remove `path` from agent-facing tool results

**Linear**: AIE-1252

Allow-test-changes: AIE-1252 removes the eval reply-path check (ADR 0033), so its grader, report, and end-to-end tests are deleted with it (human-approved at the spec checkpoint); every other changed test swaps a `path` expectation for scope/area/name.

**Feature Branch**: `AIE-1252-remove-path-results`

**Created**: 2026-10-26

**Status**: Draft

**Input**: Tool results return `path` next to `scope`, `area`, and `name`. No tool takes a path as input and agents work in scope/area/name terms, so `path` adds tokens without helping the agent.

## Decisions already made (not reopened)

- The agent names a location by scope, area, and name only. No new `entity` field.
- `path` leaves errors too: the rendered field and the message text.
- Capped index rows drop `prefix`.
- Core value types (`MemoryFile`, `FileEntry`, `CappedPrefix`) and core/scope error objects keep their `.path` / `.prefix` attributes. Only the agent-facing render layer, error message text, prompt, and evals change.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Tool results carry no path (Priority: P1)

An agent calling any tool gets scope, area, name, version, and metadata, and no `path` or `prefix` anywhere in a success result.

**Why this priority**: The issue's core ask; every other story follows from it.

**Independent Test**: Render each result kind with `render_result` and walk the output for the keys `path` and `prefix`.

**Acceptance Scenarios**:

1. **Given** a `MemoryFile` for `user/u-ada/preferences/csv.md`, **When** `render_result` renders it (as returned by `read_file`, `write_file`, `append_line`, or `replace_fact`), **Then** the dict has no `path` key and has `scope="user"`, `area="preferences"`, `name="csv"`, `content`, `version`, `description`, `aliases`, `sources`, and `last_updated`.
2. **Given** a `ListPage` with entries and a `next_cursor`, **When** rendered, **Then** each entry has scope/area/name/version/metadata and no `path` or `content`, and `next_cursor` is the unchanged opaque string (or `None`).
3. **Given** a `MemoryIndex` with entries and capped rows, **When** rendered, **Then** each entry has no `path`, and each capped row is exactly `{scope, area, omitted}` with no `prefix`; `area` is `None` for a scope- or entity-level prefix.
4. **Given** the `delete_file` result, **When** rendered, **Then** it is `{"ok": True}`.
5. **Given** an entry whose real path is malformed, **When** rendered, **Then** `scope`, `area`, `name` are `None` and there is no `path` key.
6. **Given** an entry whose `path` is not a `str`, **When** rendered, **Then** `scope`, `area`, `name` are omitted (as today) and there is still no `path` key.
7. **Given** an MCP `tools/call` of any tool, **When** it succeeds, **Then** both the `TextContent` JSON and `structured_content` contain no `path` or `prefix` key at any depth.

---

### User Story 2 - Errors name scope, area, and name (Priority: P1)

A failed call reports where in scope/area/name terms, in both fields and message text.

**Why this priority**: Acceptance criterion: no error result contains `path`.

**Independent Test**: Construct each error kind, render with `render_error`, assert on keys and message.

**Acceptance Scenarios**:

1. **Given** `VersionConflictError`, `OversizeWriteError`, `ReplaceFactMatchError`, `NotFoundError(FILE_ABSENT)`, or `RestrictedScopeError` raised for `user/u-ada/preferences/csv.md`, **When** rendered, **Then** there is no `path` key and `scope="user"`, `area="preferences"`, `name="csv"` are present, together with each kind's existing repair fields (`content`, `version`, `size`, `limit`, `match_count`, `reason`, `required_roles`).
2. **Given** the same errors, **When** the message is read, **Then** it names the location as `scope user, area preferences, name csv`, contains no `/`-joined path, no `.md`, and no entity ID.
3. **Given** `NotFoundError(INVALID_PATH)` with an unparseable path, **When** rendered, **Then** there is no `path`, `scope`, `area`, or `name` key and the message does not echo the raw path.
4. **Given** `InvalidArgumentError`, `TransientError` kinds, and the internal-error fallbacks, **When** rendered, **Then** they are unchanged.
5. **Given** an error object, **When** its `.path` attribute is read in-process, **Then** it still holds the path (core callers and conformance tests rely on it); only rendering omits it.
6. **Given** an off-contract exception or an error whose attributes raise, **When** rendered, **Then** `render_error` still never raises and never leaks internals.

---

### User Story 3 - Prompt tells the agent to name scope, area, and name (Priority: P2)

**Why this priority**: Without it, the agent has no `path` to quote and the old sentence would be false.

**Independent Test**: Assert on `overview.BODY` and the rendered `.claude/agents/wenchang-eval.md`.

**Acceptance Scenarios**:

1. **Given** `overview.BODY`, **When** read, **Then** the sentence about quoting the returned `path` is replaced by: "When you tell the user where something is stored, name its scope, area, and name." The body has no backtick span `path` and no word `path`.
2. **Given** that sentence, **When** inspected, **Then** it names no scope, area, file, or fact from any eval scenario.
3. **Given** `.claude/agents/wenchang-eval.md`, **When** regenerated with `uv run python -m evals render-agent`, **Then** it matches the prompt and contains no "quote the full `path`" text.
4. **Given** the `get_memory_index` docstring, **When** read, **Then** it describes entries by scope, area, name and no longer states a `path` form, and `tool_descriptions` still pass their existing pins.

---

### User Story 4 - Evals match the new wording (Priority: P2)

**Why this priority**: The reply-path check and four scenarios encode the old rule and would fail or mislead.

**Independent Test**: Corpus and end-to-end driver tests; `make check`.

**Acceptance Scenarios**:

1. **Given** `evals/graders.py`, **When** imported, **Then** `find_unmatched_reply_paths`, `UnmatchedReplyPath`, `PATH_ROOTS`, `_LOCATION_KEYS`, and their private helpers no longer exist.
2. **Given** a new grade, **When** `grade.json` is written, **Then** it has no `unmatched_reply_paths`; `report.json` has no `reply_path_trials`, `reply_path_unchecked_trials`, or `reply_paths`; the markdown has no reply-path lines.
3. **Given** an old `grade.json` that still contains `unmatched_reply_paths`, **When** loaded or refreshed, **Then** it loads without error and the field is ignored. (Recorded runs are not rewritten.)
4. **Given** `filing-says-saved-path`, `recall-says-stored-path`, `slots-says-shared-path`, **When** a correct driver replies naming scope, area, and name (no entity ID), **Then** all assertions pass; **When** a driver replies with an entity-qualified path or an entity ID, **Then** the no-entity check fails.
5. **Given** `applying-no-path-unasked`, **When** a driver volunteers a location, **Then** its check fails; **When** it only applies the preference, **Then** it passes.
6. **Given** the scenario corpus, **When** loaded, **Then** ids are unchanged and every `# Prompt:` header cites a sentence that still exists in the prompt.

---

### User Story 5 - Core types keep `.path` (Priority: P3)

**Acceptance Scenarios**:

1. **Given** `MemoryFile`, `FileEntry`, `CappedPrefix`, **When** read in-process, **Then** `.path` / `.prefix` are unchanged, and all `test_core_*` tests pass unmodified.

---

### Edge Cases

- A name or area that itself contains characters resembling a path (for example a name `a.md`): rendered verbatim in `name`; no path is rebuilt.
- A message for an invalid location must not echo an agent-controlled raw string beyond what is already echoed as an argument.
- `list_prefix` of an area whose `NotFoundError` carries a prefix (not a path): the tool layer already validates arguments first, so no rendered `path`, `scope`, `area`, or `name` appears.
- Old recorded run directories contain `unmatched_reply_paths`; reports must not crash on them.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `render_result` MUST NOT emit `path` for any file field, list entry, or index entry.
- **FR-002**: `render_result` MUST still emit `scope`, `area`, `name` (parsed from the entry path internally), `version`, and metadata fields, with the same malformed/non-str degradation as today.
- **FR-003**: Capped index rows MUST render exactly `scope`, `area`, `omitted`.
- **FR-004**: `next_cursor` MUST be unchanged.
- **FR-005**: `render_error` MUST NOT emit `path`, and MUST emit `scope`, `area`, `name` when the error carries a parseable path.
- **FR-006**: Error message text MUST name the location as `scope S, area A, name N` and MUST NOT contain a path.
- **FR-007**: Error classes MUST keep their `.path` constructor argument and attribute.
- **FR-008**: The overview prompt MUST tell the agent to name scope, area, and name, and MUST NOT mention `path`. The eval agent file MUST be regenerated to match.
- **FR-009**: The reply-path grader, its report fields, and its tests MUST be removed; old `grade.json` files MUST still load.
- **FR-010**: The four named scenarios MUST be rewritten or confirmed per US4; ids unchanged.
- **FR-011**: A new ADR MUST supersede ADR 0033 and amend ADR 0022's render shape; ARCHITECTURE.md and the glossary MUST be updated.
- **FR-012**: `make check` MUST pass.

### Key Entities

- **Location**: A file's address as the agent sees it: scope, area, name. The entity segment is implicit, filled in from the caller's grant.
- **Memory path**: Internal storage address `scope/entity/area/name.md`; no longer shown to the agent.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A recursive key walk over every rendered success and error result finds zero `path` and zero `prefix` keys.
- **SC-002**: Every file result still carries `scope`, `area`, `name`, `version`.
- **SC-003**: `rg 'quote the full'` over `src/` and `.claude/agents/` finds nothing.
- **SC-004**: `make check` passes.

## Assumptions

- The live eval run is not part of `make check`; the rewritten scenarios are validated by driver tests, and a live run is a follow-up for the human.
- Hosts that embed wenchang in-process and read `.path` from core values are unaffected. Hosts that parsed `path` from rendered JSON break; this is an intended contract change recorded in the ADR.
- `site-src/` and `README.md` document the old result shape; updating them is decided separately (see review-spec).
