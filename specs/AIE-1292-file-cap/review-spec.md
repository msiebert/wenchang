# Spec Review: AIE-1292 — Cap the number of files per entity

## What & why

Nothing bounds how many files an agent can create, so a looping agent could write thousands. `MemoryStore` gains `max_files_per_entity` (default 500, `None` disables). Creating a file past the cap fails with a recoverable error telling the agent to write into an existing file or consolidate and delete; edits to existing files, deletes, and `system/` content are unaffected.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | cap 3, entity holds 3 non-system files | `write_file` creates a 4th | `FileQuotaExceededError(path, limit=3)`, nothing stored |
| 2 | cap 3, entity holds 2 | create a 3rd | succeeds (inclusive cap) |
| 3 | default store | read setting / create 501st | `500` / quota error |
| 4 | entity at cap | replace, `append_line`, `replace_fact` on an existing file | succeed |
| 5 | entity at cap | create on a path that exists / vanished / corrupt | `VersionConflictError` / quota error / decode or metadata error propagates |
| 6 | entity at cap | delete one, then create | succeeds |
| 7 | `user/u1/` at cap | create under `user/u2/` or `project/u1/` | succeeds |
| 8 | 2 system + 3 / 2 other files; 3 others then a `system/` create; malformed keys | create | quota / succeeds / succeeds / malformed keys not counted |
| 9 | the error | `str()` / category / `render_error` / MCP | exact literal text naming tools, no entity ID; recoverable; `limit` + scope/area/name, no path; `isError` with `limit` |
| 10 | reference seeds, cap = 2 non-system user seeds + 1 | agent creates two files | first succeeds, second quota error |
| 11 | role-gated scope, caller lacks role, entity at cap | tool create | `RestrictedScopeError(ROLE_REQUIRED)` |
| 12 | `None` / `0` / `-1` | construct / create >500 | unlimited / `ValueError` |
| 13 | docs | — | ADR 0039, ARCHITECTURE.md, glossary entry; `write_file` docstring sentence |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| `MemoryStore(max_files_per_entity=...)`, enforced in `core` | Tool-layer check; a `MemoryTools` arg | Core enforcement covers every transport and a future remote server, matching `max_file_bytes` |
| New recoverable `FileQuotaExceededError(path, limit)` | Reuse `OversizeWriteError`; make it permanent | Oversize's fields are bytes and its advice ("split across files") is the opposite; the agent can fix this in-turn |
| Entity = `{scope}/{entity_id}/`; `system/` excluded from count and enforcement; malformed keys not counted | Count `system/`; count raw keys | Agent can't delete or merge `system/` or malformed keys; seeding writes `system/` via create (orchestrator decision) |
| Only `write_file(expected_version=None)` outside `system/` is checked | Check every write | Only creates add files |
| At cap, an existing path gives `VersionConflictError`; a vanished one gives the quota error | Always quota error | Same outcome as below the cap; the agent should merge, not delete |
| Count via `Storage.list_page`, pages of `max(limit - count, list_page_size)`, stop at `limit` | `list_prefix`; `limit - count` pages; AIE-1293 cache | Corrupt metadata elsewhere can't block creates; no one-key list calls; no sibling dependency |
| Soft cap under concurrency | Lock/marker object for a hard cap | Human accepted soft; overshoot bounded by concurrent creates at the boundary |
| Conformance suite unchanged; gap recorded in ADR | Add a cap fixture + cases | A new required fixture would break adopters' suites; the error is in the parity contract but not exercised |

## Files/modules to be touched

- `src/wenchang/errors.py`, `src/wenchang/core.py`, `src/wenchang/tools.py` (docstring only)
- `tests/` (errors, new `test_core_file_cap.py`, tools, tool descriptions, MCP server, one integration test)
- `ARCHITECTURE.md`, `docs/adr/0039-file-count-cap-per-entity.md`, `docs/product/glossary.md`

## Open questions / assumptions

- The prompt is unchanged; the error text and the `write_file` docstring carry the next action.

## Risks

- Each create lists up to `limit` + uncounted keys + one page (≈1 GCS list call at 500); acceptable at memory-write rates, and AIE-1293's cache could later replace it.
- Agents told to "retry without asking the user" may delete memory to make room; the message steers toward merging first.
