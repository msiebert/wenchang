# Concepts

How wenchang addresses and versions memory files, and the limits it enforces. These hold on every integration path. For the tools themselves see the [reference](reference.md); for how files are stored in GCS see [Storage and operations](storage.md).

## Path shape

Every memory file is stored at

```
{scope}/{entity_id}/{area}/{name}.md
```

For example `project/p-ninth-examination/characters/lin-qiao.md`. Agents never write the path. The tools take `(scope, area, name)` and the tool layer fills in `entity_id` from the caller's identity grant for that scope, so a caller can only reach its own entities. Results name a file by its `scope`, `area`, and `name`; they never include the storage path.

An **entity** is everything under one `{scope}/{entity_id}/` prefix: one user's private memory, or one project's shared memory.

## Scopes

A scope is an adopter-defined visibility tier. The library defines no scope names; a typical set is `user` (private), `project` (shared), and `organization` (shared, writes need an admin or owner role). A scope must be one of the scopes the session's identity has a grant for; otherwise the call fails with an `InvalidArgumentError` listing the available scopes. See [Identity and multi-tenant auth](identity.md) for how grants are made.

## Areas

An area groups files within a scope. The tool layer requires an area to be a lowercase slug matching `^[a-z0-9][a-z0-9_-]*$`. Areas are created implicitly by writing a file in them. The prompt's `seed_areas` slot suggests starting areas; the agent may create more.

## Names

A name is the file's stem, passed without `.md`. It must be a valid path segment: non-empty, not `.` or `..`, with no `/`, backslash, or control character, and the tool layer additionally rejects invisible, separator, and noncharacter code points. Names must be valid UTF-8.

## The system/ area

Every scope has an area named exactly `system`. It holds curated content that people maintain and replace wholesale. The agent can read it (any area may be read) but every mutating tool refuses it with `RestrictedScopeError` (reason `system_read_only`). Seeding jobs and admin tooling write it through the core `MemoryStore`, which applies no restrictions; see [Seed curated content](quickstart.md#seed). In the startup index, `system/` entries come first across all scopes.

## Fact lines

A memory file body is made of fact lines, one per line:

```
- [stated] Has grey eyes.
```

The pattern is `- [<label>] <text>` with a non-empty text. The label records how the fact is known:

| Label | Meaning |
| --- | --- |
| `stated` | The user told the agent directly. |
| `observed` | The agent saw it in a tool result, session data, or behavior. |
| `inferred` | The agent concluded it from a pattern across several observations. |
| `system` | Curated content. The prompt tells the agent never to write a new `[system]` line. |

`append_line` accepts only a single well-formed fact line. Other lines in a body are tolerated and preserved verbatim. An end date, if the user states one, is written into the fact's text as prose; there are no per-fact timestamps.

## File metadata

Each file carries four metadata fields, stored beside the body as custom metadata on the stored object, not inside the markdown. Tool results and the index show them under these names; [Storage and operations](storage.md#metadata) gives the stored keys and encodings.

| Field | Type | Behavior |
| --- | --- | --- |
| `description` | string, one line | What the file is about. Part of the agent's search surface. `write_file` replaces it; `append_line` and `replace_fact` replace it only if one is passed. |
| `aliases` | list of strings, ordered | Other names the subject is looked up by. `write_file` replaces the whole set; `append_line` and `replace_fact` add new aliases, keeping existing ones and their order. |
| `sources` | set of strings | Surface names (the `source` you configure) that have written the file. Only ever grows; returned sorted. |
| `last_updated` | UTC timestamp | Set by the store's clock on every write; rendered as ISO 8601 with a `Z` suffix. |

There is no content search. `description` and `aliases` are the entire search surface; the agent reads the index and matches on them.

## Optimistic concurrency

Every file has an opaque `version` (the GCS generation under `GcsStorage`). Every mutating tool takes `expected_version`, the version the agent read; the write succeeds only if the file is still at that version. `write_file` with `expected_version=null` creates the file and fails if it already exists. A mismatch returns a recoverable `VersionConflictError` carrying the current content and version.

`replace_fact` re-reads and retries up to three times when a concurrent write races it, re-checking the match each time; if the file's version moved but `old_string` still matches exactly once, it applies against the current content. `append_line` has no automatic re-apply: a stale version is a conflict. Versions are opaque: never parse, compare, or order them.

## Limits

| Limit | Default | Where set |
| --- | --- | --- |
| Per-file content size | 16384 bytes (UTF-8) | `MemoryStore(max_file_bytes=...)` |
| Startup index size | 65536 bytes; see [Index cost](storage.md#index-cost) for how entries are sized | `MemoryStore(index_max_bytes=...)` |
| `list_prefix` page size | 100 entries | `MemoryStore(list_page_size=...)` |
| Files per entity | 500 files, `system/` not counted; see [Files per entity](storage.md#file-cap) | `MemoryStore(max_files_per_entity=...)` |
| `replace_fact` attempts | 3 | fixed |

When the index overflows its budget, the remaining files are reported under `capped` by area, with the count omitted, and the agent pages them with `list_prefix`. Index order: `system/` areas of all scopes first; then scopes in `scope_priority` order (unlisted scopes last, as one tier); within each tier, most recently updated first.

---

HTML version: <https://msiebert.github.io/wenchang/concepts.html>
