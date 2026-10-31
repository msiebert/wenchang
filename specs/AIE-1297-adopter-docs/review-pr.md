# PR Review: AIE-1297 — Restructure the docs site for adopters embedding wenchang

## What changed & why

The site assumed one integration path: a new stdio MCP server for Claude Code.
Adopters who embed wenchang in their own service, through their own tool
framework or an existing MCP server, had to piece the details together from
paragraphs spread across pages. The site is now organized around the three
integration paths. It adds pages for integrating without MCP, multi-tenant
identity, storage and operations, and status, and it absorbs the docs from the
sibling PRs (#53, #54, #56, #57, and the AIE-1295 tool schemas) without
duplicating any of them. `scripts/build_site.py` gains support for nav
children, redirect stubs, and a generated `site/memory-prompt.md`. New tests
check the committed site (`tests/test_site.py`) and the snippets
(`tests/test_site_snippets.py`). AGENTS.md now says to regenerate the site. No
`src/` change.

## New navigation

Overview · Quickstart · Concepts · Integrate (children: new server, existing
server, without MCP) · Identity · Storage · Prompts · Reference · Walkthroughs ·
Status · GitHub

The issue suggested longer names (Identity, Storage, Reference, Status). The
nav labels are shorter so the nav fits on one header row. The page titles keep
the full names: "Identity and multi-tenant auth", "Storage and operations",
"Tool and error reference", and "Status and compatibility".

**Redirect stubs:** each stub uses a meta refresh plus a canonical link. None
is in the nav, the sitemap, or the llms files.

| Old | New |
| --- | --- |
| `setup.html` | `quickstart.html` |
| `authorization.html` | `identity.html` |
| `usage.html` | `walkthroughs.html` |
| `caching.html` | `storage.html` |
| `operations.html` | `storage.html` |

**Where the sibling PR docs went:**

| Sibling | Now lives at |
| ------- | ------------ |
| #53 Telemetry (`on_call`) | Reference keeps the `ToolCallRecord` field table. Usage for each entry point is on the integrate pages. `custom_observer.py` is on `integrate-without-mcp.md#on-call` |
| #54 file cap | `storage.md#file-cap`. Concepts limits and Reference store options keep one line that links there |
| #56 `caching.md` | `storage.md#index-cache`. The page is now a redirect stub |
| #57 `operations.md` | `storage.md#erase`. One `ops_erase.py`, extended with an index-cache step and `assert`s. `ops_restore.py` is embedded there. Reference keeps the `purge`/`export` signatures |
| #58 tool schemas | The guidance and `custom_schemas.py` are on `integrate-without-mcp.md#schemas`. Reference keeps the signatures and a link |

## Acceptance criteria → tests

| Criterion | Test(s) |
| --------- | ------- |
| US1.1 llms.txt step 0 links the three paths | `test_site.py::test_llms_txt_step_zero` |
| US1.2-1.3, US2, US3, US4, US5, US6 page content | **Manual**: each fact checked against `src/` (see Deviations). `test_stored_metadata_keys_documented` covers US5.1 keys |
| US6 limitations use no "planned" language; US7.4 says Python 3.11, never 3.12; FR-003 install lines | `test_site.py::test_no_stale_claims` |
| US7.2 `memory-prompt.md` is byte-equal to `build_memory_prompt` | `test_site.py::test_memory_prompt_matches_library` |
| US7.3 HTTP auth example works against a live MCP client | **Manual**: live run, below |
| US8.1 build exits 0; a second build produces no diff | **Manual**: built twice, no diff |
| US8.2 header nav order | `test_site.py::test_header_nav_order` |
| US8.3 every slug has .html/.md and appears in sitemap, llms-full, and llms.txt | `test_site.py::test_every_page_is_generated_and_listed` |
| US8.4 internal links and `#fragment`s resolve | `test_site.py::test_internal_links_resolve` |
| US8.5 redirect stubs | `test_site.py::test_redirect_stubs` |
| US8.6 snippets run or are skipped with a reason | `test_site_snippets.py::test_every_snippet_is_classified_once`, `test_runnable_snippet_exits_zero`, `test_skipped_snippet_compiles` |
| US8.7 no stale outputs | `test_site.py::test_no_stale_outputs` |
| US8.8 version and Python floor match `pyproject.toml` | `test_site.py::test_version_consistency` |
| US9 sibling docs absorbed, not duplicated | **Manual**: content review against plan.md's move table. Partly enforced by `test_redirect_stubs` and `test_no_stale_outputs` |
| SC-002 nav usable, no horizontal scroll | **Manual**: screenshots, below |

## Architecture / ADR changes

- N/A. Docs and the build script only. The orchestrator confirmed that no ADR
  is needed.

## Deviations from spec

The pages follow `src/` (and the locked dependencies) where the spec's wording
was wrong:

- `index_max_bytes` counts the UTF-8 bytes of each entry's path, metadata, and
  version. It does not count rendered JSON, which is what US5.3 said.
- Retry behavior differs between google-cloud-storage 2.x and 3.x (the locked
  version is 3.14.1). US5.5 assumed one behavior. `storage.md#retries` has a
  table.
- A persistent GCS outage raises an unmapped `google.api_core` `RetryError`
  after 120 s. The agent sees `internal`, not the transient
  `BackendUnavailableError` that US5.5 described. This is documented on
  storage.md and in the status limitations. It is a likely `src/` bug (see
  Follow-ups).

## Look closely at

- **`make check` now depends on committed generated output under `site/`.** If
  you change prompt wording, regenerate the site with
  `uv run scripts/build_site.py`. AGENTS.md says so.
- Install lines are deliberately unpinned. #55 (AIE-1294) rebases onto this PR
  and pins them.
- The Status page links to `CHANGELOG.md` and `docs/releasing.md`. Both links
  404 until #55 merges.
- The site-nav CSS changes go beyond `.subnav`: `overflow-x: auto` and tighter
  padding. Together they remove the horizontal scroll at widths of 800-1013px.
- Each redirect stub also has a `location.replace` script that keeps the
  `#fragment`.
- Ruff formats the Python blocks in the generated `site/*.md` files, so
  embedded snippets must already be ruff-formatted.

## Verification

- `make check`: 5810 passed, 18 skipped, 46 deselected.
- `uv run scripts/build_site.py` run twice: no diff.
- Screenshots at 1280px and 375px wide, for `integrate-without-mcp` and
  `storage`:
  `/private/tmp/claude-501/-Users-marksiebert-p-github-wenchang/d71009ad-5082-4053-99aa-1de3512e30b1/scratchpad/aie-1297-*.png`

### HTTP live run (US7.3)

`auth_http.py` ran unchanged against fake-gcs-server, driven by mcp 2.3.0's
streamable-HTTP client. google-cloud-storage was 3.14.1.

```
make -C <worktree> emulator-up        # reused the running wenchang-fake-gcs container, port 4443
uv run --directory <worktree> python scratchpad/make_bucket.py   # create bucket wenchang-auth-http
STORAGE_EMULATOR_HOST=http://localhost:4443 WENCHANG_BUCKET=wenchang-auth-http \
  uv run --directory <worktree> python site-src/snippets/auth_http.py   # Uvicorn on :8000
uv run --directory <worktree> python scratchpad/drive_http.py   # streamable_http_client -> /mcp, call_tool("write_file", ...)
```

| # | Case | Result |
| - | ---- | ------ |
| 1 | Tianlong + `X-Project-Id` writes `project` | ok, `scope: project`, version returned |
| 2 | Tianlong writes `organization` | `RestrictedScopeError`, `reason: role_required`, `required_roles: [admin, owner]` |
| 3 | Kuixing, no project header, writes `organization` | ok, `scope: organization` |
| 4 | Kuixing names `project` | `InvalidArgumentError`, `argument: scope`: "scope 'project' is not available in this session" |
| 5 | Bad token | `ResolverFailureError`: "Invalid or expired token" |

The objects in the bucket afterwards store the metadata keys `last-updated`,
`aliases` (JSON array), and `sources` (JSON array). This matches
`storage.md`. The "not run against a live MCP client" note has been removed.

## Follow-ups

- New ticket: map a google.api_core `RetryError` from `GcsStorage` to
  `BackendUnavailableError`, so that a persistent outage reaches the agent as
  transient rather than `internal`.
- #55 (AIE-1294) pins the install lines and adds `CHANGELOG.md` and
  `docs/releasing.md`.
