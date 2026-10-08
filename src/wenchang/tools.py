"""Agent-facing memory tools over a transport client.

A MemoryTools instance is one session: a resolved Identity, the adopter's
ScopePolicy, a TransportClient, the surface name stamped on writes, and
optionally the product named in each tool description. Its public methods
are the tools; descriptions() gives the descriptions a host shows the
agent: the docstrings, with the product in each first line when set. Tools
take a scope, area, and name and build the path under the caller's own
entity in that scope. Mutating tools check the write against the identity
and policy, then call the client. render_result and render_error produce
the JSON-safe form a host shows the agent.
"""

import inspect
import re
import unicodedata
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from enum import Enum
from types import MappingProxyType
from typing import Final, NoReturn, cast

from wenchang.core import CappedPrefix, FileEntry, ListCursor, ListPage, MemoryFile, MemoryIndex
from wenchang.errors import ErrorCategory, InvalidArgumentError, WenchangError
from wenchang.file_format import FileMetadata, MetadataFormatError, parse_fact
from wenchang.identity import Identity, IdentityResolver, resolve_identity
from wenchang.paths import build_path, build_prefix, is_valid_segment, parse_path
from wenchang.scope import ScopePolicy, check_write
from wenchang.transport import TransportClient
from wenchang.version_token import VersionToken

__all__ = ["TOOL_NAMES", "MemoryTools", "bind_tools", "render_error", "render_result"]

TOOL_NAMES: Final[tuple[str, ...]] = (
    "get_memory_index",
    "read_file",
    "list_prefix",
    "write_file",
    "append_line",
    "replace_fact",
    "delete_file",
)

# The only exception attributes render_error copies; never vars(exc).
_ERROR_FIELDS: Final[tuple[str, ...]] = (
    "path",
    "content",
    "version",
    "size",
    "limit",
    "match_count",
    "reason",
    "scope",
    "required_roles",
    "argument",
)

# The str.splitlines boundaries other than "\n" and "\r", which FileMetadata rejects itself.
_LINE_BOUNDARIES: Final[tuple[str, ...]] = (
    "\x0b",
    "\x0c",
    "\x1c",
    "\x1d",
    "\x1e",
    "\x85",
    "\u2028",
    "\u2029",
)

# Each tool's description first line with the product named; "{product}" is replaced verbatim.
_FIRST_LINE_TEMPLATES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "get_memory_index": (
            "Load the metadata index of every {product} memory scope available in this session."
        ),
        "read_file": "Read one {product} memory file: its content, metadata, and version.",
        "list_prefix": (
            "List the files in a {product} memory scope or area, one page at a time, "
            "without content."
        ),
        "write_file": "Create a {product} memory file or replace one whole.",
        "append_line": "Add one fact line to the end of an existing {product} memory file.",
        "replace_fact": (
            "Change one fact in a {product} memory file by quoting the text to replace."
        ),
        "delete_file": "Delete a {product} memory file.",
    }
)
if tuple(_FIRST_LINE_TEMPLATES) != TOOL_NAMES:
    raise RuntimeError("_FIRST_LINE_TEMPLATES keys must match TOOL_NAMES")

_AREA_SLUG: Final = re.compile(r"[a-z0-9][a-z0-9_-]*")

# Marks a field render_error omits because it has no JSON-safe form.
_DROP: Final = object()

# Core overrides last_updated on every write.
_UNSET_TIMESTAMP: Final = datetime(1970, 1, 1, tzinfo=UTC)


class MemoryTools:
    """The memory tools for one session."""

    def __init__(
        self,
        client: TransportClient,
        identity: Identity,
        policy: ScopePolicy,
        *,
        source: str,
        product: str | None = None,
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
        self._product = _product(product)

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

    @property
    def product(self) -> str | None:
        """The product named in each tool description's first line, or None."""
        return self._product

    def tools(self) -> Mapping[str, Callable[..., object]]:
        """The seven tools by name, in TOOL_NAMES order, as bound methods."""
        methods: dict[str, Callable[..., object]] = {
            name: getattr(self, name) for name in TOOL_NAMES
        }
        return MappingProxyType(methods)

    def descriptions(self) -> Mapping[str, str]:
        """Each tool's cleaned docstring by name, in TOOL_NAMES order.

        When a product is set, each first line names it.
        """
        out: dict[str, str] = {}
        for name in TOOL_NAMES:
            doc = inspect.cleandoc(cast(str, getattr(MemoryTools, name).__doc__))
            if self._product is None:
                out[name] = doc
            else:
                _, sep, rest = doc.partition("\n")
                first = _FIRST_LINE_TEMPLATES[name].replace("{product}", self._product)
                out[name] = first + sep + rest
        return MappingProxyType(out)

    def get_memory_index(self) -> MemoryIndex:
        """Load the metadata index of every memory scope available in this session.

        Call this first. Each entry gives a file's path, metadata, and version, without content.
        A path has the form `scope/<entity>/area/name.md`; the other tools take `scope`, `area`,
        and `name` (without `.md`), as in `read_file(scope, area, name)`, and the entity segment
        is filled in for you. Areas are lowercase ASCII slugs. The `system/` area is read-only.
        A prefix with more files than fit is listed under `capped` with the number omitted; page
        it with `list_prefix(scope, area)`.
        """
        # Built from grants, never Identity.scope_map, which a subclass may override.
        scope_map = {scope: grant.entity_id for scope, grant in self._identity.grants.items()}
        return self._client.get_memory_index(scope_map)

    def read_file(self, scope: str, area: str, name: str) -> MemoryFile:
        """Read one memory file: its content, metadata, and version.

        Any area may be read, including `system/`.
        """
        path = self._path(scope, area, name)
        return self._client.read_file(path)

    def list_prefix(
        self, scope: str, area: str | None = None, cursor: ListCursor | None = None
    ) -> ListPage:
        """List the files in a scope or area, one page at a time, without content.

        Each page returns entries with metadata and version, and a `next_cursor`; until it is
        null, pass it back as `cursor` with the same `scope` and `area` for the next page.
        """
        prefix = self._prefix(scope, area)
        if cursor is None:
            return self._client.list_prefix(prefix, None)
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

        Pass `expected_version=None` to create a file, or the version you read to replace one.
        `description` (one line) and `aliases` replace the stored values; they are not merged.
        Content over the per-file byte ceiling is rejected with the current size and the limit;
        shorten it and retry. A version conflict is routine: merge your change into the content it
        returns and retry with its version.
        """
        path = self._path(scope, area, name)
        check_write(path, self._identity, self._policy)
        content = _exact("content", content)
        _encodable("content", content)
        description = _description(description)
        alias_tuple = _aliases(aliases)
        if expected_version is not None:
            expected_version = VersionToken(_exact("expected_version", expected_version))
        metadata = FileMetadata(description, alias_tuple, frozenset(), _UNSET_TIMESTAMP)
        return self._client.write_file(
            path, content, metadata, expected_version, source=self._source
        )

    def append_line(
        self,
        scope: str,
        area: str,
        name: str,
        line: str,
        expected_version: VersionToken,
        aliases: Sequence[str] | None = None,
        description: str | None = None,
    ) -> MemoryFile:
        """Add one fact line to the end of an existing memory file.

        `line` is a single fact line with a leading bracketed label (`[stated]`, `[observed]`,
        `[inferred]`, or `[system]`), as in `- [stated] Prefers tea`. Pass the version you
        read as `expected_version`. The per-file byte ceiling applies to the result. Optional
        `aliases` are added to the file's existing aliases and never removed (`write_file` replaces
        the whole set); an optional one-line `description` replaces the stored one. A version
        conflict is routine: merge your change into the content it returns and retry with its
        version.
        """
        path = self._path(scope, area, name)
        check_write(path, self._identity, self._policy)
        line = _exact("line", line)
        _encodable("line", line)
        if parse_fact(line) is None:
            raise InvalidArgumentError(
                "line",
                "line must be a single fact line with a [stated], [observed], [inferred], "
                "or [system] label and non-empty text",
            )
        expected_version = VersionToken(_exact("expected_version", expected_version))
        alias_tuple = None if aliases is None else _aliases(aliases)
        if description is not None:
            description = _description(description)
        return self._client.append_line(
            path,
            line,
            expected_version,
            source=self._source,
            aliases=alias_tuple,
            description=description,
        )

    def replace_fact(
        self,
        scope: str,
        area: str,
        name: str,
        old_string: str,
        new_string: str,
        expected_version: VersionToken,
        aliases: Sequence[str] | None = None,
        description: str | None = None,
    ) -> MemoryFile:
        """Change one fact in a memory file by quoting the text to replace.

        `old_string` must match the content exactly once; otherwise the error carries the current
        content and version, so quote a unique span. `new_string` replaces it. Pass the
        version you read as `expected_version`. The per-file byte ceiling applies to the result.
        Optional `aliases` are added to the file's existing aliases and never removed (`write_file`
        replaces the whole set); an optional one-line `description` replaces the stored one. A
        version conflict is routine: merge your change into the content it returns and retry with
        its version.
        """
        path = self._path(scope, area, name)
        check_write(path, self._identity, self._policy)
        old_string = _exact("old_string", old_string)
        new_string = _exact("new_string", new_string)
        if old_string == "":
            raise InvalidArgumentError("old_string", "old_string must not be empty")
        _encodable("new_string", new_string)
        expected_version = VersionToken(_exact("expected_version", expected_version))
        alias_tuple = None if aliases is None else _aliases(aliases)
        if description is not None:
            description = _description(description)
        return self._client.replace_fact(
            path,
            old_string,
            new_string,
            expected_version,
            source=self._source,
            aliases=alias_tuple,
            description=description,
        )

    def delete_file(self, scope: str, area: str, name: str, expected_version: VersionToken) -> None:
        """Delete a memory file.

        Pass the version you read as `expected_version`. A version conflict is routine: retry with
        the version it returns only if the file should still go.
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
            path = build_path(scope, entity_id, area, name)
        except ValueError as exc:
            argument = "area" if not is_valid_segment(area) else "name"
            raise InvalidArgumentError(argument, str(exc)) from exc
        _check_area_slug(area)
        _check_name_chars(name)
        return path

    def _prefix(self, scope: str, area: str | None) -> str:
        scope = _exact("scope", scope)
        if area is not None:
            area = _exact("area", area)
        _encodable("scope", scope)
        if area is not None:
            _encodable("area", area)
        entity_id = self._entity(scope)
        try:
            prefix = build_prefix(scope, entity_id, area)
        except ValueError as exc:
            # scope and entity_id are valid by construction, so only area can fail.
            raise InvalidArgumentError("area", str(exc)) from exc
        if area is not None:
            _check_area_slug(area)
        return prefix


def _type_name(t: type) -> str:
    # A metaclass may make __name__ raise or return a str subclass.
    try:
        return str.__str__(t.__name__)
    except Exception:
        return "<unnamed>"


def _product(product: object) -> str | None:
    """Return product stripped to an exact one-line UTF-8 str, or None."""
    if product is None:
        return None
    if not issubclass(type(product), str):
        raise TypeError(f"product must be a str or None, not {_type_name(type(product))}")
    value = str.strip(str.__str__(cast(str, product)))
    if value == "":
        raise ValueError("product must be non-empty")
    if len(value.splitlines()) != 1:
        raise ValueError("product must be one line")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("product must be encodable as UTF-8") from exc
    return value


def _message(exc: BaseException) -> str:
    # An exception's __str__ may raise or return a str subclass.
    try:
        return str.__str__(str(exc))
    except Exception:
        return "<unreadable>"


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


def _check_area_slug(area: str) -> None:
    if _AREA_SLUG.fullmatch(area) is None:
        raise InvalidArgumentError(
            "area",
            f"area {area!r} must be a lowercase slug: a-z0-9 first, then a-z0-9, '-' or '_'",
        )


def _check_name_chars(name: str) -> None:
    for char in name:
        if _is_forbidden_name_char(char):
            raise InvalidArgumentError(
                "name",
                f"name must not contain invisible, separator, or noncharacter U+{ord(char):04X}",
            )


def _is_forbidden_name_char(char: str) -> bool:
    code = ord(char)
    if 0xFDD0 <= code <= 0xFDEF or code & 0xFFFE == 0xFFFE:
        return True
    return unicodedata.category(char) in ("Cf", "Zl", "Zp")


def _aliases(aliases: object) -> tuple[str, ...]:
    # A bare str or bytes is a Sequence of characters, never a list of aliases.
    # type() rather than isinstance, which consults a spoofable __class__.
    kind = type(aliases)
    if issubclass(kind, str | bytes | bytearray) or not issubclass(kind, Sequence):
        raise InvalidArgumentError(
            "aliases", f"aliases must be a list of strings, not {_type_name(kind)}"
        )
    members: list[str] = []
    for member in cast(Sequence[object], aliases):
        alias = _exact("aliases", member)
        _encodable("aliases", alias)
        members.append(alias)
    return tuple(members)


def _description(value: object) -> str:
    """Return value as an exact one-line str; InvalidArgumentError("description") otherwise."""
    description = _exact("description", value)
    _encodable("description", description)
    if any(boundary in description for boundary in _LINE_BOUNDARIES):
        raise InvalidArgumentError("description", "description must be a single line")
    try:
        FileMetadata(description, (), frozenset(), _UNSET_TIMESTAMP)
    except ValueError as exc:
        raise InvalidArgumentError("description", str(exc)) from exc
    return description


def _reraise_argument(argument: str, exc: ValueError) -> NoReturn:
    """Re-raise a data-integrity ValueError unchanged; convert any other to InvalidArgumentError."""
    if issubclass(type(exc), MetadataFormatError | UnicodeDecodeError):
        raise exc
    raise InvalidArgumentError(argument, _message(exc)) from exc


def bind_tools[C](
    client: TransportClient,
    resolver: IdentityResolver[C],
    credentials: C,
    policy: ScopePolicy,
    *,
    source: str,
    product: str | None = None,
) -> MemoryTools:
    """Resolve the caller's identity and return the session's tools."""
    return MemoryTools(
        client, resolve_identity(resolver, credentials), policy, source=source, product=product
    )


def render_result(value: MemoryFile | ListPage | MemoryIndex | None) -> dict[str, object]:
    """Render a tool's return value as a JSON-safe dict for the agent."""
    if value is None:
        return {"ok": True}
    kind = type(cast(object, value))
    if issubclass(kind, MemoryFile):
        file = cast(MemoryFile, value)
        return _file_fields(file, content=file.content)
    if issubclass(kind, ListPage):
        page = cast(ListPage, value)
        out: dict[str, object] = {
            "entries": [
                _file_fields(cast(FileEntry, entry))
                for entry in _iterate_or_empty(lambda: page.entries)
            ]
        }
        if page.next_cursor is None:
            out["next_cursor"] = None
        else:
            cursor = _str_or_drop(lambda: page.next_cursor)
            if cursor is not _DROP:
                out["next_cursor"] = cursor
        return out
    if issubclass(kind, MemoryIndex):
        index = cast(MemoryIndex, value)
        return {
            "entries": [
                _file_fields(cast(FileEntry, entry))
                for entry in _iterate_or_empty(lambda: index.entries)
            ],
            "capped": _capped_rows(_iterate_or_empty(lambda: index.capped)),
        }
    raise TypeError(f"cannot render a {_type_name(kind)}")


def render_error(exc: Exception) -> dict[str, object]:
    """Render any tool failure as a JSON-safe dict, including its repair material."""
    kind = type(exc)
    name = _type_name(kind)
    if issubclass(kind, MetadataFormatError | UnicodeDecodeError):
        return {"error": name, "category": "internal", "message": _message(exc)}
    # Off-contract exceptions may carry internals the agent must not see.
    internal: dict[str, object] = {
        "error": name,
        "category": "internal",
        "message": "internal error",
    }
    if not issubclass(kind, WenchangError):
        return internal
    try:
        return _wenchang_error_fields(cast(WenchangError, exc), name)
    except Exception:
        return internal


def _wenchang_error_fields(error: WenchangError, name: str) -> dict[str, object]:
    category = cast(object, getattr(error, "category", None))
    if not issubclass(type(category), ErrorCategory):
        raise TypeError("category is not an ErrorCategory")
    category_value = _json_value(category)
    if not issubclass(type(category_value), str):
        raise TypeError("category value is not a str")
    out: dict[str, object] = {
        "error": name,
        "category": category_value,
        "message": _message(error),
    }
    for key in _ERROR_FIELDS:
        try:
            field = cast(object, getattr(error, key, None))
            if field is None:
                continue
            value = _json_value(field)
        except Exception:
            continue
        if value is not _DROP:
            out[key] = value
    return out


def _json_value(value: object) -> object:
    """Return value in JSON-safe form, or _DROP if it has no such form."""
    kind = type(value)
    if issubclass(kind, Enum):
        member_value = cast(object, cast(Enum, value).value)
        if issubclass(type(member_value), str):
            return str.__str__(cast(str, member_value))
        return _DROP
    if issubclass(kind, str):
        return str.__str__(cast(str, value))
    if issubclass(kind, int) and not issubclass(kind, bool):
        return int.__int__(cast(int, value))
    if issubclass(kind, frozenset):
        members = list(cast(frozenset[object], value))
        if all(issubclass(type(member), str) for member in members):
            return sorted(str.__str__(cast(str, member)) for member in members)
    return _DROP


def _file_fields(entry: FileEntry | MemoryFile, content: object = None) -> dict[str, object]:
    # Fields whose real type is not str are omitted rather than fail to render.
    fields: dict[str, object] = {}
    path = _str_or_drop(lambda: entry.path)
    if path is not _DROP:
        fields["path"] = path
        try:
            parts = parse_path(cast(str, path))
            parsed: dict[str, object] = {
                "scope": parts.scope,
                "area": parts.area,
                "name": parts.name,
            }
        except ValueError:
            fields |= {"scope": None, "area": None, "name": None}
        except Exception:
            pass
        else:
            fields |= parsed
    if content is not None:
        content_value = _str_or_drop(lambda: content)
        if content_value is not _DROP:
            fields["content"] = content_value
    version = _str_or_drop(lambda: entry.version)
    if version is not _DROP:
        fields["version"] = version
    try:
        metadata = cast(object, entry.metadata)
    except Exception:
        return fields
    if not issubclass(type(metadata), FileMetadata):
        return fields
    meta = cast(FileMetadata, metadata)
    description = _str_or_drop(lambda: meta.description)
    if description is not _DROP:
        fields["description"] = description
    # Metadata may hold wrongly typed fields or members; drop them rather than fail to render.
    aliases = _members_or_drop(lambda: meta.aliases)
    if aliases is not _DROP:
        fields["aliases"] = aliases
    sources = _members_or_drop(lambda: meta.sources)
    if sources is not _DROP:
        fields["sources"] = sorted(cast(list[str], sources))
    last_updated = _timestamp_or_drop(lambda: meta.last_updated)
    if last_updated is not _DROP:
        fields["last_updated"] = last_updated
    return fields


def _str_or_drop(read: Callable[[], object]) -> object:
    """Return read() as an exact str, or _DROP if it raises or its real type is not str."""
    try:
        value = read()
    except Exception:
        return _DROP
    if not issubclass(type(value), str):
        return _DROP
    return str.__str__(cast(str, value))


def _members_or_drop(read: Callable[[], object]) -> object:
    """Return the exact-str members of read(), or _DROP if reading or iterating it fails."""
    try:
        values = cast(Iterable[object], read())
        return [str.__str__(cast(str, v)) for v in values if issubclass(type(v), str)]
    except Exception:
        return _DROP


def _iterate_or_empty(read: Callable[[], object]) -> list[object]:
    """Return the members of read(), or [] if reading or iterating it fails."""
    try:
        return list(cast(Iterable[object], read()))
    except Exception:
        return []


def _timestamp_or_drop(read: Callable[[], object]) -> object:
    """Return read() as UTC ISO-8601 with a "Z" suffix, or _DROP if it is not an aware datetime."""
    try:
        value = read()
        if not issubclass(type(value), datetime):
            return _DROP
        moment = cast(datetime, value)
        if moment.utcoffset() is None:
            return _DROP
        return _timestamp(moment)
    except Exception:
        return _DROP


def _timestamp(value: datetime) -> str:
    """Render value as UTC ISO-8601 with a "Z" suffix, as metadata_to_map does."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _capped_rows(caps: list[object]) -> list[dict[str, object]]:
    """Render each capped row, skipping any that cannot render."""
    rows: list[dict[str, object]] = []
    for cap in caps:
        row = _capped_fields(cap)
        if row is not None:
            rows.append(row)
    return rows


def _capped_fields(cap: object) -> dict[str, object] | None:
    """Render one capped row, or None if its prefix or omitted count is wrongly typed."""
    try:
        prefix = _str_or_drop(lambda: cast(CappedPrefix, cap).prefix)
        if prefix is _DROP:
            return None
        omitted = cast(object, cast(CappedPrefix, cap).omitted)
        kind = type(omitted)
        if not issubclass(kind, int) or issubclass(kind, bool):
            return None
        # A prefix is scope/, scope/entity/, or scope/entity/area/.
        segments = cast(str, prefix).rstrip("/").split("/")
        return {
            "prefix": prefix,
            "scope": segments[0],
            "area": segments[2] if len(segments) >= 3 else None,
            "omitted": int.__int__(cast(int, omitted)),
        }
    except Exception:
        return None
