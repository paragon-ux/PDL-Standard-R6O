from __future__ import annotations

"""Run and record the actual Codex-attached H2-E2 G06 qualification."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from r6o.model_binding.base import ModelSessionRequest
from r6o.model_binding.local_runtime import LocalRuntimeModelBinding
from r6o.h2.codex_e2 import (
    AttachedCodexSidecarPresentation,
    CodexH2E2Session,
    H2E2IntegrationError,
)
from scripts.run_r6o2_tui import (
    G06_ACTIVATION,
    G06_OPERATIONS,
    ObservedWorker,
    load_g06_worker,
    resolve_baseline,
)


EXPECTED_BRANCH = "codex/h2-e2-g06-integration"
ACCEPTED_E1_HEAD = "8a85ac4214e7b3386c3c8079b0d45fb79a97e9ff"
DEFAULT_HOST_RECORD = ROOT / "r6o_evidence" / "H2-D1" / "host-environment.json"
DEFAULT_SELECTORS = ROOT / "r6o" / "host" / "codex" / "windows" / "selectors.json"
DEFAULT_EVIDENCE = ROOT / "r6o_evidence" / "H2-E2" / "actual-host"
EXPECTED_BY_TRANSITION = {
    "G06-T0-CODEX": [G06_OPERATIONS[0]],
    "G06-T1-CODEX": list(G06_OPERATIONS[1:3]),
    "G06-T2-CODEX": list(G06_OPERATIONS[3:5]),
}


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_json_bytes(value))


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(ROOT), *arguments],
        check=check,
        capture_output=True,
        text=True,
    )


def verify_checkout() -> dict[str, str]:
    branch = _git("branch", "--show-current").stdout.strip()
    if branch != EXPECTED_BRANCH:
        raise H2E2IntegrationError(f"WRONG_E2_BRANCH:{branch}")
    ancestor = _git(
        "merge-base", "--is-ancestor", ACCEPTED_E1_HEAD, "HEAD", check=False
    )
    if ancestor.returncode != 0:
        raise H2E2IntegrationError("ACCEPTED_E1_HEAD_NOT_ANCESTOR")
    status = _git("status", "--porcelain=v1").stdout.splitlines()
    unauthorized = []
    for line in status:
        path = line[3:].replace("\\", "/") if len(line) > 3 else line
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if not path.startswith("r6o_evidence/H2-E2/"):
            unauthorized.append(line)
    if unauthorized:
        raise H2E2IntegrationError(
            "UNCOMMITTED_NON_E2_EVIDENCE_CHANGES:" + "|".join(unauthorized)
        )
    return {
        "branch": branch,
        "head": _git("rev-parse", "HEAD").stdout.strip(),
        "tree": _git("rev-parse", "HEAD^{tree}").stdout.strip(),
    }


def _host_session_observation(binding: Any) -> dict[str, Any]:
    from r6o.host.codex.windows.uia import (
        composer_empty_observation,
        fresh_chat_observation,
    )

    controls = binding.refresh_controls()
    reset = binding.selectors["reset_contract"]
    composer = composer_empty_observation(controls.composer, reset["composer_empty"])
    fresh = fresh_chat_observation(controls.primary_content_region, reset["fresh_chat"])
    return {"composer": composer, "conversation": fresh}


def _require_safe_host_session(observation: dict[str, Any], *, phase: str) -> None:
    if observation["composer"].get("empty") is not True:
        raise H2E2IntegrationError(f"{phase}_COMPOSER_NOT_EMPTY")
    if observation["conversation"].get("fresh") is not True:
        raise H2E2IntegrationError(f"{phase}_CODEX_SESSION_NOT_FRESH")


class EvidenceRecorder:
    def __init__(self, evidence_dir: Path, worker: ObservedWorker, binding: Any) -> None:
        self.evidence_dir = evidence_dir
        self.worker = worker
        self.binding = binding
        self.call_cursor = 0
        self.transitions: list[dict[str, Any]] = []
        self.files: list[Path] = []

    def __call__(self, event: dict[str, Any]) -> None:
        transition_id = event["transition_id"]
        calls = self.worker.calls[self.call_cursor :]
        self.call_cursor = len(self.worker.calls)
        expected = [
            {"operation_id": operation_id, "operation": operation}
            for operation_id, operation in EXPECTED_BY_TRANSITION[transition_id]
        ]
        if calls != expected:
            raise H2E2IntegrationError(
                f"WORKER_OPERATION_SEQUENCE_MISMATCH:{transition_id}"
            )
        envelope = event["envelope"]
        if transition_id == "G06-T0-CODEX":
            if envelope is not None:
                raise H2E2IntegrationError("START_EMITTED_INPUT_ENVELOPE")
        elif (
            not isinstance(envelope, dict)
            or envelope.get("source") != "STRUCTURED_ACTION"
            or envelope.get("text") is not None
            or envelope.get("action_id")
            not in {"confirm_prompt", "confirm_plan"}
        ):
            raise H2E2IntegrationError(
                f"INVALID_STRUCTURED_ACTION_EVIDENCE:{transition_id}"
            )

        projection = event["projection"]
        projection_path = (
            self.evidence_dir / "projections" / f"{transition_id}.json"
        )
        _write_json(projection_path, projection)
        self.files.append(projection_path)
        capture_path: Path | None = None
        if projection["stage"] != "CLOSED_SUCCESS":
            capture_path = self.evidence_dir / "captures" / f"{transition_id}.png"
            self.binding.sidecar.capture(capture_path)
            self.files.append(capture_path)

        artifact = projection.get("artifact")
        record = {
            "schema_version": "r6o-h2-e2-transition-1",
            "transition_id": transition_id,
            "state_id": event["state_id"],
            "stage": projection["stage"],
            "projection_id": projection["projection_id"],
            "projection_path": str(projection_path.relative_to(ROOT)).replace("\\", "/"),
            "projection_sha256": _sha256_file(projection_path),
            "input_envelope": envelope,
            "worker_operations": calls,
            "artifact_kind": artifact.get("artifact_kind") if artifact else None,
            "artifact_ref": artifact.get("artifact_ref") if artifact else None,
            "artifact_body_sha256": (
                hashlib.sha256(artifact["body"].encode("utf-8")).hexdigest()
                if artifact and isinstance(artifact.get("body"), str)
                else None
            ),
            "presentation": event["presentation"],
            "capture_path": (
                str(capture_path.relative_to(ROOT)).replace("\\", "/")
                if capture_path
                else None
            ),
        }
        self.transitions.append(record)

    def write(self) -> list[dict[str, Any]]:
        path = self.evidence_dir / "transitions.json"
        _write_json(path, self.transitions)
        self.files.append(path)
        return self.transitions


def _host_identity(binding: Any) -> dict[str, Any]:
    source = binding.host_record["codex"]
    keys = (
        "hwnd",
        "pid",
        "product_name",
        "product_version",
        "file_version",
        "package_version",
        "window_class",
    )
    return {key: source[key] for key in keys}


def _read_attempts(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise H2E2IntegrationError("E2_ATTEMPT_LEDGER_INVALID")
    return value


def _start_attempt(evidence_dir: Path, checkout: dict[str, str]) -> tuple[Path, list[dict[str, Any]], int]:
    path = evidence_dir / "live-attempts.json"
    attempts = _read_attempts(path)
    count = len(attempts) + 1
    attempts.append(
        {
            "attempt": count,
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": "RUNNING",
            "head": checkout["head"],
            "tree": checkout["tree"],
            "failure": None,
        }
    )
    _write_json(path, attempts)
    return path, attempts, count


def _finish_attempt(
    path: Path,
    attempts: list[dict[str, Any]],
    *,
    status: str,
    failure: str | None = None,
) -> None:
    attempts[-1]["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    attempts[-1]["status"] = status
    attempts[-1]["failure"] = failure
    _write_json(path, attempts)


def run(args: argparse.Namespace, checkout: dict[str, str], live_run_count: int) -> dict[str, Any]:
    if os.name != "nt":
        raise H2E2IntegrationError("ACTUAL_CODEX_HOST_REQUIRES_WINDOWS")
    os.environ.setdefault("QT_QUICK_BACKEND", "software")
    os.environ.setdefault("QT_SCALE_FACTOR", "1")
    os.environ.setdefault("QT_FONT_DPI", "96")
    try:
        from PySide6.QtCore import QCoreApplication, QEventLoop
        from r6o.host.codex.windows.binding import CodexSidecarBinding
        from r6o.views.sidecar.qt_app import QtSidecarWindow
    except ImportError as exc:
        raise H2E2IntegrationError("HOST_DEPENDENCY_MISSING") from exc

    baseline = resolve_baseline(args.baseline_repo)
    temporary: tempfile.TemporaryDirectory[str] | None = None
    model: LocalRuntimeModelBinding | None = None
    host: Any | None = None
    callback_errors: list[Exception] = []
    holder: dict[str, CodexH2E2Session] = {}
    try:
        workspace_root = args.workspace_root
        if workspace_root is None:
            temporary = tempfile.TemporaryDirectory(prefix="pdl-r6o-h2-e2-")
            workspace_root = Path(temporary.name) / "workspaces"

        delegate = load_g06_worker(baseline)
        worker = ObservedWorker(delegate, G06_OPERATIONS, "G06")
        model = LocalRuntimeModelBinding(
            baseline,
            worker=worker,
            workspace_root=workspace_root,
            run_id="h2-e2-g06",
        )

        def on_action(action_id: str) -> None:
            try:
                holder["session"].activate_action(action_id)
            except Exception as exc:
                callback_errors.append(exc)

        def sidecar_factory(**options: Any) -> Any:
            return QtSidecarWindow(on_action=on_action, **options)

        host = CodexSidecarBinding(
            args.host_record,
            args.selectors,
            sidecar_factory=sidecar_factory,
        )
        preflight = _host_session_observation(host)
        _require_safe_host_session(preflight, phase="INITIAL")

        recorder = EvidenceRecorder(args.evidence_dir, worker, host)
        session = CodexH2E2Session(
            model,
            AttachedCodexSidecarPresentation(host),
            ModelSessionRequest(request_id="h2-e2-g06", task_text=G06_ACTIVATION),
            on_transition=recorder,
        )
        holder["session"] = session
        session.start()

        deadline = time.monotonic() + args.timeout
        app = QCoreApplication.instance()
        while not session.terminal and not callback_errors:
            if time.monotonic() >= deadline:
                raise H2E2IntegrationError("HUMAN_ACTION_TIMEOUT")
            if app is None:
                raise H2E2IntegrationError("QT_APPLICATION_UNAVAILABLE")
            app.processEvents(QEventLoop.AllEvents, 50)
            time.sleep(0.01)
        if callback_errors:
            raise callback_errors[0]

        postflight = _host_session_observation(host)
        _require_safe_host_session(postflight, phase="TERMINAL")
        expected_calls = [
            {"operation_id": operation_id, "operation": operation}
            for operation_id, operation in G06_OPERATIONS
        ]
        if worker.calls != expected_calls:
            raise H2E2IntegrationError("G06_OPERATIONS_NOT_CONSUMED_EXACTLY_ONCE")
        if [item["action_id"] for item in session.envelopes] != [
            "confirm_prompt",
            "confirm_plan",
        ]:
            raise H2E2IntegrationError("STRUCTURED_ACTION_SEQUENCE_INVALID")

        transitions = recorder.write()
        no_native_submission = (
            preflight["conversation"]["visible_turn_group_count"] == 0
            and postflight["conversation"]["visible_turn_group_count"] == 0
            and preflight["composer"]["empty"] is True
            and postflight["composer"]["empty"] is True
        )
        if not no_native_submission:
            raise H2E2IntegrationError("NATIVE_CODEX_SUBMISSION_NOT_DISPROVEN")
        return {
            "schema_version": "r6o-h2-e2-qualification-1",
            "status": "H2_E2_G06_PASS",
            "public_command": "python scripts\\h2\\run_codex_h2_e2.py --case G06 --record",
            "case_id": "G06",
            "branch": checkout["branch"],
            "code_freeze_head": checkout["head"],
            "code_freeze_tree": checkout["tree"],
            "accepted_e1_head": ACCEPTED_E1_HEAD,
            "live_run_count": live_run_count,
            "actual_codex_host": _host_identity(host),
            "frozen_r6s": {
                "commit": "60d982f3328b45a351879d67dc4bb525172b65fd",
                "tree": "b7689fbe8b9c9838438cbba6f6e0e5c1ce5b5ed6",
                "fixture": "G06",
            },
            "host_preflight": preflight,
            "host_postflight": postflight,
            "transitions": transitions,
            "structured_action_envelopes": session.envelopes,
            "worker_operations": worker.calls,
            "native_codex_submission_observed": False,
            "sidecar_dismissed": True,
            "actual_composer_focus_restored": True,
        }
    finally:
        if host is not None:
            host.close()
        if model is not None:
            model.close()
        if temporary is not None:
            temporary.cleanup()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=("G06",), required=True)
    parser.add_argument("--record", action="store_true")
    parser.add_argument("--baseline-repo", type=Path)
    parser.add_argument("--host-record", type=Path, default=DEFAULT_HOST_RECORD)
    parser.add_argument("--selectors", type=Path, default=DEFAULT_SELECTORS)
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--timeout", type=float, default=300.0)
    args = parser.parse_args()
    args.evidence_dir = args.evidence_dir.resolve()
    args.host_record = args.host_record.resolve()
    args.selectors = args.selectors.resolve()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    return args


def main() -> int:
    args = parse_args()
    if not args.record:
        print("H2 E2 FAIL: qualification requires --record", file=sys.stderr)
        return 2
    try:
        args.evidence_dir.relative_to(ROOT / "r6o_evidence" / "H2-E2")
    except ValueError:
        print("H2 E2 FAIL: evidence must remain under r6o_evidence/H2-E2", file=sys.stderr)
        return 2

    attempt_path: Path | None = None
    attempts: list[dict[str, Any]] | None = None
    try:
        checkout = verify_checkout()
        attempt_path, attempts, count = _start_attempt(args.evidence_dir, checkout)
        report = run(args, checkout, count)
        qualification_path = args.evidence_dir / "qualification.json"
        _write_json(qualification_path, report)
        _finish_attempt(attempt_path, attempts, status="H2_E2_G06_PASS")
        print("H2_E2_G06_PASS", flush=True)
        return 0
    except KeyboardInterrupt:
        failure = "INTERRUPTED"
        if attempt_path is not None and attempts is not None:
            _finish_attempt(attempt_path, attempts, status="FAIL", failure=failure)
        print("H2 E2 INTERRUPTED", file=sys.stderr, flush=True)
        return 130
    except Exception as exc:
        failure = getattr(exc, "code", str(exc))
        if attempt_path is not None and attempts is not None:
            _finish_attempt(attempt_path, attempts, status="FAIL", failure=failure)
        print(f"H2 E2 FAIL: {failure}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
