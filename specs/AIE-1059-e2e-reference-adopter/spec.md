# Feature Specification: End-to-end test against the reference adopter configuration

**Linear issue**: AIE-1059 — End-to-end integration test against reference adopter config

**Feature Branch**: `AIE-1059-e2e-reference-adopter`

**Created**: 2026-10-08

**Status**: Draft

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
seed files, so the later eval harness (AIE-1170) can reuse one definition.

No `src/` change is expected. The issue adds no public API.

## Section 9, as fixture data

| Section 9 item | Fixture |
| -------------- | ------- |
| Scopes: organization, project, user | scope names `organization`, `project`, `user` |
| Organization writes restricted to admin or owner | `ScopePolicy({"organization": {"admin", "owner"}})` |
| Project writes open to any member; user scope private | `project` and `user` absent from the policy |
| Scope priority: user, project, organization | `MemoryStore(scope_priority=("user", "project", "organization"))` |
| Seed areas | user: identity, preferences, workflows, people. project: taxonomy, metrics, entities, conventions, glossary. organization: business-context, vocabulary. Plus `system` in every scope |
| Systems of record | the existing `systems_of_record` slot text, plus a curated `system/` file per scope that points at the canonical objects |
| Scope guidance, scope test, shared vs. private, ask-first | the existing `scope_guidance` slot text (prompt behavior; evaluated, not unit-tested, per Section 10.3) |

## Acceptance criteria

Notation. `M` is the member identity: `user` -> `u-ada` (role `owner`),
`project` -> `p-checkout` (role `member`), `organization` -> `o-acme`
(role `member`). `A` is the admin identity: `user` -> `u-grace` (role
`owner`), `project` -> `p-checkout` (role `member`), `organization` ->
`o-acme` (role `admin`). "Seeded store" means a reference store into which
the seed files were written through the transport client directly, as a
seeding job would. "Rendered" means the dict returned by `render_result` or
`render_error`, which must also survive `json.loads(json.dumps(x)) == x`.

### US1 — The reference adopter configuration

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1.1 | the fixture module | its scopes are read | they are exactly `user`, `project`, `organization` |
| 1.2 | the fixture policy | `is_write_restricted` / `permitted_roles` is asked per scope | `organization` is restricted to exactly `{"admin", "owner"}`; `project` and `user` are unrestricted |
| 1.3 | the fixture store factory | a store is built | its `scope_priority` is `("user", "project", "organization")` |
| 1.4 | the fixture seed areas | they are read per scope | they match the Section 9 table above, each a valid lowercase area slug, and none is `system` |
| 1.5 | the `seed_areas` prompt slot | compared with the fixture seed areas | every seed area name and every scope name appears in the slot text, and the text names the `system/` area |
| 1.6 | the `scope_guidance` slot | compared with the fixture scopes | it names every scope, and names `organization` alongside both `admin` and `owner` |
| 1.7 | the seed files | they are read | there is exactly one `system/` file in every scope, and at least one non-system file in a seed area of every scope; every seed file's area is `system` or a seed area of its scope |
| 1.8 | `SandboxResolver(M)` and `SandboxResolver(A)` with the fixture policy | the `wenchang.testing.ResolverConformance` suite runs against each | every case passes (Section 10.1: roles are ones the policy references or that need none) |

### US2 — Session bootstrap via `get_memory_index`

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 2.1 | a seeded store and tools bound to `M` | `get_memory_index()` is called with no arguments | rendered `entries` hold every seed file under `M`'s three entities, each with `path`, `scope`, `area`, `name`, `version`, `description`, `aliases`, `sources`, `last_updated`; rendered `capped` is `[]` |
| 2.2 | as 2.1 | the rendered entry order is read | all `system` entries come first; then all `user`, then all `project`, then all `organization` entries |
| 2.3 | as 2.1, plus a file seeded under another user's entity (`user/u-grace/...`) | `get_memory_index()` is called | that file is absent: the scope map comes from the bound identity |
| 2.4 | as 2.1 | each rendered entry's `sources` is read | it is `["seed-job"]`, the seeding source |

### US3 — Read and write across the scope hierarchy

Each row runs once per scope, as the identity permitted to write it: `M`
for `user` and `project`, `A` for `organization`. The area is a seed area of
that scope.

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 3.1 | a seeded store | `read_file(scope, "system", name)` on that scope's curated file | rendered `content` and `description` equal the seeded ones; `area` is `"system"` |
| 3.2 | as 3.1 | `write_file(scope, area, name, content, description, aliases, None)` creates a new file | rendered `path` is `scope/<entity>/area/name.md` with the identity's entity; `sources` is `["reference-agent"]`; `aliases` and `description` are those given |
| 3.3 | the file from 3.2 | `read_file` | rendered `content`, `description`, `aliases`, `version` equal 3.2's |
| 3.4 | the file from 3.3 | `append_line(..., "- [observed] ...", version, aliases=[new], description=new_desc)` | rendered `content` is the old content plus the line and `"\n"`; `aliases` is the old aliases then the new one; `description` is `new_desc`; `version` differs from 3.3's |
| 3.5 | the file from 3.4 | `replace_fact(..., old_fact_text, new_fact_text, version)` quoting one fact | rendered `content` differs from 3.4's only in that span; the other lines are byte-identical |
| 3.6 | the file from 3.5 | `delete_file(..., version)` | the rendered result is `{"ok": true}` |
| 3.7 | the file from 3.6 | `read_file` | it raises `NotFoundError`; rendered `category` is `"recoverable"` and `reason` is `"file_absent"` |

### US4 — Index reflects the session

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 4.1 | a seeded store; `M` creates one file in `user` and one in `project`; `A` creates one in `organization`; `M` deletes the seeded `user` preferences file | `get_memory_index()` for `M` | rendered entries include the three created files and omit the deleted one; within the `user`, `project`, and `organization` tiers the newly written file precedes the older seed file (recency) |
| 4.2 | the store after 4.1 | `get_memory_index()` for `A` | rendered entries include the `project` and `organization` files `M` and `A` wrote, and no file under `user/u-ada/`: shared scopes are shared, the user scope is private |

### US5 — Curated `system/` is read-only at the tool layer only

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 5.1 | a seeded store, tools bound to `A` (who may write every scope) | each of `write_file`, `append_line`, `replace_fact`, `delete_file` targets the `system` area of each scope | each raises `RestrictedScopeError`; rendered `category` is `"permanent"`, `reason` is `"system_read_only"`, `path` is the target path |
| 5.2 | as 5.1 | the store is read after all 5.1 calls | every `system/` file is unchanged (content and version) and no new file exists |
| 5.3 | the client beneath the tools | `client.write_file` on a `system/` path (the seeding path) | it succeeds; this is how the fixture seeds curated content (ADR 0019/0021) |

### US6 — Organization write restriction (role-gated)

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 6.1 | a seeded store, tools bound to `M` (`organization` role `member`) | each of `write_file`, `append_line`, `replace_fact`, `delete_file` targets an `organization` seed area (the mutating calls on the seeded organization file) | each raises `RestrictedScopeError`; rendered `category` is `"permanent"`, `reason` is `"role_required"`, `scope` is `"organization"`, `required_roles` is `["admin", "owner"]` |
| 6.2 | as 6.1 | `read_file` on the seeded organization file | it succeeds: the restriction is on writes only |
| 6.3 | as 6.1 | the store is read after the 6.1 calls | the organization file is unchanged |

### US7 — Shared-scope version conflict is routine

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 7.1 | a seeded store; `M` and `A` both read the seeded `project` file at version `v0`; `A` appends a line | `M` appends a different line with `v0` | it raises `VersionConflictError`; rendered `category` is `"recoverable"`, `content` is the file content including `A`'s line, `version` is the current version |
| 7.2 | as 7.1 | `M` retries with the rendered `version` | it succeeds; rendered `content` holds both lines exactly once, `A`'s first |

### US8 — Index byte budget under the reference priority

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 8.1 | a seeded reference store, plus two more `project/metrics` files written by `M`, whose `index_max_bytes` admits the `system/` entries and the `user` entries but not all `project` entries | `get_memory_index()` for `M` | rendered entries are every `system` entry then every `user` entry, then whatever `project` entries fit; no `organization` entry; rendered `capped` lists each omitted area prefix with `scope`, `area`, and `omitted` count, and the counts sum to the number of omitted files |
| 8.2 | the result of 8.1 | `list_prefix(scope, area)` for each capped row | the rendered entries of the pages cover every omitted file of that area |

### US9 — Runs under `make check`

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 9.1 | the new test modules | `make check` runs | they run (marked `unit`, not `integration`), using `InMemoryStorage` and `InProcessClient`; no test double replaces the transport |
| 9.2 | the existing prompt tests that imported `prompts_reference_adopter` | they import from `reference_adopter` | they pass unchanged in substance |

## Assumptions

- **Fixture stays tests-only.** Section 9 says the reference adopter is
  "illustrative only; not part of the library", so it does not go into
  `wenchang.testing`. AIE-1170 imports it from `tests/` (or moves it then,
  with its own ADR, if it needs it packaged).
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
- **Deterministic recency.** The fixture store uses a clock that advances
  one second per call, so `last_updated` ordering is deterministic.
- **Seeding job identity.** Seed files are stamped with source
  `"seed-job"`, and tool writes with `"reference-agent"`.
