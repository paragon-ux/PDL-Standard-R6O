from __future__ import annotations

"""Production Qt Quick shell for the disposable H2-C Sidecar View."""

import os
import sys
from pathlib import Path

from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QEventLoop,
    QMetaObject,
    QObject,
    Qt,
    QTimer,
    QUrl,
)
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow

from r6o.views.sidecar.bridge import (
    ActionCallback,
    CloseCallback,
    CopyCallback,
    OpenCallback,
    SidecarBridge,
    SourcePresenter,
)
from r6o.views.sidecar.model import SidecarMode


SIDECAR_ROOT = Path(__file__).resolve().parent
QML_ENTRYPOINT = SIDECAR_ROOT / "qml" / "Sidecar.qml"


def ensure_application() -> QGuiApplication:
    existing = QCoreApplication.instance()
    if existing is not None:
        if not isinstance(existing, QGuiApplication):
            raise RuntimeError("H2-C requires a QGuiApplication")
        return existing
    os.environ.setdefault("QT_SCALE_FACTOR", "1")
    os.environ.setdefault("QT_FONT_DPI", "96")
    return QGuiApplication(sys.argv[:1])


def _process_until(predicate: object, timeout_ms: int = 5000) -> None:
    app = ensure_application()
    elapsed = 0
    while elapsed < timeout_ms:
        app.processEvents(QEventLoop.AllEvents, 50)
        if callable(predicate) and bool(predicate()):
            return
        QTimer.singleShot(25, lambda: None)
        app.processEvents(QEventLoop.AllEvents, 25)
        elapsed += 25
    raise TimeoutError("Qt Sidecar did not reach the requested state")


class QtSidecarWindow:
    """Own one frameless QML Sidecar window and its narrow bridge."""

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
        app = ensure_application()
        copy_callback = on_copy or (lambda body: app.clipboard().setText(body))
        self.bridge = SidecarBridge(
            mode,
            source_presenter=source_presenter,
            on_action=on_action,
            on_close_view=on_close_view,
            on_open_editor=on_open_editor,
            on_copy=copy_callback,
        )
        self.engine = QQmlApplicationEngine()
        self.engine.rootContext().setContextProperty("sidecarBridge", self.bridge)
        self.engine.load(QUrl.fromLocalFile(str(QML_ENTRYPOINT)))
        roots = self.engine.rootObjects()
        if len(roots) != 1 or not isinstance(roots[0], QQuickWindow):
            errors = "; ".join(str(error) for error in self.engine.warnings())
            raise RuntimeError(f"Sidecar.qml did not create one QQuickWindow: {errors}")
        self.window = roots[0]
        self.bridge.closeRequested.connect(self.close_view)
        self.bridge.terminalDismissRequested.connect(self.dismiss_terminal)

    @property
    def mode(self) -> SidecarMode:
        return SidecarMode.parse(self.bridge.mode)

    def show(self) -> None:
        self.window.show()
        self.window.requestActivate()
        _process_until(
            lambda: self.window.isVisible()
            and self.window.isExposed()
            and bool(self.window.property("assetsReady"))
        )

    def render(self, projection: dict[str, object]) -> bool:
        active = self.bridge.render(projection)
        if not active:
            return False
        self.show()
        self.focus_primary_action()
        return True

    def set_mode(self, mode: SidecarMode) -> None:
        expected = SidecarMode.parse(mode)
        self.bridge.setMode(expected.value)
        width, height = expected.size
        _process_until(lambda: self.window.width() == width and self.window.height() == height)

    def focus_primary_action(self) -> None:
        if not QMetaObject.invokeMethod(self.window, "focusFirstAction", Qt.DirectConnection):
            raise RuntimeError("unable to focus the first projected Sidecar action")

    def close_view(self) -> None:
        self.window.hide()
        self.bridge.notify_closed()

    def dismiss_terminal(self) -> None:
        self.window.hide()

    def capture(self, path: Path) -> QImage:
        path.parent.mkdir(parents=True, exist_ok=True)
        image = self.window.grabWindow()
        if image.isNull():
            raise RuntimeError("QQuickWindow.grabWindow returned a null image")
        if not image.save(str(path), "PNG"):
            raise RuntimeError(f"unable to save Sidecar capture: {path}")
        return image

    def object(self, object_name: str) -> QObject:
        found = self.window.findChild(QObject, object_name)
        if found is None:
            raise LookupError(f"QML object not found: {object_name}")
        return found

    def close(self) -> None:
        self.window.close()
        self.window.deleteLater()
        self.engine.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        ensure_application().processEvents()
