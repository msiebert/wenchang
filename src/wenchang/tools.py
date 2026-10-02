"""Agent-facing memory tools over a transport client.

A MemoryTools instance is one session: a resolved Identity, the adopter's
ScopePolicy, a TransportClient, and the surface name stamped on writes.
Its public methods are the tools; their docstrings are the descriptions a
host shows the agent. Tools take a scope, area, and name and build the
path under the caller's own entity in that scope. Mutating tools check the
write against the identity and policy, then call the client.
"""

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Final, NoReturn, cast

from wenchang.core import ListCursor, ListPage, MemoryFile, MemoryIndex
from wenchang.errors import InvalidArgumentError
from wenchang.file_format import FileMetadata, MetadataFormatError
from wenchang.identity import Identity, IdentityResolver, resolve_identity
from wenchang.paths import build_path, build_prefix, is_valid_segment
from wenchang.scope import ScopePolicy, check_write
from wenchang.transport import TransportClient
from wenchang.version_token import VersionToken

__all__ = ["TOOL_NAMES", "MemoryTools", "bind_tools"]

TOOL_NAMES: Final[tuple[str, ...]] = (
    "get_memory_index",
    "read_file",
    "list_prefix",
    "write_file",
    "append_line",
    "replace_fact",
    "delete_file",
)

# Core overrides last_updated on every write.
_UNSET_TIMESTAMP: Final = datetime(1970, 1, 1, tzinfo=UTC)


class MemoryTools:
    """The memory tools for one session."""

    def __init__(
        self, client: TransportClient, identity: Identity, policy: ScopePolicy, *, source: str
    ) -> None:
        if not isinstance(cast(object, client), TransportClient):
            raise TypeError("client must satisfy TransportClient")
        # type() rather than isinstance, which consults a spoofable __class__.
        if not issubclass(type(cast(object, identity)), Identity):
            raise TypeError(f"identity must be an Identity, not {_type_name(type(identity))}")
        if not issubclass(type(cast(object, policy)), ScopePolicy):
            raise TypeError(f"policy must be a ScopePolicy, not {_type_name(type(policy))}")
        if not issubclass(type(cast(object, source)), str):
            raise TypeError(f"source must be a str, not {_type_name(type(source))}")
        source = str.__str__(source)
        if source == "":
            raise ValueError("source must be non-empty")
        self._client = client
        self._identity = identity
        self._policy = policy
        self._source = source

    @property
    def client(self) -> TransportClient:
        """The transport client the tools call."""
        return self._client

    @property
    def identity(self) -> Identity:
        """The session's resolved identity."""
        return self._identity

    @property
    def policy(self) -> ScopePolicy:
        """The adopter's write policy."""
        return self._policy

    @property
    def source(self) -> str:
        """The surface name stamped as a source on every write."""
        return self._source

    def tools(self) -> Mapping[str, Callable[..., object]]:
        """The seven tools by name, in TOOL_NAMES order, as bound methods."""
        methods: dict[str, Callable[..., object]] = {
            name: getattr(self, name) for name in TOOL_NAMES
        }
        return MappingProxyType(methods)

    def get_memory_index(self) -> MemoryIndex:
        """Load the metadata index of every memory scope available in this session.

        Call this first. Each entry lists a file's path, description, aliases,
        sources, last-updated time, and version, without content. An entry
        path has the form `scope/<entity>/area/name.md`; read it with
        `read_file(scope, area, name)`. The entity segment is yours and is
        filled in for you, so you never pass it. The index is size-limited:
        when a prefix has more files than fit, it appears under `capped` with
        the number omitted, and you page through it with
        `list_prefix(scope, area)` (or `list_prefix(scope)` for a whole scope).
        """
        return self._client.get_memory_index(self._identity.scope_map)

    def read_file(self, scope: str, area: str, name: str) -> MemoryFile:
        """Read one memory file: its content, metadata, and version.

        `scope` is one of the scopes available in this session, `area` is the
        folder inside it, and `name` is the file name without `.md`. Any area
        may be read, including `system/`. Keep the returned version: pass it
        as `expected_version` when you change the file.
        """
        path = self._path(scope, area, name)
        return self._client.read_file(path)

    def list_prefix(
        self, scope: str, area: str | None = None, cursor: ListCursor | None = None
    ) -> ListPage:
        """List the files in a scope or area, one page at a time, without content.

        `scope` is one of the scopes available in this session; `area`, if
        given, narrows the listing to one folder. Each page returns entries
        with metadata and version, and a `next_cursor`. When `next_cursor` is
        not null, pass it back as `cursor` with the same `scope` and `area` to
        get the next page.
        """
        prefix = self._prefix(scope, area)
        if cursor is not None:
            cursor = ListCursor(_exact("cursor", cursor))
        try:
            return self._client.list_prefix(prefix, cursor)
        except ValueError as exc:
            _reraise_argument("cursor", exc)

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
        """Create a memory file or replace one whole.

        `scope` is one of the scopes available in this session, `area` is the
        folder inside it, and `name` is the file name without `.md`. Pass
        `expected_version=None` to create a file that does not exist yet;
        pass the version you read to replace one. `description` (one line)
        and `aliases` replace the stored values; they are not merged with
        what was there. A per-file byte ceiling applies: an oversize write is
        rejected with the current size and the limit, so shorten the content
        and retry. The `system/` area is read-only.

        A version conflict is routine: someone else changed the file since
        you read it. The error carries the current content and version;
        merge your change into it and retry with that version.
        """
        path = self._path(scope, area, name)
        check_write(path, self._identity, self._policy)
        content = _exact("content", content)
        _encodable("content", content)
        description = _exact("description", description)
        _encodable("description", description)
        alias_tuple = _aliases(aliases)
        if expected_version is not None:
            expected_version = VersionToken(_exact("expected_version", expected_version))
        try:
            metadata = FileMetadata(description, alias_tuple, frozenset(), _UNSET_TIMESTAMP)
        except ValueError as exc:
            raise InvalidArgumentError("description", str(exc)) from exc
        return self._client.write_file(
            path, content, metadata, expected_version, source=self._source
        )

    def append_line(
        self, scope: str, area: str, name: str, line: str, expected_version: VersionToken
    ) -> MemoryFile:
        """Add one fact line to the end of an existing memory file.

        `scope` is one of the scopes available in this session, `area` is the
        folder inside it, and `name` is the file name without `.md`. `line`
        must be a single fact line with a leading bracketed label, one of
        `[stated]`, `[observed]`, `[inferred]`, or `[system]`, for example
        `- [stated] Prefers tea`. Pass the version you read as
        `expected_version`. The per-file byte ceiling applies to the result.
        The `system/` area is read-only.

        A version conflict is routine: someone else changed the file since
        you read it. The error carries the current content and version;
        merge your change into it and retry with that version.
        """
        path = self._path(scope, area, name)
        check_write(path, self._identity, self._policy)
        line = _exact("line", line)
        _encodable("line", line)
        expected_version = VersionToken(_exact("expected_version", expected_version))
        try:
            return self._client.append_line(path, line, expected_version, source=self._source)
        except ValueError as exc:
            _reraise_argument("line", exc)

    def replace_fact(
        self,
        scope: str,
        area: str,
        name: str,
        old_string: str,
        new_string: str,
        expected_version: VersionToken,
    ) -> MemoryFile:
        """Change one fact in a memory file by quoting the text to replace.

        `scope` is one of the scopes available in this session, `area` is the
        folder inside it, and `name` is the file name without `.md`.
        `old_string` must match the file's content exactly once; if it matches
        zero or several times, the error carries the current content and
        version so you can quote a longer, unique span. `new_string` replaces
        it. Pass the version you read as `expected_version`. The per-file
        byte ceiling applies to the result. The `system/` area is read-only.

        A version conflict is routine: someone else changed the file since
        you read it. The error carries the current content and version;
        merge your change into it and retry with that version.
        """
        path = self._path(scope, area, name)
        check_write(path, self._identity, self._policy)
        old_string = _exact("old_string", old_string)
        new_string = _exact("new_string", new_string)
        _encodable("new_string", new_string)
        expected_version = VersionToken(_exact("expected_version", expected_version))
        try:
            return self._client.replace_fact(
                path, old_string, new_string, expected_version, source=self._source
            )
        except ValueError as exc:
            _reraise_argument("old_string", exc)

    def delete_file(self, scope: str, area: str, name: str, expected_version: VersionToken) -> None:
        """Delete a memory file.

        `scope` is one of the scopes available in this session, `area` is the
        folder inside it, and `name` is the file name without `.md`. Pass the
        version you read as `expected_version`. The `system/` area is
        read-only.

        A version conflict is routine: someone else changed the file since
        you read it. The error carries the current content and version;
        merge that into your decision and retry with that version if the
        file should still go.
        """
        path = self._path(scope, area, name)
        check_write(path, self._identity, self._policy)
        expected_version = VersionToken(_exact("expected_version", expected_version))
        return self._client.delete_file(path, expected_version)

    def _entity(self, scope: str) -> str:
        grants = self._identity.grants
        if scope not in grants:
            available = ", ".join(sorted(grants))
            raise InvalidArgumentError(
                "scope",
                f"scope {scope!r} is not available in this session; available scopes: {available}",
            )
        # Read from the grant, never Identity.entity_id(), which a subclass may override.
        return grants[scope].entity_id

    def _path(self, scope: str, area: str, name: str) -> str:
        scope = _exact("scope", scope)
        area = _exact("area", area)
        name = _exact("name", name)
        _encodable("scope", scope)
        _encodable("area", area)
        _encodable("name", name)
        entity_id = self._entity(scope)
        try:
            return build_path(scope, entity_id, area, name)
        except ValueError as exc:
            argument = "area" if not is_valid_segment(area) else "name"
            raise InvalidArgumentError(argument, str(exc)) from exc

    def _prefix(self, scope: str, area: str | None) -> str:
        scope = _exact("scope", scope)
        if area is not None:
            area = _exact("area", area)
        _encodable("scope", scope)
        if area is not None:
            _encodable("area", area)
        entity_id = self._entity(scope)
        try:
            return build_prefix(scope, entity_id, area)
        except ValueError as exc:
            # scope and entity_id are valid by construction, so only area can fail.
            raise InvalidArgumentError("area", str(exc)) from exc


def _type_name(t: type) -> str:
    # A metaclass may make __name__ raise or return a str subclass.
    try:
        return str.__str__(t.__name__)
    except Exception:
        return "<unnamed>"


def _exact(argument: str, value: object) -> str:
    """Return value as an exact str; InvalidArgumentError(argument) if its real type is not str."""
    if not issubclass(type(value), str):
        raise InvalidArgumentError(
            argument, f"{argument} must be a string, not {_type_name(type(value))}"
        )
    return str.__str__(cast(str, value))


def _encodable(argument: str, value: str) -> None:
    """Raise InvalidArgumentError(argument) if value cannot be encoded as UTF-8."""
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise InvalidArgumentError(argument, f"{argument} is not valid UTF-8 text") from exc


def _aliases(aliases: object) -> tuple[str, ...]:
    # A bare str or bytes is a Sequence of characters, never a list of aliases.
    if issubclass(type(aliases), str | bytes | bytearray) or not isinstance(aliases, Sequence):
        raise InvalidArgumentError(
            "aliases", f"aliases must be a list of strings, not {_type_name(type(aliases))}"
        )
    return tuple(_exact("aliases", member) for member in cast(Sequence[object], aliases))


def _reraise_argument(argument: str, exc: ValueError) -> NoReturn:
    """Re-raise a data-integrity ValueError unchanged; convert any other to InvalidArgumentError."""
    if issubclass(type(exc), MetadataFormatError | UnicodeDecodeError):
        raise exc
    raise InvalidArgumentError(argument, str(exc)) from exc


def bind_tools[C](
    client: TransportClient,
    resolver: IdentityResolver[C],
    credentials: C,
    policy: ScopePolicy,
    *,
    source: str,
) -> MemoryTools:
    """Resolve the caller's identity and return the session's tools."""
    return MemoryTools(client, resolve_identity(resolver, credentials), policy, source=source)
