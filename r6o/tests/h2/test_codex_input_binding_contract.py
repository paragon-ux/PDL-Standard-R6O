from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys

import pytest

from r6o.host.codex.windows.input_binding import (
    CodexComposerInputBinding,
    CodexInputBindingError,
    VK_SHIFT,
    WM_KEYDOWN,
    WM_KEYUP,
    build_host_composer_envelope,
    validate_active_projection_context,
)
from scripts.h2 import verify_codex_input_routing as verifier


ROOT = Path(__file__).resolve().parents[3]


def projection() -> dict[str, object]:
    return {
        "schema_version": "r6o-focus-projection-1",
        "projection_id": "projection-1",
        "session_id": "session-1",
        "model_revision": "revision-1",
    }


def test_host_composer_envelope_is_exact_option_a_text_shape() -> None:
    envelope = build_host_composer_envelope(projection(), "change the boundary")
    assert envelope == {
        "schema_version": "r6o-input-envelope-1",
        "session_id": "session-1",
        "source": "HOST_COMPOSER_TEXT",
        "model_revision": "revision-1",
        "text": "change the boundary",
        "action_id": None,
        "projection_id": None,
    }


@pytest.mark.parametrize(
    "mutation",
    [
        None,
        {},
        {"schema_version": "wrong"},
        {"schema_version": "r6o-focus-projection-1", "projection_id": ""},
    ],
)
def test_projection_context_fails_closed(mutation: object) -> None:
    with pytest.raises(CodexInputBindingError, match="ACTIVE_PROJECTION_CONTEXT_INVALID"):
        validate_active_projection_context(mutation)  # type: ignore[arg-type]


class FakeUser32:
    def __init__(self, *, foreground: int = 101, shift: bool = False) -> None:
        self.foreground = foreground
        self.shift = shift

    def GetForegroundWindow(self) -> int:
        return self.foreground

    def GetAsyncKeyState(self, key: int) -> int:
        return 0x8000 if self.shift and key == VK_SHIFT else 0


def input_binding(*, focused: bool = True, text: str = "H2E1TEXT") -> CodexComposerInputBinding:
    host = SimpleNamespace(host_hwnd=101, sidecar_hwnd=303)
    binding = CodexComposerInputBinding(
        host,
        lambda envelope: None,
        focus_probe=lambda: focused,
        text_probe=lambda: text,
    )
    binding._active_projection = projection()
    binding._armed = True
    return binding


@pytest.mark.parametrize(
    ("attach_results", "error"),
    [
        ([False], "HOST_THREAD_INPUT_ATTACH_FAILED"),
        ([True, False], "HOST_THREAD_INPUT_DETACH_FAILED"),
    ],
)
def test_sidecar_to_composer_focus_transaction_fails_closed(
    attach_results: list[bool], error: str
) -> None:
    class FocusApi:
        def __init__(self) -> None:
            self.results = iter(attach_results)

        def GetWindowLongW(self, hwnd: int, index: int) -> int:
            return 0

        def SetWindowLongW(self, hwnd: int, index: int, value: int) -> int:
            return 0

        def GetWindowThreadProcessId(self, hwnd: int, pid: object) -> int:
            return 11 if hwnd == 303 else 22

        def AttachThreadInput(self, first: int, second: int, attach: bool) -> bool:
            return next(self.results)

        def SetForegroundWindow(self, hwnd: int) -> bool:
            return True

        def SetActiveWindow(self, hwnd: int) -> int:
            return hwnd

        def GetForegroundWindow(self) -> int:
            return 101

    with pytest.raises(CodexInputBindingError, match=error):
        input_binding()._transfer_focus_from_sidecar_to_host(FocusApi())


def test_sidecar_to_composer_focus_transaction_attaches_and_detaches_once() -> None:
    calls: list[bool] = []

    class FocusApi:
        def GetWindowLongW(self, hwnd: int, index: int) -> int:
            return 0

        def SetWindowLongW(self, hwnd: int, index: int, value: int) -> int:
            return 0

        def GetWindowThreadProcessId(self, hwnd: int, pid: object) -> int:
            return 11 if hwnd == 303 else 22

        def AttachThreadInput(self, first: int, second: int, attach: bool) -> bool:
            calls.append(attach)
            return True

        def SetForegroundWindow(self, hwnd: int) -> bool:
            return True

        def SetActiveWindow(self, hwnd: int) -> int:
            return hwnd

        def GetForegroundWindow(self) -> int:
            return 101

    binding = input_binding()
    binding._transfer_focus_from_sidecar_to_host(FocusApi())
    assert calls == [True, False]
    assert binding.focus_transaction_count == 1


def test_activate_revalidates_frozen_host_before_native_focus_mutation() -> None:
    calls: list[str] = []

    class StaleHost:
        def refresh_controls(self) -> object:
            calls.append("refresh_controls")
            raise RuntimeError("stale frozen host")

    binding = CodexComposerInputBinding(StaleHost(), lambda envelope: None)  # type: ignore[arg-type]
    binding._hook_thread = object()  # type: ignore[assignment]
    binding._transfer_focus_from_sidecar_to_host = lambda: calls.append(  # type: ignore[method-assign]
        "native_focus_mutation"
    )

    with pytest.raises(RuntimeError, match="stale frozen host"):
        binding.activate(projection())

    assert calls == ["refresh_controls"]


def test_unmodified_enter_is_suppressed_and_queued_exactly_once() -> None:
    binding = input_binding()
    api = FakeUser32()
    assert binding._handle_key_event(api, 0x0D, WM_KEYDOWN) is True
    assert binding._handle_key_event(api, 0x0D, WM_KEYDOWN) is True
    assert binding._handle_key_event(api, 0x0D, WM_KEYUP) is True
    capture = binding._captures.get_nowait()
    assert capture is not None
    assert capture.text == "H2E1TEXT"
    assert capture.projection == projection()
    assert binding.capture_count == 1
    assert binding.suppressed_keydown_count == 1
    assert binding.suppressed_keyup_count == 1
    assert binding.armed is False
    assert binding._captures.empty()


def test_second_enter_is_suppressed_until_captured_text_is_cleared() -> None:
    binding = input_binding()
    api = FakeUser32()

    assert binding._handle_key_event(api, 0x0D, WM_KEYDOWN) is True
    assert binding._handle_key_event(api, 0x0D, WM_KEYUP) is True
    capture = binding._captures.get_nowait()
    assert capture is not None

    # A distinct second gesture after key-up must not escape while GUI-thread
    # delivery has not yet cleared the captured text from the real composer.
    assert binding._handle_key_event(api, 0x0D, WM_KEYDOWN) is True
    assert binding._handle_key_event(api, 0x0D, WM_KEYUP) is True
    assert binding.capture_count == 1
    assert binding.suppressed_keydown_count == 2
    assert binding.suppressed_keyup_count == 2
    assert binding._captures.empty()

    binding._clear_actual_composer = lambda: None  # type: ignore[method-assign]
    binding._deliver_capture(capture)

    # Once clearing succeeds, this one-shot binding is inactive and no longer
    # consumes a later independent host gesture.
    assert binding._handle_key_event(api, 0x0D, WM_KEYDOWN) is False
    assert binding.delivery_count == 1


def test_pending_delivery_never_suppresses_enter_in_another_window() -> None:
    binding = input_binding()
    binding._armed = False
    binding._delivery_pending = True
    api = FakeUser32(foreground=999)

    assert binding._handle_key_event(api, 0x0D, WM_KEYDOWN) is False
    assert binding._handle_key_event(api, 0x0D, WM_KEYUP) is False
    assert binding.suppressed_keydown_count == 0
    assert binding.suppressed_keyup_count == 0
    assert binding.capture_count == 0


def test_shift_enter_passes_through_as_editing_and_does_not_route() -> None:
    binding = input_binding()
    api = FakeUser32(shift=True)
    assert binding._handle_key_event(api, 0x0D, WM_KEYDOWN) is False
    assert binding._handle_key_event(api, 0x0D, WM_KEYUP) is False
    assert binding.modified_enter_passthrough_count == 1
    assert binding.capture_count == 0
    assert binding.armed is True
    assert binding._captures.empty()


def test_low_level_shift_state_is_tracked_across_keyboard_events() -> None:
    binding = input_binding()
    api = FakeUser32(shift=False)
    assert binding._handle_key_event(api, VK_SHIFT, WM_KEYDOWN) is False
    assert binding._handle_key_event(api, 0x0D, WM_KEYDOWN) is False
    assert binding._handle_key_event(api, 0x0D, WM_KEYUP) is False
    assert binding._handle_key_event(api, VK_SHIFT, WM_KEYUP) is False
    assert binding.modified_enter_passthrough_count == 1
    assert binding.capture_count == 0


def test_enter_in_another_window_is_not_captured() -> None:
    binding = input_binding()
    assert binding._handle_key_event(FakeUser32(foreground=999), 0x0D, WM_KEYDOWN) is False
    assert binding.capture_count == 0
    assert binding.armed is True


def test_empty_enter_is_suppressed_without_emitting_review_text() -> None:
    binding = input_binding(text="   ")
    api = FakeUser32()
    assert binding._handle_key_event(api, 0x0D, WM_KEYDOWN) is True
    assert binding._handle_key_event(api, 0x0D, WM_KEYUP) is True
    assert binding.empty_enter_suppressed_count == 1
    assert binding.capture_count == 0
    assert binding.armed is True


def test_unverified_composer_focus_suppresses_host_dispatch_but_fails_gate() -> None:
    binding = input_binding(focused=False)
    api = FakeUser32()
    assert binding._handle_key_event(api, 0x0D, WM_KEYDOWN) is True
    assert binding._handle_key_event(api, 0x0D, WM_KEYUP) is True
    assert binding.last_error == "ACTUAL_COMPOSER_FOCUS_UNVERIFIED_AT_ENTER"
    assert binding.capture_count == 0
    assert binding.armed is False
    assert binding.suppressed_keyup_count == 1


def test_unavailable_composer_text_preserves_suppressed_key_pair() -> None:
    binding = input_binding()

    def unavailable() -> str:
        raise RuntimeError("composer unavailable")

    binding._text_probe = unavailable
    api = FakeUser32()
    assert binding._handle_key_event(api, 0x0D, WM_KEYDOWN) is True
    assert binding._handle_key_event(api, 0x0D, WM_KEYUP) is True
    assert binding.last_error == "HOST_COMPOSER_VALUE_UNAVAILABLE"
    assert binding.capture_count == 0
    assert binding.armed is False
    assert binding.suppressed_keyup_count == 1


def test_stop_drains_pending_delivery_before_removing_dispatcher() -> None:
    calls: list[str] = []
    binding = input_binding()
    binding._armed = False
    binding._delivery_pending = True
    binding._dispatcher = object()

    def drain(timeout: float) -> dict[str, object]:
        assert timeout == 5.0
        assert binding._dispatcher is not None
        calls.append("drain")
        with binding._state_lock:
            binding._delivery_pending = False
        return {}

    binding.wait_for_delivery = drain  # type: ignore[method-assign]
    binding.stop()

    assert calls == ["drain"]
    assert binding._dispatcher is None


def test_stop_reports_pending_delivery_failure_after_cleanup() -> None:
    binding = input_binding()
    binding._armed = False
    binding._delivery_pending = True
    binding._dispatcher = object()

    def fail_drain(timeout: float) -> dict[str, object]:
        raise CodexInputBindingError("HOST_COMPOSER_ENVELOPE_TIMEOUT")

    binding.wait_for_delivery = fail_drain  # type: ignore[method-assign]
    with pytest.raises(CodexInputBindingError, match="HOST_COMPOSER_ENVELOPE_TIMEOUT"):
        binding.stop()

    assert binding._dispatcher is None
    assert binding._delivery_pending is False


def test_production_binding_has_no_semantics_fixture_or_direct_authority() -> None:
    source = (ROOT / "r6o" / "host" / "codex" / "windows" / "input_binding.py").read_text(
        encoding="utf-8"
    ).casefold()
    for forbidden in (
        "h2e1routingboundary",
        "mechanicalcontroller",
        "sessionengine",
        "workeradapter",
        "reviewdecision",
        "r6o.viewmodel",
        "r6o.model_binding",
        "handle_input",
    ):
        assert forbidden not in source


def test_e1_verifier_has_portable_help() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "h2" / "verify_codex_input_routing.py"), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_qualification_cleanup_attempts_reset_stop_and_host_close(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    host = SimpleNamespace(close=lambda: calls.append("host_close"))
    input_router = SimpleNamespace(stop=lambda: calls.append("input_stop"))
    monkeypatch.setattr(verifier, "reset_composer", lambda value: calls.append("composer_reset"))
    verifier.close_qualification_resources(host, input_router, reset_required=True)
    assert calls == ["composer_reset", "input_stop", "host_close"]


def test_cleanup_failure_never_skips_later_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    host = SimpleNamespace(close=lambda: calls.append("host_close"))

    def fail_stop() -> None:
        calls.append("input_stop")
        raise RuntimeError("stop failed")

    input_router = SimpleNamespace(stop=fail_stop)

    def fail_reset(value: object) -> None:
        calls.append("composer_reset")
        raise RuntimeError("reset failed")

    monkeypatch.setattr(verifier, "reset_composer", fail_reset)
    with pytest.raises(CodexInputBindingError, match="QUALIFICATION_CLEANUP_FAILED"):
        verifier.close_qualification_resources(host, input_router, reset_required=True)
    assert calls == ["composer_reset", "input_stop", "host_close"]


def test_readme_e1_command_is_branch_bound_and_sets_exact_qt_runtime() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "codex/h2-e1-input-routing" in readme
    assert "H2-E1 CHECKOUT VERIFIED" in readme
    assert "$env:QT_QUICK_BACKEND = 'software'" in readme
    assert "verify_codex_input_routing.py --host-record" in readme
    assert "H2_E1_INPUT_ROUTING_PASS" in readme


def test_e1_evidence_is_bound_and_fail_closed_when_present() -> None:
    path = ROOT / "r6o_evidence" / "H2-E1" / "input-routing-result.json"
    if not path.exists():
        pytest.skip("actual-Codex E1 evidence is Windows-host generated")
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["schema_version"] == "r6o-h2-e1-input-routing-1"
    assert document["status"] == "H2_E1_INPUT_ROUTING_PASS"
    assert document["real_codex_host_tested"] is True
    assert document["fake_host_composer_used"] is False
    assert document["interaction"] == {
        "something_else_kind": "FREE_RESPONSE_FOCUS",
        "something_else_semantic_text": None,
        "actual_composer_focused": True,
        "shift_enter_editing_only": True,
        "unmodified_enter_captured": True,
        "native_send_button_used": False,
        "composer_text_cleared": True,
        "hook_cleanup_verified_on_success": True,
    }
    assert document["routing"]["source"] == "HOST_COMPOSER_TEXT"
    assert document["routing"]["action_id"] is None
    assert document["routing"]["projection_id"] is None
    assert document["routing"]["capture_count"] == 1
    assert document["routing"]["delivery_count"] == 1
    assert document["routing"]["duplicate_send_observed"] is False
    assert document["routing"]["text_equals_composer_at_gesture"] is True
    assert document["suppression"]["native_keydown_suppressed"] is True
    assert document["suppression"]["native_keyup_suppressed"] is True
    assert document["suppression"]["normal_codex_request_observed"] is False
    assert document["suppression"]["visible_turn_count_before"] == document["suppression"][
        "visible_turn_count_after"
    ]
    assert document["scope"]["controller_called"] is False
    assert document["scope"]["r6o3_host_model_lease_implemented"] is False
    expected_hashes = {
        source: hashlib.sha256((ROOT / source).read_bytes()).hexdigest()
        for source in (
            "r6o/host/codex/windows/input_binding.py",
            "scripts/h2/verify_codex_input_routing.py",
        )
    }
    assert document["implementation_sha256"] == expected_hashes
    assert document["runtime"]["qt_platform"] == "windows"
    assert document["runtime"]["qt_quick_backend"] == "software"
    event_path = ROOT / document["event_log"]["path"]
    assert document["event_log"]["sha256"] == hashlib.sha256(event_path.read_bytes()).hexdigest()
    events = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines()]
    assert [event["sequence"] for event in events] == list(range(1, 7))
    capture = next(event for event in events if event["event"] == "unmodified_enter_captured")
    assert capture["native_enter_keydown_suppressed"] is True
    assert capture["native_enter_keyup_suppressed"] is True
