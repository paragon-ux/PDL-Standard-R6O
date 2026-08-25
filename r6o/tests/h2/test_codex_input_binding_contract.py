from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys

import pytest

from r6o.host.codex.windows.input_binding import (
    CapturedComposerSubmission,
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


class FailingModifierProbeUser32(FakeUser32):
    def GetAsyncKeyState(self, key: int) -> int:
        raise OSError("modifier state unavailable")


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


def test_activate_installs_enter_boundary_before_native_composer_focus() -> None:
    queued: list[object] = []
    api = FakeUser32()

    class Composer:
        def set_focus(self) -> None:
            assert binding.armed is True
            assert binding._handle_key_event(api, 0x0D, WM_KEYDOWN) is True
            assert binding._handle_key_event(api, 0x0D, WM_KEYUP) is True

        def has_keyboard_focus(self) -> bool:
            return True

    composer = Composer()
    host = SimpleNamespace(
        host_hwnd=101,
        sidecar_hwnd=303,
        controls=SimpleNamespace(composer=composer),
        refresh_controls=lambda: SimpleNamespace(composer=composer),
        native=SimpleNamespace(foreground=lambda: 101),
    )
    binding = CodexComposerInputBinding(
        host, lambda envelope: None, focus_probe=lambda: True, text_probe=lambda: "EARLIEST"
    )
    binding._hook_thread = object()  # type: ignore[assignment]
    binding._dispatcher = SimpleNamespace(
        submissionRequested=SimpleNamespace(emit=queued.append)
    )
    binding._transfer_focus_from_sidecar_to_host = lambda: None  # type: ignore[method-assign]

    binding.activate(projection())

    assert binding.capture_count == 1
    assert binding.suppressed_keydown_count == 1
    assert binding.suppressed_keyup_count == 1
    assert len(queued) == 1
    assert binding.delivery_pending is True


def test_focus_probe_race_fails_with_persistent_enter_guard_until_abort() -> None:
    api = FakeUser32()

    class Composer:
        def set_focus(self) -> None:
            assert binding._handle_key_event(api, 0x0D, WM_KEYDOWN) is True
            assert binding._handle_key_event(api, 0x0D, WM_KEYUP) is True

        def has_keyboard_focus(self) -> bool:
            return True

    composer = Composer()
    host = SimpleNamespace(
        host_hwnd=101,
        sidecar_hwnd=303,
        refresh_controls=lambda: SimpleNamespace(composer=composer),
        native=SimpleNamespace(foreground=lambda: 101),
    )
    binding = CodexComposerInputBinding(
        host, lambda envelope: None, focus_probe=lambda: False, text_probe=lambda: "EARLY"
    )
    binding._hook_thread = object()  # type: ignore[assignment]
    binding._transfer_focus_from_sidecar_to_host = lambda: None  # type: ignore[method-assign]

    with pytest.raises(CodexInputBindingError, match="ACTUAL_COMPOSER_FOCUS_UNVERIFIED_AT_ENTER"):
        binding.activate(projection())

    assert binding.armed is False
    assert binding.capture_count == 0
    assert binding._handle_key_event(api, 0x0D, WM_KEYDOWN) is True
    assert binding._handle_key_event(api, 0x0D, WM_KEYUP) is True


def test_abort_clears_attempt_owned_text_before_releasing_failure_guard() -> None:
    binding = input_binding()
    binding._armed = False
    binding._failure_guard = True
    calls: list[str] = []
    binding._clear_actual_composer = lambda: calls.append("clear")  # type: ignore[method-assign]

    binding.abort_handoff()

    assert calls == ["clear"]
    assert binding._failure_guard is True
    assert binding._handle_key_event(FakeUser32(), 0x0D, WM_KEYDOWN) is True
    assert binding._handle_key_event(FakeUser32(), 0x0D, WM_KEYUP) is True
    binding.stop()
    assert binding._failure_guard is False


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


def test_modifier_probe_failure_suppresses_complete_enter_pair_without_dispatch() -> None:
    binding = input_binding()
    api = FailingModifierProbeUser32()

    assert binding._handle_key_event(api, 0x0D, WM_KEYDOWN) is True
    assert binding.last_error == "HOST_KEY_STATE_UNAVAILABLE"
    assert binding.suppressed_keydown_count == 1
    assert binding.capture_count == 0
    assert binding.delivery_count == 0
    assert binding._captures.empty()
    assert binding.armed is False

    assert binding._handle_key_event(api, 0x0D, WM_KEYUP) is True
    assert binding.suppressed_keyup_count == 1
    assert binding._enter_down is False


def test_deactivation_preserves_pair_until_keyup_then_teardown_completes() -> None:
    binding = input_binding(text="   ")
    api = FakeUser32()

    assert binding._handle_key_event(api, 0x0D, WM_KEYDOWN) is True
    binding.deactivate()
    assert binding._enter_down is True

    # An unrelated key is not part of the suppressed Enter pair.
    assert binding._handle_key_event(api, 0x41, WM_KEYDOWN) is False
    assert binding._handle_key_event(api, 0x41, WM_KEYUP) is False

    assert binding._handle_key_event(api, 0x0D, WM_KEYUP) is True
    assert binding._enter_down is False
    binding.stop()
    assert binding._dispatcher is None
    assert binding._handle_key_event(api, 0x0D, WM_KEYUP) is False


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


def test_cancelled_queued_delivery_clears_text_without_semantic_callback() -> None:
    callbacks: list[dict[str, object]] = []
    binding = input_binding()
    binding.on_envelope = callbacks.append
    api = FakeUser32()
    assert binding._handle_key_event(api, 0x0D, WM_KEYDOWN) is True
    assert binding._handle_key_event(api, 0x0D, WM_KEYUP) is True
    capture = binding._captures.get_nowait()
    assert capture is not None
    clears: list[str] = []
    binding._clear_actual_composer = lambda: clears.append("clear")  # type: ignore[method-assign]
    binding._delivery_cancelled = True

    binding._deliver_capture(capture)

    assert clears == ["clear"]
    assert callbacks == []
    assert binding.delivery_count == 0
    assert binding.delivery_pending is False
    assert binding._delivery_event.is_set()


def test_stale_cancelled_qt_delivery_cannot_clear_post_abort_user_text() -> None:
    binding = input_binding()
    capture = CapturedComposerSubmission(
        projection=projection(), text="ABORTED", captured_monotonic=1.0
    )
    binding._delivery_cancelled = True
    binding._delivery_pending = False
    clears: list[str] = []
    binding._clear_actual_composer = lambda: clears.append("clear")  # type: ignore[method-assign]

    binding._deliver_capture(capture)

    assert clears == []
    assert binding.delivery_count == 0
    assert binding._delivery_event.is_set()


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


def test_enter_pair_timeout_still_completes_bounded_resource_cleanup() -> None:
    binding = input_binding()
    binding._dispatcher = object()
    binding._enter_pair_complete.wait = lambda timeout: False  # type: ignore[method-assign]

    with pytest.raises(CodexInputBindingError, match="HOST_ENTER_KEYUP_DRAIN_TIMEOUT"):
        binding.stop()

    assert binding._stop.is_set()
    assert binding._dispatcher is None


def test_hook_thread_timeout_uses_direct_unhook_fallback_before_return() -> None:
    class StuckThread:
        def join(self, timeout: float) -> None:
            assert timeout == 5.0

        def is_alive(self) -> bool:
            return True

    binding = input_binding()
    binding._hook_thread = StuckThread()  # type: ignore[assignment]
    binding._hook = 123
    calls: list[str] = []

    def remove(_user32: object) -> bool:
        calls.append("unhook")
        binding._hook = 0
        return True

    binding._remove_keyboard_hook = remove  # type: ignore[method-assign]
    with pytest.raises(CodexInputBindingError, match="HOST_INPUT_HOOK_STOP_TIMEOUT"):
        binding.stop()

    assert calls == ["unhook"]
    assert binding._hook == 0
    assert binding._dispatcher is None


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


def test_e1_verifier_resolves_relative_evidence_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    relative = Path("r6o_evidence") / "H2-E1"
    monkeypatch.setattr(sys, "argv", ["verify_codex_input_routing.py", "--evidence-dir", str(relative)])
    args = verifier.parse_args()
    assert args.evidence_dir == (Path.cwd() / relative).resolve()


@pytest.mark.parametrize(
    ("enabled", "visible", "width", "height", "expected"),
    [
        (True, True, 221.0, 31.0, True),
        (False, True, 221.0, 31.0, False),
        (True, False, 221.0, 31.0, False),
        (True, True, 0.0, 31.0, False),
        (True, True, 221.0, 0.0, False),
    ],
)
def test_sidecar_action_readiness_requires_exact_interactable_qml_item(
    enabled: bool,
    visible: bool,
    width: float,
    height: float,
    expected: bool,
) -> None:
    action = SimpleNamespace(
        objectName=lambda: "reviewAction_something_else",
        isEnabled=lambda: enabled,
        isVisible=lambda: visible,
        width=lambda: width,
        height=lambda: height,
        childItems=lambda: [],
    )
    root = SimpleNamespace(objectName=lambda: "", childItems=lambda: [action])
    window = SimpleNamespace(contentItem=lambda: root)
    binding = SimpleNamespace(sidecar=SimpleNamespace(window=window))
    assert (
        verifier.sidecar_action_ready(binding, "reviewAction_something_else")
        is expected
    )


def test_sidecar_action_readiness_is_false_until_qml_item_exists() -> None:
    root = SimpleNamespace(objectName=lambda: "", childItems=lambda: [])
    window = SimpleNamespace(contentItem=lambda: root)
    binding = SimpleNamespace(sidecar=SimpleNamespace(window=window))
    assert verifier.sidecar_action_ready(binding, "reviewAction_something_else") is False


class CleanupComposer:
    def __init__(self, value: str, *, readable: bool = True) -> None:
        self.value = value
        self.readable = readable
        self.focus_calls = 0

    @property
    def iface_value(self) -> object:
        if not self.readable:
            raise RuntimeError("composer value unavailable")
        return SimpleNamespace(CurrentValue=self.value)

    def set_focus(self) -> None:
        self.focus_calls += 1

    def has_keyboard_focus(self) -> bool:
        return True


class CleanupBinding:
    def __init__(self, composer: CleanupComposer) -> None:
        self.composer = composer
        self.controls = SimpleNamespace(composer=composer)
        self.host_hwnd = 101
        self.native = SimpleNamespace(foreground=lambda: 101)
        self.selectors = {"reset_contract": {"composer_empty": {}}}

    def refresh_controls(self) -> object:
        return self.controls


def cleanup_send_recorder(composer: CleanupComposer, calls: list[str]):
    def send_keys(keys: str, *, pause: float) -> None:
        calls.append(keys)
        composer.value = ""

    return send_keys


def test_empty_composer_cleanup_is_nondestructive_noop() -> None:
    composer = CleanupComposer("")
    calls: list[str] = []
    verifier.reset_composer(
        CleanupBinding(composer),
        expected_text=verifier.ROUTING_MARKER,
        send_keys_fn=cleanup_send_recorder(composer, calls),
    )
    assert calls == []
    assert composer.focus_calls == 0


def test_exact_verifier_marker_cleanup_is_permitted_and_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    composer = CleanupComposer(verifier.ROUTING_MARKER)
    binding = CleanupBinding(composer)
    calls: list[str] = []
    monkeypatch.setattr(
        verifier,
        "composer_empty_observation",
        lambda candidate, contract: {"empty": candidate.value == ""},
    )

    verifier.reset_composer(
        binding,
        expected_text=verifier.ROUTING_MARKER,
        send_keys_fn=cleanup_send_recorder(composer, calls),
    )
    verifier.reset_composer(
        binding,
        expected_text=verifier.ROUTING_MARKER,
        send_keys_fn=cleanup_send_recorder(composer, calls),
    )

    assert calls == ["^a{BACKSPACE}"]
    assert composer.value == ""
    assert composer.focus_calls == 1


@pytest.mark.parametrize(
    ("actual_text", "expected_text"),
    [
        ("unrelated user draft", verifier.ROUTING_MARKER),
        (verifier.ROUTING_MARKER + " plus user text", verifier.ROUTING_MARKER),
        (verifier.ROUTING_MARKER, None),
    ],
)
def test_unowned_or_nonexact_composer_content_is_never_cleared(
    actual_text: str, expected_text: str | None
) -> None:
    composer = CleanupComposer(actual_text)
    calls: list[str] = []

    with pytest.raises(CodexInputBindingError, match="COMPOSER_RESET_CONTENT_REFUSED"):
        verifier.reset_composer(
            CleanupBinding(composer),
            expected_text=expected_text,
            send_keys_fn=cleanup_send_recorder(composer, calls),
        )

    assert calls == []
    assert composer.value == actual_text
    assert composer.focus_calls == 0


def test_unreadable_composer_content_is_never_cleared() -> None:
    composer = CleanupComposer(verifier.ROUTING_MARKER, readable=False)
    calls: list[str] = []

    with pytest.raises(CodexInputBindingError, match="HOST_COMPOSER_VALUE_UNAVAILABLE"):
        verifier.reset_composer(
            CleanupBinding(composer),
            expected_text=verifier.ROUTING_MARKER,
            send_keys_fn=cleanup_send_recorder(composer, calls),
        )

    assert calls == []
    assert composer.value == verifier.ROUTING_MARKER
    assert composer.focus_calls == 0


def test_qualification_cleanup_attempts_reset_stop_and_host_close(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    host = SimpleNamespace(close=lambda: calls.append("host_close"))
    input_router = SimpleNamespace(stop=lambda: calls.append("input_stop"))
    monkeypatch.setattr(
        verifier,
        "reset_composer",
        lambda value, *, expected_text: calls.append(f"composer_reset:{expected_text}"),
    )
    verifier.close_qualification_resources(
        host,
        input_router,
        reset_required=True,
        expected_composer_text=verifier.ROUTING_MARKER,
    )
    assert calls == [
        f"composer_reset:{verifier.ROUTING_MARKER}",
        "input_stop",
        "host_close",
    ]


def test_cleanup_failure_never_skips_later_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    host = SimpleNamespace(close=lambda: calls.append("host_close"))

    def fail_stop() -> None:
        calls.append("input_stop")
        raise RuntimeError("stop failed")

    input_router = SimpleNamespace(stop=fail_stop)

    def fail_reset(value: object, *, expected_text: str | None) -> None:
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


def test_e1_evidence_is_historical_and_fail_closed_when_present() -> None:
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
    input_source = "r6o/host/codex/windows/input_binding.py"
    verifier_source = "scripts/h2/verify_codex_input_routing.py"
    assert document["implementation_sha256"] == {
        input_source: "cae01174e33879498b206d947365eec29f967219b67011981a929324e3c39221",
        verifier_source: hashlib.sha256((ROOT / verifier_source).read_bytes()).hexdigest(),
    }
    assert document["implementation_sha256"][input_source] != hashlib.sha256(
        (ROOT / input_source).read_bytes()
    ).hexdigest()
    assert document["runtime"]["qt_platform"] == "windows"
    assert document["runtime"]["qt_quick_backend"] == "software"
    event_path = ROOT / document["event_log"]["path"]
    assert document["event_log"]["sha256"] == hashlib.sha256(event_path.read_bytes()).hexdigest()
    events = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines()]
    assert [event["sequence"] for event in events] == list(range(1, 7))
    capture = next(event for event in events if event["event"] == "unmodified_enter_captured")
    assert capture["native_enter_keydown_suppressed"] is True
    assert capture["native_enter_keyup_suppressed"] is True
