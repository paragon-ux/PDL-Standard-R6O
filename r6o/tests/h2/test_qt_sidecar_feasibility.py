from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QMetaObject, Qt
from PySide6.QtTest import QTest

from r6o.views.sidecar import EXPANDED_SIZE, STANDARD_SIZE, QtSidecarWindow, SidecarMode
from r6o.views.sidecar.bridge import SidecarFeasibilityBridge
from scripts.h2.verify_qt_sidecar_feasibility import verify_asset_provenance


REPO_ROOT = Path(__file__).resolve().parents[3]
PROTECTED_IMPORT_PREFIXES = ("r6o.model_binding", "r6o.viewmodel", "r6o.contracts")


def test_sidecar_mode_sizes_are_frozen() -> None:
    assert SidecarMode.STANDARD.size == STANDARD_SIZE == (675, 300)
    assert SidecarMode.EXPANDED.size == EXPANDED_SIZE == (412, 806)
    with pytest.raises(ValueError, match="unsupported Sidecar mode"):
        SidecarMode.parse("IMPLEMENTATION_DECIDES")


def test_feasibility_bridge_is_presentation_only_and_fail_closed() -> None:
    bridge = SidecarFeasibilityBridge()
    assert bridge.mode == "STANDARD"
    assert [action["action_id"] for action in bridge.actions] == [
        "confirm_prompt", "change_task", "change_approach", "something_else"
    ]
    bridge.activateAction("something_else")
    assert bridge.lastActionId == "something_else"
    with pytest.raises(ValueError, match="unprojected Sidecar action"):
        bridge.activateAction("direct_controller_intent")


def test_local_asset_provenance_is_complete_and_hash_locked() -> None:
    hashes = verify_asset_provenance()
    assert set(hashes) == {
        "fonts/Inter-Regular.ttf",
        "fonts/Inter-SemiBold.ttf",
        "fonts/Inter-Bold.ttf",
        "fonts/INTER-LICENSE.txt",
        "fonts/JetBrainsMono-Regular.ttf",
        "fonts/JETBRAINS-MONO-OFL.txt",
        "icons/expand.svg",
        "icons/close.svg",
        "icons/external-link.svg",
    }


def test_sidecar_python_modules_do_not_import_protected_authority() -> None:
    sidecar_root = REPO_ROOT / "r6o" / "views" / "sidecar"
    for path in sidecar_root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        assert not any(
            imported == prefix or imported.startswith(prefix + ".")
            for imported in imports
            for prefix in PROTECTED_IMPORT_PREFIXES
        ), f"protected authority import in {path}"


def test_real_qml_window_supports_modes_assets_focus_and_keyboard() -> None:
    sidecar = QtSidecarWindow()
    sidecar.show()
    try:
        assert sidecar.window.flags() & Qt.FramelessWindowHint
        assert sidecar.window.color().alpha() == 0
        assert (sidecar.window.width(), sidecar.window.height()) == STANDARD_SIZE
        assert sidecar.window.property("assetsReady") is True
        assert sidecar.window.property("uiFamily") == "Inter"
        assert sidecar.window.property("monoFamily") == "JetBrains Mono"
        assert sidecar.object("expandIcon") is not None
        assert sidecar.object("closeIcon") is not None
        assert sidecar.object("externalLinkIcon") is not None

        assert QMetaObject.invokeMethod(sidecar.window, "focusFirstAction", Qt.DirectConnection)
        QTest.keyClick(sidecar.window, Qt.Key_Return)
        QTest.qWait(20)
        assert sidecar.bridge.lastActionId == "confirm_prompt"

        sidecar.set_mode(SidecarMode.EXPANDED)
        assert (sidecar.window.width(), sidecar.window.height()) == EXPANDED_SIZE
        assert sidecar.object("expandControl").property("visible") is False
    finally:
        sidecar.close()
