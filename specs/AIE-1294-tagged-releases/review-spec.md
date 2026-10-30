# Spec Review: AIE-1294 - Publish tagged releases

## What & why

Adopters can only pin wenchang to a commit SHA. We publish releases as git tags `vX.Y.Z` with GitHub Releases carrying the wheel and sdist (no package index), add a tag-triggered workflow that checks the tag against the code before publishing, add `CHANGELOG.md`, and document the versioning policy, install-by-version, and release steps. First release is `v0.1.0`, tagged by the orchestrator on the release PR's merge commit after confirming the changelog covers everything there.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | `v0.1.0` pushed, workflow green | `pip install "wenchang[mcp] @ git+...@v0.1.0"` in a fresh venv | installs; `__version__ == "0.1.0"` |
| 2 | Same tag | open the GitHub Release | wheel and sdist attached; changelog section as notes; wheel installs from `.../releases/download/v0.1.0/wenchang-0.1.0-py3-none-any.whl` |
| 3 | Tag not `v` + pyproject version, or not on main | workflow runs | fails before publishing |
| 4 | Consistent tag | workflow runs | `make check`, `uv build`, wheel smoke-install (versions + module imports), `gh release create` |
| 5 | Changelog section for the version missing or blank | workflow runs | fails before publishing |
| 6 | `pyproject.toml`, `__version__`, `CHANGELOG.md` | `make check` | versions equal, `X.Y.Z` form, `[Unreleased]` above a non-empty `[X.Y.Z] - date` section, link reference present |
| 7 | README, `docs/releasing.md`, `site-src/*.md` | `make check` | every `git+...wenchang@v…` pin equals `v{__version__}` |
| 8 | Docs | read | `docs/releasing.md` (policy, steps, `[Unreleased]` rule), README and site pinned installs including `[testing]`, AGENTS.md pointer, ADR 0041 |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| Tags + GitHub Releases | PyPI; internal index | Human decision; no index credentials or namespace needed |
| `__version__` stays a literal, kept equal to pyproject by a test | `importlib.metadata.version`; hatch dynamic version from `__init__.py` | Works in a vendored or metadata-less monorepo build; issue asks for the version in pyproject |
| Workflow verifies tag == version and tag commit on main, then runs `make check` | Trust the tagger | A mistyped or off-main tag would publish mismatched artifacts |
| Smoke-install the wheel: both version sources plus key module imports | Publish build output unchecked | Catches packaging mistakes (missing subpackages, metadata drift) cheaply |
| Release notes from the `CHANGELOG.md` section, same extraction rule tested in `make check` | `--generate-notes` | One source of truth; an empty section fails in CI, not at release |
| Test that doc install pins equal `v{__version__}` | Unpinned docs; manual bump | Pinned docs drift silently on every release otherwise |
| Concurrency group on the release workflow, no cancel | None | Two runs for one tag must not race `gh release create` |
| Plain `X.Y.Z` only | Pre-release tags | Out of scope (confirmed); the test makes adding them deliberate |
| 0.x: breaking bumps minor | Strict SemVer from day one | Conventional for pre-1.0; documented |
| ADR 0041 | Next free number | Pre-assigned: the milestone plan reserves 0038–0043 for AIE-1291..1296 |

## Files/modules to be touched

- New: `.github/workflows/release.yml`, `CHANGELOG.md`, `tests/test_release.py`, `docs/releasing.md`, `docs/adr/0041-tagged-releases.md`
- Edited: `README.md`, `AGENTS.md` (Commands pointer), `src/wenchang/__init__.py` (docstring only), `site-src/{setup,index,reference,authorization}.md`, regenerated `site/`
- Unchanged: `pyproject.toml` (already `0.1.0`), ARCHITECTURE.md
- `CHANGELOG.md`, `release.yml`, `AGENTS.md`, `site-src/` are written by the lead or a general-purpose agent (outside the role hook scopes)

## Open questions / assumptions

1. `GITHUB_TOKEN` with `contents: write` (confirmed).
2. The site's stale "Python 3.12 or newer" lines are fixed to 3.11 (confirmed). Pre-release tags stay out of scope (confirmed).
3. Changelog date for 0.1.0 is 2026-10-30; not adjusted if the tag lands a day later.
4. Sibling PRs (AIE-1292/1293/1296): any merged before this PR is rebased in and covered in `[0.1.0]` by this PR; any merged after lands on main after the tag commit and adds its own `[Unreleased]` entry. The orchestrator confirms coverage before tagging.

## Risks

- The workflow is only exercised for real by the post-merge `v0.1.0` push. A tag runs the workflow file at the tagged commit, so a workflow bug needs a fix PR and then the tag re-pointed. Policy allows deleting and re-pushing a tag only if its run never created a GitHub Release; otherwise bump the patch version.
- The sdist is hatchling's default and includes evals/, site/, specs/; not curated here.
