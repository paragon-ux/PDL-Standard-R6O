from __future__ import annotations

import json
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]

FORBIDDEN_IMPORTS = ("host.app", "session_engine", "mechanical_controller", "import host", "import runtime", "import controller", "from host", "from runtime", "from controller", "import workspace")


def test_viewmodel_has_no_runtime_or_controller_imports() -> None:
    for path in sorted((PACKAGE / "viewmodel").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_IMPORTS:
            assert forbidden not in text, f"{path.name} contains {forbidden!r}"


def test_no_view_technology_leaks_into_r6o() -> None:
    for path in sorted(PACKAGE.rglob("*.py")):
        if "tests" in path.parts:
            continue
        text = path.read_text(encoding="utf-8").lower()
        assert "tui" not in text and "sidecar" not in text, f"{path} leaks view technology"


def test_public_contracts_have_no_path_property() -> None:
    for path in sorted((PACKAGE / "contracts").glob("*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        properties = schema.get("properties") or {}
        for key in properties:
            assert "path" not in key.lower(), f"{path.name} exposes {key!r}"


def test_command_result_contract_includes_stale() -> None:
    schema = json.loads((PACKAGE / "contracts" / "viewmodel_command_result.schema.json").read_text(encoding="utf-8"))
    assert "STALE_PROJECTION" in schema["properties"]["result_type"]["enum"]

