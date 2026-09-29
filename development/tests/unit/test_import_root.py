"""The application imports through one root: its own directory (config.*, helpers.*, ...)."""
import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]
SCANNED = (
    REPO / "runtime",
    REPO / "development" / "tests",
    REPO / "development" / "tools",
    REPO / "development" / "simulator",
)


def _main_package_imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            names = [node.module or ""]
        else:
            continue
        for name in names:
            if name == "main" or name.startswith("main."):
                yield f"{path.relative_to(REPO)}:{node.lineno}: {name}"


def test_no_module_imports_through_the_main_package():
    """main.config.constants and config.constants load as two separate module objects.

    A test patch or runtime change to one copy would not reach code reading the other,
    and on a device main.* can resolve to the legacy main/ tree kept for rollback.
    """
    found = [
        hit
        for root in SCANNED
        for path in sorted(root.rglob("*.py"))
        if "node_modules" not in path.parts
        for hit in _main_package_imports(path)
    ]
    assert not found, "\n".join(found)
