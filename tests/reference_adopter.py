"""The Notion spec section 9 reference adopter configuration, as test fixture data.

Prompt slots, scope priority, write policy, four identities, seed areas, and
seed files, plus helpers to build a store, seed it, and bind tools. This is
illustrative adopter configuration, not library code, and it imports only
public wenchang modules.
"""

import itertools
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Final

from wenchang.core import DEFAULT_INDEX_MAX_BYTES, MemoryFile, MemoryStore
from wenchang.file_format import FileMetadata
from wenchang.identity import Identity, SandboxResolver, ScopeGrant
from wenchang.paths import build_path
from wenchang.prompts import PromptSlots
from wenchang.scope import ScopePolicy
from wenchang.storage.memory import InMemoryStorage
from wenchang.tools import MemoryTools, bind_tools
from wenchang.transport import TransportClient

REFERENCE_PURPOSE: Final[str] = """\
You have persistent memory of your work in Mixpanel: reference it and save to it with these
tools whenever you work with Mixpanel."""

REFERENCE_SCOPE_GUIDANCE: Final[str] = """\
There are three scopes: user, project, and organization. An organization contains projects, and
a user can belong to several organizations.

- user is a private scope: it belongs to the person you are talking with and follows them
  across organizations.
- project is a shared scope, visible to every member of the current project; any member may
  write to it.
- organization is a shared scope, visible to every member of the organization; only admins and
  owners may write to it. Members who can access only some projects read it, so it holds only
  project-agnostic facts. Never write a fact about one project there.

Before saving a new fact to project or organization, ask the user and name the scope. Writes to
user need no ask. If a new fact contradicts one stored in a shared scope, show the stored fact,
say what conflicts, and ask which to keep.

Scope a fact by who it is true for, not who said it: if it would hold for a different person in
this project, use project, or organization if it holds for every project; otherwise use user.
When in doubt, write narrow. "I prefer charts with a dark background" goes in user; "This
project's weekly report goes out on Mondays" in project; "Our fiscal year starts in February"
in organization."""

REFERENCE_SEED_AREAS: Final[str] = """\
- user: identity, preferences, workflows, people
- project: taxonomy, metrics, entities, conventions, glossary
- organization: business-context, vocabulary

Every scope also has a `system/` area."""

REFERENCE_SYSTEMS_OF_RECORD: Final[str] = """\
- Event definitions live in the product's event catalog; refer to an event by its catalog name.
- Dashboards and cohorts are objects with IDs; refer to one by name and ID, and store what it is
  used for and what people have said about it."""

REFERENCE_SLOTS: Final[PromptSlots] = PromptSlots(
    purpose=REFERENCE_PURPOSE,
    scope_guidance=REFERENCE_SCOPE_GUIDANCE,
    seed_areas=REFERENCE_SEED_AREAS,
    systems_of_record=REFERENCE_SYSTEMS_OF_RECORD,
)

REFERENCE_SCOPE_PRIORITY: Final[tuple[str, ...]] = ("user", "project", "organization")

USER: Final = "user"
PROJECT: Final = "project"
ORGANIZATION: Final = "organization"
REFERENCE_SCOPES: Final[tuple[str, ...]] = (USER, PROJECT, ORGANIZATION)

# Excludes "system", which every scope also has.
SEED_AREAS_BY_SCOPE: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        USER: ("identity", "preferences", "workflows", "people"),
        PROJECT: ("taxonomy", "metrics", "entities", "conventions", "glossary"),
        ORGANIZATION: ("business-context", "vocabulary"),
    }
)

ORGANIZATION_WRITE_ROLES: Final[frozenset[str]] = frozenset({"admin", "owner"})
REFERENCE_POLICY: Final[ScopePolicy] = ScopePolicy({ORGANIZATION: ORGANIZATION_WRITE_ROLES})

ORGANIZATION_ID: Final = "o-acme"
PROJECT_ID: Final = "p-checkout"
MEMBER_USER_ID: Final = "u-ada"
ADMIN_USER_ID: Final = "u-grace"
OTHER_ORGANIZATION_ID: Final = "o-globex"
OTHER_PROJECT_ID: Final = "p-other"
PARTIAL_USER_ID: Final = "u-lin"
PARTIAL_PROJECT_ID: Final = "p-billing"

# Member: a plain member of the organization and project.
MEMBER_IDENTITY: Final[Identity] = Identity(
    grants={
        USER: ScopeGrant(MEMBER_USER_ID, "owner"),
        PROJECT: ScopeGrant(PROJECT_ID, "member"),
        ORGANIZATION: ScopeGrant(ORGANIZATION_ID, "member"),
    }
)
# Admin: an organization admin in the same project as the member.
ADMIN_IDENTITY: Final[Identity] = Identity(
    grants={
        USER: ScopeGrant(ADMIN_USER_ID, "owner"),
        PROJECT: ScopeGrant(PROJECT_ID, "member"),
        ORGANIZATION: ScopeGrant(ORGANIZATION_ID, "admin"),
    }
)
# Traveler: the member's user entity in another organization and project.
TRAVELER_IDENTITY: Final[Identity] = Identity(
    grants={
        USER: ScopeGrant(MEMBER_USER_ID, "owner"),
        PROJECT: ScopeGrant(OTHER_PROJECT_ID, "member"),
        ORGANIZATION: ScopeGrant(OTHER_ORGANIZATION_ID, "member"),
    }
)
# Partial: the same organization as the member, a different project.
PARTIAL_IDENTITY: Final[Identity] = Identity(
    grants={
        USER: ScopeGrant(PARTIAL_USER_ID, "owner"),
        PROJECT: ScopeGrant(PARTIAL_PROJECT_ID, "member"),
        ORGANIZATION: ScopeGrant(ORGANIZATION_ID, "member"),
    }
)
REFERENCE_ROLES: Final[frozenset[str]] = frozenset({"owner", "member", "admin"})

SEED_SOURCE: Final = "seed-job"
AGENT_SOURCE: Final = "reference-agent"
REFERENCE_PRODUCT: Final = "Mixpanel"


@dataclass(frozen=True, slots=True)
class SeedFile:
    """One file the seeding job writes; fact lines are "- [label] text" and end with a newline."""

    scope: str
    area: str
    name: str
    content: str
    description: str
    aliases: tuple[str, ...]


# Tuple order is write order.
REFERENCE_SEED_FILES: Final[tuple[SeedFile, ...]] = (
    SeedFile(
        USER,
        "system",
        "profile",
        "- [system] Ada is a product analyst on the checkout team.\n",
        "Curated profile of the user",
        ("profile", "about-user"),
    ),
    SeedFile(
        PROJECT,
        "system",
        "event-catalog",
        "- [system] Event definitions live in the product's event catalog.\n",
        "Where event definitions live",
        ("events", "event-definitions"),
    ),
    SeedFile(
        ORGANIZATION,
        "system",
        "fiscal-calendar",
        "- [system] The fiscal year starts in February.\n",
        "Curated organization fiscal calendar",
        ("fiscal-year",),
    ),
    SeedFile(
        USER,
        "preferences",
        "charts",
        "- [stated] Prefers charts with a dark background.\n",
        "Chart style preferences",
        ("chart-style", "dark-mode"),
    ),
    SeedFile(
        USER,
        "workflows",
        "weekly-review",
        "- [observed] Reviews the checkout funnel every Monday.\n",
        "Weekly funnel review routine",
        ("monday-review",),
    ),
    SeedFile(
        PROJECT,
        "metrics",
        "activation",
        "- [stated] Activation means the second purchase.\n",
        "How the project defines activation",
        ("activated-user",),
    ),
    SeedFile(
        PROJECT,
        "entities",
        "checkout-dashboard",
        '- [stated] Dashboard "Checkout health" (ID 4521) is the team\'s launch-review view.\n',
        "Notes on the Checkout health dashboard",
        ("checkout-health", "dashboard-4521"),
    ),
    SeedFile(
        ORGANIZATION,
        "vocabulary",
        "terms",
        '- [stated] "ARR" means annual recurring revenue.\n',
        "Organization terminology",
        ("glossary", "acronyms"),
    ),
)

REFERENCE_CLOCK_START: Final = datetime(2026, 1, 1, tzinfo=UTC)

_ONE_SECOND: Final = timedelta(seconds=1)


def ticking_clock(
    start: datetime = REFERENCE_CLOCK_START, step: timedelta = _ONE_SECOND
) -> Callable[[], datetime]:
    """A clock returning start, start+step, start+2*step, ... on successive calls.

    Raises ValueError if start is naive or step is not a positive whole number
    of seconds.
    """
    if start.tzinfo is None or start.utcoffset() is None:
        raise ValueError("start must be timezone-aware")
    if step <= timedelta(0) or step % _ONE_SECOND != timedelta(0):
        raise ValueError("step must be a positive whole number of seconds")
    ticks = itertools.count()
    return lambda: start + next(ticks) * step


def reference_store(
    *, index_max_bytes: int = DEFAULT_INDEX_MAX_BYTES, clock: Callable[[], datetime] | None = None
) -> MemoryStore:
    """An in-memory store with the reference scope priority and a fresh ticking_clock() default."""
    return MemoryStore(
        InMemoryStorage(),
        scope_priority=REFERENCE_SCOPE_PRIORITY,
        index_max_bytes=index_max_bytes,
        clock=ticking_clock() if clock is None else clock,
    )


def seed_path(seed: SeedFile, identity: Identity = MEMBER_IDENTITY) -> str:
    """The seed file's path under the identity's entity for its scope."""
    return build_path(seed.scope, identity.entity_id(seed.scope), seed.area, seed.name)


def seed_reference_memory(
    client: TransportClient, identity: Identity = MEMBER_IDENTITY
) -> dict[str, MemoryFile]:
    """Write every seed file through the client, as a seeding job would, system/ included.

    Returns the written files by path.
    """
    written: dict[str, MemoryFile] = {}
    for seed in REFERENCE_SEED_FILES:
        path = seed_path(seed, identity)
        metadata = FileMetadata(
            description=seed.description,
            aliases=seed.aliases,
            sources=frozenset(),
            last_updated=REFERENCE_CLOCK_START,
        )
        written[path] = client.write_file(path, seed.content, metadata, None, source=SEED_SOURCE)
    return written


def bind_reference_tools(
    client: TransportClient, identity: Identity = MEMBER_IDENTITY
) -> MemoryTools:
    """Tools for the identity under the reference policy, writing as the reference agent."""
    return bind_tools(
        client,
        SandboxResolver(identity),
        object(),
        REFERENCE_POLICY,
        source=AGENT_SOURCE,
        product=REFERENCE_PRODUCT,
    )
