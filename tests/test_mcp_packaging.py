"""The mcp extra is optional and the library core never imports it (AIE-1060, US2)."""

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
TIMEOUT = 60


def _run(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
        cwd=ROOT,
        check=False,
    )


def test_mcp_is_an_optional_and_dev_dependency_only() -> None:
    """pyproject declares mcp>=2.2,<3 as the mcp extra and in the dev group, and
    not as a core dependency (AIE-1060, US2.1).
    """
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())

    extra = [Requirement(r) for r in pyproject["project"]["optional-dependencies"]["mcp"]]
    core = [Requirement(r).name for r in pyproject["project"]["dependencies"]]
    dev = [Requirement(r) for r in pyproject["dependency-groups"]["dev"]]

    assert len(extra) == 1
    assert extra[0].name == "mcp"
    assert {(s.operator, s.version) for s in extra[0].specifier} == {(">=", "2.2"), ("<", "3")}
    assert "mcp" not in core
    assert "mcp" in [r.name for r in dev]


def test_core_modules_do_not_import_mcp() -> None:
    """Importing wenchang and every submodule except wenchang.mcp leaves no mcp
    module loaded (AIE-1060, US2.2).
    """
    code = """
import importlib
import pkgutil
import sys

import wenchang

names = [m.name for m in pkgutil.walk_packages(wenchang.__path__, "wenchang.")]
names = [n for n in names if n != "wenchang.mcp" and not n.startswith("wenchang.mcp.")]
for name in names:
    importlib.import_module(name)
loaded = sorted(m for m in sys.modules if m == "mcp" or m.startswith("mcp."))
print(len(names), loaded)
"""
    result = _run(code)

    assert result.returncode == 0, result.stderr
    count, loaded = result.stdout.strip().split(" ", 1)
    assert int(count) > 10
    assert loaded == "[]"


def test_import_without_extra_names_the_extra() -> None:
    """With mcp unimportable, import wenchang.mcp raises ImportError naming
    wenchang[mcp] (AIE-1060, US2.3).
    """
    code = """
import sys

sys.modules["mcp"] = None
try:
    import wenchang.mcp
except ImportError as exc:
    print("IMPORT-ERROR:", exc)
else:
    print("IMPORTED")
"""
    result = _run(code)

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("IMPORT-ERROR:")
    assert "wenchang[mcp]" in result.stdout


def test_import_with_incompatible_mcp_says_so() -> None:
    """With mcp installed but lacking the 2.x server module, import wenchang.mcp
    raises an ImportError saying the installed mcp is incompatible
    (AIE-1060, US2.4).
    """
    code = """
import sys

import mcp

sys.modules["mcp.server.mcpserver"] = None
try:
    import wenchang.mcp
except ImportError as exc:
    print("IMPORT-ERROR:", exc)
else:
    print("IMPORTED")
"""
    result = _run(code)

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("IMPORT-ERROR:")
    assert "incompatible" in result.stdout
    assert "mcp>=2.2,<3" in result.stdout
