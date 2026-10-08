"""End-to-end lifecycle of the reference adopter through the tool layer.

Covers AIE-1059: bind_tools over InProcessClient(MemoryStore(InMemoryStorage())) with the
Section 9 reference adopter configuration, asserted through render_result and render_error.
"""

import json
from typing import cast

import pytest

from reference_adopter import (
    ADMIN_IDENTITY,
    ADMIN_USER_ID,
    AGENT_SOURCE,
    MEMBER_IDENTITY,
    MEMBER_USER_ID,
    ORGANIZATION,
    ORGANIZATION_ID,
    OTHER_ORGANIZATION_ID,
    OTHER_PROJECT_ID,
    PARTIAL_IDENTITY,
    PARTIAL_PROJECT_ID,
    PROJECT,
    PROJECT_ID,
    REFERENCE_CLOCK_START,
    REFERENCE_SEED_FILES,
    SEED_SOURCE,
    TRAVELER_IDENTITY,
    USER,
    SeedFile,
    bind_reference_tools,
    reference_store,
    seed_path,
    seed_reference_memory,
)
from wenchang.core import ListCursor, ListPage, MemoryFile, MemoryIndex, index_entry_bytes
from wenchang.errors import NotFoundError, RestrictedScopeError, VersionConflictError
from wenchang.file_format import FileMetadata
from wenchang.identity import Identity
from wenchang.paths import build_path, build_prefix, parse_path
from wenchang.tools import MemoryTools, render_error, render_result
from wenchang.transport import InProcessClient
from wenchang.version_token import VersionToken

pytestmark = pytest.mark.unit

_ENTRY_KEYS = {
    "path",
    "scope",
    "area",
    "name",
    "version",
    "description",
    "aliases",
    "sources",
    "last_updated",
}


def _rendered(value: MemoryFile | ListPage | MemoryIndex | None) -> dict[str, object]:
    out = render_result(value)
    assert json.loads(json.dumps(out)) == out
    return out


def _rendered_error(exc: Exception) -> dict[str, object]:
    out = render_error(exc)
    assert json.loads(json.dumps(out)) == out
    return out


def _entries(rendered: dict[str, object]) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], rendered["entries"])


def _paths(rendered: dict[str, object]) -> list[str]:
    return [cast(str, entry["path"]) for entry in _entries(rendered)]


def _text(rendered: dict[str, object], key: str) -> str:
    return cast(str, rendered[key])


def _version(rendered: dict[str, object]) -> VersionToken:
    return VersionToken(_text(rendered, "version"))


def _seeded(
    identity: Identity = MEMBER_IDENTITY,
) -> tuple[InProcessClient, MemoryTools]:
    """Seed the member's entities and bind tools for the given identity."""
    client = InProcessClient(reference_store())
    seed_reference_memory(client)
    return client, bind_reference_tools(client, identity)


def _seed_of(scope: str, area: str) -> SeedFile:
    (seed,) = (s for s in REFERENCE_SEED_FILES if s.scope == scope and s.area == area)
    return seed


def _put(client: InProcessClient, path: str, content: str = "- [stated] Extra.\n") -> None:
    metadata = FileMetadata("Extra file", (), frozenset(), REFERENCE_CLOCK_START)
    client.write_file(path, content, metadata, None, source=SEED_SOURCE)


def _tier(entry: dict[str, object]) -> str:
    return "system" if entry["area"] == "system" else _text(entry, "scope")


def test_us2_1_index_holds_exactly_the_seed_files() -> None:
    """AIE-1059, US2.1: bootstrap index lists exactly the seed paths, metadata only."""
    _, tools = _seeded()

    rendered = _rendered(tools.get_memory_index())

    assert set(_paths(rendered)) == {seed_path(s) for s in REFERENCE_SEED_FILES}
    assert len(_paths(rendered)) == len(REFERENCE_SEED_FILES)
    assert all(set(entry) == _ENTRY_KEYS for entry in _entries(rendered))
    assert rendered["capped"] == []


def test_us2_2_index_orders_system_then_user_project_organization() -> None:
    """AIE-1059, US2.2: system entries first, then user, project, organization."""
    _, tools = _seeded()

    rendered = _rendered(tools.get_memory_index())

    tiers = [_tier(entry) for entry in _entries(rendered)]
    system_count = sum(1 for s in REFERENCE_SEED_FILES if s.area == "system")
    expected = ["system"] * system_count
    for scope in (USER, PROJECT, ORGANIZATION):
        expected += [scope] * sum(
            1 for s in REFERENCE_SEED_FILES if s.scope == scope and s.area != "system"
        )
    assert tiers == expected


def test_us2_3_index_omits_another_users_file() -> None:
    """AIE-1059, US2.3: the scope map comes from the bound identity."""
    client, tools = _seeded()
    other = build_path(USER, ADMIN_USER_ID, "preferences", "grace-note")
    _put(client, other)

    rendered = _rendered(tools.get_memory_index())

    assert other not in _paths(rendered)
    assert set(_paths(rendered)) == {seed_path(s) for s in REFERENCE_SEED_FILES}


def test_us2_4_index_entries_carry_the_seed_source() -> None:
    """AIE-1059, US2.4: each seeded entry's sources is the seeding job."""
    _, tools = _seeded()

    rendered = _rendered(tools.get_memory_index())

    assert all(entry["sources"] == [SEED_SOURCE] for entry in _entries(rendered))


_LIFECYCLE_ROWS = [
    (USER, MEMBER_IDENTITY, "preferences"),
    (PROJECT, MEMBER_IDENTITY, "metrics"),
    (ORGANIZATION, ADMIN_IDENTITY, "vocabulary"),
]


@pytest.mark.parametrize(
    ("scope", "identity", "area"),
    _LIFECYCLE_ROWS,
    ids=["user-member", "project-member", "organization-admin"],
)
def test_us3_scope_lifecycle(scope: str, identity: Identity, area: str) -> None:
    """AIE-1059, US3.1-3.7: read, write, append, replace, delete, and read-after-delete."""
    _, tools = _seeded(identity)
    name = "reference-e2e"
    path = build_path(scope, identity.entity_id(scope), area, name)

    # 3.1
    curated = _seed_of(scope, "system")
    read_system = _rendered(tools.read_file(scope, "system", curated.name))
    assert read_system["content"] == curated.content
    assert read_system["description"] == curated.description
    assert read_system["area"] == "system"

    # 3.2
    content = "- [stated] First fact.\n- [stated] Second fact.\n"
    written = _rendered(tools.write_file(scope, area, name, content, "E2E file", ["alpha"], None))
    assert written["path"] == path
    assert written["sources"] == [AGENT_SOURCE]
    assert written["aliases"] == ["alpha"]
    assert written["description"] == "E2E file"

    # 3.3
    read_back = _rendered(tools.read_file(scope, area, name))
    for key in ("content", "description", "aliases", "version"):
        assert read_back[key] == written[key]

    # 3.4
    line = "- [observed] Third fact."
    appended = _rendered(
        tools.append_line(
            scope,
            area,
            name,
            line,
            _version(read_back),
            aliases=["beta"],
            description="Updated E2E file",
        )
    )
    assert appended["content"] == _text(read_back, "content") + line + "\n"
    assert appended["aliases"] == ["alpha", "beta"]
    assert appended["description"] == "Updated E2E file"
    assert appended["version"] != read_back["version"]

    # 3.5
    replaced = _rendered(
        tools.replace_fact(scope, area, name, "Second fact", "Revised fact", _version(appended))
    )
    before = _text(appended, "content")
    assert replaced["content"] == before.replace("Second fact", "Revised fact")
    old_lines = before.splitlines(keepends=True)
    new_lines = _text(replaced, "content").splitlines(keepends=True)
    assert len(new_lines) == len(old_lines)
    assert [a for a, b in zip(old_lines, new_lines, strict=True) if a != b] == [
        "- [stated] Second fact.\n"
    ]

    # 3.6
    assert _rendered(tools.delete_file(scope, area, name, _version(replaced))) == {"ok": True}

    # 3.7
    with pytest.raises(NotFoundError) as excinfo:
        tools.read_file(scope, area, name)
    error = _rendered_error(excinfo.value)
    assert error["category"] == "recoverable"
    assert error["reason"] == "file_absent"


def _write_note(tools: MemoryTools, scope: str, area: str) -> None:
    tools.write_file(scope, area, "session-note", "- [stated] Session note.\n", "Note", [], None)


def _after_session() -> tuple[InProcessClient, MemoryTools, MemoryTools]:
    client, member = _seeded()
    admin = bind_reference_tools(client, ADMIN_IDENTITY)
    _write_note(member, USER, "preferences")
    _write_note(member, PROJECT, "metrics")
    _write_note(admin, ORGANIZATION, "vocabulary")
    charts = member.read_file(USER, "preferences", "charts")
    member.delete_file(USER, "preferences", "charts", charts.version)
    return client, member, admin


def test_us4_1_index_reflects_session_writes_and_deletes() -> None:
    """AIE-1059, US4.1: created files appear first in their tier; the deleted file is gone."""
    _, member, _ = _after_session()

    rendered = _rendered(member.get_memory_index())

    paths = _paths(rendered)
    note_paths = {
        scope: build_path(scope, MEMBER_IDENTITY.entity_id(scope), area, "session-note")
        for scope, area in (
            (USER, "preferences"),
            (PROJECT, "metrics"),
            (ORGANIZATION, "vocabulary"),
        )
    }
    for note in note_paths.values():
        assert note in paths
    assert seed_path(_seed_of(USER, "preferences")) not in paths
    for scope, note in note_paths.items():
        tier = [
            _text(e, "path")
            for e in _entries(rendered)
            if e["scope"] == scope and e["area"] != "system"
        ]
        assert tier[0] == note
        assert len(tier) > 1


def test_us4_2_admin_index_sees_shared_scopes_not_user_ada() -> None:
    """AIE-1059, US4.2: the admin sees the shared files both users wrote, none of u-ada's."""
    _, _, admin = _after_session()

    rendered = _rendered(admin.get_memory_index())

    paths = set(_paths(rendered))
    shared_seeds = {seed_path(s) for s in REFERENCE_SEED_FILES if s.scope != USER}
    assert shared_seeds <= paths
    assert build_path(PROJECT, PROJECT_ID, "metrics", "session-note") in paths
    assert build_path(ORGANIZATION, ORGANIZATION_ID, "vocabulary", "session-note") in paths
    assert not any(p.startswith(build_prefix(USER, MEMBER_USER_ID)) for p in paths)


def test_us4_3_traveler_follows_the_user_across_organizations() -> None:
    """AIE-1059, US4.3: u-ada's user files appear in another organization and project."""
    client, tools = _seeded(TRAVELER_IDENTITY)
    project_file = build_path(PROJECT, OTHER_PROJECT_ID, "metrics", "other-note")
    org_file = build_path(ORGANIZATION, OTHER_ORGANIZATION_ID, "vocabulary", "other-note")
    _put(client, project_file)
    _put(client, org_file)

    rendered = _rendered(tools.get_memory_index())

    expected = {seed_path(s) for s in REFERENCE_SEED_FILES if s.scope == USER}
    assert set(_paths(rendered)) == expected | {project_file, org_file}
    assert not any(
        p.startswith(("project/p-checkout/", "organization/o-acme/")) for p in _paths(rendered)
    )


def test_us4_4_partial_member_reads_the_organization_scope() -> None:
    """AIE-1059, US4.4: a member of another project reads the organization and own project."""
    client, tools = _seeded(PARTIAL_IDENTITY)
    project_file = build_path(PROJECT, PARTIAL_PROJECT_ID, "metrics", "billing-note")
    _put(client, project_file)

    rendered = _rendered(tools.get_memory_index())

    expected = {seed_path(s) for s in REFERENCE_SEED_FILES if s.scope == ORGANIZATION}
    assert set(_paths(rendered)) == expected | {project_file}
    assert not any(p.startswith(("project/p-checkout/", "user/u-ada/")) for p in _paths(rendered))


_MUTATING_TOOLS = ("write_file", "append_line", "replace_fact", "delete_file")


def _mutate(
    tools: MemoryTools, tool: str, scope: str, area: str, seed: SeedFile, version: VersionToken
) -> None:
    """Call one mutating tool on the seed file's name with a real version."""
    name = seed.name
    fact = seed.content.splitlines()[0]
    if tool == "write_file":
        tools.write_file(scope, area, name, "- [stated] Replaced.\n", "New", [], version)
    elif tool == "append_line":
        tools.append_line(scope, area, name, "- [stated] Added.", version)
    elif tool == "replace_fact":
        tools.replace_fact(scope, area, name, fact, "- [stated] Changed.", version)
    else:
        tools.delete_file(scope, area, name, version)


def _snapshot(client: InProcessClient) -> dict[str, tuple[str, VersionToken]]:
    """Content and version of every file under every entity of the reference identities."""
    entities = {
        (scope, grant.entity_id)
        for identity in (MEMBER_IDENTITY, ADMIN_IDENTITY)
        for scope, grant in identity.grants.items()
    }
    found: dict[str, tuple[str, VersionToken]] = {}
    for scope, entity_id in entities:
        cursor = None
        while True:
            page = client.list_prefix(build_prefix(scope, entity_id), cursor)
            for entry in page.entries:
                file = client.read_file(entry.path)
                found[file.path] = (file.content, file.version)
            cursor = page.next_cursor
            if cursor is None:
                break
    return found


def _assert_system_untouched(
    client: InProcessClient, before: dict[str, tuple[str, VersionToken]]
) -> None:
    after = _snapshot(client)
    assert set(after) == set(before)
    system = {path for path in before if parse_path(path).area == "system"}
    assert len(system) == sum(1 for s in REFERENCE_SEED_FILES if s.area == "system")
    assert {path: after[path] for path in system} == {path: before[path] for path in system}


@pytest.mark.parametrize("tool", _MUTATING_TOOLS)
@pytest.mark.parametrize(
    ("scope", "identity"),
    [(USER, MEMBER_IDENTITY), (PROJECT, ADMIN_IDENTITY), (ORGANIZATION, ADMIN_IDENTITY)],
    ids=["user-member", "project-admin", "organization-admin"],
)
def test_us5_1_system_area_is_read_only_through_tools(
    tool: str, scope: str, identity: Identity
) -> None:
    """AIE-1059, US5.1 and US5.3: every mutating tool is rejected on system/, files unchanged."""
    client, tools = _seeded(identity)
    seed = _seed_of(scope, "system")
    path = seed_path(seed, identity)
    version = client.read_file(path).version
    before = _snapshot(client)

    with pytest.raises(RestrictedScopeError) as excinfo:
        _mutate(tools, tool, scope, "system", seed, version)

    error = _rendered_error(excinfo.value)
    assert error["category"] == "permanent"
    assert error["reason"] == "system_read_only"
    assert error["path"] == path
    _assert_system_untouched(client, before)


@pytest.mark.parametrize("tool", _MUTATING_TOOLS)
def test_us5_2_system_check_precedes_role_check(tool: str) -> None:
    """AIE-1059, US5.2 and US5.3: a member writing organization system/ gets system_read_only."""
    client, tools = _seeded(MEMBER_IDENTITY)
    seed = _seed_of(ORGANIZATION, "system")
    assert seed.name == "fiscal-calendar"
    version = client.read_file(seed_path(seed)).version
    before = _snapshot(client)

    with pytest.raises(RestrictedScopeError) as excinfo:
        _mutate(tools, tool, ORGANIZATION, "system", seed, version)

    error = _rendered_error(excinfo.value)
    assert error["reason"] == "system_read_only"
    assert error["category"] == "permanent"
    _assert_system_untouched(client, before)


def test_us5_4_transport_accepts_the_system_write_the_tools_reject() -> None:
    """AIE-1059, US5.4: the client writes project system/ where the tools raise."""
    client, tools = _seeded(ADMIN_IDENTITY)
    seed = _seed_of(PROJECT, "system")
    path = seed_path(seed)
    assert path == build_path(PROJECT, PROJECT_ID, "system", "event-catalog")
    current = client.read_file(path)

    with pytest.raises(RestrictedScopeError) as excinfo:
        tools.write_file(
            PROJECT, "system", seed.name, "- [system] Tool write.\n", "d", [], current.version
        )
    assert _rendered_error(excinfo.value)["reason"] == "system_read_only"

    metadata = FileMetadata(seed.description, seed.aliases, frozenset(), REFERENCE_CLOCK_START)
    written = client.write_file(
        path, "- [system] Curated update.\n", metadata, current.version, source=SEED_SOURCE
    )

    assert written.version != current.version


@pytest.mark.parametrize("tool", _MUTATING_TOOLS)
def test_us6_1_organization_writes_require_admin_or_owner(tool: str) -> None:
    """AIE-1059, US6.1 and US6.3: a member's mutating calls on organization are role-gated."""
    client, tools = _seeded(MEMBER_IDENTITY)
    seed = _seed_of(ORGANIZATION, "vocabulary")
    path = seed_path(seed)
    before = client.read_file(path)

    with pytest.raises(RestrictedScopeError) as excinfo:
        _mutate(tools, tool, ORGANIZATION, "vocabulary", seed, before.version)

    error = _rendered_error(excinfo.value)
    assert error["category"] == "permanent"
    assert error["reason"] == "role_required"
    assert error["scope"] == "organization"
    assert error["required_roles"] == ["admin", "owner"]
    after = client.read_file(path)
    assert (after.content, after.version) == (before.content, before.version)


def test_us6_2_members_can_read_the_restricted_scope() -> None:
    """AIE-1059, US6.2: the organization restriction is on writes only."""
    _, tools = _seeded(MEMBER_IDENTITY)
    seed = _seed_of(ORGANIZATION, "vocabulary")

    rendered = _rendered(tools.read_file(ORGANIZATION, "vocabulary", seed.name))

    assert rendered["content"] == seed.content


def _read_activation_as_both() -> tuple[MemoryTools, MemoryTools, SeedFile, VersionToken]:
    client, member = _seeded()
    admin = bind_reference_tools(client, ADMIN_IDENTITY)
    seed = _seed_of(PROJECT, "metrics")
    v0_member = _version(_rendered(member.read_file(PROJECT, "metrics", seed.name)))
    v0_admin = _version(_rendered(admin.read_file(PROJECT, "metrics", seed.name)))
    assert v0_member == v0_admin
    return member, admin, seed, v0_member


def test_us7_1_stale_append_conflicts_with_current_content() -> None:
    """AIE-1059, US7.1: the second writer from the same version gets the current content."""
    member, admin, seed, v0 = _read_activation_as_both()
    appended = _rendered(
        admin.append_line(PROJECT, "metrics", seed.name, "- [observed] LA fact.", v0)
    )

    with pytest.raises(VersionConflictError) as excinfo:
        member.append_line(PROJECT, "metrics", seed.name, "- [observed] LM fact.", v0)

    error = _rendered_error(excinfo.value)
    assert error["category"] == "recoverable"
    assert error["path"] == seed_path(seed, MEMBER_IDENTITY)
    assert error["content"] == seed.content + "- [observed] LA fact.\n"
    assert error["version"] == appended["version"]
    assert error["version"] != v0


def test_us7_2_retry_with_the_returned_version_merges_both_lines() -> None:
    """AIE-1059, US7.2: retrying with the conflict's version succeeds."""
    member, admin, seed, v0 = _read_activation_as_both()
    admin.append_line(PROJECT, "metrics", seed.name, "- [observed] LA fact.", v0)
    with pytest.raises(VersionConflictError) as excinfo:
        member.append_line(PROJECT, "metrics", seed.name, "- [observed] LM fact.", v0)
    conflict = _rendered_error(excinfo.value)

    retried = _rendered(
        member.append_line(
            PROJECT,
            "metrics",
            seed.name,
            "- [observed] LM fact.",
            VersionToken(_text(conflict, "version")),
        )
    )

    assert retried["content"] == seed.content + "- [observed] LA fact.\n- [observed] LM fact.\n"


def _run_budget_steps(client: InProcessClient) -> MemoryTools:
    """Seed, then M writes project/metrics/budget-a and budget-b."""
    seed_reference_memory(client)
    tools = bind_reference_tools(client)
    long_description = "Budget notes covering " + "quarterly planning detail, " * 8
    for name, description in (("budget-a", long_description), ("budget-b", "Budget")):
        tools.write_file(PROJECT, "metrics", name, "- [stated] Budget.\n", description, [], None)
    return tools


def _capped_budget_run() -> tuple[MemoryTools, MemoryIndex, MemoryIndex]:
    """Return the capped store's tools, its index, and the uncapped store's index."""
    uncapped_tools = _run_budget_steps(InProcessClient(reference_store()))
    uncapped = uncapped_tools.get_memory_index()
    budget_a = build_path(PROJECT, PROJECT_ID, "metrics", "budget-a")
    budget_b = build_path(PROJECT, PROJECT_ID, "metrics", "budget-b")
    first_project = next(
        e
        for e in uncapped.entries
        if parse_path(e.path).scope == PROJECT and parse_path(e.path).area != "system"
    )
    assert first_project.path == budget_b
    b_position = [e.path for e in uncapped.entries].index(budget_b)
    later = uncapped.entries[b_position + 1 :]
    # Slack equals the smallest later entry: a skip-and-keep-filling index would admit it.
    slack = min(index_entry_bytes(e) for e in later)
    assert later[0].path == budget_a
    assert index_entry_bytes(later[0]) > slack
    cap = (
        sum(
            index_entry_bytes(e)
            for e in uncapped.entries
            if parse_path(e.path).area == "system"
            or parse_path(e.path).scope == USER
            or e.path == budget_b
        )
        + slack
    )
    capped_store = reference_store(index_max_bytes=cap, list_page_size=1)
    capped_tools = _run_budget_steps(InProcessClient(capped_store))
    return capped_tools, capped_tools.get_memory_index(), uncapped


def test_us8_1_capped_index_is_a_priority_prefix_of_the_uncapped_index() -> None:
    """AIE-1059, US8.1: the cap keeps system, user, and exactly one project entry."""
    _, capped, uncapped = _capped_budget_run()

    capped_entries = _entries(_rendered(capped))
    uncapped_entries = _entries(_rendered(uncapped))

    assert capped_entries == uncapped_entries[: len(capped_entries)]
    system_count = sum(1 for s in REFERENCE_SEED_FILES if s.area == "system")
    user_count = sum(1 for s in REFERENCE_SEED_FILES if s.scope == USER and s.area != "system")
    assert [_tier(e) for e in capped_entries] == (
        ["system"] * system_count + [USER] * user_count + [PROJECT]
    )
    assert capped_entries[-1]["path"] == build_path(PROJECT, PROJECT_ID, "metrics", "budget-b")
    assert not any(e["scope"] == ORGANIZATION and e["area"] != "system" for e in capped_entries)


def test_us8_2_capped_rows_name_every_omitted_area() -> None:
    """AIE-1059, US8.2: capped rows are exact, in prefix order."""
    _, capped, _ = _capped_budget_run()

    assert _rendered(capped)["capped"] == [
        {
            "prefix": "organization/o-acme/vocabulary/",
            "scope": "organization",
            "area": "vocabulary",
            "omitted": 1,
        },
        {
            "prefix": "project/p-checkout/entities/",
            "scope": "project",
            "area": "entities",
            "omitted": 1,
        },
        {
            "prefix": "project/p-checkout/metrics/",
            "scope": "project",
            "area": "metrics",
            "omitted": 2,
        },
    ]


def test_us8_3_list_prefix_recovers_the_omitted_files() -> None:
    """AIE-1059, US8.3: paging each capped area lists every file omitted from the index."""
    tools, capped, uncapped = _capped_budget_run()
    rendered = _rendered(capped)
    in_index = set(_paths(rendered))

    max_pages = 0
    for row in cast(list[dict[str, object]], rendered["capped"]):
        prefix = _text(row, "prefix")
        listed: list[str] = []
        cursor: ListCursor | None = None
        pages = 0
        while True:
            page = _rendered(tools.list_prefix(_text(row, "scope"), _text(row, "area"), cursor))
            pages += 1
            listed += _paths(page)
            next_cursor = page["next_cursor"]
            if next_cursor is None:
                break
            cursor = ListCursor(cast(str, next_cursor))
        omitted = {
            e.path for e in uncapped.entries if e.path.startswith(prefix) and e.path not in in_index
        }
        max_pages = max(max_pages, pages)
        assert len(omitted) == row["omitted"]
        assert omitted <= set(listed)
    assert max_pages > 1
