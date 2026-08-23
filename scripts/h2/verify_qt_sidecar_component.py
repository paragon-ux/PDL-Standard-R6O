from __future__ import annotations

"""Fail-closed Q01-Q24 qualification for the production Qt Quick Sidecar."""

import argparse
import ast
import hashlib
import json
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import PySide6
from PySide6.QtCore import QMetaObject, QObject, QPoint, Qt, qVersion
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest

from r6o.views.sidecar import EXPANDED_SIZE, STANDARD_SIZE, QtSidecarWindow, SidecarMode
from scripts.h2.verify_qt_sidecar_feasibility import (
    assert_capture,
    git_value,
    sha256_file,
    verify_asset_provenance,
)


ACCEPTED_BASE = "4928e73612048fac4b7486b24b7785a79d287e20"
DEFAULT_EVIDENCE = REPO_ROOT / "r6o_evidence" / "H2-C-QT-QUICK" / "qualification"
EXPECTED_QPA = {"windows": "windows", "x11": "xcb", "wayland": "wayland"}
CAPTURE_NAMES = {
    SidecarMode.STANDARD: "H2-C-STANDARD-SIDECAR.png",
    SidecarMode.EXPANDED: "H2-C-EXPANDED-SIDECAR.png",
}
QML_ROOT = REPO_ROOT / "r6o" / "views" / "sidecar" / "qml"
TOKENS_PATH = REPO_ROOT / "docs" / "h2" / "sidecar-qt" / "sidecar-qml-design-tokens-v2.json"
PROTECTED_PREFIXES = (
    "r6o/model_binding/",
    "r6o/viewmodel/",
    "r6o/contracts/",
    "r6o_evidence/R6O-1/",
)
PROTECTED_IMPORT_PREFIXES = ("r6o.model_binding", "r6o.viewmodel", "r6o.contracts")
REQUIRED_OBJECTS = (
    "sidecarSurface",
    "sidecarChrome",
    "sidecarTitle",
    "stageBadge",
    "activeDot",
    "activeLabel",
    "closeControl",
    "closeIcon",
    "artifactCard",
    "artifactTitle",
    "artifactBody",
    "artifactFlickable",
    "openEditorControl",
    "externalLinkIcon",
    "sourceLabel",
    "sourceValue",
    "copyControl",
    "reviewOptions",
    "reviewOptionsTitle",
    "actionsColumn",
    "tipText",
)
FORBIDDEN_TEXT = ("LOCK", "MOVE", "debug projection", "qualification", "Collapse")


def canonical_projection(*, long_body: bool = False) -> dict[str, Any]:
    body = """# Prompt

Build a task manager with:
- User authentication
- Project management
- Task tracking
- Due dates and reminders

Target tech stack: React + FastAPI + SQLite"""
    if long_body:
        body = "\n".join(f"overflow line {number:02d}" for number in range(80))
    return {
        "schema_version": "r6o-focus-projection-1",
        "session_id": "h2-c-qualification",
        "workspace_id": "h2-c-workspace",
        "model_revision": "model-revision-h2-c",
        "projection_id": "projection-h2-c-canonical",
        "interaction_state": "REVIEW_REQUIRED",
        "model_response": None,
        "stage": "PROMPT_REVIEW",
        "focus_kind": "PROMPT_REVIEW",
        "artifact": {
            "artifact_ref": "prompt:h2-c-opaque",
            "artifact_revision": "artifact-revision-h2-c",
            "artifact_kind": "prompt",
            "title": "Authoritative Prompt (PDL.md)",
            "media_type": "text/markdown",
            "body": body,
            "capabilities": {"copy": True, "open_external": True},
        },
        "actions": [
            {"action_id": "confirm_prompt", "label": "Confirm this prompt", "ordinal": 1, "kind": "SEMANTIC_MESSAGE", "canonical_review_text": "The prompt is confirmed.", "emphasis": "PRIMARY", "enabled": True},
            {"action_id": "change_task", "label": "Change the task", "ordinal": 2, "kind": "FREE_RESPONSE_FOCUS", "emphasis": "NORMAL", "enabled": True},
            {"action_id": "change_approach", "label": "Change the approach", "ordinal": 3, "kind": "FREE_RESPONSE_FOCUS", "emphasis": "NORMAL", "enabled": True},
            {"action_id": "something_else", "label": "Something else...", "ordinal": 4, "kind": "FREE_RESPONSE_FOCUS", "emphasis": "NORMAL", "enabled": True},
        ],
        "lifecycle": {
            "review_required": True,
            "terminal": False,
            "close_allowed": True,
            "handoff_ready": False,
            "terminal_disposition": None,
            "result_body": None,
            "authorized_handoff_artifacts": [],
        },
    }


def terminal_projection() -> dict[str, Any]:
    item = canonical_projection()
    item.update(
        interaction_state="TERMINAL",
        stage="CLOSED_SUCCESS",
        focus_kind="CLOSED",
        artifact=None,
        actions=[],
        lifecycle={
            "review_required": False,
            "terminal": True,
            "close_allowed": True,
            "handoff_ready": True,
            "terminal_disposition": "HOST_HANDOFF",
            "result_body": "complete",
            "authorized_handoff_artifacts": [],
        },
    )
    return item


def wait_for(predicate: Any, timeout_seconds: float = 3.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    app = QGuiApplication.instance()
    while time.monotonic() < deadline:
        assert app is not None
        app.processEvents()
        if predicate():
            return
        QTest.qWait(20)
    raise AssertionError("timed out waiting for Qt component qualification state")


def verify_protected_boundary() -> dict[str, Any]:
    changed = subprocess.run(
        ["git", "diff", "--name-only", ACCEPTED_BASE, "--"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    protected = [
        path for path in changed if any(path.replace("\\", "/").startswith(prefix) for prefix in PROTECTED_PREFIXES)
    ]
    if protected:
        raise AssertionError(f"protected R6O-1 paths changed: {protected}")

    sidecar_root = REPO_ROOT / "r6o" / "views" / "sidecar"
    forbidden_imports: list[str] = []
    for path in sidecar_root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        forbidden_imports.extend(
            f"{path.name}:{imported}"
            for imported in imports
            if any(imported == prefix or imported.startswith(prefix + ".") for prefix in PROTECTED_IMPORT_PREFIXES)
        )
    if forbidden_imports:
        raise AssertionError(f"Sidecar imports protected authority: {forbidden_imports}")
    return {"comparison_base": ACCEPTED_BASE, "protected_changed": [], "forbidden_imports": []}


def source_hashes() -> dict[str, str]:
    paths = sorted(QML_ROOT.glob("*.qml")) + [TOKENS_PATH]
    return {str(path.relative_to(REPO_ROOT)).replace("\\", "/"): sha256_file(path) for path in paths}


def qualify(target: str, evidence_root: Path, hold_seconds: float) -> dict[str, Any]:
    asset_hashes = verify_asset_provenance()
    protected = verify_protected_boundary()
    qml_hashes = source_hashes()
    actions: list[str] = []
    opened: list[str] = []
    copied: list[str] = []
    closed: list[bool] = []
    sidecar = QtSidecarWindow(
        source_presenter=lambda _artifact: ("Source: Workspace File", "/workspace/pdlt/PDL.md"),
        on_action=actions.append,
        on_open_editor=opened.append,
        on_copy=copied.append,
        on_close_view=lambda: closed.append(True),
    )
    try:
        if not sidecar.render(canonical_projection()):
            raise AssertionError("canonical active projection was not rendered")
        actual_qpa = QGuiApplication.platformName().lower()
        if actual_qpa != EXPECTED_QPA[target]:
            raise AssertionError(f"Qt backend {actual_qpa!r} != required {EXPECTED_QPA[target]!r}")
        if not sidecar.window.flags() & Qt.FramelessWindowHint:
            raise AssertionError("Qt Sidecar window is not frameless")
        if sidecar.window.color().alpha() != 0:
            raise AssertionError("Qt Sidecar top-level clear color is not transparent")
        if not bool(sidecar.window.property("assetsReady")):
            raise AssertionError("local fonts or SVG assets did not load")
        if str(sidecar.window.property("uiFamily")) != "Inter":
            raise AssertionError("Inter did not load from the local Sidecar asset")
        if str(sidecar.window.property("monoFamily")) != "JetBrains Mono":
            raise AssertionError("JetBrains Mono did not load from the local Sidecar asset")
        for object_name in REQUIRED_OBJECTS:
            sidecar.object(object_name)
        if [action["action_id"] for action in sidecar.bridge.actions] != [
            "confirm_prompt",
            "change_task",
            "change_approach",
            "something_else",
        ]:
            raise AssertionError("projected action count/order is not the canonical four-action set")
        if sidecar.window.findChild(QObject, "nativeScrollbar") is not None:
            raise AssertionError("unapproved native scrollbar is present")

        qml_source = "\n".join(path.read_text(encoding="utf-8") for path in QML_ROOT.glob("*.qml"))
        for forbidden in FORBIDDEN_TEXT:
            if forbidden in qml_source:
                raise AssertionError(f"forbidden production Sidecar UI found: {forbidden}")
        if "QtQuick.Controls" in qml_source:
            raise AssertionError("native Qt Quick Controls styling is present")

        sidecar.focus_primary_action()
        QTest.keyClick(sidecar.window, Qt.Key_Return)
        wait_for(lambda: actions == ["confirm_prompt"])
        QTest.mouseClick(sidecar.window, Qt.LeftButton, Qt.NoModifier, QPoint(336, 65))
        QTest.mouseClick(sidecar.window, Qt.LeftButton, Qt.NoModifier, QPoint(373, 274))
        wait_for(lambda: len(opened) == 1 and len(copied) == 1)
        if opened != ["prompt:h2-c-opaque"]:
            raise AssertionError(f"Open callback received wrong artifact reference: {opened}")
        if not copied[0].startswith("# Prompt"):
            raise AssertionError("Copy callback did not receive projected artifact body")

        platform_dir = evidence_root / target
        platform_dir.mkdir(parents=True, exist_ok=True)
        modes: dict[str, Any] = {}
        for mode, size in ((SidecarMode.STANDARD, STANDARD_SIZE), (SidecarMode.EXPANDED, EXPANDED_SIZE)):
            sidecar.set_mode(mode)
            wait_for(lambda size=size: (sidecar.window.width(), sidecar.window.height()) == size)
            if mode is SidecarMode.STANDARD:
                if (sidecar.object("artifactCard").property("x"), sidecar.object("reviewOptions").property("x")) != (8.0, 418.0):
                    raise AssertionError("STANDARD composition is not artifact-left/options-right")
            else:
                if (sidecar.object("artifactCard").property("y"), sidecar.object("reviewOptions").property("y")) != (49.0, 408.0):
                    raise AssertionError("EXPANDED composition is not artifact-top/options-below")
                if sidecar.object("expandControl").property("visible") is not False:
                    raise AssertionError("EXPANDED mode exposes a visible collapse/expand control")
            if hold_seconds:
                QTest.qWait(round(hold_seconds * 1000))
            capture_path = platform_dir / CAPTURE_NAMES[mode]
            image = sidecar.capture(capture_path)
            modes[mode.value] = {
                **assert_capture(image, size),
                "capture": capture_path.name,
                "capture_sha256": sha256_file(capture_path),
            }

        sidecar.bridge.render(canonical_projection(long_body=True))
        flickable = sidecar.object("artifactFlickable")
        wait_for(
            lambda: float(flickable.property("contentHeight"))
            > float(flickable.property("height"))
        )
        if not QMetaObject.invokeMethod(sidecar.window, "scrollArtifactToBottom", Qt.DirectConnection):
            raise AssertionError("artifact overflow could not be scrolled")
        wait_for(lambda: float(flickable.property("contentY")) > 0)

        sidecar.bridge.render(terminal_projection())
        wait_for(lambda: not sidecar.window.isVisible())
        if closed:
            raise AssertionError("terminal dismissal incorrectly emitted View close")

        q_status: dict[str, bool | str] = {
            f"Q{number:02d}": True for number in range(1, 22)
        }
        q_status.update(
            Q22=True if target == "windows" else "QUALIFIED_BY_WINDOWS_JOB",
            Q23=True if target == "x11" else "QUALIFIED_BY_X11_JOB",
            Q24=True if target == "wayland" else "QUALIFIED_BY_WAYLAND_JOB",
        )
        report = {
            "schema_version": "r6o-h2-c-qt-component-1",
            "gate": "H2-C-QUALIFICATION",
            "status": "MECHANICAL_PASS_PENDING_FINAL_REVIEW",
            "human_visual_approval": "CONDITIONALLY_DELEGATED_TO_SOL_REVIEW",
            "overall_h2_pass_authorized": False,
            "real_codex_host_tested": False,
            "d2_implemented": False,
            "target": target,
            "runtime": {
                "os": platform.platform(),
                "python": platform.python_version(),
                "pyside6": PySide6.__version__,
                "qt": qVersion(),
                "qpa_platform": actual_qpa,
                "logical_dpi": sidecar.window.screen().logicalDotsPerInch(),
                "device_pixel_ratio": sidecar.window.devicePixelRatio(),
            },
            "source": {
                "branch": git_value("branch", "--show-current"),
                "head": git_value("rev-parse", "HEAD"),
                "tree": git_value("rev-parse", "HEAD^{tree}"),
            },
            "proof": {
                "production_framework": "PySide6 + Qt Quick/QML",
                "same_qml_all_platforms": True,
                "qml_and_token_hashes": qml_hashes,
                "asset_hashes": asset_hashes,
                "protected_boundary": protected,
                "keyboard_action_ids": actions,
                "open_callback_refs": opened,
                "copy_callback_count": len(copied),
                "terminal_dismissal_view_close_count": len(closed),
                "q01_q24": q_status,
                "q25_standard_human_comparison": "PENDING_SOL_SUBSTITUTE_REVIEW",
                "q26_expanded_human_comparison": "PENDING_SOL_SUBSTITUTE_REVIEW",
            },
            "modes": modes,
        }
        result_path = platform_dir / "component-result.json"
        result_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return report
    finally:
        sidecar.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=tuple(EXPECTED_QPA), required=True)
    parser.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--hold-seconds", type=float, default=0.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = qualify(args.platform, args.evidence_dir, args.hold_seconds)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
