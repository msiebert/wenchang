# Implementation Plan: AIE-1294 Publish tagged releases

**Branch**: `AIE-1294-tagged-releases` | **Date**: 2026-10-30 | **Spec**: [spec.md](spec.md)

## Summary

Releases are git tags `vX.Y.Z` plus GitHub Releases carrying the wheel and sdist; no package index. A tag-triggered workflow verifies the tag against `pyproject.toml`, gates on `make check`, builds, smoke-installs the wheel, and publishes the release with the changelog section as notes. A unit test keeps `pyproject.toml`, `wenchang.__version__`, and `CHANGELOG.md` in step. Docs cover the versioning policy, install-by-version, and release steps. No library behavior changes.

## Technical Context

Python 3.11+, hatchling build backend, uv, pytest, GitHub Actions (`actions/checkout@v4`, `astral-sh/setup-uv@v3`, preinstalled `gh`). No new dependencies.

## Constitution Check

- I/II Tests-first, not weakened: `tests/test_release.py` lands first; the changelog assertions fail until `CHANGELOG.md` exists. The `__version__` equality assertion passes on arrival (both already `0.1.0`); it is a drift guard, not new behavior.
- IV Strict typing: the new test is pyright-strict clean.
- V Storage only through the interface: untouched.
- VI Spec fidelity: the Notion spec does not cover releases; the decision is recorded in ADR 0041.
- VII Architecture documented: no module boundary, public API, or storage change; ARCHITECTURE.md unchanged. ADR 0041 added.
- VIII Traceability: test docstrings cite `AIE-1294, USx.y`.
- IX Single issue: yes.
- XI Review artifacts: review-spec.md now, review-pr.md at PR.

Result: pass.

## Interfaces

### Version (unchanged, now load-bearing)

- `pyproject.toml`: `[project] version = "0.1.0"` (static; not `dynamic`).
- `src/wenchang/__init__.py`: `__version__ = "0.1.0"`, a literal string. Both are bumped together in a release PR.

### `CHANGELOG.md` (repo root)

Keep a Changelog 1.1.0 format. Machine-relevant shape:

```
# Changelog
...preamble...
## [Unreleased]

## [0.1.0] - 2026-MM-DD
### Added
- ...

[Unreleased]: https://github.com/msiebert/wenchang/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/msiebert/wenchang/releases/tag/v0.1.0
```

- Release headings match `^## \[(\d+\.\d+\.\d+)\] - (\d{4}-\d{2}-\d{2})$`.
- A version's section is the lines after its heading up to the next `## ` heading or the link-reference block.
- The `0.1.0` date is the PR's merge-intended date; the tag is pushed after merge. If they differ by a day, the date is not corrected (policy: the date is when the release was cut in the changelog).

### `tests/test_release.py` (unit)

```python
pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[1]

def _project_version() -> str  # tomllib read of pyproject [project].version

def test_package_version_matches_pyproject() -> None
    # wenchang.__version__ == _project_version()
def test_version_is_plain_semver() -> None
    # re.fullmatch(r"\d+\.\d+\.\d+", version)
def test_changelog_has_section_for_current_version() -> None
    # CHANGELOG.md has a line matching rf"## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}"
def test_changelog_has_unreleased_section_above_releases() -> None
    # "## [Unreleased]" exists and its index < the current version heading's index
```

### `.github/workflows/release.yml`

```yaml
name: Release
on:
  push:
    tags: ["v*"]
permissions:
  contents: write
jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - actions/checkout@v4 with fetch-depth: 0
      - astral-sh/setup-uv@v3
      - Check tag matches version: read pyproject version with python3 + tomllib;
        fail unless "$GITHUB_REF_NAME" == "v$version"; export VERSION to $GITHUB_ENV
      - Check tag is on main: git merge-base --is-ancestor "$GITHUB_SHA" origin/main
      - uv sync --locked
      - make check
      - uv build            # dist/wenchang-$VERSION-py3-none-any.whl, dist/wenchang-$VERSION.tar.gz
      - Smoke-install: uv venv "$RUNNER_TEMP/smoke"; uv pip install --python "$RUNNER_TEMP/smoke" dist/*.whl;
        "$RUNNER_TEMP/smoke/bin/python" -c 'import sys, wenchang; sys.exit(wenchang.__version__ != sys.argv[1])' "$VERSION"
      - Release notes: awk extracts the "## [$VERSION]" section of CHANGELOG.md to $RUNNER_TEMP/notes.md;
        fail if it is empty
      - gh release create "$GITHUB_REF_NAME" dist/* --verify-tag --title "$GITHUB_REF_NAME"
        --notes-file "$RUNNER_TEMP/notes.md"   (env GH_TOKEN: ${{ github.token }})
```

Version and tag checks run before `uv sync` and `make check` so a bad tag fails fast. Shell steps use `set -euo pipefail` (Actions' default `bash -e` plus explicit `-u -o pipefail`).

### Docs

- `docs/releasing.md` (new):
  - **Where releases live**: tags `vX.Y.Z`; GitHub Releases with wheel and sdist; not on PyPI.
  - **Installing a release**: `pip install "wenchang @ git+https://github.com/msiebert/wenchang@v0.1.0"`, `pip install "wenchang[mcp] @ git+https://github.com/msiebert/wenchang@v0.1.0"`, the `uv add` equivalents, and installing the release wheel by URL.
  - **Versioning policy**: SemVer. Public surface = the documented Python API (`wenchang.core`, `.tools`, `.mcp`, `.prompts`, `.storage`, `.identity`, `.scope`, `.transport`, `.errors`, `.testing`), tool names/parameters/result and error shapes, and the stored file format and key layout. While `0.x`, a breaking change bumps minor and everything else bumps patch; from `1.0.0`, standard SemVer. Memory-prompt wording changes are at least minor and called out under `Changed`. Tags are never moved or deleted; a bad release is superseded by a patch.
  - **Cutting a release**: (1) on a branch, bump `pyproject.toml` `version` and `src/wenchang/__init__.py` `__version__`; (2) in `CHANGELOG.md` move `Unreleased` entries under `## [X.Y.Z] - YYYY-MM-DD` and update the link references; (3) `make check`, open PR, merge to main; (4) `git fetch origin && git tag -a vX.Y.Z -m "wenchang X.Y.Z" origin/main && git push origin vX.Y.Z`; (5) watch the Release workflow; (6) verify a fresh-venv install by tag. Recovery: a tag runs the workflow file at the tagged commit. If the run failed before `gh release create`, fix on main, then delete the tag (`git push origin :refs/tags/vX.Y.Z`) and re-tag the new main commit; this is the one allowed tag move, because no release was published. If a release was created, never move the tag: for a transient failure after creation, delete the release (not the tag) and re-run; for a wrong release, ship the next patch version.
- `README.md`: new `## Install` section after the intro: pinned pip/uv commands for base and `[mcp]`, "not on PyPI", links to `docs/releasing.md` and `CHANGELOG.md`; the MCP section's `pip install 'wenchang[mcp]'` becomes the pinned form; Docs list gains `CHANGELOG.md` and `docs/releasing.md`.
- `site-src/setup.md` (Install and "What you need"), `site-src/index.md` (both install snippets and the status line), `site-src/reference.md` (Status line): pinned `@v0.1.0` installs, "Python 3.11 or newer", "Releases are git tags with GitHub Releases; not on PyPI". Regenerate `site/` with `uv run scripts/build_site.py`.
- `docs/adr/0041-tagged-releases.md`: decision, context, alternatives (PyPI, internal index, `importlib.metadata` / hatch dynamic version, no tag/main guard), consequences.
- `specs/AIE-1294-tagged-releases/review-pr.md`.

## Verification

- `make check` green.
- Locally: `uv build`, then install the wheel in a scratch venv and print `__version__`.
- Post-merge (orchestrator): push `v0.1.0`; the Release run is green; fresh-venv install by tag (base and `[mcp]`) prints `0.1.0`.

## Project Structure

```text
specs/AIE-1294-tagged-releases/{spec.md,plan.md,tasks.md,review-spec.md}
.github/workflows/release.yml       (new)
CHANGELOG.md                        (new)
tests/test_release.py               (new)
docs/releasing.md                   (new)
docs/adr/0041-tagged-releases.md    (new)
README.md  site-src/{setup.md,index.md,reference.md}  site/ (regenerated)
```

`pyproject.toml` and `src/wenchang/__init__.py` need no change (already `0.1.0`).

## Complexity Tracking

None.
