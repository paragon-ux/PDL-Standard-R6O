from __future__ import annotations

"""Disposable Qt Sidecar with toolkit-neutral imports kept dependency-light."""

from typing import Any

__all__ = [
    "EXPANDED_SIZE",
    "STANDARD_SIZE",
    "SidecarBridge",
    "QtSidecarWindow",
    "SidecarMode",
    "ensure_application",
]


def __getattr__(name: str) -> Any:
    if name in {"EXPANDED_SIZE", "STANDARD_SIZE", "SidecarMode"}:
        from r6o.views.sidecar import model

        return getattr(model, name)
    if name == "SidecarBridge":
        from r6o.views.sidecar.bridge import SidecarBridge

        return SidecarBridge
    if name in {"QtSidecarWindow", "ensure_application"}:
        from r6o.views.sidecar import qt_app

        return getattr(qt_app, name)
    raise AttributeError(name)
