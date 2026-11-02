# Releasing

## Where releases live

A release is a git tag `vX.Y.Z` on `main` plus a GitHub Release of the same
name with the built wheel and sdist attached. wenchang is not published to
PyPI or any other package index. Release notes come from
[CHANGELOG.md](../CHANGELOG.md).

## Installing a release

The current release is `v0.1.0`. Install it by tag:

```
pip install "wenchang @ git+https://github.com/msiebert/wenchang@v0.1.0"
pip install "wenchang[mcp] @ git+https://github.com/msiebert/wenchang@v0.1.0"
```

With uv:

```
uv add "wenchang @ git+https://github.com/msiebert/wenchang@v0.1.0"
uv add "wenchang[mcp] @ git+https://github.com/msiebert/wenchang@v0.1.0"
```

Or install the release wheel by URL, which needs no git and no build step:

```
pip install https://github.com/msiebert/wenchang/releases/download/v0.1.0/wenchang-0.1.0-py3-none-any.whl
pip install "wenchang[mcp] @ https://github.com/msiebert/wenchang/releases/download/v0.1.0/wenchang-0.1.0-py3-none-any.whl"
```

The `[testing]` extra installs the same way.

## Changelog

Every PR with a user-visible change adds an entry under `## [Unreleased]` in
`CHANGELOG.md`, in the Keep a Changelog groups (`Added`, `Changed`,
`Deprecated`, `Removed`, `Fixed`, `Security`). Internal-only changes, such as
the dev-only `evals/` harness, need no entry.

A version's section runs from its `## [X.Y.Z] - YYYY-MM-DD` heading to the
next `## ` heading or the first line that starts with `[` and contains `]: `
(the link references at the bottom). An entry line of that shape would cut
the release notes short, so don't start an entry with a bracketed link
definition.

## Versioning policy

wenchang follows [Semantic Versioning](https://semver.org/). The public
surface is:

- the documented Python API: `wenchang.core`, `wenchang.tools`,
  `wenchang.mcp`, `wenchang.prompts`, `wenchang.storage`, `wenchang.identity`,
  `wenchang.scope`, `wenchang.transport`, `wenchang.errors`, and
  `wenchang.testing`;
- tool names, parameters, and result and error shapes;
- the stored file format and key layout.

A breaking change is one that makes existing adopter code, tool callers, or
stored memory stop working as before.

- While the version is `0.x`, a breaking change bumps the minor version and
  every other change bumps the patch version.
- From `1.0.0`, standard SemVer applies.
- A change to the memory prompt's wording is at least a minor bump, because
  it changes agent behavior. It is listed under `Changed`.
- Versions are plain `X.Y.Z`; pre-release tags are not used. A test enforces
  this.
- A pushed tag is never moved or deleted once its GitHub Release exists. A bad
  release is superseded by the next patch version.

## Cutting a release

1. On a branch, bump `version` in `pyproject.toml` and `__version__` in
   `src/wenchang/__init__.py` to the same value. `make check` fails if they
   differ.
2. In `CHANGELOG.md`, move the `[Unreleased]` entries under a new
   `## [X.Y.Z] - YYYY-MM-DD` heading, and update the link references at the
   bottom: `[Unreleased]` compares from the new tag, and `[X.Y.Z]` links to its
   release page.
3. Update the pinned tag in every install instruction: `README.md`,
   `site-src/*.md`, `site/llms.txt` (hand-maintained, not generated), and
   this file. Then regenerate the site with `uv run scripts/build_site.py`. `make check` fails if any install
   instruction pins a different version.
4. Run `make check`, open the release PR, and merge it to `main`.
5. Confirm the `[X.Y.Z]` changelog section covers everything at the release
   PR's merge commit, including PRs that merged after the release PR was
   opened. Then tag that merge commit and push the tag:

   ```
   git tag -a vX.Y.Z -m "wenchang X.Y.Z" <release PR merge commit>
   git push origin vX.Y.Z
   ```

6. Watch the Release workflow run in GitHub Actions.
7. In a fresh virtualenv, install by the new tag (as in
   [Installing a release](#installing-a-release)) and check that
   `python -c "import wenchang; print(wenchang.__version__)"` prints the new
   version.

## What the Release workflow checks

`.github/workflows/release.yml` runs only on a pushed `v*` tag. In order, it:

1. fails unless the tag is exactly `v` plus `[project].version` from
   `pyproject.toml`;
2. fails unless the tagged commit is on `main` (an ancestor of
   `origin/main`);
3. runs `uv sync --locked` and `make check`;
4. builds the wheel and sdist with `uv build`;
5. installs the wheel with the `[mcp,testing]` extras into a clean venv and,
   from outside the checkout, checks that `wenchang.__version__` and the
   installed distribution's version both equal the tag's version and that
   `wenchang.core`, `wenchang.tools`, `wenchang.prompts`,
   `wenchang.storage.memory`, `wenchang.testing`, and `wenchang.mcp` import;
6. extracts the version's section from `CHANGELOG.md` as the release notes,
   failing if it is empty;
7. creates the GitHub Release named after the tag, with the wheel and sdist
   attached.

## Recovery

A tag runs the workflow file as it exists at the tagged commit, so fixing the
workflow on `main` does not fix a run for an existing tag.

- **The run failed before the GitHub Release was created.** Fix the problem
  on `main`, delete the tag, and tag the new `main` commit:

  ```
  git push origin :refs/tags/vX.Y.Z
  git tag -d vX.Y.Z
  git tag -a vX.Y.Z -m "wenchang X.Y.Z" <new main commit>
  git push origin vX.Y.Z
  ```

  This is the only allowed tag move, because no release was published.
- **The release was created but the run failed transiently, such as a
  partial asset upload, or a re-run fails because the release already
  exists.** Delete the GitHub Release (not the tag) and re-run the workflow.
- **The release is wrong.** Never move the tag. Fix it on `main` and ship the
  next patch version.
