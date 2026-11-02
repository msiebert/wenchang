# Changelog

All notable changes to wenchang are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
the policy in [docs/releasing.md](docs/releasing.md).

## [Unreleased]

## [0.1.0] - 2026-10-30

First tagged release.

### Added

- `MemoryStore` (`wenchang.core`): a virtual filesystem of markdown memory
  files with metadata, per-file size limits, and optimistic concurrency.
  Every write names the version it read; a stale version returns the current
  content and version so the caller can merge and retry.
- Seven memory tools: `get_memory_index`, `read_file`, `list_prefix`,
  `write_file`, `append_line`, `replace_fact`, and `delete_file`.
  `get_memory_index` returns a size-capped startup index of every file's
  metadata, ordered by an optional scope priority.
- Storage behind one interface (`wenchang.storage`): `GcsStorage` for Google
  Cloud Storage and `InMemoryStorage` for tests and local use.
- Identity and authorization: `IdentityResolver`, scopes, a read-only
  `system/` area, and a write policy enforced on every call.
- Transport layer (`wenchang.transport`) with an in-process client, and a
  tool layer (`wenchang.tools`) that binds the tools per session, with tool
  descriptions that name the adopter's product.
- Prompt layer (`wenchang.prompts`): a generic memory prompt assembled from
  four adopter slots (`purpose`, `scope_guidance`, `seed_areas`, optional
  `systems_of_record`).
- MCP adapter (`wenchang.mcp`, `[mcp]` extra): serves the tools and the
  memory prompt from an MCP server, or adds them to an existing one.
- Tool-call observer (`wenchang.observer`): `bind_tools(..., on_call=...)`
  and the MCP adapter deliver a `ToolCallRecord` after every tool call.
- A per-entity file cap: `MemoryStore(max_files_per_entity=500)` limits
  creates under `{scope}/{entity_id}/` (excluding `system/`) and raises the
  recoverable `FileQuotaExceededError` at the cap. `None` disables it.
- Optional index cache (`wenchang.index_cache`): `IndexCache` caches each
  entity's listing for `get_memory_index` in an adopter-supplied store such
  as Redis, with generation-token invalidation on every write;
  `MemoryStore.invalidate_index` for writers that bypass the store, and
  `InMemoryIndexCache` for tests.
- Operator-only `MemoryStore.purge(scope, entity_id)` and
  `MemoryStore.export(scope, entity_id)` to erase or export everything stored
  for one entity.
- Exported tool schemas (`wenchang.schemas`): `tool_schemas()` and
  `error_schema()` return JSON Schema for every tool's input, output, and
  error payload, for registering the tools with non-MCP frameworks.
- Conformance mixins (`wenchang.testing`, `[testing]` extra) for checking an
  adopter's identity resolver and transport client.
- Supports Python 3.11 and newer.
- Documentation site at <https://msiebert.github.io/wenchang/>, organized by
  integration path (new MCP server, existing MCP server, no MCP), with
  `llms.txt` for agents.

[Unreleased]: https://github.com/msiebert/wenchang/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/msiebert/wenchang/releases/tag/v0.1.0
