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
- `system/` files do not count toward the cap, and creates under `system/` are never checked (orchestrator, 2026-10-30): the agent cannot delete or merge `system/` files, so a quota error would give it nothing to do; the cap exists to stop runaway agent writes; and seeding writes `system/` through `write_file(expected_version=None)`.

## Decisions made in this spec (recorded in ADR 0039)

- **Where the setting lives**: a keyword argument on `MemoryStore`, `max_files_per_entity: int | None = DEFAULT_MAX_FILES_PER_ENTITY` (500), beside `max_file_bytes`, with a read-only property. Enforcement is in `core`, so every transport (and a future remote server, which wraps a `MemoryStore`) enforces it identically, and the tool layer needs no logic change beyond a docstring line.
- **Error type**: a new recoverable `FileQuotaExceededError(path, limit)` in `wenchang.errors`. Recoverable because the agent can repair it in the same turn (write into an existing file, or consolidate and delete), like `OversizeWriteError`. A new type rather than reusing `OversizeWriteError`, whose `size`/`limit` are bytes and whose advice ("split the content across multiple files") is the opposite of what the agent must do here.
- **Entity**: the storage prefix `{scope}/{entity_id}/` (`build_prefix(scope, entity_id)`). The same entity ID in two scopes is two entities. A key counts iff it is a well-formed memory path (`is_valid_path`) whose area is not `core.INDEX_SYSTEM_AREA` (`"system"`). Malformed keys do not count, since the agent can neither see nor delete them. `core` does not import `scope`; it uses its own `INDEX_SYSTEM_AREA`, already pinned equal to `scope.SYSTEM_AREA` by a test.
- **What is checked**: only `write_file` with `expected_version=None` creates a file, and only when the requested path's area is not `system`. `append_line` and `replace_fact` never create; `write_file` with a token replaces.
- **Race behavior**: soft cap. The count and the conditional put are not atomic, so concurrent creates under one entity that each count below the cap can all land, exceeding the cap by at most the number of creates racing at the boundary. Later creates then fail until the count drops below the cap.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A runaway agent cannot create unbounded files (Priority: P1)

An agent stuck in a loop keeps creating files. Once its entity holds the cap, further creates fail with an error telling it what to do instead.

**Independent Test**: A `MemoryStore` with a small cap; fill one entity to the cap; attempt one more create.

**Acceptance Scenarios**:

1. **Given** a `MemoryStore` with `max_files_per_entity=3` and entity `user/u1/` holding 3 non-`system/` files, **When** `write_file` creates a 4th path under `user/u1/notes/` (`expected_version=None`), **Then** it raises `FileQuotaExceededError` with `path` equal to the requested path and `limit == 3`, and nothing is stored at that path.
2. **Given** a store with cap 3 and `user/u1/` holding 2 non-`system/` files, **When** `write_file` creates a 3rd, **Then** it succeeds (the cap is inclusive: exactly `limit` counted files may exist).
3. **Given** a store with the default cap, **When** `max_files_per_entity` is read, **Then** it is `500` and equals `core.DEFAULT_MAX_FILES_PER_ENTITY`; **and Given** an entity holding 500 non-`system/` files under the default, **When** a 501st is created, **Then** `FileQuotaExceededError` with `limit == 500` is raised.

---

### User Story 2 - Existing files stay editable at the cap (Priority: P1)

**Acceptance Scenarios**:

1. **Given** an entity at the cap, **When** `write_file` replaces one of its files with the current version token, **Then** it succeeds.
2. **Given** an entity at the cap, **When** `append_line` appends to one of its files, **Then** it succeeds.
3. **Given** an entity at the cap, **When** `replace_fact` edits one of its files, **Then** it succeeds.
4. **Given** an entity at the cap, **When** `write_file` creates (`expected_version=None`) a path that already exists, **Then** it raises `VersionConflictError` carrying that file's current content and version (as it would below the cap), not `FileQuotaExceededError`.
5. **Given** an entity at the cap and a storage wrapper whose `get` of the requested path returns `None` (the file vanished between the count and the read), **When** `write_file` creates that path, **Then** it raises `FileQuotaExceededError`.
6. **Given** an entity at the cap and the requested path already holding an object with corrupt metadata (seeded directly into storage), **When** `write_file` creates that path, **Then** `MetadataFormatError` propagates; **and Given** that object's content is not valid UTF-8, **Then** `UnicodeDecodeError` propagates — the same as the existing conflict path.

---

### User Story 3 - Deleting a file frees a slot (Priority: P1)

**Acceptance Scenarios**:

1. **Given** an entity at the cap, **When** one file is deleted with `delete_file` and a new path is then created, **Then** the create succeeds and the entity again holds exactly `limit` counted files.

---

### User Story 4 - The limit is per entity and excludes `system/` (Priority: P1)

Each scenario starts with cap 3 on `user/u1/`.

**Acceptance Scenarios**:

1. **Given** `user/u1/` at the cap, **When** a file is created under `user/u2/`, **Then** it succeeds.
2. **Given** `user/u1/` at the cap, **When** a file is created under `project/u1/` (same entity ID, different scope), **Then** it succeeds.
3. **Given** `user/u1/` holding 2 `system/` files and 3 other files (spread over at least two areas), **When** a file is created under `user/u1/notes/`, **Then** `FileQuotaExceededError` is raised.
4. **Given** `user/u1/` holding 2 `system/` files and 2 other files, **When** a file is created under `user/u1/notes/`, **Then** it succeeds.
5. **Given** `user/u1/` holding 3 non-`system/` files, **When** `MemoryStore.write_file` creates `user/u1/system/x.md`, **Then** it succeeds.
6. **Given** `user/u1/` holding 2 well-formed non-`system/` files plus 2 keys under `user/u1/` that are not well-formed memory paths (seeded directly into storage), **When** a 3rd well-formed file is created, **Then** it succeeds.

---

### User Story 5 - The agent knows what to do next (Priority: P1)

**Acceptance Scenarios**:

1. **Given** `FileQuotaExceededError("user/u1/notes/new.md", 3)`, **When** it is rendered with `str()`, **Then** the text is exactly the literal message in plan.md; it never contains the entity ID `u1`. **And Given** an unparseable path, **Then** the text is exactly plan.md's fallback literal.
2. **Given** the error, **When** its category is read, **Then** it is `ErrorCategory.RECOVERABLE` and it is a `RecoverableError`.
3. **Given** a `MemoryTools` over an `InProcessClient` whose store has cap 1 and whose caller's entity in a writable scope holds 1 non-`system/` file, **When** the agent calls `write_file` for a new name, **Then** it raises `FileQuotaExceededError`, and `render_error` of it yields `error == "FileQuotaExceededError"`, `category == "recoverable"`, `limit == 1`, the `scope`, `area`, and `name` of the request, the full message, and no `path` key.
4. **Given** the reference adopter's seeds written with `seed_reference_memory` into a store whose cap is the number of non-`system/` seeds in the member's `user` entity plus 1 (2 + 1 = 3), **When** the member agent creates two new files in the `user` scope through `MemoryTools`, **Then** the first succeeds and the second raises `FileQuotaExceededError` with `limit == 3`.
5. **Given** the reference policy (organization scope role-gated to `admin`/`owner`), the member identity (role `member`), and the member's organization entity at the cap, **When** the agent calls `write_file` to create a file in the organization scope, **Then** it raises `RestrictedScopeError` with reason `ROLE_REQUIRED`, not `FileQuotaExceededError` (scope checks run before the cap).
6. **Given** an MCP server built with `register_memory_tools` over a store at the cap, **When** the agent calls the `write_file` tool to create a file, **Then** the `CallToolResult` has `isError` true and its structured content has `error == "FileQuotaExceededError"` and `limit` equal to the cap.
7. **Given** `tool_descriptions()["write_file"]`, **When** read, **Then** it contains one sentence stating that creating a file fails once the scope holds its file limit, with what to do instead, next to the byte-ceiling sentence.

---

### User Story 6 - Adopters configure or disable the cap (Priority: P2)

**Acceptance Scenarios**:

1. **Given** `MemoryStore(storage, max_files_per_entity=None)`, **When** more than 500 files are created under one entity, **Then** every create succeeds and the property reads `None`.
2. **Given** `max_files_per_entity=0` or `-1`, **When** `MemoryStore` is constructed, **Then** it raises `ValueError("max_files_per_entity must be positive or None")`.
3. **Given** `FileQuotaExceededError(path, 0)` or `(path, -1)`, **When** constructed, **Then** it raises `ValueError("limit must be positive")`.

---

### User Story 7 - The limit is recorded (Priority: P2)

**Acceptance Scenarios**:

1. **Given** `docs/adr/`, **When** listed, **Then** ADR 0039 records the cap, its default, the entity definition and the `system/` exclusion, the error choice, the counting cost, the soft-cap race behavior, and the conformance-suite gap; **and** ARCHITECTURE.md's `core` and `errors` entries, key invariants, and error taxonomy describe the limit; **and** `docs/product/glossary.md` has a "File cap (`max_files_per_entity`)" entry.

### Edge Cases

- Check order in `write_file` is unchanged up to the cap check: invalid path, empty `source`, oversize, then (create, non-`system/` area only) the cap. An oversize create at the cap raises `OversizeWriteError`. At the tool layer, `scope.check_write` runs before the client, so `system/` and role rejections win over the cap.
- The cap check counts with `Storage.list_page`, not `MemoryStore.list_prefix`, so corrupt metadata on another file never blocks a create and a subclass override cannot change the count.
- Counting requests pages of `max(limit - count, list_page_size)` keys and stops as soon as `limit` counted keys are seen. Keys listed per create are at most `limit` + the uncounted keys (`system/` and malformed) under the prefix + one page's overshoot (`list_page_size`).
- Listing is not a snapshot; a delete or create racing the count may be missed. The cap is soft (see Decisions).
- The transport conformance suite is unchanged. `FileQuotaExceededError` is covered by the transport error-parity contract but not exercised by the suite, which has no cap fixture; ADR 0039 records the gap.
- Lowering the cap below an entity's current count blocks creates until files are deleted below the new cap; existing files are never removed.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `MemoryStore.__init__` MUST accept keyword-only `max_files_per_entity: int | None = DEFAULT_MAX_FILES_PER_ENTITY`, where `core.DEFAULT_MAX_FILES_PER_ENTITY: int = 500`; a non-`None` value `<= 0` MUST raise `ValueError("max_files_per_entity must be positive or None")`, checked after the existing `index_max_bytes` positivity check. There is no type check: `bool` is not rejected (`True` is a cap of 1), matching `max_file_bytes`. A read-only property `max_files_per_entity` MUST return the configured value.
- **FR-002**: `write_file` with `expected_version=None`, a non-`None` cap, and a requested path whose area is not `INDEX_SYSTEM_AREA` MUST, after the path, `source`, and size checks and before the conditional put, count the counted keys (well-formed, area not `system`) under `build_prefix(scope, entity_id)` via `Storage.list_page`. If the count is `>= limit` it MUST `get` the requested path: if an object exists, decode its content as UTF-8 and run `metadata_from_map` on its metadata (in that order, as on the existing conflict path, so `UnicodeDecodeError` and `MetadataFormatError` propagate) and raise `VersionConflictError(path, content, version)`; if none exists, raise `FileQuotaExceededError(path, limit)`. Nothing is stored in either case.
- **FR-003**: `write_file` with a version token, creates under `system/`, `append_line`, `replace_fact`, `delete_file`, and all reads MUST NOT consult the cap.
- **FR-004**: `wenchang.errors.FileQuotaExceededError(path: str, limit: int)` MUST be a `RecoverableError` exposing `path` and `limit`, raising `ValueError("limit must be positive")` for `limit < 1`, with the exact messages in plan.md.
- **FR-005**: `tools.render_error` MUST render the new error with its `limit` and location and no path (no code change expected: `limit` is already a rendered payload field). The `write_file` tool docstring MUST gain one sentence about the cap beside the byte-ceiling sentence.
- **FR-006**: ADR 0039, ARCHITECTURE.md, and `docs/product/glossary.md` MUST record the limit.

## Success Criteria *(mandatory)*

- **SC-001**: Every acceptance scenario above has a passing test; `make check` is green.
- **SC-002**: `make test-integration` is green (the cap uses `Storage.list_page`, which `GcsStorage` implements).

## Assumptions

- No current test or eval writes more than 500 non-`system/` files under one entity (checked: the largest is 101 in `tests/test_core_list_prefix.py`).
- The prompt is not changed: the error text and the `write_file` docstring carry the next action.
