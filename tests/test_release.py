"""Releases are versioned, changelogged, and installed by pinned tag (AIE-1294)."""

import re
import tomllib
from pathlib import Path

import pytest

import wenchang

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = ROOT / "CHANGELOG.md"

GIT_URL_RE = re.compile(r"git\+https://github\.com/msiebert/wenchang(@v[^\s\"'`)<]*)?")
# An install of wenchang by name with no direct URL: optional flags, optional
# extras and version specifier, and no " @ " after the requirement.
BARE_INSTALL_RE = re.compile(
    r"(?:pip install|uv add|uv pip install|uv tool install)(?:\s+-\S+)*\s+(['\"]?)"
    r"wenchang(?:\[[^\]]*\])?(?![\[\w.-])(?:\s*[<>=!~]=?[^\s'\"`]*)?\1(?!\s*@)"
)
RELEASE_ASSET_RE = re.compile(
    r"releases/download/v([^/\s\"'`)<]+)/wenchang-([^-\s\"'`)<]+?)(?:-py3|\.tar\.gz)"
)


def _project_version() -> str:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    version: str = pyproject["project"]["version"]
    return version


def _changelog_lines() -> list[str]:
    assert CHANGELOG.is_file(), "CHANGELOG.md is missing at the repo root"
    return CHANGELOG.read_text().splitlines()


def _version_heading_index(lines: list[str], version: str) -> int:
    pattern = re.compile(rf"## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}")
    for i, line in enumerate(lines):
        if pattern.fullmatch(line):
            return i
    pytest.fail(f"CHANGELOG.md has no '## [{version}] - YYYY-MM-DD' heading")


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def test_package_version_matches_pyproject() -> None:
    """wenchang.__version__ equals pyproject [project].version (AIE-1294, US3.1)."""
    assert wenchang.__version__ == _project_version()


def test_version_is_plain_semver() -> None:
    """The project version is plain MAJOR.MINOR.PATCH (AIE-1294, US3.1)."""
    version = _project_version()
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), f"not plain semver: {version!r}"


def test_changelog_has_section_for_current_version() -> None:
    """CHANGELOG.md has a dated heading for the current version (AIE-1294, US3.2)."""
    _version_heading_index(_changelog_lines(), _project_version())


def test_changelog_has_unreleased_section_above_releases() -> None:
    """CHANGELOG.md has '## [Unreleased]' above the current version heading
    (AIE-1294, US3.2).
    """
    lines = _changelog_lines()
    assert "## [Unreleased]" in lines, "CHANGELOG.md has no '## [Unreleased]' heading"
    heading = _version_heading_index(lines, _project_version())
    assert lines.index("## [Unreleased]") < heading


def test_changelog_section_for_current_version_is_not_empty() -> None:
    """The current version's changelog section, extracted by the same rule the
    release workflow uses, has at least one non-blank line (AIE-1294, US3.2).
    """
    version = _project_version()
    lines = _changelog_lines()
    prefix = f"## [{version}] - "
    starts = [i for i, line in enumerate(lines) if line.startswith(prefix)]
    assert starts, f"CHANGELOG.md has no line starting with {prefix!r}"

    body: list[str] = []
    for line in lines[starts[0] + 1 :]:
        if line.startswith("## ") or (line.startswith("[") and "]: " in line):
            break
        body.append(line)

    assert any(line.strip() for line in body), f"CHANGELOG.md section for {version} is empty"


def test_changelog_has_link_reference_for_current_version() -> None:
    """CHANGELOG.md links the current version to its GitHub release (AIE-1294, US3.2)."""
    version = _project_version()
    expected = f"[{version}]: https://github.com/msiebert/wenchang/releases/tag/v{version}"
    assert expected in _changelog_lines(), f"CHANGELOG.md is missing {expected!r}"


@pytest.mark.parametrize(
    ("text", "flagged"),
    [
        ("pip install wenchang", True),
        ("pip install 'wenchang[mcp]'", True),
        ('pip install -U "wenchang[testing]"', True),
        ("pip install --upgrade wenchang>=0.1", True),
        ('uv add "wenchang==0.1.0"', True),
        ("uv tool install wenchang", True),
        ("uv pip install wenchang[mcp]", True),
        ('pip install "wenchang[mcp] @ git+https://github.com/msiebert/wenchang@v0.1.0"', False),
        ("pip install wenchang[mcp] @ git+https://github.com/msiebert/wenchang@v0.1.0", False),
        ("pip install wenchang @ https://example.com/wenchang-0.1.0-py3-none-any.whl", False),
        ("pip install wenchang-other", False),
    ],
)
def test_bare_install_pattern(text: str, flagged: bool) -> None:
    """The pin test flags installs of wenchang by name without a URL, with or without
    flags, extras, and version specifiers (AIE-1294, US3.3).
    """
    assert bool(BARE_INSTALL_RE.search(text)) is flagged


def test_install_instructions_pin_current_version() -> None:
    """Every install instruction in README.md, docs/releasing.md, site/llms.txt, and
    site-src/*.md pins the current release tag (AIE-1294, US3.3).
    """
    version = _project_version()
    named = [ROOT / "README.md", ROOT / "docs" / "releasing.md", ROOT / "site" / "llms.txt"]
    site_src = sorted((ROOT / "site-src").glob("*.md"))
    assert site_src, "site-src/*.md matched no files"
    files = named + site_src

    failures: list[str] = []
    git_url_matches = 0
    for path in files:
        rel = path.relative_to(ROOT)
        if not path.is_file():
            failures.append(f"{rel}: missing")
            continue
        text = path.read_text()

        for m in GIT_URL_RE.finditer(text):
            git_url_matches += 1
            if m.group(1) != f"@v{version}":
                failures.append(f"{rel}:{_line_number(text, m.start())}: {m.group(0)}")

        for m in BARE_INSTALL_RE.finditer(text):
            failures.append(f"{rel}:{_line_number(text, m.start())}: {m.group(0)}")

        for m in RELEASE_ASSET_RE.finditer(text):
            if m.group(1) != version or m.group(2) != version:
                failures.append(f"{rel}:{_line_number(text, m.start())}: {m.group(0)}")

    assert not failures, f"Install instructions not pinned to v{version}:\n" + "\n".join(failures)
    assert git_url_matches > 0, "no git+https://github.com/msiebert/wenchang install URL found"
