# 0041. Tagged releases on GitHub

Date: 2026-10-30

## Status

Accepted.

## Context

Adopters could pin wenchang only to a commit SHA. There was no release, no
changelog, and no stated meaning for a version number. The Notion spec does
not cover packaging or releases (AIE-1294). The version already lived in two
places, `pyproject.toml` and `wenchang.__version__`, with nothing keeping them
equal.

## Decision

1. **Releases are git tags plus GitHub Releases.** A release is a `vX.Y.Z`
   tag on `main` and a GitHub Release of the same name with the wheel and
   sdist attached. Nothing is published to PyPI or any other index. Adopters
   install by a `git+https` URL pinned to the tag, or by the release wheel's
   URL.
2. **A tag-triggered workflow publishes the release.**
   `.github/workflows/release.yml` runs only on a pushed `v*` tag. Before
   anything slow, it fails unless the tag equals `v` plus the
   `pyproject.toml` version and the tagged commit is an ancestor of
   `origin/main`. It then runs `make check`, builds with `uv build`,
   smoke-installs the wheel with the `[mcp,testing]` extras into a clean venv
   outside the checkout (checking `__version__`, the distribution metadata
   version, and that the public modules import), and creates the GitHub
   Release with the version's `CHANGELOG.md` section as its notes. A missing
   or empty section fails the run.
3. **The version stays a literal in two places.** `pyproject.toml` has a
   static `version`, and `src/wenchang/__init__.py` has a literal
   `__version__`. `tests/test_release.py` asserts they are equal, that the
   version is plain `X.Y.Z`, and that `CHANGELOG.md` has a dated, non-empty
   section and link reference for it, so drift fails `make check` rather than
   the release.
4. **Install instructions pin the current version, and a test checks them.**
   `README.md`, `docs/releasing.md`, `site/llms.txt`, and `site-src/*.md` show concrete
   `@v{version}` pins. The same test fails on any wenchang git URL or release
   asset URL with another version, and on any bare install with no URL.
   Code docstrings and error messages name the extra (`wenchang[mcp]`) and
   point to `docs/releasing.md` rather than pinning a version.
5. **Changelog and versioning policy.** `CHANGELOG.md` follows Keep a
   Changelog; every user-visible PR adds an `[Unreleased]` entry. SemVer
   applies to the documented Python API, the tool contract, and the stored
   format; while `0.x`, breaking changes bump minor and everything else bumps
   patch; memory-prompt wording changes are at least minor. Pushed tags with
   a published release are never moved. Details are in
   [docs/releasing.md](../releasing.md).
6. **The sdist is curated.** `[tool.hatch.build.targets.sdist]` includes only
   `src/`, `README.md`, `LICENSE`, `CHANGELOG.md`, and `pyproject.toml`, and
   builds the same wheel. Tests are left out: the test suite needs the repo
   (the dev-only `evals/` package, agent docs, ADRs) and runs from a checkout.

## Consequences

- Adopters pin a meaningful version and read what changed in the changelog.
- A release bumps the version in two files; the test catches a missed one.
- Every release PR also bumps the pinned tag in the README, the site sources,
  the hand-maintained `site/llms.txt`, and `docs/releasing.md`, and
  regenerates `site/`. The test catches a missed pin.
- A tag runs the workflow file as it exists at the tagged commit. A workflow
  bug found on the first run of a tag needs a fix on `main` and a re-tag; this
  is allowed only while no GitHub Release exists for the tag.
- Installing needs network access to GitHub, and installing by tag needs git.
  The wheel URL avoids the git and build step.

Rejected:

- **Publish to PyPI.** Not wanted for this project; tags and GitHub Releases
  cover pinning without an index account or name.
- **An internal package index.** Adds infrastructure and credentials for no
  gain over installing from GitHub.
- **Derive `__version__` with `importlib.metadata`, or a hatch dynamic
  version.** A source tree vendored or built without distribution metadata,
  as a monorepo may do, would fail to report its version or to import.
- **`gh release create --generate-notes`.** PR titles are not curated
  release notes; the changelog section is.
- **Skip the tag/version and on-`main` guards.** A mistyped tag would
  publish artifacts whose version disagrees with the tag, or release
  unreviewed code.
- **Pre-release tags such as `v0.2.0rc1`.** Out of scope; the version test
  rejects them, so adding them is a deliberate change.
