from __future__ import annotations

"""Narrow presentation bridge used by the bounded Qt feasibility slice.

The feasibility bridge intentionally contains reference-sized presentation
data only. FocusProjection mapping and callback routing are added after the
three-platform shell is independently qualified.
"""

from PySide6.QtCore import Property, QObject, Signal, Slot

from r6o.views.sidecar.fixture import CANONICAL_ACTIONS, CANONICAL_ARTIFACT_BODY
from r6o.views.sidecar.model import SidecarMode


class SidecarFeasibilityBridge(QObject):
    modeChanged = Signal()
    lastActionChanged = Signal()
    closeRequested = Signal()

    def __init__(self, mode: SidecarMode = SidecarMode.STANDARD) -> None:
        super().__init__()
        self._mode = SidecarMode.parse(mode)
        self._last_action_id = ""

    @Property(str, notify=modeChanged)
    def mode(self) -> str:
        return self._mode.value

    @Property("QVariantList", constant=True)
    def actions(self) -> list[dict[str, object]]:
        return [dict(action) for action in CANONICAL_ACTIONS]

    @Property("QVariantList", constant=True)
    def artifactLines(self) -> list[str]:
        return CANONICAL_ARTIFACT_BODY.splitlines()

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

    @Slot(str)
    def activateAction(self, action_id: str) -> None:
        allowed = {str(action["action_id"]) for action in CANONICAL_ACTIONS}
        if action_id not in allowed:
            raise ValueError(f"unprojected Sidecar action: {action_id!r}")
        self._last_action_id = action_id
        self.lastActionChanged.emit()

    @Slot()
    def requestClose(self) -> None:
        self.closeRequested.emit()
