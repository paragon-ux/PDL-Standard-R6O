from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QMetaObject, QPoint, Qt
from PySide6.QtTest import QTest

from r6o.views.sidecar import QtSidecarWindow, SidecarMode
from r6o.views.sidecar.bridge import SidecarBridge


REPO_ROOT = Path(__file__).resolve().parents[3]
QML_ROOT = REPO_ROOT / "r6o" / "views" / "sidecar" / "qml"
TOKENS_PATH = REPO_ROOT / "docs" / "h2" / "sidecar-qt" / "sidecar-qml-design-tokens-v2.json"


def projection(
    *,
    stage: str = "PROMPT_REVIEW",
    body: str = "# Prompt\n\nBuild the projected system.",
    capabilities: dict[str, bool] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "r6o-focus-projection-1",
        "session_id": "session-h2-c",
        "workspace_id": "workspace-h2-c",
        "model_revision": "model-revision-1",
        "projection_id": f"projection-{stage.lower()}",
        "interaction_state": "REVIEW_REQUIRED",
        "model_response": None,
        "stage": stage,
        "focus_kind": stage,
        "artifact": {
            "artifact_ref": "prompt:opaque-reference",
            "artifact_revision": "artifact-revision-1",
            "artifact_kind": "prompt",
            "title": "Projected Prompt",
            "media_type": "text/markdown",
            "body": body,
            "capabilities": capabilities or {"copy": True, "open_external": True},
        },
        "actions": [
            {
                "action_id": "confirm_prompt",
                "label": "Confirm prompt",
                "ordinal": 1,
                "kind": "SEMANTIC_MESSAGE",
                "canonical_review_text": "The prompt is confirmed.",
                "emphasis": "PRIMARY",
                "enabled": True,
            },
            {
                "action_id": "change_task",
                "label": "Change the task",
                "ordinal": 2,
                "kind": "FREE_RESPONSE_FOCUS",
                "emphasis": "NORMAL",
                "enabled": True,
            },
            {
                "action_id": "change_approach",
                "label": "Change approach",
                "ordinal": 3,
                "kind": "FREE_RESPONSE_FOCUS",
                "emphasis": "NORMAL",
                "enabled": True,
            },
            {
                "action_id": "something_else",
                "label": "Something else...",
                "ordinal": 4,
                "kind": "FREE_RESPONSE_FOCUS",
                "emphasis": "NORMAL",
                "enabled": True,
            },
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


def terminal_projection() -> dict[str, object]:
    result = projection(stage="CLOSED_SUCCESS")
    result["interaction_state"] = "TERMINAL"
    result["artifact"] = None
    result["actions"] = []
    result["lifecycle"] = {
        "review_required": False,
        "terminal": True,
        "close_allowed": True,
        "handoff_ready": True,
        "terminal_disposition": "HOST_HANDOFF",
        "result_body": "complete",
        "authorized_handoff_artifacts": [],
    }
    return result


def test_projection_mapping_and_callbacks_remain_presentation_only() -> None:
    actions: list[str] = []
    opened: list[str] = []
    copied: list[str] = []
    bridge = SidecarBridge(
        source_presenter=lambda _artifact: ("Source: Workspace File", "PDL.md"),
        on_action=actions.append,
        on_open_editor=opened.append,
        on_copy=copied.append,
    )

    assert bridge.render(projection()) is True
    assert bridge.stageLabel == "PROMPT REVIEW"
    assert bridge.artifactTitle == "Projected Prompt"
    assert bridge.artifactLines == ["# Prompt", "", "Build the projected system."]
    assert bridge.sourceLabel == "Source: Workspace File"
    assert bridge.sourceValue == "PDL.md"
    assert bridge.canCopy is True
    assert bridge.canOpenExternal is True

    bridge.activateAction("something_else")
    bridge.requestOpen()
    bridge.requestCopy()
    assert actions == ["something_else"]
    assert opened == ["prompt:opaque-reference"]
    assert copied == ["# Prompt\n\nBuild the projected system."]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda item: item.update(schema_version="wrong"), "schema_version"),
        (lambda item: item.update(projection_id=""), "projection_id"),
        (lambda item: item.update(lifecycle=[]), "lifecycle"),
        (lambda item: item.update(artifact=None), "artifact"),
        (lambda item: item.update(actions=[]), "actions"),
        (lambda item: item["actions"][0].update(kind="DIRECT_CONTROLLER"), "kind"),
        (lambda item: item["actions"][0].update(enabled="false"), "enabled"),
        (lambda item: item["artifact"].update(artifact_ref=""), "artifact_ref"),
        (lambda item: item["artifact"].update(capabilities={"copy": "false", "open_external": False}), "booleans"),
    ],
)
def test_invalid_active_projection_fails_closed(mutation: object, message: str) -> None:
    item = projection()
    assert callable(mutation)
    mutation(item)
    with pytest.raises(ValueError, match=message):
        SidecarBridge().render(item)


def test_rejected_projection_cannot_replace_payload_under_old_permissions() -> None:
    opened: list[str] = []
    copied: list[str] = []
    bridge = SidecarBridge(on_open_editor=opened.append, on_copy=copied.append)
    accepted = projection(body="accepted body")
    bridge.render(accepted)

    rejected = projection(body="rejected body")
    rejected["artifact"]["artifact_ref"] = "prompt:rejected"
    rejected["artifact"]["capabilities"] = {"copy": "false", "open_external": True}
    with pytest.raises(ValueError, match="booleans"):
        bridge.render(rejected)

    bridge.requestOpen()
    bridge.requestCopy()
    assert opened == ["prompt:opaque-reference"]
    assert copied == ["accepted body"]


def test_disabled_and_unprojected_actions_do_not_cross_the_callback_boundary() -> None:
    received: list[str] = []
    item = projection()
    item["actions"][1]["enabled"] = False
    bridge = SidecarBridge(on_action=received.append)
    bridge.render(item)
    bridge.activateAction("change_task")
    assert received == []
    with pytest.raises(ValueError, match="unprojected Sidecar action"):
        bridge.activateAction("controller_intent")


def test_real_qml_renders_projection_and_routes_local_controls() -> None:
    actions: list[str] = []
    opened: list[str] = []
    copied: list[str] = []
    closed: list[bool] = []
    sidecar = QtSidecarWindow(
        source_presenter=lambda _artifact: ("Source: Workspace File", "PDL.md"),
        on_action=actions.append,
        on_open_editor=opened.append,
        on_copy=copied.append,
        on_close_view=lambda: closed.append(True),
    )
    try:
        assert sidecar.render(projection()) is True
        assert sidecar.object("artifactTitle").property("text") == "Projected Prompt"
        assert sidecar.object("sourceLabel").property("text") == "Source: Workspace File"
        assert sidecar.object("sourceValue").property("text") == "PDL.md"
        assert sidecar.object("stageBadge") is not None

        QTest.keyClick(sidecar.window, Qt.Key_Return)
        QTest.qWait(20)
        assert actions == ["confirm_prompt"]

        QTest.mouseClick(sidecar.window, Qt.LeftButton, Qt.NoModifier, QPoint(336, 65))
        QTest.mouseClick(sidecar.window, Qt.LeftButton, Qt.NoModifier, QPoint(373, 274))
        QTest.qWait(20)
        assert opened == ["prompt:opaque-reference"]
        assert copied == ["# Prompt\n\nBuild the projected system."]

        QTest.mouseClick(sidecar.window, Qt.LeftButton, Qt.NoModifier, QPoint(603, 23))
        QTest.qWait(20)
        assert sidecar.mode is SidecarMode.EXPANDED
        assert (sidecar.object("artifactCard").property("x"), sidecar.object("artifactCard").property("y")) == (8.0, 49.0)
        assert (sidecar.object("reviewOptions").property("x"), sidecar.object("reviewOptions").property("y")) == (8.0, 408.0)

        QTest.mouseClick(sidecar.window, Qt.LeftButton, Qt.NoModifier, QPoint(387, 23))
        QTest.qWait(20)
        assert sidecar.window.isVisible() is False
        assert closed == [True]
    finally:
        sidecar.close()


def test_single_long_artifact_line_wraps_and_scrolls_without_native_scrollbar() -> None:
    long_body = "one-unbroken-projected-line " * 120
    sidecar = QtSidecarWindow(SidecarMode.EXPANDED)
    try:
        sidecar.render(projection(body=long_body))
        flickable = sidecar.object("artifactFlickable")
        QTest.qWait(20)
        assert float(flickable.property("contentHeight")) > float(flickable.property("height"))
        assert QMetaObject.invokeMethod(sidecar.window, "scrollArtifactToBottom", Qt.DirectConnection)
        QTest.qWait(20)
        assert float(flickable.property("contentY")) > 0
        assert sidecar.window.findChild(type(flickable), "nativeScrollbar") is None
    finally:
        sidecar.close()


def test_custom_repeated_and_native_close_paths_notify_exactly_once_per_render() -> None:
    closed: list[bool] = []
    sidecar = QtSidecarWindow(on_close_view=lambda: closed.append(True))
    try:
        sidecar.render(projection())
        sidecar.bridge.requestClose()
        sidecar.bridge.requestClose()
        QTest.qWait(20)
        assert closed == [True]

        sidecar.render(projection())
        sidecar.window.close()
        QTest.qWait(20)
        assert closed == [True, True]
        assert sidecar.window.isVisible() is False
    finally:
        sidecar.close()
    assert closed == [True, True]


def test_terminal_projection_dismisses_without_emitting_view_close() -> None:
    closed: list[bool] = []
    sidecar = QtSidecarWindow(on_close_view=lambda: closed.append(True))
    try:
        sidecar.render(projection())
        assert sidecar.window.isVisible() is True
        assert sidecar.render(terminal_projection()) is False
        QTest.qWait(20)
        assert sidecar.window.isVisible() is False
        assert closed == []
    finally:
        sidecar.close()


def test_locked_tokens_and_forbidden_ui_are_structurally_enforced() -> None:
    tokens = json.loads(TOKENS_PATH.read_text(encoding="utf-8"))
    qml = (QML_ROOT / "DesignTokens.qml").read_text(encoding="utf-8")
    for color in tokens["colors"].values():
        assert color in qml
    for radius in tokens["radii_px"].values():
        assert f": {radius}" in qml

    component_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in QML_ROOT.glob("*.qml")
        if path.name != "DesignTokens.qml"
    )
    assert re.search(r'#[0-9A-Fa-f]{6}', component_source) is None
    for forbidden in ("LOCK", "MOVE", "debug projection", "qualification", "Collapse"):
        assert forbidden not in component_source
    assert "QtQuick.Controls" not in component_source
    review_action = (QML_ROOT / "ReviewAction.qml").read_text(encoding="utf-8")
    assert "keyboardFocusVisible" in review_action
    assert "border.color: control.activeFocus" not in review_action
