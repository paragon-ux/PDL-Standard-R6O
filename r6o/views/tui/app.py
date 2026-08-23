from __future__ import annotations

"""Persistent keyboard-driven terminal View over the accepted R6O ViewModel."""

import codecs
import os
import shutil
import sys
import textwrap
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterator, TextIO

from r6o.viewmodel.dispatcher import handle_input, validate_command_result
from r6o.viewmodel.projection import build_focus_projection_from_port

ESC = "\x1b"
TERMINAL_STAGES = frozenset({"CLOSED_SUCCESS", "CLOSED_CANCELLED"})


class TerminalViewClosed(Exception):
    """The human closed only the disposable TUI View."""


@dataclass(frozen=True)
class KeyEvent:
    name: str
    text: str | None = None


class TerminalInput:
    """Translate native terminal key sequences into presentation events."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self.stream = stream or sys.stdin
        self._pending: list[str] = []
        self._byte_decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

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
            return {
                "H": KeyEvent("UP"),
                "P": KeyEvent("DOWN"),
                "I": KeyEvent("PAGE_UP"),
                "Q": KeyEvent("PAGE_DOWN"),
                "?": KeyEvent("REFRESH"),
                "\x0f": KeyEvent("PREVIOUS"),
            }.get(extended, KeyEvent("UNKNOWN"))
        return TerminalInput._translate(value)

    def _read_stream(self) -> KeyEvent:
        value = self._read_character()
        if value == "":
            return KeyEvent("EOF")
        if value != ESC:
            return self._translate(value)
        second = self._read_escape_continuation()
        if second != "[":
            if second:
                self._pending.append(second)
            return KeyEvent("ESCAPE")
        third = self._read_character()
        if third in {"A", "B", "Z"}:
            return {"A": KeyEvent("UP"), "B": KeyEvent("DOWN"), "Z": KeyEvent("PREVIOUS")}[third]
        sequence = third
        while len(sequence) < 4 and not sequence.endswith("~"):
            continuation = self._read_character()
            if not continuation:
                break
            sequence += continuation
        return {
            "5~": KeyEvent("PAGE_UP"),
            "6~": KeyEvent("PAGE_DOWN"),
            "15~": KeyEvent("REFRESH"),
        }.get(sequence, KeyEvent("UNKNOWN"))

    def _read_character(self) -> str:
        if self._pending:
            return self._pending.pop()
        if self.stream is sys.stdin and hasattr(self.stream, "buffer"):
            while True:
                raw = self.stream.buffer.read(1)
                if not raw:
                    return self._byte_decoder.decode(b"", final=True)
                decoded = self._byte_decoder.decode(raw)
                if decoded:
                    return decoded
        return self.stream.read(1)

    def _read_escape_continuation(self) -> str:
        if self.stream is sys.stdin and self.stream.isatty() and os.name != "nt":
            import select

            readable, _, _ = select.select([self.stream], [], [], 0.05)
            if not readable:
                return ""
        return self._read_character()

    @staticmethod
    def _translate(value: str) -> KeyEvent:
        if value == ESC:
            return KeyEvent("ESCAPE")
        if value in {"\r", "\n"}:
            return KeyEvent("ENTER")
        if value == "\t":
            return KeyEvent("NEXT")
        if value in {"\x08", "\x7f"}:
            return KeyEvent("BACKSPACE")
        if value == "\x03":
            return KeyEvent("INTERRUPT")
        if value == "\x11":
            return KeyEvent("CLOSE")
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


@dataclass(frozen=True)
class FrameCharacters:
    top_left: str
    top_right: str
    bottom_left: str
    bottom_right: str
    vertical: str
    horizontal: str
    tee_left: str
    tee_right: str


UNICODE_FRAME = FrameCharacters("┌", "┐", "└", "┘", "│", "─", "├", "┤")
ASCII_FRAME = FrameCharacters("+", "+", "+", "+", "|", "-", "+", "+")


class TerminalReviewApp:
    """Render FocusProjection documents and dispatch real keyboard events."""

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
        self.artifact_offset = 0
        self.artifact_page_size = 1
        self.free_response_active = False
        self.free_response_text = ""
        self.notice: str | None = None

    @staticmethod
    def _title(stage: str) -> str:
        return {"PROMPT_REVIEW": "PROMPT REVIEW", "PLAN_REVIEW": "PLAN REVIEW"}.get(
            stage, stage.replace("_", " ")
        )

    def _frame_characters(self) -> FrameCharacters:
        encoding = getattr(self.stdout, "encoding", None) or "utf-8"
        try:
            "┌─ PDLt ↑↓".encode(encoding)
        except (LookupError, UnicodeEncodeError):
            return ASCII_FRAME
        return UNICODE_FRAME

    def _terminal_size(self) -> tuple[int, int]:
        if self.stdout is sys.stdout:
            size = shutil.get_terminal_size((80, 30))
            return max(40, min(size.columns, 120)), max(18, size.lines)
        return 80, 30

    @staticmethod
    def _fit(value: str, width: int) -> str:
        if len(value) <= width:
            return value + " " * (width - len(value))
        if width <= 3:
            return value[:width]
        return value[: width - 3] + "..."

    @staticmethod
    def _wrap(value: str, width: int, *, subsequent_indent: str = "") -> list[str]:
        lines: list[str] = []
        for source_line in value.splitlines() or [""]:
            wrapped = textwrap.wrap(
                source_line,
                width=max(1, width),
                subsequent_indent=subsequent_indent,
                replace_whitespace=False,
                drop_whitespace=False,
            )
            lines.extend(wrapped or [""])
        return lines

    def _header(self, title: str, status: str, width: int, frame: FrameCharacters) -> str:
        inner = width - 2
        separator = "·" if frame is UNICODE_FRAME else "-"
        prefix = f"{frame.horizontal} PDLt {separator} {title} "
        suffix = f" {status} {frame.horizontal}"
        if len(prefix) + len(suffix) > inner:
            return frame.top_left + self._fit(f" PDLt {separator} {title} {separator} {status} ", inner) + frame.top_right
        return frame.top_left + prefix + frame.horizontal * (inner - len(prefix) - len(suffix)) + suffix + frame.top_right

    @staticmethod
    def _framed(content: str, width: int, frame: FrameCharacters) -> str:
        if frame is ASCII_FRAME:
            content = (
                content.replace("·", "-")
                .replace("…", "...")
                .replace("–", "-")
                .replace("↑↓", "Up/Down")
                .encode("ascii", errors="replace")
                .decode("ascii")
            )
        return f"{frame.vertical} {TerminalReviewApp._fit(content, width - 4)} {frame.vertical}"

    def _render(self, projection: dict[str, Any]) -> None:
        stage = projection["stage"]
        if stage in TERMINAL_STAGES:
            raise RuntimeError("terminal projections restore the terminal without rendering a review screen")
        artifact = projection.get("artifact")
        actions = projection.get("actions") or []
        width, height = self._terminal_size()
        frame = self._frame_characters()
        inner = width - 4
        artifact_lines = self._wrap(artifact["body"] if artifact else "", inner)
        self.artifact_page_size = max(1, height - (12 + len(actions)))
        self.artifact_offset = min(self.artifact_offset, max(len(artifact_lines) - self.artifact_page_size, 0))
        visible_artifact = artifact_lines[self.artifact_offset : self.artifact_offset + self.artifact_page_size]
        artifact_label = artifact["title"] if artifact else "Authoritative Artifact"
        if len(artifact_lines) > self.artifact_page_size:
            indicator = f"{self.artifact_offset + 1}-{self.artifact_offset + len(visible_artifact)} / {len(artifact_lines)}"
            artifact_label = self._fit(artifact_label, max(1, inner - len(indicator) - 1)).rstrip() + " " + indicator

        lines = [self._header(self._title(stage), "ACTIVE", width, frame)]
        lines += [
            self._framed("", width, frame),
            self._framed(artifact_label, width, frame),
            self._framed(frame.horizontal * inner, width, frame),
        ]
        lines.extend(self._framed(line, width, frame) for line in visible_artifact)
        lines += [self._framed("", width, frame), self._framed("Review Options", width, frame), self._framed("", width, frame)]
        for index, action in enumerate(actions):
            prefix = f" {'>' if index == self.focus_index else ' '} {action['ordinal']}  "
            action_lines = self._wrap(action["label"], max(1, inner - len(prefix)))
            lines.append(self._framed(prefix + action_lines[0], width, frame))
            lines.extend(self._framed(" " * len(prefix) + line, width, frame) for line in action_lines[1:])
        if self.notice:
            lines.append(self._framed("", width, frame))
            lines.extend(self._framed(line, width, frame) for line in self._wrap(self.notice, inner))
        lines.append(frame.tee_left + frame.horizontal * (width - 2) + frame.tee_right)
        if self.free_response_active:
            lines.extend(self._framed(line, width, frame) for line in self._wrap(f"Review > {self.free_response_text}", inner))
            lines.append(frame.tee_left + frame.horizontal * (width - 2) + frame.tee_right)
            help_text = "Enter  Submit review     Esc  Return to actions     Ctrl+Q  Close"
        else:
            arrows = "↑↓" if frame is UNICODE_FRAME else "Up/Down"
            help_text = f"{arrows} / Tab  Move     Enter  Select     F5  Refresh     Ctrl+Q  Close"
        lines.extend(self._framed(line, width, frame) for line in self._wrap(help_text, inner))
        lines.append(frame.bottom_left + frame.horizontal * (width - 2) + frame.bottom_right)
        self.stdout.write(f"{ESC}[2J{ESC}[H" + "\n".join(lines) + "\n")
        self.stdout.flush()

    @staticmethod
    def _action_envelope(projection: dict[str, Any], action_id: str) -> dict[str, Any]:
        return {
            "schema_version": "r6o-input-envelope-1",
            "session_id": projection["session_id"],
            "source": "STRUCTURED_ACTION",
            "model_revision": projection["model_revision"],
            "text": None,
            "action_id": action_id,
            "projection_id": projection["projection_id"],
        }

    @staticmethod
    def _text_envelope(projection: dict[str, Any], text: str) -> dict[str, Any]:
        return {
            "schema_version": "r6o-input-envelope-1",
            "session_id": projection["session_id"],
            "source": "TUI_TEXT",
            "model_revision": projection["model_revision"],
            "text": text,
            "action_id": None,
            "projection_id": None,
        }

    def _apply_result(self, result: dict[str, Any], projection: dict[str, Any]) -> dict[str, Any]:
        validate_command_result(result)
        if result["result_type"] == "FOCUS_REQUIRED":
            self.free_response_active = True
            self.free_response_text = ""
            self.notice = None
            return projection
        if result["result_type"] == "STALE_PROJECTION" and result.get("projection"):
            self.notice = "State changed. Refreshed the authoritative review."
            self.free_response_active = False
            self.free_response_text = ""
            return result["projection"]
        if not result["ok"]:
            self.notice = (result.get("error") or {}).get("message") or "Review action failed."
            return projection
        self.notice = None
        self.free_response_active = False
        self.free_response_text = ""
        self.focus_index = 0
        self.artifact_offset = 0
        return result["projection"]

    def run(self, initial_projection: dict[str, Any]) -> dict[str, Any]:
        projection = initial_projection
        self.on_projection("START", None, projection)
        with terminal_session(self.stdin, self.stdout):
            while True:
                if projection["stage"] in TERMINAL_STAGES:
                    return projection
                actions = projection.get("actions") or []
                if not actions:
                    raise RuntimeError(f"stage {projection['stage']} has no projected actions")
                self.focus_index = min(self.focus_index, len(actions) - 1)
                self._render(projection)
                event = self.input.read()
                if event.name in {"EOF", "INTERRUPT"}:
                    raise KeyboardInterrupt("terminal review interrupted")
                if event.name == "CLOSE":
                    raise TerminalViewClosed
                if self.free_response_active:
                    if event.name == "ESCAPE":
                        self.free_response_active = False
                        self.free_response_text = ""
                        self.notice = None
                    elif event.name == "BACKSPACE":
                        self.free_response_text = self.free_response_text[:-1]
                    elif event.name == "TEXT" and event.text and event.text.isprintable():
                        self.free_response_text += event.text
                    elif event.name == "ENTER":
                        if not self.free_response_text.strip():
                            self.notice = "Review text is required before submission."
                        else:
                            result = handle_input(self._text_envelope(projection, self.free_response_text), self.port)
                            projection = self._apply_result(result, projection)
                            if result.get("ok") and result.get("projection"):
                                self.on_projection("TEXT", None, projection)
                    continue
                if event.name in {"DOWN", "NEXT"}:
                    self.focus_index = (self.focus_index + 1) % len(actions)
                elif event.name in {"UP", "PREVIOUS"}:
                    self.focus_index = (self.focus_index - 1) % len(actions)
                elif event.name == "PAGE_UP":
                    self.artifact_offset = max(0, self.artifact_offset - self.artifact_page_size)
                elif event.name == "PAGE_DOWN":
                    self.artifact_offset += self.artifact_page_size
                elif event.name == "REFRESH":
                    projection = build_focus_projection_from_port(self.port, self.session_id)
                    self.notice = None
                elif event.name == "ENTER":
                    action = actions[self.focus_index]
                    if not action["enabled"]:
                        self.notice = "That review option is unavailable."
                        continue
                    action_id = action["action_id"]
                    result = handle_input(self._action_envelope(projection, action_id), self.port)
                    projection = self._apply_result(result, projection)
                    if result.get("result_type") == "FOCUS_REQUIRED" and result.get("ok"):
                        self.on_projection("FOCUS", action_id, projection)
                    elif result.get("ok") and result.get("projection"):
                        self.on_projection("ACTION", action_id, projection)
