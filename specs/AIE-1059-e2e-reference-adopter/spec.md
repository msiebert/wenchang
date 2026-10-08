# Feature Specification: End-to-end test against the reference adopter configuration

**Linear issue**: AIE-1059 — End-to-end integration test against reference adopter config

**Feature Branch**: `AIE-1059-e2e-reference-adopter`

**Created**: 2026-10-08

**Status**: Draft, revised after adversarial spec review round 1

**Input**: Linear AIE-1059 and Notion spec Section 9 (reference adopter
configuration), with Sections 3, 5, 6, and 8.2 for the behavior exercised.

## Summary

Assemble the Section 9 reference adopter as one tests-only fixture module,
`tests/reference_adopter.py`, and drive a full agent session lifecycle
against it through the tool layer (`bind_tools` -> `MemoryTools`) over
`InProcessClient(MemoryStore(InMemoryStorage()))`. Every tool output the
lifecycle checks is asserted through `render_result` / `render_error`, the
JSON-safe form a host shows the agent.

The fixture is the single reference adopter configuration in the repo. It
absorbs `tests/prompts_reference_adopter.py` (prompt slots and scope
priority) and adds the scope set, write policy, identities, seed areas, and
seed files. It depends only on public `wenchang` imports.

No `src/` change is expected. The issue adds no public API.

The existing tool-layer end-to-end test uses a client double whose
`get_memory_index` returns an empty `MemoryIndex()`, so no tool-layer test
has yet asserted a populated index. US2, US4, and US8 are the first.

## Section 9, as fixture data

| Section 9 item | Fixture |
| -------------- | ------- |
| Scopes: organization, project, user | scope names `organization`, `project`, `user` |
| Organization writes restricted to admin or owner | `ScopePolicy({"organization": {"admin", "owner"}})` |
| Project writes open to any member; user scope private | `project` and `user` absent from the policy |
| User scope follows the person across organizations | identity `T`: the same user entity in a different organization and project (US4.3) |
| Organization readable by members with access to only some projects | identity `P`: the same organization, a different project (US4.4) |
| Scope priority: user, project, organization | `MemoryStore(scope_priority=("user", "project", "organization"))` |
| Seed areas | user: identity, preferences, workflows, people. project: taxonomy, metrics, entities, conventions, glossary. organization: business-context, vocabulary. Plus `system` in every scope |
| Systems of record | the existing `systems_of_record` slot text; the curated `project/system/event-catalog` file says event definitions live in the event catalog; the `project/entities/checkout-dashboard` file annotates a dashboard by name and ID without copying it |
| Scope guidance, scope test, shared vs. private, ask-first | the existing `scope_guidance` slot text (prompt behavior; evaluated, not unit-tested, per Section 10.3) |

## Acceptance criteria

Notation. Identities, each as `scope -> entity (role)`:

- `M` (member): `user -> u-ada (owner)`, `project -> p-checkout (member)`, `organization -> o-acme (member)`.
- `A` (admin): `user -> u-grace (owner)`, `project -> p-checkout (member)`, `organization -> o-acme (admin)`.
- `T` (M in another organization): `user -> u-ada (owner)`, `project -> p-other (member)`, `organization -> o-globex (member)`.
- `P` (partial-project member): `user -> u-lin (owner)`, `project -> p-billing (member)`, `organization -> o-acme (member)`.

"Seeded store" means a reference store into which the fixture's seed files
were written, under `M`'s entities, through the transport client directly,
as a seeding job would. "Rendered" means the dict returned by
`render_result` or `render_error`, which must also survive
`json.loads(json.dumps(x)) == x`. "Index entry keys" means exactly
`{path, scope, area, name, version, description, aliases, sources,
last_updated}`.

### US1 — The reference adopter configuration

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1.1 | the fixture module | its scopes are read | they are exactly `user`, `project`, `organization` |
| 1.2 | the fixture policy | `is_write_restricted` / `permitted_roles` is asked per scope | `organization` is restricted to exactly `{"admin", "owner"}`; `project` and `user` are unrestricted |
| 1.3 | the fixture store factory | a store is built | its `scope_priority` is `("user", "project", "organization")` |
| 1.4 | the fixture seed areas by scope | they are read per scope | they match the Section 9 table above; each passes `wenchang.paths.is_valid_segment` and the test-local slug pattern `[a-z0-9][a-z0-9_-]*`; none is `system` |
| 1.5 | the `seed_areas` prompt slot text | compared with the fixture seed areas | every seed area name and every scope name appears in the slot text, and the text names the `system/` area |
| 1.6 | the `scope_guidance` slot text | compared with the fixture scopes | it names every scope, and its `- organization` bullet contains both `admin` and `owner` |
| 1.7 | the seed files | they are read | there is exactly one `system/` file in every scope and at least one non-system file in a seed area of every scope; every seed file's area is `system` or a seed area of its scope; every seed file's content ends with `"\n"` |
| 1.8 | `SandboxResolver(X)` for each of `M`, `A`, `T`, `P`, with the fixture policy | the `wenchang.testing.ResolverConformance` suite runs against each | every case passes |
| 1.9 | `ticking_clock` | called with a naive `start`, or with a `step` that is not a positive whole number of seconds (`timedelta(milliseconds=1500)`, `timedelta(0)`, `timedelta(seconds=-1)`) | it raises `ValueError` |

### US2 — Session bootstrap via `get_memory_index`

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 2.1 | a seeded store and tools bound to `M` | `get_memory_index()` is called with no arguments | rendered `entries` hold exactly the seed files' paths; each entry's key set is exactly the index entry keys (no `content`); rendered `capped` is `[]` |
| 2.2 | as 2.1 | the rendered entry order is read | all `system` entries come first; then all `user`, then all `project`, then all `organization` entries |
| 2.3 | as 2.1, plus a file seeded under another user's entity (`user/u-grace/preferences/...`) | `get_memory_index()` is called | that file is absent: the scope map comes from the bound identity |
| 2.4 | as 2.1 | each rendered entry's `sources` is read | it is `["seed-job"]`, the seeding source |

### US3 — Read and write across the scope hierarchy

Each row runs once per scope, as the identity permitted to write it: `M`
for `user` and `project`, `A` for `organization`. The area is
`preferences`, `metrics`, and `vocabulary` respectively; the file name is
`reference-e2e`, which no seed file uses. Content written in 3.2 ends with
`"\n"`.

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 3.1 | a seeded store | `read_file(scope, "system", name)` on that scope's curated file | rendered `content` and `description` equal the seeded ones; `area` is `"system"` |
| 3.2 | as 3.1 | `write_file(scope, area, "reference-e2e", content, description, aliases, None)` | rendered `path` is `scope/<entity>/area/reference-e2e.md` with the identity's entity; `sources` is `["reference-agent"]`; `aliases` and `description` are those given |
| 3.3 | the file from 3.2 | `read_file` | rendered `content`, `description`, `aliases`, `version` equal 3.2's |
| 3.4 | the file from 3.3 | `append_line(..., "- [observed] ...", version, aliases=[new], description=new_desc)` | rendered `content` is 3.3's content plus the line and `"\n"`; `aliases` is the old aliases then the new one; `description` is `new_desc`; `version` differs from 3.3's |
| 3.5 | the file from 3.4 | `replace_fact(..., old_fact_text, new_fact_text, version)` quoting one fact | rendered `content` equals 3.4's with that one span replaced; the other lines are byte-identical |
| 3.6 | the file from 3.5 | `delete_file(..., version)` | the rendered result is `{"ok": true}` |
| 3.7 | the file from 3.6 | `read_file` | it raises `NotFoundError`; rendered `category` is `"recoverable"` and `reason` is `"file_absent"` |

### US4 — Index reflects the session and the Section 9 scope properties

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 4.1 | a seeded store; `M` creates `user/preferences/session-note` and `project/metrics/session-note`; `A` creates `organization/vocabulary/session-note`; `M` deletes the seeded `user/preferences/charts` | `get_memory_index()` for `M` | rendered entries include the three created files and omit the deleted one; within each of the `user`, `project`, and `organization` tiers the `session-note` entry precedes every seed entry of that tier (recency) |
| 4.2 | the store after 4.1 | `get_memory_index()` for `A` | rendered entries include the `project` and `organization` files `M` and `A` wrote and the seeded `project` and `organization` files, and no path under `user/u-ada/` |
| 4.3 | a seeded store, plus one `project` and one `organization` file seeded under `T`'s `p-other` and `o-globex` entities | `get_memory_index()` for `T` | rendered entries are exactly the seeded `user/u-ada/...` files plus the two `T` files; no path under `project/p-checkout/` or `organization/o-acme/`. User scope follows the person across organizations |
| 4.4 | a seeded store, plus one `project` file seeded under `P`'s `p-billing` entity | `get_memory_index()` for `P` | rendered entries are exactly the seeded `organization/o-acme/...` files plus the `p-billing` file; no path under `project/p-checkout/` or `user/u-ada/`. A member with access to other projects reads the organization scope |

### US5 — Curated `system/` is read-only at the tool layer only

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 5.1 | a seeded store; tools bound to `M` for `user`, to `A` for `project` and `organization` | each of `write_file`, `append_line`, `replace_fact`, `delete_file` targets that scope's seeded `system/` file, mutating calls passing the file's real current version | each raises `RestrictedScopeError`; rendered `category` is `"permanent"`, `reason` is `"system_read_only"`, `path` is the target path |
| 5.2 | a seeded store, tools bound to `M` (`organization` role `member`) | each of the four mutating tools targets `organization/o-acme/system/fiscal-calendar` | each raises with rendered `reason` `"system_read_only"`, not `"role_required"`: the `system/` check precedes the role check |
| 5.3 | the end of every 5.1 and 5.2 case | every `system/` file is read through the client and the store's paths are listed | each is unchanged (content and version) and no new file exists |
| 5.4 | a seeded store, tools bound to `A` | a tool write to `project/system/event-catalog` is rejected, then `client.write_file` on `project/p-checkout/system/event-catalog.md` with its current version (its own test) | the tool call raises `system_read_only`; the client write succeeds and the returned version differs from the prior one: the transport beneath the tools accepts `system/` writes (ADR 0019/0021) |

### US6 — Organization write restriction (role-gated)

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 6.1 | a seeded store, tools bound to `M` (`organization` role `member`) | each of `write_file`, `append_line`, `replace_fact`, `delete_file` targets the seeded `organization/vocabulary/terms` file with its real version | each raises `RestrictedScopeError`; rendered `category` is `"permanent"`, `reason` is `"role_required"`, `scope` is `"organization"`, `required_roles` is `["admin", "owner"]` |
| 6.2 | as 6.1 | `read_file` on that file | it succeeds: the restriction is on writes only |
| 6.3 | the end of every 6.1 case | the organization file is read through the client | it is unchanged (content and version) |

### US7 — Shared-scope version conflict is routine

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 7.1 | a seeded store; `M` and `A` both read `project/metrics/activation` at version `v0`; `A` appends line `LA` | `M` appends a different line `LM` with `v0` | it raises `VersionConflictError`; rendered `category` is `"recoverable"`, `path` is `project/p-checkout/metrics/activation.md`, `content` is exactly the seed content + `LA` + `"\n"`, `version` is the current version |
| 7.2 | as 7.1 | `M` retries with the rendered `version` | it succeeds; rendered `content` is exactly the seed content + `LA` + `"\n"` + `LM` + `"\n"` |

### US8 — Index byte budget under the reference priority

Two stores are built with `reference_store`, each on a fresh
`ticking_clock()` with a whole-second step, and each runs the same
sequence: seed, then `M` writes `project/metrics/budget-a`, then
`project/metrics/budget-b`. `budget-a` has a long description, so it is the
largest entry after `budget-b`. The first store is uncapped (default
`index_max_bytes`). Its index gives entry sizes via
`wenchang.core.index_entry_bytes`. The second store's `index_max_bytes` is
the sum of the sizes of every `system` entry, every `user` entry, and the
`budget-b` entry, plus a slack equal to the size of the smallest entry after
`budget-b`. The next entry, `budget-a`, is larger than the slack and does
not fit; an index that skipped it and kept filling would admit the smallest
later entry and break the prefix property. The capped store also uses
`list_page_size=1`, so 8.3 pages more than once. Byte sizes match across
the two stores because `InMemoryStorage` version tokens are a counter and
both stores run the same sequence on the same clock start and step.

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 8.1 | the capped store | `get_memory_index()` for `M` | rendered entries are a prefix of the uncapped store's rendered entries: every `system` entry, then every `user` entry, then exactly one `project` entry, `budget-b`; no non-system `organization` entry |
| 8.2 | as 8.1 | rendered `capped` is read | it is exactly, in this order: `{prefix: "organization/o-acme/vocabulary/", scope: "organization", area: "vocabulary", omitted: 1}`, `{prefix: "project/p-checkout/entities/", scope: "project", area: "entities", omitted: 1}`, `{prefix: "project/p-checkout/metrics/", scope: "project", area: "metrics", omitted: 2}` |
| 8.3 | the result of 8.2 | `list_prefix(scope, area)` for each capped row, following `next_cursor` | the rendered entries cover every file of that area omitted from 8.1; at least one row takes more than one page |

### US9 — Runs under `make check`

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 9.1 | the new test modules | `make check` runs | they run (marked `unit`, not `integration`), using `InMemoryStorage` and `InProcessClient`; no test double replaces the transport |
| 9.2 | the existing prompt tests that imported `prompts_reference_adopter` | they import from `reference_adopter` | they pass with no assertion changed |

## Assumptions

- **Fixture stays tests-only.** Section 9 says the reference adopter is
  "illustrative only; not part of the library", so it does not go into
  `wenchang.testing`. AIE-1170 relocates the module to a dev-only
  importable location outside the wheel (e.g. a top-level `reference/`
  package or an `evals/` package), wired in via `[tool.pytest.ini_options]
  pythonpath` and pyright `extraPaths`; not public API, so no ADR. Keeping
  the module dependent only on public `wenchang` imports makes that move
  mechanical.
- **AIE-1151 optional arguments are covered** (3.4) because Section 8.1
  alias upkeep says every write adds lookup names; one call with both
  `aliases` and `description` per scope is enough here, as AIE-1151 owns
  their edge cases.
- **Index byte budget is covered** (US8) because Section 9 defines the
  scope priority order specifically for the capped index.
- **Prompt-layer behavior** in Section 9 (ask before shared writes, surface
  contradictions, the scope test, write narrow) is agent judgment and is
  not unit-tested (Section 10.3). The fixture carries the text for the
  eval harness.
- **Oversize writes, resolver failure, and transient errors** are covered by
  existing tool and conformance tests and are not part of the Section 9
  lifecycle.
- **Deterministic recency.** The fixture store uses a clock that starts at
  an aware UTC datetime and advances a whole second per call, so
  `last_updated` ordering and rendered sizes are deterministic.
- **Seeding job identity.** Seed files are stamped with source
  `"seed-job"`, and tool writes with `"reference-agent"`.
- **Four identities.** Section 9's two cross-scope properties need two
  identities beyond `M` and `A`: `T` (same user, other organization) and
  `P` (same organization, other project).
