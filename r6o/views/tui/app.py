from __future__ import annotations

"""A real keyboard-driven terminal View over the accepted R6O ViewModel."""

import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterator, TextIO

from r6o.viewmodel.dispatcher import handle_input, validate_command_result


ESC = "\x1b"


@dataclass(frozen=True)
class KeyEvent:
    name: str
    text: str | None = None


class TerminalInput:
    """Translate native terminal key sequences into presentation events."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self.stream = stream or sys.stdin

    def read(self) -> KeyEvent:
        if os.name == "nt" and self.stream is sys.stdin and self.stream.isatty():
            return self._read_windows()
        return self._read_stream()

    @staticmethod
    def _read_windows() -> KeyEvent:
        import msvcrt

        value = msvcrt.getwch()
        if value in {"\x00", "\xe0"}:
            extended = msvcrt.getwch()
            return {"H": KeyEvent("UP"), "P": KeyEvent("DOWN")}.get(extended, KeyEvent("UNKNOWN"))
        return TerminalInput._translate(value)

    def _read_stream(self) -> KeyEvent:
        value = self._read_character()
        if value == "":
            return KeyEvent("EOF")
        if value == ESC:
            second = self._read_character()
            if second == "[":
                third = self._read_character()
                return {"A": KeyEvent("UP"), "B": KeyEvent("DOWN")}.get(third, KeyEvent("UNKNOWN"))
            return KeyEvent("ESCAPE")
        return self._translate(value)

    def _read_character(self) -> str:
        if self.stream is sys.stdin and hasattr(self.stream, "buffer"):
            return self.stream.buffer.read(1).decode("utf-8", errors="replace")
        return self.stream.read(1)

    @staticmethod
    def _translate(value: str) -> KeyEvent:
        if value in {"\r", "\n"}:
            return KeyEvent("ENTER")
        if value == "\t":
            return KeyEvent("NEXT")
        if value == "\x03":
            return KeyEvent("INTERRUPT")
        return KeyEvent("TEXT", value)


@contextmanager
def terminal_session(stdin: TextIO, stdout: TextIO) -> Iterator[None]:
    """Enable alternate-screen/raw keyboard mode only for an attached terminal."""

    interactive = stdin.isatty() and stdout.isatty()
    old_termios: Any | None = None
    if interactive and os.name != "nt":
        import termios
        import tty

        old_termios = termios.tcgetattr(stdin.fileno())
        tty.setcbreak(stdin.fileno())
    if interactive:
        stdout.write(f"{ESC}[?1049h{ESC}[?25l")
        stdout.flush()
    try:
        yield
    finally:
        if old_termios is not None:
            import termios

            termios.tcsetattr(stdin.fileno(), termios.TCSADRAIN, old_termios)
        if interactive:
            stdout.write(f"{ESC}[?25h{ESC}[?1049l")
            stdout.flush()


class TerminalReviewApp:
    """Render FocusProjection documents and dispatch real key selections."""

    def __init__(
        self,
        port: Any,
        session_id: str,
        *,
        stdin: TextIO | None = None,
        stdout: TextIO | None = None,
        on_projection: Callable[[str, str | None, dict[str, Any]], None] | None = None,
    ) -> None:
        self.port = port
        self.session_id = session_id
        self.stdin = stdin or sys.stdin
        self.stdout = stdout or sys.stdout
        self.input = TerminalInput(self.stdin)
        self.on_projection = on_projection or (lambda event, action, projection: None)
        self.focus_index = 0

    @staticmethod
    def _title(stage: str) -> str:
        return {
            "PROMPT_REVIEW": "PROMPT REVIEW",
            "PLAN_REVIEW": "PLAN REVIEW",
            "CLOSED_SUCCESS": "REVIEW COMPLETE",
            "CLOSED_CANCELLED": "REVIEW CANCELLED",
        }.get(stage, stage.replace("_", " "))

    def _render(self, projection: dict[str, Any]) -> None:
        stage = projection["stage"]
        artifact = projection.get("artifact")
        actions = projection.get("actions") or []
        lines = [
            "PDLt REVIEW",
            "=" * 72,
            self._title(stage),
            "-" * 72,
        ]
        if artifact:
            lines.extend([artifact["title"], "", artifact["body"], ""])
        if actions:
            lines.append("ACTIONS")
            for index, action in enumerate(actions):
                pointer = ">" if index == self.focus_index else " "
                enter = " [Enter]" if index == self.focus_index else ""
                lines.append(f"{pointer} {action['ordinal']}. {action['label']}{enter}")
            lines.extend(["", "Use Up/Down or Tab to move; press Enter to activate."])
        elif stage == "CLOSED_SUCCESS":
            lines.extend(["The review workflow reached CLOSED_SUCCESS.", "Returning control to the invoking shell."])
        self.stdout.write(f"{ESC}[2J{ESC}[H" + "\n".join(lines) + "\n")
        self.stdout.flush()

    @staticmethod
    def _envelope(projection: dict[str, Any], action_id: str) -> dict[str, Any]:
        return {
            "schema_version": "r6o-input-envelope-1",
            "session_id": projection["session_id"],
            "source": "STRUCTURED_ACTION",
            "model_revision": projection["model_revision"],
            "text": None,
            "action_id": action_id,
            "projection_id": projection["projection_id"],
        }

    def run(self, initial_projection: dict[str, Any]) -> dict[str, Any]:
        projection = initial_projection
        self.on_projection("START", None, projection)
        with terminal_session(self.stdin, self.stdout):
            while True:
                self.focus_index = min(self.focus_index, max(len(projection.get("actions") or []) - 1, 0))
                self._render(projection)
                if projection["stage"] in {"CLOSED_SUCCESS", "CLOSED_CANCELLED"}:
                    return projection
                event = self.input.read()
                if event.name in {"EOF", "INTERRUPT", "ESCAPE"}:
                    raise KeyboardInterrupt("terminal review interrupted")
                actions = projection.get("actions") or []
                if not actions:
                    raise RuntimeError(f"stage {projection['stage']} has no projected actions")
                if event.name in {"DOWN", "NEXT"}:
                    self.focus_index = (self.focus_index + 1) % len(actions)
                    continue
                if event.name == "UP":
                    self.focus_index = (self.focus_index - 1) % len(actions)
                    continue
                if event.name != "ENTER":
                    continue
                action_id = actions[self.focus_index]["action_id"]
                result = handle_input(self._envelope(projection, action_id), self.port)
                validate_command_result(result)
                if not result["ok"]:
                    message = (result.get("error") or {}).get("message") or "action failed"
                    raise RuntimeError(message)
                if result["result_type"] == "FOCUS_REQUIRED":
                    raise RuntimeError("free-response input is not part of the structured G06 gate")
                projection = result["projection"]
                self.focus_index = 0
                self.on_projection("ACTION", action_id, projection)
