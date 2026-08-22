from __future__ import annotations

"""Small cross-platform terminal driver for a persistent raw-key event loop."""

import os
import select
import shutil
import sys
import time
from typing import TextIO


class TerminalDriver:
    def __init__(self, input_stream: TextIO | None = None, output_stream: TextIO | None = None) -> None:
        self.input = input_stream or sys.stdin
        self.output = output_stream or sys.stdout
        self._saved_terminal = None

    @property
    def interactive(self) -> bool:
        return bool(self.input.isatty() and self.output.isatty())

    def __enter__(self) -> "TerminalDriver":
        if not self.interactive:
            raise RuntimeError("R6O-2 TUI requires an interactive terminal")
        if os.name == "nt" and hasattr(self.output, "reconfigure"):
            self.output.reconfigure(encoding="utf-8", errors="replace")
        if os.name != "nt":
            import termios
            import tty

            descriptor = self.input.fileno()
            self._saved_terminal = termios.tcgetattr(descriptor)
            tty.setcbreak(descriptor)
        else:
            os.system("")
        self.output.write("\x1b[?1049h\x1b[?25l\x1b[2J\x1b[H")
        self.output.flush()
        return self

    def __exit__(self, *_args: object) -> None:
        if self._saved_terminal is not None:
            import termios

            termios.tcsetattr(
                self.input.fileno(), termios.TCSADRAIN, self._saved_terminal
            )
        self.output.write("\x1b[?25h\x1b[?1049l")
        self.output.flush()

    def size(self) -> tuple[int, int]:
        size = shutil.get_terminal_size((100, 30))
        return size.columns, size.lines

    def draw(self, screen: str) -> None:
        self.output.write("\x1b[H\x1b[2J" + screen)
        self.output.flush()

    def read_key(self, timeout: float = 0.1) -> str | None:
        if os.name == "nt":
            return self._read_windows(timeout)
        return self._read_posix(timeout)

    @staticmethod
    def _read_windows(timeout: float) -> str | None:
        import msvcrt

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not msvcrt.kbhit():
                time.sleep(0.01)
                continue
            value = msvcrt.getwch()
            if value in {"\x00", "\xe0"}:
                code = msvcrt.getwch()
                return {
                    "H": "UP",
                    "P": "DOWN",
                    "K": "LEFT",
                    "M": "RIGHT",
                    "I": "PAGE_UP",
                    "Q": "PAGE_DOWN",
                    "G": "HOME",
                    "O": "END",
                    "S": "DELETE",
                    "?": "F5",
                }.get(code)
            return _translate_character(value)
        return None

    def _read_posix(self, timeout: float) -> str | None:
        ready, _, _ = select.select([self.input], [], [], timeout)
        if not ready:
            return None
        value = self.input.read(1)
        if value != "\x1b":
            return _translate_character(value)
        sequence = value
        while select.select([self.input], [], [], 0.01)[0]:
            sequence += self.input.read(1)
        return {
            "\x1b[A": "UP",
            "\x1b[B": "DOWN",
            "\x1b[C": "RIGHT",
            "\x1b[D": "LEFT",
            "\x1b[5~": "PAGE_UP",
            "\x1b[6~": "PAGE_DOWN",
            "\x1b[H": "HOME",
            "\x1b[F": "END",
            "\x1b[3~": "DELETE",
            "\x1b[15~": "F5",
            "\x1b[Z": "SHIFT_TAB",
        }.get(sequence, "ESC")


def _translate_character(value: str) -> str:
    return {
        "\x03": "CTRL_C",
        "\x11": "CTRL_Q",
        "\t": "TAB",
        "\r": "ENTER",
        "\n": "ENTER",
        "\x08": "BACKSPACE",
        "\x7f": "BACKSPACE",
    }.get(value, value)
