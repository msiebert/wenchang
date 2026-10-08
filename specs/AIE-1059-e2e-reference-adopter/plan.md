# Implementation Plan: End-to-end test against the reference adopter configuration

**Linear issue**: AIE-1059 | **Spec**: [spec.md](spec.md)

## Shape of the change

Tests and docs only. No `src/` change, no public API change, no storage
semantics change, so no ADR is required (AGENTS.md). If building surfaces a
library bug, it is reported at the build checkpoint rather than fixed
silently here.

## Files

| File | Change |
| ---- | ------ |
| `tests/reference_adopter.py` | New. The single reference adopter fixture: everything in `tests/prompts_reference_adopter.py` (moved verbatim) plus the interface below. `git mv` from the old module so history follows. |
| `tests/prompts_reference_adopter.py` | Removed (moved). |
| `tests/test_prompts_assembly.py`, `tests/test_prompts_write_mechanics.py` | Import from `reference_adopter` instead. No other change. |
| `tests/test_reference_adopter_config.py` | New. US1 (config shape, slot consistency, resolver conformance for both identities). |
| `tests/test_reference_adopter_end_to_end.py` | New. US2 through US8. |
| `README.md` | Link to `tests/reference_adopter.py` instead of the old module. |
| `docs/adr/0025-*.md`, `docs/adr/0026-*.md` | Path-only fix: the old module name becomes `tests/reference_adopter.py` so links resolve. No decision text changes. Closed specs under `specs/AIE-10xx/` keep the old name as history. |
| `ARCHITECTURE.md` | One line where tests are described (or under the tools module entry) naming the reference adopter fixture and the end-to-end test. No ADR. |
| `specs/AIE-1059-e2e-reference-adopter/review-pr.md` | At build checkpoint. |

## Fixture interface: `tests/reference_adopter.py`

Everything is module-level and `Final`. Imports only public `wenchang`
modules.

```python
# Moved verbatim from prompts_reference_adopter.py
REFERENCE_PURPOSE: Final[str]
REFERENCE_SCOPE_GUIDANCE: Final[str]
REFERENCE_SEED_AREAS: Final[str]
REFERENCE_SYSTEMS_OF_RECORD: Final[str]
REFERENCE_SLOTS: Final[PromptSlots]
REFERENCE_SCOPE_PRIORITY: Final[tuple[str, ...]]  # ("user", "project", "organization")

# Scopes
USER: Final = "user"
PROJECT: Final = "project"
ORGANIZATION: Final = "organization"
REFERENCE_SCOPES: Final[tuple[str, ...]]  # (USER, PROJECT, ORGANIZATION)

# Seed areas per scope; excludes "system", which every scope also has.
REFERENCE_SEED_AREA_NAMES: Final[Mapping[str, tuple[str, ...]]]  # MappingProxyType
#   user:         ("identity", "preferences", "workflows", "people")
#   project:      ("taxonomy", "metrics", "entities", "conventions", "glossary")
#   organization: ("business-context", "vocabulary")

# Write policy
ORGANIZATION_WRITE_ROLES: Final[frozenset[str]]  # {"admin", "owner"}
REFERENCE_POLICY: Final[ScopePolicy]  # ScopePolicy({ORGANIZATION: ORGANIZATION_WRITE_ROLES})

# Entities and identities
ORGANIZATION_ID: Final = "o-acme"
PROJECT_ID: Final = "p-checkout"
MEMBER_USER_ID: Final = "u-ada"
ADMIN_USER_ID: Final = "u-grace"
MEMBER_IDENTITY: Final[
    Identity
]  # user u-ada/owner, project p-checkout/member, organization o-acme/member
ADMIN_IDENTITY: Final[
    Identity
]  # user u-grace/owner, project p-checkout/member, organization o-acme/admin
REFERENCE_ROLES: Final[frozenset[str]]  # {"owner", "member", "admin"}

# Sources and product
SEED_SOURCE: Final = "seed-job"
AGENT_SOURCE: Final = "reference-agent"
REFERENCE_PRODUCT: Final = "Mixpanel"  # matches REFERENCE_PURPOSE


@dataclass(frozen=True, slots=True)
class SeedFile:
    scope: str
    area: str
    name: str
    content: str  # fact lines, each "- [label] text\n"
    description: str
    aliases: tuple[str, ...]


# Paths are built against MEMBER_IDENTITY's entities.
REFERENCE_SEED_FILES: Final[tuple[SeedFile, ...]]
#   user/system/profile                 [system] curated profile line
#   project/system/event-catalog        [system] systems-of-record pointer: event definitions live in the catalog
#   organization/system/fiscal-calendar [system] curated org fact
#   user/preferences/charts             [stated] prefers dark-background charts
#   project/metrics/activation          [stated] activation means the second purchase
#   organization/vocabulary/terms       [stated] "ARR" means annual recurring revenue


def ticking_clock(
    start: datetime = ..., step: timedelta = timedelta(seconds=1)
) -> Callable[[], datetime]:
    """A clock returning start, start+step, start+2*step, ... on successive calls."""


def reference_store(
    *, index_max_bytes: int = DEFAULT_INDEX_MAX_BYTES, clock: Callable[[], datetime] | None = None
) -> MemoryStore:
    """MemoryStore(InMemoryStorage(), scope_priority=REFERENCE_SCOPE_PRIORITY, ...);
    clock defaults to a fresh ticking_clock()."""


def seed_path(seed: SeedFile, identity: Identity = MEMBER_IDENTITY) -> str:
    """build_path(seed.scope, identity entity for seed.scope, seed.area, seed.name)."""


def seed_reference_memory(
    client: TransportClient, identity: Identity = MEMBER_IDENTITY
) -> dict[str, MemoryFile]:
    """Write every REFERENCE_SEED_FILES entry through client.write_file directly
    (expected_version=None, source=SEED_SOURCE), in tuple order, as a seeding
    job would; system/ paths included. Returns the written files by path."""


def bind_reference_tools(
    client: TransportClient, identity: Identity = MEMBER_IDENTITY
) -> MemoryTools:
    """bind_tools(client, SandboxResolver(identity), object(), REFERENCE_POLICY,
    source=AGENT_SOURCE, product=REFERENCE_PRODUCT)."""
```

`DEFAULT_INDEX_MAX_BYTES` comes from `wenchang.core`. Tests compute the US8
cap from `wenchang.core.index_entry_bytes` over the index the uncapped store
returns, so the cap does not depend on literal byte counts.

## Test modules

`tests/test_reference_adopter_config.py` (`pytestmark = pytest.mark.unit`):

- US1.1 through US1.7 as plain tests on the fixture constants.
- US1.8 as two `ResolverConformance[object]` subclasses
  (`TestReferenceMemberResolver`, `TestReferenceAdminResolver`), following
  `tests/test_resolver_conformance_reference.py`: `resolver` is
  `SandboxResolver(identity)`, `invalid_credentials` skips (sandbox accepts
  everything), `policy` is `REFERENCE_POLICY`, `expected_scopes` is
  `frozenset(REFERENCE_SCOPES)`, `known_roles` is `REFERENCE_ROLES`.

`tests/test_reference_adopter_end_to_end.py` (`pytestmark = pytest.mark.unit`):

- Each test builds `client = InProcessClient(reference_store())`, seeds it,
  and binds tools with `bind_reference_tools`.
- A `_rendered(value)` helper returns `render_result(value)` after asserting
  JSON round-trip; `_rendered_error(exc)` likewise for `render_error`.
  Every lifecycle assertion reads the rendered dict, not the dataclass.
- US3 is one test parametrized over `(scope, identity, area)`:
  `(USER, MEMBER, "preferences")`, `(PROJECT, MEMBER, "metrics")`,
  `(ORGANIZATION, ADMIN, "vocabulary")`, running 3.1 through 3.7 in order.
- US5.1 and US6.1 are parametrized over the four mutating tools (and, for
  US5.1, the three scopes). Mutating calls on an existing file pass that
  file's real version, so the rejection is the restriction, not a missing
  file or bad token.
- Docstrings cite `AIE-1059` and the criterion numbers.

## Design decisions

| Decision | Alternatives rejected | Why |
| -------- | --------------------- | --- |
| Fixture in `tests/reference_adopter.py` | `wenchang.testing.reference_adopter` (public) | Section 9 calls the reference adopter illustrative, not part of the library; public API would need an ADR and a support commitment for example data. AIE-1170 can import it from `tests/` or promote it later under its own ADR. |
| Fold `prompts_reference_adopter.py` into the new module | Keep both; new module imports from old | One configuration, one module, so prompt slots, seed areas, and policy cannot drift apart. Two test imports change; no assertion changes. |
| `InProcessClient` over a real `MemoryStore` | The tests-only `_StoreClient` in `test_tools_end_to_end.py` | The issue asks for the path an adopter uses; the existing double stubs `get_memory_index`. |
| Seed through `client.write_file` | Seed through `MemoryStore` directly; seed via tools | Seeding through the transport shows the layer beneath the tools accepts `system/` writes (5.3). Tools would reject them. |
| Assert through `render_result` / `render_error` | Assert on dataclasses | The issue requires the host-visible JSON-safe contract. |
| Ticking clock | Fixed clock | Recency ordering in 2.2, 4.1, and 8.1 needs distinct `last_updated` values. |
| Two identities (member, admin) | One identity per scope | Section 9's role gate is visible only with a member and an admin on the same organization and project; distinct user entities show user-scope privacy (2.3, 4.2). |

## ARCHITECTURE.md and ADRs

- No ADR: no public API, module boundary, or storage semantics change.
- ARCHITECTURE.md: one sentence naming `tests/reference_adopter.py` as the
  Section 9 reference adopter and `tests/test_reference_adopter_end_to_end.py`
  as the tool-layer lifecycle test over it.
- README: update the reference adopter link.
