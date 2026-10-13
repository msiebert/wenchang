# Spec Review: AIE-1059 — End-to-end test against the reference adopter configuration

## What & why

Turn the Notion Section 9 reference adopter (user, project, and organization
scopes; organization writes for admins and owners only; seed areas; a
curated `system/` area per scope; systems of record) into one tests-only
fixture module. Then drive a full agent session through the tool layer over
the real in-process transport, asserting what a host would see. These are
the first tool-layer tests of a populated memory index.

## Acceptance criteria

Identities: M member, A org admin (same org and project), T = M's user in another org, P = another user in M's org but another project.

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| US1 | the fixture | read | scopes, org role gate `{admin, owner}`, priority user>project>org, seed areas, one `system/` file per scope; prompt slots name every scope and seed area; all four identities pass `ResolverConformance` |
| US2 | seeded store, M's tools | `get_memory_index()` | exactly the seed files, exact index keys, `system/` first then user, project, org; another user's file absent; `capped` empty |
| US3 | each scope, as the identity allowed to write it | read system, write `reference-e2e`, read, append (with aliases + description), replace, delete, read | each step's rendered output is exact; final read is `not_found` / `file_absent` |
| US4 | after M and A sessions; T; P | index for each | new files first in tier, deleted absent; A sees shared writes but not M's user scope; T sees M's user files and nothing of o-acme; P sees o-acme org files and nothing of p-checkout |
| US5 | tools on `system/` in each scope | all four mutating tools | `system_read_only`, permanent; also for M on org `system/` (precedes the role check); store unchanged; the transport then accepts a write to the rejected path |
| US6 | M's tools | all four mutating tools on organization | `role_required`, `required_roles` `["admin", "owner"]`; reads still work |
| US7 | M and A hold the same project version | both append | second gets a recoverable conflict with exact current content; retry lands, no duplicate |
| US8 | two stores replaying one sequence; second capped to system + user + one project entry | `get_memory_index()` | capped entries are a prefix of uncapped; exact `capped` rows (org vocabulary 1, project entities 1, project metrics 2); `list_prefix` recovers them |
| US9 | — | `make check` | unit tests on `InMemoryStorage` + `InProcessClient`; prompt tests unchanged after the fixture move |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| Fixture in `tests/reference_adopter.py`, public `wenchang` imports only | Public `wenchang.testing` module | Section 9 says the reference adopter is illustrative, not library; AIE-1170 moves it to a dev-only package outside the wheel, no ADR |
| Absorb `tests/prompts_reference_adopter.py` | Keep two modules | One configuration that cannot drift |
| Real `InProcessClient` + `MemoryStore` | Existing tests-only client double | That double returns an empty index |
| Seed via the transport client | Seed via tools or store | Shows `system/` is enforced only at the tool layer |
| Whole-second ticking clock, two-store replay for US8 | Fixed clock; literal byte counts | Deterministic order and sizes; cap derived, not hard-coded |
| Four identities | Two | Section 9's cross-org user scope and partial-project org reads each need one |

## Files/modules to be touched

- `tests/reference_adopter.py` (new, moved from `tests/prompts_reference_adopter.py`)
- `tests/test_reference_adopter_config.py`, `tests/test_reference_adopter_end_to_end.py` (new)
- `tests/test_prompts_assembly.py`, `tests/test_prompts_write_mechanics.py` (import only)
- `README.md` link, ADR 0025 decision 10 sentence, ADR 0026 path, `ARCHITECTURE.md` one sentence. No `src/`, no new ADR.

## Open questions / assumptions

- No public API: the fixture stays in `tests/` for now; AIE-1170 relocates it.
- AIE-1151 `aliases` / `description` are exercised once per scope; their edge cases stay in AIE-1151's tests.
- The index byte budget is covered because Section 9 defines scope priority for the capped index.
- Section 9 prompt behavior (ask before shared writes, surface contradictions, the scope test) is agent judgment, evaluated in AIE-1170, not unit-tested.
- Oversize, resolver-failure, and transient errors are already covered elsewhere and left out.

## Risks

- A lifecycle failure would mean a library defect; it would be reported at the build checkpoint, not patched silently.
- US8 relies on `InMemoryStorage` tokens being a deterministic counter; the prefix assertion fails loudly if that changes.
