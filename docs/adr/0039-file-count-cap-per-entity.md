# 0039. File-count cap per entity

Date: 2026-10-30

## Status

Accepted.

## Context

The only write limit was the per-file byte ceiling (`max_file_bytes`, 16 KiB).
Nothing bounded how many files one user or project could hold, so an agent
stuck in a loop could create thousands of files. The cap had to reject new
files past a limit while leaving existing files editable, and tell the agent
what to do instead.

## Decision

1. **A `MemoryStore` setting, enforced in `core`.** `max_files_per_entity: int
   | None = DEFAULT_MAX_FILES_PER_ENTITY` (500) is a keyword argument beside
   `max_file_bytes`, exposed as a read-only property. `None` disables the cap;
   a non-`None` value `<= 0` raises `ValueError("max_files_per_entity must be
   positive or None")` after the `index_max_bytes` check. There is no type
   check, so `True` is a cap of 1, as for `max_file_bytes`. Enforcing in
   `core` means every transport, and any remote server wrapping a
   `MemoryStore`, applies it identically. The tool layer has no logic change;
   the `write_file` docstring gains one sentence.
2. **The entity is the prefix `{scope}/{entity_id}/`.** The same entity ID in
   two scopes is two entities. A key counts iff it is a well-formed memory
   path whose area is not `system`. `system/` files are excluded from the
   count and creates under `system/` are never checked: the agent cannot
   delete or merge them, so a quota error would give it nothing to do; the
   cap targets runaway agent writes; and seeding writes `system/` through
   `write_file(expected_version=None)`. Malformed keys do not count, since the
   agent can neither see nor delete them. `core` uses its own
   `INDEX_SYSTEM_AREA` rather than importing `scope`.
3. **Only creates are checked.** `write_file` with `expected_version=None`
   checks, after the path, empty-`source`, and size checks and before the
   conditional put. A replace with a token, `append_line`, `replace_fact`,
   `delete_file`, and all reads never consult the cap. The cap is inclusive:
   exactly `limit` counted files may exist.
4. **At the cap, an existing path is a conflict.** The store reads the
   requested path. If an object exists, it decodes the content and parses the
   metadata (so `UnicodeDecodeError` and `MetadataFormatError` propagate as
   on the existing conflict path) and raises `VersionConflictError` with the
   current content and version, the same result as below the cap. If none
   exists, including a file deleted after the count, it raises
   `FileQuotaExceededError`. Nothing is stored either way.
5. **A new recoverable error.** `FileQuotaExceededError(path, limit)` exposes
   `path` and `limit`, and `limit < 1` raises `ValueError`. Its message names
   the location (scope, area, name) and the limit, says `system/` files are
   not counted, and tells the agent to add to an existing file (`append_line`,
   `replace_fact`, or `write_file` with that file's version) or merge files and
   delete the extras with `delete_file`, then retry. It is recoverable because
   the agent can repair it in the same turn. `render_error` already renders
   `limit` and the location.
6. **Counting through `Storage.list_page`.** The store pages through the
   entity prefix in pages of `max(limit - count, list_page_size)` keys,
   stopping once `limit` counted keys are seen or a short page ends the
   listing. Keys listed per create are at most `limit` plus the uncounted
   keys under the prefix plus one page (`list_page_size`). It does not use
   `MemoryStore.list_prefix`, so corrupt metadata on another file never blocks
   a create and a `list_prefix` override cannot change the count.
7. **The cap is soft.** The count and the conditional put are not atomic, so
   concurrent creates that each count below the cap can all land, exceeding
   it by at most the number racing at the boundary. Later creates fail until
   the count drops below the cap.
8. **The transport conformance suite is unchanged.** `FileQuotaExceededError`
   falls under the transport error-parity contract but no conformance case
   exercises it: the suite has no cap fixture, and adding a required fixture
   would break every adopter's existing suite.

## Consequences

- A runaway agent stops at 500 files per entity by default and is told how
  to continue. Adopters can raise, lower, or disable the cap.
- Every non-`system/` create lists the entity's keys before writing, up to
  the bound above; the first page requests `max(limit, list_page_size)`
  keys, so an entity with no uncounted keys before the limit is reached
  takes one `list_page` call. Replaces, edits, deletes, and reads cost
  nothing extra.
- Lowering the cap below an entity's current count blocks creates until files
  are deleted below it; existing files are never removed.
- Storage stubs that create files must implement `list_page`, since the
  default cap calls it before every non-`system/` create.
- A remote transport that drops or reshapes `FileQuotaExceededError` is not
  caught by the conformance suite.

Rejected:

- **Enforce in the tool layer.** A remote server or a direct `MemoryStore`
  caller would bypass it.
- **Reuse `OversizeWriteError`.** Its `size` and `limit` are bytes, and its
  advice ("split the content across multiple files") is the opposite of what
  the agent must do here.
- **Count `system/` files.** A seeded entity could start at or near the cap,
  and the agent could not free a slot by deleting curated files.
- **Count through `list_prefix` or the index.** Corrupt metadata elsewhere
  would block creates, and the index cache is separate work.
- **Raise `FileQuotaExceededError` for an existing path at the cap.** A
  create-on-existing is a conflict whether or not the entity is full; the
  conflict carries the content the agent needs.
- **A hard cap.** It needs an atomic count and put across objects, which the
  `Storage` protocol does not offer; a soft cap was accepted if documented.
- **A required cap fixture in the conformance suite.** It would break every
  adopter's existing suite.
