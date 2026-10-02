"""Packaging tests for the wenchang.testing subpackage.

Covers AIE-1039, US9.1 through US9.7, and AIE-1047, US5.1, US5.2, US5.4.
"""

import ast
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any, cast

import pytest

import wenchang.testing
from wenchang.testing import ResolverConformance, TransportConformance

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = REPO_ROOT / "src" / "wenchang"
TESTING_DIR = PACKAGE_DIR / "testing"
CONFORMANCE_MODULE = TESTING_DIR / "resolver_conformance.py"
TRANSPORT_CONFORMANCE_MODULE = TESTING_DIR / "transport_conformance.py"

TRANSPORT_CONFORMANCE_WENCHANG_IMPORTS = frozenset(
    {"core", "errors", "file_format", "paths", "transport", "version_token"}
)

LINEAR_ID = re.compile(r"AIE-\d+")

SUITE_TEST_NAMES = frozenset(
    {
        "test_valid_credentials_resolve_to_identity",
        "test_valid_credentials_resolve_through_library_entry_point",
        "test_invalid_credentials_return_resolution_failure",
        "test_invalid_credentials_raise_permanent_resolver_failure_error",
        "test_valid_resolution_is_consistent",
        "test_invalid_resolution_is_consistent",
        "test_roles_are_known_to_scope_configuration",
        "test_granted_scopes_build_valid_paths",
        "test_system_area_is_read_only_in_every_scope",
        "test_own_entity_writes_follow_policy",
        "test_foreign_entity_writes_are_not_granted",
        "test_ungranted_scope_writes_are_not_granted",
    }
)

IMPORT_SCRIPT = """
import importlib
import json
import pkgutil
import sys

sys.modules["pytest"] = None
sys.modules["_pytest"] = None

try:
    import pytest
except ImportError:
    pass
else:
    raise SystemExit("pytest was not blocked")

import wenchang

imported = []
skipped = []
for info in pkgutil.walk_packages(wenchang.__path__, "wenchang."):
    if info.name == "wenchang.testing" or info.name.startswith("wenchang.testing."):
        skipped.append(info.name)
        continue
    importlib.import_module(info.name)
    imported.append(info.name)

print(json.dumps({"imported": imported, "skipped": skipped}))
"""


def _is_pytest_module(module: str) -> bool:
    return any(module == root or module.startswith(root + ".") for root in ("pytest", "_pytest"))


def _is_testing_module(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(prefix + ".")


def _forbidden_imports(tree: ast.AST) -> list[str]:
    """Return a description of each pytest or wenchang.testing import in the tree."""
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_pytest_module(alias.name) or _is_testing_module(
                    alias.name, "wenchang.testing"
                ):
                    found.append(f"line {node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            names = {alias.name for alias in node.names}
            module = node.module
            if node.level == 0:
                assert module is not None
                if (
                    _is_pytest_module(module)
                    or _is_testing_module(module, "wenchang.testing")
                    or (module == "wenchang" and "testing" in names)
                ):
                    found.append(f"line {node.lineno}: from {module} import ...")
            elif (module is None and "testing" in names) or (
                module is not None and _is_testing_module(module, "testing")
            ):
                dots = "." * node.level
                found.append(f"line {node.lineno}: from {dots}{module or ''} import ...")
    return found


def _pytest_marks(tree: ast.AST) -> list[str]:
    """Return a description of each pytestmark name or pytest.mark use in the tree."""
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "pytestmark":
            found.append(f"line {node.lineno}: pytestmark")
        elif (
            isinstance(node, ast.Attribute)
            and node.attr == "mark"
            and isinstance(node.value, ast.Name)
            and node.value.id == "pytest"
        ):
            found.append(f"line {node.lineno}: pytest.mark")
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module == "pytest"
            and any(alias.name == "mark" for alias in node.names)
        ):
            found.append(f"line {node.lineno}: from pytest import mark")
    return found


def _library_modules() -> list[Path]:
    return sorted(
        path for path in PACKAGE_DIR.rglob("*.py") if not path.is_relative_to(TESTING_DIR)
    )


def test_resolver_conformance_is_importable_and_not_collected() -> None:
    """ResolverConformance imports and has no Test name prefix (AIE-1039, US9.1)."""
    assert isinstance(ResolverConformance, type)
    assert not ResolverConformance.__name__.startswith("Test")


def test_pyproject_declares_testing_extra() -> None:
    """pyproject.toml declares a testing extra requiring pytest (AIE-1039, US9.2)."""
    with (REPO_ROOT / "pyproject.toml").open("rb") as f:
        data: dict[str, Any] = tomllib.load(f)

    extras = cast(dict[str, list[str]], data["project"].get("optional-dependencies", {}))

    assert extras.get("testing") == ["pytest>=8.3"]


@pytest.mark.parametrize(
    "source",
    [
        "import pytest",
        "import _pytest.fixtures",
        "from pytest import fixture",
        "from _pytest import mark",
        "import wenchang.testing",
        "import wenchang.testing.resolver_conformance",
        "from wenchang import testing",
        "from wenchang import core, testing",
        "from wenchang.testing import ResolverConformance",
        "from wenchang.testing.resolver_conformance import ResolverConformance",
        "from . import testing",
        "from .. import testing",
        "from .testing import ResolverConformance",
        "from .testing.resolver_conformance import ResolverConformance",
    ],
)
def test_import_scan_detects_forbidden_form(source: str) -> None:
    """The import scan flags every forbidden import form (AIE-1039, US9.3)."""
    assert _forbidden_imports(ast.parse(source))


@pytest.mark.parametrize(
    "source",
    [
        "import wenchang",
        "import pytest_cov",
        "from wenchang import core",
        "from wenchang.errors import ErrorCategory",
        "from . import paths",
        "from .scope import check_write",
        "from .testingutils import helper",
    ],
)
def test_import_scan_allows_other_imports(source: str) -> None:
    """The import scan does not flag unrelated imports (AIE-1039, US9.3)."""
    assert _forbidden_imports(ast.parse(source)) == []


def test_library_does_not_import_pytest_or_testing_package() -> None:
    """No module outside wenchang.testing imports pytest or wenchang.testing (AIE-1039, US9.3)."""
    modules = _library_modules()
    assert modules, f"no modules found under {PACKAGE_DIR}"

    violations = {
        str(path.relative_to(REPO_ROOT)): found
        for path in modules
        if (found := _forbidden_imports(ast.parse(path.read_text(), filename=str(path))))
    }

    assert violations == {}


def test_testing_package_cites_no_linear_ids() -> None:
    """No file under src/wenchang/testing/ matches AIE-\\d+ (AIE-1039, US9.5)."""
    files = sorted(
        path
        for path in TESTING_DIR.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )
    names = {path.name for path in files}
    assert {"__init__.py", "resolver_conformance.py"} <= names

    matches = {
        str(path.relative_to(REPO_ROOT)): LINEAR_ID.findall(path.read_text())
        for path in files
        if LINEAR_ID.search(path.read_text())
    }

    assert matches == {}


def test_library_imports_without_pytest() -> None:
    """Every module outside wenchang.testing imports with pytest blocked (AIE-1039, US9.6)."""
    result = subprocess.run(
        [sys.executable, "-c", IMPORT_SCRIPT],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    report = cast(dict[str, list[str]], json.loads(result.stdout))
    assert "wenchang.core" in report["imported"]
    assert "wenchang.testing" in report["skipped"]


@pytest.mark.parametrize(
    "source",
    [
        "pytestmark = pytest.mark.unit",
        "pytestmark: list[object] = []",
        "@pytest.mark.unit\ndef test_x() -> None: ...",
        "class A:\n    @pytest.mark.slow\n    def test_x(self) -> None: ...",
        "from pytest import mark",
    ],
)
def test_mark_scan_detects_marks(source: str) -> None:
    """The mark scan flags pytestmark and pytest.mark uses (AIE-1039, US9.7)."""
    assert _pytest_marks(ast.parse(source))


def test_mark_scan_allows_fixtures_and_fail() -> None:
    """The mark scan does not flag pytest.fixture, pytest.fail, or pytest.skip (AIE-1039, US9.7)."""
    # Split so the stop gate's skip-marker grep does not match this sample.
    skip_call = "pytest." + "skip('x')"
    source = f"@pytest.fixture\ndef f() -> None:\n    {skip_call}\n    pytest.fail('y')\n"

    assert _pytest_marks(ast.parse(source)) == []


def test_resolver_conformance_defines_exactly_the_planned_tests() -> None:
    """ResolverConformance's test_* methods are exactly the twelve planned (AIE-1039, US9.4)."""
    names = sorted(name for name in dir(ResolverConformance) if name.startswith("test_"))

    assert names == sorted(SUITE_TEST_NAMES)


def test_conformance_module_applies_no_pytest_marks() -> None:
    """resolver_conformance.py has no pytestmark and no pytest.mark (AIE-1039, US9.7)."""
    assert CONFORMANCE_MODULE.is_file(), f"{CONFORMANCE_MODULE} does not exist"

    tree = ast.parse(CONFORMANCE_MODULE.read_text(), filename=str(CONFORMANCE_MODULE))

    assert _pytest_marks(tree) == []


def _transport_module_source() -> str:
    assert TRANSPORT_CONFORMANCE_MODULE.is_file(), f"{TRANSPORT_CONFORMANCE_MODULE} does not exist"
    return TRANSPORT_CONFORMANCE_MODULE.read_text()


def _disallowed_wenchang_imports(tree: ast.AST) -> list[str]:
    """Return each relative import or wenchang import outside the allowed modules."""
    allowed = TRANSPORT_CONFORMANCE_WENCHANG_IMPORTS
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if parts[0] == "wenchang" and (len(parts) != 2 or parts[1] not in allowed):
                    found.append(f"line {node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                found.append(f"line {node.lineno}: relative import")
                continue
            assert node.module is not None
            parts = node.module.split(".")
            if parts[0] != "wenchang":
                continue
            if len(parts) == 1:
                bad = [alias.name for alias in node.names if alias.name not in allowed]
            else:
                bad = [] if len(parts) == 2 and parts[1] in allowed else [node.module]
            if bad:
                found.append(f"line {node.lineno}: from {node.module} import {bad}")
    return found


def _imports_pytest(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(a.name == "pytest" for a in node.names):
            return True
    return False


def _is_version_operand(node: ast.expr) -> bool:
    if isinstance(node, ast.Name):
        return node.id.endswith("version")
    if isinstance(node, ast.Attribute):
        return node.attr.endswith("version")
    return False


def _is_exempt_call(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "type"
    return (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and (func.value.id == "client")
    )


def find_version_misuse(source: str) -> list[int]:
    """Return the line of each Compare, BinOp, Subscript, or Call using a version operand.

    A Call to `type` or to a method on the name `client` is exempt.
    """
    lines: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Compare):
            operands = [node.left, *node.comparators]
        elif isinstance(node, ast.BinOp):
            operands = [node.left, node.right]
        elif isinstance(node, ast.Subscript):
            operands = [node.value]
        elif isinstance(node, ast.Call) and not _is_exempt_call(node):
            operands = [*node.args, *(keyword.value for keyword in node.keywords)]
        else:
            continue
        if any(_is_version_operand(operand) for operand in operands):
            lines.append(node.lineno)
    return sorted(lines)


def test_transport_conformance_is_exported_and_not_collected() -> None:
    """wenchang.testing exports TransportConformance, not Test-prefixed (AIE-1047, US5.1)."""
    assert isinstance(TransportConformance, type)
    assert not TransportConformance.__name__.startswith("Test")
    assert {"ResolverConformance", "TransportConformance"} <= set(wenchang.testing.__all__)


def test_transport_conformance_imports_only_allowed_modules() -> None:
    """transport_conformance.py imports pytest and only the allowed wenchang modules.

    (AIE-1047, US5.2)
    """
    tree = ast.parse(_transport_module_source(), filename=str(TRANSPORT_CONFORMANCE_MODULE))

    assert _imports_pytest(tree)
    assert _disallowed_wenchang_imports(tree) == []


@pytest.mark.parametrize(
    "source",
    [
        "from wenchang.scope import check_write",
        "from wenchang.identity import Identity",
        "from wenchang.storage.memory import InMemoryStorage",
        "from wenchang.testing import ResolverConformance",
        "from wenchang import core, scope",
        "import wenchang",
        "import wenchang.storage",
        "from . import core",
        "from ..paths import build_path",
    ],
)
def test_transport_import_scan_detects_disallowed(source: str) -> None:
    """The transport import scan flags disallowed wenchang imports (AIE-1047, US5.2)."""
    assert _disallowed_wenchang_imports(ast.parse(source))


@pytest.mark.parametrize(
    "source",
    [
        "import pytest",
        "from collections.abc import Mapping",
        "from wenchang.core import MemoryFile",
        "from wenchang import paths, transport",
        "import wenchang.errors",
        "from wenchang.version_token import VersionToken",
        "from wenchang.file_format import FileMetadata",
    ],
)
def test_transport_import_scan_allows_permitted(source: str) -> None:
    """The transport import scan allows stdlib, pytest, and allowed modules (AIE-1047, US5.2)."""
    assert _disallowed_wenchang_imports(ast.parse(source)) == []


def test_transport_conformance_applies_no_pytest_marks() -> None:
    """transport_conformance.py has no pytestmark and no pytest.mark (AIE-1047, US5.2)."""
    tree = ast.parse(_transport_module_source(), filename=str(TRANSPORT_CONFORMANCE_MODULE))

    assert _pytest_marks(tree) == []


def test_transport_conformance_cites_no_linear_ids() -> None:
    """transport_conformance.py matches no Linear ID pattern (AIE-1047, US5.2)."""
    assert LINEAR_ID.findall(_transport_module_source()) == []


def test_transport_conformance_never_operates_on_version_tokens() -> None:
    """The token ast rule finds no misuse in transport_conformance.py (AIE-1047, US5.4, US2.6)."""
    assert find_version_misuse(_transport_module_source()) == []


@pytest.mark.parametrize(
    "source",
    [
        "a.version == b.version",
        "x.version[0]",
        "int(x.version)",
        "f(version=r.version)",
        "sorted(v.version)",
        "expected_version != None",
        "token + expected_version",
        "str(w.version)",
        "other.write_file(p, c, m, r.version, source=s)",
    ],
)
def test_version_scan_flags_misuse(source: str) -> None:
    """The token ast rule flags each listed violation (AIE-1047, US5.4, US2.6)."""
    assert find_version_misuse(source) == [1]


def test_version_scan_reports_line_numbers() -> None:
    """The token ast rule reports the offending line (AIE-1047, US5.4, US2.6)."""
    assert find_version_misuse("x = 1\ny = r.version + 'a'\nz = 2\n") == [2]


@pytest.mark.parametrize(
    "source",
    [
        "type(x.version)",
        "client.write_file(p, c, m, r.version, source=s)",
        "client.append_line(q, line, w.version, source=s)",
        "type(value.version) is str and value.version",
        "version_text = 'v'",
        "a.path == b.path",
    ],
)
def test_version_scan_allows_exemptions(source: str) -> None:
    """The token ast rule allows type() and client calls (AIE-1047, US5.4, US2.6)."""
    assert find_version_misuse(source) == []
