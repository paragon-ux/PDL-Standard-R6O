from __future__ import annotations

"""Persistent terminal UI event loop."""

from r6o.views.tui.controller import TuiController
from r6o.views.tui.terminal import TerminalDriver


class TuiApplication:
    def __init__(self, controller: TuiController, driver: TerminalDriver | None = None) -> None:
        self.controller = controller
        self.driver = driver or TerminalDriver()

    def run(self) -> None:
        previous_size: tuple[int, int] | None = None
        with self.driver:
            while not self.controller.closed:
                size = self.driver.size()
                if self.controller.dirty or size != previous_size:
                    self.driver.draw(self.controller.render(*size))
                    self.controller.dirty = False
                    previous_size = size
                key = self.driver.read_key(0.1)
                if key is not None:
                    self.controller.handle_key(key)
