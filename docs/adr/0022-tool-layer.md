# 0022. Tool layer

Date: 2026-10-02

## Status

Accepted

## Context

The Notion spec sets out the agent-facing tool layer across several
sections:

- Section 7: "The agent-facing tool layer is thin and transport-agnostic.
  Tool bodies contain no logic; they call an abstract client interface and
  format the response." For mounting into a host, "the library ships as its
  own server instance with the memory tools decorated onto it, each
  carrying a docstring as its description."
- Section 6: "Tool code never touches a credential. It calls the resolver
  and uses the returned fields to build the path prefix and to check write
  eligibility against any write-restricted scope."
- Section 3: the `system/` area is read-only to the agent, "enforced at the
  tool layer".
- Section 5: "A version conflict is routine coordination, not an error path
  ... Agent-facing tool descriptions must present it as routine, or the
  agent treats a conflict as failure and abandons the write." The per-file
  limit "is also stated to the agent up front."
- Section 1, design principle 1: "Tools are reliable verbs with no embedded
  policy. Anything requiring judgment lives in prompt text layered on top,
  never in tool code."

AIE-1044 defines that layer: `read_file`, `write_file`, `append_line`,
`replace_fact`, `list_prefix`, `delete_file`, and `get_memory_index` as
callable tools over the transport client (ADR 0019) and the scope model
(ADRs 0016, 0017). The pieces it builds on exist: `TransportClient`,
`Identity` / `IdentityResolver` / `resolve_identity` (ADR 0014), the path
builders (ADR 0015), `check_write` and `ScopePolicy` (ADRs 0016, 0017), and
the error taxonomy (ADR 0005). Three earlier ADRs leave work here. ADRs
0016 and 0017 put write enforcement in the tool layer and require its tests
to show that every mutating tool calls the check. ADR 0017 decision 8
leaves read scoping, "if any", to the tool layer, and decision 11 requires
the tool to pass storage the same exact `str` the check validated. ADR 0010
leaves the agent-facing mapping of core's plain `ValueError`s (for example
a malformed cursor) to the tool layer. ADR 0019 decision 7 requires a
conforming client to surface every transport failure as
`BackendUnavailableError`, which this layer relies on when rendering
errors.

An adversarial spec review raised two questions that changed the public
tool API, and the human decided both on 2026-10-02:

1. **How does the agent learn its own entity IDs?** With path-taking
   tools, the agent would have to type `scope/<entity_id>/area/name.md`
   with an entity ID it can only learn from adopter prompt text or from an
   exposed scope map. Decided: **(c) scope-relative tools**, which take
   `(scope, area, name)` and build the path themselves.
2. **Who formats results and errors?** Tools return core value types, and
   `str(err)` omits the repair material (current content, version, size,
   limit) that Section 5's merge-and-retry loop needs. Decided: **(a)
   tool-layer rendering helpers** that a host adapter calls.

The orchestrator made three further calls at the spec checkpoint, which
are pending human confirmation at PR review:

3. Section 7's server object is deferred to AIE-1060.
4. The byte-ceiling number is not written into the docstrings.
5. `InvalidArgumentError` joins the taxonomy as a new recoverable kind.

## Decision

Add `src/wenchang/tools.py` exporting `MemoryTools`, `bind_tools`,
`TOOL_NAMES`, `render_result`, and `render_error`, and add
`InvalidArgumentError` to `src/wenchang/errors.py`. No other module
changes. `tools` imports from `wenchang` only `core`, `errors`,
`file_format`, `identity`, `paths`, `scope`, `transport`, and
`version_token`, and none of `core`, `scope`, `identity`, or `transport`
imports it.

1. **Framework-agnostic `MemoryTools` with plain methods and docstrings,
   and no runtime dependency.** Section 7 wants tools "decorated onto" a
   server with docstrings as descriptions. The decoration belongs to a host
   adapter; the verbs and descriptions belong to the library. `tools()`
   gives a host the seven bound methods by name.
   - **Rejected: depending on a specific framework** (for example an MCP
     server library) here. That fixes the host choice for every adopter,
     and it can't be tested until AIE-1060's smoke test.
   - **Rejected: a JSON-schema generator**, which duplicates what every
     framework already derives from signatures.
2. **One `MemoryTools` per session, with identity resolved once in
   `bind_tools`.** Section 6 says tool code never touches a credential.
   `bind_tools(client, resolver, credentials, policy, *, source)` is the
   only function that sees credentials, and it uses them only to call
   `resolve_identity`; nothing reachable from the returned tools retains
   them. `source`, the calling surface's name, is fixed per instance, so
   the agent can't set it. Constructor arguments are adopter-side, so a
   wrong type raises `TypeError` and an empty `source` raises `ValueError`.
   - **Rejected: per-call credentials**, which give every tool a parameter
     the agent must not control.
   - **Rejected: resolving lazily on first use**, which moves a permanent
     failure from session start to mid-conversation.
3. **`check_write` runs on the built path before every mutating client
   call. Reads, listing, and the index are not checked.** ADRs 0016 and
   0017 put write enforcement here. The check runs before any client call,
   so a rejected write never reaches the transport, and the client receives
   the same path object the check validated (ADR 0017 decision 11). The
   check still runs even though path building (decision 9) makes
   `NOT_GRANTED` and `INVALID_PATH` unreachable, because it is the single
   place the `system/` and role rules live.
   - **Rejected: checking after a dry-run read**, which costs a wasted
     round trip and opens a time-of-check/time-of-use window.
   - **Rejected: skipping `check_write` because the path is tool-built**,
     which would duplicate the `system/` and role rules here.
4. **`write_file` takes `description` and `aliases`, not a
   `FileMetadata`.** The agent controls exactly those two fields (Section
   4). The tool builds `FileMetadata(description, tuple(aliases),
   frozenset(), datetime(1970, 1, 1, tzinfo=UTC))`. Core stamps
   `last_updated` over the placeholder and unions the tool's fixed `source`
   into `sources`.
   - **Rejected: exposing `sources` to the agent**, which would let one
     surface impersonate another.
   - **Rejected: exposing `last_updated`**, which core overrides anyway.
5. **`InvalidArgumentError(argument, detail)` is a new recoverable
   error.** Core raises plain `ValueError` for a malformed `cursor`, a
   non-fact `line`, and an empty `old_string`, and ADR 0010 deferred the
   agent-facing mapping to this layer. A `ValueError` has no category, so
   the agent can't tell that it should retry. A recoverable error that
   names the argument gives it repair material. `detail` holds the composed
   sentence `Argument {argument} is invalid: {detail}`, as every other
   `WenchangError` stores its full sentence. A non-`str` `argument` raises
   `TypeError`, an empty one raises `ValueError`, and a `str` subclass is
   stored as an exact `str`.
   The tool pre-validates `line` (`parse_fact(line) is not None`) and
   `old_string` (non-empty) and raises `InvalidArgumentError` itself, with
   no `__cause__`, before any client call. Each rule is a single call, and
   checking it first means a `ValueError` from those client calls is never
   guessed to be the agent's fault. The cursor can't be checked without
   decoding it against the prefix, so a client `ValueError` from
   `list_prefix` is converted to `cursor`, chained as `__cause__` (core's
   messages carry no secrets), but only when a cursor was passed.
   `MetadataFormatError` and `UnicodeDecodeError` are `ValueError`
   subclasses but data-integrity failures (ADRs 0006, 0007), so they pass
   through unconverted.
   - **Rejected: `NotFoundError(INVALID_PATH)` for a bad cursor**, which
     gives the wrong repair: the path is fine.
   - **Rejected: converting every client `ValueError` from `append_line`
     and `replace_fact`**, the original design. An adversarial code review
     showed this blames the agent for any other `ValueError` those calls
     raise.
6. **Conversion is per tool and per argument, never a blanket `except
   ValueError`.** Exactly these sites convert: `list_prefix` with a cursor
   (→ `cursor`), `build_path` / `build_prefix` (decision 9), and
   `FileMetadata`'s newline check on `description`. Any other client
   `ValueError`, including from `append_line`, `replace_fact`, and
   `list_prefix` without a cursor, propagates unchanged and renders as
   `"internal error"`.
   - **Rejected: one wrapper around every client call**, which would hide
     a core bug as an agent error.
7. **`TOOL_NAMES` is ordered index, read, list, write, append, replace,
   delete.** Bootstrap comes first, then reads, then writes in increasing
   destructiveness, which is the order a host should list them in.
8. **The agent-facing docstrings are the tool descriptions.** Each first
   line is one sentence, the short description a host shows. The mutating
   tools present a version conflict as routine (Section 5): "the error
   carries the current content and version; merge your change into it and
   retry with that version." The docstrings also state the byte ceiling,
   that `system/` is read-only, the fact-line syntax and its four labels,
   the exactly-once anchor rule, that `description` and `aliases` are "not
   merged", and the `(scope, area, name)` arguments with `name` excluding
   `.md`. The `get_memory_index` docstring explains how an index path
   `scope/<entity>/area/name.md` maps to `read_file(scope, area, name)` and
   how a capped prefix is paged with `list_prefix(scope, area)`. Tests pin
   the phrases a host must not lose, and the module cites no Linear IDs.
   - **Note (2026-10-07, AIE-1165).** The shared mechanics listed above
     (the `(scope, area, name)` arguments, `name` excluding `.md`, the slug
     rule, `system/` being read-only) are now stated once, in the
     `get_memory_index` docstring, rather than in every tool's; each
     mutating tool keeps its own version-conflict sentence. See
     [ADR 0025](0025-prompt-layer-sections-and-slots.md) decision 11.
9. **Scope-relative tools, so the tool builds every path (human decision
   1c).** File tools take `scope`, `area`, and `name`; `list_prefix` takes
   `scope`, an optional `area`, and an optional `cursor`. The tool checks
   `scope in identity.grants` and then calls `build_path(scope, entity_id,
   area, name)` or `build_prefix(scope, entity_id, area)` with `entity_id =
   identity.grants[scope].entity_id`. Section 6 says tool code "uses the
   returned fields to build the path prefix". The tool reads the grant
   directly and never calls `Identity.entity_id()`, so an `Identity`
   subclass overriding that method can't redirect reads or writes to
   another entity. For the same reason, `get_memory_index` builds its scope
   map from the grants (`{s: g.entity_id for s, g in grants.items()}`) and
   never reads the overridable `scope_map` property. An ungranted scope
   raises `InvalidArgumentError("scope", "scope '<scope>' is not available
   in this session; available scopes: <sorted, comma-separated>")` before
   any path is built. It is recoverable because the error itself lists the
   scopes the agent can use. A `build_path` / `build_prefix` `ValueError` becomes
   `InvalidArgumentError` naming `area` if `area` fails `is_valid_segment`,
   and `name` otherwise; scope and entity ID are already valid because
   `Identity` and `ScopeGrant` validate them. `build_path` appends `.md`
   unconditionally, so `name` is documented as excluding it but a name
   ending in `.md` is not rejected.
   - **Rejected: full paths with entity prefixes supplied by adopter prompt
     text**, which makes the tools depend on milestone 4's prompt work and
     admits a whole class of agent path errors.
   - **Rejected: exposing the scope map to the agent**, which still makes
     the agent type entity IDs.
   - **Rejected: `RestrictedScopeError(NOT_GRANTED)` for an ungranted
     scope**, which is permanent, though the agent can recover by choosing
     another scope.
10. **Reads are scoped to the caller's own entity.** This decides the read
    scoping ADR 0017 left to the tool layer, and it follows from decision
    9: no tool accepts an entity ID, so reads and listing reach only the
    caller's own entity in each granted scope. Shared content lives under
    the scope entity the caller is granted (for example the `org` entity),
    so nothing a session should read is lost. `scope` itself still never
    checks reads.
    - **Rejected: a separate, unchecked read tool taking a full path**,
      which would reopen the entity-ID problem decision 9 closes.
11. **Tool-layer rendering helpers (human decision 2a).**
    `render_result(value)` and `render_error(exc)` turn a tool's result, or
    any exception, into a JSON-safe `dict`. This is Section 7's "format the
    response". The methods stay typed and testable, and a host adapter
    calls the helpers.
    - A file renders as `path`, `scope`, `area`, `name`, `version`,
      `description`, `aliases`, `sources` (sorted), and `last_updated`,
      plus `content` for a `MemoryFile`. `last_updated` uses
      `metadata_to_map`'s form, so the agent sees the timestamp as storage
      holds it. `scope`, `area`, and `name` come from `parse_path`, so the
      path-to-arguments mapping is in the data and not only in docstrings.
      A malformed entry path renders them as `None` instead of raising.
      Capped index rows carry `prefix`, `scope`, `area` (`None` for a
      scope- or entity-level prefix), and `omitted`. A `ListPage` renders
      `entries` and `next_cursor`, and `None` renders `{"ok": True}`.
    - `render_error` copies from a fixed list of ten attributes (`path`,
      `content`, `version`, `size`, `limit`, `match_count`, `reason`,
      `scope`, `required_roles`, `argument`), never `vars(exc)`, so
      `detail` and `__cause__` stay hidden. That carries the repair
      material `str(err)` omits, which keeps Section 5's merge-and-retry
      loop intact.
    - Host contract: every tool failure is renderable. `render_error`
      accepts any `Exception` and never raises. The type name and message
      are read through guards, with fallbacks `"<unnamed>"` and
      `"<unreadable>"`. `MetadataFormatError` and `UnicodeDecodeError`
      render as `{"error": <type name>, "category": "internal", "message":
      str(exc)}`. Any other exception outside the taxonomy renders the
      fixed message `"internal error"`, so an off-contract exception
      doesn't leak internals to the agent. So does a `WenchangError`
      subclass whose `category` is missing, raises, or is not an
      `ErrorCategory` member. A payload value renders only if it is an
      exact `str`, an `int` that is not a `bool`, an `Enum` member (as its
      value), or a `frozenset` of `str` (sorted); otherwise that field is
      dropped. `render_result` never raises for any value of a supported
      type, and its output is always JSON-serializable: it drops
      `aliases` or `sources` members that are not JSON-safe strings, and
      drops a `path`, `content`, `version`, `description`, or
      `next_cursor` that is not an exact `str`. A dropped `path` takes
      `scope`, `area`, and `name` with it, whereas a malformed `str` path
      still renders those three as `None`. Container fields are guarded
      too: a `metadata` that is not a `FileMetadata`, `aliases` or
      `sources` that are not iterable, or a `last_updated` that is not a
      `datetime` is dropped (keys omitted), and `entries` or `capped` that
      are not iterable render as empty lists. A `capped` row whose `prefix`
      is not a `str` or whose `omitted` is not an `int` is skipped, and a
      naive `datetime` `last_updated` is dropped. This relies on ADR 0019
      decision 7: a conforming client surfaces every transport failure as
      `BackendUnavailableError`, so nothing the agent must act on arrives
      as an off-contract exception. A host needs one `except Exception` and
      no branching.
    - **Rejected: tools that return or raise rendered payloads**, which
      lose typed results for in-process callers and the end-to-end tests.
    - **Rejected: leaving formatting to each host.** Every host would have
      to rediscover which attributes matter, and one that renders
      `str(err)` breaks the conflict loop.
12. **Orchestrator calls pending PR review.** Section 7's server object is
    deferred to AIE-1060; the reading taken here is that "ships as its own
    server instance" depends on the host framework, and a server pulls a
    framework dependency into every adopter. The byte-ceiling number is not
    in the docstrings: the docstrings state that a per-file ceiling
    applies, and the number reaches the agent through
    `OversizeWriteError.limit` (rendered by `render_error`) and adopter
    prompt text. `InvalidArgumentError` joins the taxonomy (decision 5).
13. **One wrong-type rule for agent arguments.** Any agent-supplied
    argument whose real type (`issubclass(type(x), str)`) is wrong raises
    `InvalidArgumentError` naming it before any client call, never
    `TypeError`. That covers `scope`, `area`, `name`, `content`, `line`,
    `old_string`, `new_string`, `description`, a non-`None` `cursor`,
    `expected_version` (`None` is allowed only for `write_file`), and each
    `aliases` member. A bare `str` or `bytes` `aliases`, or a value whose
    real type is not a `Sequence` (`issubclass(type(x), Sequence)`, not the
    spoofable `isinstance`), is rejected too. `str` subclasses are
    normalized with `str.__str__`. The detail is `"{argument} must be a
    string, not {type_name}"`, with `type_name` read through a guarded
    helper. `scope`, `area`, `name`, `description`, each `aliases` member,
    `content`, `line`, and `new_string` are also checked for UTF-8
    encodability. A lone surrogate passes `is_valid_segment`, and core's
    `UnicodeEncodeError` (a `ValueError`) would otherwise reach the client
    as an uncategorized error. A `description` containing any line boundary
    `str.splitlines` recognizes is rejected, so a description is one line
    under every rule a reader might apply. Two layers share this: the tool
    itself rejects `\x0b`, `\x0c`, `\x1c`, `\x1d`, `\x1e`, `\x85`,
    `\u2028`, and `\u2029` before building the metadata (no `__cause__`);
    `\n` and `\r` are rejected by `FileMetadata`, whose `ValueError`
    surfaces as `InvalidArgumentError("description")` chained from it.
    A host schema may pass through whatever the model emitted, and a
    `TypeError` has no category, so the agent couldn't repair it.
    - **Rejected: treating `TypeError` as the host schema's concern**,
      which leaves the agent stuck when the host is loose.
14. **`area` is an ASCII slug; `name` rejects invisible characters
    (human decision, 2026-10-02).** `scope` compares the area to `system`
    exactly (ADR 0016 decision 2), and `paths` accepts any segment without
    a `Cc` character, so `System`, `ѕystem` with a Cyrillic `ѕ`, or
    `system` with a zero-width character inserted would otherwise be
    writable areas that look like `system/` to a human or a model. Every
    tool that takes `area` requires it to match `^[a-z0-9][a-z0-9_-]*$`
    (`list_prefix` only when an area is given). `name` stays Unicode, since
    names are human titles, but must not contain a `Cf` character,
    `\u2028`, `\u2029`, or a Unicode noncharacter (U+FDD0–U+FDEF, or a code
    point whose low 16 bits are `FFFE` or `FFFF`). A violation raises
    `InvalidArgumentError("area")` or `InvalidArgumentError("name")` with a
    detail naming the rule, no `__cause__`, and no client call. The check
    runs after the grant check and path building, so an `area` or `name`
    that `build_path` / `build_prefix` rejects keeps that chained error,
    and before `check_write`, so `system` itself still reaches the
    `SYSTEM_READ_ONLY` rule. Core `paths`, storage, and the transport are
    unchanged: files stored under a non-slug area remain valid and
    readable through core and the transport, but not through the tools.
    - **Rejected: NFKC normalization and casefolding before comparing to
      `system`**, which catches `System` and compatibility forms but misses
      cross-script confusables such as `ѕystem`.
    - **Rejected: rejecting only invisible (`Cf`) characters**, which
      leaves `System` and cross-script lookalikes writable.
    - **Rejected: restricting segments in core `paths`**, which changes
      storage semantics and invalidates existing stored data.

The resulting check order for every tool is: segment type check,
normalization, and UTF-8 check; grant check; path building; the `area`
slug and `name` character rules; for mutating tools, `check_write`; the
remaining arguments; the client call.

## Consequences

The `system/` read-only rule and the write restriction are now enforced on
the agent path. Tests show that every mutating tool calls `check_write` on
the built path before the client, that the client receives that same path
object, and that a rejected write never reaches the client. This meets the
obligation ADRs 0016 and 0017 recorded. Read scoping is settled as
own-entity-only.

The agent never types an entity ID, and a whole class of path mistakes
becomes either impossible or a recoverable `InvalidArgumentError` naming
the argument. The trade-off is that the tool signatures differ from
`TransportClient`'s: index and listing results carry full paths, while
tools take `(scope, area, name)`. `render_result` emits each entry's
`scope`, `area`, and `name`, and the docstrings describe the mapping, but a
host that skips `render_result` loses the former. A confused agent passing
`name="a.md"` creates `a.md.md`.

Milestone 4's prompt text, and the AIE-1059 and AIE-1060 issue text, still
describe path-based tools and must be updated for scope-relative
arguments. No tool reaches another entity's files; if an adopter ever needs
cross-entity reads, that would be a new decision.

`InvalidArgumentError` is a deviation from Section 5, which enumerates the
recoverable kinds without it. It is used only by the tool layer, so core
and transport error parity (ADR 0019) are unaffected.

Off-contract exceptions are not shown to the agent: `render_error` replaces
their message with `"internal error"`, so a host must log the original
exception itself if it wants it. A client that violates ADR 0019's
transport-failure mapping gives the agent an uncategorized internal error
rather than a transient one.

Tool docstrings are now part of the public contract, and the phrase tests
are brittle by design: they protect the agent-facing text from silent
edits.

The end-to-end test runs over a tests-only `_StoreClient` around a real
`MemoryStore`, whose `get_memory_index` returns an empty index. It moves to
the in-process client once that exists, which also exercises real index
semantics through the tools.

Lookalike `system` areas are not writable through the tools (decision 14).
An adopter's seed areas must be ASCII slugs to be reachable through the
tools.

An adversarial code review raised one point outside this layer's
decisions, still open:

- **`resolve_identity`'s `from None` keeps `__context__`.** `raise ...
  from None` suppresses display of the resolver's original exception, but
  the exception stays reachable as `__context__`, along with its traceback
  and the frame holding the credentials. An error reporter that walks the
  chain can see it. `bind_tools` passes `ResolverFailureError` through
  unchanged and `render_error` never reads `__context__`, so the agent
  never sees it, but a host's logging might. This is a follow-up for
  `identity` (ADR 0014), for example clearing `__context__` before
  raising.

The layer adds no dependency and no server object. Mounting it into a host
framework is AIE-1060's adapter and smoke test, built on `tools()`,
`render_result`, and `render_error`. A host that forgets to bind one
`MemoryTools` per session would share one identity across callers;
`bind_tools` makes the right thing the easy thing, but nothing prevents the
misuse.
