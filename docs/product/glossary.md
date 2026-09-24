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
  by the identity resolver, checked against write-restricted scopes before
  any mutating call proceeds.
- **Version token / generation** — an opaque handle representing a file's
  current state, used for optimistic concurrency (compare-and-swap on
  write). Currently backed by a GCS object generation number; callers never
  parse, compare, or order it.
- **Memory index** — the merged, metadata-only view across a set of scopes,
  returned by `get_memory_index` for session bootstrap, subject to a byte
  cap (default 64 KB) and a documented priority ordering.
- **Description** — a file's one-line human-readable summary; part of the
  metadata-only search surface.
- **Aliases** — a file's list of alternate names, nicknames, acronyms, and
  phrasings; the other half of the metadata-only search surface used to
  find an existing file before creating a duplicate.
- **System area (`system/`)** — a read-only-to-the-agent area within any
  scope, holding content a human deliberately curated; enforced at the
  tool layer, refreshed only by wholesale prefix rewrite.
- **Seed areas** — the starting set of area names an adopter configures per
  scope; a starting shape the agent is free to extend.
- **Systems of record** — data that already has a canonical home in the
  adopter's product (e.g. an event catalog, a dashboard object); memory
  references and annotates these rather than duplicating them.
- **Sources** — a file-level metadata field recording which calling
  surfaces have written to the file; free-form strings, not an enum.
- **Confidence label** — one of `stated`, `observed`, `inferred`, `system`,
  marking how a fact came to be known.
