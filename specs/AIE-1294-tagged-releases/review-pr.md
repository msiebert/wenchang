# PR Review: AIE-1294 — Publish tagged releases

## What changed & why

Adopters could pin wenchang only to a commit SHA. Releases are now `vX.Y.Z` tags plus GitHub Releases with the wheel and sdist (no package index). A tag-triggered workflow guards tag/version and on-main, runs `make check`, builds, smoke-installs, and publishes with the `CHANGELOG.md` section as notes. A unit test keeps `pyproject.toml`, `__version__`, the changelog, and every documented install pin in step. No library behavior changes.

## Acceptance criteria → tests

| Acceptance criterion | Test / verification |
| --- | --- |
| US1.1–2 install by tag / wheel URL yields `0.1.0` | Post-merge: orchestrator pushes `v0.1.0`, fresh-venv installs (base, `[mcp]`, wheel URL) |
| US1.3, US3.3 install docs pin `@v0.1.0`, no bare installs, say not on PyPI | `test_install_instructions_pin_current_version`; README Install, `docs/releasing.md`, `site-src/` by reading |
| US2.1 tag != `v`+version fails before publishing | `release.yml` "Check tag matches version"; local dry-run; live `v0.1.0` run |
| US2.2 tag not on main fails | `release.yml` "Check tag is on main"; by reading |
| US2.3 `make check`, build, smoke install `[mcp,testing]`, release with notes | `release.yml` steps; local `uv build` + scratch-venv install; live `v0.1.0` run |
| US2.4 no changelog section fails | "Extract release notes" step; same rule as `test_changelog_section_for_current_version_is_not_empty` |
| US2.5 no run on branch/PR | `on: push: tags: ["v*"]` only |
| US3.1 `__version__` == pyproject, plain `X.Y.Z` | `test_package_version_matches_pyproject`, `test_version_is_plain_semver` |
| US3.2 changelog heading, `[Unreleased]` above, non-empty, link ref | `test_changelog_has_section_for_current_version`, `test_changelog_has_unreleased_section_above_releases`, `test_changelog_section_for_current_version_is_not_empty`, `test_changelog_has_link_reference_for_current_version` |
| US4.1 policy, release steps, `[Unreleased]` rule | `docs/releasing.md` by reading |
| US4.2 ADR | `docs/adr/0041-tagged-releases.md` |
| US4.3 `0.1.0` section summarizes first release | `CHANGELOG.md` by reading |

## Architecture / ADR changes

- [ADR 0041](../../docs/adr/0041-tagged-releases.md): tags + GitHub Releases, workflow guards, literal two-place version with a consistency test, tested install pins.
- `ARCHITECTURE.md`: unchanged (no module, API, or storage change). Glossary unchanged.

## Deviations from spec

- None. The Notion spec does not cover releases; the decision is in ADR 0041.

## Look closely at

- `release.yml` awk notes extraction matches the test's rule (stops at the next `## ` or a `[x]: ` link line).
- Smoke install runs from `$RUNNER_TEMP` so the checkout's `src/` cannot mask a broken wheel.
- `CHANGELOG.md` `0.1.0` contents: accurate and complete for what is on `main` at tag time (sibling PRs may land first).
- Recovery policy in `docs/releasing.md`: a tag may be moved only if no release was created.

## Follow-ups

- Post-merge: push `v0.1.0` on the merge commit, confirm the run is green and the fresh-venv installs print `0.1.0`.
