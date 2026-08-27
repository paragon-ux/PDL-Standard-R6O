from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import threading
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
            binding._hook = 0

        def is_alive(self) -> bool:
            return self.alive

    monkeypatch.setattr(input_binding_module.threading, "Thread", FakeThread)
    monkeypatch.setattr(binding, "_install_dispatcher", lambda: setattr(binding, "_dispatcher", object()))
    def install_verified_hook() -> None:
        binding._hook = 701
        binding._ready.set()

    monkeypatch.setattr(binding, "_run_keyboard_hook", install_verified_hook)

    binding.start()
    binding.stop()
    binding.start()
    binding.stop()

    assert binding.last_error is None
    assert binding._hook_thread is None
    assert binding._dispatcher is None


def test_pending_delivery_timeout_invalidates_stale_callback_across_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelopes: list[dict[str, Any]] = []
    clears: list[str] = []
    binding = input_binding(on_envelope=envelopes.append)
    binding._clear_actual_composer = lambda: clears.append("clear")  # type: ignore[method-assign]
    user32 = FakeUser32()
    assert binding._handle_key_event(user32, 0x0D, WM_KEYDOWN) is True
    assert binding._handle_key_event(user32, 0x0D, WM_KEYUP) is True
    capture = binding._captures.get_nowait()
    assert capture is not None
    binding._dispatcher = object()

    def fail_wait(timeout: float) -> dict[str, Any]:
        assert timeout == 5.0
        raise CodexInputBindingError("HOST_COMPOSER_ENVELOPE_TIMEOUT")

    binding.wait_for_delivery = fail_wait  # type: ignore[method-assign]
    with pytest.raises(CodexInputBindingError, match="HOST_COMPOSER_ENVELOPE_TIMEOUT"):
        binding.stop()

    assert binding._delivery_pending is False
    assert binding._delivery_cancelled is True
    assert binding._dispatcher is None
    assert clears == ["clear"]
    assert envelopes == []

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
            binding._hook = 0

        def is_alive(self) -> bool:
            return self.alive

    monkeypatch.setattr(input_binding_module.os, "name", "nt")
    monkeypatch.setattr(input_binding_module.threading, "Thread", FakeThread)
    monkeypatch.setattr(binding, "_install_dispatcher", lambda: setattr(binding, "_dispatcher", object()))

    def install_verified_hook() -> None:
        binding._hook = 702
        binding._ready.set()

    monkeypatch.setattr(binding, "_run_keyboard_hook", install_verified_hook)
    binding.start()
    binding._delivery_event.clear()

    # A callback retained by Qt from the prior cycle must be entirely inert.
    binding._deliver_capture(capture)
    assert clears == ["clear"]
    assert envelopes == []
    assert binding._delivery_event.is_set() is False
    binding.stop()


def test_delivery_cancellation_serializes_composer_mutation_before_stale_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelopes: list[dict[str, Any]] = []
    composer = {"text": "attempt-owned text"}
    clears: list[str] = []
    callback_before_mutation = threading.Event()
    resume_stale_callback = threading.Event()
    binding = input_binding(on_envelope=envelopes.append)

    def clear_composer() -> None:
        clears.append(composer["text"])
        composer["text"] = ""

    binding._clear_actual_composer = clear_composer  # type: ignore[method-assign]
    user32 = FakeUser32()
    assert binding._handle_key_event(user32, 0x0D, WM_KEYDOWN) is True
    assert binding._handle_key_event(user32, 0x0D, WM_KEYUP) is True
    capture = binding._captures.get_nowait()
    assert capture is not None
    binding._dispatcher = object()
    original_builder = input_binding_module.build_host_composer_envelope

    def blocked_builder(active_projection: dict[str, Any], text: str) -> dict[str, Any]:
        callback_before_mutation.set()
        assert resume_stale_callback.wait(timeout=5.0)
        return original_builder(active_projection, text)

    monkeypatch.setattr(input_binding_module, "build_host_composer_envelope", blocked_builder)
    callback = threading.Thread(target=binding._deliver_capture, args=(capture,))
    callback.start()
    assert callback_before_mutation.wait(timeout=5.0)

    binding.abort_handoff()

    assert clears == ["attempt-owned text"]
    assert composer["text"] == ""
    with binding._state_lock:
        current_token = binding._delivery_token + 1
        binding._delivery_cancelled = False
        binding._delivery_pending = True
        binding._pending_delivery_token = current_token
        binding._delivery_token = current_token
    binding._delivery_event.clear()
    composer["text"] = "new user text"
    resume_stale_callback.set()
    callback.join(timeout=5.0)

    assert callback.is_alive() is False
    assert composer["text"] == "new user text"
    assert clears == ["attempt-owned text"]
    assert envelopes == []
    assert binding._delivery_event.is_set() is False
    with binding._state_lock:
        assert binding._delivery_pending is True
        assert binding._pending_delivery_token == current_token
        assert binding._delivery_token == current_token


def test_failed_hook_shutdown_cannot_restart_from_stale_thread_liveness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StuckThread:
        def join(self, timeout: float) -> None:
            assert timeout == 5.0

        def is_alive(self) -> bool:
            return True

    binding = input_binding()
    binding._hook_thread = StuckThread()  # type: ignore[assignment]
    binding._hook = 801
    binding._hook_user32 = object()

    def remove_hook(_user32: object) -> bool:
        binding._hook = 0
        return True

    binding._remove_keyboard_hook = remove_hook  # type: ignore[method-assign]
    with pytest.raises(CodexInputBindingError, match="HOST_INPUT_HOOK_STOP_TIMEOUT"):
        binding.stop()

    assert binding._hook == 0
    assert binding._hook_thread is not None
    monkeypatch.setattr(input_binding_module.os, "name", "nt")
    with pytest.raises(CodexInputBindingError, match="HOST_INPUT_HOOK_RESTART_BLOCKED"):
        binding.start()

    # Even corrupted teardown provenance cannot make hookless liveness STARTED.
    binding._teardown_pending = False
    with pytest.raises(CodexInputBindingError, match="HOST_INPUT_HOOK_RESTART_BLOCKED"):
        binding.start()


def test_enter_keyup_timeout_retains_hook_ownership_until_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class PairEvent:
        complete = False

        def wait(self, timeout: float) -> bool:
            assert timeout == 5.0
            return self.complete

        def set(self) -> None:
            self.complete = True

        def clear(self) -> None:
            self.complete = False

    class OwningThread:
        alive = True
        joins = 0

        def join(self, timeout: float) -> None:
            assert timeout == 5.0
            self.joins += 1
            self.alive = False
            binding._hook = 0

        def is_alive(self) -> bool:
            return self.alive

    binding = input_binding()
    pair_event = PairEvent()
    thread = OwningThread()
    binding._enter_pair_complete = pair_event  # type: ignore[assignment]
    binding._enter_down = True
    binding._hook_thread = thread  # type: ignore[assignment]
    binding._hook = 901
    binding._dispatcher = object()

    with pytest.raises(CodexInputBindingError, match="HOST_ENTER_KEYUP_DRAIN_TIMEOUT"):
        binding.stop()

    assert binding._stop.is_set() is False
    assert binding._hook == 901
    assert thread.joins == 0
    assert binding._teardown_pending is True
    assert binding._dispatcher is None

    monkeypatch.setattr(input_binding_module.os, "name", "nt")
    with pytest.raises(CodexInputBindingError, match="HOST_INPUT_HOOK_RESTART_BLOCKED"):
        binding.start()

    assert binding._handle_key_event(FakeUser32(), 0x0D, WM_KEYUP) is True
    assert binding._enter_down is False
    assert binding.suppressed_keyup_count == 1

    binding.stop()
    assert binding._hook == 0
    assert binding._hook_thread is None
    assert binding._teardown_pending is False


def test_lifecycle_verifier_help_is_portable() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "h2" / "verify_h2_lifecycle_resilience.py"), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "lifecycle" in result.stdout.lower()


def test_lifecycle_process_exit_probe_cleans_resources_and_terminates() -> None:
    pytest.importorskip("PySide6")
    environment = os.environ.copy()
    environment.setdefault("QT_QPA_PLATFORM", "offscreen")
    environment.setdefault("QT_QUICK_BACKEND", "software")
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "h2" / "verify_h2_lifecycle_resilience.py"),
            "--process-exit-probe",
            "portable",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30.0,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    prefix = "H2_F2_PROCESS_EXIT_CLEANUP_COMPLETE="
    marker_lines = [line for line in result.stdout.splitlines() if line.startswith(prefix)]
    assert len(marker_lines) == 1
    marker = json.loads(marker_lines[0][len(prefix) :])
    assert marker["status"] == "PASS"
    assert marker["cleanup_complete"] is True
    assert marker["probe_mode"] == "portable"


def _valid_matrix_facts() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    input_facts = {
        "normal_activation_deactivation": True,
        "repeated_activation_deactivation": 2,
        "partial_activation_failure_cleanup": True,
        "pending_delivery_teardown": True,
        "stale_queued_delivery_inert": True,
        "failed_hook_thread_shutdown": "HOST_INPUT_HOOK_STOP_TIMEOUT",
        "restart_after_failed_shutdown": "HOST_INPUT_HOOK_RESTART_BLOCKED",
        "enter_keyup_timeout_retains_ownership": True,
        "retry_after_delayed_keyup": True,
        "delivery_cancellation_race": {
            "status": "PASS",
            "new_user_text_preserved": True,
            "destructive_clear_count": 1,
            "envelope_count": 0,
            "current_delivery_state_preserved": True,
            "current_delivery_event_preserved": True,
        },
    }
    qt_facts = {
        "partial_close_failure": "EXERCISED",
        "partial_close_retry": True,
        "repeated_successful_close_reopen": True,
        "close_view_hide_failure_retry": {
            "hide_attempts": 2,
            "notification_count": 1,
            "close_notified": True,
        },
    }
    process_facts = {
        "status": "PASS",
        "probe_mode": "portable",
        "cleanup_complete_marker": True,
        "process_terminated": True,
        "returncode": 0,
    }
    return input_facts, qt_facts, process_facts


@pytest.mark.parametrize(
    ("fact_group", "missing_key"),
    [
        ("input", "delivery_cancellation_race"),
        ("qt", "close_view_hide_failure_retry"),
        ("process", "cleanup_complete_marker"),
    ],
)
def test_resilience_matrix_fails_closed_when_executed_proof_is_missing(
    fact_group: str,
    missing_key: str,
) -> None:
    from scripts.h2.verify_h2_lifecycle_resilience import (
        F2VerificationError,
        derive_repair_resilience_matrix,
    )

    input_facts, qt_facts, process_facts = copy.deepcopy(_valid_matrix_facts())
    groups = {"input": input_facts, "qt": qt_facts, "process": process_facts}
    groups[fact_group].pop(missing_key)
    with pytest.raises(F2VerificationError, match="RESILIENCE_MATRIX_DIMENSION_INSUFFICIENT"):
        derive_repair_resilience_matrix(input_facts, qt_facts, process_facts)


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

    replacement = QtSidecarWindow()
    try:
        assert replacement.render(projection(projection_id="f2-replacement")) is True
        assert replacement.bridge.projectionId == "f2-replacement"
    finally:
        replacement.close()
        replacement.close()


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


def test_qt_close_hide_failure_can_be_retried() -> None:
    pytest.importorskip("PySide6")
    from r6o.views.sidecar import qt_app

    class Window:
        attempts = 0

        def hide(self) -> None:
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("hide unavailable")

    class Bridge:
        notifications = 0

        def notify_closed(self) -> None:
            self.notifications += 1

    sidecar = qt_app.QtSidecarWindow.__new__(qt_app.QtSidecarWindow)
    sidecar._tearing_down = False
    sidecar._closed = False
    sidecar._close_notified = False
    window = Window()
    bridge = Bridge()
    sidecar.window = window
    sidecar.bridge = bridge

    with pytest.raises(RuntimeError, match="hide unavailable"):
        sidecar.close_view()
    assert sidecar._close_notified is False

    sidecar.close_view()
    sidecar.close_view()
    assert window.attempts == 2
    assert bridge.notifications == 1
    assert sidecar._close_notified is True


def test_qt_partial_terminal_cleanup_failure_remains_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("PySide6")
    from r6o.views.sidecar import qt_app

    calls: list[str] = []

    class Resource:
        def __init__(self, name: str) -> None:
            self.name = name

        def hide(self) -> None:
            calls.append(f"{self.name}.hide")

        def deleteLater(self) -> None:
            calls.append(f"{self.name}.deleteLater")

    class App:
        attempts = 0

        def processEvents(self) -> None:
            self.attempts += 1
            calls.append("app.processEvents")
            if self.attempts == 1:
                raise RuntimeError("event processing unavailable")

    sidecar = qt_app.QtSidecarWindow.__new__(qt_app.QtSidecarWindow)
    sidecar._close_notified = False
    sidecar._tearing_down = False
    sidecar._closed = False
    sidecar._window_hidden = False
    sidecar._window_delete_scheduled = False
    sidecar._engine_delete_scheduled = False
    sidecar._deferred_deletes_sent = False
    sidecar._cleanup_events_processed = False
    sidecar.window = Resource("window")
    sidecar.engine = Resource("engine")
    app = App()
    monkeypatch.setattr(qt_app, "ensure_application", lambda: app)

    with pytest.raises(RuntimeError, match="event processing unavailable"):
        sidecar.close()
    assert sidecar._closed is False
    assert sidecar._tearing_down is True

    sidecar.close()
    sidecar.close()
    assert sidecar._closed is True
    assert calls == [
        "window.hide",
        "window.deleteLater",
        "engine.deleteLater",
        "app.processEvents",
        "app.processEvents",
    ]
