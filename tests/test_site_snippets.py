"""Every docs snippet runs offline or is explicitly skipped with a reason
(AIE-1297, US8.6).
"""

import ast
import py_compile
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
SNIPPETS = ROOT / "site-src" / "snippets"
TIMEOUT = 60

RUNNABLE = frozenset(
    {
        "custom_bind.py",
        "custom_conformance.py",
        "custom_embed.py",
        "custom_observer.py",
        "custom_schemas.py",
        "custom_store.py",
        "integrate_direct.py",
        "ops_erase.py",
        "ops_restore.py",
        "prompt_extra.py",
        "prompt_slots.py",
    }
)
SKIPPED = {
    "auth_http.py": "needs GCS",
    "cache_redis.py": "needs a third-party package",
    "setup_seed.py": "needs GCS",
    "setup_server.py": "needs GCS",
}
SKIP_REASONS = {"needs GCS", "needs a network server", "needs a third-party package"}


def test_every_snippet_is_classified_once() -> None:
    """RUNNABLE and SKIPPED are disjoint and together cover site-src/snippets/*.py
    exactly, with an allowed reason for each skip (AIE-1297, US8.6).
    """
    on_disk = {p.name for p in SNIPPETS.glob("*.py")}
    assert not RUNNABLE & SKIPPED.keys()
    assert RUNNABLE | SKIPPED.keys() == on_disk
    assert set(SKIPPED.values()) <= SKIP_REASONS


@pytest.mark.parametrize("name", sorted(RUNNABLE))
def test_runnable_snippet_exits_zero(name: str, tmp_path: Path) -> None:
    """A runnable snippet exits 0 under the test interpreter (AIE-1297, US8.6)."""
    path = SNIPPETS / name
    assert path.is_file(), f"site-src/snippets/{name} does not exist"
    result = subprocess.run(
        [sys.executable, str(path)],
        cwd=tmp_path,
        timeout=TIMEOUT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"{name} exited {result.returncode}:\n{result.stderr}"


@pytest.mark.parametrize("name", ["integrate_direct.py", "ops_erase.py", "ops_restore.py"])
def test_outcome_snippets_assert(name: str) -> None:
    """An outcome snippet checks its result with at least one assert
    (AIE-1297, US8.6).
    """
    tree = ast.parse((SNIPPETS / name).read_text(), filename=name)
    assert any(isinstance(node, ast.Assert) for node in ast.walk(tree)), (
        f"{name} has no assert statement"
    )


@pytest.mark.parametrize("name", sorted(SKIPPED))
def test_skipped_snippet_compiles(name: str, tmp_path: Path) -> None:
    """A snippet that cannot run offline still compiles (AIE-1297, US8.6)."""
    py_compile.compile(str(SNIPPETS / name), cfile=str(tmp_path / f"{name}c"), doraise=True)
