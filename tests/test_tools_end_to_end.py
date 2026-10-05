"""End-to-end test of the tool layer over a real MemoryStore.

Covers AIE-1044, SC-002: bind_tools with SandboxResolver over a tests-only
client wrapping MemoryStore(InMemoryStorage()); and AIE-1151, US4.15 through
InProcessClient.
"""

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

import pytest

from wenchang.core import ListCursor, ListPage, MemoryFile, MemoryIndex, MemoryStore
from wenchang.errors import (
    InvalidArgumentError,
    NotFoundError,
    NotFoundReason,
    RestrictedScopeError,
    RestrictionReason,
)
from wenchang.file_format import FileMetadata
from wenchang.identity import Identity, SandboxResolver, ScopeGrant
from wenchang.scope import ScopePolicy
from wenchang.storage.memory import InMemoryStorage
from wenchang.tools import MemoryTools, bind_tools, render_error, render_result
from wenchang.transport import InProcessClient, TransportClient
from wenchang.version_token import VersionToken

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 10, 2, 12, 0, 0, tzinfo=UTC)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_SOURCE = "test-surface"


class _StoreClient:
    """Forwards the six MemoryStore operations; records get_memory_index scope maps."""

    def __init__(self, store: MemoryStore) -> None:
        self.store = store
        self.scope_maps: list[dict[str, str]] = []

    def read_file(self, path: str) -> MemoryFile:
        return self.store.read_file(path)

    def write_file(
        self,
        path: str,
        content: str,
        metadata: FileMetadata,
        expected_version: VersionToken | None,
        *,
        source: str,
    ) -> MemoryFile:
        return self.store.write_file(path, content, metadata, expected_version, source=source)

    def append_line(
        self,
        path: str,
        line: str,
        expected_version: VersionToken,
        *,
        source: str,
        aliases: Sequence[str] | None = None,
        description: str | None = None,
    ) -> MemoryFile:
        return self.store.append_line(
            path, line, expected_version, source=source, aliases=aliases, description=description
        )

    def replace_fact(
        self,
        path: str,
        old_string: str,
        new_string: str,
        expected_version: VersionToken,
        *,
        source: str,
        aliases: Sequence[str] | None = None,
        description: str | None = None,
    ) -> MemoryFile:
        return self.store.replace_fact(
            path,
            old_string,
            new_string,
            expected_version,
            source=source,
            aliases=aliases,
            description=description,
        )

    def list_prefix(self, prefix: str, cursor: ListCursor | None = None) -> ListPage:
        return self.store.list_prefix(prefix, cursor)

    def delete_file(self, path: str, expected_version: VersionToken) -> None:
        return self.store.delete_file(path, expected_version)

    def get_memory_index(self, scope_map: Mapping[str, str]) -> MemoryIndex:
        self.scope_maps.append(dict(scope_map))
        return MemoryIndex()


_ORG_ROLES = frozenset({"owner", "admin", "editor", "viewer", "auditor"})


def _identity() -> Identity:
    return Identity({"user": ScopeGrant("u-1", "owner"), "org": ScopeGrant("o-9", "member")})


def _policy() -> ScopePolicy:
    return ScopePolicy({"org": _ORG_ROLES})


def _client() -> _StoreClient:
    return _StoreClient(MemoryStore(InMemoryStorage(), clock=lambda: _NOW))


def _bind(client: _StoreClient) -> MemoryTools:
    return bind_tools(client, SandboxResolver(_identity()), object(), _policy(), source=_SOURCE)


def _json_safe(out: dict[str, object]) -> None:
    assert json.loads(json.dumps(out)) == out


def test_store_client_satisfies_transport_client() -> None:
    """AIE-1044, SC-002: the tests-only store client is a TransportClient."""
    assert isinstance(_client(), TransportClient)


def test_end_to_end_lifecycle() -> None:
    """AIE-1044, SC-002: create, read, append, replace, list, index, delete through the tools."""
    client = _client()
    tools = _bind(client)
    path = "user/u-1/notes/a.md"

    created = tools.write_file(
        "user", "notes", "a", "- [stated] likes tea\n", "Drink preferences", ["drinks"], None
    )
    assert created.path == path
    _json_safe(render_result(created))

    read = tools.read_file("user", "notes", "a")
    assert read.path == path
    assert read.content == "- [stated] likes tea\n"
    assert read.metadata.description == "Drink preferences"
    assert read.metadata.aliases == ("drinks",)
    assert read.metadata.sources == frozenset({_SOURCE})
    assert read.metadata.last_updated != _EPOCH
    assert read.metadata.last_updated == _NOW
    rendered_read = render_result(read)
    _json_safe(rendered_read)
    assert rendered_read["sources"] == [_SOURCE]
    assert rendered_read["last_updated"] == "2026-10-02T12:00:00Z"
    assert (rendered_read["scope"], rendered_read["area"], rendered_read["name"]) == (
        "user",
        "notes",
        "a",
    )

    appended = tools.append_line("user", "notes", "a", "- [observed] drinks coffee", read.version)
    assert appended.content == "- [stated] likes tea\n- [observed] drinks coffee\n"
    assert appended.metadata.sources == frozenset({_SOURCE})
    _json_safe(render_result(appended))

    replaced = tools.replace_fact(
        "user", "notes", "a", "likes tea", "likes green tea", appended.version
    )
    assert replaced.content == "- [stated] likes green tea\n- [observed] drinks coffee\n"
    _json_safe(render_result(replaced))

    page = tools.list_prefix("user", "notes")
    assert [entry.path for entry in page.entries] == [path]
    assert page.entries[0].version == replaced.version
    assert page.next_cursor is None
    _json_safe(render_result(page))

    whole_scope = tools.list_prefix("user")
    assert [entry.path for entry in whole_scope.entries] == [path]
    _json_safe(render_result(whole_scope))

    index = tools.get_memory_index()
    assert client.scope_maps == [{"user": "u-1", "org": "o-9"}]
    assert index == MemoryIndex()
    _json_safe(render_result(index))

    assert tools.delete_file("user", "notes", "a", replaced.version) is None
    assert render_result(None) == {"ok": True}

    with pytest.raises(NotFoundError) as excinfo:
        tools.read_file("user", "notes", "a")
    assert excinfo.value.reason is NotFoundReason.FILE_ABSENT
    _json_safe(render_error(excinfo.value))


def test_append_line_unions_aliases_and_replaces_description_end_to_end() -> None:
    """AIE-1151, US4.15: append_line with aliases and description through
    InProcessClient over a real MemoryStore adds the alias and replaces the
    description in what read_file returns.
    """
    store = MemoryStore(InMemoryStorage(), clock=lambda: _NOW)
    tools = bind_tools(
        InProcessClient(store), SandboxResolver(_identity()), object(), _policy(), source=_SOURCE
    )
    created = tools.write_file("user", "notes", "a", "- [stated] a\n", "d", ["x"], None)

    tools.append_line(
        "user", "notes", "a", "- [stated] b", created.version, aliases=["z"], description="d2"
    )

    read = tools.read_file("user", "notes", "a")
    assert read.content == "- [stated] a\n- [stated] b\n"
    assert read.metadata.aliases == ("x", "z")
    assert type(read.metadata.aliases) is tuple
    assert read.metadata.description == "d2"


def test_end_to_end_rejections() -> None:
    """AIE-1044, SC-002: system/, role, and ungranted-scope rejections never reach the store."""
    client = _client()
    tools = _bind(client)

    with pytest.raises(RestrictedScopeError) as system_info:
        tools.write_file("user", "system", "rules", "- [system] x\n", "Rules", [], None)
    assert system_info.value.reason is RestrictionReason.SYSTEM_READ_ONLY
    assert system_info.value.path == "user/u-1/system/rules.md"
    rendered_system = render_error(system_info.value)
    _json_safe(rendered_system)
    assert rendered_system["reason"] == "system_read_only"

    with pytest.raises(RestrictedScopeError) as role_info:
        tools.write_file("org", "notes", "a", "- [stated] x\n", "Org notes", [], None)
    assert role_info.value.reason is RestrictionReason.ROLE_REQUIRED
    assert role_info.value.path == "org/o-9/notes/a.md"
    assert role_info.value.required_roles == _ORG_ROLES
    rendered_role = render_error(role_info.value)
    _json_safe(rendered_role)
    assert rendered_role["required_roles"] == ["admin", "auditor", "editor", "owner", "viewer"]

    with pytest.raises(InvalidArgumentError) as scope_info:
        tools.read_file("team", "notes", "a")
    assert scope_info.value.argument == "scope"
    rendered_scope = render_error(scope_info.value)
    _json_safe(rendered_scope)
    assert rendered_scope["argument"] == "scope"
    assert rendered_scope["category"] == "recoverable"

    assert client.store.list_prefix("user/").entries == ()
    assert client.store.list_prefix("org/").entries == ()
