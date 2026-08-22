from __future__ import annotations

"""TUI console loop. View-only: closing or quitting never touches the session."""

import sys
from typing import Any


def run(controller: Any, input_stream: Any = None, output_stream: Any = None) -> None:
    input_stream = input_stream or sys.stdin
    output_stream = output_stream or sys.stdout
    while not controller.closed:
        output_stream.write("\n" + controller.render() + "\n")
        output_stream.flush()
        try:
            raw = input_stream.readline()
        except KeyboardInterrupt:
            controller.close_view()
            continue
        if raw == "":
            controller.close_view()
            continue
        line = raw.rstrip("\r\n")
        if line == "":
            if controller.focus_mode:
                controller.notice = "type your review input"
            else:
                controller.focus_free_response()
            continue
        if controller.focus_mode:
            controller.submit_text(line)
            continue
        command = line.strip().lower()
        if command in {"q", "quit", "exit"}:
            controller.close_view()
            continue
        if command in {"r", "refresh"}:
            controller.refresh()
            continue
        if command in {"u", "up"}:
            controller.scroll_artifact(-3)
            continue
        if command in {"d", "down"}:
            controller.scroll_artifact(3)
            continue
        if line.strip().isdigit():
            controller.select_action(int(line.strip()))
            continue
        controller.submit_text(line)
