# PR Review: AIE-1241 — Project website on GitHub Pages

## What changed & why

Adds a static project website for humans and agents, published to
https://msiebert.github.io/wenchang/. `scripts/build_site.py` (PEP 723, run
with `uv run scripts/build_site.py`) generates the committed `site/` from
`site-src/` (page sources and snippets): five HTML pages, a Markdown twin of
each, `llms.txt`, `llms-full.txt`, `robots.txt`, `sitemap.xml`, and a 404 page.
`.github/workflows/pages.yml` deploys `site/` via Actions on pushes to `main`
that touch `site/**`. `.gitignore` drops the stale mkdocs `/site` entry so the
generated output can be committed. `README.md` links the site and notes how to
regenerate it.

## Acceptance criteria → tests

No spec acceptance criteria or automated tests; this is docs and tooling with no
change to `src/`. Verification was by execution and script:

| Check | Result |
| ----- | ------ |
| `make check` | Passes (4076 passed, 18 skipped) |
| All 10 site Python snippets executed | In-memory server driven by a real stdio MCP client; GCS server exercised against fake-gcs-server; production GCS only constructed |
| Conformance snippet | Ran 66 tests |
| Internal links, Markdown twins, sitemap and `llms.txt` URLs | Checked by script |
| Pages served locally | Returned 200 |
| `claude mcp add --help` | Checked against the site's instructions |

Not verified: the Pages workflow has never run.

## Architecture / ADR changes

- N/A. No module, API, or storage change, so no ADR and no `ARCHITECTURE.md`
  update.

## Deviations from spec

- None.

## Look closely at

- `.github/workflows/pages.yml`: permissions, trigger paths, and the upload
  and deploy steps, since it could not be run before merge.
- `site/` is generated output; review `site-src/` and `scripts/build_site.py`,
  and confirm `uv run scripts/build_site.py` reproduces `site/` with no diff.
- The `.gitignore` change: removing `/site` is what lets `site/` be tracked.
- Snippet accuracy on the site against the current public API.

## Follow-ups

- After merge, set the repo's Pages source to "GitHub Actions" (Settings →
  Pages), then confirm the first workflow run succeeds.
- Found in `src/`, out of scope here: tool descriptions say "a Acme" for
  vowel-initial product names.
- Found in `src/`, out of scope here: the unknown-scope `InvalidArgumentError`
  message is missing a period before "This is normal coordination".
