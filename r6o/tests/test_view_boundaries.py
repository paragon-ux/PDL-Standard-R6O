from __future__ import annotations

from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
VIEWS = PACKAGE / "views"
TRANSPORT = PACKAGE / "presentation_transport"

FORBIDDEN_IN_VIEWS = (
    "controller_state",
    "from r6o.model_binding",
    "import runtime",
    "import controller",
    "import workspace",
    "current.md",
    "subprocess",
    "os.system",
    "codex exec",
    "deepseek",
    "openai",
)
CANONICAL_EXAMPLES = ("Yes, that is what I mean.", "Confirm the plan and execute.")


def test_views_have_no_forbidden_dependencies_or_paths() -> None:
    for path in sorted(VIEWS.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_IN_VIEWS:
            assert forbidden not in text, f"{path} contains {forbidden!r}"
        for canonical in CANONICAL_EXAMPLES:
            assert canonical not in text, f"{path} hardcodes canonical semantic text"


def test_views_have_no_semantic_verbs() -> None:
    for path in sorted(TRANSPORT.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for verb in ("def accept", "def reject", "def revise", "def confirm", "def advance", "def execute", "def call_worker"):
            assert verb not in text, f"{path} exposes {verb}"


def test_viewmodel_and_binding_have_no_view_toolkit_imports() -> None:
    for folder in ("viewmodel", "model_binding"):
        for path in sorted((PACKAGE / folder).glob("*.py")):
            text = path.read_text(encoding="utf-8")
            assert "tkinter" not in text and "curses" not in text and "import r6o.views" not in text, path


def test_sidecar_has_no_editable_input() -> None:
    text = (VIEWS / "sidecar" / "app.py").read_text(encoding="utf-8")
    lines = text.splitlines()
    entry_lines = [i for i, line in enumerate(lines) if "tk.Entry(" in line]
    harness_index = next(i for i, line in enumerate(lines) if line.startswith("class HarnessShell"))
    panel_index = next(i for i, line in enumerate(lines) if line.startswith("class SidecarPanel"))
    assert len(entry_lines) == 1, f"expected exactly one Entry (harness composer), found {len(entry_lines)}"
    assert entry_lines[0] > harness_index > panel_index


def test_input_envelope_contract_unchanged() -> None:
    import json

    schema = json.loads((PACKAGE / "contracts" / "input_envelope.schema.json").read_text(encoding="utf-8"))
    assert schema["properties"]["schema_version"]["const"] == "r6o-input-envelope-1"
    assert "STRUCTURED_ACTION" in schema["properties"]["source"]["enum"]

