from __future__ import annotations

"""Opt-in display-dependent Sidecar checks (R6O2_RUN_DISPLAY_TESTS=1)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ROOT_SLASH = str(ROOT).replace("\\", "/")

pytestmark = pytest.mark.skipif(
    os.environ.get("R6O2_RUN_DISPLAY_TESTS") != "1",
    reason="display-dependent; set R6O2_RUN_DISPLAY_TESTS=1 on a machine with a display",
)

PREAMBLE = "\n".join(
    [
        "import sys",
        "sys.path.insert(0, '" + ROOT_SLASH + "')",
        "from r6o.model_binding.memory_model import StaticModelPort",
        "from r6o.presentation_transport import PresentationAdapter",
        "from r6o.tests.helpers import artifact, state",
        "from r6o.views.sidecar.model import SidecarModel",
        "from r6o.views.sidecar.app import HarnessShell, TkSidecarView",
        "def make_model():",
        "    return SidecarModel(PresentationAdapter(StaticModelPort(state(), {'prompt:P1': artifact()})), 'I-1')",
        "",
    ]
)


def _run(code: str) -> None:
    proc = subprocess.run(
        [sys.executable, "-c", PREAMBLE + code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_harness_renders_actions_and_composer() -> None:
    _run(
        "s = HarnessShell(make_model())\n"
        "s.root.update()\n"
        "assert len(s.panel._buttons) == 4\n"
        "assert s.composer_entry.winfo_ismapped()\n"
        "s.root.destroy()\n"
        "print('OK')\n"
    )


def test_toggle_reapplies_geometry() -> None:
    _run(
        "s = HarnessShell(make_model())\n"
        "s.root.update_idletasks()\n"
        "s.panel._toggle_mode()\n"
        "s.root.update_idletasks()\n"
        "assert s.model.mode == 'EXPANDED'\n"
        "s.root.destroy()\n"
        "print('OK')\n"
    )


def test_close_hides_panel_only_and_reopen_restores() -> None:
    _run(
        "s = HarnessShell(make_model())\n"
        "s.root.update_idletasks()\n"
        "s.panel._close()\n"
        "s.root.update_idletasks()\n"
        "assert not s.panel.winfo_ismapped()\n"
        "assert s.root.winfo_ismapped()\n"
        "s._show_panel()\n"
        "s.root.update_idletasks()\n"
        "assert s.panel.winfo_ismapped()\n"
        "s.root.destroy()\n"
        "print('OK')\n"
    )


def test_standalone_geometry_modes() -> None:
    _run(
        "model = make_model()\n"
        "v = TkSidecarView(model)\n"
        "v.root.update_idletasks()\n"
        "w0 = v.root.winfo_width()\n"
        "model.mode = 'EXPANDED'\n"
        "v._apply_geometry()\n"
        "v.root.update_idletasks()\n"
        "assert v.root.winfo_width() > w0\n"
        "v.root.destroy()\n"
        "print('OK')\n"
    )
