# Feature Specification: Cap the number of files per entity

**Linear**: AIE-1292

**Feature Branch**: `AIE-1292-file-cap`

**Created**: 2026-10-30

**Status**: Draft

**Input**: The only limit is 16 KiB per file. Nothing caps the number of files per user or project, so an agent stuck in a loop could write thousands of files. Add a `max_files_per_entity` setting; reject a write that would create a file past the cap while overwrites, appends, and fact replacements on existing files still succeed; return an error the agent can act on.

## Decisions already made (not reopened)

- Default cap is 500, configurable; `None` disables the cap (human, 2026-10-30).
- A soft cap that concurrent creates may exceed is acceptable if documented.
- Count files through the `Storage` interface; do not depend on the index cache being added by AIE-1293.

## Decisions made in this spec (recorded in ADR 0039)

- **Where the setting lives**: a keyword argument on `MemoryStore`, `max_files_per_entity: int | None = DEFAULT_MAX_FILES_PER_ENTITY` (500), beside `max_file_bytes`, with a read-only property. Enforcement is in `core`, so every transport (and a future remote server, which wraps a `MemoryStore`) enforces it identically, and the tool layer needs no change beyond rendering the new error.
- **Error type**: a new recoverable `FileQuotaExceededError(path, limit)` in `wenchang.errors`. Recoverable because the agent can repair it in the same turn (write into an existing file, or consolidate and delete), like `OversizeWriteError`. A new type rather than reusing `OversizeWriteError`, whose `size`/`limit` are bytes and whose advice ("split the content across multiple files") is the opposite of what the agent must do here.
- **Entity**: the storage prefix `{scope}/{entity_id}/` (`build_prefix(scope, entity_id)`). The same entity ID in two scopes is two entities. Every well-formed memory path under the prefix counts, in every area including `system/`. Keys under the prefix that are not well-formed memory paths (`is_valid_path` false) do not count, since the agent can neither see nor delete them.
- **What is a create**: only `write_file` with `expected_version=None` creates a file. `append_line` and `replace_fact` never create; `write_file` with a token replaces. Only the create path is checked.
- **Race behavior**: soft cap. The count and the conditional put are not atomic, so concurrent creates under one entity that each count below the cap can all land, exceeding the cap by at most the number of creates racing at the boundary. Later creates then fail until the count drops below the cap.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A runaway agent cannot create unbounded files (Priority: P1)

An agent stuck in a loop keeps creating files. Once its entity holds the cap, further creates fail with an error telling it what to do instead.

**Independent Test**: A `MemoryStore` with a small cap; fill one entity to the cap; attempt one more create.

**Acceptance Scenarios**:

1. **Given** a `MemoryStore` with `max_files_per_entity=3` and entity `user/u1/` holding 3 files, **When** `write_file` creates a 4th path under `user/u1/` (`expected_version=None`), **Then** it raises `FileQuotaExceededError` with `path` equal to the requested path and `limit == 3`, and nothing is stored at that path.
2. **Given** a store with cap 3 and `user/u1/` holding 2 files, **When** `write_file` creates a 3rd, **Then** it succeeds (the cap is inclusive: exactly `limit` files may exist).
3. **Given** a store with the default cap, **When** `max_files_per_entity` is read, **Then** it is `500` and equals `core.DEFAULT_MAX_FILES_PER_ENTITY`; **and Given** an entity holding 500 files under the default, **When** a 501st is created, **Then** `FileQuotaExceededError` with `limit == 500` is raised.

---

### User Story 2 - Existing files stay editable at the cap (Priority: P1)

**Acceptance Scenarios**:

1. **Given** an entity at the cap, **When** `write_file` replaces one of its files with the current version token, **Then** it succeeds.
2. **Given** an entity at the cap, **When** `append_line` appends to one of its files, **Then** it succeeds.
3. **Given** an entity at the cap, **When** `replace_fact` edits one of its files, **Then** it succeeds.
4. **Given** an entity at the cap, **When** `write_file` creates (`expected_version=None`) a path that already exists, **Then** it raises `VersionConflictError` carrying that file's current content and version (as it would below the cap), not `FileQuotaExceededError`.

---

### User Story 3 - Deleting a file frees a slot (Priority: P1)

**Acceptance Scenarios**:

1. **Given** an entity at the cap, **When** one file is deleted with `delete_file` and a new path is then created, **Then** the create succeeds and the entity again holds exactly `limit` files.

---

### User Story 4 - The limit is per entity (Priority: P1)

**Acceptance Scenarios**:

1. **Given** cap 3 and `user/u1/` at the cap, **When** a file is created under `user/u2/`, **Then** it succeeds.
2. **Given** cap 3 and `user/u1/` at the cap, **When** a file is created under `project/u1/` (same entity ID, different scope), **Then** it succeeds.
3. **Given** cap 3 and `user/u1/` holding 3 files spread over several areas (including `system/`), **When** a 4th is created in any area, **Then** `FileQuotaExceededError` is raised.
4. **Given** cap 3 and `user/u1/` holding 2 well-formed files plus 2 keys under `user/u1/` that are not well-formed memory paths (seeded directly into storage), **When** a 3rd well-formed file is created, **Then** it succeeds.

---

### User Story 5 - The agent knows what to do next (Priority: P1)

**Acceptance Scenarios**:

1. **Given** a `FileQuotaExceededError("user/u1/notes/new.md", 3)`, **When** it is rendered with `str()`, **Then** the text is exactly the message in plan.md: it names the scope, area, and name, the limit, tells the agent to add the content to an existing file (naming `append_line`, `replace_fact`, and `write_file`) or merge related files and delete the merged ones (naming `delete_file`), then retry; and ends with the recoverable guidance. It never contains the entity ID `u1`.
2. **Given** the error, **When** its category is read, **Then** it is `ErrorCategory.RECOVERABLE` and it is a `RecoverableError`.
3. **Given** a `MemoryTools` over an `InProcessClient` whose store has cap 1 and whose caller's entity holds 1 file, **When** the agent calls `write_file` for a new name, **Then** it raises `FileQuotaExceededError`, and `render_error` of it yields `error == "FileQuotaExceededError"`, `category == "recoverable"`, `limit == 1`, the `scope`, `area`, and `name` of the request, the full message, and no `path` key.

---

### User Story 6 - Adopters configure or disable the cap (Priority: P2)

**Acceptance Scenarios**:

1. **Given** `MemoryStore(storage, max_files_per_entity=None)`, **When** more than 500 files are created under one entity, **Then** every create succeeds and the property reads `None`.
2. **Given** `max_files_per_entity=0` or `-1`, **When** `MemoryStore` is constructed, **Then** it raises `ValueError("max_files_per_entity must be positive or None")`.
3. **Given** `FileQuotaExceededError(path, 0)`, **When** constructed, **Then** it raises `ValueError` (the limit must be positive).

---

### User Story 7 - The limit is recorded (Priority: P2)

**Acceptance Scenarios**:

1. **Given** `docs/adr/`, **When** listed, **Then** ADR 0039 records the cap, its default, the entity definition, the error choice, and the soft-cap race behavior; **and** ARCHITECTURE.md's `core` and `errors` entries, key invariants, and error taxonomy describe the limit.

### Edge Cases

- Check order in `write_file` is unchanged up to the cap check: invalid path, empty `source`, oversize, then (create only) the cap. An oversize create at the cap raises `OversizeWriteError`.
- The cap check counts with `Storage.list_page`, not `MemoryStore.list_prefix`, so corrupt metadata on another file never blocks a create and a subclass override cannot change the count.
- Counting stops as soon as `limit` well-formed keys are seen, so a create never lists more than about `limit` keys.
- Listing is not a snapshot; a delete or create racing the count may be missed. The cap is soft (see Decisions).
- The transport conformance suite is unchanged: it has no fixture for the cap, and its cases write far fewer than 500 files per entity. The transport error-parity contract already covers the new error.
- Lowering the cap below an entity's current count blocks creates until files are deleted below the new cap; existing files are never removed.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `MemoryStore.__init__` MUST accept keyword-only `max_files_per_entity: int | None = DEFAULT_MAX_FILES_PER_ENTITY`, where `core.DEFAULT_MAX_FILES_PER_ENTITY: int = 500`; a non-`None` value `<= 0` MUST raise `ValueError("max_files_per_entity must be positive or None")`, checked after the existing `index_max_bytes` positivity check. A read-only property `max_files_per_entity` MUST return the configured value.
- **FR-002**: `write_file` with `expected_version=None` and a non-`None` cap MUST, after the path, `source`, and size checks and before the conditional put, count the well-formed memory paths under `build_prefix(scope, entity_id)` of the requested path via `Storage.list_page`; if the count is `>= limit` it MUST read the requested path and raise `VersionConflictError(path, content, version)` if a file exists there, otherwise `FileQuotaExceededError(path, limit)`, storing nothing.
- **FR-003**: `write_file` with a version token, `append_line`, `replace_fact`, `delete_file`, and all reads MUST NOT consult the cap.
- **FR-004**: `wenchang.errors.FileQuotaExceededError(path: str, limit: int)` MUST be a `RecoverableError` exposing `path` and `limit`, raising `ValueError` for `limit < 1`, with the exact message in plan.md.
- **FR-005**: `tools.render_error` MUST render the new error with its `limit` and location and no path (no code change expected: `limit` is already a rendered payload field).
- **FR-006**: ADR 0039 and ARCHITECTURE.md MUST record the limit.

## Success Criteria *(mandatory)*

- **SC-001**: Every acceptance scenario above has a passing test; `make check` is green.
- **SC-002**: `make test-integration` is green (the cap uses `Storage.list_page`, which `GcsStorage` implements).

## Assumptions

- No current test or eval writes more than 500 files under one entity (checked: the largest is 101 in `tests/test_core_list_prefix.py`).
- The tool docstrings and the prompt are not changed: the error text itself carries the next action, which is what the acceptance criteria require.
