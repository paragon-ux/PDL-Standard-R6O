from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from r6o.host.codex.windows import input_binding as input_binding_module
from r6o.host.codex.windows.input_binding import (
    CodexComposerInputBinding,
    CodexInputBindingError,
    VK_SHIFT,
    WM_KEYDOWN,
    WM_KEYUP,
)


ROOT = Path(__file__).resolve().parents[3]


def projection(*, projection_id: str = "f2-projection", body: str = "# F2\n") -> dict[str, Any]:
    return {
        "schema_version": "r6o-focus-projection-1",
        "session_id": "f2-session",
        "workspace_id": "f2-workspace",
        "model_revision": "f2-model-revision",
        "projection_id": projection_id,
        "interaction_state": "REVIEW_REQUIRED",
        "model_response": None,
        "stage": "PROMPT_REVIEW",
        "focus_kind": "PROMPT_REVIEW",
        "artifact": {
            "artifact_ref": "f2:prompt",
            "artifact_revision": "f2-artifact-revision",
            "artifact_kind": "prompt",
            "title": "F2 prompt",
            "media_type": "text/markdown",
            "body": body,
            "capabilities": {"copy": True, "open_external": False},
        },
        "actions": [
            {
                "action_id": "confirm_prompt",
                "label": "Confirm prompt",
                "ordinal": 1,
                "kind": "SEMANTIC_MESSAGE",
                "enabled": True,
            },
            {
                "action_id": "something_else",
                "label": "Something else...",
                "ordinal": 2,
                "kind": "FREE_RESPONSE_FOCUS",
                "enabled": True,
            },
        ],
        "lifecycle": {
            "review_required": True,
            "terminal": False,
            "close_allowed": True,
            "handoff_ready": False,
            "terminal_disposition": None,
            "result_body": None,
            "authorized_handoff_artifacts": [],
        },
    }


class FakeUser32:
    def __init__(self, *, foreground: int = 101, modifiers: set[int] | None = None) -> None:
        self.foreground = foreground
        self.modifiers = modifiers or set()

    def GetForegroundWindow(self) -> int:
        return self.foreground

    def GetAsyncKeyState(self, key: int) -> int:
        return 0x8000 if key in self.modifiers else 0


def input_binding(
    *, focused: bool = True, text: str = "F2 captured text", on_envelope: Any | None = None
) -> CodexComposerInputBinding:
    host = SimpleNamespace(host_hwnd=101, sidecar_hwnd=303)
    binding = CodexComposerInputBinding(
        host,
        on_envelope or (lambda _envelope: None),
        focus_probe=lambda: focused,
        text_probe=lambda: text,
    )
    binding._active_projection = projection()
    binding._armed = True
    return binding


def test_unmodified_enter_owns_the_complete_pair_and_delivers_once() -> None:
    envelopes: list[dict[str, Any]] = []
    binding = input_binding(on_envelope=envelopes.append)
    binding._clear_actual_composer = lambda: None  # type: ignore[method-assign]
    user32 = FakeUser32()

    assert binding._handle_key_event(user32, 0x0D, WM_KEYDOWN) is True
    assert binding._handle_key_event(user32, 0x0D, WM_KEYDOWN) is True
    assert binding._handle_key_event(user32, 0x0D, WM_KEYUP) is True

    capture = binding._captures.get_nowait()
    binding._deliver_capture(capture)

    assert binding.capture_count == 1
    assert binding.delivery_count == 1
    assert envelopes[0]["source"] == "HOST_COMPOSER_TEXT"
    assert envelopes[0]["text"] == "F2 captured text"
    assert binding.delivery_pending is False


def test_shift_enter_and_unrelated_foreground_are_not_captured() -> None:
    shift_binding = input_binding()
    shift_user32 = FakeUser32(modifiers={VK_SHIFT})
    assert shift_binding._handle_key_event(shift_user32, 0x0D, WM_KEYDOWN) is False
    assert shift_binding._handle_key_event(shift_user32, 0x0D, WM_KEYUP) is False
    assert shift_binding.capture_count == 0

    unrelated = input_binding()
    other_window = FakeUser32(foreground=999)
    assert unrelated._handle_key_event(other_window, 0x0D, WM_KEYDOWN) is False
    assert unrelated._handle_key_event(other_window, 0x0D, WM_KEYUP) is False
    assert unrelated.capture_count == 0


def test_focus_failure_suppresses_key_pair_and_fails_closed() -> None:
    binding = input_binding(focused=False)
    user32 = FakeUser32()

    assert binding._handle_key_event(user32, 0x0D, WM_KEYDOWN) is True
    assert binding._handle_key_event(user32, 0x0D, WM_KEYUP) is True

    assert binding.last_error == "ACTUAL_COMPOSER_FOCUS_UNVERIFIED_AT_ENTER"
    assert binding.capture_count == 0
    with pytest.raises(CodexInputBindingError, match="ACTUAL_COMPOSER_FOCUS_UNVERIFIED_AT_ENTER"):
        binding.assert_healthy()


def test_orphaned_native_hook_is_removed_even_without_a_live_thread() -> None:
    binding = input_binding()
    removed: list[int] = []

    class User32:
        def UnhookWindowsHookEx(self, handle: object) -> bool:
            removed.append(int(getattr(handle, "value", handle)))
            return True

    binding._hook = 456
    binding._hook_user32 = User32()
    binding.stop()

    assert removed == [456]
    assert binding._hook == 0
    assert binding._dispatcher is None


def test_clean_stop_allows_a_fresh_input_hook_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(input_binding_module.os, "name", "nt")
    binding = input_binding()

    class FakeThread:
        def __init__(self, target: Any, **_: Any) -> None:
            self.target = target
            self.alive = False

        def start(self) -> None:
            self.alive = True
            self.target()

        def join(self, timeout: float) -> None:
            assert timeout == 5.0
            self.alive = False

        def is_alive(self) -> bool:
            return self.alive

    monkeypatch.setattr(input_binding_module.threading, "Thread", FakeThread)
    monkeypatch.setattr(binding, "_install_dispatcher", lambda: setattr(binding, "_dispatcher", object()))
    monkeypatch.setattr(binding, "_run_keyboard_hook", lambda: binding._ready.set())

    binding.start()
    binding.stop()
    binding.start()
    binding.stop()

    assert binding.last_error is None
    assert binding._hook_thread is None
    assert binding._dispatcher is None


def test_pending_delivery_timeout_is_reported_after_cleanup() -> None:
    binding = input_binding()
    binding._delivery_pending = True
    binding._dispatcher = object()

    def fail_wait(timeout: float) -> dict[str, Any]:
        assert timeout == 5.0
        raise CodexInputBindingError("HOST_COMPOSER_ENVELOPE_TIMEOUT")

    binding.wait_for_delivery = fail_wait  # type: ignore[method-assign]
    with pytest.raises(CodexInputBindingError, match="HOST_COMPOSER_ENVELOPE_TIMEOUT"):
        binding.stop()

    assert binding._delivery_pending is False
    assert binding._dispatcher is None


def test_lifecycle_verifier_help_is_portable() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "h2" / "verify_h2_lifecycle_resilience.py"), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "lifecycle" in result.stdout.lower()


def test_qt_close_is_idempotent_and_active_projection_can_reopen() -> None:
    pytest.importorskip("PySide6")
    from r6o.views.sidecar import QtSidecarWindow

    sidecar = QtSidecarWindow()
    try:
        first = projection(projection_id="f2-first")
        second = projection(projection_id="f2-second", body="# Current F2 projection\n")
        assert sidecar.render(first) is True
        assert sidecar.bridge.projectionId == "f2-first"
        sidecar.close_view()
        assert sidecar.window.isVisible() is False

        assert sidecar.render(second) is True
        assert sidecar.bridge.projectionId == "f2-second"
    finally:
        sidecar.close()
        sidecar.close()

    with pytest.raises(RuntimeError, match="SIDECAR_WINDOW_CLOSED"):
        sidecar.render(projection())


def test_qt_close_callback_failure_can_be_retried() -> None:
    pytest.importorskip("PySide6")
    from r6o.views.sidecar import QtSidecarWindow

    attempts: list[int] = []

    def close_callback() -> None:
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("focus callback unavailable")

    sidecar = QtSidecarWindow(on_close_view=close_callback)
    try:
        assert sidecar.render(projection()) is True
        with pytest.raises(RuntimeError, match="focus callback unavailable"):
            sidecar.close_view()
        sidecar.close_view()
        assert len(attempts) == 2
    finally:
        sidecar.close()
