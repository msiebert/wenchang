# Implementation Plan: Tool layer

**Linear issue**: AIE-1044 | **Branch**: `AIE-1044-tool-layer` | **Date**: 2026-10-01 | **Spec**: [spec.md](spec.md)

## Summary

Add `src/wenchang/tools.py` (`MemoryTools` with scope-relative tools,
`bind_tools`, `TOOL_NAMES`, `render_result`, `render_error`) and
`InvalidArgumentError` in `src/wenchang/errors.py`. Five new test files.
Based on `AIE-1048-transport-interface`; PR targets that branch until it
merges.

## Technical Context

Python ≥ 3.12; pyright strict; ruff 100. `tools` imports `core`
(`FileEntry`, `ListCursor`, `ListPage`, `MemoryFile`, `MemoryIndex`),
`errors` (`InvalidArgumentError`, `WenchangError`), `file_format`
(`FileMetadata`, `LAST_UPDATED_KEY`, `MetadataFormatError`,
`metadata_to_map`, `parse_fact`), `identity` (`Identity`, `IdentityResolver`,
`resolve_identity`), `paths` (`build_path`, `build_prefix`,
`is_valid_segment`, `parse_path`), `scope` (`ScopePolicy`, `check_write`), `transport`
(`TransportClient`), `version_token` (`VersionToken`). No new
dependencies.

## Constitution Check

| Principle | Status |
| --------- | ------ |
| I. Tests-first | T1–T4 each test-writer → implementer |
| II. Tests not negotiable | No existing test changes |
| IV. Strict typing | `bind_tools[C]` generic; `cast(object, ...)` for runtime type checks |
| V. Storage only through interface | Never touches storage |
| VI. Spec fidelity | §7 thin tools over a client that "format the response" (`render_*`); §6 tool code builds the path from resolved fields and never touches a credential; §3 `system/` tool-layer enforcement; §5 routine-conflict descriptions. Framework-agnostic shape, scope-relative tools, read scoping, rendering, and `InvalidArgumentError` recorded in ADR 0022 |
| VII. Architecture documented | ARCHITECTURE.md tools entry, errors entry, diagram prose, invariants; ADR 0022 |
| VIII. Traceability | Test docstrings cite AIE-1044; shipped modules cite none |
| IX. Small PR | One new module, one new error class; no change to `core`, `scope`, `identity`, `paths` |

**Decisions to record in ADR 0022:**

1. **Framework-agnostic `MemoryTools` with plain methods and docstrings;
   no runtime dependency.** Notion §7 wants tools "decorated onto" a
   server with docstrings as descriptions. The decoration is a host
   adapter; the verbs and descriptions are the library's. `tools()` hands a
   host the seven bound methods by name. Rejected: depending on a specific
   framework (e.g. an MCP server library) here, which fixes the host
   choice for every adopter and cannot be tested until AIE-1060's smoke
   test; a JSON-schema generator, which duplicates what every framework
   derives from signatures.
2. **One `MemoryTools` per session, identity resolved once in
   `bind_tools`.** §6: "Tool code never touches a credential." Only
   `bind_tools` sees credentials and only to pass them to
   `resolve_identity`. Rejected: per-call credentials (every tool grows a
   parameter the agent must not control); resolving lazily on first use
   (moves the permanent failure from session start to mid-conversation).
3. **`check_write` on the built path before every mutating client call;
   no `check_write` on reads, listing, or index.** ADR 0016/0017 put write
   enforcement here. The check runs before any client call so a rejected
   write never reaches the transport, and it still runs even though path
   building already makes `NOT_GRANTED` and `INVALID_PATH` unreachable:
   it is the single place `system/` and role rules live. Rejected:
   checking after a dry-run read, which is a wasted round trip and a
   TOCTOU window; skipping `check_write` because the path is
   tool-built, which would duplicate the `system/` and role rules here.
4. **`write_file` takes `description` and `aliases`, not a
   `FileMetadata`.** The agent controls exactly those two fields (§4);
   `sources` is stamped from the tool's fixed `source` and `last-updated`
   by core. The tool builds `FileMetadata(description, tuple(aliases),
   frozenset(), _UNSET_TIMESTAMP)` where `_UNSET_TIMESTAMP = datetime(1970,
   1, 1, tzinfo=UTC)`; core overrides it. Rejected: exposing `sources` to
   the agent (it would let one surface impersonate another); exposing
   `last_updated` (core overrides it anyway).
5. **`InvalidArgumentError` is a new recoverable error.** Core raises
   plain `ValueError` for a malformed `cursor`, a non-fact `line`, and an
   empty `old_string`, and ADR 0010 deferred agent-facing mapping to the
   tool layer. A `ValueError` has no category, so the agent cannot know to
   retry; a recoverable error naming the argument gives repair material.
   `line` and `old_string` are pre-validated by the tool
   (`parse_fact(line) is not None`, `old_string != ""`), which raises
   `InvalidArgumentError` directly: the rules are one call each and
   checking them first means a client `ValueError` from those calls is
   never guessed to be the agent's fault. The cursor cannot be
   pre-validated without decoding it, so a client `ValueError` from
   `list_prefix` is converted to `cursor`, chained as `__cause__` (core's
   messages carry no secrets), but only when a cursor was passed.
   `MetadataFormatError` and `UnicodeDecodeError` are `ValueError`
   subclasses but data-integrity failures (ADR 0006/0007) and pass
   through. Rejected: raising `NotFoundError(INVALID_PATH)` for a bad
   cursor (wrong repair: the path is fine); converting every client
   `ValueError` from `append_line`/`replace_fact` (blames the agent for
   any other `ValueError` those calls raise).
6. **Conversion is per tool and per argument, never a blanket
   `except ValueError`.** Only `list_prefix` with a cursor,
   `build_path`/`build_prefix` (decision 9), and `FileMetadata`'s
   `description` newline check convert; a `ValueError` from anywhere else
   propagates and renders as `"internal error"`. Rejected: one wrapper
   around every client call, which would hide a core bug as an agent
   error.
7. **`TOOL_NAMES` order is index, read, list, write, append, replace,
   delete**: bootstrap first, then reads, then writes in increasing
   destructiveness, the order a host should list them.
8. **Agent-facing docstrings are the tool descriptions.** They present a
   version conflict as routine (§5), state the byte ceiling and
   `system/` read-only, describe the fact-line syntax, and explain the
   `(scope, area, name)` arguments and how an index path maps to them.
   Tests pin the phrases a host must not lose.
9. **Scope-relative tools: the tool builds every path (human decision
   1c).** Tools take `scope`, `area`, `name` (and `list_prefix` takes
   `scope`, optional `area`); the tool checks `scope in identity.grants`,
   then calls `build_path(scope, entity_id, area, name)` or
   `build_prefix(scope, entity_id, area)` with `entity_id =
   identity.grants[scope].entity_id`. The tool reads the grant directly
   and never calls `Identity.entity_id()`, so an `Identity` subclass
   overriding that method cannot redirect reads or writes to another
   entity (spec US2.9). For the same reason `get_memory_index` builds its
   scope map from the grants (`{s: g.entity_id for s, g in
   grants.items()}`) and never reads the overridable `scope_map`
   property (spec US2.3). Notion §6: tool code "uses the returned fields to
   build the path prefix". An ungranted scope is
   `InvalidArgumentError("scope", f"scope {scope!r} is not available in
   this session; available scopes: {', '.join(sorted(identity.grants))}")`,
   raised before any path is built: recoverable, because the error itself
   lists the scopes the agent can use. A `build_path`/`build_prefix`
   `ValueError` becomes `InvalidArgumentError` naming `area` if
   `not is_valid_segment(area)`, else `name` (scope and entity ID are
   already valid, since `Identity` and `ScopeGrant` validate them).
   `build_path` appends `.md` unconditionally; `name` is documented as
   excluding it and is not rejected for ending in `.md`. Rejected: full
   paths with entity prefixes from adopter prompt text (milestone 4
   dependency, a class of agent path errors); exposing the scope map to
   the agent; `RestrictedScopeError` for an ungranted scope (permanent,
   but the agent can recover by choosing another scope).
10. **Read scoping: own entity only.** ADR 0017 left read scoping to the
    tool layer. Decision 9 decides it: reads and listing reach only the
    caller's own entity in each granted scope, because no tool accepts an
    entity ID. Shared content lives under the scope's entity the caller
    is granted (e.g. the `org` entity), so nothing a session should read
    is lost. Rejected: an unchecked read path taking a full path, which
    would reopen the entity-ID problem decision 9 closes.
11. **Tool-layer rendering helpers (human decision 2a).**
    `render_result(value)` and `render_error(exc)` turn a tool result or
    any exception into a JSON-safe `dict`, carrying the repair material
    (`content`, `version`, `size`, `limit`, `match_count`,
    `required_roles`, `argument`) that `str(err)` omits, so a host that
    renders them keeps §5's merge-and-retry loop intact. This is §7's
    "format the response". The methods stay typed and testable; a host
    adapter calls the helpers. `last_updated` uses `metadata_to_map`'s
    rendering so the agent sees the same timestamp form as storage. Each
    rendered file also carries `scope`, `area`, `name` (via `parse_path`),
    so the path → arguments mapping is in the data, not only in
    docstrings; a malformed entry path renders them as `None` rather than
    raising, and capped rows carry `scope` and `area` (`None` for a
    scope- or entity-level prefix). Host contract: every tool failure is
    renderable. `render_error` accepts any `Exception` and never raises:
    the type name and message are read through guards (fallbacks
    `"<unnamed>"`, `"<unreadable>"`). `MetadataFormatError` and
    `UnicodeDecodeError` render as `{"error": <type name>, "category":
    "internal", "message": str(exc)}`; any other non-`WenchangError`
    renders the fixed message `"internal error"`, so an off-contract
    exception does not leak internals to the agent. A `WenchangError`
    subclass whose `category` is missing, raises, or is not an
    `ErrorCategory` member falls back to that same internal rendering, and
    a payload value that is not JSON-safe is dropped: `_json_value`
    accepts only an exact `str`, an `int` that is not a `bool`, an `Enum`
    member (its value), and a `frozenset` of `str` (sorted).
    `render_result` never raises for any value of a supported type, and
    its output is always JSON-serializable: it drops `aliases`/`sources`
    members that are not JSON-safe strings, and drops a `path`,
    `content`, `version`, `description`, or `next_cursor` that is not an
    exact `str`. This relies on ADR
    0019's transport-failure mapping: a conforming client surfaces every
    transport failure as `BackendUnavailableError`, so nothing the agent
    needs to act on arrives as an off-contract exception. A host needs one
    `except Exception` and no branching.
    Rejected: tools returning or raising rendered payloads (loses typed
    results for in-process callers and the end-to-end tests); leaving
    formatting to each host (every host must rediscover which attributes
    matter, and one that renders `str(err)` breaks the conflict loop).
12. **Orchestrator calls pending PR review**: the §7 server object is
    deferred to AIE-1060; the byte-ceiling number is not in the docstring
    (it reaches the agent via `OversizeWriteError.limit` and prompt
    text); `InvalidArgumentError` joins the taxonomy (decision 5).
13. **One wrong-type rule for agent arguments.** Any agent-supplied
    argument whose real type is wrong raises `InvalidArgumentError`
    naming it before any client call, never `TypeError`; `str` subclasses
    are normalized with `str.__str__`; the detail is `f"{argument} must be
    a string, not {type_name}"` with `type_name` read through the guarded
    `_type_name`. `aliases` must be a `Sequence` by real type
    (`issubclass(type(aliases), Sequence)`, not `isinstance`), and
    `description` is rejected if it contains any `str.splitlines` line
    boundary, not only `\n`/`\r`. `scope`, `area`, `name` (during the
    segment checks), `description`, each `aliases` member, `content`,
    `line`, and `new_string` are also checked
    for UTF-8 encodability (a lone surrogate passes `is_valid_segment`), so core's
    `UnicodeEncodeError` (a `ValueError`) never reaches the client as an
    uncategorized error. A host schema
    may pass through whatever the model emitted, and a `TypeError` has no
    category, so the agent could not repair it. Rejected: `TypeError` as
    the host schema's concern (leaves the agent stuck when the host is
    loose).

## Public interface

### `src/wenchang/errors.py` addition

```python
class InvalidArgumentError(RecoverableError):
    """An agent-supplied argument was rejected; correct it and retry."""

    def __init__(self, argument: str, detail: str) -> None:
        # TypeError unless issubclass(type(argument), str); argument = str.__str__(argument)
        # ValueError if argument == ""
        self.argument = argument
        super().__init__(f"Argument {argument} is invalid: {detail}")
```

`WenchangError.detail` holds the full detail sentence; this class keeps
that behavior (`detail` is the composed sentence) and adds `argument`.
Tests assert `err.detail == "Argument cursor is invalid: bad"`,
`str(err).startswith(err.detail)`, and `err.argument == "cursor"` (spec
US4.4).

### `src/wenchang/tools.py`

```python
"""Agent-facing memory tools over a transport client.

A MemoryTools instance is one session: a resolved Identity, the adopter's
ScopePolicy, a TransportClient, and the surface name stamped on writes.
Its public methods are the tools; their docstrings are the descriptions a
host shows the agent. Tools take a scope, area, and name and build the
path under the caller's own entity in that scope. Mutating tools check the
write against the identity and policy, then call the client.
render_result and render_error produce the JSON-safe form a host shows the
agent.
"""

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Final, NoReturn, cast

from wenchang.core import FileEntry, ListCursor, ListPage, MemoryFile, MemoryIndex
from wenchang.errors import InvalidArgumentError, WenchangError
from wenchang.file_format import (
    LAST_UPDATED_KEY, FileMetadata, MetadataFormatError, metadata_to_map, parse_fact,
)
from wenchang.identity import Identity, IdentityResolver, resolve_identity
from wenchang.paths import build_path, build_prefix, is_valid_segment, parse_path
from wenchang.scope import ScopePolicy, check_write
from wenchang.transport import TransportClient
from wenchang.version_token import VersionToken

__all__ = ["TOOL_NAMES", "MemoryTools", "bind_tools", "render_error", "render_result"]

TOOL_NAMES: Final[tuple[str, ...]] = (
    "get_memory_index", "read_file", "list_prefix",
    "write_file", "append_line", "replace_fact", "delete_file",
)
_UNSET_TIMESTAMP: Final = datetime(1970, 1, 1, tzinfo=UTC)


class MemoryTools:
    """The memory tools for one session."""

    def __init__(
        self, client: TransportClient, identity: Identity, policy: ScopePolicy, *, source: str
    ) -> None:
        # TypeError if not isinstance(cast(object, client), TransportClient)
        # TypeError if not issubclass(type(identity), Identity) / type(policy), ScopePolicy)
        # TypeError if not issubclass(type(source), str); source = str.__str__(source)
        # ValueError("source must be non-empty") if source == ""
        ...

    @property
    def client(self) -> TransportClient: ...
    @property
    def identity(self) -> Identity: ...
    @property
    def policy(self) -> ScopePolicy: ...
    @property
    def source(self) -> str: ...

    def tools(self) -> Mapping[str, Callable[..., object]]:
        """The seven tools by name, in TOOL_NAMES order, as bound methods."""
        # MappingProxyType({name: getattr(self, name) for name in TOOL_NAMES})

    def get_memory_index(self) -> MemoryIndex:
        """Load the metadata index of every memory scope available in this session. ..."""
        # scope_map = {s: g.entity_id for s, g in self._identity.grants.items()}
        # return self._client.get_memory_index(scope_map)   # never identity.scope_map

    def read_file(self, scope: str, area: str, name: str) -> MemoryFile:
        """Read one memory file: its content, metadata, and version. ..."""
        # path = self._path(scope, area, name); return self._client.read_file(path)

    def list_prefix(
        self, scope: str, area: str | None = None, cursor: ListCursor | None = None
    ) -> ListPage:
        """List the files in a scope or area, one page at a time, without content. ..."""
        # prefix = self._prefix(scope, area); cursor = None or _exact("cursor", cursor)
        # try: return self._client.list_prefix(prefix, cursor)   # both positional
        # except ValueError as exc:
        #     if cursor is None: raise   # no agent argument to blame
        #     _reraise_argument("cursor", exc)

    def write_file(
        self,
        scope: str,
        area: str,
        name: str,
        content: str,
        description: str,
        aliases: Sequence[str],
        expected_version: VersionToken | None,
    ) -> MemoryFile:
        """Create a memory file or replace one whole. ..."""
        # path = self._path(scope, area, name); check_write(path, self._identity, self._policy)
        # _exact + _encodable("content"); _exact + _encodable("description");
        # description with any str.splitlines boundary -> InvalidArgumentError("description");
        # aliases: real-type Sequence, not str/bytes; members _exact + _encodable("aliases");
        # expected_version None or _exact; FileMetadata ValueError -> "description"
        # return self._client.write_file(path, content, metadata, expected_version, source=self._source)

    def append_line(
        self, scope: str, area: str, name: str, line: str, expected_version: VersionToken
    ) -> MemoryFile:
        """Add one fact line to the end of an existing memory file. ..."""
        # _path; check_write; _exact + _encodable("line");
        # parse_fact(line) is None -> InvalidArgumentError("line") (no __cause__);
        # _exact("expected_version"); client call (ValueError propagates unchanged)

    def replace_fact(
        self,
        scope: str,
        area: str,
        name: str,
        old_string: str,
        new_string: str,
        expected_version: VersionToken,
    ) -> MemoryFile:
        """Change one fact in a memory file by quoting the text to replace. ..."""
        # _path; check_write; _exact("old_string");
        # old_string == "" -> InvalidArgumentError("old_string") (no __cause__);
        # _exact + _encodable("new_string"); _exact("expected_version")
        # client call (ValueError propagates unchanged)

    def delete_file(
        self, scope: str, area: str, name: str, expected_version: VersionToken
    ) -> None:
        """Delete a memory file. ..."""
        # _path; check_write; _exact("expected_version")
        # return self._client.delete_file(path, expected_version)

    def _entity(self, scope: str) -> str:
        # scope already exact str; grants = self._identity.grants
        # if scope not in grants:
        #     available = ", ".join(sorted(grants))
        #     raise InvalidArgumentError(
        #         "scope", f"scope {scope!r} is not available in this session; available scopes: {available}")
        # return grants[scope].entity_id   # never self._identity.entity_id(scope)

    def _path(self, scope: str, area: str, name: str) -> str:
        # scope, area, name = _exact("scope", scope), _exact("area", area), _exact("name", name)
        # _encodable("scope", scope); _encodable("area", area); _encodable("name", name)
        # entity_id = self._entity(scope)
        # try: return build_path(scope, entity_id, area, name)
        # except ValueError as exc:
        #     raise InvalidArgumentError("area" if not is_valid_segment(area) else "name", str(exc)) from exc

    def _prefix(self, scope: str, area: str | None) -> str:
        # as _path with build_prefix(scope, entity_id, area); area None allowed; failure -> "area"


def _exact(argument: str, value: object) -> str:
    """Return value as an exact str; InvalidArgumentError(argument) if its real type is not str."""
    # detail: f"{argument} must be a string, not {_type_name(type(value))}"


def _type_name(t: type) -> str:
    # A metaclass may make __name__ raise or return a str subclass.
    # try: return str.__str__(t.__name__)  except Exception: return "<unnamed>"


def _message(exc: BaseException) -> str:
    # try: return str.__str__(str(exc))  except Exception: return "<unreadable>"


def _encodable(argument: str, value: str) -> None:
    """Raise InvalidArgumentError(argument) from UnicodeEncodeError if value is not UTF-8-encodable."""


def _reraise_argument(argument: str, exc: ValueError) -> NoReturn:
    """Re-raise a data-integrity ValueError unchanged; convert any other to InvalidArgumentError."""
    # if issubclass(type(exc), (MetadataFormatError, UnicodeDecodeError)): raise exc
    # raise InvalidArgumentError(argument, str(exc)) from exc


def bind_tools[C](
    client: TransportClient,
    resolver: IdentityResolver[C],
    credentials: C,
    policy: ScopePolicy,
    *,
    source: str,
) -> MemoryTools:
    """Resolve the caller's identity and return the session's tools."""
    # return MemoryTools(client, resolve_identity(resolver, credentials), policy, source=source)


def render_result(value: MemoryFile | ListPage | MemoryIndex | None) -> dict[str, object]:
    """Render a tool's return value as a JSON-safe dict for the agent."""
    # MemoryFile -> _file_fields(value) | {"content": value.content}   (content after path)
    # ListPage   -> {"entries": [_file_fields(e) ...], "next_cursor": str(c) or None}
    # MemoryIndex-> {"entries": [...], "capped": [{"prefix": p, "scope": seg[0],
    #                "area": seg[2] if 3 segments else None, "omitted": n} ...]}
    # None       -> {"ok": True}
    # other      -> TypeError (dispatch on issubclass(type(value), ...))
    # path / content / version / description / next_cursor not exact str -> key dropped


def render_error(exc: Exception) -> dict[str, object]:
    """Render any tool failure as a JSON-safe dict, including its repair material."""
    # name = _type_name(type(exc))
    # MetadataFormatError / UnicodeDecodeError (by issubclass(type(exc), ...)):
    #     return {"error": name, "category": "internal", "message": _message(exc)}
    # other non-WenchangError:
    #     return {"error": name, "category": "internal", "message": "internal error"}
    # category missing / raising / not an ErrorCategory member -> the "internal error" dict above
    # out = {"error": name, "category": exc.category.value, "message": _message(exc)}
    # for key in _ERROR_FIELDS: value = getattr(exc, key, None) (guarded); skip None
    #   _json_value: exact str; int but not bool; Enum member -> .value;
    #   frozenset of str -> sorted list; anything else -> field dropped
    # _ERROR_FIELDS = ("path", "content", "version", "size", "limit", "match_count",
    #                  "reason", "scope", "required_roles", "argument")


def _file_fields(entry: FileEntry | MemoryFile) -> dict[str, object]:
    # try: parts = parse_path(entry.path)  except ValueError: scope/area/name = None
    # {"path", "scope": parts.scope, "area": parts.area, "name": parts.name,
    #  "version": str, "description", "aliases": list, "sources": sorted list,
    #  "last_updated": metadata_to_map(entry.metadata)[LAST_UPDATED_KEY]}
    # aliases / sources members that are not JSON-safe strings are dropped, never raised on
```

`render_error` reads only the ten fixed payload attributes, never `vars(exc)`,
so `detail`, `__cause__`, and traceback state never reach the agent. A
`ResolverFailureError` renders only `error`, `category`, and `message`,
whose text `resolve_identity` already keeps free of credentials.

`raise exc` inside `_reraise_argument` re-raises the same object (its
traceback grows one frame, which is acceptable; the identity check in tests
is `is`). Alternatively the `except` clause checks the type and uses a
bare `raise`; either satisfies the tests.

### Docstring content (agent-facing; tests pin the quoted phrases)

| Tool | Must contain |
| ---- | ------------ |
| `get_memory_index` | `capped`, `read_file(scope, area, name)`, `list_prefix(scope, area)` (index path → arguments mapping) |
| `read_file` | first-line sentence; `scope`, `area`, `name`, `.md` |
| `list_prefix` | `scope`, `area`, `cursor`, `next_cursor` |
| `write_file` | `scope`, `area`, `name`, `.md`, `routine`, `expected_version`, `byte ceiling`, `current size and the limit`, `not merged` (description/aliases are replaced), `system/`, `read-only` |
| `append_line` | `scope`, `area`, `name`, `.md`, `routine`, `expected_version`, `byte ceiling`, `[stated]`, `[observed]`, `[inferred]`, `[system]`, `system/`, `read-only` |
| `replace_fact` | `scope`, `area`, `name`, `.md`, `routine`, `expected_version`, `byte ceiling`, `exactly once`, `system/`, `read-only` |
| `delete_file` | `scope`, `area`, `name`, `.md`, `routine`, `expected_version`, `system/`, `read-only` |

Every tool taking `name` says, in substance: "`name` is the file name
without `.md`." `get_memory_index` says: "A path `scope/<entity>/area/
name.md` in the index is read with `read_file(scope, area, name)`; the
entity segment is yours and is filled in for you."

Each mutating docstring says, in substance: "A version conflict is
routine: the error carries the current content and version; merge your
change into it and retry with that version." `write_file` says: "Pass
`expected_version=None` to create a file that does not exist yet; pass the
version you read to replace one." No Linear IDs. Present tense.

### ARCHITECTURE.md

`tools` moves from *(planned)* to implemented: per-session `MemoryTools`,
`bind_tools` as the only credential-touching function, scope-relative
arguments with the tool building every path under the caller's own entity
(reads scoped to own entity, deciding ADR 0017's open point),
check-then-call for mutations, the `ValueError` → `InvalidArgumentError`
conversions and the two pass-through types, `render_result` /
`render_error` as the agent-facing format, framework-agnostic with
`tools()` for hosts. `tools --> paths` joins the diagram. `errors`: add `InvalidArgumentError` to the
recoverable kinds and the taxonomy section. Diagram prose: `tools -->
scope` and `tools --> transport` are now live; `identity` is called by
`bind_tools`; `scope` is called by `tools`. Key invariant: "Every mutating
tool checks the write before the transport sees it." ADR 0016's
"AIE-1044's tests must cover that" is satisfied: note it.

## Test layout

All files `pytestmark = pytest.mark.unit`; docstrings cite AIE-1044 and
scenario IDs.

- `tests/test_errors_invalid_argument.py` (US4.4): category, attributes,
  message prefix and guidance suffix, empty `argument` (`ValueError`),
  non-`str` `argument` (`TypeError`), `str`-subclass `argument`
  normalized.
- `tests/test_tools.py` (US1–US4, US6): `_FakeClient` recording double
  with `returns: dict[str, object]` and `raises: dict[str, BaseException]`,
  satisfying `TransportClient` (all seven methods, fully annotated);
  reference identity, policy, a `member` and an `owner` variant;
  parametrized mutating-tool table `(tool, extra_args)` for US3.1–6 so
  each check runs against all four with `(scope, area, name)` varied;
  US2.5–8 parametrized across all six scope-taking tools; `ast` scans for
  US6.1–2; `tomllib` read for US6.3 (`dependencies ==
  ["google-cloud-storage>=2.18"]`); a weakref-able credentials sentinel,
  `weakref.ref`, and `gc.collect()` for US1.7. `check_write` is observed
  with `monkeypatch.setattr(wenchang.tools, "check_write", spy)`, where
  the spy appends `("check_write", path)` to the same call log the
  `_FakeClient` writes, then delegates to `scope.check_write`; US2.1
  asserts no spy entry, US3.0 asserts the spy entry precedes the client
  entry and the two path objects are `is`-identical, US3.3 asserts no spy
  entry. An `Identity` subclass overriding `entity_id()` covers US2.9.
- `tests/test_tools_render.py` (US7): one test per value type and per
  error kind, each also asserting `json.loads(json.dumps(out)) == out`;
  `TypeError` cases for `render_result`; a malformed entry path rendering
  `None` segments (US7.5a); capped-row `scope`/`area` for area-, entity-,
  and scope-level prefixes (US7.3); the `"internal"` rendering with
  `str(exc)` for `MetadataFormatError`/`UnicodeDecodeError` and `"internal
  error"` for others (US7.11); hostile `__str__` and `__name__` (US7.12).
- `tests/test_tools_descriptions.py` (US5): `TOOL_NAMES`, `tools()`
  mapping identity and order, docstring phrase table, first-line sentence
  rule (first line stripped ends with `"."` and contains no `". "`), no
  Linear IDs.
- `tests/test_tools_end_to_end.py` (SC-002): `bind_tools` with
  `SandboxResolver` over a tests-only `_StoreClient` wrapping
  `MemoryStore(InMemoryStorage())`: the six `MemoryStore` operations
  forwarded unchanged, and `get_memory_index(scope_map)` recording the
  `scope_map` and returning `MemoryIndex()`. Asserts
  `isinstance(client, TransportClient)`, the recorded `scope_map ==
  {"user": "u-1", "org": "o-9"}`, read-back `sources ==
  frozenset({"test-surface"})`, and `last_updated` not the epoch
  placeholder. Follow-up (not a runtime choice): switch to
  `InProcessClient` after rebasing on AIE-1046.

## Project Structure

```text
specs/AIE-1044-tool-layer/              spec.md plan.md tasks.md review-spec.md review-pr.md
src/wenchang/errors.py                  # InvalidArgumentError
src/wenchang/tools.py                   # new
tests/test_errors_invalid_argument.py   # new
tests/test_tools.py                     # new
tests/test_tools_descriptions.py        # new
tests/test_tools_render.py              # new
tests/test_tools_end_to_end.py          # new
ARCHITECTURE.md
docs/adr/0022-tool-layer.md
docs/product/glossary.md                # tool layer / session binding terms if needed
```

## Complexity Tracking

None.
