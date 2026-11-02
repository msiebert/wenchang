# Spec Review: AIE-1297 — Restructure the docs site for adopters

## What & why

The site only explains one setup: a new stdio MCP server for Claude Code.
Adopters embedding wenchang in an existing service, with their own MCP server
or tool framework, have to stitch it together. This reorganizes the site
around three integration paths and adds pages for identity, storage and
operations, and status, describing AIE-1291/1292/1293/1295/1296 as shipped.
Docs and build script only; no `src/` change.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | llms.txt | agent reads instructions | step 0 asks which path and links the three integrate pages |
| 2 | Integrate without MCP | read | base install, per-request `bind_tools`, `tool_schemas`, `render_error`, sync/thread-safe, `on_call` on `bind_tools`, runnable snippet |
| 3 | Quickstart + MCP integrate pages | read | callout: mcp 2.x `MCPServer` only, no FastMCP/1.x, `TypeError` otherwise |
| 4 | Identity page | read | domain-neutral chain credentials→resolver→Identity→path→ScopePolicy and a type/owner/org-project-user table, before the example |
| 5 | Storage page | read | stored keys (`last-updated`, JSON arrays), purge/export + GDPR + soft delete/versioning, index cost + cache, file cap, no timeout/retry settings |
| 6 | Status page | read | 0.1.0, Python 3.11+, tags + GitHub Releases, no PyPI, SemVer policy, changelog link, limitations as they are today |
| 7 | Nav | read | Overview, Quickstart, Concepts, Integrate, Identity, Storage, Prompts, Reference, Walkthroughs, Status |
| 8 | `site/memory-prompt.md` | compared to `build_memory_prompt(placeholders)` | equal; Prompts page embeds it |
| 9 | HTTP auth example | run unchanged on fake-gcs-server | 5 cases driven by mcp 2.x streamable-HTTP client, recorded in review-pr.md; note removed (kept if run impossible) |
| 10 | Site | built twice; tests run | idempotent; nav, pages, sitemap, llms files, no stale outputs, internal links/anchors, redirects, versions, install-line form, snippets (run or py_compile) all checked by tests |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| 13 pages; Integrate is a chooser page plus 3 children, shown in a sub-nav | One Integrate page with 3 sections | Issue asks for a page per path for llms.txt step 0 |
| Short nav labels (Identity, Storage, Reference, Status) | Issue's full names | Ten full names don't fit one header row; titles keep full names |
| Redirect stubs for setup/authorization/usage/caching; build deletes stale outputs | Keep old slugs | "Examples" label must match file; old links shouldn't 404 |
| Generated `memory-prompt.md` with `{slot}` placeholders + drift test | Hand-pasted copy | Hand copy drifts from the library |
| Tests read committed `site/` output (stdlib parsing) | Run the build in tests | Build needs markdown/pygments, not in dev deps |
| Snippets executed by a test, with an explicit skip list | Untested snippets | New integrate/ops snippets must actually run |
| Install lines unpinned URL form | Pin to v0.1.0 here | #55 owns pinning and its pin test, rebasing onto this |
| HTTP example: one live run of the unchanged snippet on fake-gcs-server, recorded in review-pr.md | Durable ASGI test; rewriting the snippet onto InMemoryStorage | Tests the published file as-is; one recorded run satisfies the issue |
| No ADR | ADR 0044 | Build change is mechanical (page list, stubs, one generated file) |

## Files/modules to be touched

- `site-src/*.md` (rename 3, add 7, edit index/prompts/reference), `site-src/snippets/` (+2), `site-src/style.css` (`.subnav`)
- `scripts/build_site.py`; regenerated `site/**` incl. `memory-prompt.md`, `sitemap.xml`, redirect stubs
- `site/llms.txt`
- `tests/test_site.py`, `tests/test_site_snippets.py`
- `AGENTS.md` (Commands: regenerate the site after prompt or site-src changes)

## Open questions / assumptions

- Settled by orchestrator: no ADR; the prompt drift test is accepted; #55 rebases onto this and re-pins every install line.
- Status page links `CHANGELOG.md` / `docs/releasing.md`, which exist only after #55 merges right after this.
- Sibling docs (#53 Telemetry, #54 file cap in `reference.md`; #56 `caching.md`; #57 purge/export) are relocated per plan.md's move table; `caching.html` becomes a redirect to `storage.html`.

## Risks

- Sibling PRs add their own site text in places this moves; rebase conflicts are resolved by placing each topic per the plan's move table.
- Moved anchors break external deep links into `reference.html` (pages redirect, anchors don't).
- Facts are written from the specs now; build must re-verify every one against merged `src/`.
