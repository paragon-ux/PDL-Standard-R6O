from __future__ import annotations

"""Narrow View-facing adapter with no protocol semantics."""

from typing import Any

from r6o.viewmodel.dispatcher import handle_input, validate_command_result
from r6o.viewmodel.projection import build_focus_projection_from_port


class PresentationAdapter:
    """Expose only current projection and InputEnvelope submission to Views."""

    def __init__(self, port: Any) -> None:
        self._port = port

    def current_projection(self, session_id: str) -> dict[str, Any]:
        return build_focus_projection_from_port(self._port, session_id)

    def submit_input(self, envelope: dict[str, Any]) -> dict[str, Any]:
        result = handle_input(envelope, self._port)
        validate_command_result(result)
        return result
