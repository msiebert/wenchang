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
- Conformance mixins (`wenchang.testing`, `[testing]` extra) for checking an
  adopter's identity resolver and transport client.
- Supports Python 3.11 and newer.

[Unreleased]: https://github.com/msiebert/wenchang/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/msiebert/wenchang/releases/tag/v0.1.0
