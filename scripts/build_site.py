# /// script
# requires-python = ">=3.12"
# dependencies = ["markdown", "pygments"]
# ///
"""Build the project website: site-src/ -> site/.

site/ is generated output, committed as-is and served by GitHub Pages. Edit
site-src/ (one Markdown source per page, style.css, site.js,
favicon.svg, seal.svg, lattice.svg, snippets/*.py) or this script, then regenerate with
`uv run scripts/build_site.py`. The files in site-src/snippets/ are the Python
examples embedded in the pages.
"""

# ruff: noqa: E501

import difflib
import html
import json
import re
from pathlib import Path

import markdown
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import JsonLexer

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
        "title": "wenchang: a memory store AI agents write to themselves",
        "description": "wenchang is a Python library that lets an AI agent decide what to remember, save it as markdown files in GCS, and read it back in later conversations.",
        "toc": False,
    },
    {
        "slug": "setup",
        "nav": "Setup",
        "title": "Set up the wenchang MCP server",
        "description": "Install wenchang, create a GCS bucket, write a server script, register it with Claude Code or another MCP client, and seed curated content.",
        "toc": True,
    },
    {
        "slug": "prompts",
        "nav": "Prompts",
        "title": "Customizing the wenchang prompts",
        "description": "The four prompt slots, the fixed prompt sections, and the product, tool_prefix, and source settings, and when to change each.",
        "toc": True,
    },
    {
        "slug": "authorization",
        "nav": "Authorization",
        "title": "Authorization in wenchang",
        "description": "Plug in your own authentication: credentials from the request, an identity resolver, and a scope policy, with a per-user and per-project example over HTTP.",
        "toc": True,
    },
    {
        "slug": "usage",
        "nav": "Examples",
        "title": "Examples: wenchang tool calls and memory files",
        "description": "Six walkthroughs of a novelist's writing assistant, with real tool calls and memory files: recall across sessions, a timeline append and an editing conflict, correcting a detail, cutting a subplot, house style from the system area, and refusing an account number.",
        "toc": True,
    },
    {
        "slug": "reference",
        "nav": "Reference",
        "title": "Reference: wenchang tools, file format, configuration, and errors",
        "description": "The seven memory tools with exact parameters and returns, the file and path format, configuration options, the error taxonomy, and known limitations.",
        "toc": True,
    },
]
SLUGS = [p["slug"] for p in PAGES]
ASSETS = ("style.css", "site.js", "favicon.svg", "seal.svg", "lattice.svg")

HANZI_FONT = "https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@700&text=%E6%96%87%E6%98%8C&display=swap"
FONTS = (
    "https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:ital,wght@0,400;0,500;0,600;1,400"
    "&amp;family=JetBrains+Mono:wght@400;500;600;700&amp;display=swap"
)

FENCE = re.compile(r"```(\w*)\n(.*?)\n```", re.S)
FACT = re.compile(r"^- \[(\w+)\] (.*)$")
CARD_PATH = re.compile(r"^[\w-]+/[\w-]+/[\w-]+/[\w.-]+\.md$")
JSON_LEXER = JsonLexer()
FORMATTER = HtmlFormatter(nowrap=True)


def select(text: str, keep: str) -> str:
    """Keep the `keep` block kind ('md' or 'html') and drop the other."""
    drop = "html" if keep == "md" else "md"
    text = re.sub(rf"<!--{drop}-->.*?<!--/{drop}-->\n?", "", text, flags=re.S)
    text = re.sub(rf"<!--/?{keep}-->\n?", "", text)
    return text


def includes(text: str) -> str:
    def code(m: re.Match[str]) -> str:
        lang, name = m.group(1), m.group(2)
        lines = (SNIPS / name).read_text().rstrip("\n").split("\n")
        body = "\n".join(line for line in lines if not line.startswith(("# pyright:", "# ruff:")))
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


def parse_card(body: str) -> dict | None:
    """Parse a memory-file block (path, `key: value` metadata, `---`, fact lines)."""
    lines = body.split("\n")
    if not CARD_PATH.match(lines[0]) or "---" not in lines:
        return None
    sep = lines.index("---")
    meta = [tuple(line.split(": ", 1)) for line in lines[1:sep] if ": " in line]
    facts = []
    for line in lines[sep + 1 :]:
        m = FACT.match(line)
        facts.append((m.group(1), m.group(2)) if m else ("", line))
    return {"path": lines[0], "meta": meta, "facts": facts}


def raw_lines(card: dict) -> list[str]:
    facts = [f"- [{tag}] {text}" if tag else text for tag, text in card["facts"]]
    return [f"{key}: {value}" for key, value in card["meta"]] + ["---"] + facts


def line_html(raw: str) -> str:
    m = FACT.match(raw)
    if m:
        return f'<span class="tag tag-{m.group(1)}">[{m.group(1)}]</span> {html.escape(m.group(2))}'
    if raw == "---":
        return '<span class="rule">---</span>'
    if ": " in raw:
        key, value = raw.split(": ", 1)
        return f'<span class="k">{html.escape(key)}:</span> {html.escape(value)}'
    return html.escape(raw)


def card_html(card: dict, other: dict | None, kind: str) -> str:
    """Render a memory file as a listing, or as a diff against `other` for an after card."""
    new = raw_lines(card)
    rows: list[tuple[str, str]] = []
    if kind == "after":
        old = raw_lines(other) if other else []
        ops = difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes()
        for op, i1, i2, j1, j2 in ops:
            if op == "equal":
                rows += [("", line) for line in new[j1:j2]]
                continue
            rows += [("-", line) for line in old[i1:i2]]
            rows += [("+", line) for line in new[j1:j2]]
    else:
        rows = [("", line) for line in new]
    items = []
    for sign, raw in rows:
        state = {"+": "added", "-": "removed"}.get(sign, "")
        hint = f'<span class="vh">{state}: </span>' if state else ""
        items.append(
            f'<li class="{state}"><span class="gutter" aria-hidden="true">{sign}</span>'
            f'<span class="fact">{hint}{line_html(raw)}</span></li>'
        )
    stat = ""
    if kind == "after":
        plus = sum(1 for sign, _ in rows if sign == "+")
        minus = sum(1 for sign, _ in rows if sign == "-")
        label = " new file" if other is None else ""
        stat = (
            f'<span class="stat"><span class="plus">+{plus}</span> '
            f'<span class="minus">-{minus}</span>{label}</span>'
        )
    if "/system/" in card["path"]:
        stat += ' <span class="pill pill-red">read only</span>'
    return (
        f'<figure class="memfile"><figcaption class="mf-path"><span>{html.escape(card["path"])}</span>{stat}</figcaption>'
        f'<ul class="mf-lines">{"".join(items)}</ul></figure>'
    )


def pre_html(code: str) -> str:
    return f'<pre class="highlight"><code>{highlight(code, JSON_LEXER, FORMATTER).rstrip()}</code></pre>'


def toolcall_html(body: str) -> str | None:
    """Render a `// name` JSON block as an agent call with its result."""
    lines = body.split("\n")
    title = re.match(r"//\s*(\w+(?:\(.*?\))?)\s*(.*)$", lines[0])
    if not title:
        if '"error"' not in body[:60]:
            return None
        return (
            '<div class="toolcall tc-err"><div class="tc-rhead"><span class="arrow">&larr;</span><span>error</span></div>'
            f"{pre_html(body)}</div>"
        )
    name, note = title.group(1), title.group(2)
    rest = lines[1:]
    split = next((i for i, line in enumerate(rest) if line.startswith("// result")), None)
    if split is not None:
        call = "\n".join(rest[:split]).strip()
        result = "\n".join(rest[split + 1 :]).strip()
        rnote = rest[split].removeprefix("// result").lstrip(": ")
    elif "(" in name:
        call, result, rnote = "", "\n".join(rest).strip(), ""
    else:
        call, result, rnote = "\n".join(rest).strip(), "", ""
    err = '"error"' in result[:60]
    note_html = f'<span class="tc-note">{html.escape(note)}</span>' if note else ""
    out = [
        f'<div class="toolcall{" tc-err" if err else ""}"><div class="tc-head">'
        f'<span class="arrow">&rarr;</span><code>{html.escape(name)}</code>{note_html}</div>'
    ]
    if call:
        out.append(pre_html(call))
    if result or rnote:
        label = "error" if err else "result"
        if rnote:
            label += f": {html.escape(rnote)}"
        out.append(
            f'<div class="tc-rhead"><span class="arrow">&larr;</span><span>{label}</span></div>'
        )
        if result:
            out.append(pre_html(result))
    out.append("</div>")
    return "".join(out)


def stash_blocks(text: str) -> tuple[str, dict[str, str]]:
    """Swap memory-file and tool-call fences for placeholders rendered after Markdown."""
    stash: dict[str, str] = {}
    found = []
    pos = 0
    pending: dict | None = None
    for m in FENCE.finditer(text):
        label = re.findall(r"Memory file, (before|after)", text[pos : m.start()])
        if label and label[-1] == "before":
            pending = None
        pos = m.end()
        card = parse_card(m.group(2)) if not m.group(1) else None
        if card:
            kind = label[-1] if label else "after"
            other = pending if kind == "after" else None
            found.append((m, "card", card, kind, other))
            pending = card if kind == "before" else None
        elif m.group(1) == "json":
            found.append((m, "tool", m.group(2), "", None))
    # A before card is rendered against its paired after card, so link them.
    for i, (m, kind, card, state, _other) in enumerate(found):
        if kind == "card" and state == "before":
            nxt = next((f for f in found[i + 1 :] if f[1] == "card"), None)
            if nxt and nxt[3] == "after" and nxt[4] is card:
                found[i] = (m, kind, card, state, nxt[2])
    out = []
    last = 0
    for m, kind, payload, state, other in found:
        rendered = card_html(payload, other, state) if kind == "card" else toolcall_html(payload)
        if rendered is None:
            continue
        key = f"WCHSTASH{len(stash)}X"
        stash[key] = rendered
        out.append(text[last : m.start()])
        out.append(f"\n\n{key}\n\n")
        last = m.end()
    out.append(text[last:])
    return "".join(out), stash


def story_classes(body: str) -> str:
    body = re.sub(
        r"<blockquote>\n<p><strong>User:",
        '<blockquote class="msg msg-user">\n<p><strong>User:',
        body,
    )
    body = re.sub(
        r"<blockquote>\n<p><strong>Agent</strong>",
        '<blockquote class="msg msg-agent">\n<p><strong>Agent</strong>',
        body,
    )
    body = re.sub(
        r"<p><strong>(Session [^<]*)</strong></p>",
        r'<p class="session"><strong>\1</strong></p>',
        body,
    )
    body = re.sub(r"<p><strong>(Memory )", r'<p class="mf-label"><strong>\1', body)
    body = body.replace('<li class="transcript">', "<li>")
    body = body.replace("<li><strong>You:</strong>", '<li class="msg-user"><strong>You:</strong>')
    body = body.replace(
        "<li><strong>Agent:</strong>", '<li class="msg-agent"><strong>Agent:</strong>'
    )
    body = body.replace(
        "<li><strong>Agent</strong> calls", '<li class="msg-call"><strong>Agent</strong> calls'
    )
    return re.sub(r'<ul>\n(<li class="msg-)', r'<ul class="transcript">\n\1', body)


def sessions(section: str) -> str:
    pat = re.compile(r'(<p class="session">.*?</p>\s*<ul class="transcript">.*?</ul>)', re.S)
    found = list(pat.finditer(section))
    if not found:
        return section
    inner = "".join(f'<div class="chargecard">{m.group(1)}</div>' for m in found)
    return (
        section[: found[0].start()]
        + f'<div class="sessions">{inner}</div>'
        + section[found[-1].end() :]
    )


TOOLS = (
    "get_memory_index",
    "read_file",
    "list_prefix",
    "write_file",
    "append_line",
    "replace_fact",
    "delete_file",
)
READS = TOOLS[:3]


def signature(name: str, part: str) -> str:
    """A one-line call signature built from the entry's parameter table."""
    table = re.search(r"<table>.*?</table>", part, re.S)
    params = []
    if table:
        for pname, req in re.findall(
            r"<tr>\s*<td><code>(\w+)</code></td>\s*<td>.*?</td>\s*<td>(.*?)</td>",
            table.group(0),
            re.S,
        ):
            params.append(pname if req.startswith("yes") else f'<span class="opt">{pname}?</span>')
    return f'<p class="sig"><span class="fn">{name}</span>({", ".join(params)})</p>'


def tool_cards(body: str) -> str:
    """Wrap each tool's reference entry in its own card."""
    out = []
    for part in re.split(r"(?=<h[23] id=)", body):
        m = re.match(r'<h3 id="(\w+)"', part)
        if m and m.group(1) in TOOLS:
            kind = "reads" if m.group(1) in READS else "writes"
            part = re.sub(
                r'(<h3 id="\w+">)(.*?)(<a class="headerlink")',
                rf'\1<span>\2</span><span class="pill pill-muted">{kind}</span>\3',
                part,
                count=1,
                flags=re.S,
            )
            part = part.replace("</h3>", "</h3>" + signature(m.group(1), part), 1)
            part = f'<section class="tool-card">{part}</section>'
        out.append(part)
    return "".join(out)


def render_html_body(slug: str) -> tuple[str, list[dict]]:
    text = select((SRC / f"{slug}.md").read_text(), "html")
    text = includes(text)
    stash: dict[str, str] = {}
    if slug == "usage":
        text, stash = stash_blocks(text)
    for s in SLUGS:
        text = re.sub(
            rf"\]\({s}\.md(#[\w-]+)?\)", lambda m, s=s: f"]({s}.html{m.group(1) or ''})", text
        )
    md = markdown.Markdown(
        extensions=["extra", "md_in_html", "toc", "codehilite", "sane_lists"],
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
    for key, rendered in stash.items():
        body = body.replace(f"<p>{key}</p>", rendered)
    if slug == "usage":
        body = story_classes(body)
    if slug == "reference":
        body = tool_cards(body)
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


def page_href(slug: str) -> str:
    return "index.html" if slug == "index" else f"{slug}.html"


def page_html(page: dict, body: str, tokens: list[dict]) -> str:
    slug = page["slug"]
    url = BASE if slug == "index" else f"{BASE}{slug}.html"
    desc = html.escape(page["description"], quote=True)
    title = html.escape(page["title"])
    nav = []
    for p in PAGES:
        href = page_href(p["slug"])
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
    pos = SLUGS.index(slug)
    links = []
    if pos > 0:
        prev = PAGES[pos - 1]
        links.append(
            f'<a rel="prev" href="{page_href(prev["slug"])}"><small>Previous</small>{prev["nav"]}</a>'
        )
    if pos < len(PAGES) - 1:
        nxt = PAGES[pos + 1]
        links.append(
            f'<a rel="next" href="{page_href(nxt["slug"])}"><small>Next</small>{nxt["nav"]}</a>'
        )
    page_nav = f'<nav class="page-nav" aria-label="Pages">{"".join(links)}</nav>'

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
<meta name="theme-color" media="(prefers-color-scheme: light)" content="#e5e9e1">
<meta name="theme-color" media="(prefers-color-scheme: dark)" content="#151c1d">
<link rel="icon" href="favicon.svg" type="image/svg+xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{FONTS}">
<link rel="stylesheet" href="{HANZI_FONT}">
<link rel="stylesheet" href="style.css">
<script src="site.js"></script>
{jsonld}</head>
<body class="page-{slug}">
<a class="skip-link" href="#main">Skip to content</a>
<header class="site-header">
<div class="inner">
<a class="brand" href="index.html"><span>wenchang</span></a>
<nav class="site-nav" aria-label="Main">
<ul>
{chr(10).join(nav)}
</ul>
</nav>
</div>
</header>
<div class="{page_cls}">
<main id="main" class="content">
<p class="md-link"><span class="path">wenchang/{md_href}</span> <a href="{md_href}" type="text/markdown">View as Markdown</a> (for AI agents; also <a href="llms.txt">llms.txt</a>)</p>
{inline_toc}
{body}
{page_nav}
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
    def url(p: dict) -> str:
        return "/wenchang/" + ("" if p["slug"] == "index" else page_href(p["slug"]))

    nav404 = "\n".join(f'<li><a href="{url(p)}">{p["nav"]}</a></li>' for p in PAGES)
    list404 = "\n".join(
        '<li><span class="gutter" aria-hidden="true"></span><span class="fact">'
        f'<a href="{url(p)}">{p["nav"]}</a></span></li>'
        for p in PAGES
    )
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
<meta name="theme-color" media="(prefers-color-scheme: light)" content="#e5e9e1">
<meta name="theme-color" media="(prefers-color-scheme: dark)" content="#151c1d">
<link rel="icon" href="/wenchang/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="{FONTS}">
<link rel="stylesheet" href="{HANZI_FONT}">
<link rel="stylesheet" href="/wenchang/style.css">
<script src="/wenchang/site.js"></script>
</head>
<body class="page-404">
<a class="skip-link" href="#main">Skip to content</a>
<header class="site-header">
<div class="inner">
<a class="brand" href="/wenchang/"><span>wenchang</span></a>
<nav class="site-nav" aria-label="Main">
<ul>
{nav404}
<li><a href="{REPO}">GitHub</a></li>
</ul>
</nav>
</div>
</header>
<div class="page">
<main id="main" class="content notfound">
<h1>Page not found</h1>
<p>Nothing is filed at this address. The pages below exist.</p>
<div class="nf-grid">
<figure class="memfile">
<figcaption class="mf-path"><span>get_memory_index()</span><span class="stat">404: no entry for this path</span></figcaption>
<ul class="mf-lines">
{list404}
<li><span class="gutter" aria-hidden="true"></span><span class="fact"><a href="/wenchang/llms.txt">llms.txt (for AI agents)</a></span></li>
</ul>
</figure>
</div>
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
        "> Persistent, self-organizing memory for AI agents. This file concatenates the pages of https://msiebert.github.io/wenchang/ (overview, setup, prompts, authorization, examples, reference) as Markdown. Page boundaries are marked with `<!-- page: NAME -->`.\n",
    ]
    for page in PAGES:
        full.append(f"\n<!-- page: {page['slug']}.md -->\n")
        full.append(twins[page["slug"]])
    (OUT / "llms-full.txt").write_text("\n".join(full))
    (OUT / "404.html").write_text(page_404())
    for name in ASSETS:
        (OUT / name).write_bytes((SRC / name).read_bytes())
    print("generated", [p["slug"] for p in PAGES])


if __name__ == "__main__":
    main()
