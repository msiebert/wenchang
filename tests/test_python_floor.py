"""The supported Python floor is 3.11 (AIE-1290)."""

import ast
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = ("src", "evals", "tests")


def _python_files() -> list[Path]:
    files: list[Path] = []
    for name in SOURCE_DIRS:
        files.extend(
            p for p in (ROOT / name).rglob("*.py") if ".venv" not in p.relative_to(ROOT).parts
        )
    return sorted(files)


def test_no_python_312_syntax_in_source_evals_or_tests() -> None:
    """No .py file under src/, evals/, or tests/ uses PEP 695 syntax; each file
    must parse under Python 3.11 grammar (AIE-1290, AC3).
    """
    failures: list[str] = []
    for path in _python_files():
        rel = path.relative_to(ROOT)
        try:
            ast.parse(path.read_text(), filename=str(rel), feature_version=(3, 11))
        except SyntaxError as exc:
            failures.append(f"{rel}:{exc.lineno}: {exc.msg}")

    assert not failures, "Python 3.12-only syntax found:\n" + "\n".join(failures)


def test_pyproject_targets_python_311() -> None:
    """pyproject sets requires-python, ruff target-version, and pyright
    pythonVersion to the 3.11 floor (AIE-1290, AC4).
    """
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())

    assert pyproject["project"]["requires-python"] == ">=3.11"
    assert pyproject["tool"]["ruff"]["target-version"] == "py311"
    assert pyproject["tool"]["pyright"]["pythonVersion"] == "3.11"
