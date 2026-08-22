from __future__ import annotations

"""TUI View controller: presentation state + mechanical input adaptation.

Owns only presentation state (projection, scroll, focus, notices). Routes
input through the presentation adapter using the accepted InputEnvelope
contract. Never interprets semantic text.
"""

from typing import Any

from r6o.views.envelopes import free_response_envelope, structured_action_envelope

ARTIFACT_WIDTH = 52
VISIBLE_ARTIFACT_LINES = 6


class TuiController:
    def __init__(self, adapter: Any, session_id: str) -> None:
        self.adapter = adapter
        self.session_id = session_id
        self.projection = adapter.current_projection(session_id)
        self.scroll = 0
        self.focus_mode = False
        self.notice: str | None = None
        self.closed = False

    # --- presentation state -------------------------------------------------
    def refresh(self) -> None:
        self.projection = self.adapter.current_projection(self.session_id)
        self.scroll = 0
        self.notice = None

    def _safe_refresh(self) -> bool:
        try:
            self.refresh()
            return True
        except Exception as exc:  # non-semantic failure surface
            self.notice = f"error: MODEL_ACCESS ({exc})"
            return False

    def scroll_artifact(self, delta: int) -> None:
        body = (self.projection.get("artifact") or {}).get("body") or ""
        lines = _wrap(body, ARTIFACT_WIDTH)
        self.scroll = min(max(0, self.scroll + delta), max(0, len(lines) - VISIBLE_ARTIFACT_LINES))

    def close_view(self) -> None:
        self.closed = True

    def focus_free_response(self) -> None:
        self.focus_mode = True

    # --- input adaptation ---------------------------------------------------
    def select_action(self, ordinal: int) -> dict[str, Any] | None:
        actions = _sorted_actions(self.projection.get("actions", []))
        action = next((a for a in actions if a["ordinal"] == ordinal), None)
        if action is None:
            self.notice = f"no action {ordinal}"
            return None
        if not action.get("enabled", True):
            self.notice = f"action {ordinal} is disabled"
            return None
        if action["kind"] == "SEMANTIC_MESSAGE":
            envelope = structured_action_envelope(self.projection, action["action_id"])
            return self._submit(envelope)
        if action["kind"] == "FREE_RESPONSE_FOCUS":
            self.focus_mode = True
            self.notice = f"focus: {action['label']}"
            return {"result_type": "FOCUS_REQUIRED", "focus_role": "FREE_RESPONSE"}
        self.notice = f"unsupported action kind: {action['kind']}"
        return None

    def submit_text(self, text: str) -> dict[str, Any]:
        self.focus_mode = False
        envelope = free_response_envelope("TUI_TEXT", self.projection, text)
        return self._submit(envelope)

    def _submit(self, envelope: dict[str, Any]) -> dict[str, Any]:
        result = self.adapter.submit_input(envelope)
        self._apply_result(result)
        return result

    def _apply_result(self, result: dict[str, Any]) -> None:
        kind = result.get("result_type")
        if kind == "REVISION" and result.get("projection"):
            self.projection = result["projection"]
            self.scroll = 0
            self.notice = None
        elif kind == "STALE_PROJECTION":
            if result.get("projection"):
                self.projection = result["projection"]
                self.scroll = 0
                self.notice = "view changed; refreshed from current projection"
            else:
                if self._safe_refresh():
                    self.notice = "view changed; refreshed from current projection"
        elif kind == "FOCUS_REQUIRED":
            self.focus_mode = True
        elif kind == "ERROR":
            error = result.get("error") or {}
            self.notice = f"error: {error.get('code', 'UNKNOWN')}"

    # --- rendering (TUI-REFERENCE layout) -----------------------------------
    def render(self, width: int = 84) -> str:
        stage = str(self.projection.get("stage") or "UNKNOWN").replace("_", " ")
        header = f"PDLt · {stage}"
        artifact = (self.projection.get("artifact") or {}).get("body") or "(no artifact)"
        left = _wrap(artifact, ARTIFACT_WIDTH)
        actions = _sorted_actions(self.projection.get("actions", []))
        right = _actions_lines(actions)
        start = min(self.scroll, max(0, len(left) - VISIBLE_ARTIFACT_LINES))
        rows = max(VISIBLE_ARTIFACT_LINES, len(right))
        lines = [header, ""]
        for idx in range(rows):
            l = left[start + idx] if start + idx < len(left) else ""
            r = right[idx] if idx < len(right) else ""
            lines.append(f"{l:<{ARTIFACT_WIDTH}}  {r}")
        lines.append("")
        if self.notice:
            lines.append(f"! {self.notice}")
        lines.append("u/d scroll · q quit · empty line focuses input")
        prompt = "Review > "
        if self.focus_mode:
            prompt = "Review > [free-response focus] "
        lines.append(prompt)
        return "\n".join(lines)


def _sorted_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(actions, key=lambda a: a.get("ordinal", 0))


def _wrap(text: str, width: int) -> list[str]:
    out: list[str] = []
    for raw in text.splitlines() or [""]:
        line = raw
        while len(line) > width:
            out.append(line[:width])
            line = line[width:]
        out.append(line)
    return out


def _actions_lines(actions: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for action in actions:
        label = action.get("label") or action.get("action_id") or "?"
        suffix = "" if action.get("enabled", True) else " (disabled)"
        out.append(f"{action.get('ordinal')} {label}{suffix}")
    return out

