from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]


def test_view_modules_do_not_import_protected_or_runtime_layers() -> None:
    forbidden = (
        "r6o.model_binding",
        "r6o.viewmodel",
        "host",
        "runtime",
        "controller",
        "providers",
    )
    for path in sorted((PACKAGE / "views").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        assert not [
            name
            for name in imported
            if any(name == item or name.startswith(item + ".") for item in forbidden)
        ], path


def test_views_do_not_read_workspace_or_artifact_paths() -> None:
    for path in sorted((PACKAGE / "views").rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        for forbidden in (
            "controller_state",
            "WorkerAdapter",
            "current.md",
            "workspace_path",
            "canonical_review_messages",
        ):
            assert forbidden not in source, f"{path} contains {forbidden!r}"


def test_tui_primary_surface_has_no_readline_or_repl_parser() -> None:
    paths = sorted((PACKAGE / "views" / "tui").glob("*.py"))
    sources = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    assert ".readline(" not in sources
    assert "while not self.controller.closed" in sources
    assert "get_terminal_size" in sources
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        assert not [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "input"
        ], path
