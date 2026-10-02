# Feature Specification: Tool layer

**Linear issue**: AIE-1044 — https://linear.app/mixpanel/issue/AIE-1044/tool-layer-definitions-including-get-memory-index

**Feature Branch**: `AIE-1044-tool-layer` (based on `AIE-1048-transport-interface`)

**Created**: 2026-10-01

**Status**: Implemented — code-reviewed 2026-10-02 (human decisions
recorded 2026-10-02; see "Human decisions (2026-10-02)" below).

**Input**: Linear AIE-1044 ("Define the tool-facing layer exposing memory
operations as callable tools, built on top of the transport client and the
scope model: read_file, write_file, append_line, replace_fact,
list_prefix, delete_file, and get_memory_index."). The index semantics in
the same issue text are implemented in `MemoryStore.get_memory_index`
under AIE-1046 (ADR 0019); here the `get_memory_index` tool calls the
client with the caller's resolved scope map. Notion:

- §7: "The agent-facing tool layer is thin and transport-agnostic. Tool
  bodies contain no logic; they call an abstract client interface and
  format the response." "Mounting into a host: ... the library ships as
  its own server instance with the memory tools decorated onto it, each
  carrying a docstring as its description."
- §6: "Tool code never touches a credential. It calls the resolver and uses
  the returned fields to build the path prefix and to check write
  eligibility against any write-restricted scope."
- §3: "the area named `system/` is read-only to the agent, enforced at the
  tool layer".
- §5: "A version conflict is routine coordination, not an error path ...
  Agent-facing tool descriptions must present it as routine, or the agent
  treats a conflict as failure and abandons the write." "The limit is also
  stated to the agent up front."
- §1 design principle 1: "Tools are reliable verbs with no embedded
  policy. Anything requiring judgment lives in prompt text layered on top,
  never in tool code."

Builds on `TransportClient` (AIE-1048), `Identity` / `IdentityResolver` /
`resolve_identity` (AIE-1043), `ScopePolicy` / `check_write` (AIE-1040,
AIE-1042), and the error taxonomy (AIE-1030).

## Summary

Add `wenchang.tools` with:

- `MemoryTools(client, identity, policy, *, source)`: one object per
  session holding the resolved `Identity`, the adopter's `ScopePolicy`, the
  injected `TransportClient`, and the surface name stamped as `source` on
  every write. Its seven public methods are the tools.
- **Scope-relative tools.** File tools take `scope`, `area`, and `name`
  instead of a path; `list_prefix` takes `scope` and an optional `area`.
  The agent never has to type an entity ID. Each tool first requires
  `scope in identity.grants` (otherwise the recoverable
  `InvalidArgumentError("scope", ...)`, before any path is built), then
  builds the path with `paths.build_path(scope, entity_id, area, name)`
  (or the prefix with `paths.build_prefix(scope, entity_id, area)`), where
  `entity_id = identity.grants[scope].entity_id`, converting an invalid segment to `InvalidArgumentError` naming
  `area` or `name`. `build_path` always appends `.md`, so `name` excludes
  the extension. Reads and listing therefore reach only the caller's own
  entity in each granted scope: this is the read-scoping decision ADR 0017
  left to the tool layer. Each mutating tool then calls
  `scope.check_write(built_path, identity, policy)` (for `system/` and
  role checks) and then the client with the built path.
  `get_memory_index()` takes no arguments and passes a scope map built from
  the grants (`{s: g.entity_id for s, g in identity.grants.items()}`),
  never the overridable `identity.scope_map` property.
- `bind_tools(client, resolver, credentials, policy, *, source)`: the one
  place credentials are handled. It calls `resolve_identity` and returns a
  `MemoryTools`; a resolution failure raises the permanent
  `ResolverFailureError` unchanged.
- `TOOL_NAMES`, the seven tool names in a fixed order, and
  `MemoryTools.tools()`, a mapping from each name to the bound method, so
  a host can decorate them without naming each one.
- Agent-facing docstrings on every tool method, which are the tool
  descriptions a host picks up.
- A new recoverable error, `InvalidArgumentError(argument, detail)`, for
  every rejected agent-supplied argument. The tool pre-validates a `line`
  that is not a fact line and an empty `old_string` and raises it itself;
  it converts a client `ValueError` from `list_prefix` to `cursor` only
  when a cursor was passed; plus its own `scope`/`area`/`name`
  rejections. ADR 0010 deferred this mapping to the tool layer. Every
  other `ValueError` propagates unchanged. `MetadataFormatError` and
  `UnicodeDecodeError`, both `ValueError` subclasses, are data-integrity
  errors and pass through unchanged.
- Rendering helpers `render_result(value)` and `render_error(exc)`, which
  turn a tool's return value or a `WenchangError` into a JSON-safe `dict`
  carrying every field the agent needs, including the repair material
  (`content`, `version`, `size`, `limit`, ...) that `str(err)` omits. This
  is Notion §7's "format the response": the tool methods stay typed, and a
  host adapter calls these two functions to produce what the agent sees.

The tool layer is framework-agnostic: it depends on no agent framework and
adds no runtime dependency. Mounting into a host server (Notion §7's
"ships as its own server instance") is AIE-1060's smoke test and any
adapter it needs.

Out of scope: prompt text (milestone 4), any host-framework adapter or
server object, reads of other entities' files (not reachable through the
tools by construction), input schema generation, and any change to `core`,
`scope`, `identity`, or `paths`.

## User Scenarios & Testing *(mandatory)*

Reference fixture: `identity` with grants `{"user": ScopeGrant("u-1",
"owner"), "org": ScopeGrant("o-9", "member")}`; `policy =
ScopePolicy({"org": frozenset({"admin", "owner"})})`; `source =
"test-surface"`. The client is a `_FakeClient` test double satisfying
`TransportClient` that records every call `(name, args, kwargs)`, returns
preset values, and raises a configured exception on demand. "The call is
forwarded" means the client recorded exactly one call with the stated
name and arguments. "`check_write` runs" is observed with a spy installed
by `monkeypatch.setattr(wenchang.tools, "check_write", spy)` that records
each call's arguments and its order relative to client calls, then
delegates to the real `scope.check_write`.

### User Story 1 - Construction and binding (Priority: P1)

**Acceptance Scenarios**:

1. **Given** `MemoryTools(client, identity, policy, source="s")`, **Then**
   `tools.identity is identity`, `tools.policy is policy`, `tools.client
   is client`, `tools.source == "s"`; all four are read-only properties.
2. **Given** `source=""`, or a `source` whose real type is not `str`,
   **Then** `ValueError` / `TypeError` at construction. A `str` subclass is
   stored as an exact `str`.
3. **Given** a `client` that does not satisfy `TransportClient`
   (`isinstance` False), an `identity` whose real type is not `Identity`,
   or a `policy` whose real type is not `ScopePolicy`, **Then**
   `TypeError`.
4. **Given** `bind_tools(client, SandboxResolver(identity), object(),
   policy, source="s")`, **Then** the result is a `MemoryTools` whose
   `identity == identity`.
5. **Given** a resolver returning `ResolutionFailure("expired")`, **When**
   `bind_tools(...)`, **Then** `ResolverFailureError` propagates (category
   `PERMANENT`), and the client is never called.
6. **Given** a resolver that raises `RuntimeError("secret")`, **Then**
   `bind_tools` raises `ResolverFailureError` whose message does not
   contain `secret`, as `resolve_identity` guarantees.
7. **Given** `bind_tools` called with a weakref-able credentials sentinel
   (an instance of a local class) and a `weakref.ref` to it, **When** the
   test drops its own reference and runs `gc.collect()` while keeping the
   returned `MemoryTools` alive, **Then** the weak reference is dead: the
   credentials are not retained anywhere reachable from the tools.

---

### User Story 2 - Reads, listing, and index build the caller's path and forward (Priority: P1)

**Acceptance Scenarios**:

1. **Given** `tools.read_file("org", "notes", "a")`, **Then** the call is
   forwarded as `read_file("org/o-9/notes/a.md")` (the caller's entity
   `o-9` filled in, `.md` appended) and the client's return value is
   returned as the same object. The `check_write` spy records no call.
   **Given**
   `read_file("user", "system", "rules")`, **Then** it is forwarded as
   `read_file("user/u-1/system/rules.md")` (reading `system/` is allowed).
2. **Given** `tools.list_prefix("user")`, **Then** the client receives
   `list_prefix("user/u-1/", None)`. **Given** `tools.list_prefix("user",
   "notes", cursor)`, **Then** it receives `list_prefix("user/u-1/notes/",
   cursor)`. Both arguments are passed positionally (recorded `args ==
   (prefix, cursor)`, `kwargs == {}`). The return value is returned as-is.
3. **Given** `tools.get_memory_index()`, **Then** the client receives
   `get_memory_index(scope_map)` with `scope_map == {s: g.entity_id for
   s, g in identity.grants.items()}` (`{"user": "u-1", "org": "o-9"}`) and
   the return value is returned as-is. The method takes no parameters.
   **Given** an `Identity` subclass whose `scope_map` property returns a
   different map (`{"user": "u-evil"}`), **Then** the client still
   receives the map built from `grants`: the tool never reads
   `scope_map`, for the same reason it never calls `entity_id()` (US2.9).
4. **Given** the client raises `NotFoundError`, `BackendUnavailableError`,
   `MetadataFormatError`, or `UnicodeDecodeError` from `read_file`,
   **Then** the same exception object propagates.
5. **Given** `read_file` or `list_prefix` with an ungranted scope
   (`"team"`), **Then** `InvalidArgumentError` with `argument == "scope"`
   is raised before any path is built, constructed with the exact detail
   `"scope 'team' is not available in this session; available scopes:
   org, user"` (`f"scope {scope!r} is not available in this session;
   available scopes: {', '.join(sorted(identity.grants))}"`), so
   `err.detail == "Argument scope is invalid: " + that`; the client
   records no call.
6. **Given** `read_file("user", "", "a")`, `read_file("user", "..", "a")`,
   or `read_file("user", "a/b", "a")`, **Then** `InvalidArgumentError`
   with `argument == "area"`; **given** `read_file("user", "notes", "")` or
   a `name` containing `/`, **Then** `argument == "name"`; **given**
   `list_prefix("user", "a/b")`, **Then** `argument == "area"`. In each
   case `__cause__` is `build_path`'s / `build_prefix`'s `ValueError` and
   the client records no call.
7. **Given** a `name` that already ends in `.md` (`"a.md"`), **Then** it is
   not rejected: `build_path` appends `.md` unconditionally, so the client
   receives `.../a.md.md`. The docstrings tell the agent that `name`
   excludes `.md`.
8. **Given** a `scope`, `area`, or `name` whose real type is not `str`
   (for `list_prefix`, an `area` or `cursor` that is neither `None` nor a
   `str`), **Then** `InvalidArgumentError` naming that argument, never
   `TypeError`; no client call (the one wrong-type rule, US3.10). **Given**
   a `str` subclass whose `__str__`/`__format__`/`__eq__`/`__hash__` lie,
   **Then** each segment is normalized once with `str.__str__` before the
   grant lookup and path building, and the client receives a path of
   `type(...) is str` built from the normalized values. **Given** a
   `scope`, `area`, or `name` that cannot be UTF-8-encoded (a lone
   surrogate such as `"\ud800"`, which `is_valid_segment` accepts because
   its category is `Cs`, not `Cc`), **Then** `InvalidArgumentError` naming
   that argument, chained from the `UnicodeEncodeError`, raised during the
   segment checks (before the grant lookup); no client call. One scenario
   per tool for `area` and for `name` (`list_prefix`: `area` only).
9. **Given** an `Identity` subclass whose `entity_id()` method returns a
   different entity (`"u-evil"`) than `grants["user"].entity_id`, **When**
   `read_file("user", "notes", "a")` or `write_file("user", ...)`, **Then**
   the client receives `user/u-1/notes/a.md`: the tool reads
   `identity.grants[scope].entity_id` directly and never calls
   `entity_id()`.

---

### User Story 3 - Writes are checked, then forwarded (Priority: P1)

For each mutating tool: `write_file(scope, area, name, content,
description, aliases, expected_version)`, `append_line(scope, area, name,
line, expected_version)`, `replace_fact(scope, area, name, old_string,
new_string, expected_version)`, `delete_file(scope, area, name,
expected_version)`. In the scenarios below `path` means the path the tool
built, e.g. `user/u-1/notes/a.md` for `("user", "notes", "a")`.

**Acceptance Scenarios**:

0. **Given** any mutating tool, **Then** it runs, in order: segment type
   check, `str.__str__` normalization, and UTF-8 encodability check
   (US2.8); grant check (US2.5);
   path building (US2.6); `check_write(path, identity, policy)`; argument
   validation (US3.8–11); the client call. The `check_write` spy records
   exactly one call before the client call, and the path it received `is`
   the path object the client received (ADR 0017 decision 11: storage
   receives the string the check validated).
1. **Given** `("user", "notes", "a")` (the caller's own entity in an
   unrestricted scope), **When** each mutating tool is called, **Then**
   the client receives exactly one forwarded call, with `path ==
   "user/u-1/notes/a.md"`:
   - `write_file(path, content, FileMetadata(description,
     tuple(aliases), frozenset(), <placeholder>), expected_version,
     source=tools.source)`, where `<placeholder>` is the fixed
     `datetime(1970, 1, 1, tzinfo=UTC)` that core overrides on write and
     `aliases` is any `Sequence[str]` copied to a `tuple`;
   - `append_line(path, line, expected_version, source=tools.source)`;
   - `replace_fact(path, old_string, new_string, expected_version,
     source=tools.source)`;
   - `delete_file(path, expected_version)`;
   and the client's return value is returned as-is (`None` for delete).
2. **Given** area `"system"` (`("user", "system", "x")`, built path
   `user/u-1/system/x.md`), **Then** each mutating tool raises
   `RestrictedScopeError(SYSTEM_READ_ONLY)` with `path ==
   "user/u-1/system/x.md"` and the client records no call.
3. **Given** an ungranted scope (`("team", "notes", "a")`), **Then** each
   raises `InvalidArgumentError(argument="scope")` (US2.5); the
   `check_write` spy and the client record no call. A foreign entity cannot be named,
   so `RestrictedScopeError(NOT_GRANTED)` is unreachable through the tools;
   `check_write` still runs on every built path as defense in depth.
4. **Given** `("org", "notes", "a")` with role `member` and the reference
   policy, **Then** each raises `RestrictedScopeError(ROLE_REQUIRED)` with
   `path == "org/o-9/notes/a.md"` and `required_roles ==
   frozenset({"admin", "owner"})`; no client call. **Given** role `owner`
   instead, each is forwarded.
5. **Given** an invalid `area` or `name` (US2.6), **Then** each mutating
   tool raises `InvalidArgumentError` naming that argument; no client
   call. `NotFoundError(INVALID_PATH)` from `check_write` is unreachable
   because the built path is always well formed.
6. **Given** the client raises `VersionConflictError`,
   `OversizeWriteError`, `ReplaceFactMatchError`, or `NotFoundError`,
   **Then** the same exception object propagates from the tool.
7. **Given** `write_file` with `expected_version=None`, **Then** the
   forwarded call carries `None` (create). **Given** `aliases` as a
   `list`, **Then** the metadata holds a `tuple`.
8. **Given** `write_file` with a `description` containing any line
   boundary `str.splitlines` recognizes (`\n`, `\r`, `\x0b`, `\x0c`,
   `\x1c`, `\x1d`, `\x1e`, `\x85`, ` `, ` `), **Then**
   `InvalidArgumentError("description", ...)`; no client call. A
   description must be one line under every line-boundary rule a reader
   may apply, not only `FileMetadata`'s `\n`/`\r` check, whose
   `ValueError` is still converted to `description` if it fires.
   A non-`str` `description` raises `InvalidArgumentError("description",
   ...)` too (US3.10; the tool checks real type before building
   metadata), and a `str` subclass is normalized with `str.__str__`. A
   `description` that cannot be UTF-8-encoded (lone surrogate) raises
   `InvalidArgumentError("description", ...)` chained from the
   `UnicodeEncodeError`. The `check_write` call precedes metadata
   construction, so area `system` with a bad description raises
   `RestrictedScopeError`.
9. **Given** `aliases` that is a bare `str`/`bytes` (a `str` is a
   `Sequence[str]` of characters), whose real type is not a `Sequence`
   (`issubclass(type(aliases), Sequence)`, not the spoofable `isinstance`),
   that contains a member whose real type is not `str`, or that contains a
   member that cannot be UTF-8-encoded (lone surrogate; chained from the
   `UnicodeEncodeError`), **Then** `InvalidArgumentError("aliases", ...)`
   before any client call, never `TypeError`. `FileMetadata` validates
   neither, and a non-`str` member would be stored and make every later
   `read_file` and `list_prefix` over that prefix raise
   `MetadataFormatError`. Members are normalized to exact `str`; a `str`
   subclass member is stored as `str`.
10. **One wrong-type rule.** **Given** any agent-supplied argument whose
    real type is wrong — `scope`, `area`, `name`, `content`, `line`,
    `old_string`, `new_string`, `description`, `cursor` (non-`None`
    non-`str`), `expected_version` (non-`str`; `None` allowed only for
    `write_file`), or an `aliases` member — **Then** the tool raises
    `InvalidArgumentError(<that argument>, ...)` before any client call,
    never `TypeError`; the check uses the real type
    (`issubclass(type(x), str)`), and every `str` subclass is normalized
    with `str.__str__` before use. Segment arguments are checked first
    (US3.0); the rest after `check_write`. The detail is exactly
    `f"{argument} must be a string, not {type_name}"`, where `type_name`
    is `type(x).__name__` read through a guarded helper (exact `str` via
    `str.__str__`; `"<unnamed>"` if reading it raises), so
    `InvalidArgumentError("content", ...)` for `content=5` has detail
    `"Argument content is invalid: content must be a string, not int"`.
    The same rule (and format) applies to segments in US2.8.
11. **Given** `content` (write_file), `line` (append_line),
    `new_string` (replace_fact), or — per US2.8, US3.8, and US3.9 — `scope`,
    `area`, `name`, `description`, or an `aliases` member that cannot be
    UTF-8-encoded (contains a
    lone surrogate such as `"\ud800"`), **Then** the tool raises
    `InvalidArgumentError` naming that argument before any client call,
    so core's `UnicodeEncodeError` (a `ValueError`) is never converted
    and mis-attributed to `old_string` or `line`. The check is
    `x.encode("utf-8")` raising `UnicodeEncodeError`, chained as
    `__cause__`.

---

### User Story 4 - Agent-argument errors become recoverable (Priority: P1)

**Acceptance Scenarios**:

1. **Given** the client's `list_prefix` raises `ValueError("Malformed
   list cursor: 'x'")`, **When** `tools.list_prefix("user", None, "x")`
   (a cursor was passed), **Then** `InvalidArgumentError` is raised with
   `argument == "cursor"`, `detail` containing the original message,
   category `RECOVERABLE`, and the original `ValueError` as `__cause__`.
   **Given** the same client `ValueError` but **When**
   `tools.list_prefix("user")` (no cursor), **Then** the same `ValueError`
   object propagates unchanged: with no cursor there is no agent argument
   to blame.
2. **Given** `append_line` with a `line` for which `parse_fact(line) is
   None` (not a single fact line), **Then** the tool raises
   `InvalidArgumentError(argument="line")` itself, after `check_write` and
   the type and UTF-8 checks, with no `__cause__` and no client call.
   **Given** `replace_fact` with `old_string == ""`, **Then** the tool
   raises `InvalidArgumentError(argument="old_string")` itself, likewise
   with no `__cause__` and no client call. **Given** a well-formed `line` /
   non-empty `old_string` and the client's `append_line` / `replace_fact`
   raises `ValueError`, **Then** the same `ValueError` object propagates
   unchanged (no conversion).
3. **Given** the client raises `MetadataFormatError` or
   `UnicodeDecodeError` (both `ValueError` subclasses) from any tool,
   **Then** it propagates unchanged, never converted.
4. **Given** `InvalidArgumentError("cursor", "bad")`, **Then** it is a
   `RecoverableError`; `argument == "cursor"`; `detail == "Argument
   cursor is invalid: bad"` (the composed sentence, as every other
   `WenchangError` stores in `detail`); `str(err)` starts with that
   sentence and ends with the recoverable guidance text; an empty
   `argument` raises `ValueError`; a non-`str` `argument` raises
   `TypeError`.
5. **Given** the client raises `ValueError` from `read_file`,
   `delete_file`, `write_file`, `get_memory_index`, `append_line`,
   `replace_fact`, or `list_prefix` called without a cursor, **Then** it
   propagates unchanged (and `render_error` renders it as `"internal
   error"`): the only client-side conversion is `list_prefix` with a
   cursor (US4.1), and the tool layer never guesses.
6. **Given** the tool layer's own rejections (US2.5–6), **Then** the
   `argument` is exactly one of `"scope"`, `"area"`, `"name"`; for
   `build_path`/`build_prefix` failures the original `ValueError` is the
   `__cause__`; the ungranted-scope rejection and the `line` /
   `old_string` pre-validations (US4.2) have no `__cause__` (they are
   raised directly, not converted).

---

### User Story 5 - Tool descriptions and enumeration (Priority: P1)

**Acceptance Scenarios**:

1. **Given** `TOOL_NAMES`, **Then** it is the tuple `("get_memory_index",
   "read_file", "list_prefix", "write_file", "append_line",
   "replace_fact", "delete_file")`.
2. **Given** `tools.tools()`, **Then** it is a `Mapping[str, Callable[...,
   object]]` with exactly `TOOL_NAMES` as keys in that order, each value
   being the bound method of the same name (`value.__self__ is tools`,
   `value.__name__ == name`). A fresh mapping each call; read-only
   (`MappingProxyType`).
3. **Given** every tool method, **Then** its docstring is non-empty and
   its first line is a single sentence (the short description a host
   shows): the first line, stripped, ends with `"."` and contains no
   `". "`.
4. **Given** the docstrings of `write_file`, `append_line`,
   `replace_fact`, and `delete_file`, **Then** each contains the word
   `routine` and the phrase `expected_version`, and describes a version
   conflict as something to merge and retry, not a failure.
5. **Given** the `write_file` docstring, **Then** it states that a
   per-file byte ceiling applies and that an oversize write is rejected
   with the current size and limit, and that `description` and `aliases`
   replace the stored values; it contains the literal `not merged`.
   **Given** the
   `append_line` docstring, **Then** it states the line must be a single
   fact line with a leading bracketed label and names the four labels.
   **Given** the `replace_fact` docstring, **Then** it states the anchor
   must match exactly once. **Given** the `append_line` and
   `replace_fact` docstrings, **Then** each states that the per-file byte
   ceiling applies to the result.
6. **Given** the `get_memory_index` docstring, **Then** it mentions
   `capped` and `list_prefix`. **Given** every mutating tool's docstring,
   **Then** it states that `system/` is read-only.
7. **Given** `src/wenchang/tools.py`, **Then** no docstring or comment
   matches `AIE-\d+`.
8. **Given** the docstring of every tool that takes `name`, **Then** it
   names the `scope`, `area`, and `name` arguments and states that `name`
   excludes `.md`. **Given** the `get_memory_index` docstring, **Then** it
   explains that an index path `scope/<entity>/area/name.md` maps to the
   arguments `scope`, `area`, `name` (the entity segment is filled in by
   the tools), and that a capped prefix is paged with `list_prefix(scope,
   area)`; it contains the literal strings `read_file(scope, area, name)`
   and `list_prefix(scope, area)`.

---

### User Story 6 - Module boundaries (Priority: P1)

**Acceptance Scenarios**:

1. **Given** `src/wenchang/tools.py`, **When** parsed with `ast`, **Then**
   its `wenchang` imports are only `core`, `errors`, `file_format`,
   `identity`, `paths`, `scope`, `transport`, and `version_token`, all at
   module level. It imports nothing from `wenchang.storage` or `google`.
2. **Given** `core.py`, `scope.py`, `identity.py`, `transport.py`,
   **Then** none imports `wenchang.tools`.
3. **Given** `pyproject.toml`, **Then** `[project].dependencies ==
   ["google-cloud-storage>=2.18"]` (unchanged; no agent framework added).

---

### User Story 7 - Rendering results and errors for the agent (Priority: P1)

`render_result` and `render_error` are module-level functions in
`wenchang.tools`. Their output is JSON-safe: `json.dumps(out)` succeeds and
`json.loads(json.dumps(out)) == out` for every case below. A file's
rendered fields are `path`, `scope`, `area`, `name` (from
`parse_path(path)`, so the path → arguments mapping is in the data:
`name` excludes `.md`), `version` (`str`), `description`, `aliases`
(list, stored order), `sources` (sorted list), and `last_updated`
(ISO-8601 UTC ending in `Z`, the exact string
`metadata_to_map(metadata)[LAST_UPDATED_KEY]` produces); a `MemoryFile`
adds `content`. If `parse_path` raises `ValueError` on an entry's path
(malformed path from a remote client), `scope`, `area`, and `name` are
`None` and rendering continues. An `aliases` or `sources` member that is
not a JSON-safe string is dropped from the rendered list rather than
raising, and a `path`, `content`, `version`, `description`, or
`next_cursor` that is not an exact `str` is dropped from the output.
`render_result` never raises for any value of a supported type, and its
output is always JSON-serializable. Host contract: every tool failure is renderable —
`render_error` accepts any `Exception` and never raises, so a host
adapter wraps each tool call in `except Exception as exc: return
render_error(exc)`.

**Acceptance Scenarios**:

1. **Given** a `MemoryFile` with aliases `("b", "a")`, sources
   `frozenset({"z", "y"})`, `last_updated` `2026-10-02T12:00:00+02:00`,
   path `user/u-1/notes/a.md`, **When** `render_result(file)`, **Then**
   the result is `{"path": "user/u-1/notes/a.md", "scope": "user", "area":
   "notes", "name": "a", "content": ..., "version": <str>, "description":
   ..., "aliases": ["b", "a"], "sources": ["y", "z"], "last_updated":
   "2026-10-02T10:00:00Z"}` and `type(result["version"]) is str`.
2. **Given** a `ListPage` with two entries and a cursor, **Then**
   `{"entries": [<file fields without content>, ...], "next_cursor":
   <str>}`, entries in page order; **given** `next_cursor=None`, **Then**
   `"next_cursor": None`.
3. **Given** a `MemoryIndex` with entries and `capped =
   (CappedPrefix("user/u-1/notes/", 3),)`, **Then** `{"entries": [...],
   "capped": [{"prefix": "user/u-1/notes/", "scope": "user", "area":
   "notes", "omitted": 3}]}`. A capped row's `scope` is the prefix's first
   segment and `area` its third, or `None` for a scope-level (`"user/"`)
   or entity-level (`"user/u-1/"`) prefix. **Given** `MemoryIndex()`,
   **Then** `{"entries": [], "capped": []}`.
4. **Given** `None` (the `delete_file` result), **Then** `{"ok": True}`.
5. **Given** any other value (a `str`, a `dict`, a `FileEntry` alone),
   **Then** `TypeError`.
5a. **Given** a `ListPage` (built with `FileEntry` directly, bypassing
   core) whose entry path is `"not-a-path"`, **Then** that entry renders
   with `"path": "not-a-path"`, `"scope": None`, `"area": None`, `"name":
   None` and the other fields as usual; no exception. **Given** an entry
   (or `MemoryFile`) whose metadata `aliases` or `sources` holds a member
   that is not a JSON-safe string (e.g. an `int`, or an object with a
   raising `__str__`), **Then** that member is dropped from the rendered
   list, the remaining members render as usual, and no exception is
   raised. **Given** a `MemoryFile`, entry, or `ListPage` (built
   directly, bypassing core) whose `path`, `content`, `version`,
   `description`, or `next_cursor` is not an exact `str` (e.g. an `int`;
   `next_cursor=None` still renders as `None`), **Then** that
   field is absent from the output, the other fields render as usual, no
   exception is raised, and `json.dumps(out)` succeeds.
6. **Given** any `WenchangError` `exc` (`render_error(exc: Exception)`),
   **When** `render_error(exc)`,
   **Then** the result has `error == type(exc).__name__`, `category ==
   exc.category.value`, and `message == str(exc)`, followed by every
   payload attribute the instance has with a non-`None` value, from the
   fixed list `path`, `content`, `version`, `size`, `limit`,
   `match_count`, `reason`, `scope`, `required_roles`, `argument`, and no
   other keys.
7. **Given** `VersionConflictError(path, content, version)`, **Then** the
   result includes `path`, `content`, and `version` (as `str`), so the
   agent can merge and retry. **Given** `OversizeWriteError`, **Then**
   `path`, `size`, `limit` (ints). **Given** `ReplaceFactMatchError`,
   **Then** `path`, `content`, `version`, `match_count`.
8. **Given** `NotFoundError(path, FILE_ABSENT)`, **Then** `path` and
   `reason == "file_absent"`. **Given** `BackendUnavailableError(TIMEOUT)`,
   **Then** `reason == "timeout"` and `category == "transient"`.
9. **Given** `RestrictedScopeError(ROLE_REQUIRED, required_roles=
   frozenset({"owner", "admin"}))`, **Then** `path`, `scope`, `reason ==
   "role_required"`, `required_roles == ["admin", "owner"]`. **Given**
   `SYSTEM_READ_ONLY`, **Then** no `required_roles` key.
10. **Given** `InvalidArgumentError("scope", ...)`, **Then** `argument ==
    "scope"`, `category == "recoverable"`. **Given**
    `ResolverFailureError()`, **Then** only `error`, `category`,
    `message`.
11. **Given** `MetadataFormatError` or `UnicodeDecodeError` (data-integrity
    errors on the documented contract), **Then** `render_error` returns
    exactly `{"error": <type name>, "category": "internal", "message":
    str(exc)}`. **Given** any other non-`WenchangError` exception
    (`ValueError("secret detail")`, `RuntimeError("boom")`), **Then** it
    returns `{"error": <type name>, "category": "internal", "message":
    "internal error"}` — a fixed message, so off-contract exceptions do
    not leak internals to the agent (e.g. `{"error": "RuntimeError",
    "category": "internal", "message": "internal error"}`).
12. **Given** a hostile exception — a subclass whose `__str__` raises, and
    one whose metaclass makes `__name__` raise — **Then** `render_error`
    never raises: the type name and message are read through guards,
    falling back to `"<unnamed>"` and `"<unreadable>"` respectively (the
    message guard matters for `WenchangError`, `MetadataFormatError`, and
    `UnicodeDecodeError`, whose `str(exc)` is rendered); both are exact
    `str`. **Given** a `WenchangError` subclass whose `category` is
    missing, raises on access, or is not an `ErrorCategory` member,
    **Then**
    `render_error` falls back to the off-contract rendering `{"error":
    <type name>, "category": "internal", "message": "internal error"}`.
    **Given** a `WenchangError` whose payload attribute holds a value that
    is not JSON-safe, **Then** that field is dropped and the rest render.
    Payload values are rendered only if they are an exact `str`, an `int`
    that is not a `bool`, an `Enum` member (rendered as its value), or a
    `frozenset` of `str` (rendered sorted); anything else is dropped.

### Edge Cases

- `MemoryTools` is per session: one resolved identity, fixed for its
  lifetime. A host that serves many sessions constructs one per session
  via `bind_tools`. The transport client may be shared.
- `source` is the calling surface's name (Notion §4 `sources`), fixed per
  `MemoryTools`; the agent cannot set it.
- The tool layer validates `scope` (granted), `area`, and `name` (via
  `build_path`/`build_prefix`), `description`, `aliases`, the real type of
  every agent-supplied argument, UTF-8 encodability of `scope`, `area`,
  `name`, `description`, `aliases` members, `content`, `line`, and
  `new_string`, that `line` is a single fact line, and that `old_string`
  is non-empty; beyond that it does not validate `content` etc., and
  converts only one client `ValueError` (`list_prefix` with a cursor). A
  wrongly typed agent argument is always
  `InvalidArgumentError` naming it, never `TypeError` (US3.10): a host
  schema may be loose, and the agent can repair the call. `TypeError`
  remains only for adopter-side mistakes (constructor arguments).
- A scope listed in `identity.grants` is always a valid segment (Identity
  validates it) and its entity ID too (ScopeGrant validates it), so path
  building can fail only on `area` or `name`.
- `MemoryIndex` and `ListPage` paths are full paths including the entity
  segment; `render_result` also emits each entry's `scope`, `area`, and
  `name` (US7), and the docstrings describe the mapping (US5.8). A
  `capped` prefix of the form `scope/<entity>/` maps to
  `list_prefix(scope)`.
- `expected_version` is a `VersionToken` (`NewType` over `str`); the agent
  passes back the string it received. Tools never inspect it.
- Tool methods return core value types; `render_result`/`render_error`
  produce the agent-facing form, and a host adapter calls them.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `wenchang.tools` MUST export `MemoryTools`, `bind_tools`,
  `TOOL_NAMES`, `render_result`, and `render_error`.
- **FR-002**: Every mutating tool MUST call `scope.check_write(path,
  identity, policy)` on the built path before calling the client, and MUST
  NOT call the client when it raises. `read_file`, `list_prefix`, and
  `get_memory_index` MUST NOT call `check_write`.
- **FR-003**: Every tool MUST forward to the client as in US2–3 and return
  the client's result unchanged.
- **FR-004**: `wenchang.errors` MUST export `InvalidArgumentError(argument:
  str, detail: str)`, a `RecoverableError` with attribute `argument`
  (`TypeError` for a non-`str` `argument`, `ValueError` for an empty one,
  US4.4). The tool layer raises `InvalidArgumentError` from exactly these
  sources, and no others:
  (a) **one client `ValueError` converted**, chained as `__cause__`: from
  the client's `list_prefix` → `cursor`, only when a cursor was passed
  (US4.1); every other client `ValueError` propagates unchanged (US4.1,
  US4.2, US4.5), and `MetadataFormatError` and `UnicodeDecodeError` pass
  through unconverted;
  (b) **path-building `ValueError`s converted**, chained: `build_path` /
  `build_prefix` → `area` or `name` (US2.6); `FileMetadata`'s newline
  check → `description` (US3.8);
  (c) **`UnicodeEncodeError` from the tool's own UTF-8 check**, chained:
  `scope`, `area`, `name`, `description`, `aliases` members, `content`,
  `line`, `new_string` (US2.8, US3.8, US3.9, US3.11);
  (d) **the tool's own checks, raised directly (no `__cause__`)**: wrong
  real type of any agent argument, with detail `f"{argument} must be a
  string, not {type_name}"` (US3.10; never `TypeError`); malformed
  `aliases` (US3.9); a `description` containing any `str.splitlines`
  line boundary (US3.8); a `line` that is not a single fact line and an
  empty `old_string` (US4.2); ungranted `scope` (FR-008).
  `str` subclasses MUST be normalized with `str.__str__`.
- **FR-008**: Every tool that takes `scope` MUST reject a scope not in
  `identity.grants` with `InvalidArgumentError("scope", f"scope {scope!r}
  is not available in this session; available scopes: {',
  '.join(sorted(identity.grants))}")` before building any path, and MUST
  build paths only with `paths.build_path(scope, entity_id, area, name)` /
  `paths.build_prefix(scope, entity_id, area)` where `entity_id =
  identity.grants[scope].entity_id` (read directly, never via
  `Identity.entity_id()`, US2.9). No tool accepts a path, prefix, or
  entity ID from the agent.
- **FR-009**: `render_result` and `render_error` MUST behave as in US7 and
  produce JSON-safe output. `render_result` raises `TypeError` for an
  unsupported value type and never raises for any value of a supported
  type; its output is always JSON-serializable. A malformed entry path
  renders `scope`/`area`/`name` as `None`; non-JSON-safe
  `aliases`/`sources` members are dropped; and `path`, `content`,
  `version`, `description`, or `next_cursor` that is not an exact `str`
  is dropped from the output (US7.5a). Capped rows carry `scope` and
  `area` (US7.3). `render_error` accepts any `Exception` and
  never raises (guarded type name and message; a `WenchangError` subclass
  whose `category` is missing, raises, or is not an `ErrorCategory` member
  falls back to the internal
  rendering; non-JSON-safe payload fields are dropped, US7.12); exceptions
  outside the taxonomy and the two data-integrity types render the fixed
  message `"internal error"` (US7.11).
- **FR-005**: `bind_tools` MUST be the only function in `tools` that takes
  credentials, MUST obtain the identity via `resolve_identity`, and MUST
  NOT retain the credentials.
- **FR-006**: Tool docstrings MUST satisfy US5.3–6 and US5.8 and cite no
  Linear IDs.
- **FR-007**: `tools` MUST add no runtime dependency.

## Success Criteria *(mandatory)*

- **SC-001**: Every scenario has a test citing AIE-1044; `make check`
  passes.
- **SC-002**: One end-to-end test runs `bind_tools` with
  `SandboxResolver` over a tests-only `_StoreClient` wrapping
  `MemoryStore(InMemoryStorage())`. `_StoreClient` forwards the six
  `MemoryStore` operations unchanged; its `get_memory_index(scope_map)`
  records the `scope_map` it receives and returns `MemoryIndex()`; and
  `isinstance(client, TransportClient)` holds. The test exercises create,
  read, append, replace, list, index, delete, plus one `system/`
  rejection, one `ROLE_REQUIRED` rejection, and one ungranted-scope
  rejection, and asserts: the recorded `scope_map == {"user": "u-1",
  "org": "o-9"}`; the read-back metadata has `sources ==
  frozenset({"test-surface"})` and `last_updated != datetime(1970, 1, 1,
  tzinfo=UTC)`; each result through `render_result` and each error
  through `render_error` passes `json.dumps`. Follow-up (not a runtime
  choice): switch to `InProcessClient` after rebasing on AIE-1046.

## Human decisions (2026-10-02)

Raised by the adversarial spec review; each changed the public tool API.

1. **How does the agent learn its own entity IDs? → (c) scope-relative
   tools.** Tools take `(scope, area, name)` and build the path with
   `build_path(scope, identity.grants[scope].entity_id, area, name)`, so
   the agent never has to type an entity ID. This matches Notion §6 ("uses
   the returned fields to build the path prefix"). An ungranted scope is
   the recoverable `InvalidArgumentError("scope")`; `NOT_GRANTED` is
   unreachable through the tools. Consequence: reads and listing reach only
   the caller's own entity in each granted scope, which decides the read
   scoping ADR 0017 left to this layer as "own entity only". Rejected: (a)
   full paths with prefixes from adopter prompt text; (b) exposing the
   scope map to the agent.
2. **Who formats results and errors? → (a) tool-layer rendering
   helpers.** `render_result` and `render_error` (US7) produce JSON-safe
   dicts including the repair material that `str(err)` omits; a host
   adapter calls them. This satisfies Notion §7's "format the response"
   while the tool methods stay typed. Rejected: (b) tools return/raise
   rendered payloads; (c) hosts format.
The remaining three proceed with the recommended defaults as orchestrator
calls, pending PR review:

3. **Server object (§7) → deferred to AIE-1060.** §7's wording is
   conditional on the host framework, and a server pulls a framework
   dependency into every adopter. This issue ships `tools()` for a host to
   decorate.
4. **Byte-ceiling number → generic docstring statement.** The docstring
   states that a per-file byte ceiling applies; the number reaches the
   agent through `OversizeWriteError.limit` (rendered by `render_error`)
   and adopter prompt text.
5. **`InvalidArgumentError` as a new recoverable kind → yes.** ADR 0010
   deferred exactly this mapping here, and it is tool-layer only.

## Adversarial code review (2026-10-02)

The code review of the implementation changed these scenarios: US2.3
(index scope map built from `grants`), US4.1, US4.2, US4.5, US4.6, and
FR-004(a) (conversions narrowed to `list_prefix` with a cursor; `line` and
`old_string` pre-validated), US3.8 (every `str.splitlines` boundary),
US3.9 and US3.11 (alias members UTF-8-checked; real-type `Sequence`
check), US7.5a, US7.12, and FR-009 (rendering never raises on hostile
metadata or `WenchangError` subclasses). It also raised two points outside
this issue's scope, recorded in ADR 0022 Consequences:

- **Lookalike `system` areas are writable.** `System`, a Cyrillic `ѕ`, or
  a name containing a zero-width (`Cf`) character passes the exact
  `system` comparison in `scope` and `paths`. This is a policy question
  for the human: NFKC/casefold rejection in the tool, or `Cf` rejection in
  `paths`. Open.
- **`resolve_identity`'s `from None` keeps `__context__`.** It suppresses
  display of the original exception but leaves it reachable as
  `__context__`, with the frame holding the credentials, to error
  reporters that walk the chain. A follow-up for `identity`.

## Assumptions

- One `MemoryTools` per session with identity resolved once at binding
  (consistent with ADR 0019: credentials bind at construction).
- Tool method parameter order is `scope, area, name` first and
  `expected_version` last so the mandatory arguments read naturally in a
  generated schema.
- Branch must be rebased onto the final `AIE-1048-transport-interface`
  commit before building (done 2026-10-01). ADR number **0022**: 0020 is
  AIE-1046's and 0021 is AIE-1047's, both of which land first.
