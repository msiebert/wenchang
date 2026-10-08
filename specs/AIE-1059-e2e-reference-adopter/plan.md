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
| `tests/test_reference_adopter_config.py` | New. US1 (config shape, slot consistency, resolver conformance for all four identities). |
| `tests/test_reference_adopter_end_to_end.py` | New. US2 through US8. |
| `README.md` | Link to `tests/reference_adopter.py` instead of the old module. |
| `docs/adr/0025-prompt-layer-sections-and-slots.md` | Decision 10: update the sentence, not only the path. It becomes: `tests/reference_adopter.py` holds Section 9 as the prompt slots, scope priority, write policy, identities, seed areas, and seed files; not in `src/` because Section 9 says it is not part of the library; it is the worked example for adopters. |
| `docs/adr/0026-product-identity.md` | Path-only fix to `tests/reference_adopter.py`. |
| `ARCHITECTURE.md` | One sentence naming `tests/reference_adopter.py` as the Section 9 reference adopter and `tests/test_reference_adopter_end_to_end.py` as the tool-layer lifecycle test over it. |
| `specs/AIE-1059-e2e-reference-adopter/review-pr.md` | At build checkpoint. |

Closed specs under `specs/AIE-10xx/` and `specs/AIE-11xx/` keep the old
module name as history.

## Fixture interface: `tests/reference_adopter.py`

Everything is module-level and `Final`. Imports only public `wenchang`
modules, so a later move out of `tests/` is mechanical.

```python
# Moved verbatim from prompts_reference_adopter.py
REFERENCE_PURPOSE: Final[str]
REFERENCE_SCOPE_GUIDANCE: Final[str]
REFERENCE_SEED_AREAS: Final[str]  # the seed_areas slot text
REFERENCE_SYSTEMS_OF_RECORD: Final[str]
REFERENCE_SLOTS: Final[PromptSlots]
REFERENCE_SCOPE_PRIORITY: Final[tuple[str, ...]]  # ("user", "project", "organization")

# Scopes
USER: Final = "user"
PROJECT: Final = "project"
ORGANIZATION: Final = "organization"
REFERENCE_SCOPES: Final[tuple[str, ...]]  # (USER, PROJECT, ORGANIZATION)

# Seed area names per scope (MappingProxyType); excludes "system", which every scope also has.
SEED_AREAS_BY_SCOPE: Final[Mapping[str, tuple[str, ...]]]
#   user:         ("identity", "preferences", "workflows", "people")
#   project:      ("taxonomy", "metrics", "entities", "conventions", "glossary")
#   organization: ("business-context", "vocabulary")

# Write policy
ORGANIZATION_WRITE_ROLES: Final[frozenset[str]]  # {"admin", "owner"}
REFERENCE_POLICY: Final[ScopePolicy]  # ScopePolicy({ORGANIZATION: ORGANIZATION_WRITE_ROLES})

# Entities
ORGANIZATION_ID: Final = "o-acme"
PROJECT_ID: Final = "p-checkout"
MEMBER_USER_ID: Final = "u-ada"
ADMIN_USER_ID: Final = "u-grace"
OTHER_ORGANIZATION_ID: Final = "o-globex"
OTHER_PROJECT_ID: Final = "p-other"
PARTIAL_USER_ID: Final = "u-lin"
PARTIAL_PROJECT_ID: Final = "p-billing"

# Identities (spec notation in brackets)
# [M] user u-ada/owner, project p-checkout/member, organization o-acme/member
MEMBER_IDENTITY: Final[Identity]
# [A] user u-grace/owner, project p-checkout/member, organization o-acme/admin
ADMIN_IDENTITY: Final[Identity]
# [T] user u-ada/owner, project p-other/member, organization o-globex/member
TRAVELER_IDENTITY: Final[Identity]
# [P] user u-lin/owner, project p-billing/member, organization o-acme/member
PARTIAL_IDENTITY: Final[Identity]
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
    content: str  # fact lines, each "- [label] text\n"; always ends with "\n"
    description: str
    aliases: tuple[str, ...]


# Paths are built against MEMBER_IDENTITY's entities. Tuple order is write order.
REFERENCE_SEED_FILES: Final[tuple[SeedFile, ...]]
#   user/system/profile                  [system] curated profile line
#   project/system/event-catalog         [system] event definitions live in the product's event catalog
#   organization/system/fiscal-calendar  [system] curated org fact
#   user/preferences/charts              [stated] prefers dark-background charts
#   user/workflows/weekly-review         [observed] reviews the checkout funnel every Monday
#   project/metrics/activation           [stated] activation means the second purchase
#   project/entities/checkout-dashboard  [stated] dashboard "Checkout health" (ID 4521) is the team's
#                                        launch-review view; annotates, never copies its definition
#   organization/vocabulary/terms        [stated] "ARR" means annual recurring revenue

REFERENCE_CLOCK_START: Final = datetime(2026, 1, 1, tzinfo=UTC)


def ticking_clock(
    start: datetime = REFERENCE_CLOCK_START, step: timedelta = timedelta(seconds=1)
) -> Callable[[], datetime]:
    """A clock returning start, start+step, start+2*step, ... on successive calls.

    Raises ValueError if start is naive or step is not a positive whole number
    of seconds.
    """


def reference_store(
    *, index_max_bytes: int = DEFAULT_INDEX_MAX_BYTES, clock: Callable[[], datetime] | None = None
) -> MemoryStore:
    """MemoryStore(InMemoryStorage(), scope_priority=REFERENCE_SCOPE_PRIORITY, ...);
    clock defaults to a fresh ticking_clock()."""


def seed_path(seed: SeedFile, identity: Identity = MEMBER_IDENTITY) -> str:
    """build_path(seed.scope, identity's entity for seed.scope, seed.area, seed.name)."""


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

`DEFAULT_INDEX_MAX_BYTES` comes from `wenchang.core`. Extra files under
other entities (2.3, 4.3, 4.4) are written by the tests with
`client.write_file` and `wenchang.paths.build_path`, source `SEED_SOURCE`.

## US8 cap computation

`MemoryStore` takes `index_max_bytes` only at construction, so the test
builds two stores and replays one step function on each:

1. `uncapped = InProcessClient(reference_store())`; run the steps (seed,
   then `M` writes `project/metrics/budget-a`, then `budget-b`, both content
   ending in `"\n"`).
2. From `uncapped`'s `MemoryIndex`, sum `index_entry_bytes` over every
   `system` entry, every `user` entry, and the `budget-b` entry. Assert
   `budget-b` is the first `project` entry, so the cap admits exactly one.
3. `capped = InProcessClient(reference_store(index_max_bytes=cap))`; run the
   same steps.
4. Assert the capped rendered entries are a prefix of the uncapped rendered
   entries, then the 8.1 and 8.2 expectations.

Each `reference_store()` call gets a fresh whole-second `ticking_clock()`,
and `InMemoryStorage` version tokens are a counter, so the two runs produce
identical paths, versions, and timestamps, and therefore identical sizes.

## Test modules

`tests/test_reference_adopter_config.py` (`pytestmark = pytest.mark.unit`):

- US1.1 through US1.7 as plain tests on the fixture constants. 1.4 checks
  `wenchang.paths.is_valid_segment` and a test-local regex
  `[a-z0-9][a-z0-9_-]*` (the tools' own slug regex is private). 1.6 locates
  the line starting `- organization` in `REFERENCE_SCOPE_GUIDANCE` and its
  continuation lines up to the next bullet.
- US1.8 as four `ResolverConformance[object]` subclasses, one per identity,
  following `tests/test_resolver_conformance_reference.py`: `resolver` is
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
  `(ORGANIZATION, ADMIN, "vocabulary")`, running 3.1 through 3.7 in order on
  a file named `reference-e2e` whose content ends in `"\n"`.
- US5.1 is parametrized over the four mutating tools and the rows
  `(USER, MEMBER)`, `(PROJECT, ADMIN)`, `(ORGANIZATION, ADMIN)`; every
  target file exists under the bound identity's entity, and mutating calls
  pass its real version. US5.2 and US6.1 are parametrized over the four
  mutating tools bound to `M`, also with real versions. So each rejection
  comes from the restriction, never a missing file or bad token.
- Each parametrized case is independent: every 5.1 and 5.2 case ends with
  the 5.3 check (all `system/` files unchanged in content and version, no
  new path), and every 6.1 case ends with the 6.3 check (the organization
  file unchanged). 5.4 is its own test: seed, a rejected tool write to
  `project/system/event-catalog`, then `client.write_file` on that path,
  asserting the version changed.
- US1.9 lives in the config test module.
- Docstrings cite `AIE-1059` and the criterion numbers.

## Design decisions

| Decision | Alternatives rejected | Why |
| -------- | --------------------- | --- |
| Fixture in `tests/reference_adopter.py` | `wenchang.testing.reference_adopter` (public) | Section 9 calls the reference adopter illustrative, not part of the library; the wheel would ship example data as supported API, needing an ADR. `tests/` is not importable outside pytest, so AIE-1170 relocates the module to a dev-only package outside the wheel (pytest `pythonpath`, pyright `extraPaths`); that move is not public API and needs no ADR. |
| Fold `prompts_reference_adopter.py` into the new module | Keep both; new module imports from old | One configuration, one module, so prompt slots, seed areas, and policy cannot drift apart. Two test imports change; no assertion changes. |
| `InProcessClient` over a real `MemoryStore` | The tests-only `_StoreClient` in `test_tools_end_to_end.py` | The issue asks for the path an adopter uses. That double's `get_memory_index` returns an empty `MemoryIndex()`, so no tool-layer test has asserted a populated index; US2, US4, and US8 are the first. |
| Seed through `client.write_file` | Seed through `MemoryStore` directly; seed via tools | Seeding through the transport, and 5.4's write to a path the tools just rejected, show the layer beneath the tools accepts `system/` writes. Tools would reject them. |
| Assert through `render_result` / `render_error` | Assert on dataclasses | The issue requires the host-visible JSON-safe contract. |
| Whole-second ticking clock from an aware UTC start | Fixed clock; sub-second step | Recency ordering (2.2, 4.1, 8.1) needs distinct `last_updated`; whole seconds keep rendered sizes stable for US8; a naive start makes `FileMetadata` raise. |
| Four identities | Two | Role gate needs member and admin on one organization and project; Section 9's "follows the person across organizations" and "readable by members with only some projects" each need an identity that differs from `M` in exactly that way. |
| `SEED_AREAS_BY_SCOPE` name | `REFERENCE_SEED_AREA_NAMES` | Too close to the `REFERENCE_SEED_AREAS` slot text. |

## ARCHITECTURE.md and ADRs

- No new ADR: no public API, module boundary, or storage semantics change.
- ADR 0025 decision 10 sentence updated (see Files); ADR 0026 path fix.
- ARCHITECTURE.md: one sentence (see Files).
- README: update the reference adopter link.
