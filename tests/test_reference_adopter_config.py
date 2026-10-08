"""Reference adopter configuration shape (AIE-1059, US1.1 through US1.9)."""

import re
from datetime import UTC, datetime, timedelta

import pytest

from reference_adopter import (
    ADMIN_IDENTITY,
    MEMBER_IDENTITY,
    ORGANIZATION,
    PARTIAL_IDENTITY,
    PROJECT,
    REFERENCE_POLICY,
    REFERENCE_ROLES,
    REFERENCE_SCOPE_GUIDANCE,
    REFERENCE_SCOPES,
    REFERENCE_SEED_AREAS,
    REFERENCE_SEED_FILES,
    SEED_AREAS_BY_SCOPE,
    TRAVELER_IDENTITY,
    USER,
    reference_store,
    ticking_clock,
)
from wenchang.identity import Identity, IdentityResolver, SandboxResolver
from wenchang.paths import is_valid_segment
from wenchang.scope import ScopePolicy
from wenchang.testing import ResolverConformance

pytestmark = pytest.mark.unit

_SLUG = re.compile(r"[a-z0-9][a-z0-9_-]*")


def test_scopes_are_user_project_organization() -> None:
    """The fixture's scopes are exactly user, project, organization (AIE-1059, US1.1)."""
    assert set(REFERENCE_SCOPES) == {"user", "project", "organization"}
    assert len(REFERENCE_SCOPES) == 3


def test_only_organization_writes_are_restricted_to_admin_and_owner() -> None:
    """Organization is restricted to admin/owner; project and user are open (AIE-1059, US1.2)."""
    assert REFERENCE_POLICY.is_write_restricted(ORGANIZATION)
    assert REFERENCE_POLICY.permitted_roles(ORGANIZATION) == frozenset({"admin", "owner"})
    for scope in (PROJECT, USER):
        assert not REFERENCE_POLICY.is_write_restricted(scope)
        assert REFERENCE_POLICY.permitted_roles(scope) is None


def test_store_factory_uses_reference_scope_priority() -> None:
    """The store factory's scope_priority is user, project, organization (AIE-1059, US1.3)."""
    assert reference_store().scope_priority == ("user", "project", "organization")


def test_seed_areas_match_section_nine() -> None:
    """Seed areas per scope match Section 9 and are valid slugs, never system (AIE-1059, US1.4)."""
    assert dict(SEED_AREAS_BY_SCOPE) == {
        "user": ("identity", "preferences", "workflows", "people"),
        "project": ("taxonomy", "metrics", "entities", "conventions", "glossary"),
        "organization": ("business-context", "vocabulary"),
    }
    for areas in SEED_AREAS_BY_SCOPE.values():
        for area in areas:
            assert is_valid_segment(area)
            assert _SLUG.fullmatch(area)
            assert area != "system"


def test_seed_areas_slot_names_every_area_scope_and_system() -> None:
    """The seed_areas slot text names every area, scope, and system/ (AIE-1059, US1.5)."""
    for scope, areas in SEED_AREAS_BY_SCOPE.items():
        assert scope in REFERENCE_SEED_AREAS
        for area in areas:
            assert area in REFERENCE_SEED_AREAS
    assert "system/" in REFERENCE_SEED_AREAS


def _bullet(text: str, scope: str) -> str:
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"- {scope}"))
    block = [lines[start]]
    for line in lines[start + 1 :]:
        if line.startswith("- ") or line.strip() == "":
            break
        block.append(line)
    return "\n".join(block)


def test_scope_guidance_names_every_scope_and_organization_roles() -> None:
    """Guidance names every scope; the organization bullet has admin and owner (AIE-1059, US1.6)."""
    for scope in REFERENCE_SCOPES:
        assert scope in REFERENCE_SCOPE_GUIDANCE
    bullet = _bullet(REFERENCE_SCOPE_GUIDANCE, ORGANIZATION)
    assert "admin" in bullet
    assert "owner" in bullet


def test_seed_files_cover_every_scope_and_stay_in_known_areas() -> None:
    """Seed files cover every scope, use known areas, and end in a newline (AIE-1059, US1.7)."""
    for scope in REFERENCE_SCOPES:
        in_scope = [seed for seed in REFERENCE_SEED_FILES if seed.scope == scope]
        assert len([seed for seed in in_scope if seed.area == "system"]) == 1
        assert [seed for seed in in_scope if seed.area in SEED_AREAS_BY_SCOPE[scope]]
    for seed in REFERENCE_SEED_FILES:
        assert seed.area == "system" or seed.area in SEED_AREAS_BY_SCOPE[seed.scope]
        assert seed.content.endswith("\n")


class _ReferenceConformance(ResolverConformance[object]):
    """Shared contract fixtures; subclasses supply the identity."""

    identity: Identity

    @pytest.fixture
    def resolver(self) -> IdentityResolver[object]:
        return SandboxResolver(self.identity)

    @pytest.fixture
    def valid_credentials(self) -> object:
        return object()

    @pytest.fixture
    def invalid_credentials(self) -> object:
        pytest.skip("SandboxResolver accepts every credential")

    @pytest.fixture
    def policy(self) -> ScopePolicy:
        return REFERENCE_POLICY

    @pytest.fixture
    def expected_scopes(self) -> frozenset[str]:
        return frozenset(REFERENCE_SCOPES)

    @pytest.fixture
    def known_roles(self) -> frozenset[str]:
        return REFERENCE_ROLES


class TestMemberIdentityConformance(_ReferenceConformance):
    """Member identity passes the resolver conformance suite (AIE-1059, US1.8)."""

    identity = MEMBER_IDENTITY


class TestAdminIdentityConformance(_ReferenceConformance):
    """Admin identity passes the resolver conformance suite (AIE-1059, US1.8)."""

    identity = ADMIN_IDENTITY


class TestTravelerIdentityConformance(_ReferenceConformance):
    """Traveler identity passes the resolver conformance suite (AIE-1059, US1.8)."""

    identity = TRAVELER_IDENTITY


class TestPartialIdentityConformance(_ReferenceConformance):
    """Partial-project identity passes the resolver conformance suite (AIE-1059, US1.8)."""

    identity = PARTIAL_IDENTITY


def test_ticking_clock_advances_by_step() -> None:
    """ticking_clock returns start, start+step, start+2*step (AIE-1059, US1.9)."""
    start = datetime(2026, 3, 1, 12, tzinfo=UTC)
    step = timedelta(seconds=5)
    clock = ticking_clock(start, step)

    assert [clock(), clock(), clock()] == [start, start + step, start + 2 * step]


def test_ticking_clock_rejects_naive_start() -> None:
    """A naive start raises ValueError (AIE-1059, US1.9)."""
    with pytest.raises(ValueError):
        ticking_clock(datetime(2026, 1, 1))


@pytest.mark.parametrize(
    "step",
    [timedelta(milliseconds=1500), timedelta(0), timedelta(seconds=-1)],
)
def test_ticking_clock_rejects_bad_step(step: timedelta) -> None:
    """A step that is not a positive whole number of seconds raises ValueError (AIE-1059, US1.9)."""
    with pytest.raises(ValueError):
        ticking_clock(step=step)
