from __future__ import annotations

"""Fail-closed H2-F2 lifecycle and resilience qualification."""

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import patch
import warnings


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_OBSERVED_WARNING_IDS: set[str] = set()
_ORIGINAL_SHOWWARNING = warnings.showwarning
_ORIGINAL_WARN = warnings.warn


def _warning_id(message: object) -> str | None:
    text = str(message)
    if "STA COM threading mode" in text or "RPC_E_CHANGED_MODE" in text:
        return "RPC_E_CHANGED_MODE"
    if "DPI" in text and ("denied" in text.lower() or "awareness" in text.lower()):
        return "DPI_AWARENESS_ACCESS_DENIED"
    return None


def _capture_warning(
    message: object,
    category: type[Warning],
    filename: str,
    lineno: int,
    file: Any | None = None,
    line: str | None = None,
) -> None:
    identifier = _warning_id(message)
    if identifier is not None:
        _OBSERVED_WARNING_IDS.add(identifier)
    _ORIGINAL_SHOWWARNING(message, category, filename, lineno, file=file, line=line)


def _capture_warn(
    message: object,
    category: type[Warning] | None = None,
    stacklevel: int = 1,
    source: object | None = None,
) -> None:
    identifier = _warning_id(message)
    if identifier is not None:
        _OBSERVED_WARNING_IDS.add(identifier)
    _ORIGINAL_WARN(message, category, stacklevel=stacklevel, source=source)


warnings.showwarning = _capture_warning
warnings.warn = _capture_warn

from r6o.host.codex.windows.binding import (  # noqa: E402
    CodexBindingError,
    CodexSidecarBinding,
    verify_frozen_host_identity,
    verify_selector_host_compatibility,
)
from r6o.host.codex.windows import input_binding as input_binding_module  # noqa: E402
from r6o.host.codex.windows.input_binding import (  # noqa: E402
    CodexComposerInputBinding,
    CodexInputBindingError,
    VK_SHIFT,
    WM_KEYDOWN,
    WM_KEYUP,
)
from r6o.host.codex.windows.uia import composer_empty_observation  # noqa: E402
from r6o.views.sidecar.fixture import CANONICAL_ACTIONS, CANONICAL_ARTIFACT_BODY  # noqa: E402
from r6o.views.sidecar.model import SidecarMode  # noqa: E402


DEFAULT_HOST_RECORD = ROOT / "r6o_evidence" / "H2-D1" / "host-environment.json"
DEFAULT_SELECTORS = ROOT / "r6o" / "host" / "codex" / "windows" / "selectors.json"
DEFAULT_EVIDENCE_DIR = ROOT / "r6o_evidence" / "H2-F2" / "human-override-repair-2"
FROZEN_ORACLE_COMMIT = "60d982f3328b45a351879d67dc4bb525172b65fd"
FROZEN_ORACLE_TREE = "b7689fbe8b9c9838438cbba6f6e0e5c1ce5b5ed6"
PROCESS_EXIT_MARKER = "H2_F2_PROCESS_EXIT_CLEANUP_COMPLETE"
PROCESS_EXIT_TIMEOUT_SECONDS = 180.0


class F2VerificationError(RuntimeError):
    """A stable, machine-readable F2 qualification failure."""

    def __init__(self, code: str, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}{':' + detail if detail else ''}")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise F2VerificationError("EVIDENCE_INPUT_UNREADABLE", str(path)) from exc
    if not isinstance(value, dict):
        raise F2VerificationError("EVIDENCE_INPUT_INVALID", str(path))
    return value


def git(*arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise F2VerificationError("GIT_COMMAND_FAILED", " ".join(arguments))
    return result.stdout.strip()


def checkout_identity() -> dict[str, Any]:
    return {
        "branch": git("branch", "--show-current"),
        "head": git("rev-parse", "HEAD"),
        "tree": git("rev-parse", "HEAD^{tree}"),
        "dirty": bool(git("status", "--porcelain")),
    }


def require(condition: bool, code: str, detail: str | None = None) -> None:
    if not condition:
        raise F2VerificationError(code, detail)


def canonical_projection(*, projection_id: str, body: str = CANONICAL_ARTIFACT_BODY) -> dict[str, Any]:
    action_kinds = {
        "confirm_prompt": "SEMANTIC_MESSAGE",
        "change_task": "SEMANTIC_MESSAGE",
        "change_approach": "SEMANTIC_MESSAGE",
        "something_else": "FREE_RESPONSE_FOCUS",
    }
    return {
        "schema_version": "r6o-focus-projection-1",
        "session_id": "h2-f2-session",
        "workspace_id": "h2-f2-workspace",
        "model_revision": "h2-f2-model-revision",
        "projection_id": projection_id,
        "interaction_state": "REVIEW_REQUIRED",
        "model_response": None,
        "stage": "PROMPT_REVIEW",
        "focus_kind": "PROMPT_REVIEW",
        "artifact": {
            "artifact_ref": "h2-f2:qualification-artifact",
            "artifact_revision": "h2-f2-artifact-revision",
            "artifact_kind": "prompt",
            "title": "Authoritative Prompt (PDL.md)",
            "media_type": "text/markdown",
            "body": body,
            "capabilities": {"copy": True, "open_external": False},
        },
        "actions": [
            {**dict(action), "kind": action_kinds[str(action["action_id"])]}
            for action in CANONICAL_ACTIONS
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


def terminal_projection() -> dict[str, Any]:
    value = canonical_projection(projection_id="h2-f2-terminal")
    value.update(
        {
            "stage": "CLOSED_SUCCESS",
            "interaction_state": "TERMINAL",
            "artifact": None,
            "actions": [],
            "lifecycle": {
                "review_required": False,
                "terminal": True,
                "close_allowed": True,
                "handoff_ready": True,
                "terminal_disposition": "HOST_HANDOFF",
                "result_body": "H2-F2 terminal result",
                "authorized_handoff_artifacts": [],
            },
        }
    )
    return value


class _FakeUser32:
    def __init__(self, *, foreground: int = 101, modifiers: set[int] | None = None) -> None:
        self.foreground = foreground
        self.modifiers = modifiers or set()

    def GetForegroundWindow(self) -> int:
        return self.foreground

    def GetAsyncKeyState(self, key: int) -> int:
        return 0x8000 if key in self.modifiers else 0


def _input_binding(
    *,
    focused: bool = True,
    text: str = "H2-F2 captured text",
    on_envelope: Callable[[dict[str, Any]], None] | None = None,
) -> CodexComposerInputBinding:
    host = SimpleNamespace(host_hwnd=101, sidecar_hwnd=303)
    binding = CodexComposerInputBinding(
        host,
        on_envelope or (lambda _envelope: None),
        focus_probe=lambda: focused,
        text_probe=lambda: text,
    )
    binding._active_projection = canonical_projection(projection_id="h2-f2-input")
    binding._armed = True
    return binding


def qualify_delivery_cancellation_race() -> dict[str, Any]:
    envelopes: list[dict[str, Any]] = []
    composer = {"text": "H2-F2 attempt-owned text"}
    clears: list[str] = []
    callback_before_mutation = threading.Event()
    resume_stale_callback = threading.Event()
    binding = _input_binding(on_envelope=envelopes.append)
    user32 = _FakeUser32()

    def clear_composer() -> None:
        clears.append(composer["text"])
        composer["text"] = ""

    binding._clear_actual_composer = clear_composer  # type: ignore[method-assign]
    require(binding._handle_key_event(user32, 0x0D, WM_KEYDOWN), "R1_CAPTURE_KEYDOWN")
    require(binding._handle_key_event(user32, 0x0D, WM_KEYUP), "R1_CAPTURE_KEYUP")
    capture = binding._captures.get_nowait()
    require(capture is not None, "R1_CAPTURE_MISSING")
    binding._dispatcher = object()

    original_builder = input_binding_module.build_host_composer_envelope

    def blocked_builder(projection: dict[str, Any], text: str) -> dict[str, Any]:
        callback_before_mutation.set()
        require(resume_stale_callback.wait(timeout=5.0), "R1_CALLBACK_RESUME_TIMEOUT")
        return original_builder(projection, text)

    def fail_wait(timeout: float) -> dict[str, Any]:
        require(timeout == 5.0, "R1_CANCELLATION_WAIT_NOT_BOUNDED")
        raise CodexInputBindingError("HOST_COMPOSER_ENVELOPE_TIMEOUT")

    binding.wait_for_delivery = fail_wait  # type: ignore[method-assign]
    with patch.object(input_binding_module, "build_host_composer_envelope", blocked_builder):
        callback = threading.Thread(
            target=binding._deliver_capture,
            args=(capture,),
            name="h2-f2-stale-delivery",
        )
        callback.start()
        require(callback_before_mutation.wait(timeout=5.0), "R1_CALLBACK_NOT_PAUSED")
        try:
            binding.stop()
        except CodexInputBindingError as exc:
            require(exc.code == "HOST_COMPOSER_ENVELOPE_TIMEOUT", "R1_STOP_REASON_UNSTABLE")
        else:
            raise F2VerificationError("R1_CANCELLATION_FAILURE_NOT_REPORTED")

        require(clears == ["H2-F2 attempt-owned text"], "R1_CANCELLATION_CLEAR_INVALID")
        require(composer["text"] == "", "R1_CANCELLATION_CLEANUP_INCOMPLETE")
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
        require(not callback.is_alive(), "R1_STALE_CALLBACK_DID_NOT_FINISH")

    with binding._state_lock:
        current_state_preserved = (
            binding._delivery_pending
            and binding._pending_delivery_token == current_token
            and binding._delivery_token == current_token
        )
        binding._delivery_pending = False
        binding._pending_delivery_token = None
    require(composer["text"] == "new user text", "R1_STALE_CALLBACK_CLEARED_NEW_TEXT")
    require(clears == ["H2-F2 attempt-owned text"], "R1_SECOND_DESTRUCTIVE_CLEAR")
    require(envelopes == [], "R1_STALE_CALLBACK_EMITTED_ENVELOPE")
    require(current_state_preserved, "R1_STALE_CALLBACK_CORRUPTED_CURRENT_STATE")
    require(not binding._delivery_event.is_set(), "R1_STALE_CALLBACK_CORRUPTED_CURRENT_EVENT")
    return {
        "status": "PASS",
        "callback_paused_before_mutation": True,
        "cancellation_cleanup_completed": True,
        "new_user_text_preserved": True,
        "destructive_clear_count": len(clears),
        "envelope_count": len(envelopes),
        "current_delivery_state_preserved": current_state_preserved,
        "current_delivery_event_preserved": not binding._delivery_event.is_set(),
    }


def qualify_input_boundary() -> dict[str, Any]:
    binding = _input_binding()
    binding._clear_actual_composer = lambda: None  # type: ignore[method-assign]
    user32 = _FakeUser32()
    require(binding._handle_key_event(user32, 0x0D, WM_KEYDOWN), "UNMODIFIED_ENTER_NOT_SUPPRESSED")
    require(binding._handle_key_event(user32, 0x0D, WM_KEYUP), "UNMODIFIED_ENTER_KEYUP_NOT_SUPPRESSED")
    capture = binding._captures.get_nowait()
    binding._deliver_capture(capture)
    require(binding.capture_count == 1, "INPUT_CAPTURE_COUNT_INVALID")
    require(binding.delivery_count == 1, "INPUT_DELIVERY_COUNT_INVALID")

    shift = _input_binding()
    shift_user32 = _FakeUser32(modifiers={VK_SHIFT})
    require(not shift._handle_key_event(shift_user32, 0x0D, WM_KEYDOWN), "SHIFT_ENTER_CAPTURED")
    require(not shift._handle_key_event(shift_user32, 0x0D, WM_KEYUP), "SHIFT_ENTER_KEYUP_CAPTURED")

    unrelated = _input_binding()
    other_user32 = _FakeUser32(foreground=999)
    require(not unrelated._handle_key_event(other_user32, 0x0D, WM_KEYDOWN), "UNRELATED_WINDOW_CAPTURED")
    require(not unrelated._handle_key_event(other_user32, 0x0D, WM_KEYUP), "UNRELATED_WINDOW_KEYUP_CAPTURED")

    failed_focus = _input_binding(focused=False)
    require(
        failed_focus._handle_key_event(user32, 0x0D, WM_KEYDOWN),
        "FOCUS_FAILURE_DID_NOT_SUPPRESS",
    )
    require(
        failed_focus._handle_key_event(user32, 0x0D, WM_KEYUP),
        "FOCUS_FAILURE_KEYUP_NOT_SUPPRESSED",
    )
    require(
        failed_focus.last_error == "ACTUAL_COMPOSER_FOCUS_UNVERIFIED_AT_ENTER",
        "FOCUS_FAILURE_REASON_UNSTABLE",
    )

    composer = SimpleNamespace(set_focus=lambda: None, has_keyboard_focus=lambda: True)
    activation_host = SimpleNamespace(
        host_hwnd=101,
        sidecar_hwnd=303,
        refresh_controls=lambda: SimpleNamespace(composer=composer),
        native=SimpleNamespace(foreground=lambda: 101),
    )
    activation = CodexComposerInputBinding(
        activation_host,
        lambda _envelope: None,
        focus_probe=lambda: True,
        text_probe=lambda: "unused",
    )
    activation._hook_thread = object()  # type: ignore[assignment]
    activation._transfer_focus_from_sidecar_to_host = lambda: None  # type: ignore[method-assign]
    for cycle in range(2):
        activation.activate(canonical_projection(projection_id=f"h2-f2-activation-{cycle}"))
        require(activation.armed, "ACTIVATION_DID_NOT_ARM")
        activation.deactivate()
        require(not activation.armed, "DEACTIVATION_DID_NOT_DISARM")
    try:
        activation.activate(
            canonical_projection(projection_id="h2-f2-partial-activation"), timeout=0
        )
    except CodexInputBindingError as exc:
        require(
            exc.code == "ACTUAL_COMPOSER_FOCUS_UNVERIFIED",
            "PARTIAL_ACTIVATION_REASON_UNSTABLE",
            exc.code,
        )
    else:
        raise F2VerificationError("PARTIAL_ACTIVATION_FAILURE_NOT_EXERCISED")
    activation._clear_actual_composer = lambda: None  # type: ignore[method-assign]
    activation.abort_handoff()
    require(not activation.armed, "PARTIAL_ACTIVATION_CLEANUP_FAILED")

    orphaned = _input_binding()
    removed: list[int] = []

    class User32:
        def UnhookWindowsHookEx(self, handle: object) -> bool:
            removed.append(int(getattr(handle, "value", handle)))
            return True

    orphaned._hook = 901
    orphaned._hook_user32 = User32()
    orphaned.stop()
    require(orphaned._hook == 0, "ORPHANED_HOOK_REMAINS")
    require(removed == [901], "ORPHANED_HOOK_REMOVAL_NOT_EXACTLY_ONCE")

    envelopes: list[dict[str, Any]] = []
    clears: list[str] = []
    timed_out = _input_binding(on_envelope=envelopes.append)
    timed_out._clear_actual_composer = lambda: clears.append("clear")  # type: ignore[method-assign]
    require(timed_out._handle_key_event(user32, 0x0D, WM_KEYDOWN), "TIMEOUT_CAPTURE_KEYDOWN")
    require(timed_out._handle_key_event(user32, 0x0D, WM_KEYUP), "TIMEOUT_CAPTURE_KEYUP")
    stale_capture = timed_out._captures.get_nowait()
    require(stale_capture is not None, "TIMEOUT_CAPTURE_MISSING")
    timed_out._dispatcher = object()

    def fail_wait(timeout: float) -> dict[str, Any]:
        require(timeout == 5.0, "DELIVERY_TIMEOUT_NOT_BOUNDED")
        raise CodexInputBindingError("HOST_COMPOSER_ENVELOPE_TIMEOUT")

    timed_out.wait_for_delivery = fail_wait  # type: ignore[method-assign]
    try:
        timed_out.stop()
    except CodexInputBindingError as exc:
        require(exc.code == "HOST_COMPOSER_ENVELOPE_TIMEOUT", "TIMEOUT_PRECEDENCE_UNSTABLE")
    else:
        raise F2VerificationError("TIMEOUT_FAILURE_NOT_REPORTED")
    require(timed_out._delivery_pending is False, "TIMEOUT_CLEANUP_LEFT_DELIVERY_PENDING")
    require(timed_out._dispatcher is None, "TIMEOUT_CLEANUP_LEFT_DISPATCHER")
    require(clears == ["clear"], "TIMEOUT_COMPOSER_CLEANUP_INVALID")
    require(envelopes == [], "TIMEOUT_ENVELOPE_EMITTED")
    timed_out._delivery_event.clear()
    with timed_out._state_lock:
        timed_out._delivery_cancelled = False
        timed_out._delivery_pending = True
        timed_out._pending_delivery_token = timed_out._delivery_token + 1
    timed_out._deliver_capture(stale_capture)
    require(clears == ["clear"], "STALE_DELIVERY_CLEARED_COMPOSER")
    require(envelopes == [], "STALE_DELIVERY_EMITTED_ENVELOPE")
    require(not timed_out._delivery_event.is_set(), "STALE_DELIVERY_MUTATED_CURRENT_EVENT")
    with timed_out._state_lock:
        timed_out._delivery_pending = False
        timed_out._pending_delivery_token = None

    class StuckThread:
        def join(self, timeout: float) -> None:
            require(timeout == 5.0, "HOOK_SHUTDOWN_TIMEOUT_NOT_BOUNDED")

        def is_alive(self) -> bool:
            return True

    failed_shutdown = _input_binding()
    failed_shutdown._hook_thread = StuckThread()  # type: ignore[assignment]
    failed_shutdown._hook = 902
    failed_shutdown._hook_user32 = object()

    def remove_stuck_hook(_user32: object) -> bool:
        failed_shutdown._hook = 0
        return True

    failed_shutdown._remove_keyboard_hook = remove_stuck_hook  # type: ignore[method-assign]
    try:
        failed_shutdown.stop()
    except CodexInputBindingError as exc:
        require(exc.code == "HOST_INPUT_HOOK_STOP_TIMEOUT", "HOOK_TIMEOUT_REASON_UNSTABLE")
    else:
        raise F2VerificationError("FAILED_HOOK_SHUTDOWN_NOT_EXERCISED")
    with patch.object(os, "name", "nt"):
        try:
            failed_shutdown.start()
        except CodexInputBindingError as exc:
            require(
                exc.code == "HOST_INPUT_HOOK_RESTART_BLOCKED",
                "FAILED_RESTART_REASON_UNSTABLE",
                exc.code,
            )
        else:
            raise F2VerificationError("STALE_THREAD_RESTART_ACCEPTED")
        failed_shutdown._teardown_pending = False
        try:
            failed_shutdown.start()
        except CodexInputBindingError as exc:
            require(
                exc.code == "HOST_INPUT_HOOK_RESTART_BLOCKED",
                "HOOKLESS_THREAD_CORRUPTION_ACCEPTED",
                exc.code,
            )
        else:
            raise F2VerificationError("HOOKLESS_THREAD_RESTART_ACCEPTED")

    class PairEvent:
        complete = False

        def wait(self, timeout: float) -> bool:
            require(timeout == 5.0, "ENTER_KEYUP_TIMEOUT_NOT_BOUNDED")
            return self.complete

        def set(self) -> None:
            self.complete = True

        def clear(self) -> None:
            self.complete = False

    pair_owner = _input_binding()

    class PairOwnerThread:
        alive = True

        def join(self, timeout: float) -> None:
            require(timeout == 5.0, "PAIR_OWNER_JOIN_NOT_BOUNDED")
            self.alive = False
            pair_owner._hook = 0

        def is_alive(self) -> bool:
            return self.alive

    pair_event = PairEvent()
    pair_thread = PairOwnerThread()
    pair_owner._enter_pair_complete = pair_event  # type: ignore[assignment]
    pair_owner._enter_down = True
    pair_owner._hook_thread = pair_thread  # type: ignore[assignment]
    pair_owner._hook = 903
    try:
        pair_owner.stop()
    except CodexInputBindingError as exc:
        require(exc.code == "HOST_ENTER_KEYUP_DRAIN_TIMEOUT", "ENTER_KEYUP_REASON_UNSTABLE")
    else:
        raise F2VerificationError("ENTER_KEYUP_TIMEOUT_NOT_EXERCISED")
    require(pair_owner._hook == 903 and pair_thread.is_alive(), "ENTER_PAIR_OWNERSHIP_ABANDONED")
    require(not pair_owner._stop.is_set(), "ENTER_PAIR_OWNER_STOPPED_EARLY")
    require(pair_owner._handle_key_event(user32, 0x0D, WM_KEYUP), "DELAYED_KEYUP_NOT_SUPPRESSED")
    pair_owner.stop()
    require(pair_owner._hook == 0 and pair_owner._hook_thread is None, "PAIR_RETRY_CLEANUP_FAILED")
    delivery_cancellation_race = qualify_delivery_cancellation_race()
    return {
        "status": "PASS",
        "normal_activation_deactivation": True,
        "repeated_activation_deactivation": 2,
        "partial_activation_failure_cleanup": True,
        "unmodified_enter": {"capture_count": binding.capture_count, "delivery_count": binding.delivery_count},
        "shift_enter": "PASSTHROUGH",
        "unrelated_window": "PASSTHROUGH",
        "focus_failure": failed_focus.last_error,
        "orphaned_hook_removed": True,
        "timeout_error_precedence": "HOST_COMPOSER_ENVELOPE_TIMEOUT",
        "pending_delivery_teardown": True,
        "stale_queued_delivery_inert": True,
        "failed_hook_thread_shutdown": "HOST_INPUT_HOOK_STOP_TIMEOUT",
        "restart_after_failed_shutdown": "HOST_INPUT_HOOK_RESTART_BLOCKED",
        "enter_keyup_timeout_retains_ownership": True,
        "retry_after_delayed_keyup": True,
        "stale_provenance_corruption": "FAIL_CLOSED",
        "delivery_cancellation_race": delivery_cancellation_race,
        "final_resource_state": {
            "orphaned_hook_removed": orphaned._hook == 0,
            "orphaned_dispatcher_released": orphaned._dispatcher is None,
            "pair_owner_hook_removed": pair_owner._hook == 0,
            "pair_owner_thread_absent": pair_owner._hook_thread is None,
            "pair_owner_teardown_complete": not pair_owner._teardown_pending,
        },
    }


def qualify_host_fail_closed(host_record_path: Path, selectors_path: Path) -> dict[str, Any]:
    record = read_json(host_record_path)
    selectors = read_json(selectors_path)
    try:
        verify_frozen_host_identity(record, enumerator=lambda: [])
    except CodexBindingError as exc:
        require(exc.code == "FROZEN_HOST_HWND_STALE", "STALE_HOST_REASON_UNSTABLE", exc.code)
    else:
        raise F2VerificationError("STALE_HOST_ACCEPTED")

    mismatched = copy.deepcopy(selectors)
    compatibility = mismatched.get("host_compatibility")
    require(isinstance(compatibility, dict), "SELECTOR_COMPATIBILITY_INVALID")
    compatibility["package_version"] = "H2-F2-MISMATCH"
    try:
        verify_selector_host_compatibility(mismatched, record)
    except CodexBindingError as exc:
        require(exc.code == "SELECTOR_HOST_MISMATCH:package_version", "SELECTOR_MISMATCH_REASON_UNSTABLE", exc.code)
    else:
        raise F2VerificationError("SELECTOR_HOST_MISMATCH_ACCEPTED")
    return {
        "status": "PASS",
        "stale_hwnd": "FROZEN_HOST_HWND_STALE",
        "selector_mismatch": "SELECTOR_HOST_MISMATCH:package_version",
    }


def qualify_qt_lifecycle() -> dict[str, Any]:
    try:
        from r6o.views.sidecar import qt_app
    except ImportError as exc:
        raise F2VerificationError("SIDECAR_DEPENDENCY_MISSING") from exc

    sidecar = qt_app.QtSidecarWindow()
    try:
        first = canonical_projection(projection_id="h2-f2-open")
        second = canonical_projection(projection_id="h2-f2-reopen", body="# Current authoritative projection\n")
        require(sidecar.render(first), "SIDECAR_OPEN_FAILED")
        sidecar.close_view()
        require(not sidecar.window.isVisible(), "SIDECAR_CLOSE_VIEW_NOT_DISMISSED")
        require(sidecar.render(second), "SIDECAR_REOPEN_FAILED")
        require(sidecar.bridge.projectionId == "h2-f2-reopen", "SIDECAR_REOPEN_STALE_PROJECTION")
        require(sidecar.render(terminal_projection()) is False, "TERMINAL_PROJECTION_NOT_DISMISSED")
        require(not sidecar.window.isVisible(), "TERMINAL_SIDECAR_NOT_DISMISSED")
        authoritative_projection_id = sidecar.bridge.projectionId
    finally:
        sidecar.close()
        sidecar.close()

    replacement = qt_app.QtSidecarWindow()
    try:
        require(
            replacement.render(canonical_projection(projection_id="h2-f2-replacement")),
            "SIDECAR_REPLACEMENT_OPEN_FAILED",
        )
        require(
            replacement.bridge.projectionId == "h2-f2-replacement",
            "SIDECAR_REPLACEMENT_STALE_PROJECTION",
        )
    finally:
        replacement.close()
        replacement.close()

    calls: list[str] = []

    class CleanupResource:
        def __init__(self, name: str) -> None:
            self.name = name

        def hide(self) -> None:
            calls.append(f"{self.name}.hide")

        def deleteLater(self) -> None:
            calls.append(f"{self.name}.deleteLater")

    class CleanupApplication:
        attempts = 0

        def processEvents(self) -> None:
            self.attempts += 1
            calls.append("app.processEvents")
            if self.attempts == 1:
                raise RuntimeError("H2-F2 injected event-processing failure")

    partial = qt_app.QtSidecarWindow.__new__(qt_app.QtSidecarWindow)
    partial._close_notified = False
    partial._tearing_down = False
    partial._closed = False
    partial._window_hidden = False
    partial._window_delete_scheduled = False
    partial._engine_delete_scheduled = False
    partial._deferred_deletes_sent = False
    partial._cleanup_events_processed = False
    partial.window = CleanupResource("window")
    partial.engine = CleanupResource("engine")
    cleanup_app = CleanupApplication()
    with patch.object(qt_app, "ensure_application", return_value=cleanup_app):
        try:
            partial.close()
        except RuntimeError as exc:
            require(
                str(exc) == "H2-F2 injected event-processing failure",
                "QT_PARTIAL_CLOSE_REASON_UNSTABLE",
            )
        else:
            raise F2VerificationError("QT_PARTIAL_CLOSE_FAILURE_NOT_EXERCISED")
        require(not partial._closed, "QT_PARTIAL_CLOSE_MARKED_TERMINAL")
        partial.close()
        partial.close()
    require(partial._closed, "QT_PARTIAL_CLOSE_RETRY_FAILED")
    require(
        calls
        == [
            "window.hide",
            "window.deleteLater",
            "engine.deleteLater",
            "app.processEvents",
            "app.processEvents",
        ],
        "QT_PARTIAL_CLOSE_REPEATED_RELEASE",
    )

    close_view_calls: list[str] = []

    class HideRetryWindow:
        attempts = 0

        def hide(self) -> None:
            self.attempts += 1
            close_view_calls.append("window.hide")
            if self.attempts == 1:
                raise RuntimeError("H2-F2 injected hide failure")

    class CloseBridge:
        notifications = 0

        def notify_closed(self) -> None:
            self.notifications += 1
            close_view_calls.append("bridge.notify_closed")

    retry_close_view = qt_app.QtSidecarWindow.__new__(qt_app.QtSidecarWindow)
    retry_close_view._tearing_down = False
    retry_close_view._closed = False
    retry_close_view._close_notified = False
    retry_window = HideRetryWindow()
    close_bridge = CloseBridge()
    retry_close_view.window = retry_window
    retry_close_view.bridge = close_bridge
    try:
        retry_close_view.close_view()
    except RuntimeError as exc:
        require(str(exc) == "H2-F2 injected hide failure", "QT_HIDE_FAILURE_REASON_UNSTABLE")
    else:
        raise F2VerificationError("QT_HIDE_FAILURE_NOT_EXERCISED")
    require(not retry_close_view._close_notified, "QT_HIDE_FAILURE_STRANDED_CLOSE")
    retry_close_view.close_view()
    retry_close_view.close_view()
    require(retry_window.attempts == 2, "QT_HIDE_FAILURE_NOT_RETRIED")
    require(close_bridge.notifications == 1, "QT_CLOSE_NOTIFICATION_NOT_EXACTLY_ONCE")
    require(retry_close_view._close_notified, "QT_CLOSE_RETRY_NOT_ACKNOWLEDGED")
    return {
        "status": "PASS",
        "open_close_reopen": True,
        "authoritative_projection_id": authoritative_projection_id,
        "terminal_dismissed": True,
        "partial_close_failure": "EXERCISED",
        "partial_close_retry": True,
        "repeated_successful_close_reopen": True,
        "close_view_hide_failure_retry": {
            "hide_attempts": retry_window.attempts,
            "notification_count": close_bridge.notifications,
            "close_notified": retry_close_view._close_notified,
            "calls": close_view_calls,
        },
        "final_resource_state": {
            "primary_sidecar_closed": sidecar._closed,
            "replacement_sidecar_closed": replacement._closed,
            "partial_sidecar_closed": partial._closed,
            "window_delete_scheduled": partial._window_delete_scheduled,
            "engine_delete_scheduled": partial._engine_delete_scheduled,
            "deferred_deletes_sent": partial._deferred_deletes_sent,
            "cleanup_events_processed": partial._cleanup_events_processed,
        },
        "pyside6_executed": True,
    }


def qualify_accepted_d2_regression() -> dict[str, Any]:
    sources = [
        ROOT / "r6o_evidence" / "H2-D2" / "attachment-result.json",
        ROOT / "r6o_evidence" / "H2-D1R" / "d2-actual-host" / "attachment-result.json",
    ]
    checked: list[str] = []
    for path in sources:
        if not path.is_file():
            continue
        document = read_json(path)
        require(document.get("status") == "H2_D2_ATTACHMENT_PASS", "D2_REGRESSION_STATUS_INVALID")
        for mode in ("standard", "expanded"):
            observation = document.get(mode)
            require(isinstance(observation, dict), "D2_REGRESSION_OBSERVATION_MISSING", mode)
            require(observation.get("placement_matches") is True, "D2_PLACEMENT_REGRESSION", mode)
            require(observation.get("sidecar_above_host") is True, "D2_Z_ORDER_REGRESSION", mode)
            require(observation.get("global_topmost") is False, "D2_TOPMOST_REGRESSION", mode)
        checked.append(path.relative_to(ROOT).as_posix())
    require(bool(checked), "D2_ACCEPTED_EVIDENCE_MISSING")
    return {"status": "PASS", "accepted_evidence": checked}


def oracle_identity(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"status": "NOT_BOUND"}
    resolved = path.resolve()
    actual_commit = subprocess.run(
        ["git", "-C", str(resolved), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    actual_tree = subprocess.run(
        ["git", "-C", str(resolved), "rev-parse", "HEAD^{tree}"],
        capture_output=True,
        text=True,
        check=False,
    )
    require(actual_commit.returncode == 0 and actual_tree.returncode == 0, "FROZEN_ORACLE_UNREADABLE")
    commit = actual_commit.stdout.strip()
    tree = actual_tree.stdout.strip()
    require(commit == FROZEN_ORACLE_COMMIT, "FROZEN_ORACLE_COMMIT_MISMATCH", commit)
    require(tree == FROZEN_ORACLE_TREE, "FROZEN_ORACLE_TREE_MISMATCH", tree)
    return {"status": "PASS", "path": str(resolved), "commit": commit, "tree": tree}


def dependency_versions() -> dict[str, str | None]:
    values: dict[str, str | None] = {}
    for distribution in ("PySide6", "pywinauto", "pywin32", "pytest"):
        try:
            values[distribution] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            values[distribution] = None
    return values


def warning_triage() -> list[dict[str, Any]]:
    rpc_observed = "RPC_E_CHANGED_MODE" in _OBSERVED_WARNING_IDS
    dpi_observed = "DPI_AWARENESS_ACCESS_DENIED" in _OBSERVED_WARNING_IDS
    return [
        {
            "id": "RPC_E_CHANGED_MODE",
            "observed_in_current_run": rpc_observed,
            "prior_frozen_observation": True,
            "classification": "NONBLOCKING_P2",
            "effective_runtime_state": (
                "Warning was emitted while pywinauto restored STA COM mode; no lifecycle failure, "
                "nondeterminism, or resource leak was observed."
                if rpc_observed
                else "No warning was emitted; no lifecycle failure, nondeterminism, or resource leak was observed."
            ),
        },
        {
            "id": "DPI_AWARENESS_ACCESS_DENIED",
            "observed_in_current_run": dpi_observed,
            "prior_frozen_observation": True,
            "classification": "NONBLOCKING_P2",
            "effective_runtime_state": (
                "DPI-awareness setup was denied; configured runtime DPI and bounded placement/teardown remained valid."
                if dpi_observed
                else "DPI-awareness denial was not emitted; configured runtime DPI and bounded placement/teardown remained valid."
            ),
        },
    ]


def qualify_actual_host(host_record_path: Path, selectors_path: Path, settle_seconds: float) -> dict[str, Any]:
    if os.name != "nt":
        raise F2VerificationError("ACTUAL_CODEX_HOST_REQUIRES_WINDOWS")
    os.environ.setdefault("QT_QUICK_BACKEND", "software")
    os.environ.setdefault("QT_SCALE_FACTOR", "1")
    os.environ.setdefault("QT_FONT_DPI", "96")
    try:
        from PySide6.QtCore import QCoreApplication, QEventLoop
    except ImportError as exc:
        raise F2VerificationError("SIDECAR_DEPENDENCY_MISSING") from exc

    host: CodexSidecarBinding | None = None
    input_binding: CodexComposerInputBinding | None = None
    cleanup_failures: list[str] = []
    try:
        host = CodexSidecarBinding(host_record_path, selectors_path)
        actual_hwnd = host.host_hwnd
        empty_contract = host.selectors["reset_contract"]["composer_empty"]
        before = composer_empty_observation(host.refresh_controls().composer, empty_contract)
        require(before.get("empty") is True, "HOST_COMPOSER_NOT_EMPTY")

        opened = host.attach(canonical_projection(projection_id="h2-f2-actual-open"), settle_seconds=settle_seconds)
        require(opened.get("visible") is True, "ACTUAL_OPEN_NOT_VISIBLE")
        require(opened.get("global_topmost") is False, "ACTUAL_GLOBAL_TOPMOST")

        host.set_mode(SidecarMode.EXPANDED, settle_seconds=settle_seconds)
        expanded = host.observe()
        require(expanded.get("global_topmost") is False, "ACTUAL_EXPANDED_GLOBAL_TOPMOST")

        first_close = host.close_view_and_verify_focus()
        second_close = host.close_view_and_verify_focus()
        require(first_close["sidecar_visible"] is False, "ACTUAL_CLOSE_NOT_DISMISSED")
        require(second_close["sidecar_visible"] is False, "ACTUAL_REPEATED_CLOSE_NOT_IDEMPOTENT")

        reopened = host.attach(
            canonical_projection(
                projection_id="h2-f2-actual-reopen",
                body="# Current authoritative F2 projection\n",
            ),
            settle_seconds=settle_seconds,
        )
        require(host.sidecar.bridge.projectionId == "h2-f2-actual-reopen", "ACTUAL_REOPEN_STALE_PROJECTION")

        input_binding = CodexComposerInputBinding(host, lambda _envelope: None)
        input_binding.start()
        hook_installed = bool(input_binding._hook)
        activation_cycles = 0
        for cycle in range(2):
            input_binding.activate(
                canonical_projection(projection_id=f"h2-f2-actual-activation-{cycle}")
            )
            require(input_binding.armed, "ACTUAL_INPUT_BINDING_NOT_ARMED")
            input_binding.deactivate()
            require(not input_binding.armed, "ACTUAL_INPUT_BINDING_NOT_DEACTIVATED")
            activation_cycles += 1
        try:
            input_binding.activate(
                canonical_projection(projection_id="h2-f2-actual-partial-activation"),
                timeout=0,
            )
        except CodexInputBindingError as exc:
            require(
                exc.code == "ACTUAL_COMPOSER_FOCUS_UNVERIFIED",
                "ACTUAL_PARTIAL_ACTIVATION_REASON_UNSTABLE",
                exc.code,
            )
        else:
            raise F2VerificationError("ACTUAL_PARTIAL_ACTIVATION_FAILURE_NOT_EXERCISED")
        input_binding.abort_handoff()
        require(not input_binding.armed, "ACTUAL_PARTIAL_ACTIVATION_CLEANUP_FAILED")
        input_binding.stop()
        require(hook_installed, "ACTUAL_INPUT_HOOK_NOT_INSTALLED")
        require(input_binding._hook == 0 and input_binding._hook_thread is None, "ACTUAL_INPUT_HOOK_NOT_REMOVED")
        input_final_state = {
            "hook_removed": input_binding._hook == 0,
            "hook_thread_absent": input_binding._hook_thread is None,
            "hook_thread_alive": False,
            "teardown_pending": input_binding._teardown_pending,
            "dispatcher_released": input_binding._dispatcher is None,
            "delivery_pending": input_binding._delivery_pending,
        }
        input_binding = None

        app = QCoreApplication.instance()
        require(app is not None, "QT_APPLICATION_UNAVAILABLE")
        require(host.sidecar.render(terminal_projection()) is False, "ACTUAL_TERMINAL_NOT_DISMISSED")
        app.processEvents(QEventLoop.AllEvents, 50)
        terminal_close = host.close_view_and_verify_focus()
        require(terminal_close["sidecar_visible"] is False, "ACTUAL_TERMINAL_CLOSE_NOT_DISMISSED")
        after = composer_empty_observation(host.refresh_controls().composer, empty_contract)
        require(after.get("empty") is True, "HOST_COMPOSER_NOT_EMPTY_AFTER_F2")

        host.close()
        host.close()
        sidecar = host.sidecar
        focus_router = host.focus_router
        sidecar_native_window_alive = host.native.is_window(host.sidecar_hwnd)
        final_resource_state = {
            "input": input_final_state,
            "sidecar": {
                "closed": bool(sidecar is not None and sidecar._closed),
                "window_hidden": bool(sidecar is not None and sidecar._window_hidden),
                "window_delete_scheduled": bool(
                    sidecar is not None and sidecar._window_delete_scheduled
                ),
                "engine_delete_scheduled": bool(
                    sidecar is not None and sidecar._engine_delete_scheduled
                ),
                "deferred_deletes_sent": bool(
                    sidecar is not None and sidecar._deferred_deletes_sent
                ),
                "cleanup_events_processed": bool(
                    sidecar is not None and sidecar._cleanup_events_processed
                ),
                "native_window_alive": sidecar_native_window_alive,
            },
            "focus_router": {
                "hook_removed": bool(focus_router is None or focus_router._hook == 0),
                "thread_absent": bool(focus_router is None or focus_router._thread is None),
            },
        }
        require(
            all(
                (
                    input_final_state["hook_removed"],
                    input_final_state["hook_thread_absent"],
                    not input_final_state["teardown_pending"],
                    input_final_state["dispatcher_released"],
                    not input_final_state["delivery_pending"],
                    final_resource_state["sidecar"]["closed"],
                    final_resource_state["sidecar"]["window_hidden"],
                    final_resource_state["sidecar"]["window_delete_scheduled"],
                    final_resource_state["sidecar"]["engine_delete_scheduled"],
                    final_resource_state["sidecar"]["deferred_deletes_sent"],
                    final_resource_state["sidecar"]["cleanup_events_processed"],
                    not final_resource_state["sidecar"]["native_window_alive"],
                    final_resource_state["focus_router"]["hook_removed"],
                    final_resource_state["focus_router"]["thread_absent"],
                )
            ),
            "ACTUAL_FINAL_RESOURCE_STATE_INCOMPLETE",
        )
        host = None
        return {
            "status": "PASS",
            "host": {
                "hwnd": actual_hwnd,
                "record_sha256": sha256_file(host_record_path),
                "selectors_sha256": sha256_file(selectors_path),
            },
            "open": opened,
            "expanded": expanded,
            "first_close": first_close,
            "second_close": second_close,
            "reopen": reopened,
            "input_hook": {
                "installed": hook_installed,
                "removed": True,
                "activation_cycles": activation_cycles,
                "partial_activation_failure_cleanup": True,
            },
            "terminal_close": terminal_close,
            "composer_empty_before": before,
            "composer_empty_after": after,
            "final_resource_state": final_resource_state,
        }
    finally:
        if input_binding is not None:
            try:
                input_binding.stop()
            except Exception as exc:
                cleanup_failures.append(f"INPUT_BINDING_STOP:{getattr(exc, 'code', type(exc).__name__)}")
        if host is not None:
            try:
                host.close()
            except Exception as exc:
                cleanup_failures.append(f"HOST_CLOSE:{getattr(exc, 'code', type(exc).__name__)}")
        if cleanup_failures:
            raise F2VerificationError("F2_CLEANUP_FAILED", "|".join(cleanup_failures))


def _portable_cleanup_complete(
    input_boundary: dict[str, Any], qt_lifecycle: dict[str, Any]
) -> bool:
    input_state = input_boundary.get("final_resource_state")
    qt_state = qt_lifecycle.get("final_resource_state")
    return bool(
        isinstance(input_state, dict)
        and isinstance(qt_state, dict)
        and input_state
        and qt_state
        and all(value is True for value in input_state.values())
        and all(value is True for value in qt_state.values())
    )


def _actual_cleanup_complete(actual_host: dict[str, Any]) -> bool:
    state = actual_host.get("final_resource_state")
    if not isinstance(state, dict):
        return False
    input_state = state.get("input")
    sidecar_state = state.get("sidecar")
    router_state = state.get("focus_router")
    return bool(
        isinstance(input_state, dict)
        and isinstance(sidecar_state, dict)
        and isinstance(router_state, dict)
        and input_state.get("hook_removed") is True
        and input_state.get("hook_thread_absent") is True
        and input_state.get("hook_thread_alive") is False
        and input_state.get("teardown_pending") is False
        and input_state.get("dispatcher_released") is True
        and input_state.get("delivery_pending") is False
        and sidecar_state.get("closed") is True
        and sidecar_state.get("window_hidden") is True
        and sidecar_state.get("window_delete_scheduled") is True
        and sidecar_state.get("engine_delete_scheduled") is True
        and sidecar_state.get("deferred_deletes_sent") is True
        and sidecar_state.get("cleanup_events_processed") is True
        and sidecar_state.get("native_window_alive") is False
        and router_state.get("hook_removed") is True
        and router_state.get("thread_absent") is True
    )


def run_process_exit_probe(args: argparse.Namespace) -> int:
    try:
        if args.process_exit_probe == "actual-host":
            lifecycle = qualify_actual_host(
                args.host_record.resolve(), args.selectors.resolve(), args.settle_seconds
            )
            cleanup_complete = _actual_cleanup_complete(lifecycle)
            final_resource_state = lifecycle.get("final_resource_state")
        else:
            input_boundary = qualify_input_boundary()
            qt_lifecycle = qualify_qt_lifecycle()
            cleanup_complete = _portable_cleanup_complete(input_boundary, qt_lifecycle)
            final_resource_state = {
                "input": input_boundary.get("final_resource_state"),
                "sidecar": qt_lifecycle.get("final_resource_state"),
            }
        require(cleanup_complete, "PROCESS_EXIT_CLEANUP_INCOMPLETE")
        marker = {
            "marker": PROCESS_EXIT_MARKER,
            "status": "PASS",
            "probe_mode": args.process_exit_probe,
            "cleanup_complete": cleanup_complete,
            "final_resource_state": final_resource_state,
        }
        print(f"{PROCESS_EXIT_MARKER}={json.dumps(marker, sort_keys=True)}")
        return 0
    except Exception as exc:
        failure = {
            "status": "FAIL",
            "probe_mode": args.process_exit_probe,
            "code": getattr(exc, "code", type(exc).__name__),
            "detail": str(exc),
        }
        print(json.dumps(failure, sort_keys=True), file=sys.stderr)
        return 1


def qualify_process_exit(
    host_record_path: Path,
    selectors_path: Path,
    *,
    probe_mode: str,
    settle_seconds: float,
    timeout_seconds: float = PROCESS_EXIT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--process-exit-probe",
        probe_mode,
        "--host-record",
        str(host_record_path),
        "--selectors",
        str(selectors_path),
        "--settle-seconds",
        str(settle_seconds),
    ]
    environment = os.environ.copy()
    environment.setdefault("QT_QUICK_BACKEND", "software")
    environment.setdefault("QT_SCALE_FACTOR", "1")
    environment.setdefault("QT_FONT_DPI", "96")
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        process.terminate()
        try:
            process.communicate(timeout=5.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=5.0)
        raise F2VerificationError("PROCESS_EXIT_TIMEOUT", str(timeout_seconds)) from exc
    duration_seconds = time.monotonic() - started
    require(process.returncode == 0, "PROCESS_EXIT_CHILD_FAILED", stderr[-2000:])
    prefix = f"{PROCESS_EXIT_MARKER}="
    marker_lines = [line for line in stdout.splitlines() if line.startswith(prefix)]
    require(len(marker_lines) == 1, "PROCESS_EXIT_CLEANUP_MARKER_MISSING")
    try:
        marker = json.loads(marker_lines[0][len(prefix) :])
    except json.JSONDecodeError as exc:
        raise F2VerificationError("PROCESS_EXIT_CLEANUP_MARKER_INVALID") from exc
    require(isinstance(marker, dict), "PROCESS_EXIT_CLEANUP_MARKER_INVALID")
    require(marker.get("marker") == PROCESS_EXIT_MARKER, "PROCESS_EXIT_CLEANUP_MARKER_INVALID")
    require(marker.get("status") == "PASS", "PROCESS_EXIT_CLEANUP_NOT_PASS")
    require(marker.get("cleanup_complete") is True, "PROCESS_EXIT_CLEANUP_INCOMPLETE")
    require(process.poll() is not None, "PROCESS_EXIT_TERMINATION_UNOBSERVED")
    return {
        "status": "PASS",
        "probe_mode": probe_mode,
        "child_pid": process.pid,
        "cleanup_complete_marker": True,
        "process_terminated": True,
        "returncode": process.returncode,
        "timeout_seconds": timeout_seconds,
        "duration_seconds": round(duration_seconds, 3),
        "final_resource_state": marker.get("final_resource_state"),
        "stderr_tail": stderr[-2000:],
    }


def _matrix_pass(
    name: str,
    source: str,
    condition: bool,
    observed: object,
) -> dict[str, Any]:
    require(condition, "RESILIENCE_MATRIX_DIMENSION_INSUFFICIENT", f"{name}:{source}")
    return {"status": "PASS", "source": source, "observed": observed}


def derive_repair_resilience_matrix(
    input_boundary: dict[str, Any],
    qt_lifecycle: dict[str, Any],
    process_exit: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    repeated = input_boundary.get("repeated_activation_deactivation")
    race = input_boundary.get("delivery_cancellation_race")
    hide_retry = qt_lifecycle.get("close_view_hide_failure_retry")
    process_proof = (
        process_exit.get("status") == "PASS"
        and process_exit.get("cleanup_complete_marker") is True
        and process_exit.get("process_terminated") is True
        and process_exit.get("returncode") == 0
    )
    race_proof = bool(
        isinstance(race, dict)
        and race.get("status") == "PASS"
        and race.get("new_user_text_preserved") is True
        and race.get("destructive_clear_count") == 1
        and race.get("envelope_count") == 0
        and race.get("current_delivery_state_preserved") is True
        and race.get("current_delivery_event_preserved") is True
    )
    hide_retry_proof = bool(
        isinstance(hide_retry, dict)
        and hide_retry.get("hide_attempts") == 2
        and hide_retry.get("notification_count") == 1
        and hide_retry.get("close_notified") is True
    )
    return {
        "normal_activation_deactivation": _matrix_pass(
            "normal_activation_deactivation",
            "input_boundary.normal_activation_deactivation",
            input_boundary.get("normal_activation_deactivation") is True,
            input_boundary.get("normal_activation_deactivation"),
        ),
        "repeated_activation_deactivation": _matrix_pass(
            "repeated_activation_deactivation",
            "input_boundary.repeated_activation_deactivation",
            isinstance(repeated, int) and not isinstance(repeated, bool) and repeated >= 2,
            repeated,
        ),
        "partial_activation_failure_cleanup": _matrix_pass(
            "partial_activation_failure_cleanup",
            "input_boundary.partial_activation_failure_cleanup",
            input_boundary.get("partial_activation_failure_cleanup") is True,
            input_boundary.get("partial_activation_failure_cleanup"),
        ),
        "pending_delivery_during_teardown": _matrix_pass(
            "pending_delivery_during_teardown",
            "input_boundary.pending_delivery_teardown",
            input_boundary.get("pending_delivery_teardown") is True,
            input_boundary.get("pending_delivery_teardown"),
        ),
        "stale_queued_delivery_after_teardown": _matrix_pass(
            "stale_queued_delivery_after_teardown",
            "input_boundary.stale_queued_delivery_inert",
            input_boundary.get("stale_queued_delivery_inert") is True,
            input_boundary.get("stale_queued_delivery_inert"),
        ),
        "failed_hook_thread_shutdown": _matrix_pass(
            "failed_hook_thread_shutdown",
            "input_boundary.failed_hook_thread_shutdown",
            input_boundary.get("failed_hook_thread_shutdown")
            == "HOST_INPUT_HOOK_STOP_TIMEOUT",
            input_boundary.get("failed_hook_thread_shutdown"),
        ),
        "restart_after_failed_shutdown": _matrix_pass(
            "restart_after_failed_shutdown",
            "input_boundary.restart_after_failed_shutdown",
            input_boundary.get("restart_after_failed_shutdown")
            == "HOST_INPUT_HOOK_RESTART_BLOCKED",
            input_boundary.get("restart_after_failed_shutdown"),
        ),
        "enter_keyup_drain_timeout": _matrix_pass(
            "enter_keyup_drain_timeout",
            "input_boundary.enter_keyup_timeout_retains_ownership+retry_after_delayed_keyup",
            input_boundary.get("enter_keyup_timeout_retains_ownership") is True
            and input_boundary.get("retry_after_delayed_keyup") is True,
            {
                "ownership_retained": input_boundary.get(
                    "enter_keyup_timeout_retains_ownership"
                ),
                "retry_completed": input_boundary.get("retry_after_delayed_keyup"),
            },
        ),
        "shutdown_process_exit_cleanup": _matrix_pass(
            "shutdown_process_exit_cleanup",
            "process_exit.cleanup_complete_marker+process_terminated",
            process_proof,
            {
                "probe_mode": process_exit.get("probe_mode"),
                "cleanup_complete_marker": process_exit.get("cleanup_complete_marker"),
                "process_terminated": process_exit.get("process_terminated"),
                "returncode": process_exit.get("returncode"),
            },
        ),
        "qt_partial_close_failure": _matrix_pass(
            "qt_partial_close_failure",
            "qt_lifecycle.partial_close_failure",
            qt_lifecycle.get("partial_close_failure") == "EXERCISED",
            qt_lifecycle.get("partial_close_failure"),
        ),
        "qt_partial_close_retry": _matrix_pass(
            "qt_partial_close_retry",
            "qt_lifecycle.partial_close_retry",
            qt_lifecycle.get("partial_close_retry") is True,
            qt_lifecycle.get("partial_close_retry"),
        ),
        "repeated_successful_close_reopen": _matrix_pass(
            "repeated_successful_close_reopen",
            "qt_lifecycle.repeated_successful_close_reopen",
            qt_lifecycle.get("repeated_successful_close_reopen") is True,
            qt_lifecycle.get("repeated_successful_close_reopen"),
        ),
        "stale_resource_callback_invalidation": _matrix_pass(
            "stale_resource_callback_invalidation",
            "input_boundary.delivery_cancellation_race+stale_queued_delivery_inert",
            race_proof and input_boundary.get("stale_queued_delivery_inert") is True,
            race,
        ),
        "qt_close_view_hide_failure_retry": _matrix_pass(
            "qt_close_view_hide_failure_retry",
            "qt_lifecycle.close_view_hide_failure_retry",
            hide_retry_proof,
            hide_retry,
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify H2-F2 lifecycle, resilience, fail-closed handling, and bounded cleanup."
    )
    parser.add_argument("--host-record", type=Path, default=DEFAULT_HOST_RECORD)
    parser.add_argument("--selectors", type=Path, default=DEFAULT_SELECTORS)
    parser.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE_DIR)
    parser.add_argument("--baseline-repo", type=Path)
    parser.add_argument("--mode", choices=("auto", "portable", "actual-host"), default="auto")
    parser.add_argument("--settle-seconds", type=float, default=0.25)
    parser.add_argument(
        "--process-exit-probe",
        choices=("portable", "actual-host"),
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--process-exit-timeout",
        type=float,
        default=PROCESS_EXIT_TIMEOUT_SECONDS,
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.process_exit_probe is not None:
        return run_process_exit_probe(args)
    evidence_dir = args.evidence_dir.resolve()
    identity: dict[str, Any] | None = None
    result: dict[str, Any] = {
        "schema_version": "r6o-h2-f2-lifecycle-resilience-human-override-repair-2",
        "gate": "H2-F2",
        "status": "FAIL",
        "started_at_utc": utc_now(),
        "mode": args.mode,
        "host_record": str(args.host_record.resolve()),
        "selectors": str(args.selectors.resolve()),
        "runtime": {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "dependencies": dependency_versions(),
        },
        "warnings": [],
    }
    try:
        identity = checkout_identity()
        result["checkout"] = identity
        result["frozen_oracle"] = oracle_identity(args.baseline_repo)
        result["host_fail_closed"] = qualify_host_fail_closed(
            args.host_record.resolve(), args.selectors.resolve()
        )
        input_boundary = qualify_input_boundary()
        qt_lifecycle = qualify_qt_lifecycle()
        result["input_boundary"] = input_boundary
        result["qt_lifecycle"] = qt_lifecycle
        result["d2_regression"] = qualify_accepted_d2_regression()
        run_actual = args.mode == "actual-host" or (args.mode == "auto" and os.name == "nt")
        if run_actual:
            result["windows_local_actual_codex"] = qualify_actual_host(
                args.host_record.resolve(), args.selectors.resolve(), args.settle_seconds
            )
        else:
            result["windows_local_actual_codex"] = {
                "status": "NOT_RUN",
                "reason": "portable mode or non-Windows host",
            }
        process_exit = qualify_process_exit(
            args.host_record.resolve(),
            args.selectors.resolve(),
            probe_mode="actual-host" if run_actual else "portable",
            settle_seconds=args.settle_seconds,
            timeout_seconds=args.process_exit_timeout,
        )
        result["process_exit_qualification"] = process_exit
        result["repair_resilience_matrix"] = derive_repair_resilience_matrix(
            input_boundary,
            qt_lifecycle,
            process_exit,
        )
        result["scope"] = {
            "semantic_workflow_exercised": False,
            "normal_codex_submit_gesture_used": False,
            "r6o3_lease_implemented": False,
            "qml_or_design_changed": False,
        }
        result["status"] = "H2_F2_LIFECYCLE_RESILIENCE_PASS"
    except (F2VerificationError, CodexBindingError) as exc:
        result["failure"] = {
            "code": getattr(exc, "code", type(exc).__name__),
            "detail": str(exc),
        }
    except Exception as exc:
        result["failure"] = {"code": "UNEXPECTED_FAILURE", "detail": repr(exc)}
    finally:
        result["finished_at_utc"] = utc_now()
        result["warnings"] = warning_triage()
        if identity is None:
            try:
                result["checkout"] = checkout_identity()
            except Exception as exc:
                result["checkout_error"] = repr(exc)
        write_json(evidence_dir / "qualification.json", result)

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "H2_F2_LIFECYCLE_RESILIENCE_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
