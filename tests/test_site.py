"""The committed docs site under site/ is complete and consistent (AIE-1297)."""

import re
import tomllib
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from wenchang.prompts import PromptSlots, build_memory_prompt

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
SITE_SRC = ROOT / "site-src"
SNIPPETS = SITE_SRC / "snippets"

SLUGS = [
    "index",
    "quickstart",
    "concepts",
    "integrate",
    "integrate-new-server",
    "integrate-existing-server",
    "integrate-without-mcp",
    "identity",
    "storage",
    "prompts",
    "reference",
    "walkthroughs",
    "status",
]
NAV_LABELS = [
    "Overview",
    "Quickstart",
    "Concepts",
    "Integrate",
    "Identity",
    "Storage",
    "Prompts",
    "Reference",
    "Walkthroughs",
    "Status",
]
REDIRECTS = {
    "setup": "quickstart",
    "authorization": "identity",
    "usage": "walkthroughs",
    "caching": "storage",
    "operations": "storage",
}
BASE = "https://msiebert.github.io/wenchang/"
SITE_PATH_PREFIX = "/wenchang/"
PLACEHOLDER_SLOTS = PromptSlots(
    purpose="{purpose}",
    scope_guidance="{scope_guidance}",
    seed_areas="{seed_areas}",
    systems_of_record="{systems_of_record}",
)
STALE_PHRASES = (
    "not run against a live MCP client",
    "Python 3.12",
    "3.12 or newer",
    "3.12+",
)
BARE_INSTALL_RE = re.compile(
    r"(?:pip install|uv add|uv pip install|uv tool install)(?:\s+-\S+)*\s+(['\"]?)"
    r"wenchang(?:\[[^\]]*\])?(?![\[\w.-])(?:\s*[<>=!~]=?[^\s'\"`]*)?\1(?!\s*@)"
)
LIMITATIONS_RE = re.compile(r"^## [^\n]*\{#limitations\}[^\n]*\n(.*?)(?=^## |\Z)", re.M | re.S)
UNSHIPPED_RE = re.compile(r"\bplanned\b|\bcoming soon\b|\bwill be added\b", re.IGNORECASE)
STORED_METADATA_KEYS = ("last-updated", "description", "aliases", "sources")


def _url(slug: str) -> str:
    return BASE if slug == "index" else f"{BASE}{slug}.html"


def _read(path: Path) -> str:
    assert path.is_file(), f"{path.relative_to(ROOT)} does not exist"
    return path.read_text()


class _PageParser(HTMLParser):
    """Collects nav link texts, link targets, element ids, and head metadata."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.nav_labels: list[str] = []
        self.nav_hrefs: list[str] = []
        self.links: list[str] = []
        self.ids: set[str] = set()
        self.meta_refresh: list[str] = []
        self.canonical: list[str] = []
        self._nav_depth = 0
        self._in_nav_link = False
        self._link_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v for k, v in attrs}
        if a.get("id"):
            self.ids.add(a["id"] or "")
        for key in ("href", "src"):
            value = a.get(key)
            if value is not None:
                self.links.append(value)
        if tag == "nav":
            classes = (a.get("class") or "").split()
            if self._nav_depth or "site-nav" in classes:
                self._nav_depth += 1
        if tag == "a" and self._nav_depth:
            self._in_nav_link = True
            self._link_text = []
            self.nav_hrefs.append(a.get("href") or "")
        if tag == "meta" and (a.get("http-equiv") or "").lower() == "refresh":
            self.meta_refresh.append(a.get("content") or "")
        if tag == "link" and "canonical" in (a.get("rel") or "").split():
            self.canonical.append(a.get("href") or "")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag == "nav":
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_nav_link:
            self.nav_labels.append("".join(self._link_text).strip())
            self._in_nav_link = False
        if tag == "nav" and self._nav_depth:
            self._nav_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._in_nav_link:
            self._link_text.append(data)


def _parse(path: Path) -> _PageParser:
    parser = _PageParser()
    parser.feed(_read(path))
    parser.close()
    return parser


def _refresh_target(content: str) -> str | None:
    for part in content.split(";"):
        key, sep, value = part.strip().partition("=")
        if sep and key.strip().lower() == "url":
            return value.strip().strip("'\"")
    return None


def _old_slug_link_re(old: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![\w-]){re.escape(old)}\.(?:html|md)\b")


def test_header_nav_order() -> None:
    """Every page's header nav lists the 10 top-level labels then GitHub
    (AIE-1297, US8.2).
    """
    expected = [*NAV_LABELS, "GitHub"]
    failures: list[str] = []
    for slug in SLUGS:
        path = SITE / f"{slug}.html"
        if not path.is_file():
            failures.append(f"{slug}.html: missing")
            continue
        labels = _parse(path).nav_labels
        if labels != expected:
            failures.append(f"{slug}.html: {labels}")
    assert not failures, f"header nav must be {expected}:\n" + "\n".join(failures)


def test_every_page_is_generated_and_listed() -> None:
    """Each slug has .html and .md outputs and is listed, in order, in the
    sitemap, llms-full.txt, and llms.txt (AIE-1297, US8.3).
    """
    missing = [
        f"{slug}{ext}"
        for slug in SLUGS
        for ext in (".html", ".md")
        if not (SITE / f"{slug}{ext}").is_file()
    ]
    assert not missing, f"missing generated pages: {missing}"

    locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", _read(SITE / "sitemap.xml"))
    assert locs == [_url(slug) for slug in SLUGS]

    markers = re.findall(r"<!-- page: ([\w-]+\.md) -->", _read(SITE / "llms-full.txt"))
    assert markers == [f"{slug}.md" for slug in SLUGS]

    llms = _read(SITE / "llms.txt")
    unlinked = [slug for slug in SLUGS if f"({BASE}{slug}.md)" not in llms]
    assert not unlinked, f"site/llms.txt does not link: {unlinked}"


def test_no_stale_outputs() -> None:
    """site/ holds exactly the current pages, redirect stubs, 404, and the
    memory prompt (AIE-1297, US8.7).
    """
    html = {p.stem for p in SITE.glob("*.html")}
    md = {p.stem for p in SITE.glob("*.md")}
    assert html == set(SLUGS) | set(REDIRECTS) | {"404"}
    assert md == set(SLUGS) | set(REDIRECTS) | {"memory-prompt"}


def _resolve(page: Path, href: str) -> tuple[Path, str] | None:
    """Map a link to (target file, fragment), or None if it is external."""
    if href.startswith(("http://", "https://", "//", "mailto:")) or href == "#":
        return None
    parts = urlsplit(href)
    path = parts.path
    if not path:
        return page, parts.fragment
    if path.startswith(SITE_PATH_PREFIX):
        path = path[len(SITE_PATH_PREFIX) :]
    if path == "" or path.endswith("/"):
        path += "index.html"
    return SITE / path, parts.fragment


def test_internal_links_resolve() -> None:
    """Every relative href/src in site/*.html names an existing file and any
    fragment names an id in the target page (AIE-1297, US8.4).
    """
    ids: dict[Path, set[str]] = {}

    def ids_of(path: Path) -> set[str]:
        if path not in ids:
            ids[path] = _parse(path).ids
        return ids[path]

    failures: list[str] = []
    for page in sorted(SITE.glob("*.html")):
        for href in _parse(page).links:
            resolved = _resolve(page, href)
            if resolved is None:
                continue
            target, fragment = resolved
            if not target.is_file():
                failures.append(f"{page.name}: {href} (no such file)")
            elif fragment and target.suffix == ".html" and fragment not in ids_of(target):
                failures.append(f"{page.name}: {href} (no id {fragment!r})")
    assert not failures, "broken internal links:\n" + "\n".join(failures)


def test_redirect_stubs() -> None:
    """Old pages redirect to their new page and are not listed anywhere
    (AIE-1297, US8.5).
    """
    for old, new in REDIRECTS.items():
        stub = _parse(SITE / f"{old}.html")
        targets = [_refresh_target(c) for c in stub.meta_refresh]
        assert f"{new}.html" in targets, f"{old}.html meta refresh: {stub.meta_refresh}"
        assert _url(new) in stub.canonical, f"{old}.html canonical: {stub.canonical}"

    listings = {name: _read(SITE / name) for name in ("sitemap.xml", "llms.txt", "llms-full.txt")}
    nav_hrefs = {slug: _parse(SITE / f"{slug}.html").nav_hrefs for slug in SLUGS}
    failures: list[str] = []
    for old in REDIRECTS:
        pattern = _old_slug_link_re(old)
        failures += [f"{name}: {old}" for name, text in listings.items() if pattern.search(text)]
        failures += [
            f"{slug}.html nav: {href}"
            for slug, hrefs in nav_hrefs.items()
            for href in hrefs
            if pattern.search(href)
        ]
    assert not failures, "old slugs still listed:\n" + "\n".join(failures)


def test_llms_txt_step_zero() -> None:
    """llms.txt's agent instructions start with step 0 linking the three
    integration paths (AIE-1297, US1.1).
    """
    llms = _read(SITE / "llms.txt")
    heading = "## Instructions for AI agents"
    assert heading in llms
    section = llms.split(heading, 1)[1].split("\n## ", 1)[0]
    items = re.findall(r"^\d+\..*?(?=^\d+\.|\Z)", section, flags=re.MULTILINE | re.DOTALL)
    assert items, "no numbered list in the agent instructions"
    first = items[0]
    assert first.startswith("0."), f"first instruction is not step 0: {first!r}"
    for page in (
        "integrate-new-server.md",
        "integrate-existing-server.md",
        "integrate-without-mcp.md",
    ):
        assert re.search(rf"\]\([^)\s]*\b{re.escape(page)}\)", first), (
            f"step 0 does not link {page}"
        )


def test_memory_prompt_matches_library() -> None:
    """site/memory-prompt.md is build_memory_prompt with placeholder slots,
    byte for byte (AIE-1297, US7.2).
    """
    path = SITE / "memory-prompt.md"
    hint = "regenerate the site with `uv run scripts/build_site.py`"
    assert path.is_file(), f"site/memory-prompt.md is missing; {hint}"
    assert path.read_bytes() == build_memory_prompt(PLACEHOLDER_SLOTS).encode(), (
        f"site/memory-prompt.md is out of date with wenchang.prompts; {hint}"
    )


def test_version_consistency() -> None:
    """The Status page and llms.txt state pyproject's version and Python floor
    (AIE-1297, US8.8).
    """
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    version: str = project["version"]
    floor = re.search(r">=\s*(\d+\.\d+)", project["requires-python"])
    assert floor is not None
    python = f"Python {floor.group(1)}"
    for path in (SITE_SRC / "status.md", SITE / "llms.txt"):
        text = _read(path)
        rel = path.relative_to(ROOT)
        assert version in text, f"{rel} does not state version {version}"
        assert python in text, f"{rel} does not state {python}"


def test_no_stale_claims() -> None:
    """Docs carry no stale Python floor, untested-client note, planned items,
    bare or .git installs, and snippets carry no install commands
    (AIE-1297, US7.4, US6, FR-003).
    """
    docs = [*sorted(SITE_SRC.glob("*.md")), SITE / "llms.txt"]
    failures: list[str] = []
    for path in docs:
        text = _read(path)
        rel = path.relative_to(ROOT)
        failures += [f"{rel}: {phrase!r}" for phrase in STALE_PHRASES if phrase in text]
        failures += [f"{rel}: bare install {m.group(0)!r}" for m in BARE_INSTALL_RE.finditer(text)]
        if "msiebert/wenchang.git" in text:
            failures.append(f"{rel}: 'msiebert/wenchang.git'")
    status = SITE_SRC / "status.md"
    if not status.is_file():
        failures.append("site-src/status.md: missing")
    else:
        section = LIMITATIONS_RE.search(status.read_text())
        if section is None:
            failures.append("site-src/status.md: no `## ... {#limitations}` section")
        else:
            failures += [
                f"site-src/status.md limitations: {m.group(0)!r}"
                for m in UNSHIPPED_RE.finditer(section.group(1))
            ]
    for path in sorted(SNIPPETS.glob("*.py")):
        text = path.read_text()
        rel = path.relative_to(ROOT)
        failures += [f"{rel}: {cmd!r}" for cmd in ("pip install", "uv add") if cmd in text]
    assert not failures, "stale claims:\n" + "\n".join(failures)


def test_stored_metadata_keys_documented() -> None:
    """The Storage page names every stored metadata key (AIE-1297, US5.1)."""
    text = _read(SITE_SRC / "storage.md")
    missing = [key for key in STORED_METADATA_KEYS if f"`{key}`" not in text]
    assert not missing, f"site-src/storage.md does not name: {missing}"
