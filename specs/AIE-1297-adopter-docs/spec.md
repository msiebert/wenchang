# Feature Specification: Restructure the docs site for adopters embedding wenchang

**Linear**: AIE-1297

**Feature Branch**: `AIE-1297-adopter-docs`

**Created**: 2026-10-30

**Status**: Draft

**Input**: The docs site assumes one integration path, a new stdio MCP server
for Claude Code. Adopters embedding wenchang in an existing service (their own
tool framework or MCP server) piece things together from scattered paragraphs.
Restructure the site around integration paths and add the pages adopters need:
integrate without MCP, `[mcp]` compatibility, multi-tenant identity, storage &
operations, status. Fix the smaller issues listed in the Linear issue.

## Sequencing (build happens after siblings merge)

This branch is built only after these PRs merge to `main`, in this order:
#53 (AIE-1296, `on_call` for `bind_tools`), #54 (AIE-1292,
`max_files_per_entity`), #56 (AIE-1293, index cache), #57 (AIE-1291,
purge/export), then AIE-1295 (`wenchang.schemas`). Pages describe all five as
shipped. Any site text those PRs add is absorbed into the new structure, not
duplicated. #55 (AIE-1294, tagged releases) merges **after** this branch and
rebases onto it.

- **Install lines are not pinned here.** Every install line uses the git URL
  form, `"wenchang[...] @ git+https://github.com/msiebert/wenchang"`, with no
  `@vX.Y.Z`. No bare `pip install wenchang` (no URL) appears anywhere, because
  #55's pin test rejects bare installs. #55 pins every line and owns its pin
  test.
- The Status page describes the release policy of ADR 0041 (#55): releases are
  `vX.Y.Z` git tags with GitHub Releases, no PyPI, Keep a Changelog, the 0.x
  SemVer rule. It links to `CHANGELOG.md` and `docs/releasing.md` on GitHub;
  those links 404 until #55 merges, which follows directly.

## Target navigation

Top nav (short labels; page titles carry the long names):

| # | Nav label | Slug | Page title (long name) |
| - | --------- | ---- | ---------------------- |
| 1 | Overview | `index` | (unchanged) |
| 2 | Quickstart | `quickstart` | Quickstart: a memory MCP server in Claude Code |
| 3 | Concepts | `concepts` | Concepts: paths, scopes, files, versions, limits |
| 4 | Integrate | `integrate` | Choose an integration path |
|   | (child) | `integrate-new-server` | Integrate: a new MCP server |
|   | (child) | `integrate-existing-server` | Integrate: an existing mcp 2.x server |
|   | (child) | `integrate-without-mcp` | Integrate without MCP |
| 5 | Identity | `identity` | Identity and multi-tenant auth |
| 6 | Storage | `storage` | Storage and operations |
| 7 | Prompts | `prompts` | Customizing the prompts |
| 8 | Reference | `reference` | Tool and error reference |
| 9 | Walkthroughs | `walkthroughs` | Walkthroughs |
| 10 | Status | `status` | Status and compatibility |

This matches the issue's suggested order. Labels are shortened to fit one
header row; the PR states this.

Old URLs `setup.html`, `authorization.html`, `usage.html`, `caching.html`,
`operations.html` become redirect stubs to `quickstart.html`,
`identity.html`, `walkthroughs.html`, `storage.html`, `storage.html`. Links into moved pages are retargeted
(e.g. `caching.md`'s `setup.md#seed` becomes `quickstart.md#seed`).

## User Scenarios & Testing

### User Story 1 - An adopter picks an integration path (P1)

1. **Given** `site/llms.txt`, **When** an agent reads "Instructions for AI
   agents", **Then** the first step is numbered 0 and asks which path applies
   (new MCP server, existing MCP server, no MCP), linking to
   `integrate-new-server.md`, `integrate-existing-server.md`, and
   `integrate-without-mcp.md`; the remaining steps are the new-server steps
   and say so.
2. **Given** the `integrate` page, **When** read, **Then** a table states when
   to use each path and links each child page; each child page shows links to
   its siblings.
3. **Given** the Overview's "How you use it", **When** read, **Then** it names
   the three paths and links the Integrate page.

### User Story 2 - Integrate without MCP (P1)

**Given** `integrate-without-mcp`, **When** read, **Then** it covers, matching
shipped code:

1. Installing the base package with no extra is enough
   (`"wenchang @ git+https://github.com/msiebert/wenchang"`).
1a. Tools are plain Python methods on `MemoryTools` (`tools.tools()` maps
   name to bound method; `tools.descriptions()` gives descriptions); nothing
   is registered anywhere until the adopter does it.
2. `bind_tools` resolves identity once and returns a `MemoryTools` for that
   identity, so a multi-tenant service binds per request (or per session),
   never once per process.
3. `wenchang.schemas.tool_schemas(product=None)` gives each tool's JSON Schema
   input, output, and error shape (AIE-1295); the adopter feeds those to their
   framework instead of writing arg models by hand.
4. Tool methods raise exceptions; `render_error(exc)` turns one into the
   payload to show the model; `render_result(value)` does the same for
   results.
5. Calls are synchronous and block on GCS round trips; the store and client
   must be safe to call from several threads; async hosts run calls in a
   worker thread.
6. `bind_tools(..., on_call=...)` delivers a `ToolCallRecord` per call
   (AIE-1296), with `request_id` `None` and the fields' direct-call meanings.
7. A runnable snippet binds per request with an in-memory store, dispatches a
   call by name with arguments from the schema, and renders a result and an
   error.

### User Story 3 - `[mcp]` extra compatibility (P1)

**Given** Quickstart's install section and both MCP integrate pages, **When**
read, **Then** a compatibility callout says the adapter targets
`mcp.server.mcpserver.MCPServer` from mcp 2.x (`mcp>=2.2,<3`), that FastMCP and
mcp 1.x servers do not work, and that `register_memory_tools` raises
`TypeError("server must be an MCPServer, not ...")` for any other server type.

### User Story 4 - Multi-tenant identity (P1)

**Given** the `identity` page, **When** read, **Then** before any worked
example it shows the chain credentials → `credentials_from_context` (MCP) or
the caller (direct) → resolver → `Identity` → path built from grants →
`ScopePolicy` gates writes, in domain-neutral terms, with a table mapping each
type to what it owns and to an org/project/user deployment. The novelist HTTP
example, behavior table, transports, and resolver testing follow.

### User Story 5 - Storage and operations (P1)

**Given** the `storage` page, **When** read, **Then** it covers, matching
shipped code:

1. Object key layout and the GCS custom metadata keys with their encodings:
   `description` (plain string, one line), `aliases` (JSON array of strings,
   ordered), `sources` (JSON array, sorted), `last-updated` (ISO 8601 UTC with
   `Z`). Tool results and the index render the last field as `last_updated`.
   The Reference/Concepts metadata table no longer gives `last_updated` as the
   stored key.
2. Deleting or exporting everything for one entity with
   `MemoryStore.purge` / `MemoryStore.export` (AIE-1291): operator-only, not
   agent tools; stop writers first; `PurgeIncompleteError`; export format and
   restore; GDPR erasure steps; bucket soft delete and object versioning keep
   deleted bytes for their retention window; the index cache needs a finite
   `ttl` for erasure.
3. Index cost: each session's index is capped at `index_max_bytes` (65536 by
   default), measured as the UTF-8 bytes of each entry's path, stored
   metadata keys and values, and version (not rendered JSON), and building it
   lists every object under every granted `{scope}/{entity_id}/` prefix unless
   an `IndexCache` (AIE-1293) serves it; how to configure the cache and its
   consistency requirements.
4. The per-entity file cap (AIE-1292): 500 by default, `None` disables, soft,
   creates only, `system/` excluded, `FileQuotaExceededError`.
5. Timeouts and retries: wenchang exposes no timeout or retry setting.
   `GcsStorage.get` retries a generation race (object replaced between its
   metadata and body reads) up to 3 times; every other call uses
   google-cloud-storage defaults: a 60 s timeout per request, and retry
   behavior that depends on the major version. On 2.x an unconditional `put`
   is not retried; on 3.x (the locked version) every call is retried.
   `put_if_version` and `delete_if_version` are retried on both. The page
   gives a 2.x/3.x table, verified against `src/wenchang/storage/gcs.py` and
   the installed library. Timeouts and unreachable backends that the storage
   layer maps surface as `BackendUnavailableError`; an outage that outlasts
   the retry deadline raises google.api_core's `RetryError`, which is not
   mapped, so the agent sees an `internal` error. The page and the Status
   limitations state this as it is today.
5a. `metadata_from_map` requires all four keys, so an object written out of
   band (e.g. `gcloud storage cp`) without them fails reads and indexing with
   `MetadataFormatError`; the page says to write through the store or set all
   four keys.
6. Bucket and IAM setup, and the one-bucket access model, moved or linked
   from Quickstart.

### User Story 6 - Status and compatibility (P1)

**Given** the `status` page, **When** read, **Then** it states version 0.1.0,
MIT, Python 3.11+, `mcp>=2.2,<3` for the extra; releases as `vX.Y.Z` git tags
with GitHub Releases, not on PyPI; the SemVer policy (public surface; 0.x
breaking → minor, else patch; prompt wording changes at least minor; tags never
moved once released); links to `CHANGELOG.md` and `docs/releasing.md`; and the
known limitations moved from Reference, each described as it is today (no
"planned" language, e.g. "there is no remote transport").

### User Story 7 - Smaller fixes (P2)

1. **Given** the nav, **When** read, **Then** the walkthroughs page's label and
   slug match (`Walkthroughs`, `walkthroughs`).
2. **Given** `site/memory-prompt.md`, **When** compared to
   `build_memory_prompt(PromptSlots(purpose="{purpose}",
   scope_guidance="{scope_guidance}", seed_areas="{seed_areas}",
   systems_of_record="{systems_of_record}"))`, **Then** they are equal byte
   for byte (no added newline); the Prompts page embeds that text in a "The
   full prompt" section inside a fence longer than any backtick run in the
   prompt, and links the raw file; llms.txt links it.
3. **Given** the HTTP auth example, **When** the build is done, **Then**
   `auth_http.py`, unchanged, has been run against fake-gcs-server
   (`make emulator-up`, `STORAGE_EMULATOR_HOST`, `WENCHANG_BUCKET`, bucket
   created) and driven with mcp 2.x's streamable-HTTP client through five
   cases: Tianlong with `X-Project-Id` writes `project` (ok); Tianlong writes
   `organization` (`RestrictedScopeError`, `role_required`); Kuixing with no
   project header writes `organization` (ok); Kuixing names `project`
   (`InvalidArgumentError`, not granted); a bad token
   (`ResolverFailureError`). The commands and output are recorded in
   `review-pr.md` and the "not run against a live MCP client" note is
   removed. If the run cannot be done, the note stays.
4. **Given** any page or llms.txt, **When** read, **Then** it says Python 3.11
   or newer (matching `requires-python`), never 3.12.

### User Story 8 - The site builds and stays consistent (P1)

1. **Given** `uv run scripts/build_site.py`, **When** run, **Then** it exits 0
   and regenerates `site/`; a second run produces no diff.
2. **Given** every generated page, **When** its header nav is read, **Then**
   labels are, in order, the 10 nav labels above plus `GitHub`.
3. **Given** the 13 slugs (`caching` and `operations` are folded into
   `storage` and are not slugs), **When** `site/` is checked, **Then** each has `.html` and `.md`,
   `sitemap.xml` lists exactly those 13 URLs (`index` as the site root
   `https://msiebert.github.io/wenchang/`),
   `llms-full.txt` has a `<!-- page: {slug}.md -->` marker for each in order,
   and `llms.txt` links each `.md`.
4. **Given** every relative `href` in `site/*.html`, **When** resolved,
   **Then** the target file exists and any `#fragment` names an `id` in the
   target page.
5. **Given** `setup.html`, `authorization.html`, `usage.html`,
   `caching.html` (#56), and `operations.html` (#57), **When**
   loaded, **Then** each redirects (meta refresh plus canonical link) to its
   new page and is not in the nav, sitemap, or llms files.
6. **Given** each Python snippet in `site-src/snippets/`, **When** run with
   the test interpreter, **Then** it exits 0, unless it is on an explicit skip
   list with a reason (needs GCS, needs a network server, or needs a
   third-party package not in the dev group); skipped snippets still
   `py_compile`; every snippet is on exactly one of the two lists.
   `integrate_direct.py` and `ops_erase.py` `assert` their outcomes (a
   rendered result and a rendered error; export contents, purge count, and
   an empty prefix afterwards).
7. **Given** `site/`, **When** listed, **Then** the `.html` files are exactly
   the 13 slugs, the `REDIRECTS` keys, and `404`; the `.md` files are exactly
   the 13 slugs, the `REDIRECTS` keys, and `memory-prompt`. The build deletes
   generated `.html`/`.md` outputs outside those sets.
8. **Given** the Status page and `site/llms.txt`, **When** their version and
   Python floor are read, **Then** they equal `pyproject.toml`'s `version`
   and `requires-python` floor.

### User Story 9 - Sibling docs are absorbed, not duplicated (P1)

1. **Given** the merged sibling docs (#53 Telemetry and #54 file-cap
   sections in `reference.md`, #56 `caching.md`, #57 `operations.md` and its
   snippets), **When** the build is done, **Then** each topic's operational
   guidance lives on exactly one page per plan.md's move table, other pages
   only link to it, `caching.md` and `operations.md` no longer exist as source
   pages, and there is one `ops_erase.py`.

### Edge Cases

- A page whose content a sibling PR already added (e.g. a purge or cache
  section added to `reference.md` or `setup.md`) is moved into the new page,
  not left in both.
- Anchor IDs that external links may use (`reference.md#embed`, `#bind`,
  `#limitations`, `#paths`) are allowed to move; only page-level redirects are
  provided.

## Requirements

- **FR-001**: Pages, slugs, and nav order as in "Target navigation".
- **FR-002**: Every scope item and smaller fix in AIE-1297 is addressed as in
  US1-US7, matching code on `main` after the five sibling PRs.
- **FR-003**: Install lines appear only in `site-src/*.md` and
  `site/llms.txt`, never in snippets or HTML includes. Each uses exactly
  `git+https://github.com/msiebert/wenchang` (no `.git`, no `@vX.Y.Z`). None is
  bare (no URL); this fixes the existing bare `pip install
  "wenchang[testing]"` lines (`authorization.md:61`, `reference.md:325`).
- **FR-004**: `scripts/build_site.py` supports nav children, redirect stubs,
  and the generated memory prompt; the `llms-full.txt` header lists pages from
  `PAGES` rather than a hard-coded string.
- **FR-005**: `tests/test_site.py` and `tests/test_site_snippets.py` cover
  US7.2, US7.4, US8.2-8.8, and FR-003; `make check` passes. `make check`
  thereby depends on committed generated output; the PR description says so.
- **FR-006**: No `src/` change.
- **FR-007**: AGENTS.md Commands gains a line: regenerate the site with
  `uv run scripts/build_site.py` after changing prompts or `site-src/`.

## Success Criteria

- **SC-001**: Every acceptance scenario is met; `make check` green; build is
  idempotent.
- **SC-002**: Desktop and 375px-wide screenshots of the Integrate and Storage
  pages show the header nav usable with no page-level horizontal scroll.
