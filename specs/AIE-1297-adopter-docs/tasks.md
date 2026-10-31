# Tasks: AIE-1297

Build starts only after AIE-1295 merges. First: rebase onto `origin/main`,
then re-read the shipped `src/` for every fact listed in plan.md.

The guard hook blocks the `implementer` from `site-src/`, `scripts/`, `site/`,
and `AGENTS.md`, so those edits go to a `general-purpose` agent (opus, no
`name=`), which stays out of `src/` and `tests/`.

1. **Inventory sibling site text** (lead): list every `site-src/` and
   `site/llms.txt` change the five sibling PRs merged (#53 Telemetry, #54 file
   cap, #56 `caching.md`, #57 purge/export, AIE-1295), and where each lands
   per plan.md's move table, including links to retarget.
2. **Tests first** (test-writer): `tests/test_site.py` and
   `tests/test_site_snippets.py` per plan.md. Confirm they fail against the
   current `site/` for the right reasons (missing pages, nav labels, missing
   `memory-prompt.md`, stale strings, bare installs); snippets that already
   run pass.
3. **Build script** (general-purpose): nav children, sub-nav, redirect stubs
   (4), generated `memory-prompt.md` and `<!--include-prompt-->` with a safe
   fence, generated sitemap, stale-output deletion, `PAGES`-derived
   `llms-full.txt` header, `walkthroughs` special-casing, `.subnav` CSS.
4. **Pages** (general-purpose, `site-src/` only): rename `setup`→`quickstart`,
   `authorization`→`identity`, `usage`→`walkthroughs`; fold `caching` into
   `storage`; write `concepts`, `integrate`, three integrate children,
   `storage`, `status`; slim `reference`; update `index`, `prompts`; new
   snippets `integrate_direct.py` and `ops_erase.py` with `assert`s; fix
   Python 3.11, metadata keys, and bare installs; verify US5.5/5a facts.
5. **llms.txt** (general-purpose): step 0, Docs list, Optional prompt link.
6. **AGENTS.md** (general-purpose): the regenerate-site Commands line.
7. **HTTP example run** (general-purpose): per plan.md against
   fake-gcs-server; record commands and output for review-pr.md; remove the
   note only if all five cases ran.
8. **Regenerate and verify** (general-purpose): `uv run scripts/build_site.py`
   twice (no diff on second run), `make check`, desktop and 375px screenshots
   of `integrate-without-mcp.html` and `storage.html`.
9. **Review artifact** (doc-updater): `review-pr.md` from the template,
   including the nav-label note, the HTTP run commands and output, and the
   note that `make check` depends on committed `site/` output.
