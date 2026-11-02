# Implementation Plan: AIE-1297 docs site restructure

## Summary

Docs-only change plus small, mechanical build-script changes. No `src/`
change, no ADR (the build script stays a single-file static generator; the new
features are a page list field, redirect stubs, and one generated file).

## Content moves

| Today | Goes to |
| ----- | ------- |
| `setup.md` (install, bucket, server.py, register, try, seed, local) | `quickstart.md` (install gets the `[mcp]` compatibility callout and the base-package line; bucket IAM detail summarized and linked to `storage.md#bucket`) |
| `reference.md#concepts` (paths, scopes, areas, names, system, facts, metadata, concurrency, limits) | `concepts.md` (metadata table names stored keys correctly; limits add `max_files_per_entity`) |
| `reference.md#embed` | `integrate-existing-server.md` |
| `reference.md#bind` | `integrate-without-mcp.md` |
| `reference.md#telemetry` | Reference keeps `ToolCallRecord` fields (now from `wenchang.observer`); both integrate pages link it |
| `authorization.md` | `identity.md`, with a new domain-neutral "How identity flows" section first |
| `authorization.md#transports` (stdio, HTTP) | `integrate-new-server.md`; identity page keeps a short pointer |
| `reference.md#storage`, `#store-options` | Reference keeps API signatures; operational guidance in `storage.md` |
| `reference.md#limitations` | `status.md#limitations` |
| `usage.md` | `walkthroughs.md` (content unchanged; title "Walkthroughs") |
| `reference.md` Telemetry section (#53, `on_call` on both entry points) | Reference keeps the `ToolCallRecord` field table; per-entry-point usage moves to the integrate pages |
| `reference.md` file-cap section (#54) | `storage.md#file-cap`; Concepts limits table and Reference store options keep one row/line linking it |
| `caching.md` page (#56, in `PAGES`) | `storage.md#index-cache`; `caching` removed from `PAGES` and added to `REDIRECTS` (→ `storage`) |
| `operations.md` page "Purge & export" (#57, in `PAGES`, the `llms-full` header, `sitemap.xml`, `llms.txt`; snippets `ops_erase.py`, `ops_restore.py`) | `storage.md#erase`; `operations` removed from `PAGES`, its hand-added sitemap/llms.txt lines removed, and added to `REDIRECTS` (→ `storage`). Its `ops_erase.py` is reused (extended with the index-cache/`invalidate_index` step and `assert`s if it lacks them), not duplicated; `ops_restore.py` is kept and embedded. Reference keeps the `purge`/`export` signatures |
| Any other sibling site text | Wherever this table and the pages below place that topic; never in two places |

## New pages

- **`integrate.md`**: a three-row table (path, when to use it, entry point:
  `build_server` / `register_memory_tools` / `bind_tools`), links.
- **`integrate-new-server.md`**: `build_server(...)` arguments, stdio vs
  streamable HTTP (`server.run`), `credentials_from_context`, `product`,
  `tool_prefix`, `source`, `on_call`, compatibility callout, link to identity.
- **`integrate-existing-server.md`**: `register_memory_tools`,
  `memory_instructions(slots)`, collision checks, warning when instructions lack
  the prompt, compatibility callout (with the exact `TypeError` text), the
  `custom_embed.py` snippet.
- **`integrate-without-mcp.md`**: US2 items 1-7; new snippet
  `snippets/integrate_direct.py`.
- **`storage.md`**: US5 items 1-6, absorbing #56's `caching.md` and #57's
  `operations.md`; uses #57's `snippets/ops_erase.py` (export then purge one
  user on `InMemoryStorage`), extended if needed with an
  `InMemoryIndexCache`, `invalidate_index`, and `assert`s, plus #57's
  `ops_restore.py`.
- **`status.md`**: US6.

Every fact on these pages is checked against `src/` on the rebased branch,
not against specs. Specifically verify: `bind_tools` and `MemoryTools`
signatures (incl. `on_call`), `wenchang.schemas` exports, `purge`/`export`
signatures and `PURGE_MAX_PASSES`, `IndexCache`/`InMemoryIndexCache`
signatures, `max_files_per_entity` default, how `index_max_bytes` is measured,
and what `GcsStorage` passes for timeout/retry.

## Build script (`scripts/build_site.py`)

- `PAGES` entries gain optional `"parent": "integrate"`. Header nav lists only
  entries with no parent; a child page marks its parent's nav link
  `aria-current="page"`. Child pages and `integrate` render a small sub-nav
  (`<nav class="subnav">`) listing `integrate` and its children. Prev/next
  links follow `PAGES` order across all 13 pages. The 404 page lists top-level
  pages.
- `REDIRECTS = {"setup": "quickstart", "authorization": "identity",
  "usage": "walkthroughs", "caching": "storage", "operations": "storage"}`: each writes `site/{old}.html` (meta refresh,
  canonical to the new URL, `noindex`, a plain link) and `site/{old}.md` (one
  line pointing to the new `.md`).
- Memory prompt: the script puts `ROOT / "src"` on `sys.path` and imports
  `wenchang.prompts` (only stdlib dependencies; the PEP 723 env has no
  wenchang install, so this is the lazy-import exception, commented). It
  writes `site/memory-prompt.md` = exactly
  `build_memory_prompt(PLACEHOLDER_SLOTS)` (no added newline) with
  `PLACEHOLDER_SLOTS` using `"{field}"` for each of the four fields.
  `<!--include-prompt-->` in a page source expands to that text in a fenced
  `text` block whose fence is one backtick longer than the longest backtick
  run in the prompt (minimum 3).
- Stale outputs: after writing, the build deletes any `site/*.html` not in
  slugs ∪ `REDIRECTS` ∪ {`404`} and any `site/*.md` not in slugs ∪
  `REDIRECTS` ∪ {`memory-prompt`}.
- `llms-full.txt` header: page list built from `PAGES` nav labels.
- `story_classes`/`stash_blocks` special-case `walkthroughs` instead of
  `usage`; `tool_cards` stays on `reference`.
- `site/sitemap.xml` is generated from `PAGES` (13 URLs; `index` is the site
  root URL, not `index.html`) instead of hand-maintained. `robots.txt`
  unchanged.
- CSS: `.subnav` styles only, reusing existing tokens. Nav must fit 10 items
  plus GitHub at desktop width; at <= 48rem the existing scrollable nav is
  kept.

## llms.txt (hand-maintained)

- Summary line: Python 3.11+.
- "Instructions for AI agents": new step 0 ("Ask which path applies: a new MCP
  server (follow steps 1-8), an existing mcp 2.x `MCPServer` (see ...), or no
  MCP (see ...)"), linking the three child `.md` pages. Steps 1-8 stay the
  new-server path; step 2 keeps the unpinned git URL.
- "Docs": one line per page in nav order (13), plus "Full memory prompt"
  (`memory-prompt.md`) under Optional.

## Tests (written first, fail before the build)

`tests/test_site.py` (`pytest.mark.unit`, stdlib + `wenchang.prompts` only,
reads committed files under `site/` and `site-src/`):

| Test | Checks |
| ---- | ------ |
| `test_header_nav_order` | For each of the 13 `site/{slug}.html`, the `<nav class="site-nav">` link texts equal `NAV_LABELS + ["GitHub"]` (US8.2) |
| `test_every_page_is_generated_and_listed` | `.html` + `.md` per slug; sitemap `<loc>`s equal the 13 URLs (`index` → site root); `llms-full.txt` page markers in order; `llms.txt` links each `{slug}.md` (US8.3) |
| `test_no_stale_outputs` | `site/*.html` stems == slugs ∪ `REDIRECTS` ∪ {`404`}; `site/*.md` stems == slugs ∪ `REDIRECTS` ∪ {`memory-prompt`} (US8.7) |
| `test_internal_links_resolve` | Every relative `href` in `site/*.html` (redirect stubs included) exists in `site/`; every fragment, including same-page `#frag`, is an `id` in the target. Skipped: absolute `http(s)://`, protocol-relative `//`, `mailto:`, and bare `#` (US8.4) |
| `test_redirect_stubs` | The five old `.html` files (`setup`, `authorization`, `usage`, `caching`, `operations`) meta-refresh to the new page; old slugs absent from nav, sitemap, `llms.txt`, `llms-full.txt` (US8.5) |
| `test_llms_txt_step_zero` | The instructions list's first item starts `0.` and links the three integrate child pages (US1.1) |
| `test_memory_prompt_matches_library` | `site/memory-prompt.md` equals `build_memory_prompt(placeholders)` byte for byte; failure message says to run `uv run scripts/build_site.py` (US7.2) |
| `test_version_consistency` | `status.md` and `site/llms.txt` state `pyproject.toml`'s `version` and the `requires-python` floor (US8.8) |
| `test_no_stale_claims` | `site-src/*.md` and `site/llms.txt` contain none of `"not run against a live MCP client"`, `"Python 3.12"`, `"3.12 or newer"`, `"3.12+"`; no "planned" in `status.md` limitations; no bare install (pip/uv install of `wenchang` without ` @ ` URL, same pattern as #55's `BARE_INSTALL_RE`); no `msiebert/wenchang.git`; no install command in `site-src/snippets/*.py` (US7.3-7.4, US6, FR-003) |
| `test_stored_metadata_keys_documented` | `site-src/storage.md` names `last-updated`, `description`, `aliases`, `sources` as stored keys (US5.1) |

HTML is parsed with `html.parser.HTMLParser`, not regex.

`tests/test_site_snippets.py`: `RUNNABLE` (set) and `SKIPPED` (name →
reason) covering `site-src/snippets/*.py` exactly (a test asserts the union
equals the directory listing and the sets are disjoint). Reasons are one of
"needs GCS", "needs a network server", "needs a third-party package". Each
runnable snippet runs via `subprocess.run([sys.executable, path], timeout=60,
cwd=tmp_path)` and must exit 0; each skipped snippet must `py_compile` (US8.6).
Expected classification (the test-writer confirms against the merged
snippets, including any siblings added):

- `SKIPPED`: `setup_server.py`, `setup_seed.py` (needs GCS), `auth_http.py`
  (needs GCS), `cache_redis.py` or any other snippet importing a package not
  in the dev group (needs a third-party package).
- `RUNNABLE`: `custom_bind.py`, `custom_embed.py`, `custom_store.py`,
  `custom_conformance.py`, `prompt_slots.py`, `prompt_extra.py`,
  `custom_observer.py`, `integrate_direct.py`, `ops_erase.py`,
  `ops_restore.py` (if it runs offline), and any other
  sibling snippet that runs offline.

`integrate_direct.py` and `ops_erase.py` end in `assert`s on their outcomes
(US8.6), so running them is a real check.

These tests read `site/` as committed, so they fail until the build regenerates
it. They also mean a future prompt-wording change must regenerate the site,
which the failure message says.

## HTTP example run (US7.3)

Run `auth_http.py` unchanged against fake-gcs-server: `make emulator-up`,
create the bucket, then start the snippet with `STORAGE_EMULATOR_HOST=
http://localhost:4443` and `WENCHANG_BUCKET` set (google-cloud-storage honors
the emulator variable). A scratch client script (not committed) uses mcp
2.x's streamable-HTTP client against `http://localhost:8000/mcp` with
per-case headers for the five cases in spec US7.3. The exact commands and the
output of each case go into `review-pr.md`. If the run cannot be done, the
note stays on the page and `review-pr.md` says why. A snippet bug found here
is fixed.

## Constraints

- No version pins (see spec, Sequencing); no bare installs; install lines
  only in `site-src/*.md` and `site/llms.txt`, as
  `git+https://github.com/msiebert/wenchang` (no `.git`).
- Storage page facts for US5.5/5a are verified at build time: the default
  timeout and the retry policy google-cloud-storage applies to `upload` with
  and without `if_generation_match` and to `delete` with it, and
  `GcsStorage.get`'s 3-attempt generation-race loop.
- AGENTS.md Commands: add "regenerate the site with
  `uv run scripts/build_site.py` after changing prompts or `site-src/`".
- The PR description notes that `make check` now depends on committed
  generated output under `site/`.
- Comments in snippets and the build script describe current state; no issue
  IDs in site-src or code.
- `make check` green; `uv run scripts/build_site.py` idempotent.
