# Spec Review: AIE-1044 — tool layer

## What & why

Notion §7 wants a thin, transport-agnostic tool layer whose bodies "call
an abstract client interface and format the response"; §6 says tool code
never touches a credential and "uses the returned fields to build the path
prefix"; §3 makes `system/` read-only at the tool layer; §5 wants tool
descriptions that present version conflicts as routine. This adds
`wenchang.tools`: a per-session `MemoryTools` (resolved identity, policy,
transport client, surface name) whose seven methods are the tools. Tools
take `(scope, area, name)`, never a path: the tool checks the scope is
granted and builds the path under the caller's own entity, so the agent
never has to type an entity ID. Mutating tools run `scope.check_write` on the
built path before the client. `bind_tools` is the single
credential-handling entry; `TOOL_NAMES` and `tools()` serve hosts;
`render_result` / `render_error` produce the JSON-safe agent-facing form,
including the repair material `str(err)` omits; a new recoverable
`InvalidArgumentError` covers agent-argument mistakes ADR 0010 deferred
here. The `get_memory_index` tool passes `identity.scope_map` to the
client (index semantics are AIE-1046's, ADR 0019).

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | `MemoryTools(client, identity, policy, source="s")` | build | four read-only properties; bad `source`/types → `ValueError`/`TypeError` |
| 2 | `bind_tools(client, resolver, creds, policy, source=...)` | resolver succeeds / returns failure / raises | `MemoryTools` / `ResolverFailureError` (permanent, no client call) / `ResolverFailureError` with no secret; credentials never retained |
| 3 | `read_file("org", "notes", "a")`, `list_prefix("user")`, `list_prefix("user", "notes", cursor)`, `get_memory_index()` | call | client gets `read_file("org/o-9/notes/a.md")`, `list_prefix("user/u-1/", None)`, `list_prefix("user/u-1/notes/", cursor)`, `get_memory_index(identity.scope_map)`; result returned as-is; no `check_write` |
| 4 | any scope-taking tool, ungranted scope `"team"` | call | `InvalidArgumentError(argument="scope")` with detail `"scope 'team' is not available in this session; available scopes: org, user"`, before any path is built; no `check_write`, no client call |
| 5 | invalid `area` (`""`, `".."`, `"a/b"`) or `name` (`""`, contains `/`) | call | `InvalidArgumentError` naming `area` / `name`, `__cause__` = `build_path`/`build_prefix` `ValueError`; no client call |
| 6 | `name="a.md"`; lying `str` subclass segment; `Identity` subclass with a lying `entity_id()` | call | path `.../a.md.md` (not rejected; docstrings say `name` excludes `.md`); exact-`str` path from normalized segments; entity read from `grants[scope].entity_id`, never `entity_id()` |
| 6a | any agent argument with wrong real type (segments, `content`, `line`, `old_string`, `new_string`, `description`, `aliases` members, `cursor`, `expected_version`); `scope`/`area`/`name`/`description`/`content`/`line`/`new_string` with a lone surrogate | call | `InvalidArgumentError` naming that argument, never `TypeError` (wrong-type detail `"{argument} must be a string, not {type_name}"`); no client call |
| 7 | each of 4 mutating tools, `("user", "notes", "a")` | call | `check_write` spy (monkeypatched on `wenchang.tools`) sees `"user/u-1/notes/a.md"` before the client, same object the client receives; forwarded with `source=` (write_file builds `FileMetadata(description, tuple(aliases), frozenset(), epoch)`) |
| 8 | each mutating tool, area `system` / `org` with role `member` | call | `RestrictedScopeError(SYSTEM_READ_ONLY / ROLE_REQUIRED)` on the built path; client never called. `NOT_GRANTED` and `INVALID_PATH` unreachable through tools |
| 9 | client raises taxonomy errors, `MetadataFormatError`, `UnicodeDecodeError` | any tool | same object propagates |
| 10 | client raises plain `ValueError` from `list_prefix` / `append_line` / `replace_fact`; bad `description` / `aliases` | call | `InvalidArgumentError(argument="cursor"/"line"/"old_string"/"description"/"aliases")`, recoverable, `__cause__` set where converted |
| 11 | client raises `ValueError` from any other tool | call | propagates unchanged (no blanket conversion) |
| 12 | `TOOL_NAMES`, `tools()` | read | seven names in fixed order; bound methods; read-only mapping |
| 13 | docstrings | read | phrase table in plan.md (routine conflicts, byte ceiling, fact-line labels, exactly-once anchor, `write_file` "not merged", `get_memory_index` literals `read_file(scope, area, name)` and `list_prefix(scope, area)`, `system/` read-only, `scope`/`area`/`name` and `.md`); no Linear IDs |
| 14 | `render_result(MemoryFile / ListPage / MemoryIndex / None / other)` | call | JSON-safe dict: file fields (`path`, `scope`/`area`/`name` via `parse_path`, `version` str, `aliases` list, `sources` sorted, `last_updated` ISO "Z"), `entries` + `next_cursor`, `entries` + `capped` `[{prefix, scope, area, omitted}]` (`area` null for scope/entity-level prefixes), `{"ok": True}`; malformed entry path → `scope`/`area`/`name` null, no raise; other type → `TypeError` |
| 15 | `render_error(exc)` per error kind; any other `Exception` | call | `error`, `category`, `message` plus each non-`None` payload attribute from the fixed ten (`path`, `content`, `version`, `size`, `limit`, `match_count`, `reason` value, `scope`, `required_roles` sorted, `argument`); `MetadataFormatError`/`UnicodeDecodeError` → `{"error", "category": "internal", "message": str(exc)}`; any other exception → `"message": "internal error"` (no internals leaked); hostile `__str__`/`__name__` → `"<unreadable>"`/`"<unnamed>"`; never raises |
| 16 | `tools.py` imports; other modules; `pyproject.toml` | ast / tomllib | only `core`, `errors`, `file_format`, `identity`, `paths`, `scope`, `transport`, `version_token`; nothing imports `tools`; `dependencies == ["google-cloud-storage>=2.18"]` |
| 17 | end to end via tests-only `_StoreClient` over `MemoryStore(InMemoryStorage())` (`isinstance` `TransportClient`; index call records `scope_map`, returns `MemoryIndex()`) | create/read/append/replace/list/index/delete + `system/`, role, ungranted-scope rejections, all rendered | recorded `scope_map == {"user": "u-1", "org": "o-9"}`; `sources == {"test-surface"}`; `last_updated` not epoch; every rendered value `json.dumps`-able. Follow-up: `InProcessClient` after rebasing on AIE-1046 |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| **Scope-relative tools** `(scope, area, name)`; tool builds the path with `build_path(scope, identity.grants[scope].entity_id, area, name)` (human decision 1c) | Full paths with prefixes from prompt text; exposing the scope map to the agent; calling `Identity.entity_id()` (overridable by a subclass) | §6 "uses the returned fields to build the path prefix"; agent never has to type entity IDs; removes a class of path errors |
| Ungranted scope → recoverable `InvalidArgumentError("scope")` listing the available scopes, before any path is built | `RestrictedScopeError(NOT_GRANTED)` (permanent) | The error itself tells the agent which scopes to use |
| One wrong-type rule: any wrongly typed agent argument, or non-UTF-8-encodable `content`/`line`/`new_string` → `InvalidArgumentError` naming it | `TypeError` as the host schema's concern | A loose host schema leaves the agent stuck on an uncategorized error; stops core's `UnicodeEncodeError` being blamed on `old_string` |
| **Reads scoped to own entity** (decides ADR 0017's open point) | Separate unchecked full-path read tool | Follows from scope-relative tools; reopening paths for reads reopens the entity-ID problem |
| `check_write` on the built path for every mutation, even though `NOT_GRANTED`/`INVALID_PATH` are unreachable | Skip it for tool-built paths | Single home for `system/` and role rules; defense in depth |
| **Tool-layer `render_result` / `render_error`** (human decision 2a); `render_error` accepts any `Exception` and never raises (non-library → `category: "internal"`, fixed `"internal error"` message except for the two data-integrity types); rendered files and capped rows carry `scope`/`area`(/`name`) | Tools return rendered payloads; hosts format; `TypeError` for non-library exceptions; rendering `str(exc)` for every exception | §7 "format the response"; repair material survives; every tool failure is renderable with one `except Exception`; off-contract exceptions leak nothing (relies on ADR 0019's transport-failure mapping); path → arguments mapping is in the data |
| Framework-agnostic `MemoryTools` + `tools()`; no dependency; server object deferred to AIE-1060 (orchestrator call) | Depend on an MCP/agent framework now; schema generator | Host adapter is AIE-1060's testable concern; frameworks derive schemas from signatures |
| One `MemoryTools` per session; identity resolved once in `bind_tools` | Per-call credentials; lazy resolution | §6 credential rule; permanent failure surfaces at session start; matches ADR 0019 |
| `write_file(scope, area, name, content, description, aliases, expected_version)` | Expose `FileMetadata` | Agent controls only description/aliases; `sources` stamped from fixed `source`; `last-updated` by core |
| New recoverable `InvalidArgumentError` (orchestrator call), converted at named sites only, chained `from exc` | `NotFoundError(INVALID_PATH)` for bad cursor; blanket `except ValueError` | Right repair material; data-integrity `ValueError` subclasses pass through |
| Byte ceiling stated generically in the docstring (orchestrator call) | Put the configured number in the docstring | Number reaches the agent via `OversizeWriteError.limit` and prompt text |
| Docstrings are the descriptions; phrases pinned by tests | Separate description strings | §7 "each carrying a docstring as its description" |
| Recorded in ADR 0022 | — | New public module, new error kind, read-scoping decision |

## Files/modules to be touched

- `src/wenchang/tools.py` (new), `src/wenchang/errors.py`
- `tests/test_errors_invalid_argument.py`, `tests/test_tools.py`, `tests/test_tools_descriptions.py`, `tests/test_tools_render.py`, `tests/test_tools_end_to_end.py` (new)
- `ARCHITECTURE.md`, `docs/adr/0022-tool-layer.md`, `docs/adr/0016-*.md` (consequence note), `docs/adr/0017-*.md` (read scoping decided as own-entity-only), `docs/product/glossary.md`

## Open questions / assumptions

- **Human decisions (2026-10-02)**: 1c scope-relative tools; 2a
  tool-layer rendering helpers.
- **Orchestrator calls** (flag at the PR if you disagree): (3) server
  object deferred to AIE-1060; (4) generic byte-ceiling docstring; (5)
  `InvalidArgumentError` added to the taxonomy; plus per-session binding
  with identity resolved once, and `write_file` exposing `description` and
  `aliases` only.

## Risks

- A host that forgets to construct `MemoryTools` per session would share
  one identity across callers; `bind_tools` makes the right thing the
  easy thing, but nothing prevents misuse.
- The agent sees full paths in the index and listings but passes
  `(scope, area, name)`; `render_result` emits `scope`/`area`/`name` per
  file and the docstrings describe the mapping (US5.8), but a host that
  skips `render_result` loses the former. A confused agent gets a
  recoverable error, or for `name="a.md"` a file named `a.md.md`.
- The `_StoreClient` end-to-end test does not exercise real index
  semantics; that waits for the `InProcessClient` follow-up after AIE-1046.
- Docstring phrase tests are brittle by design: they protect the agent-
  facing contract from silent edits.
