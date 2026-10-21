# /// script
# requires-python = ">=3.12"
# dependencies = ["markdown", "pygments"]
# ///
"""Build the project website: site-src/ -> site/.

site/ is generated output, committed as-is and served by GitHub Pages. Edit
site-src/ (one Markdown source per page, diagram.html, snippets/*.py) or this
script, then regenerate with `uv run scripts/build_site.py`. The files in
site-src/snippets/ are the Python examples embedded in the pages.
"""

# ruff: noqa: E501

import html
import json
import re
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "site-src"
SNIPS = SRC / "snippets"
OUT = ROOT / "site"
BASE = "https://msiebert.github.io/wenchang/"
REPO = "https://github.com/msiebert/wenchang"

PAGES = [
    {
        "slug": "index",
        "nav": "Overview",
        "title": "wenchang: persistent, self-organizing memory for AI agents",
        "description": "wenchang gives AI agents persistent memory: a virtual filesystem of markdown files in GCS, exposed as seven tools with optimistic concurrency and scope-based authorization.",
        "toc": False,
    },
    {
        "slug": "quickstart",
        "nav": "Quickstart",
        "title": "Quickstart: build a wenchang memory server",
        "description": "Install wenchang from git, build an MCP memory server with in-memory or GCS storage, connect Claude Code, and talk to your agent.",
        "toc": True,
    },
    {
        "slug": "usage",
        "nav": "Usage",
        "title": "What usage looks like: wenchang walkthroughs",
        "description": "Five walkthroughs with real tool calls and memory files: recall across sessions, filing by alias, forgetting a fact, a conflict with curated content, and refusing an account number.",
        "toc": True,
    },
    {
        "slug": "customize",
        "nav": "Customize",
        "title": "Customize wenchang: scopes, prompts, storage, telemetry",
        "description": "Configure identity and scope policy, prompt slots, store limits, storage backends, transport, embedding in an existing MCP server, telemetry, and conformance suites.",
        "toc": True,
    },
    {
        "slug": "reference",
        "nav": "Reference",
        "title": "Reference: wenchang tools, file format, and errors",
        "description": "The seven memory tools with exact parameters and returns, the file and path format, limits, the memory prompt resource, the error taxonomy, and known limitations.",
        "toc": True,
    },
]
SLUGS = [p["slug"] for p in PAGES]


def select(text: str, keep: str) -> str:
    """Keep the `keep` block kind ('md' or 'html') and drop the other."""
    drop = "html" if keep == "md" else "md"
    text = re.sub(rf"<!--{drop}-->.*?<!--/{drop}-->\n?", "", text, flags=re.S)
    text = re.sub(rf"<!--/?{keep}-->\n?", "", text)
    return text


def includes(text: str) -> str:
    def code(m: re.Match[str]) -> str:
        lang, name = m.group(1), m.group(2)
        body = (SNIPS / name).read_text().rstrip("\n")
        return f"```{lang}\n{body}\n```"

    text = re.sub(r"<!--include (\w+) ([\w.]+)-->", code, text)

    def raw(m: re.Match[str]) -> str:
        return (SRC / m.group(1)).read_text()

    return re.sub(r"<!--include-html ([\w.]+)-->", raw, text)


def md_twin(slug: str) -> str:
    text = select((SRC / f"{slug}.md").read_text(), "md")
    text = includes(text)
    text = re.sub(r"[ \t]*\{#[\w-]+\}[ \t]*$", "", text, flags=re.M)
    text = re.sub(r"^\{: [^}]*\}\n", "", text, flags=re.M)
    parts = re.split(r"(```.*?```)", text, flags=re.S)
    text = "".join(p if p.startswith("```") else re.sub(r"\n{3,}", "\n\n", p) for p in parts)
    text = text.strip() + "\n"
    url = BASE if slug == "index" else f"{BASE}{slug}.html"
    text += f"\n---\n\nHTML version: <{url}>\n"
    return text


def render_html_body(slug: str) -> tuple[str, list[dict]]:
    text = select((SRC / f"{slug}.md").read_text(), "html")
    text = includes(text)
    for s in SLUGS:
        text = re.sub(
            rf"\]\({s}\.md(#[\w-]+)?\)", lambda m, s=s: f"]({s}.html{m.group(1) or ''})", text
        )
    md = markdown.Markdown(
        extensions=["extra", "toc", "codehilite", "sane_lists"],
        extension_configs={
            "toc": {
                "permalink": "#",
                "permalink_title": "Link to this section",
                "toc_depth": "2-3",
            },
            "codehilite": {"guess_lang": False, "css_class": "highlight"},
        },
    )
    body = md.convert(text)
    body = re.sub(r"<table>", '<div class="table-wrap"><table>', body)
    body = re.sub(r"</table>", "</table></div>", body)
    tokens: list[dict] = []

    def walk(items: list[dict]) -> None:
        for t in items:
            tokens.append(t)
            walk(t.get("children", []))

    walk(md.toc_tokens)  # type: ignore[attr-defined]
    return body, tokens


def toc_html(tokens: list[dict]) -> str:
    top = [t for t in tokens if t["level"] == 2]
    out = ["<ul>"]
    for t in top:
        kids = [c for c in t.get("children", []) if c["level"] == 3]
        name = re.sub(r"<[^>]+>", "", t["name"])
        out.append(f'<li><a href="#{t["id"]}">{html.escape(html.unescape(name))}</a>')
        if kids:
            out.append("<ul>")
            for c in kids:
                cname = re.sub(r"<[^>]+>", "", c["name"])
                out.append(f'<li><a href="#{c["id"]}">{html.escape(html.unescape(cname))}</a></li>')
            out.append("</ul>")
        out.append("</li>")
    out.append("</ul>")
    return "\n".join(out)


JSONLD = {
    "@context": "https://schema.org",
    "@type": "SoftwareSourceCode",
    "name": "wenchang",
    "description": "Persistent, self-organizing memory for AI agents: a virtual filesystem of markdown files in GCS, exposed as tools with optimistic concurrency and scope-based authorization.",
    "codeRepository": REPO,
    "programmingLanguage": "Python",
    "license": "https://spdx.org/licenses/MIT.html",
    "version": "0.1.0",
    "url": BASE,
    "author": {"@type": "Person", "name": "Mark Siebert"},
}


def page_html(page: dict, body: str, tokens: list[dict]) -> str:
    slug = page["slug"]
    url = BASE if slug == "index" else f"{BASE}{slug}.html"
    desc = html.escape(page["description"], quote=True)
    title = html.escape(page["title"])
    nav = []
    for p in PAGES:
        href = "index.html" if p["slug"] == "index" else f"{p['slug']}.html"
        cur = ' aria-current="page"' if p["slug"] == slug else ""
        nav.append(f'<li><a href="{href}"{cur}>{p["nav"]}</a></li>')
    nav.append(f'<li><a href="{REPO}">GitHub</a></li>')
    toc = ""
    inline_toc = ""
    if page["toc"] and tokens:
        t = toc_html(tokens)
        toc = f'<aside class="toc toc-side" aria-label="On this page"><p class="toc-title">On this page</p>{t}</aside>'
        inline_toc = f'<nav class="toc toc-inline" aria-label="On this page"><details><summary>On this page</summary>{t}</details></nav>'
    jsonld = ""
    if slug == "index":
        jsonld = f'<script type="application/ld+json">\n{json.dumps(JSONLD, indent=2)}\n</script>\n'
    page_cls = "page has-toc" if toc else "page"
    md_href = f"{slug}.md"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{url}">
<link rel="alternate" type="text/markdown" href="{md_href}" title="Markdown version of this page">
<meta property="og:type" content="website">
<meta property="og:site_name" content="wenchang">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="{url}">
<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="{title}">
<meta name="twitter:description" content="{desc}">
<meta name="color-scheme" content="light dark">
<link rel="icon" href="favicon.svg" type="image/svg+xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&amp;family=JetBrains+Mono:wght@400;500&amp;display=swap">
<link rel="stylesheet" href="style.css">
<script src="site.js"></script>
{jsonld}</head>
<body>
<a class="skip-link" href="#main">Skip to content</a>
<header class="site-header">
<div class="inner">
<a class="brand" href="index.html">wenchang</a>
<nav class="site-nav" aria-label="Main">
<ul>
{chr(10).join(nav)}
</ul>
</nav>
</div>
</header>
<div class="{page_cls}">
<main id="main" class="content">
<p class="md-link"><a href="{md_href}" type="text/markdown">View as Markdown</a> (for AI agents; also <a href="llms.txt">llms.txt</a>)</p>
{inline_toc}
{body}
</main>
{toc}
</div>
<footer class="site-footer">
<div class="inner">
<p>MIT licensed. Version 0.1.0.</p>
<ul>
<li><a href="{REPO}">GitHub repository</a></li>
<li><a href="{REPO}/blob/main/LICENSE">License</a></li>
<li><a href="llms.txt">For agents: llms.txt</a></li>
<li><a href="{md_href}" type="text/markdown">This page as Markdown</a></li>
</ul>
</div>
</footer>
</body>
</html>
"""


def page_404() -> str:
    # Absolute paths: GitHub Pages serves this file for any missing URL depth.
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Page not found · wenchang</title>
<meta name="description" content="This page does not exist. Go to the wenchang documentation.">
<meta name="robots" content="noindex">
<meta name="color-scheme" content="light dark">
<link rel="icon" href="/wenchang/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&amp;family=JetBrains+Mono:wght@400;500&amp;display=swap">
<link rel="stylesheet" href="/wenchang/style.css">
<script src="/wenchang/site.js"></script>
</head>
<body>
<a class="skip-link" href="#main">Skip to content</a>
<header class="site-header">
<div class="inner">
<a class="brand" href="/wenchang/">wenchang</a>
<nav class="site-nav" aria-label="Main">
<ul>
<li><a href="/wenchang/">Overview</a></li>
<li><a href="/wenchang/quickstart.html">Quickstart</a></li>
<li><a href="/wenchang/usage.html">Usage</a></li>
<li><a href="/wenchang/customize.html">Customize</a></li>
<li><a href="/wenchang/reference.html">Reference</a></li>
<li><a href="{REPO}">GitHub</a></li>
</ul>
</nav>
</div>
</header>
<div class="page">
<main id="main" class="content">
<h1>Page not found</h1>
<p>That page does not exist. Try one of these:</p>
<ul>
<li><a href="/wenchang/">Overview</a></li>
<li><a href="/wenchang/quickstart.html">Quickstart</a></li>
<li><a href="/wenchang/usage.html">Usage walkthroughs</a></li>
<li><a href="/wenchang/customize.html">Customize</a></li>
<li><a href="/wenchang/reference.html">Reference</a></li>
<li><a href="/wenchang/llms.txt">llms.txt (for AI agents)</a></li>
</ul>
</main>
</div>
<footer class="site-footer">
<div class="inner">
<p>MIT licensed. Version 0.1.0.</p>
<ul>
<li><a href="{REPO}">GitHub repository</a></li>
<li><a href="/wenchang/llms.txt">For agents: llms.txt</a></li>
</ul>
</div>
</footer>
</body>
</html>
"""


def main() -> None:
    OUT.mkdir(exist_ok=True)
    twins = {}
    for page in PAGES:
        slug = page["slug"]
        body, tokens = render_html_body(slug)
        (OUT / f"{slug}.html").write_text(page_html(page, body, tokens))
        twins[slug] = md_twin(slug)
        (OUT / f"{slug}.md").write_text(twins[slug])
    full = [
        "# wenchang: full documentation\n",
        "> Persistent, self-organizing memory for AI agents. This file concatenates the five pages of https://msiebert.github.io/wenchang/ (overview, quickstart, usage, customize, reference) as Markdown. Page boundaries are marked with `<!-- page: NAME -->`.\n",
    ]
    for page in PAGES:
        full.append(f"\n<!-- page: {page['slug']}.md -->\n")
        full.append(twins[page["slug"]])
    (OUT / "llms-full.txt").write_text("\n".join(full))
    (OUT / "404.html").write_text(page_404())
    print("generated", [p["slug"] for p in PAGES])


if __name__ == "__main__":
    main()
