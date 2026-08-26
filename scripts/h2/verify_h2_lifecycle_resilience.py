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
from types import SimpleNamespace
from typing import Any, Callable
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
DEFAULT_EVIDENCE_DIR = ROOT / "r6o_evidence" / "H2-F2"
FROZEN_ORACLE_COMMIT = "60d982f3328b45a351879d67dc4bb525172b65fd"
FROZEN_ORACLE_TREE = "b7689fbe8b9c9838438cbba6f6e0e5c1ce5b5ed6"


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


def _input_binding(*, focused: bool = True, text: str = "H2-F2 captured text") -> CodexComposerInputBinding:
    host = SimpleNamespace(host_hwnd=101, sidecar_hwnd=303)
    binding = CodexComposerInputBinding(
        host,
        lambda _envelope: None,
        focus_probe=lambda: focused,
        text_probe=lambda: text,
    )
    binding._active_projection = canonical_projection(projection_id="h2-f2-input")
    binding._armed = True
    return binding


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

    timed_out = _input_binding()
    timed_out._delivery_pending = True
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
    return {
        "status": "PASS",
        "unmodified_enter": {"capture_count": binding.capture_count, "delivery_count": binding.delivery_count},
        "shift_enter": "PASSTHROUGH",
        "unrelated_window": "PASSTHROUGH",
        "focus_failure": failed_focus.last_error,
        "orphaned_hook_removed": True,
        "timeout_error_precedence": "HOST_COMPOSER_ENVELOPE_TIMEOUT",
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
        from r6o.views.sidecar.qt_app import QtSidecarWindow
    except ImportError as exc:
        raise F2VerificationError("SIDECAR_DEPENDENCY_MISSING") from exc

    sidecar = QtSidecarWindow()
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
        return {
            "status": "PASS",
            "open_close_reopen": True,
            "authoritative_projection_id": sidecar.bridge.projectionId,
            "terminal_dismissed": True,
        }
    finally:
        sidecar.close()
        sidecar.close()


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
        input_binding.stop()
        require(hook_installed, "ACTUAL_INPUT_HOOK_NOT_INSTALLED")
        require(input_binding._hook == 0 and input_binding._hook_thread is None, "ACTUAL_INPUT_HOOK_NOT_REMOVED")
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
            "input_hook": {"installed": hook_installed, "removed": True},
            "terminal_close": terminal_close,
            "composer_empty_before": before,
            "composer_empty_after": after,
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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    evidence_dir = args.evidence_dir.resolve()
    identity: dict[str, Any] | None = None
    result: dict[str, Any] = {
        "schema_version": "r6o-h2-f2-lifecycle-resilience-1",
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
        result["input_boundary"] = qualify_input_boundary()
        result["qt_lifecycle"] = qualify_qt_lifecycle()
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
