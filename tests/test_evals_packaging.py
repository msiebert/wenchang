"""The evals package stays dev-only and importable from anywhere (AIE-1170, US7, US8.2)."""

import ast
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path
from typing import Any

import pytest
from packaging.requirements import Requirement

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
TIMEOUT = 60


def _pyproject() -> dict[str, Any]:
    return tomllib.loads((ROOT / "pyproject.toml").read_text())


def test_wheel_ships_only_the_library() -> None:
    """The wheel's packages are exactly src/wenchang (AIE-1170, US7.1)."""
    pyproject = _pyproject()
    tool = pyproject["tool"]
    assert tool["hatch"]["build"]["targets"]["wheel"]["packages"] == ["src/wenchang"]


def test_built_wheel_contains_only_the_library(tmp_path: Path) -> None:
    """A wheel built from the repo holds wenchang and its metadata, and no
    evals or tests module (AIE-1170, US7.1).
    """
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is not on PATH")
    result = subprocess.run(
        [uv, "build", "--wheel", "--out-dir", str(tmp_path), str(ROOT)],
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    (wheel,) = tmp_path.glob("*.whl")
    tops = {name.split("/", 1)[0] for name in zipfile.ZipFile(wheel).namelist()}
    assert {t for t in tops if not t.endswith(".dist-info")} == {"wenchang"}


def test_editable_install_adds_repo_root() -> None:
    """dev-mode-dirs puts the repo root and src on sys.path (AIE-1170, US7.1)."""
    tool = _pyproject()["tool"]
    assert tool["hatch"]["build"]["dev-mode-dirs"] == [".", "src"]


def test_pyright_covers_evals() -> None:
    """Pyright strict includes the evals package (AIE-1170, US7.1)."""
    tool = _pyproject()["tool"]
    assert "evals" in tool["pyright"]["include"]


def test_yaml_is_a_dev_dependency_only() -> None:
    """pyyaml and types-pyyaml are in the dev group and nowhere else (AIE-1170, US7.1)."""
    pyproject = _pyproject()
    project = pyproject["project"]
    groups = pyproject["dependency-groups"]

    dev = {Requirement(r).name.lower() for r in groups["dev"]}
    core = {Requirement(r).name.lower() for r in project["dependencies"]}
    extras = {
        Requirement(r).name.lower()
        for reqs in project["optional-dependencies"].values()
        for r in reqs
    }

    assert {"pyyaml", "types-pyyaml"} <= dev
    assert not {"pyyaml", "types-pyyaml"} & (core | extras)


def test_evals_imports_from_any_working_directory(tmp_path: Path) -> None:
    """evals.reference_adopter imports in a subprocess whose cwd is outside the
    repo (AIE-1170, US7.2).
    """
    result = subprocess.run(
        [sys.executable, "-c", "import evals.reference_adopter as r; print(r.REFERENCE_PRODUCT)"],
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
        cwd=tmp_path,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "Mixpanel"


def test_tests_fixture_module_is_gone() -> None:
    """The reference adopter lives only in evals; the tests copy is deleted
    (AIE-1170, US7.3).
    """
    assert (ROOT / "evals" / "reference_adopter.py").is_file()
    assert not (ROOT / "tests" / "prompts_reference_adopter.py").exists()


def test_no_test_imports_the_old_fixture_module() -> None:
    """No test imports prompts_reference_adopter (AIE-1170, US7.3)."""
    offenders = [
        path.name
        for path in sorted((ROOT / "tests").rglob("*.py"))
        if "prompts_reference_adopter" in path.read_text() and path.name != Path(__file__).name
    ]
    assert offenders == []


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            names.add(node.module)
    return names


def test_library_never_imports_evals() -> None:
    """No module under src/wenchang imports evals (AIE-1170, US8.2)."""
    offenders = sorted(
        str(path.relative_to(ROOT))
        for path in (ROOT / "src" / "wenchang").rglob("*.py")
        if any(n == "evals" or n.startswith("evals.") for n in _imported_modules(path))
    )
    assert offenders == []
