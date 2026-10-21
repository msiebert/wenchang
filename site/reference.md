# Reference

Version 0.1.0. Everything here is taken from the source: the tool layer (`wenchang.tools`, `wenchang.mcp`), the core store (`wenchang.core`), and the file format (`wenchang.file_format`). For how to assemble a server see the [quickstart](quickstart.md); for configuration see [customize](customize.md).

## Concepts

### Path shape

Every memory file is stored at

```
{scope}/{entity_id}/{area}/{name}.md
```

For example `user/u-ada/preferences/charts.md`. Agents never write the path. The tools take `(scope, area, name)` and the tool layer fills in `entity_id` from the caller's identity grant for that scope, so a caller can only reach its own entities. Results report the full `path` plus the parsed `scope`, `area`, and `name`.

### Scopes

A scope is an adopter-defined visibility tier. The library defines no scope names; the reference adopter uses `user` (private), `project` (shared), and `organization` (shared, writes need an admin or owner role). A scope must be one of the scopes the session's identity has a grant for; otherwise the call fails with an `InvalidArgumentError` listing the available scopes.

### Areas

An area groups files within a scope. The tool layer requires an area to be a lowercase slug matching `^[a-z0-9][a-z0-9_-]*$`. Areas are created implicitly by writing a file in them. The prompt's `seed_areas` slot suggests starting areas; the agent may create more.

### Names

A name is the file's stem, passed without `.md`. It must be a valid path segment: non-empty, not `.` or `..`, with no `/`, backslash, or control character, and the tool layer additionally rejects invisible, separator, and noncharacter code points. Names must be valid UTF-8.

### The system/ area

Every scope has an area named exactly `system`. It holds curated content that people maintain and replace wholesale. The agent can read it (any area may be read) but every mutating tool refuses it with `RestrictedScopeError` (reason `system_read_only`). Seeding jobs and admin tooling write it through the core `MemoryStore`, which applies no restrictions. In the startup index, `system/` entries come first across all scopes.

### Fact-line format

A memory file body is made of fact lines, one per line:

```
- [stated] Prefers bar charts for weekly reports.
```

The pattern is `- [<label>] <text>` with a non-empty text. The label records how the fact is known:

| Label | Meaning |
| --- | --- |
| `stated` | The user told the agent directly. |
| `observed` | The agent saw it in a tool result, session data, or behavior. |
| `inferred` | The agent concluded it from a pattern across several observations. |
| `system` | Curated content. The prompt tells the agent never to write a new `[system]` line. |

`append_line` accepts only a single well-formed fact line. Other lines in a body are tolerated and preserved verbatim. An end date, if the user states one, is written into the fact's text as prose; there are no per-fact timestamps.

### File metadata

Metadata is stored beside the body, as flat string custom metadata on the stored object (in GCS), not inside the markdown.

| Field | Type | Behavior |
| --- | --- | --- |
| `description` | string, one line | What the file is about. Part of the agent's search surface. `write_file` replaces it; `append_line` and `replace_fact` replace it only if one is passed. |
| `aliases` | list of strings, ordered | Other names the subject is looked up by. `write_file` replaces the whole set; `append_line` and `replace_fact` add new aliases, keeping existing ones and their order. |
| `sources` | set of strings | Surface names (the `source` you configure) that have written the file. Only ever grows; returned sorted. |
| `last_updated` | UTC timestamp | Set by the store's clock on every write; rendered as ISO 8601 with a `Z` suffix. |

There is no content search. `description` and `aliases` are the entire search surface; the agent reads the index and matches on them.

### Optimistic concurrency

Every file has an opaque `version` (the GCS generation under `GcsStorage`). Every mutating tool takes `expected_version`, the version the agent read; the write succeeds only if the file is still at that version. `write_file` with `expected_version=null` creates the file and fails if it already exists. A mismatch returns a recoverable `VersionConflictError` carrying the current content and version.

`replace_fact` re-reads and retries up to three times when a concurrent write races it, re-checking the match each time; if the file's version moved but `old_string` still matches exactly once, it applies against the current content. `append_line` has no automatic re-apply: a stale version is a conflict. Versions are opaque: never parse, compare, or order them.

### Limits

| Limit | Default | Where set |
| --- | --- | --- |
| Per-file content size | 16384 bytes (UTF-8) | `MemoryStore(max_file_bytes=...)` |
| Startup index size | 65536 bytes | `MemoryStore(index_max_bytes=...)` |
| `list_prefix` page size | 100 entries | `MemoryStore(list_page_size=...)` |
| `replace_fact` attempts | 3 | fixed |

When the index overflows its budget, the remaining files are reported under `capped` by area prefix, with the count omitted, and the agent pages them with `list_prefix`. Index order: `system/` areas of all scopes first; then scopes in `scope_priority` order (unlisted scopes last, as one tier); within each tier, most recently updated first.

## Tools

Seven tools. With `tool_prefix` set, each is registered as `{tool_prefix}_{name}`. All results are JSON objects; all failures are rendered as described under [errors](#errors). In every tool, `scope`, `area`, and `name` are strings, and `expected_version` is a string (the `version` from a prior result).

Common file object, returned by `read_file`, `write_file`, `append_line`, and `replace_fact`:

| Field | Type | Notes |
| --- | --- | --- |
| `path` | string | Full path, `scope/entity/area/name.md`. |
| `scope`, `area`, `name` | string | Parsed from the path. |
| `content` | string | The body. Present on a file; absent on index and list entries. |
| `version` | string | Opaque. Pass as `expected_version`. |
| `description` | string | |
| `aliases` | array of strings | |
| `sources` | array of strings | Sorted. |
| `last_updated` | string | UTC ISO 8601, `Z` suffix. |

### get_memory_index

> Load the metadata index of every memory scope available in this session. Call this first. Each entry gives a file's path, metadata, and version, without content.

Call it first in every session.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| (none) | | | |

Returns an object:

| Field | Type | Description |
| --- | --- | --- |
| `entries` | array of file entries | Each is the common file object without `content`, in index order, up to the byte budget. |
| `capped` | array of objects | One per area prefix not fully returned. Empty means the index is complete. |

Each `capped` object: `prefix` (string, for example `user/u-ada/preferences/`), `scope` (string), `area` (string, or `null` for a prefix above area level), `omitted` (integer, files left out). Page a capped area with `list_prefix(scope, area)`.

### read_file

> Read one memory file: its content, metadata, and version. Any area may be read, including `system/`.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `scope` | string | yes | A granted scope. |
| `area` | string | yes | Lowercase slug. |
| `name` | string | yes | File name without `.md`. |

Returns the common file object. If no file exists: `NotFoundError` with reason `file_absent`.

### list_prefix

> List the files in a scope or area, one page at a time, without content. Each page returns entries with metadata and version, and a `next_cursor`; until it is null, pass it back as `cursor` with the same `scope` and `area` for the next page.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `scope` | string | yes | A granted scope. |
| `area` | string or null | no (default `null`) | Restrict to one area; `null` lists the whole scope. |
| `cursor` | string or null | no (default `null`) | The `next_cursor` from the previous page, with the same `scope` and `area`. |

Returns `{"entries": [...], "next_cursor": string | null}`. Entries are the common file object without `content`, ascending by path. A malformed cursor, or one from a different prefix, returns `InvalidArgumentError` for `cursor`. Listing is not a snapshot: a file written or deleted between two pages may or may not appear.

### write_file

> Create a memory file or replace one whole. Pass `expected_version=None` to create a file, or the version you read to replace one. `description` (one line) and `aliases` replace the stored values; they are not merged. Content over the per-file byte ceiling is rejected with the current size and the limit; shorten it and retry. A version conflict is routine: merge your change into the content it returns and retry with its version.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `scope` | string | yes | A granted scope the caller may write. |
| `area` | string | yes | Lowercase slug; not `system`. |
| `name` | string | yes | File name without `.md`. |
| `content` | string | yes | The whole new body, at most `max_file_bytes` UTF-8 bytes. |
| `description` | string | yes | One line; replaces the stored value. |
| `aliases` | array of strings | yes | Replaces the stored set (use `[]` for none). |
| `expected_version` | string or null | yes | `null` creates (fails if the file exists); otherwise the version being replaced. |

Returns the common file object. Errors: `VersionConflictError`, `NotFoundError` (`file_absent`, when replacing a file that does not exist), `OversizeWriteError`, `InvalidArgumentError`, `RestrictedScopeError`.

### append_line

> Add one fact line to the end of an existing memory file. `line` is a single fact line with a leading bracketed label (`[stated]`, `[observed]`, `[inferred]`, or `[system]`), as in `- [stated] Prefers tea`. Pass the version you read as `expected_version`. The per-file byte ceiling applies to the result. Optional `aliases` are added to the file's existing aliases and never removed (`write_file` replaces the whole set); an optional one-line `description` replaces the stored one. A version conflict is routine: merge your change into the content it returns and retry with its version.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `scope` | string | yes | A granted scope the caller may write. |
| `area` | string | yes | Lowercase slug; not `system`. |
| `name` | string | yes | Existing file name without `.md`. |
| `line` | string | yes | One fact line, `- [label] text`. Rejected with `InvalidArgumentError` otherwise. |
| `expected_version` | string | yes | The version read. |
| `aliases` | array of strings or null | no (default `null`) | Added to existing aliases, never removed. |
| `description` | string or null | no (default `null`) | Replaces the stored description when given. |

The file must already exist (`NotFoundError` with `file_absent` otherwise). A newline is added before the line if the body does not end with one, and one after. Returns the common file object.

### replace_fact

> Change one fact in a memory file by quoting the text to replace. `old_string` must match the content exactly once; otherwise the error carries the current content and version, so quote a unique span. `new_string` replaces it. Pass the version you read as `expected_version`. The per-file byte ceiling applies to the result. Optional `aliases` are added to the file's existing aliases and never removed (`write_file` replaces the whole set); an optional one-line `description` replaces the stored one. A version conflict is routine: merge your change into the content it returns and retry with its version.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `scope` | string | yes | A granted scope the caller may write. |
| `area` | string | yes | Lowercase slug; not `system`. |
| `name` | string | yes | Existing file name without `.md`. |
| `old_string` | string | yes | Non-empty text that appears exactly once in the file. |
| `new_string` | string | yes | Replacement. An empty string removes the span (to drop a whole fact line, quote the line including its line break). |
| `expected_version` | string | yes | The version read. |
| `aliases` | array of strings or null | no (default `null`) | Added to existing aliases, never removed. |
| `description` | string or null | no (default `null`) | Replaces the stored description when given. |

Zero or several matches return `ReplaceFactMatchError` with the current content, version, and `match_count`. Returns the common file object.

### delete_file

> Delete a memory file. Pass the version you read as `expected_version`. A version conflict is routine: retry with the version it returns only if the file should still go.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `scope` | string | yes | A granted scope the caller may write. |
| `area` | string | yes | Lowercase slug; not `system`. |
| `name` | string | yes | File name without `.md`. |
| `expected_version` | string | yes | The version read. |

Returns `{"ok": true}`. Errors: `VersionConflictError`, `NotFoundError`, `RestrictedScopeError`.

## The memory prompt resource

The server exposes the assembled memory prompt as an MCP resource:

| Property | Value |
| --- | --- |
| URI | `wenchang://memory-prompt` (`wenchang.mcp.PROMPT_RESOURCE_URI`) |
| Name | `memory_prompt` |
| MIME type | `text/markdown` |
| Content | The same text as the server's `instructions`: `build_memory_prompt(slots)`. |

Clients that drop server `instructions` can read the resource instead. The prompt is markdown with `##` headings and no H1; see [customize](customize.md#slots) for its sections.

## Errors

A failed tool call returns an MCP error result (`isError` true) whose JSON payload has this shape:

```json
{
  "error": "VersionConflictError",
  "category": "recoverable",
  "message": "...",
  "path": "...",
  "content": "...",
  "version": "..."
}
```

`error` is the class name, `category` is `recoverable`, `permanent`, `transient`, or `internal`, and `message` combines the detail with fixed guidance for the category. Extra fields appear only when relevant.

| Category | Meaning | What the agent should do |
| --- | --- | --- |
| `recoverable` | Normal coordination. | Correct the call from the attached details and retry in the same turn, without asking the user. |
| `permanent` | The call cannot succeed as given. | Do not retry. |
| `transient` | A temporary condition. | Retry. Version-guarded calls are safe to retry; a retried `append_line` may duplicate a line. |
| `internal` | An unexpected failure, or corrupt stored data. | The payload carries only a generic message (or, for corrupt metadata or a non-UTF-8 body, that error's message). |

| Error | Category | Raised when | Extra fields |
| --- | --- | --- | --- |
| `VersionConflictError` | recoverable | The file changed since it was read. | `path`, `content`, `version` (current) |
| `OversizeWriteError` | recoverable | The resulting content exceeds the per-file limit. | `path`, `size`, `limit` |
| `ReplaceFactMatchError` | recoverable | `old_string` matched zero spans or more than one. | `path`, `content`, `version`, `match_count` |
| `InvalidArgumentError` | recoverable | An argument was rejected: unknown scope, bad area slug, bad name, not a fact line, empty `old_string`, bad cursor, and similar. | `argument` |
| `NotFoundError` | recoverable | The path is invalid (`invalid_path`) or no file exists there (`file_absent`). | `path`, `reason` |
| `RestrictedScopeError` | permanent | A write to `system/` (`system_read_only`), or to a scope whose policy requires another role (`role_required`), or outside the caller's grant (`not_granted`). | `path`, `scope`, `reason`, and `required_roles` for `role_required` |
| `ResolverFailureError` | permanent | The identity could not be resolved, or `credentials_from_context` raised. Memory is unavailable for the session. | none |
| `BackendUnavailableError` | transient | The storage backend timed out or is unreachable. | `reason` (`timeout` or `unavailable`) |

Notes:

- The tool layer builds each path from the caller's own grants, so over MCP an ungranted scope is reported as `InvalidArgumentError` (naming the available scopes); `not_granted` is raised by the core path check.
- MCP validates arguments before wenchang sees them. A wrong-type or missing argument returns MCP's own error text, not a rendered wenchang error.
- MCP pre-parses JSON-like strings: the string `"null"` arrives as `None` for a nullable parameter. For example `list_prefix(area="null")` lists the whole scope.

## Limitations and status

- **Status.** Version 0.1.0, MIT license, Python 3.12 or newer. Installed from git; no PyPI release is documented.
- **A library, not a server.** There is no CLI, console script, or ready-made server binary. You supply the identity resolver, scope policy, prompt slots, and a short server script. The only server in the repository is the dev-only eval server (`python -m evals.server`), which uses in-memory storage.
- **No content search.** Files are found through `description` and `aliases`. The quality of that metadata is what makes recall work.
- **Not snapshots.** `list_prefix` and `get_memory_index` are not point-in-time snapshots: a file written or deleted while an index is being built may or may not appear.
- **Remote transport is planned.** Today the only client is `InProcessClient`; the `TransportClient` protocol is the seam for a remote one.
- **Reads are never role-restricted.** A caller can read any area (including `system/`) of any scope it holds a grant for. `ScopePolicy` gates writes only.
- **Privacy is prompt-level.** The prompt tells the agent to refuse financial account numbers, health diagnoses, and anything indicating the user is a minor, and to be stricter in shared scopes. No tool checks content, so a successful write does not mean the content was safe.
- **Behavior depends on the agent.** Where facts get filed, and how well, is up to the model following the prompt. The repository's behavioral evals run scripted scenarios against a real agent and grade what it stored; they are signal for prompt iteration, not release gates.
- **Tool calls run concurrently** on worker threads, so the transport client (and `on_call`) must be thread-safe.

---

HTML version: <https://msiebert.github.io/wenchang/reference.html>
