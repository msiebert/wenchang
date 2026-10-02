# Glossary

Terms as used throughout wenchang and its spec.

- **Fact** — one line of markdown, carrying a leading bracketed confidence
  label (`[stated]`, `[observed]`, `[inferred]`, `[system]`) and nothing
  else. No per-line author or timestamp.
- **File** — a markdown document about one subject, carrying the four
  metadata fields and a version token, capped in size (default 16 KB).
- **Area** — a folder grouping files by subject matter within a scope
  (e.g. `preferences`, `taxonomy`). Adopter-seeded, agent-extensible.
- **Scope** — a named visibility tier keyed by an entity ID (e.g. user,
  project, organization). Scopes are flat siblings, arbitrary in number and
  name, entirely adopter-defined; the library privileges none of them.
- **Entity ID** — the identifier naming a scope's instance (e.g. a specific
  user ID or project ID), supplied by the identity resolver.
- **Role** — the caller's permission level within a given scope, returned
  by the identity resolver as part of a scope grant, checked against
  write-restricted scopes before any mutating call proceeds. An opaque,
  non-empty, adopter-defined string; every granted scope carries exactly
  one. Roles compare by exact, case-sensitive equality with no hierarchy
  (`Admin` is not `admin`, and `owner` does not imply `admin`), so a scope
  policy lists every permitted role explicitly.
- **Write-restricted scope** — a scope listed in the adopter's scope policy,
  which only callers holding one of its permitted roles may write (e.g.
  organization writes limited to admin or owner). The only scope property
  the library understands; any scope name may be restricted, and none is
  special-cased. A write by a caller without a permitted role is rejected
  with a permanent `RestrictedScopeError(ROLE_REQUIRED)` listing the
  permitted roles. Reads and listing are never restricted.
- **Scope policy** — `scope.ScopePolicy`, the adopter's startup
  configuration mapping each write-restricted scope to its set of permitted
  roles. A scope absent from the policy is unrestricted, so any granted
  role may write it. Keys must match the resolver's scope names exactly; a
  key that matches no scope restricts nothing. Immutable and validated at
  construction.
- **Not granted** — the permanent rejection
  (`RestrictedScopeError(NOT_GRANTED)`) of a write whose path lies outside
  the caller's identity: its scope has no grant, or its entity ID differs
  from the caller's entity ID in that scope. Checked before the role, so a
  permitted role never opens another entity's prefix. One generic message
  covers both cases and never reveals the caller's own entity ID or role.
  Unreachable through the tools, which build every path from the caller's
  own grant.
- **Identity resolver** — the adopter-injected dependency that turns
  caller credentials (opaque to the library) into an identity, or reports a
  resolution failure. It must not raise, and identical credentials must
  give an equal result within a session. The library calls it only through
  `resolve_identity`.
- **Identity** — what a resolver returns: the caller's scope grant in each
  scope it can reach, keyed by scope name. Immutable and validated at
  construction; an identity with no grants is valid and reaches no scope.
- **Scope grant** — the caller's entity ID and role within one scope. The
  entity ID, like the scope name it is keyed by, must be a valid path
  segment.
- **Resolution failure** — a resolver's report that credentials could not be
  resolved, carrying a non-empty detail shown to the agent that must never
  contain credentials. Always permanent: the library converts it into
  `ResolverFailureError`, and memory is unavailable for the session.
- **Sandbox resolver** — the reference identity resolver, returning one
  adopter-supplied identity for any credentials; for sandboxes and tests.
- **Conformance suite** — an executable test suite the library ships for an
  interface the adopter implements; passing it defines a correct
  implementation. For the identity resolver it is
  `wenchang.testing.ResolverConformance`, a pytest mixin the adopter
  subclasses, installed with the `wenchang[testing]` extra; for the
  transport client it is the transport conformance suite.
- **Transport conformance suite** — the conformance suite for transport
  clients, `wenchang.testing.TransportConformance`. It runs the same cases
  against any transport client (in-process or remote) and fails one that is
  distinguishable from the in-process client in results or errors,
  covering round-trip fidelity, atomicity, token opacity, conflicts,
  replace-fact matching, append guarding, enforcement, index behavior, and
  error parity, including core's exact wording for argument errors. On
  enforcement it requires a transport to *accept* a `system/` write: scope
  rules are enforced by the tools, not the transport. It never
  compares version tokens, only hands them back. The adopter supplies a
  fresh client per test plus the settings its store was configured with;
  every scope in the supplied scope map must be writable through that
  client, and its writes must stamp strictly increasing last-updated times.
- **Conformance sentinel** — a small file the transport conformance suite
  writes under the first mapped scope's own entity, in area
  `conformance-sentinel`, at the start of every test that touches the
  store. Finding it already present means the client fixture was shared
  between tests, which fails the test as not isolated.
- **Known roles** — the conformance-suite fixture listing every role the
  adopter's resolver may return. The suite requires every granted role, and
  every role the scope policy permits, to be in it, so write-restriction
  checks are decidable and a role typo is caught. A known role the policy
  never mentions (e.g. `member`) is legitimate.
- **Expected scopes** — the conformance-suite fixture naming exactly the
  scopes the adopter's valid test credentials must grant, so a resolver
  that silently drops a scope fails.
- **Version token / generation** — an opaque handle representing a file's
  current state, used for optimistic concurrency (compare-and-swap on
  write). Currently backed by a GCS object generation number; callers never
  parse, compare, or order it.
- **Memory index** — the merged, metadata-only view across a set of scopes,
  returned by `get_memory_index` for session bootstrap, subject to a byte
  cap (default 64 KB, the store's `index_max_bytes`) and a documented
  priority ordering: `system/` areas first, then scopes in the adopter's
  scope priority with unlisted scopes as one trailing tier, then most
  recently updated first, then by path. Each entry costs
  `core.index_entry_bytes`: the UTF-8 bytes of its path, its canonical
  metadata, and its version. The cap is inclusive and is applied as a
  prefix of the order: entries are included until the next one would not
  fit, and every entry from there on is omitted. Represented by
  `core.MemoryIndex`: the entries in load order, plus the capped prefixes;
  no capped prefixes means the index is complete.
- **Capped prefix** — an area prefix (`scope/entity_id/area/`) the memory
  index could not return in full once its byte cap was reached, with a
  count of the files left out (`core.CappedPrefix`), listed in prefix
  order. The agent can list that prefix to page through them.
- **Scope priority** — the adopter's optional ordering of scope names for
  the memory index, set when the store is constructed. Listed scopes rank
  ahead of unlisted ones, in list order; by default it is empty and every
  scope ranks equally, ordered by recency. It never affects `system/`
  areas, which always load first.
- **Transport client** — the object the tool layer calls to reach memory,
  implementing `transport.TransportClient`: the core API's operations with
  identical signatures and identical errors, over any transport (in-process
  or remote). It carries no identity per call; a remote client
  authenticates once, when it is constructed.
- **In-process client** — `transport.InProcessClient`, the transport client
  that calls a `MemoryStore` directly with no network hop, passing every
  call and result through unchanged; the simplest adoption path and the
  reference implementation. A `MemoryStore` can also be used as a
  transport client directly.
- **Tool layer** — the agent-facing verbs (`get_memory_index`,
  `read_file`, `list_prefix`, `write_file`, `append_line`, `replace_fact`,
  `delete_file`), implemented as `tools.MemoryTools` over a transport
  client. Tools carry no judgment; each one's docstring is the description
  the agent sees. Mutating tools check the write (`system/` read-only,
  write restriction) before the transport sees it. Framework-agnostic: a
  host adapter mounts the tools and renders results and errors with
  `render_result` / `render_error`.
- **Session binding** — resolving the caller's identity once, at session
  start, with `tools.bind_tools`, which returns that session's
  `MemoryTools`. It is the only place credentials pass through the tool
  layer, and they are not retained. The identity and the calling surface's
  `source` name are then fixed for the session.
- **Scope-relative address** — how the agent names a file to the tools:
  `(scope, area, name)`, with `name` excluding `.md`. The tool fills in the
  caller's own entity ID for that scope, so the agent never types an entity
  ID and reaches only its own entity in each granted scope. A memory path
  `scope/<entity>/area/name.md` from the index or a listing maps to
  `read_file(scope, area, name)`. A scope the session isn't granted is a
  recoverable error listing the available scopes. `area` must be a
  lowercase ASCII slug (`^[a-z0-9][a-z0-9_-]*$`), so no lookalike of
  `system` can be addressed; `name` may be any Unicode title without
  invisible format characters, line or paragraph separators, or
  noncharacters. Core paths are broader; this narrowing is the tools' own.
- **Description** — a file's one-line human-readable summary; part of the
  metadata-only search surface.
- **Aliases** — a file's list of alternate names, nicknames, acronyms, and
  phrasings; the other half of the metadata-only search surface used to
  find an existing file before creating a duplicate.
- **System area (`system/`)** — a read-only-to-the-agent area within any
  scope, holding content a human deliberately curated; enforced at the
  tool layer by `scope.check_not_system`, which rejects any write whose area
  segment is exactly `system`, for every caller regardless of role. The
  tool layer applies it through `scope.check_write`, before the grant and
  role checks.
  Refreshed only by wholesale prefix rewrite through `core`, which does not
  apply the check.
- **Seed areas** — the starting set of area names an adopter configures per
  scope; a starting shape the agent is free to extend.
- **Systems of record** — data that already has a canonical home in the
  adopter's product (e.g. an event catalog, a dashboard object); memory
  references and annotates these rather than duplicating them.
- **Sources** — a file-level metadata field recording which calling
  surfaces have written to the file; free-form strings, not an enum.
- **Confidence label** — one of `stated`, `observed`, `inferred`, `system`,
  marking how a fact came to be known.
- **Body line** — a parsed line of a file's body: either a fact, or a
  verbatim non-fact line (heading, blank line, prose) tolerated by the
  parser but not part of the format presented to the agent.
- **Metadata map** — the flat string-to-string map holding a file's
  metadata as GCS custom object metadata, keyed by `description`,
  `aliases`, `sources`, `last-updated`.
- **Memory path** — a file's address, `{scope}/{entity_id}/{area}/{name}.md`,
  relative to the storage root; exactly four non-empty segments, checked
  only syntactically.
- **Name** — a file's stem: the last segment of its memory path without the
  final `.md`. `.md` is always appended when a path is built, so a name may
  itself end in `.md` (`notes.md` is stored as `notes.md.md`).
- **Prefix** — a memory path's leading 1-3 segments followed by `/` (e.g.
  `scope/`, `scope/entity_id/`), naming a scope, entity, or area for
  `list_prefix` to recurse under; segment-aligned, so it never cuts a
  segment in half.
- **Cursor** — an opaque token returned by `list_prefix` alongside a page of
  results, passed back to resume listing after the last entry seen; callers
  never parse it, the same as a version token.
- **Storage root** — the base a memory path is relative to; one storage
  instance (for GCS, one bucket).
- **Recoverable error** — an error category whose instance carries its own
  repair material (e.g. current content and version); the caller corrects
  and retries in the same turn without asking the user. Includes
  `InvalidArgumentError`, the tool layer's rejection of an agent-supplied
  argument, which names the argument to correct.
- **Permanent error** — an error category signaling the call cannot succeed
  as given; the caller must stop and not retry.
- **Transient error** — an error category signaling a temporary condition
  where retrying is appropriate; a version-guarded retry safely degrades to
  a recoverable version conflict if the first attempt actually landed.
