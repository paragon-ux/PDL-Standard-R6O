from __future__ import annotations

"""Projection-only QObject bridge for the disposable Qt Sidecar View."""

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Property, QObject, Signal, Slot

from r6o.views.sidecar.fixture import CANONICAL_ACTIONS, CANONICAL_ARTIFACT_BODY
from r6o.views.sidecar.model import SidecarMode


TERMINAL_STAGES = frozenset({"CLOSED_SUCCESS", "CLOSED_CANCELLED"})
SourcePresenter = Callable[[dict[str, Any]], tuple[str, str]]
ActionCallback = Callable[[str], None]
CloseCallback = Callable[[], None]
OpenCallback = Callable[[str], None]
CopyCallback = Callable[[str], None]


class SidecarBridge(QObject):
    """Expose presentation-safe projection fields and approved View events."""

    modeChanged = Signal()
    presentationChanged = Signal()
    lastActionChanged = Signal()
    closeRequested = Signal()
    terminalDismissRequested = Signal()

    def __init__(
        self,
        mode: SidecarMode = SidecarMode.STANDARD,
        *,
        source_presenter: SourcePresenter | None = None,
        on_action: ActionCallback | None = None,
        on_close_view: CloseCallback | None = None,
        on_open_editor: OpenCallback | None = None,
        on_copy: CopyCallback | None = None,
    ) -> None:
        super().__init__()
        self._mode = SidecarMode.parse(mode)
        self._stage_label = "PROMPT REVIEW"
        self._artifact_title = "Authoritative Prompt (PDL.md)"
        self._artifact_body = CANONICAL_ARTIFACT_BODY
        self._source_label = "Source: Workspace File"
        self._source_value = "/workspace/pdlt/PDL.md"
        self._actions = [dict(action) for action in CANONICAL_ACTIONS]
        self._artifact_ref = ""
        self._capabilities = {"copy": True, "open_external": True}
        self._projection_id = "h2-c-canonical-feasibility"
        self._last_action_id = ""
        self._source_presenter = source_presenter or self._default_source_presenter
        self._on_action = on_action or (lambda _action_id: None)
        self._on_close_view = on_close_view or (lambda: None)
        self._on_open_editor = on_open_editor or (lambda _artifact_ref: None)
        self._on_copy = on_copy or (lambda _body: None)

    @staticmethod
    def _default_source_presenter(artifact: dict[str, Any]) -> tuple[str, str]:
        return "Source: Projected Artifact", str(artifact.get("artifact_ref") or "Opaque reference")

    @Property(str, notify=modeChanged)
    def mode(self) -> str:
        return self._mode.value

    @Property(str, notify=presentationChanged)
    def stageLabel(self) -> str:
        return self._stage_label

    @Property(str, constant=True)
    def statusLabel(self) -> str:
        return "ACTIVE"

    @Property(str, notify=presentationChanged)
    def artifactTitle(self) -> str:
        return self._artifact_title

    @Property("QVariantList", notify=presentationChanged)
    def actions(self) -> list[dict[str, object]]:
        return [dict(action) for action in self._actions]

    @Property("QVariantList", notify=presentationChanged)
    def artifactLines(self) -> list[str]:
        return self._artifact_body.splitlines()

    @Property(str, notify=presentationChanged)
    def sourceLabel(self) -> str:
        return self._source_label

    @Property(str, notify=presentationChanged)
    def sourceValue(self) -> str:
        return self._source_value

    @Property(bool, notify=presentationChanged)
    def canCopy(self) -> bool:
        return bool(self._capabilities.get("copy"))

    @Property(bool, notify=presentationChanged)
    def canOpenExternal(self) -> bool:
        return bool(self._capabilities.get("open_external"))

    @Property(str, notify=presentationChanged)
    def projectionId(self) -> str:
        return self._projection_id

    @Property(str, notify=lastActionChanged)
    def lastActionId(self) -> str:
        return self._last_action_id

    @Slot(str)
    def setMode(self, value: str) -> None:
        mode = SidecarMode.parse(value)
        if mode is self._mode:
            return
        self._mode = mode
        self.modeChanged.emit()

    def render(self, projection: dict[str, Any]) -> bool:
        if not isinstance(projection, dict):
            raise TypeError("Sidecar projection must be an object")
        if projection.get("schema_version") != "r6o-focus-projection-1":
            raise ValueError("unsupported Sidecar projection schema_version")
        projection_id = projection.get("projection_id")
        if not isinstance(projection_id, str) or not projection_id:
            raise ValueError("Sidecar projection requires a projection_id")
        stage = projection.get("stage")
        lifecycle = projection.get("lifecycle")
        if not isinstance(lifecycle, dict):
            raise ValueError("Sidecar projection lifecycle must be an object")
        if stage in TERMINAL_STAGES or lifecycle.get("terminal") is True:
            self.terminalDismissRequested.emit()
            return False
        if not isinstance(stage, str) or not stage:
            raise ValueError("active Sidecar projection requires a stage")
        artifact = projection.get("artifact")
        actions = projection.get("actions")
        if not isinstance(artifact, dict):
            raise ValueError("active Sidecar projection requires an artifact object")
        if not isinstance(actions, list) or not actions:
            raise ValueError("active Sidecar projection requires projected actions")
        normalized_actions: list[dict[str, object]] = []
        action_ids: set[str] = set()
        for action in actions:
            if not isinstance(action, dict):
                raise ValueError("projected Sidecar actions must be objects")
            action_id = action.get("action_id")
            label = action.get("label")
            ordinal = action.get("ordinal")
            kind = action.get("kind")
            if not isinstance(action_id, str) or not action_id:
                raise ValueError("projected action_id must be a non-empty string")
            if action_id in action_ids:
                raise ValueError(f"duplicate projected action_id: {action_id}")
            if not isinstance(label, str) or not label:
                raise ValueError(f"projected action {action_id!r} requires a label")
            if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 1:
                raise ValueError(f"projected action {action_id!r} requires a positive ordinal")
            if kind not in {"SEMANTIC_MESSAGE", "FREE_RESPONSE_FOCUS"}:
                raise ValueError(f"projected action {action_id!r} has an unsupported kind")
            action_ids.add(action_id)
            normalized_actions.append(
                {
                    "action_id": action_id,
                    "label": label,
                    "ordinal": ordinal,
                    "enabled": bool(action.get("enabled", True)),
                    "kind": kind,
                }
            )
        source_label, source_value = self._source_presenter(artifact)
        if not isinstance(source_label, str) or not isinstance(source_value, str):
            raise TypeError("source presenter must return two strings")
        self._stage_label = str(stage or "REVIEW").replace("_", " ")
        self._artifact_title = str(artifact.get("title") or "Authoritative Artifact")
        self._artifact_body = str(artifact.get("body") or "")
        self._artifact_ref = str(artifact.get("artifact_ref") or "")
        capabilities = artifact.get("capabilities")
        if not isinstance(capabilities, dict):
            raise ValueError("projected artifact capabilities must be an object")
        self._capabilities = {
            "copy": bool(capabilities.get("copy", False)),
            "open_external": bool(capabilities.get("open_external", False)),
        }
        self._source_label = source_label
        self._source_value = source_value
        self._actions = normalized_actions
        self._projection_id = projection_id
        self._last_action_id = ""
        self.presentationChanged.emit()
        self.lastActionChanged.emit()
        return True

    @Slot(str)
    def activateAction(self, action_id: str) -> None:
        current = next((action for action in self._actions if action["action_id"] == action_id), None)
        if current is None:
            raise ValueError(f"unprojected Sidecar action: {action_id!r}")
        if not bool(current["enabled"]):
            return
        self._last_action_id = action_id
        self.lastActionChanged.emit()
        self._on_action(action_id)

    @Slot()
    def requestOpen(self) -> None:
        if self._capabilities.get("open_external"):
            self._on_open_editor(self._artifact_ref)

    @Slot()
    def requestCopy(self) -> None:
        if self._capabilities.get("copy"):
            self._on_copy(self._artifact_body)

    @Slot()
    def requestClose(self) -> None:
        self.closeRequested.emit()

    def notify_closed(self) -> None:
        self._on_close_view()


# Compatibility alias for the already-frozen shell feasibility tests. It has
# no separate renderer or authority.
SidecarFeasibilityBridge = SidecarBridge
