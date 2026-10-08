# Spec Review: AIE-1059 — End-to-end test against the reference adopter configuration

## What & why

Turn the Notion Section 9 reference adopter (user, project, and organization
scopes; organization writes for admins and owners only; seed areas; a
curated `system/` area per scope; systems of record) into one tests-only
fixture module. Then drive a full agent session through the tool layer over
the real in-process transport, asserting what a host would see. This proves
the pieces built in milestones 1 to 4 compose for a realistic adopter.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| US1 | the fixture | read | scopes, org role gate `{admin, owner}`, priority user>project>org, seed areas, one `system/` file per scope; prompt slots name every scope and seed area; both identities pass `ResolverConformance` |
| US2 | seeded store, member tools | `get_memory_index()` | every seed file, `system/` first then user, project, org; another user's file absent; `capped` empty |
| US3 | each scope, as the identity allowed to write it | read system, write, read, append (with aliases + description), replace, delete, read | each step's rendered output is right; final read is `not_found` / `file_absent` |
| US4 | after member and admin sessions | index for each | created files present, deleted absent, newest first in tier; admin sees shared writes, never member's user scope |
| US5 | admin tools | all four mutating tools on `system/` in each scope | `system_read_only`, permanent, store unchanged; the transport beneath accepts `system/` writes |
| US6 | member tools | all four mutating tools on organization | `role_required`, `required_roles` `["admin", "owner"]`; reads still work |
| US7 | member and admin hold the same project version | both append | second gets a recoverable conflict with current content; retry lands, no duplicate |
| US8 | small index budget | `get_memory_index()` | system, then user, then partial project; `capped` rows with counts; `list_prefix` recovers the omitted files |
| US9 | — | `make check` | runs as unit tests on `InMemoryStorage` + `InProcessClient`; prompt tests still pass after the fixture move |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| Fixture in `tests/reference_adopter.py` | Public `wenchang.testing` module | Section 9 says the reference adopter is illustrative, not library; no ADR or support burden |
| Absorb `tests/prompts_reference_adopter.py` | Keep two modules | One configuration that cannot drift; AIE-1170 reuses it |
| Real `InProcessClient` + `MemoryStore` | Existing tests-only client double | Matches an adopter's path; the double stubs the index |
| Seed via the transport client | Seed via tools or store | Shows `system/` is enforced only at the tool layer |
| Ticking clock | Fixed clock | Deterministic recency ordering |

## Files/modules to be touched

- `tests/reference_adopter.py` (new, moved from `tests/prompts_reference_adopter.py`)
- `tests/test_reference_adopter_config.py`, `tests/test_reference_adopter_end_to_end.py` (new)
- `tests/test_prompts_assembly.py`, `tests/test_prompts_write_mechanics.py` (import only)
- `README.md` and ADRs 0025/0026 (path-only link fix), `ARCHITECTURE.md` (one sentence). No `src/`, no new ADR.

## Open questions / assumptions

- No public API: the fixture stays in `tests/`. AIE-1170 imports it from there or promotes it under its own ADR.
- AIE-1151 `aliases` / `description` are exercised once per scope; their edge cases stay in AIE-1151's tests.
- The index byte budget is covered because Section 9 defines scope priority for the capped index.
- Section 9 prompt behavior (ask before shared writes, surface contradictions, the scope test) is agent judgment, evaluated in AIE-1170, not unit-tested.
- Oversize, resolver-failure, and transient errors are already covered elsewhere and left out.

## Risks

- A lifecycle failure would mean a library defect; it would be reported at the build checkpoint, not patched silently.
- Moving the prompt fixture changes a README link; nothing outside `tests/` imports it.
