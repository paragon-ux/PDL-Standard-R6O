from __future__ import annotations

"""Shared presentation state and fail-closed result handling."""

from typing import Any

from r6o.views.envelopes import structured_action_envelope, text_envelope


class ProjectionViewState:
    """Own projection, notice, and presentation-only disposal state."""

    def __init__(self, adapter: Any, session_id: str) -> None:
        self.adapter = adapter
        self.session_id = session_id
        self.projection = adapter.current_projection(session_id)
        self.notice: str | None = None
        self.closed = False

    @property
    def actions(self) -> list[dict[str, Any]]:
        return sorted(
            self.projection.get("actions") or [],
            key=lambda action: action.get("ordinal", 0),
        )

    def refresh(self) -> bool:
        try:
            self.projection = self.adapter.current_projection(self.session_id)
        except Exception as exc:
            self.notice = f"MODEL_ACCESS: {exc}"
            return False
        self.session_id = self.projection["session_id"]
        self.notice = None
        return True

    def submit_action(self, action_id: str) -> dict[str, Any] | None:
        action = next(
            (item for item in self.actions if item.get("action_id") == action_id),
            None,
        )
        if action is None:
            self.notice = f"UNKNOWN_ACTION: {action_id}"
            return None
        if not action.get("enabled", True):
            self.notice = f"Action unavailable: {action.get('label', action_id)}"
            return None
        return self._apply(
            self.adapter.submit_input(
                structured_action_envelope(self.projection, action_id)
            )
        )

    def submit_text(self, source: str, text: str) -> dict[str, Any] | None:
        if not text.strip():
            self.notice = "Enter review feedback before submitting."
            return None
        return self._apply(
            self.adapter.submit_input(text_envelope(source, self.projection, text))
        )

    def _apply(self, result: dict[str, Any]) -> dict[str, Any]:
        result_type = result.get("result_type")
        projection = result.get("projection")
        if result_type == "REVISION" and projection:
            self.projection = projection
            self.session_id = projection["session_id"]
            self.notice = None
        elif result_type == "STALE_PROJECTION":
            if projection:
                self.projection = projection
                self.session_id = projection["session_id"]
                self.notice = "View changed; refreshed to the current projection."
            else:
                self.refresh()
        elif result_type == "FOCUS_REQUIRED":
            self.notice = None
        else:
            error = result.get("error") or {}
            code = error.get("code", "UNKNOWN")
            message = error.get("message", "Command failed")
            self.notice = f"{code}: {message}"
        return result

    def close_view(self) -> None:
        self.closed = True
