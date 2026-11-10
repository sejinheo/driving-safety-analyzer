"""Project-specific architecture rules that ruff and import-linter cannot check.

- Import bans and layer direction: import-linter (`uv run lint-imports`)
- print, bare/swallowed except, utcnow: ruff (T20, E722, S110, DTZ)
- Row-level loops and async endpoints: this file

Fix the code, not this test, when it fails.
"""

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[2] / "app"
API_DIR = APP_DIR / "presentation"

ROW_LOOP_METHODS = ("iter_rows", "map_elements")


def _py_files(root: Path) -> Iterator[Path]:
    if not root.exists():
        pytest.skip(f"{root} does not exist yet")
    yield from sorted(root.rglob("*.py"))


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _rel(path: Path) -> str:
    return str(path.relative_to(APP_DIR.parent))


def test_no_row_loop_methods() -> None:
    violations = [
        f"{_rel(path)}:{node.lineno} .{node.func.attr}()"
        for path in _py_files(APP_DIR)
        for node in ast.walk(_parse(path))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in ROW_LOOP_METHODS
    ]
    assert not violations, "use Polars expressions instead of row loops:\n" + "\n".join(
        violations
    )


def test_endpoints_are_sync_def() -> None:
    violations = [
        f"{_rel(path)}:{node.lineno} async def {node.name}"
        for path in _py_files(API_DIR)
        for node in ast.walk(_parse(path))
        if isinstance(node, ast.AsyncFunctionDef)
    ]
    assert not violations, "CPU-bound endpoints must be def, not async def:\n" + "\n".join(
        violations
    )
