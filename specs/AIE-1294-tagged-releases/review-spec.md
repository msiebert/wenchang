# Spec Review: AIE-1294 - Publish tagged releases

## What & why

Adopters can only pin wenchang to a commit SHA. We publish releases as git tags `vX.Y.Z` with GitHub Releases carrying the wheel and sdist (no package index), add a tag-triggered workflow that checks the tag against the code before publishing, add `CHANGELOG.md`, and document the versioning policy, install-by-version, and release steps. First release is `v0.1.0`, tagged by the orchestrator after merge.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | `v0.1.0` pushed, workflow green | `pip install "wenchang[mcp] @ git+...@v0.1.0"` in a fresh venv | installs; `__version__ == "0.1.0"` |
| 2 | Same tag | open the GitHub Release | wheel and sdist attached; changelog section as notes |
| 3 | Tag not `v` + pyproject version, or not on main | workflow runs | fails before publishing |
| 4 | Consistent tag | workflow runs | `make check`, `uv build`, wheel smoke-install, `gh release create` |
| 5 | No changelog section for the version | workflow runs | fails before publishing |
| 6 | `pyproject.toml`, `__version__`, `CHANGELOG.md` | `make check` | versions equal, `X.Y.Z` form, changelog has `[Unreleased]` and `[X.Y.Z] - date` |
| 7 | Docs | read | `docs/releasing.md` (policy + steps), README and site show pinned installs, ADR 0041 |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| Tags + GitHub Releases | PyPI; internal index | Human decision; no index credentials or namespace needed |
| `__version__` stays a literal, kept equal to pyproject by a test | `importlib.metadata.version`; hatch dynamic version from `__init__.py` | Works in a vendored or metadata-less monorepo build; issue asks for the version in pyproject |
| Workflow verifies tag == version and tag commit on main, then runs `make check` | Trust the tagger | A mistyped or off-main tag would publish mismatched artifacts, and tags must never move |
| Smoke-install the built wheel before publishing | Publish build output unchecked | Catches packaging mistakes (missing package data) cheaply |
| Release notes from the `CHANGELOG.md` section | `--generate-notes` | One source of truth; missing section fails the release |
| Plain `X.Y.Z` only | Pre-release tags | YAGNI; the test makes adding them a deliberate change |
| 0.x: breaking bumps minor | Strict SemVer from day one | Conventional for pre-1.0; documented |

## Files/modules to be touched

- New: `.github/workflows/release.yml`, `CHANGELOG.md`, `tests/test_release.py`, `docs/releasing.md`, `docs/adr/0041-tagged-releases.md`
- Edited: `README.md`, `site-src/{setup,index,reference}.md`, regenerated `site/`
- Unchanged: `pyproject.toml` and `src/wenchang/__init__.py` (already `0.1.0`), ARCHITECTURE.md

## Open questions / assumptions

1. Assumes `GITHUB_TOKEN` may get `contents: write` on this repo (default for personal repos).
2. While editing the site's install/status lines, also fix their stale "Python 3.12 or newer" to 3.11 (from AIE-1290). OK?
3. Changelog date for 0.1.0 is 2026-10-30; not adjusted if the tag lands a day later.

## Risks

- The workflow is only exercised for real by the post-merge `v0.1.0` push. A tag runs the workflow file at the tagged commit, so a workflow bug needs a fix PR and then the tag re-pointed. Policy allows deleting and re-pushing a tag only if its run never created a GitHub Release; otherwise bump the patch version.
- The sdist is hatchling's default and includes evals/, site/, specs/; not curated here.
