# Feature Specification: Publish tagged releases

**Linear**: AIE-1294

**Feature Branch**: `AIE-1294-tagged-releases`

**Created**: 2026-10-30

**Status**: Implemented

**Input**: Adopters can only pin wenchang to a commit SHA. Decide where releases go, set the version in `pyproject.toml` and document the versioning policy, add a release workflow that builds and tags, and add a changelog. Acceptance: a tagged release exists and installs by version; release steps are documented.

## Decisions already made (not reopened)

- Releases are git tags plus GitHub Releases with the built wheel and sdist attached. No package index (public or internal).
- The first version is `v0.1.0` (`pyproject.toml` already says `0.1.0`).
- The release workflow is triggered by pushing a `v*` tag. It builds, verifies the tag matches the `pyproject.toml` version, and creates the GitHub Release with the artifacts.
- The orchestrator pushes the `v0.1.0` tag after this PR merges, on the release PR's merge commit, after confirming the `[0.1.0]` changelog section covers everything at that commit (sibling PRs AIE-1292/1293/1296 may land first). This issue's work never pushes a tag.
- Changelog is `CHANGELOG.md` in Keep a Changelog style.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Pin wenchang to a version (Priority: P1)

An adopter installs a specific wenchang release instead of a commit SHA.

**Why this priority**: The whole point of the issue.

**Independent Test**: After the tag is pushed, in a fresh virtualenv, `pip install "wenchang @ git+https://github.com/msiebert/wenchang@v0.1.0"` and `pip install "wenchang[mcp] @ git+https://github.com/msiebert/wenchang@v0.1.0"` succeed and `python -c "import wenchang; print(wenchang.__version__)"` prints `0.1.0`.

**Acceptance Scenarios**:

1. **Given** the `v0.1.0` tag is pushed and its release workflow succeeded, **When** an adopter installs `wenchang @ git+https://github.com/msiebert/wenchang@v0.1.0` (with or without the `[mcp]` extra) into a fresh environment, **Then** the install succeeds and `wenchang.__version__ == "0.1.0"`.
2. **Given** the same tag, **When** the adopter opens the GitHub Release `v0.1.0`, **Then** it has `wenchang-0.1.0-py3-none-any.whl` and `wenchang-0.1.0.tar.gz` attached, and installing the wheel by URL (`pip install https://github.com/msiebert/wenchang/releases/download/v0.1.0/wenchang-0.1.0-py3-none-any.whl`, or `pip install "wenchang[mcp] @ https://github.com/msiebert/wenchang/releases/download/v0.1.0/wenchang-0.1.0-py3-none-any.whl"` for the extra) also yields `0.1.0`.
3. **Given** the README and the site's setup page, **When** an adopter reads the install instructions, **Then** they show install-by-tag for the base package and the `[mcp]` extra (pip and uv), and say releases are not on PyPI.

---

### User Story 2 - A tag push produces a verified release (Priority: P1)

A maintainer pushes a `vX.Y.Z` tag and the workflow publishes a release only if the tag is consistent with the code.

**Why this priority**: Without the guard, a mistyped tag publishes artifacts whose version disagrees with the tag.

**Independent Test**: Read `.github/workflows/release.yml`; after merge, the orchestrator's `v0.1.0` push is the live run.

**Acceptance Scenarios**:

1. **Given** a pushed tag matching `v*`, **When** the release workflow runs, **Then** it fails before publishing if the tag is not exactly `v` + `[project].version` from `pyproject.toml`.
2. **Given** a pushed tag, **When** the workflow runs, **Then** it fails before publishing if the tagged commit is not an ancestor of `origin/main`.
3. **Given** a consistent tag on main, **When** the workflow runs, **Then** it runs `make check`, builds the wheel and sdist with `uv build`, installs the built wheel into a clean venv and checks `wenchang.__version__` and `importlib.metadata.version("wenchang")` equal the version and that `wenchang.core`, `wenchang.tools`, `wenchang.prompts`, `wenchang.storage.memory`, `wenchang.testing`, and `wenchang.mcp` import (the wheel installed with the `[mcp,testing]` extras), and creates a GitHub Release named after the tag with both artifacts attached and the matching `CHANGELOG.md` section as its notes.
4. **Given** `CHANGELOG.md` has no section for the version, **When** the workflow runs, **Then** it fails before publishing.
5. **Given** a push to a branch or a pull request, **When** CI runs, **Then** the release workflow does not run.

---

### User Story 3 - Version numbers stay consistent (Priority: P1)

**Why this priority**: The version lives in two places (`pyproject.toml` and `wenchang.__version__`) plus the changelog; drift must fail `make check`, not the release.

**Independent Test**: `tests/test_release.py`.

**Acceptance Scenarios**:

1. **Given** `pyproject.toml`, **When** the test suite runs, **Then** `wenchang.__version__` equals `[project].version`, and the version has the form `X.Y.Z` (three non-negative integers, no pre-release or local suffix).
2. **Given** `CHANGELOG.md`, **When** the test suite runs, **Then** it contains a release heading `## [X.Y.Z] - YYYY-MM-DD` for the current `pyproject.toml` version with an `## [Unreleased]` heading above it; that version's section (same extraction rule as the workflow) has at least one non-blank line; and the link reference `[X.Y.Z]: https://github.com/msiebert/wenchang/releases/tag/vX.Y.Z` exists.
3. **Given** `README.md`, `docs/releasing.md`, and `site-src/*.md` (all of which must exist), **When** the test suite runs, **Then** it fails listing `file: offending text` for any `git+https://github.com/msiebert/wenchang` not immediately followed by `@v{version}`, any `pip install` / `uv add` of `wenchang` or `wenchang[...]` with no ` @ ` URL, and any `releases/download/v…/wenchang-…` URL whose tag or filename version is not `{version}`. Docs use no placeholder pins.

---

### User Story 4 - Release steps and versioning policy are documented (Priority: P2)

**Acceptance Scenarios**:

1. **Given** `docs/releasing.md`, **When** a maintainer reads it, **Then** it states the versioning policy (SemVer, what counts as breaking, how 0.x is treated) and the release steps: bump version in both places, move changelog entries, update the pinned tag in README, `site-src/`, and `docs/releasing.md` and regenerate `site/`, merge the release PR, tag the release PR's merge commit, push the tag, verify the release. It also says every user-visible PR adds an entry under `## [Unreleased]`.
2. **Given** `docs/adr/`, **When** listed, **Then** ADR 0041 records git tags + GitHub Releases (no package index), the tag/version guard, and the two-place version with a consistency test.
3. **Given** `CHANGELOG.md`, **When** read, **Then** the `0.1.0` section summarizes what the first release contains.

---

### Edge Cases

- `wenchang.__version__` stays a literal string rather than `importlib.metadata.version("wenchang")`: a source tree vendored or built without distribution metadata (as a monorepo may do) must still import and report its version.
- A re-run of the workflow for a tag whose release already exists fails at `gh release create`; the maintainer deletes the release (not the tag) and re-runs. Documented in `docs/releasing.md`.
- Moving or deleting a pushed tag breaks adopters pinned to it. The policy forbids it once a GitHub Release exists: a bad release is fixed by a new patch version. A tag whose run failed before creating a release may be deleted and re-pushed (a tag runs the workflow file at the tagged commit, so a workflow fix needs a new commit).
- Pre-release tags (`v0.2.0rc1`) are out of scope; the version test rejects non-`X.Y.Z` versions, so adding them later is a deliberate change.
- The sdist is hatchling's default: the project tree minus `.gitignore`d paths. Its contents are not curated in this issue.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `pyproject.toml` `[project].version` MUST be `0.1.0`, and `src/wenchang/__init__.py` MUST keep `__version__ = "0.1.0"` as a literal. Its stale "Skeleton package" docstring is replaced with a one-line description.
- **FR-002**: `.github/workflows/release.yml` MUST trigger only on `push` of tags matching `v*`, with `permissions: contents: write` and a `concurrency` group keyed on the ref with `cancel-in-progress: false`.
- **FR-003**: The workflow MUST, in order: check out with full history; check the tag equals `v` + pyproject version; check the tagged commit is an ancestor of `origin/main`; `uv sync --locked`; `make check`; `uv build`; install the wheel with the `[mcp,testing]` extras (`"wenchang[mcp,testing] @ file://$PWD/dist/wenchang-$VERSION-py3-none-any.whl"`) in a clean venv and, from outside the checkout, assert `wenchang.__version__` and `importlib.metadata.version("wenchang")` equal the version and that `wenchang.core`, `wenchang.tools`, `wenchang.prompts`, `wenchang.storage.memory`, `wenchang.testing`, `wenchang.mcp` import; extract the version's `CHANGELOG.md` section (fail if it has no non-blank line); `gh release create <tag> dist/* --verify-tag --title <tag> --notes-file <notes>`.
- **FR-004**: `tests/test_release.py` MUST assert: `__version__` equals the pyproject version; the version matches `^\d+\.\d+\.\d+$`; `CHANGELOG.md` has `## [Unreleased]` above `## [<version>] - <YYYY-MM-DD>`; that section has a non-blank line; the `[<version>]: https://github.com/msiebert/wenchang/releases/tag/v<version>` link reference exists; and the install instructions in `README.md`, `docs/releasing.md`, and `site-src/*.md` (required to exist) pin the current version per US3.3.
- **FR-005**: `CHANGELOG.md` MUST exist at the repo root in Keep a Changelog format with `[Unreleased]` and `[0.1.0]` sections. The `0.1.0` section names `get_memory_index` and scope priority explicitly and omits the dev-only `evals/` harness.
- **FR-006**: `docs/releasing.md` MUST document the versioning policy, install-by-version (git tag, base and `[mcp]`, and the release-wheel URL form), the release steps, and the rule that every user-visible PR adds an `[Unreleased]` entry; README MUST gain an Install section with pinned install commands and link to it; `site-src/setup.md`, `site-src/index.md`, the reference "Status" line, and the `[testing]` installs at `site-src/authorization.md:61` and `site-src/reference.md:325` MUST use `@v0.1.0` (e.g. `"wenchang[testing] @ git+https://github.com/msiebert/wenchang@v0.1.0"`); `site/` MUST be regenerated. AGENTS.md Commands gains "Releasing: see docs/releasing.md".
- **FR-007**: ADR 0041 (pre-assigned by the milestone plan) MUST record the release decision.
- **FR-008**: `make check` MUST pass.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After the orchestrator pushes `v0.1.0`, the release workflow is green and the GitHub Release has the wheel and sdist.
- **SC-002**: A fresh-venv `pip install "wenchang @ git+https://github.com/msiebert/wenchang@v0.1.0"` reports `__version__ == "0.1.0"`.
- **SC-003**: `make check` green with the new tests.

## Assumptions

- The repository's Actions settings allow `GITHUB_TOKEN` write access to contents when the workflow requests it (the default for a personal repo).
- ARCHITECTURE.md describes modules, not packaging, so it needs no change; the `wenchang` package entry already mentions `__version__`.
- The site's "Python 3.12 or newer" lines are stale after AIE-1290; they are corrected to 3.11 (confirmed). `GITHUB_TOKEN` with `contents: write` is allowed (confirmed).
- No tests exercise the workflow YAML itself; the live `v0.1.0` run is its verification.
