# Tasks: AIE-1294

Test-first: test-writer writes failing tests (`tests/**` only), then the implementer adds the config (`CHANGELOG.md`, `.github/workflows/**`, `pyproject.toml` if needed). Spec refs are `spec.md` user stories.

## T1 - Version and changelog consistency tests (US3)

- [ ] T1 test-writer: add `tests/test_release.py` per plan.md (four unit tests). Expected failing state: both changelog tests fail (no `CHANGELOG.md`); the `__version__` and SemVer tests pass on arrival.

## T2 - Changelog (US3, US4)

- [ ] T2 implementer: add `CHANGELOG.md` (Keep a Changelog; `[Unreleased]` empty; `[0.1.0] - 2026-10-30` summarizing the first release: core store and seven tools, optimistic concurrency, GCS and in-memory storage, identity resolver, scopes and write policy, transport and in-process client, tool layer with product naming, prompt layer with slots, MCP adapter (`[mcp]` extra), conformance mixins (`[testing]` extra), Python 3.11+; link references). T1 passes; `make check` green.

## T3 - Release workflow (US2)

- [ ] T3 implementer: add `.github/workflows/release.yml` per plan.md. Validate YAML parses (`uv run python -c "import yaml; yaml.safe_load(open(...))"`) and dry-run the shell pieces locally: the version check with `GITHUB_REF_NAME=v0.1.0` and `v0.1.1`, `uv build`, the smoke install, and the awk notes extraction against `CHANGELOG.md`. Do not push any tag.

## T4 - Docs (US1, US4; doc-updater, then site)

- [ ] T4a `docs/releasing.md`, README Install section and pinned MCP install, Docs list.
- [ ] T4b `docs/adr/0041-tagged-releases.md`.
- [ ] T4c `site-src/setup.md`, `site-src/index.md`, `site-src/reference.md`; regenerate `site/` with `uv run scripts/build_site.py` (general-purpose agent: `site-src/` is outside doc-updater's scope).
- [ ] T4d `specs/AIE-1294-tagged-releases/review-pr.md`.

## T5 - Verify

- [ ] T5 lead: `make check`; local `uv build` + scratch-venv wheel install prints `0.1.0`.

## Order

T1, then T2. T3 is independent of T1/T2. T4 after T2/T3. T5 last. Post-merge tag push and live install check belong to the orchestrator.
