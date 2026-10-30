# Spec Review: AIE-1292 — Cap the number of files per entity

## What & why

Nothing bounds how many files an agent can create, so a looping agent could write thousands. `MemoryStore` gains `max_files_per_entity` (default 500, `None` disables). Creating a file past the cap fails with a recoverable error telling the agent to write into an existing file or consolidate and delete; edits to existing files, and deletes, are unaffected.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | cap 3, entity holds 3 files | `write_file` creates a 4th | `FileQuotaExceededError(path, limit=3)`, nothing stored |
| 2 | cap 3, entity holds 2 | create a 3rd | succeeds (inclusive cap) |
| 3 | default store | read setting / create 501st | `500` / quota error |
| 4 | entity at cap | replace, `append_line`, `replace_fact` on an existing file | succeed |
| 5 | entity at cap | create on a path that exists | `VersionConflictError`, not quota |
| 6 | entity at cap | delete one, then create | succeeds |
| 7 | `user/u1/` at cap | create under `user/u2/` or `project/u1/` | succeeds |
| 8 | files spread over areas incl. `system/`; or malformed keys under the prefix | create | all well-formed paths count; malformed keys don't |
| 9 | the error | `str()` / category / `render_error` | exact actionable text naming tools, no entity ID; recoverable; `limit` + scope/area/name, no path |
| 10 | `None` / `0` / `-1` | construct / create >500 | unlimited / `ValueError` |
| 11 | docs | — | ADR 0039 + ARCHITECTURE.md record the limit |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| `MemoryStore(max_files_per_entity=...)`, enforced in `core` | Tool-layer check; a `MemoryTools` arg | Core enforcement covers every transport and a future remote server, matching `max_file_bytes` |
| New recoverable `FileQuotaExceededError(path, limit)` | Reuse `OversizeWriteError`; make it permanent | Oversize's fields are bytes and its advice ("split across files") is the opposite; the agent can fix this in-turn, so recoverable |
| Entity = `{scope}/{entity_id}/`, all areas incl. `system/`, well-formed keys only | Exclude `system/`; count raw keys | The cap bounds storage per entity; malformed keys are invisible and undeletable to the agent |
| Only `write_file(expected_version=None)` is checked | Check every write | Only creates add files |
| At cap, an existing path gives `VersionConflictError` | Always quota error | Same outcome as below the cap; the agent should merge, not delete |
| Count via `Storage.list_page`, stop at `limit` | `list_prefix`; AIE-1293 cache | Corrupt metadata elsewhere can't block creates; no dependency on the sibling issue; ≤ `limit` keys listed |
| Soft cap under concurrency | Lock/marker object for a hard cap | Human accepted soft; overshoot is bounded by concurrent creates at the boundary |
| Conformance suite unchanged | Add a cap fixture + cases | A new required fixture would break adopters' suites; parity contract already covers the error |

## Files/modules to be touched

- `src/wenchang/errors.py`, `src/wenchang/core.py`
- `tests/` (errors, new `test_core_file_cap.py`, tools render, one integration test)
- `ARCHITECTURE.md`, `docs/adr/0039-file-count-cap-per-entity.md`

## Open questions / assumptions

- Should `system/` files count? Spec says yes; if seeded `system/` content is large in some deployment, adopters raise the cap.
- Tool docstrings and prompt unchanged; the error text carries the next action.

## Risks

- Each create lists up to 500 keys (≈1 GCS list call with `max_results` paging); acceptable at memory-write rates, and AIE-1293's cache could later replace it.
- Agents told to "retry without asking the user" may delete memory to make room; the message steers toward merging first.
