from __future__ import annotations

"""Sidecar presentation model: pure View state, no protocol authority.

Owns only mode (STANDARD/EXPANDED), closed flag, current projection, and
notices. Free response is NOT owned by the Sidecar; it is submitted through
HOST_COMPOSER_TEXT by the surrounding harness.
"""

from typing import Any, Callable

from r6o.views.envelopes import free_response_envelope, structured_action_envelope

FocusCallback = Callable[[str], None]


class SidecarModel:
    def __init__(self, adapter: Any, session_id: str, focus_host_callback: FocusCallback | None = None) -> None:
        self.adapter = adapter
        self.session_id = session_id
        self.focus_host_callback = focus_host_callback
        self.mode = "STANDARD"
        self.closed = False
        self.notice: str | None = None
        self.projection = adapter.current_projection(session_id)

    # --- presentation-only transitions --------------------------------------
    def toggle_mode(self) -> None:
        self.mode = "EXPANDED" if self.mode == "STANDARD" else "STANDARD"
        self.notice = None

    def close(self) -> None:
        self.closed = True

    def open_(self) -> None:
        self.closed = False
        self.refresh()

    def refresh(self) -> None:
        self.projection = self.adapter.current_projection(self.session_id)
        self.notice = None

    def _safe_refresh(self) -> bool:
        try:
            self.refresh()
            return True
        except Exception as exc:
            self.notice = f"error: MODEL_ACCESS ({exc})"
            return False

    # --- action input -------------------------------------------------------
    def select_action(self, action_id: str) -> dict[str, Any] | None:
        if self.closed:
            return None
        action = next((a for a in self.projection.get("actions", []) if a["action_id"] == action_id), None)
        if action is None:
            self.notice = f"unknown action {action_id}"
            return None
        if not action.get("enabled", True):
            self.notice = f"action disabled: {action['label']}"
            return None
        if action["kind"] == "SEMANTIC_MESSAGE":
            envelope = structured_action_envelope(self.projection, action_id)
            return self._submit(envelope)
        if action["kind"] == "FREE_RESPONSE_FOCUS":
            if self.focus_host_callback is not None:
                self.focus_host_callback(str(action.get("label") or action_id))
            self.notice = f"focus requested: {action.get('label')}"
            return {"result_type": "FOCUS_REQUIRED", "focus_role": "FREE_RESPONSE"}
        self.notice = f"unsupported action kind: {action['kind']}"
        return None

    def host_composer_text(self, text: str) -> dict[str, Any]:
        envelope = free_response_envelope("HOST_COMPOSER_TEXT", self.projection, text)
        return self._submit(envelope)

    def _submit(self, envelope: dict[str, Any]) -> dict[str, Any]:
        result = self.adapter.submit_input(envelope)
        self._apply_result(result)
        return result

    def _apply_result(self, result: dict[str, Any]) -> None:
        kind = result.get("result_type")
        if kind == "REVISION" and result.get("projection"):
            self.projection = result["projection"]
            self.notice = None
        elif kind == "STALE_PROJECTION":
            if result.get("projection"):
                self.projection = result["projection"]
                self.notice = "view changed; refreshed from current projection"
            else:
                if self._safe_refresh():
                    self.notice = "view changed; refreshed from current projection"
        elif kind == "ERROR":
            error = result.get("error") or {}
            self.notice = f"error: {error.get('code', 'UNKNOWN')}"

