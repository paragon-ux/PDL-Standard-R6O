from __future__ import annotations

"""Mechanical presentation adapter over the ViewModel dispatcher.

Public surface is limited to ``current_projection`` and ``submit_input``.
No semantic controller verbs, lifecycle operations, workspace paths, or
worker calls are exposed.
"""

from typing import Any

from r6o.viewmodel.dispatcher import handle_input
from r6o.viewmodel.projection import build_focus_projection_from_port


class PresentationAdapter:
    """Presentation plumbing over an ``r6o-model-port-1`` port."""

    def __init__(self, port: Any) -> None:
        self._port = port

    def current_projection(self, session_id: str) -> dict[str, Any]:
        return build_focus_projection_from_port(self._port, session_id)

    def submit_input(self, envelope: dict[str, Any]) -> dict[str, Any]:
        return handle_input(envelope, self._port)
