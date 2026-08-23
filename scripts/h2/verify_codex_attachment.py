from __future__ import annotations

"""Qualify H2-D2 against the exact frozen Codex desktop HWND."""

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from r6o.host.codex.windows.binding import CodexBindingError, CodexSidecarBinding
from r6o.host.codex.windows.placement import Rect
from r6o.host.codex.windows.uia import composer_empty_observation, write_canonical_json
from r6o.views.sidecar.fixture import CANONICAL_ACTIONS, CANONICAL_ARTIFACT_BODY
from r6o.views.sidecar.model import SidecarMode


DEFAULT_HOST_RECORD = ROOT / "r6o_evidence" / "H2-D1" / "host-environment.json"
DEFAULT_SELECTORS = ROOT / "r6o" / "host" / "codex" / "windows" / "selectors.json"
DEFAULT_EVIDENCE_DIR = ROOT / "r6o_evidence" / "H2-D2"
MARKER = "H2D2NONINTERFERENCE"
IMPLEMENTATION_PATHS = (
    "r6o/host/codex/windows/binding.py",
    "r6o/host/codex/windows/placement.py",
    "scripts/h2/verify_codex_attachment.py",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def implementation_hashes() -> dict[str, str]:
    return {path: sha256_file(ROOT / path) for path in IMPLEMENTATION_PATHS}


def runtime_record() -> dict[str, Any]:
    try:
        from PySide6.QtCore import qVersion
        from PySide6.QtGui import QGuiApplication
    except ImportError as exc:
        raise CodexBindingError("SIDECAR_DEPENDENCY_MISSING") from exc
    app = QGuiApplication.instance()
    if app is None:
        raise CodexBindingError("SIDECAR_QT_APPLICATION_MISSING")
    dependencies = {
        distribution: importlib.metadata.version(distribution)
        for distribution in (
            "PySide6",
            "pywinauto",
            "pywin32",
            "Pillow",
            "imageio-ffmpeg",
        )
    }
    return {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "qt_version": qVersion(),
        "qt_platform": app.platformName(),
        "qt_quick_backend": os.environ.get("QT_QUICK_BACKEND", ""),
        "dependencies": dependencies,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify real Codex Sidecar ownership, placement, z-order, focus, and non-interference."
    )
    parser.add_argument("--host-record", type=Path, default=DEFAULT_HOST_RECORD)
    parser.add_argument("--selectors", type=Path, default=DEFAULT_SELECTORS)
    parser.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE_DIR)
    parser.add_argument("--settle-seconds", type=float, default=0.75)
    parser.add_argument("--recording-fps", type=int, default=8)
    return parser.parse_args()


def canonical_projection() -> dict[str, object]:
    action_kinds = {
        "confirm_prompt": "SEMANTIC_MESSAGE",
        "change_task": "SEMANTIC_MESSAGE",
        "change_approach": "SEMANTIC_MESSAGE",
        "something_else": "FREE_RESPONSE_FOCUS",
    }
    return {
        "schema_version": "r6o-focus-projection-1",
        "projection_id": "h2-d2-real-codex-attachment",
        "stage": "PROMPT_REVIEW",
        "lifecycle": {"terminal": False},
        "artifact": {
            "artifact_ref": "h2-d2:qualification-artifact",
            "title": "Authoritative Prompt (PDL.md)",
            "body": CANONICAL_ARTIFACT_BODY,
            "capabilities": {"copy": True, "open_external": False},
        },
        "actions": [
            {**dict(action), "kind": action_kinds[str(action["action_id"])]}
            for action in CANONICAL_ACTIONS
        ],
    }


@dataclass
class ScreenRecording:
    path: Path
    rectangle: Rect
    fps: int

    def __post_init__(self) -> None:
        if self.fps <= 0:
            raise CodexBindingError("RECORDING_FPS_INVALID")
        self.frame_count = 0
        self._error: Exception | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            raise CodexBindingError("RECORDING_ALREADY_STARTED")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._thread = threading.Thread(target=self._capture, name="h2-d2-screen-recorder", daemon=True)
        self._thread.start()
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and self.frame_count == 0 and self._error is None:
            time.sleep(0.025)
        if self._error is not None:
            raise CodexBindingError("SCREEN_RECORDING_START_FAILED") from self._error
        if self.frame_count == 0:
            raise CodexBindingError("SCREEN_RECORDING_START_TIMEOUT")

    def _capture(self) -> None:
        writer = None
        try:
            from PIL import ImageGrab
            import imageio_ffmpeg

            writer = imageio_ffmpeg.write_frames(
                str(self.path),
                (self.rectangle.width, self.rectangle.height),
                fps=self.fps,
                codec="libx264",
                pix_fmt_in="rgb24",
                pix_fmt_out="yuv420p",
                output_params=["-crf", "18", "-movflags", "+faststart"],
                ffmpeg_log_level="warning",
                macro_block_size=2,
            )
            writer.send(None)
            interval = 1.0 / self.fps
            next_frame = time.monotonic()
            while not self._stop.is_set():
                image = ImageGrab.grab(bbox=self.rectangle.as_tuple(), all_screens=True).convert("RGB")
                writer.send(image.tobytes())
                self.frame_count += 1
                next_frame += interval
                self._stop.wait(max(0.0, next_frame - time.monotonic()))
        except Exception as exc:
            self._error = exc
        finally:
            if writer is not None:
                try:
                    writer.close()
                except Exception as exc:
                    if self._error is None:
                        self._error = exc

    def stop(self) -> dict[str, Any]:
        if self._thread is None:
            raise CodexBindingError("RECORDING_NOT_STARTED")
        self._stop.set()
        self._thread.join(timeout=15.0)
        if self._thread.is_alive():
            raise CodexBindingError("SCREEN_RECORDING_STOP_TIMEOUT")
        if self._error is not None:
            raise CodexBindingError("SCREEN_RECORDING_FAILED") from self._error
        if self.frame_count <= 0 or not self.path.is_file() or self.path.stat().st_size <= 0:
            raise CodexBindingError("SCREEN_RECORDING_EMPTY")
        return {
            "path": self.path.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(self.path),
            "frame_count": self.frame_count,
            "fps": self.fps,
            "crop_rectangle": self.rectangle.as_record(),
            "observer_ordering_mutation": False,
        }


class EventLedger:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def add(self, event: str, **fields: Any) -> None:
        self.records.append(
            {
                "sequence": len(self.records) + 1,
                "timestamp_utc": utc_now(),
                "event": event,
                **fields,
            }
        )

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(json.dumps(record, sort_keys=True) + "\n" for record in self.records),
            encoding="utf-8",
            newline="\n",
        )


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
        time.sleep(0.05)
    raise CodexBindingError(code)


def safe_current_value(composer: Any) -> str:
    try:
        return str(composer.iface_value.CurrentValue)
    except Exception as exc:
        raise CodexBindingError("COMPOSER_VALUE_UNAVAILABLE") from exc


def clear_injected_composer_text(
    binding: CodexSidecarBinding,
    empty_contract: dict[str, Any],
    send_keys: Any,
) -> None:
    """Clear even a partial marker after an injection failure or timeout."""

    current = binding.refresh_controls().composer
    current.set_focus()
    wait_until(
        lambda: bool(binding.refresh_controls().composer.has_keyboard_focus())
        and binding.native.foreground() == binding.host_hwnd,
        timeout=5.0,
        code="NON_INTERFERENCE_CLEANUP_FOCUS_UNVERIFIED",
    )
    send_keys("^a{BACKSPACE}", pause=0.025)
    wait_until(
        lambda: composer_empty_observation(
            binding.refresh_controls().composer, empty_contract
        ).get("empty")
        is True,
        timeout=5.0,
        code="NON_INTERFERENCE_MARKER_CLEANUP_FAILED",
    )


def visible_turn_group_count(region: Any, class_name: str) -> int:
    try:
        return sum(
            1
            for wrapper in region.descendants(control_type="Group")
            if wrapper.is_visible() and str(wrapper.element_info.class_name or "") == class_name
        )
    except Exception as exc:
        raise CodexBindingError("CONVERSATION_TURN_OBSERVATION_FAILED") from exc


def run_unrelated_window_probe(binding: CodexSidecarBinding, sidecar_rectangle: Rect) -> dict[str, Any]:
    """Prove an unowned ordinary window can cover the non-topmost Sidecar."""

    try:
        from PySide6.QtCore import QCoreApplication, QEventLoop
        from PySide6.QtGui import QWindow
    except ImportError as exc:
        raise CodexBindingError("SIDECAR_DEPENDENCY_MISSING") from exc
    probe = QWindow()
    probe.setTitle("H2-D2 unrelated-window probe")
    probe.resize(240, 96)
    probe.setPosition(
        sidecar_rectangle.left + (sidecar_rectangle.width - 240) // 2,
        sidecar_rectangle.top + (sidecar_rectangle.height - 96) // 2,
    )
    probe.show()
    app = QCoreApplication.instance()
    probe_hwnd = int(probe.winId())
    if app is not None:
        app.processEvents(QEventLoop.AllEvents, 100)
    try:
        import win32api
        import win32con
    except ImportError as exc:
        probe.hide()
        raise CodexBindingError("HOST_DEPENDENCY_MISSING") from exc
    router_count_before = binding.focus_router.transfer_count
    probe_rectangle = binding.native.rectangle(probe_hwnd)
    probe_point = (
        probe_rectangle.left + probe_rectangle.width // 2,
        probe_rectangle.top + probe_rectangle.height // 2,
    )
    win32api.SetCursorPos(probe_point)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0)
    time.sleep(0.05)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0)
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if app is not None:
            app.processEvents(QEventLoop.AllEvents, 25)
        if binding.native.foreground() == probe_hwnd:
            break
        time.sleep(0.025)
    z_order = binding.native.z_order()
    try:
        probe_index = z_order.index(probe_hwnd)
        sidecar_index = z_order.index(binding.sidecar_hwnd)
    except ValueError as exc:
        probe.hide()
        raise CodexBindingError("UNRELATED_WINDOW_Z_ORDER_UNOBSERVABLE") from exc
    record = {
        "probe_hwnd": probe_hwnd,
        "probe_owner_hwnd": binding.native.owner(probe_hwnd),
        "probe_global_topmost": binding.native.is_topmost(probe_hwnd),
        "probe_foreground": binding.native.foreground() == probe_hwnd,
        "probe_above_sidecar": probe_index < sidecar_index,
        "host_focus_router_ignored_probe_click": binding.focus_router.transfer_count
        == router_count_before,
    }
    probe.hide()
    if app is not None:
        app.processEvents(QEventLoop.AllEvents, 100)
    probe.destroy()
    if (
        record["probe_owner_hwnd"] != 0
        or record["probe_global_topmost"]
        or not record["probe_foreground"]
        or not record["probe_above_sidecar"]
        or not record["host_focus_router_ignored_probe_click"]
    ):
        raise CodexBindingError("SIDECAR_COVERS_UNRELATED_WINDOW")
    return record


def run_non_interference(binding: CodexSidecarBinding, ledger: EventLedger) -> dict[str, Any]:
    composer = binding.refresh_controls().composer
    empty_contract = binding.selectors["reset_contract"]["composer_empty"]
    before_empty = composer_empty_observation(composer, empty_contract)
    if before_empty.get("empty") is not True:
        raise CodexBindingError("COMPOSER_NOT_EMPTY")
    turn_class = binding.selectors["reset_contract"]["fresh_chat"]["visible_turn_group_class"]
    turns_before = visible_turn_group_count(binding.controls.primary_content_region, turn_class)
    rectangle_before = binding.native.rectangle(binding.sidecar_hwnd)

    try:
        import win32api
        import win32con
    except ImportError as exc:
        raise CodexBindingError("HOST_DEPENDENCY_MISSING") from exc
    composer_rectangle = binding.controls.composer_rectangle
    click_point = (
        composer_rectangle.left + composer_rectangle.width // 2,
        composer_rectangle.top + composer_rectangle.height // 2,
    )
    # Use the actual Windows mouse boundary. Wrapper.click_input() performs
    # toolkit synchronization that can wait for Chromium's whole process; the
    # physical click itself must remain immediate and independently observed.
    win32api.SetCursorPos(click_point)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0)
    time.sleep(0.05)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0)
    wait_until(
        lambda: binding.native.foreground() == binding.host_hwnd,
        timeout=5.0,
        code="CODEX_CLICK_FOREGROUND_UNVERIFIED",
    )
    wait_until(
        lambda: binding.focus_router.transfer_count >= 1
        and binding.focus_router.last_transfer_succeeded
        and binding.focus_router.last_thread_input_attached
        and binding.focus_router.last_thread_input_detached
        and binding.native.owner(binding.sidecar_hwnd) == binding.host_hwnd,
        timeout=5.0,
        code="HOST_CLICK_FOCUS_ROUTING_UNVERIFIED",
    )
    composer = binding.refresh_controls().composer
    wait_until(
        lambda: bool(binding.refresh_controls().composer.has_keyboard_focus()),
        timeout=5.0,
        code="COMPOSER_CLICK_FOCUS_UNVERIFIED",
    )
    ledger.add(
        "actual_codex_composer_clicked",
        foreground_hwnd=binding.native.foreground(),
        composer_keyboard_focus=True,
        point_outside_sidecar=True,
        focus_router_transfer_count=binding.focus_router.transfer_count,
        exact_owner_preserved=binding.native.owner(binding.sidecar_hwnd) == binding.host_hwnd,
        thread_input_attached=binding.focus_router.last_thread_input_attached,
        thread_input_detached=binding.focus_router.last_thread_input_detached,
        thread_input_attached_only_for_focus_transaction=(
            binding.focus_router.last_thread_input_attached
            and binding.focus_router.last_thread_input_detached
        ),
    )

    try:
        from pywinauto.keyboard import send_keys
    except ImportError as exc:
        raise CodexBindingError("HOST_DEPENDENCY_MISSING") from exc
    marker_may_be_present = False
    try:
        # Set this before injection: send_keys can fail after typing only a
        # prefix, and the real composer must still be restored to its verified
        # empty precondition.
        marker_may_be_present = True
        send_keys(MARKER, pause=0.025, with_spaces=False)
        wait_until(
            lambda: MARKER in safe_current_value(binding.refresh_controls().composer),
            timeout=5.0,
            code="NON_INTERFERENCE_MARKER_NOT_VISIBLE",
        )
        composer = binding.refresh_controls().composer
        marker_value = safe_current_value(composer)
        ledger.add(
            "non_submitting_marker_visible",
            marker_length=len(MARKER),
            marker_sha256=hashlib.sha256(MARKER.encode("utf-8")).hexdigest(),
            observed_value_length=len(marker_value),
            submit_gesture_used=False,
        )
        send_keys("^a{BACKSPACE}", pause=0.025)
        wait_until(
            lambda: composer_empty_observation(
                binding.refresh_controls().composer, empty_contract
            ).get("empty")
            is True,
            timeout=5.0,
            code="NON_INTERFERENCE_MARKER_RESET_FAILED",
        )
        marker_may_be_present = False
    except Exception:
        if marker_may_be_present:
            try:
                clear_injected_composer_text(binding, empty_contract, send_keys)
                ledger.add("failure_cleanup_marker_removed", marker_removed=True)
            except Exception as cleanup_error:
                raise CodexBindingError("NON_INTERFERENCE_MARKER_CLEANUP_FAILED") from cleanup_error
        raise
    refreshed = binding.refresh_controls()
    turns_after = visible_turn_group_count(refreshed.primary_content_region, turn_class)
    rectangle_after = binding.native.rectangle(binding.sidecar_hwnd)
    placement_unchanged = rectangle_after == rectangle_before
    if turns_after != turns_before:
        raise CodexBindingError("NORMAL_CODEX_DISPATCH_NOT_SUPPRESSED")
    if not placement_unchanged:
        raise CodexBindingError("SIDECAR_MOVED_DURING_HOST_INTERACTION")
    steady_state = binding.observe(expected=rectangle_before)
    ledger.add(
        "non_interference_complete",
        marker_removed=True,
        visible_turn_count_before=turns_before,
        visible_turn_count_after=turns_after,
        placement_unchanged=placement_unchanged,
        sidecar_above_host=steady_state["sidecar_above_host"],
        observation_ordering_mutation=False,
    )
    return {
        "composer_empty_before": True,
        "composer_clicked_outside_sidecar": True,
        "composer_received_keyboard_focus": True,
        "marker_visible": True,
        "marker_removed": True,
        "marker_submitted": False,
        "normal_codex_dispatch_observed": False,
        "visible_turn_count_before": turns_before,
        "visible_turn_count_after": turns_after,
        "placement_unchanged": placement_unchanged,
        "sidecar_visible_after": steady_state["visible"],
        "sidecar_above_host_after": steady_state["sidecar_above_host"],
    }


def write_failure(
    evidence_dir: Path,
    ledger: EventLedger,
    *,
    code: str,
    host_record: Path,
    selectors: Path,
    real_codex_host_tested: bool,
) -> None:
    ledger.add("qualification_failed", code=code)
    ledger.write(evidence_dir / "win32-uia-events.jsonl")
    write_canonical_json(
        evidence_dir / "attachment-result.json",
        {
            "schema_version": "r6o-h2-d2-attachment-result-1",
            "status": "FAIL",
            "code": code,
            "timestamp_utc": utc_now(),
            "host_record": host_record.resolve().as_posix(),
            "selectors": selectors.resolve().as_posix(),
            "real_codex_host_tested": real_codex_host_tested,
            "synthetic_owner_used": False,
        },
    )


def main() -> int:
    args = parse_args()
    evidence_dir = args.evidence_dir.resolve()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    ledger = EventLedger()
    binding: CodexSidecarBinding | None = None
    active_recorders: list[ScreenRecording] = []
    try:
        binding = CodexSidecarBinding(args.host_record, args.selectors)
        host = binding.host_record["codex"]
        ledger.add(
            "frozen_actual_codex_resolved",
            hwnd=binding.host_hwnd,
            pid=host["pid"],
            product_version=host["product_version"],
            package_version=host["package_version"],
            geometry_source="LIVE_REMEASURED_EXACT_D1_HWND",
            live_client_rectangle=binding.host_client_rectangle.as_record(),
            live_work_area=binding.work_area_rectangle.as_record(),
            live_dpi=binding.dpi,
            composer_selector_match_count=binding.controls.composer_selector_match_count,
            geometry_tie_breaker="LOWER_HALF_BOTTOM_ANCHORED_MINIMUM_35_PERCENT_PRIMARY_WIDTH",
        )

        standard = binding.attach(canonical_projection(), settle_seconds=args.settle_seconds)
        ledger.add("standard_steady_state_observed", **standard, observation_ordering_mutation=False)
        standard_rectangle = Rect(
            standard["actual_rectangle"]["left"],
            standard["actual_rectangle"]["top"],
            standard["actual_rectangle"]["right"],
            standard["actual_rectangle"]["bottom"],
        )
        # The actual composer is wider than the locked 675px Sidecar. Capture
        # only the Sidecar-width portion of that composer so the required
        # marker remains visible without exposing conversation content beside
        # the Sidecar. One blank boundary pixel makes the H.264 crop even.
        standard_crop = Rect(
            max(binding.work_area_rectangle.left, standard_rectangle.left - 1),
            standard_rectangle.top,
            standard_rectangle.right,
            binding.controls.composer_rectangle.bottom,
        )
        standard_recorder = ScreenRecording(
            evidence_dir / "attachment-standard.mp4", standard_crop, args.recording_fps
        )
        active_recorders.append(standard_recorder)
        standard_recorder.start()
        unrelated = run_unrelated_window_probe(binding, standard_rectangle)
        ledger.add("unrelated_window_coverage_proved", **unrelated)
        non_interference = run_non_interference(binding, ledger)
        standard_recording = standard_recorder.stop()
        active_recorders.remove(standard_recorder)
        ledger.add("standard_recording_closed", **standard_recording)

        expanded = binding.set_mode(SidecarMode.EXPANDED, settle_seconds=args.settle_seconds)
        ledger.add("expanded_steady_state_observed", **expanded, observation_ordering_mutation=False)
        expanded_rectangle = Rect(
            expanded["actual_rectangle"]["left"],
            expanded["actual_rectangle"]["top"],
            expanded["actual_rectangle"]["right"],
            expanded["actual_rectangle"]["bottom"],
        )
        expanded_recorder = ScreenRecording(
            evidence_dir / "attachment-expanded.mp4",
            expanded_rectangle,
            args.recording_fps,
        )
        active_recorders.append(expanded_recorder)
        expanded_recorder.start()
        time.sleep(max(1.0, args.settle_seconds))
        expanded_after_recording = binding.observe(expected=expanded_rectangle)
        expanded_recording = expanded_recorder.stop()
        active_recorders.remove(expanded_recorder)
        ledger.add(
            "expanded_recording_closed",
            steady_state_after_recording=expanded_after_recording,
            **expanded_recording,
        )

        binding.set_mode(SidecarMode.STANDARD, settle_seconds=args.settle_seconds)
        close_focus = binding.close_view_and_verify_focus()
        if close_focus["sidecar_visible"]:
            raise CodexBindingError("SIDECAR_CLOSE_UNVERIFIED")
        ledger.add("close_returned_focus_to_actual_composer", **close_focus)
        ledger.write(evidence_dir / "win32-uia-events.jsonl")

        result = {
            "schema_version": "r6o-h2-d2-attachment-result-1",
            "status": "H2_D2_ATTACHMENT_PASS",
            "timestamp_utc": utc_now(),
            "gate": "H2-D2",
            "real_codex_host_tested": True,
            "synthetic_owner_used": False,
            "observer_ordering_mutation": False,
            "host": {
                "hwnd": binding.host_hwnd,
                "pid": host["pid"],
                "product_name": host["product_name"],
                "product_version": host["product_version"],
                "file_version": host["file_version"],
                "package_version": host["package_version"],
                "dpi": binding.dpi,
                "geometry_source": "LIVE_REMEASURED_EXACT_D1_HWND",
                "client_rectangle": binding.host_client_rectangle.as_record(),
                "work_area": binding.work_area_rectangle.as_record(),
            },
            "host_record_sha256": sha256_file(args.host_record),
            "selectors_sha256": sha256_file(args.selectors),
            "implementation_sha256": implementation_hashes(),
            "runtime": runtime_record(),
            "composer_resolution": {
                "selector_match_count": binding.controls.composer_selector_match_count,
                "qualifying_geometry_match_count": 1,
                "actual_composer_rectangle": binding.controls.composer_rectangle.as_record(),
            },
            "standard": standard,
            "expanded": expanded,
            "unrelated_window": unrelated,
            "non_interference": non_interference,
            "close_focus_return": close_focus,
            "recording": {
                "mandatory": True,
                "standard": standard_recording,
                "expanded": expanded_recording,
                "frame_count": standard_recording["frame_count"] + expanded_recording["frame_count"],
                "sha256": hashlib.sha256(
                    (standard_recording["sha256"] + expanded_recording["sha256"]).encode("ascii")
                ).hexdigest(),
            },
            "event_log": {
                "path": "r6o_evidence/H2-D2/win32-uia-events.jsonl",
                "sha256": sha256_file(evidence_dir / "win32-uia-events.jsonl"),
                "event_count": len(ledger.records),
            },
            "scope": {
                "semantic_workflow_exercised": False,
                "normal_codex_submit_gesture_used": False,
                "r6o3_lease_implemented": False,
            },
        }
        write_canonical_json(evidence_dir / "attachment-result.json", result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        for recorder in list(active_recorders):
            try:
                recorder.stop()
            except Exception:
                pass
        code = exc.code if isinstance(exc, CodexBindingError) else "H2_D2_RUNTIME_ERROR"
        write_failure(
            evidence_dir,
            ledger,
            code=code,
            host_record=args.host_record,
            selectors=args.selectors,
            real_codex_host_tested=binding is not None,
        )
        print(json.dumps({"status": "FAIL", "code": code}, sort_keys=True), file=sys.stderr)
        return 1
    finally:
        if binding is not None:
            try:
                binding.close()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
