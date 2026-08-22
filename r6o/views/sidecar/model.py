from __future__ import annotations

"""Presentation-only Sidecar state over the mechanical adapter."""

from typing import Any

from r6o.views.state import ProjectionViewState


class SidecarModel:
    def __init__(
        self,
        adapter: Any,
        session_id: str,
        mode: str = "STANDARD",
        *,
        qualification_case: str | None = None,
    ) -> None:
        if mode not in {"STANDARD", "EXPANDED"}:
            raise ValueError(f"unsupported Sidecar mode: {mode}")
        self.state = ProjectionViewState(
            adapter,
            session_id,
            qualification_case=qualification_case,
        )
        self.mode = mode
        self.visible = True

    @property
    def projection(self) -> dict[str, Any]:
        return self.state.projection

    @property
    def actions(self) -> list[dict[str, Any]]:
        return self.state.actions

    @property
    def notice(self) -> str | None:
        return self.state.notice

    @property
    def terminal(self) -> bool:
        return self.projection.get("interaction_state") == "TERMINAL"

    def select_action(self, action_id: str) -> dict[str, Any] | None:
        return self.state.submit_action(action_id)

    def host_composer_text(self, text: str) -> dict[str, Any] | None:
        return self.state.submit_text("HOST_COMPOSER_TEXT", text)

    def toggle_mode(self) -> str:
        self.mode = "EXPANDED" if self.mode == "STANDARD" else "STANDARD"
        return self.mode

    def close(self) -> None:
        self.visible = False
