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
| Sibling-PR site text (purge, cache, cap, on_call, schemas) | Wherever this table and the pages below place that topic |

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
- **`storage.md`**: US5 items 1-6; new snippet `snippets/ops_erase.py`
  (export then purge one user on `InMemoryStorage`, with an
  `InMemoryIndexCache` and `invalidate_index`).
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
  "usage": "walkthroughs"}`: each writes `site/{old}.html` (meta refresh,
  canonical to the new URL, `noindex`, a plain link) and `site/{old}.md` (one
  line pointing to the new `.md`).
- Memory prompt: the script puts `ROOT / "src"` on `sys.path` and imports
  `wenchang.prompts` (only stdlib dependencies; the PEP 723 env has no
  wenchang install, so this is the lazy-import exception, commented). It
  writes `site/memory-prompt.md` = `build_memory_prompt(PLACEHOLDER_SLOTS) +
  "\n"` with `PLACEHOLDER_SLOTS` using `"{field}"` for each of the four
  fields. `<!--include-prompt-->` in a page source expands to that text in a
  fenced `text` block.
- `llms-full.txt` header: page list built from `PAGES` nav labels.
- `story_classes`/`stash_blocks` special-case `walkthroughs` instead of
  `usage`; `tool_cards` stays on `reference`.
- `site/sitemap.xml` is generated from `PAGES` (13 URLs) instead of
  hand-maintained. `robots.txt` unchanged.
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
| `test_every_page_is_generated_and_listed` | `.html` + `.md` per slug; sitemap `<loc>`s equal the 13 URLs; `llms-full.txt` page markers in order; `llms.txt` links each `{slug}.md` (US8.3) |
| `test_internal_links_resolve` | Every relative `href` in `site/*.html` (redirect stubs included) exists in `site/`; every fragment is an `id` in the target (US8.4) |
| `test_redirect_stubs` | The three old `.html` files meta-refresh to the new page; old slugs absent from nav, sitemap, `llms.txt`, `llms-full.txt` (US8.5) |
| `test_llms_txt_step_zero` | The instructions list's first item starts `0.` and links the three integrate child pages (US1.1) |
| `test_memory_prompt_matches_library` | `site/memory-prompt.md` equals `build_memory_prompt(placeholders) + "\n"`; failure message says to run `uv run scripts/build_site.py` (US7.2) |
| `test_no_stale_claims` | `site-src/*.md` and `site/llms.txt` contain none of `"not run against a live MCP client"`, `"Python 3.12"`, `"3.12 or newer"`, `"3.12+"`; no "planned" in `status.md` limitations (US7.3-7.4, US6) |
| `test_stored_metadata_keys_documented` | `site-src/storage.md` names `last-updated`, `description`, `aliases`, `sources` as stored keys (US5.1) |

HTML is parsed with `html.parser.HTMLParser`, not regex.

`tests/test_site_snippets.py`: `RUNNABLE` and `SKIPPED` (name → reason) sets
covering `site-src/snippets/*.py` exactly (a test asserts the union equals the
directory listing and the sets are disjoint); each runnable snippet runs via
`subprocess.run([sys.executable, path], timeout=60, cwd=tmp_path)` and must
exit 0 (US8.6).

These tests read `site/` as committed, so they fail until the build regenerates
it. They also mean a future prompt-wording change must regenerate the site,
which the failure message says.

## HTTP example run (US7.3)

A scratch script (not committed) imports `auth_http.py`'s resolver and slots,
builds the same server on `InMemoryStorage`, serves it with
`server.run("streamable-http")` on localhost, and drives it with mcp 2.x's
streamable-HTTP client: Tianlong with `X-Project-Id` writes `project` (ok)
and `organization` (`role_required`); Kuixing with no project header writes
`organization` (ok) and has no `project` scope; a bad token gets the resolver
failure. Output summarized in `review-pr.md`. Any snippet bug found is fixed.

## Constraints

- No version pins (see spec, Sequencing); no bare installs.
- Comments in snippets and the build script describe current state; no issue
  IDs in site-src or code.
- `make check` green; `uv run scripts/build_site.py` idempotent.
