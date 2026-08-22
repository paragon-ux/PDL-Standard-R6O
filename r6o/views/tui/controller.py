from __future__ import annotations

"""Presentation-only state and keyboard behavior for the event-loop TUI."""

import textwrap
from typing import Any

from r6o.views.state import ProjectionViewState

FOCUS_ORDER = ("artifact", "actions", "input")


class TuiController:
    def __init__(self, adapter: Any, session_id: str) -> None:
        self.state = ProjectionViewState(adapter, session_id)
        self.focus = "actions" if self.state.actions else "input"
        self.action_index = 0
        self.artifact_scroll = 0
        self.input_buffer = ""
        self.cursor = 0
        self.dirty = True

    @property
    def closed(self) -> bool:
        return self.state.closed

    @property
    def projection(self) -> dict[str, Any]:
        return self.state.projection

    @property
    def notice(self) -> str | None:
        return self.state.notice

    def close_view(self) -> None:
        self.state.close_view()
        self.dirty = True

    def refresh(self) -> None:
        self.state.refresh()
        self._projection_changed()

    def _projection_changed(self) -> None:
        self.artifact_scroll = 0
        self.action_index = min(
            self.action_index, max(0, len(self.state.actions) - 1)
        )
        self.dirty = True

    def cycle_focus(self, backwards: bool = False) -> None:
        index = FOCUS_ORDER.index(self.focus)
        delta = -1 if backwards else 1
        self.focus = FOCUS_ORDER[(index + delta) % len(FOCUS_ORDER)]
        self.dirty = True

    def select_action(self, index: int | None = None) -> dict[str, Any] | None:
        actions = self.state.actions
        if not actions:
            self.state.notice = "No actions are available in the current state."
            self.dirty = True
            return None
        if index is not None:
            self.action_index = max(0, min(index, len(actions) - 1))
        action = actions[self.action_index]
        result = self.state.submit_action(action["action_id"])
        if result and result.get("result_type") == "FOCUS_REQUIRED":
            self.focus = "input"
        if result and result.get("projection"):
            self._projection_changed()
        self.dirty = True
        return result

    def submit_input(self) -> dict[str, Any] | None:
        value = self.input_buffer
        result = self.state.submit_text("TUI_TEXT", value)
        if result and result.get("result_type") == "REVISION":
            self.input_buffer = ""
            self.cursor = 0
            self._projection_changed()
        self.dirty = True
        return result

    def handle_key(self, key: str) -> dict[str, Any] | None:
        if key in {"CTRL_C", "CTRL_Q"}:
            self.close_view()
            return None
        if key == "TAB":
            self.cycle_focus()
            return None
        if key == "SHIFT_TAB":
            self.cycle_focus(backwards=True)
            return None
        if key == "F5":
            self.refresh()
            return None

        if self.focus == "artifact":
            if key in {"UP", "PAGE_UP"}:
                self.artifact_scroll = max(
                    0, self.artifact_scroll - (8 if key == "PAGE_UP" else 1)
                )
            elif key in {"DOWN", "PAGE_DOWN"}:
                self.artifact_scroll += 8 if key == "PAGE_DOWN" else 1
            elif key == "HOME":
                self.artifact_scroll = 0
            elif key == "END":
                self.artifact_scroll = 10**9
            self.dirty = True
            return None

        if self.focus == "actions":
            actions = self.state.actions
            if key == "UP" and actions:
                self.action_index = (self.action_index - 1) % len(actions)
            elif key == "DOWN" and actions:
                self.action_index = (self.action_index + 1) % len(actions)
            elif key == "ENTER":
                return self.select_action()
            elif len(key) == 1 and key.isdigit():
                ordinal = int(key)
                for index, action in enumerate(actions):
                    if action.get("ordinal") == ordinal:
                        return self.select_action(index)
            self.dirty = True
            return None

        if key == "ENTER":
            return self.submit_input()
        if key == "LEFT":
            self.cursor = max(0, self.cursor - 1)
        elif key == "RIGHT":
            self.cursor = min(len(self.input_buffer), self.cursor + 1)
        elif key == "HOME":
            self.cursor = 0
        elif key == "END":
            self.cursor = len(self.input_buffer)
        elif key == "BACKSPACE" and self.cursor:
            self.input_buffer = (
                self.input_buffer[: self.cursor - 1]
                + self.input_buffer[self.cursor :]
            )
            self.cursor -= 1
        elif key == "DELETE" and self.cursor < len(self.input_buffer):
            self.input_buffer = (
                self.input_buffer[: self.cursor]
                + self.input_buffer[self.cursor + 1 :]
            )
        elif len(key) == 1 and key.isprintable():
            self.input_buffer = (
                self.input_buffer[: self.cursor]
                + key
                + self.input_buffer[self.cursor :]
            )
            self.cursor += 1
        self.dirty = True
        return None

    def render(self, width: int, height: int) -> str:
        width = max(42, width)
        height = max(14, height)
        inner = width - 4
        stage = str(self.projection.get("stage") or "UNKNOWN").replace("_", " ")
        status = "ACTIVE" if self.projection.get("interaction_state") == "REVIEW_REQUIRED" else str(
            self.projection.get("interaction_state") or ""
        )
        title = f" PDLt · {stage} "
        top = "┌" + title + "─" * max(0, width - len(title) - len(status) - 3) + f" {status} ┐"
        content_height = max(5, height - 8)
        if width >= 76:
            body = self._render_wide(inner, content_height)
        else:
            body = self._render_narrow(inner, content_height)
        notice = self.notice or "Tab changes focus · F5 refresh · Ctrl+Q closes only this View"
        notice = _clip(notice, inner)
        input_line = self._render_input(inner)
        lines = [top, *body]
        lines.append("├" + "─" * (width - 2) + "┤")
        lines.append("│ " + f"{notice:<{inner}}" + " │")
        lines.append("│ " + f"{input_line:<{inner}}" + " │")
        lines.append("└" + "─" * (width - 2) + "┘")
        return "\n".join(lines[:height])

    def _render_wide(self, inner: int, rows: int) -> list[str]:
        gap = 3
        action_width = max(24, min(34, inner // 3))
        artifact_width = inner - action_width - gap
        artifact_lines = _wrap_artifact(self.projection, artifact_width)
        max_scroll = max(0, len(artifact_lines) - max(1, rows - 1))
        self.artifact_scroll = min(self.artifact_scroll, max_scroll)
        visible = artifact_lines[self.artifact_scroll : self.artifact_scroll + rows - 1]
        actions = self._action_lines(action_width, rows - 1)
        focus_artifact = "▶ " if self.focus == "artifact" else "  "
        focus_actions = "▶ " if self.focus == "actions" else "  "
        headings = (
            _clip(focus_artifact + "Authoritative Artifact", artifact_width),
            _clip(focus_actions + "Review Options", action_width),
        )
        result = [
            "│ "
            + f"{headings[0]:<{artifact_width}}"
            + " " * gap
            + f"{headings[1]:<{action_width}}"
            + " │"
        ]
        for index in range(rows - 1):
            left = visible[index] if index < len(visible) else ""
            right = actions[index] if index < len(actions) else ""
            result.append(
                "│ "
                + f"{_clip(left, artifact_width):<{artifact_width}}"
                + " " * gap
                + f"{_clip(right, action_width):<{action_width}}"
                + " │"
            )
        return result

    def _render_narrow(self, inner: int, rows: int) -> list[str]:
        action_rows = min(max(2, len(self.state.actions)), max(2, rows // 3))
        artifact_rows = max(2, rows - action_rows - 2)
        artifact_lines = _wrap_artifact(self.projection, inner)
        max_scroll = max(0, len(artifact_lines) - artifact_rows)
        self.artifact_scroll = min(self.artifact_scroll, max_scroll)
        visible = artifact_lines[self.artifact_scroll : self.artifact_scroll + artifact_rows]
        result = [
            "│ "
            + f"{(('▶ ' if self.focus == 'artifact' else '  ') + 'Authoritative Artifact'):<{inner}}"
            + " │"
        ]
        for line in visible:
            result.append("│ " + f"{_clip(line, inner):<{inner}}" + " │")
        while len(result) < artifact_rows + 1:
            result.append("│ " + " " * inner + " │")
        result.append(
            "│ "
            + f"{(('▶ ' if self.focus == 'actions' else '  ') + 'Review Options'):<{inner}}"
            + " │"
        )
        for line in self._action_lines(inner, action_rows):
            result.append("│ " + f"{_clip(line, inner):<{inner}}" + " │")
        return result

    def _action_lines(self, width: int, limit: int) -> list[str]:
        lines: list[str] = []
        for index, action in enumerate(self.state.actions[:limit]):
            marker = "▶" if self.focus == "actions" and index == self.action_index else " "
            disabled = " [disabled]" if not action.get("enabled", True) else ""
            primary = " ★" if action.get("emphasis") == "PRIMARY" else ""
            lines.append(
                _clip(
                    f"{marker} {action.get('ordinal')} {action.get('label')}{primary}{disabled}",
                    width,
                )
            )
        return lines

    def _render_input(self, width: int) -> str:
        prefix = "▶ Review > " if self.focus == "input" else "  Review > "
        available = max(1, width - len(prefix))
        start = max(0, self.cursor - available + 1)
        value = self.input_buffer[start : start + available]
        if self.focus == "input":
            position = min(len(value), self.cursor - start)
            value = value[:position] + "▌" + value[position:]
        return _clip(prefix + value, width)


def _wrap_artifact(projection: dict[str, Any], width: int) -> list[str]:
    artifact = projection.get("artifact") or {}
    title = artifact.get("title") or "No authoritative artifact"
    body = artifact.get("body") or projection.get("model_response") or "(no artifact)"
    lines = [str(title), "─" * min(width, max(3, len(str(title))))]
    for raw in str(body).splitlines() or [""]:
        lines.extend(
            textwrap.wrap(
                raw,
                width=max(1, width),
                replace_whitespace=False,
                drop_whitespace=False,
            )
            or [""]
        )
    return lines


def _clip(value: str, width: int) -> str:
    if len(value) <= width:
        return value
    return value[: max(0, width - 1)] + "…"
