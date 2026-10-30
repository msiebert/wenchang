# Tasks: AIE-1297

Build starts only after AIE-1295 merges. First: rebase onto `origin/main`,
then re-read the shipped `src/` for every fact listed in plan.md.

1. **Inventory sibling site text** (lead): list every `site-src/` and
   `site/llms.txt` change the five sibling PRs merged, and where each lands
   in the new structure.
2. **Tests first** (test-writer): `tests/test_site.py` and
   `tests/test_site_snippets.py` per plan.md. Confirm they fail against the
   current `site/` for the right reasons (missing pages, nav labels, missing
   `memory-prompt.md`, stale strings); snippets that already run pass.
3. **Build script** (implementer): nav children, sub-nav, redirect stubs,
   generated `memory-prompt.md` and `<!--include-prompt-->`, generated
   sitemap, `PAGES`-derived `llms-full.txt` header, `walkthroughs`
   special-casing, `.subnav` CSS.
4. **Pages** (implementer, site-src only): rename `setup`→`quickstart`,
   `authorization`→`identity`, `usage`→`walkthroughs`; write `concepts`,
   `integrate`, three integrate children, `storage`, `status`; slim
   `reference`; update `index`, `prompts`; new snippets `integrate_direct.py`
   and `ops_erase.py`; fix Python 3.11 and metadata keys.
5. **llms.txt** (implementer): step 0, Docs list, Optional prompt link.
6. **HTTP example run** (implementer): per plan.md; fix snippet if needed;
   remove the note.
7. **Regenerate and verify** (implementer): `uv run scripts/build_site.py`
   twice (no diff on second run), `make check`, desktop and 375px screenshots
   of `integrate-without-mcp.html` and `storage.html`.
8. **Review artifact** (doc-updater): `review-pr.md` from the template,
   including the nav-label note and the HTTP run result.
