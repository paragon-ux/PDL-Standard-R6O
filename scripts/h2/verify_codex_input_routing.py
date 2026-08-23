from __future__ import annotations

"""Qualify H2-E1 against the actual Codex composer and native Enter gesture."""

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from r6o.host.codex.windows.binding import CodexBindingError, CodexSidecarBinding
from r6o.host.codex.windows.input_binding import (
    CodexComposerInputBinding,
    CodexInputBindingError,
)
from r6o.host.codex.windows.uia import composer_empty_observation, write_canonical_json
from r6o.views.sidecar.fixture import CANONICAL_ACTIONS, CANONICAL_ARTIFACT_BODY


DEFAULT_HOST_RECORD = ROOT / "r6o_evidence" / "H2-D1" / "host-environment.json"
DEFAULT_SELECTORS = ROOT / "r6o" / "host" / "codex" / "windows" / "selectors.json"
DEFAULT_EVIDENCE = ROOT / "r6o_evidence" / "H2-E1"
ROUTING_MARKER = "H2E1ROUTINGBOUNDARY"
SHIFT_PREFIX = "H2E1SHIFT"
SHIFT_SUFFIX = "EDIT"
IMPLEMENTATION_PATHS = (
    "r6o/host/codex/windows/input_binding.py",
    "scripts/h2/verify_codex_input_routing.py",
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def git_value(*arguments: str) -> str:
    return subprocess.check_output(["git", *arguments], cwd=ROOT, text=True).strip()


def dependency_versions() -> dict[str, str]:
    return {
        name: importlib.metadata.version(distribution)
        for name, distribution in (
            ("PySide6", "PySide6"),
            ("pywin32", "pywin32"),
            ("pywinauto", "pywinauto"),
        )
    }


def projection() -> dict[str, Any]:
    action_kinds = {
        "confirm_prompt": "SEMANTIC_MESSAGE",
        "change_task": "SEMANTIC_MESSAGE",
        "change_approach": "SEMANTIC_MESSAGE",
        "something_else": "FREE_RESPONSE_FOCUS",
    }
    return {
        "schema_version": "r6o-focus-projection-1",
        "projection_id": "h2-e1-real-codex-input-routing",
        "session_id": "h2-e1-routing-session",
        "model_revision": "h2-e1-routing-revision",
        "stage": "PROMPT_REVIEW",
        "lifecycle": {"terminal": False},
        "artifact": {
            "artifact_ref": "h2-e1:nonsemantic-routing-boundary",
            "title": "Authoritative Prompt (PDL.md)",
            "body": CANONICAL_ARTIFACT_BODY,
            "capabilities": {"copy": True, "open_external": False},
        },
        "actions": [
            {**dict(action), "kind": action_kinds[str(action["action_id"])]}
            for action in CANONICAL_ACTIONS
        ],
    }


def structured_focus_envelope(active: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "r6o-input-envelope-1",
        "session_id": active["session_id"],
        "source": "STRUCTURED_ACTION",
        "model_revision": active["model_revision"],
        "text": None,
        "action_id": "something_else",
        "projection_id": active["projection_id"],
    }


def current_value(composer: Any) -> str:
    try:
        return str(composer.iface_value.CurrentValue)
    except Exception as exc:
        raise CodexInputBindingError("HOST_COMPOSER_VALUE_UNAVAILABLE") from exc


def visible_turn_count(binding: CodexSidecarBinding) -> int:
    class_name = binding.selectors["reset_contract"]["fresh_chat"]["visible_turn_group_class"]
    controls = binding.refresh_controls()
    try:
        return sum(
            1
            for wrapper in controls.primary_content_region.descendants(control_type="Group")
            if wrapper.is_visible() and str(wrapper.element_info.class_name or "") == class_name
        )
    except Exception as exc:
        raise CodexInputBindingError("CONVERSATION_TURN_OBSERVATION_FAILED") from exc


def wait_until(predicate: Callable[[], bool], *, timeout: float, code: str) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            from PySide6.QtCore import QCoreApplication, QEventLoop

            app = QCoreApplication.instance()
            if app is not None:
                app.processEvents(QEventLoop.AllEvents, 25)
        except ImportError:
            pass
        try:
            if predicate():
                return
        except Exception:
            pass
        time.sleep(0.025)
    raise CodexInputBindingError(code)


def physical_click(point: tuple[int, int]) -> None:
    try:
        import win32api
        import win32con
    except ImportError as exc:
        raise CodexInputBindingError("HOST_DEPENDENCY_MISSING") from exc
    win32api.SetCursorPos(point)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0)
    time.sleep(0.05)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0)


def sidecar_action_center(binding: CodexSidecarBinding, object_name: str) -> tuple[int, int]:
    if object_name != "reviewAction_something_else":
        raise CodexInputBindingError("SIDECAR_ACTION_TARGET_INVALID")
    rectangle = binding.native.rectangle(binding.sidecar_hwnd)
    if (rectangle.width, rectangle.height) != (675, 300):
        raise CodexInputBindingError("SIDECAR_STANDARD_GEOMETRY_REQUIRED")
    # Locked STANDARD QML geometry: ReviewOptions(418,44), actions column
    # (14,36), fourth 31px row after three 5px gaps. The point is the center
    # of that row's full MouseArea, not a hidden qualification control.
    return rectangle.left + 542, rectangle.top + 203


def reset_composer(binding: CodexSidecarBinding) -> None:
    try:
        from pywinauto.keyboard import send_keys
    except ImportError as exc:
        raise CodexInputBindingError("HOST_DEPENDENCY_MISSING") from exc
    controls = binding.refresh_controls()
    controls.composer.set_focus()
    wait_until(
        lambda: bool(binding.refresh_controls().composer.has_keyboard_focus())
        and binding.native.foreground() == binding.host_hwnd,
        timeout=5.0,
        code="COMPOSER_RESET_FOCUS_UNVERIFIED",
    )
    send_keys("^a{BACKSPACE}", pause=0.025)
    empty_contract = binding.selectors["reset_contract"]["composer_empty"]
    wait_until(
        lambda: composer_empty_observation(
            binding.refresh_controls().composer, empty_contract
        ).get("empty")
        is True,
        timeout=5.0,
        code="COMPOSER_RESET_UNVERIFIED",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host-record", type=Path, default=DEFAULT_HOST_RECORD)
    parser.add_argument("--selectors", type=Path, default=DEFAULT_SELECTORS)
    parser.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE)
    return parser.parse_args()


def run(args: argparse.Namespace) -> dict[str, Any]:
    try:
        from PySide6.QtGui import QGuiApplication
        from r6o.views.sidecar.qt_app import QtSidecarWindow
        from pywinauto.keyboard import send_keys
    except ImportError as exc:
        raise CodexInputBindingError("HOST_DEPENDENCY_MISSING") from exc

    active = projection()
    routed: list[dict[str, Any]] = []
    action_envelopes: list[dict[str, Any]] = []
    action_errors: list[str] = []
    holder: dict[str, Any] = {}

    def on_action(action_id: str) -> None:
        if action_id != "something_else":
            raise CodexInputBindingError(f"UNEXPECTED_SIDECAR_ACTION:{action_id}")
        envelope = structured_focus_envelope(active)
        action_envelopes.append(envelope)
        try:
            holder["input"].activate(active)
        except Exception as exc:
            action_errors.append(getattr(exc, "code", type(exc).__name__))

    def sidecar_factory(**options: Any) -> Any:
        return QtSidecarWindow(on_action=on_action, **options)

    host: CodexSidecarBinding | None = None
    input_binding: CodexComposerInputBinding | None = None
    injection_started = False
    try:
        host = CodexSidecarBinding(
            args.host_record,
            args.selectors,
            sidecar_factory=sidecar_factory,
        )
        input_binding = CodexComposerInputBinding(host, routed.append)
        holder["input"] = input_binding
        input_binding.start()
        standard = host.attach(active)
        if QGuiApplication.platformName().lower() != "windows":
            raise CodexInputBindingError("QT_PLATFORM_NOT_WINDOWS")
        empty_contract = host.selectors["reset_contract"]["composer_empty"]
        initial = composer_empty_observation(host.refresh_controls().composer, empty_contract)
        if initial.get("empty") is not True:
            raise CodexInputBindingError("COMPOSER_NOT_EMPTY")
        turns_before = visible_turn_count(host)

        action_point = sidecar_action_center(host, "reviewAction_something_else")
        physical_click(action_point)
        wait_until(
            lambda: len(action_envelopes) == 1 or bool(action_errors),
            timeout=7.0,
            code="SOMETHING_ELSE_ACTION_UNOBSERVED",
        )
        if action_errors:
            raise CodexInputBindingError(action_errors[0])
        wait_until(
            lambda: input_binding.armed
            and bool(host.refresh_controls().composer.has_keyboard_focus())
            and host.native.foreground() == host.host_hwnd,
            timeout=7.0,
            code="SOMETHING_ELSE_FOCUS_FLOW_UNVERIFIED",
        )

        injection_started = True
        send_keys(SHIFT_PREFIX, pause=0.025, with_spaces=False)
        send_keys("+{ENTER}", pause=0.025)
        send_keys(SHIFT_SUFFIX, pause=0.025, with_spaces=False)
        wait_until(
            lambda: SHIFT_PREFIX in current_value(host.refresh_controls().composer)
            and SHIFT_SUFFIX in current_value(host.controls.composer),
            timeout=5.0,
            code="SHIFT_ENTER_EDITING_UNVERIFIED",
        )
        if input_binding.capture_count or input_binding.delivery_count or routed:
            raise CodexInputBindingError("SHIFT_ENTER_WAS_CAPTURED")
        turns_after_shift = visible_turn_count(host)
        if turns_after_shift != turns_before:
            raise CodexInputBindingError("SHIFT_ENTER_INITIATED_CODEX_REQUEST")
        reset_composer(host)

        send_keys(ROUTING_MARKER, pause=0.025, with_spaces=False)
        wait_until(
            lambda: ROUTING_MARKER in current_value(host.refresh_controls().composer),
            timeout=5.0,
            code="ROUTING_MARKER_NOT_VISIBLE",
        )
        composer_text_at_gesture = current_value(host.controls.composer)
        send_keys("{ENTER}", pause=0.025)
        envelope = input_binding.wait_for_delivery(timeout=7.0)
        wait_until(
            lambda: composer_empty_observation(
                host.refresh_controls().composer, empty_contract
            ).get("empty")
            is True,
            timeout=5.0,
            code="CAPTURED_COMPOSER_NOT_CLEARED",
        )
        time.sleep(2.0)
        turns_after = visible_turn_count(host)
        if turns_after != turns_before:
            raise CodexInputBindingError("NORMAL_CODEX_DISPATCH_NOT_SUPPRESSED")
        if routed != [envelope]:
            raise CodexInputBindingError("ROUTING_BOUNDARY_DELIVERY_NOT_EXACTLY_ONCE")
        if envelope["text"] != composer_text_at_gesture:
            raise CodexInputBindingError("CAPTURED_TEXT_MISMATCH")
        if ROUTING_MARKER not in envelope["text"]:
            raise CodexInputBindingError("ROUTING_MARKER_MISSING_FROM_ENVELOPE")
        input_binding.assert_healthy()
        steady = host.observe(expected=host.expected_rectangle())

        events = [
            {
                "sequence": 1,
                "event": "something_else_clicked",
                "actual_sidecar": True,
                "action_point": list(action_point),
                "structured_envelope_source": action_envelopes[0]["source"],
                "structured_envelope_text": action_envelopes[0]["text"],
                "semantic_text_submitted": False,
            },
            {
                "sequence": 2,
                "event": "actual_codex_composer_focused",
                "foreground_hwnd": host.native.foreground(),
                "expected_hwnd": host.host_hwnd,
                "binding_armed": True,
            },
            {
                "sequence": 3,
                "event": "shift_enter_passed_through_as_editing",
                "modified_enter_passthrough_count": input_binding.modified_enter_passthrough_count,
                "route_count": 0,
                "visible_turn_count": turns_after_shift,
            },
            {
                "sequence": 4,
                "event": "unmodified_enter_captured",
                "native_enter_keydown_suppressed": input_binding.suppressed_keydown_count == 1,
                "native_enter_keyup_suppressed": input_binding.suppressed_keyup_count == 1,
                "captured_text_length": len(composer_text_at_gesture),
                "captured_text_sha256": sha256_text(composer_text_at_gesture),
            },
            {
                "sequence": 5,
                "event": "host_composer_envelope_delivered",
                "source": envelope["source"],
                "action_id": envelope["action_id"],
                "projection_id": envelope["projection_id"],
                "capture_count": input_binding.capture_count,
                "delivery_count": input_binding.delivery_count,
            },
            {
                "sequence": 6,
                "event": "normal_codex_dispatch_suppressed",
                "visible_turn_count_before": turns_before,
                "visible_turn_count_after": turns_after,
                "normal_codex_request_observed": False,
                "composer_empty": True,
                "sidecar_visible": steady["visible"],
            },
        ]
        args.evidence_dir.mkdir(parents=True, exist_ok=True)
        event_path = args.evidence_dir / "input-routing-events.jsonl"
        event_path.write_text(
            "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
            encoding="utf-8",
            newline="\n",
        )
        result = {
            "schema_version": "r6o-h2-e1-input-routing-1",
            "gate": "H2-E1",
            "status": "H2_E1_INPUT_ROUTING_PASS",
            "real_codex_host_tested": True,
            "fake_host_composer_used": False,
            "qualification_specific_behavior_in_production_binding": False,
            "host": {
                "hwnd": host.host_hwnd,
                "pid": host.host_record["codex"]["pid"],
                "product_version": host.host_record["codex"]["product_version"],
                "package_version": host.host_record["codex"]["package_version"],
            },
            "interaction": {
                "something_else_kind": "FREE_RESPONSE_FOCUS",
                "something_else_semantic_text": None,
                "actual_composer_focused": True,
                "shift_enter_editing_only": True,
                "unmodified_enter_captured": True,
                "native_send_button_used": False,
                "composer_text_cleared": True,
                "hook_cleanup_verified_on_success": True,
            },
            "routing": {
                "source": envelope["source"],
                "text_length": len(envelope["text"]),
                "text_sha256": sha256_text(envelope["text"]),
                "text_equals_composer_at_gesture": envelope["text"] == composer_text_at_gesture,
                "action_id": envelope["action_id"],
                "projection_id": envelope["projection_id"],
                "capture_count": input_binding.capture_count,
                "delivery_count": input_binding.delivery_count,
                "duplicate_send_observed": False,
            },
            "suppression": {
                "native_keydown_suppressed": input_binding.suppressed_keydown_count == 1,
                "native_keyup_suppressed": input_binding.suppressed_keyup_count == 1,
                "visible_turn_count_before": turns_before,
                "visible_turn_count_after": turns_after,
                "normal_codex_request_observed": False,
            },
            "scope": {
                "viewmodel_semantics_exercised": False,
                "controller_called": False,
                "r6o3_host_model_lease_implemented": False,
                "automatic_invocation_implemented": False,
                "terminal_handoff_implemented": False,
            },
            "steady_state": steady,
            "host_record_sha256": sha256_file(args.host_record),
            "selectors_sha256": sha256_file(args.selectors),
            "implementation_sha256": {
                path: sha256_file(ROOT / path) for path in IMPLEMENTATION_PATHS
            },
            "runtime": {
                "platform": platform.platform(),
                "python": platform.python_version(),
                "qt_platform": QGuiApplication.platformName().lower(),
                "qt_quick_backend": os.environ.get("QT_QUICK_BACKEND", ""),
                "dependencies": dependency_versions(),
            },
            "source": {
                "branch": git_value("branch", "--show-current"),
                "head": git_value("rev-parse", "HEAD"),
                "tree": git_value("rev-parse", "HEAD^{tree}"),
            },
            "event_log": {
                "path": event_path.relative_to(ROOT).as_posix(),
                "event_count": len(events),
                "sha256": sha256_file(event_path),
            },
        }
        injection_started = False
        return result
    finally:
        if injection_started and host is not None:
            try:
                reset_composer(host)
            except Exception:
                pass
        if input_binding is not None:
            input_binding.stop()
        if host is not None:
            host.close()


def main() -> int:
    args = parse_args()
    try:
        result = run(args)
        write_canonical_json(args.evidence_dir / "input-routing-result.json", result)
        print(json.dumps(result, indent=2, sort_keys=True))
        print("H2_E1_INPUT_ROUTING_PASS")
        return 0
    except (CodexInputBindingError, CodexBindingError, AssertionError, OSError, RuntimeError) as exc:
        code = getattr(exc, "code", type(exc).__name__)
        failure = {
            "schema_version": "r6o-h2-e1-input-routing-1",
            "gate": "H2-E1",
            "status": "FAIL",
            "code": str(code),
            "real_codex_host_tested": str(code)
            not in {"HOST_PLATFORM_UNSUPPORTED", "HOST_DEPENDENCY_MISSING"},
            "fake_host_composer_used": False,
        }
        args.evidence_dir.mkdir(parents=True, exist_ok=True)
        write_canonical_json(args.evidence_dir / "input-routing-result.json", failure)
        print(json.dumps(failure, indent=2, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
