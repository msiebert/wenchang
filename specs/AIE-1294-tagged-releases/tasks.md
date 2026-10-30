# Tasks: AIE-1294

Test-first: test-writer writes failing tests (`tests/**` only) before anything else. `CHANGELOG.md`, `.github/workflows/**`, `AGENTS.md`, and `site-src/` are outside the implementer's and doc-updater's hook scopes, so those tasks are done by the lead or a general-purpose agent. Spec refs are `spec.md` user stories.

## T1 - Version, changelog, and pinned-tag tests (US3)

- [ ] T1 test-writer: add `tests/test_release.py` per plan.md (seven unit tests). Expected failing state: the four changelog tests fail (no `CHANGELOG.md`); the pin test fails (`docs/releasing.md` missing; unpinned installs in README and site-src); the two version tests pass on arrival.

## T2 - Changelog (US3, US4; lead/general-purpose)

- [ ] T2 add `CHANGELOG.md` (Keep a Changelog; `[Unreleased]` empty; `[0.1.0] - 2026-10-30` summarizing the first release: core store and the seven tools including `get_memory_index`, optimistic concurrency, scope priority for the startup index, GCS and in-memory storage, identity resolver, scopes and write policy, transport and in-process client, tool layer with product naming, prompt layer with slots, MCP adapter (`[mcp]` extra), conformance mixins (`[testing]` extra), Python 3.11+; no `evals/`; link references). Changelog tests pass.

## T3 - Release workflow (US2; lead/general-purpose)

- [ ] T3 add `.github/workflows/release.yml` per plan.md, including the concurrency group. Validate the YAML parses and dry-run the shell pieces locally: the version check with `GITHUB_REF_NAME=v0.1.0` and `v0.1.1`, `uv build`, the smoke install of `"wenchang[mcp,testing] @ file://…whl"` and the six module imports (including `wenchang.mcp`) from a temp dir, and the awk notes extraction against `CHANGELOG.md` (non-empty for `0.1.0`, empty for a missing version). Do not push any tag.

## T4 - Docs (US1, US4)

- [ ] T4a doc-updater: `docs/releasing.md` (policy, install by tag and by wheel URL, release steps including pinned-tag update and tagging the release PR's merge commit, `[Unreleased]` rule, recovery); README Install section, pinned MCP install, Docs list.
- [ ] T4b doc-updater: `docs/adr/0041-tagged-releases.md`.
- [ ] T4c lead/general-purpose: `site-src/setup.md`, `site-src/index.md`, `site-src/reference.md` (status line and `[testing]` install), `site-src/authorization.md` (`[testing]` install), Python 3.11 lines; regenerate `site/` with `uv run scripts/build_site.py`. `AGENTS.md` Commands: "Releasing: see docs/releasing.md". Pinned-tag test passes.
- [ ] T4d lead/implementer: `src/wenchang/__init__.py` docstring.
- [ ] T4e doc-updater: `specs/AIE-1294-tagged-releases/review-pr.md`.

## T5 - Verify

- [ ] T5 lead: `make check`; local `uv build` + scratch-venv install of the wheel with `[mcp,testing]` prints `0.1.0` and the six module imports succeed.

## Order

T1, then T2 and T3 (independent). T4 after T2/T3. T5 last. Post-merge tag push and live install check belong to the orchestrator.
