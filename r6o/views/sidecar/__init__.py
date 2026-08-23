"""Disposable PySide6/Qt Quick Sidecar presentation."""

from r6o.views.sidecar.model import EXPANDED_SIZE, STANDARD_SIZE, SidecarMode
from r6o.views.sidecar.qt_app import QtSidecarWindow, ensure_application

__all__ = [
    "EXPANDED_SIZE",
    "STANDARD_SIZE",
    "QtSidecarWindow",
    "SidecarMode",
    "ensure_application",
]
