from __future__ import annotations

"""Run and record the human-operated actual Codex A02-FULL H2-E3 qualification."""

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

from r6o.h2.codex_e3 import (  # noqa: E402
    AttachedCodexE3Presentation,
    CodexH2E3Session,
    H2E3IntegrationError,
)
from r6o.model_binding.base import ModelSessionRequest  # noqa: E402
from r6o.model_binding.local_runtime import LocalRuntimeModelBinding  # noqa: E402
from scripts.h2.verify_a02_full_fixture import (  # noqa: E402
    ACTIVATION_TEXT,
    FROZEN_ORACLE_COMMIT,
    FROZEN_ORACLE_TREE,
    REVISION_TEXT,
    validate_fixture_documents,
)
from scripts.run_r6o2_tui import (  # noqa: E402
    A02_OPERATIONS,
    A02ReplayWorker,
    ObservedWorker,
    resolve_baseline,
)


EXPECTED_BRANCH = "codex/h2-e3-a02-full-integration"
ACCEPTED_E2_HEAD = "1b46da916aec20aa2a27e533ac5e8aff9f360791"
DEFAULT_HOST_RECORD = ROOT / "r6o_evidence" / "H2-D1" / "host-environment.json"
DEFAULT_SELECTORS = ROOT / "r6o" / "host" / "codex" / "windows" / "selectors.json"
DEFAULT_EVIDENCE = ROOT / "r6o_evidence" / "H2-E3" / "actual-host"
FREEZE_MANIFEST = ROOT / "r6o_evidence" / "H2-E3" / "code-freeze.json"
FIXTURE_MANIFEST = ROOT / "fixtures" / "r6o2" / "a02-full" / "manifest.json"
RECORDED_CASE = ROOT / "fixtures" / "r6o2" / "a02-full" / "recorded-case.json"

EXPECTED_BY_TRANSITION = {
    "A02-T0-CODEX": [A02_OPERATIONS[0]],
    "A02-T1-FOCUS-CODEX": [],
    "A02-T2-REVISE-CODEX": list(A02_OPERATIONS[1:3]),
    "A02-T3-CODEX": list(A02_OPERATIONS[3:5]),
    "A02-T4-CODEX": list(A02_OPERATIONS[5:7]),
}


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


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


def _verify_fixture_identity() -> dict[str, Any]:
    try:
        recorded = json.loads(RECORDED_CASE.read_text(encoding="utf-8"))
        manifest = json.loads(FIXTURE_MANIFEST.read_text(encoding="utf-8"))
        validate_fixture_documents(recorded, manifest)
    except (OSError, json.JSONDecodeError, AssertionError, KeyError, TypeError, ValueError) as exc:
        raise H2E3IntegrationError("A02_FULL_FIXTURE_IDENTITY_INVALID") from exc
    return manifest


def _verify_freeze_manifest() -> dict[str, str]:
    freeze_path = str(FREEZE_MANIFEST.relative_to(ROOT)).replace("\\", "/")
    if (
        _git("ls-files", "--error-unmatch", freeze_path, check=False).returncode != 0
        or _git("diff", "--quiet", "HEAD", "--", freeze_path, check=False).returncode != 0
    ):
        raise H2E3IntegrationError("E3_CODE_FREEZE_MANIFEST_NOT_COMMITTED")
    try:
        freeze = json.loads(FREEZE_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise H2E3IntegrationError("E3_CODE_FREEZE_MANIFEST_UNREADABLE") from exc
    expected_keys = {
        "schema_version",
        "branch",
        "accepted_e2_head",
        "code_freeze_head",
        "code_freeze_tree",
    }
    if not isinstance(freeze, dict) or set(freeze) != expected_keys:
        raise H2E3IntegrationError("E3_CODE_FREEZE_MANIFEST_INVALID")
    if (
        freeze.get("schema_version") != "r6o-h2-e3-code-freeze-1"
        or freeze.get("branch") != EXPECTED_BRANCH
        or freeze.get("accepted_e2_head") != ACCEPTED_E2_HEAD
    ):
        raise H2E3IntegrationError("E3_CODE_FREEZE_MANIFEST_INVALID")
    freeze_head = freeze.get("code_freeze_head")
    freeze_tree = freeze.get("code_freeze_tree")
    if not isinstance(freeze_head, str) or not isinstance(freeze_tree, str):
        raise H2E3IntegrationError("E3_CODE_FREEZE_MANIFEST_INVALID")
    actual_tree = _git("rev-parse", f"{freeze_head}^{{tree}}", check=False)
    if actual_tree.returncode != 0 or actual_tree.stdout.strip() != freeze_tree:
        raise H2E3IntegrationError("E3_CODE_FREEZE_IDENTITY_MISMATCH")
    if _git("merge-base", "--is-ancestor", freeze_head, "HEAD", check=False).returncode != 0:
        raise H2E3IntegrationError("E3_CODE_FREEZE_NOT_ANCESTOR")
    post_freeze_paths = _git("diff", "--name-only", f"{freeze_head}..HEAD").stdout.splitlines()
    unauthorized_post_freeze = [
        path
        for path in post_freeze_paths
        if not path.replace("\\", "/").startswith("r6o_evidence/H2-E3/")
    ]
    if unauthorized_post_freeze:
        raise H2E3IntegrationError(
            "POST_FREEZE_NON_EVIDENCE_DIFF:" + "|".join(unauthorized_post_freeze)
        )
    return {"code_freeze_head": freeze_head, "code_freeze_tree": freeze_tree}


def verify_checkout() -> dict[str, str]:
    branch = _git("branch", "--show-current").stdout.strip()
    if branch != EXPECTED_BRANCH:
        raise H2E3IntegrationError(f"WRONG_E3_BRANCH:{branch}")
    ancestor = _git("merge-base", "--is-ancestor", ACCEPTED_E2_HEAD, "HEAD", check=False)
    if ancestor.returncode != 0:
        raise H2E3IntegrationError("ACCEPTED_E2_HEAD_NOT_ANCESTOR")
    _verify_fixture_identity()
    freeze = _verify_freeze_manifest()
    status = _git("status", "--porcelain=v1").stdout.splitlines()
    unauthorized = []
    for line in status:
        path = line[3:].replace("\\", "/") if len(line) > 3 else line
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if not path.startswith("r6o_evidence/H2-E3/"):
            unauthorized.append(line)
    if unauthorized:
        raise H2E3IntegrationError(
            "UNCOMMITTED_NON_E3_EVIDENCE_CHANGES:" + "|".join(unauthorized)
        )
    return {
        "branch": branch,
        "head": _git("rev-parse", "HEAD").stdout.strip(),
        "tree": _git("rev-parse", "HEAD^{tree}").stdout.strip(),
        **freeze,
    }


def _host_session_observation(binding: Any) -> dict[str, Any]:
    from r6o.host.codex.windows.uia import composer_empty_observation, fresh_chat_observation

    controls = binding.refresh_controls()
    reset = binding.selectors["reset_contract"]
    composer = composer_empty_observation(controls.composer, reset["composer_empty"])
    fresh = fresh_chat_observation(controls.primary_content_region, reset["fresh_chat"])
    return {"composer": composer, "conversation": fresh}


def _require_safe_host_session(observation: dict[str, Any], *, phase: str) -> None:
    if observation["composer"].get("empty") is not True:
        raise H2E3IntegrationError(f"{phase}_COMPOSER_NOT_EMPTY")
    if observation["conversation"].get("fresh") is not True:
        raise H2E3IntegrationError(f"{phase}_CODEX_SESSION_NOT_FRESH")


def _post_terminal_no_submission_ledger(
    binding: Any, *, duration_seconds: float = 3.0
) -> list[dict[str, Any]]:
    from PySide6.QtCore import QCoreApplication, QEventLoop

    started = time.monotonic()
    deadline = started + duration_seconds
    samples: list[dict[str, Any]] = []
    while not samples or time.monotonic() < deadline:
        app = QCoreApplication.instance()
        if app is not None:
            app.processEvents(QEventLoop.AllEvents, 25)
        observation = _host_session_observation(binding)
        _require_safe_host_session(observation, phase="POST_TERMINAL_SETTLE")
        samples.append(
            {
                "elapsed_ms": round((time.monotonic() - started) * 1000),
                "composer": observation["composer"],
                "conversation": observation["conversation"],
            }
        )
        time.sleep(0.1)
    return samples


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
        if transition_id not in EXPECTED_BY_TRANSITION:
            raise H2E3IntegrationError(f"UNEXPECTED_TRANSITION:{transition_id}")
        calls = self.worker.calls[self.call_cursor :]
        self.call_cursor = len(self.worker.calls)
        expected = [
            {"operation_id": operation_id, "operation": operation}
            for operation_id, operation in EXPECTED_BY_TRANSITION[transition_id]
        ]
        if calls != expected:
            raise H2E3IntegrationError(
                f"WORKER_OPERATION_SEQUENCE_MISMATCH:{transition_id}"
            )

        envelope = event["envelope"]
        if transition_id == "A02-T0-CODEX":
            if envelope is not None:
                raise H2E3IntegrationError("START_EMITTED_INPUT_ENVELOPE")
        elif transition_id == "A02-T1-FOCUS-CODEX":
            if (
                not isinstance(envelope, dict)
                or envelope.get("source") != "STRUCTURED_ACTION"
                or envelope.get("action_id") != "something_else"
                or envelope.get("text") is not None
            ):
                raise H2E3IntegrationError("INVALID_SOMETHING_ELSE_EVIDENCE")
        elif transition_id == "A02-T2-REVISE-CODEX":
            if (
                not isinstance(envelope, dict)
                or envelope.get("source") != "HOST_COMPOSER_TEXT"
                or envelope.get("text") != REVISION_TEXT
                or envelope.get("action_id") is not None
                or envelope.get("projection_id") is not None
            ):
                raise H2E3IntegrationError("INVALID_HOST_COMPOSER_TEXT_EVIDENCE")
        else:
            expected_action = (
                "confirm_prompt" if transition_id == "A02-T3-CODEX" else "confirm_plan"
            )
            if (
                not isinstance(envelope, dict)
                or envelope.get("source") != "STRUCTURED_ACTION"
                or envelope.get("action_id") != expected_action
                or envelope.get("text") is not None
            ):
                raise H2E3IntegrationError(
                    f"INVALID_STRUCTURED_ACTION_EVIDENCE:{transition_id}"
                )

        projection = event["projection"]
        host_session = _host_session_observation(self.binding)
        _require_safe_host_session(
            host_session, phase=f"TRANSITION_{transition_id.replace('-', '_')}"
        )
        projection_path = self.evidence_dir / "projections" / f"{transition_id}.json"
        _write_json(projection_path, projection)
        self.files.append(projection_path)
        capture_path: Path | None = None
        if projection["stage"] != "CLOSED_SUCCESS":
            capture_path = self.evidence_dir / "captures" / f"{transition_id}.png"
            self.binding.sidecar.capture(capture_path)
            self.files.append(capture_path)

        artifact = projection.get("artifact")
        input_binding = getattr(self, "input_binding", None)
        record = {
            "schema_version": "r6o-h2-e3-transition-1",
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
            "result_body_sha256": (
                hashlib.sha256(
                    projection["lifecycle"]["result_body"].encode("utf-8")
                ).hexdigest()
                if isinstance(projection.get("lifecycle"), dict)
                and isinstance(projection["lifecycle"].get("result_body"), str)
                else None
            ),
            "presentation": event["presentation"],
            "host_session_observation": host_session,
            "capture_path": (
                str(capture_path.relative_to(ROOT)).replace("\\", "/")
                if capture_path
                else None
            ),
            "input_binding": {
                "armed": bool(input_binding.armed) if input_binding is not None else None,
                "capture_count": input_binding.capture_count if input_binding is not None else None,
                "delivery_count": input_binding.delivery_count if input_binding is not None else None,
                "suppressed_keydown_count": (
                    input_binding.suppressed_keydown_count if input_binding is not None else None
                ),
                "suppressed_keyup_count": (
                    input_binding.suppressed_keyup_count if input_binding is not None else None
                ),
            },
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
        raise H2E3IntegrationError("E3_ATTEMPT_LEDGER_INVALID")
    return value


def _start_attempt(
    evidence_dir: Path, checkout: dict[str, str]
) -> tuple[Path, list[dict[str, Any]], int]:
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
            "code_freeze_head": checkout["code_freeze_head"],
            "code_freeze_tree": checkout["code_freeze_tree"],
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
        raise H2E3IntegrationError("ACTUAL_CODEX_HOST_REQUIRES_WINDOWS")
    os.environ.setdefault("QT_QUICK_BACKEND", "software")
    os.environ.setdefault("QT_SCALE_FACTOR", "1")
    os.environ.setdefault("QT_FONT_DPI", "96")
    try:
        from PySide6.QtCore import QCoreApplication, QEventLoop
        from r6o.host.codex.windows.binding import CodexSidecarBinding
        from r6o.host.codex.windows.input_binding import CodexComposerInputBinding
        from r6o.views.sidecar.qt_app import QtSidecarWindow
    except ImportError as exc:
        raise H2E3IntegrationError("HOST_DEPENDENCY_MISSING") from exc

    fixture_manifest = _verify_fixture_identity()
    baseline = resolve_baseline(args.baseline_repo)
    temporary: tempfile.TemporaryDirectory[str] | None = None
    model: LocalRuntimeModelBinding | None = None
    host: Any | None = None
    input_binding: Any | None = None
    callback_errors: list[Exception] = []
    holder: dict[str, Any] = {}
    try:
        workspace_root = args.workspace_root
        if workspace_root is None:
            temporary = tempfile.TemporaryDirectory(prefix="pdl-r6o-h2-e3-")
            workspace_root = Path(temporary.name) / "workspaces"

        delegate = A02ReplayWorker()
        worker = ObservedWorker(delegate, A02_OPERATIONS, "A02-FULL")
        model = LocalRuntimeModelBinding(
            baseline,
            worker=worker,
            workspace_root=workspace_root,
            run_id="h2-e3-a02-full",
        )

        def on_action(action_id: str) -> None:
            try:
                holder["session"].activate_action(action_id)
            except Exception as exc:
                callback_errors.append(exc)

        def on_envelope(envelope: dict[str, Any]) -> None:
            try:
                holder["session"].submit_composer_text(envelope)
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

        input_binding = CodexComposerInputBinding(host, on_envelope)
        input_binding.start()
        recorder = EvidenceRecorder(args.evidence_dir, worker, host)
        recorder.input_binding = input_binding
        session = CodexH2E3Session(
            model,
            AttachedCodexE3Presentation(host, input_binding),
            input_binding,
            ModelSessionRequest(request_id="h2-e3-a02-full", task_text=ACTIVATION_TEXT),
            on_transition=recorder,
        )
        holder["session"] = session
        session.start()

        deadline = time.monotonic() + args.timeout
        app = QCoreApplication.instance()
        while not session.terminal and not callback_errors:
            if time.monotonic() >= deadline:
                raise H2E3IntegrationError("HUMAN_ACTION_TIMEOUT")
            if app is None:
                raise H2E3IntegrationError("QT_APPLICATION_UNAVAILABLE")
            app.processEvents(QEventLoop.AllEvents, 50)
            time.sleep(0.01)
        if callback_errors:
            raise callback_errors[0]

        if input_binding.capture_count != 1 or input_binding.delivery_count != 1:
            raise H2E3IntegrationError("HOST_COMPOSER_CAPTURE_NOT_EXACTLY_ONCE")
        captured = input_binding.wait_for_delivery(timeout=1.0)
        if captured.get("text") != REVISION_TEXT:
            raise H2E3IntegrationError("CAPTURED_TEXT_MISMATCH")
        input_binding.assert_healthy()
        for transition in recorder.transitions:
            if transition["transition_id"] == "A02-T2-REVISE-CODEX":
                transition["input_binding"] = {
                    "armed": input_binding.armed,
                    "capture_count": input_binding.capture_count,
                    "delivery_count": input_binding.delivery_count,
                    "suppressed_keydown_count": input_binding.suppressed_keydown_count,
                    "suppressed_keyup_count": input_binding.suppressed_keyup_count,
                }

        post_terminal_ledger = _post_terminal_no_submission_ledger(host)
        postflight = {
            "composer": post_terminal_ledger[-1]["composer"],
            "conversation": post_terminal_ledger[-1]["conversation"],
        }
        expected_calls = [
            {"operation_id": operation_id, "operation": operation}
            for operation_id, operation in A02_OPERATIONS
        ]
        if worker.calls != expected_calls:
            raise H2E3IntegrationError("A02_OPERATIONS_NOT_CONSUMED_EXACTLY_ONCE")
        if [item["source"] for item in session.envelopes] != [
            "STRUCTURED_ACTION",
            "HOST_COMPOSER_TEXT",
            "STRUCTURED_ACTION",
            "STRUCTURED_ACTION",
        ]:
            raise H2E3IntegrationError("A02_INPUT_ENVELOPE_SEQUENCE_INVALID")
        if session.envelopes[0]["action_id"] != "something_else":
            raise H2E3IntegrationError("A02_FOCUS_ACTION_INVALID")
        if session.envelopes[1]["text"] != REVISION_TEXT:
            raise H2E3IntegrationError("A02_REVISION_TEXT_INVALID")
        if [item["action_id"] for item in session.envelopes[2:]] != [
            "confirm_prompt",
            "confirm_plan",
        ]:
            raise H2E3IntegrationError("A02_CONFIRMATION_SEQUENCE_INVALID")

        transitions = recorder.write()
        observed_hashes = {
            "initial_prompt_body_sha256": transitions[0]["artifact_body_sha256"],
            "revised_prompt_body_sha256": transitions[2]["artifact_body_sha256"],
            "plan_body_sha256": transitions[3]["artifact_body_sha256"],
            "final_result_body_sha256": transitions[4]["result_body_sha256"],
        }
        if observed_hashes != fixture_manifest["expected_artifact_hashes"]:
            raise H2E3IntegrationError("A02_ARTIFACT_HASHES_MISMATCH")
        no_native_submission = (
            preflight["conversation"]["visible_turn_group_count"] == 0
            and postflight["conversation"]["visible_turn_group_count"] == 0
            and preflight["composer"]["empty"] is True
            and postflight["composer"]["empty"] is True
            and all(
                item["host_session_observation"]["conversation"]["visible_turn_group_count"]
                == 0
                for item in transitions
            )
        )
        if not no_native_submission:
            raise H2E3IntegrationError("NATIVE_CODEX_SUBMISSION_NOT_DISPROVEN")
        if input_binding.suppressed_keydown_count != 1 or input_binding.suppressed_keyup_count != 1:
            raise H2E3IntegrationError("NATIVE_ENTER_PAIR_NOT_SUPPRESSED_EXACTLY_ONCE")
        return {
            "schema_version": "r6o-h2-e3-qualification-1",
            "status": "H2_E3_A02_FULL_PASS",
            "public_command": "python scripts\\h2\\run_codex_h2_e3.py --case A02-FULL --record",
            "case_id": "A02-FULL",
            "branch": checkout["branch"],
            "code_freeze_head": checkout["code_freeze_head"],
            "code_freeze_tree": checkout["code_freeze_tree"],
            "evidence_head_at_run": checkout["head"],
            "evidence_tree_at_run": checkout["tree"],
            "accepted_e2_head": ACCEPTED_E2_HEAD,
            "live_run_count": live_run_count,
            "actual_codex_host": _host_identity(host),
            "frozen_r6s": {
                "commit": FROZEN_ORACLE_COMMIT,
                "tree": FROZEN_ORACLE_TREE,
                "fixture": "A02-FULL",
                "manifest_sha256": _sha256_file(FIXTURE_MANIFEST),
                "recorded_case_file_sha256": _sha256_file(RECORDED_CASE),
                "recorded_case_sha256": fixture_manifest["recorded_case_sha256"],
            },
            "host_preflight": preflight,
            "host_postflight": postflight,
            "post_terminal_no_submission_ledger": post_terminal_ledger,
            "transitions": transitions,
            "input_envelopes": session.envelopes,
            "worker_operations": worker.calls,
            "native_codex_submission_observed": False,
            "native_enter_keydown_suppressed": True,
            "native_enter_keyup_suppressed": True,
            "composer_cleared": True,
            "sidecar_dismissed": True,
            "actual_composer_focus_restored": True,
        }
    finally:
        if input_binding is not None:
            input_binding.stop()
        if host is not None:
            host.close()
        if model is not None:
            model.close()
        if temporary is not None:
            temporary.cleanup()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=("A02-FULL",), required=True)
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
        print("H2 E3 FAIL: qualification requires --record", file=sys.stderr)
        return 2
    try:
        args.evidence_dir.relative_to(ROOT / "r6o_evidence" / "H2-E3")
    except ValueError:
        print("H2 E3 FAIL: evidence must remain under r6o_evidence/H2-E3", file=sys.stderr)
        return 2

    attempt_path: Path | None = None
    attempts: list[dict[str, Any]] | None = None
    try:
        checkout = verify_checkout()
        attempt_path, attempts, count = _start_attempt(args.evidence_dir, checkout)
        report = run(args, checkout, count)
        qualification_path = args.evidence_dir / "qualification.json"
        _write_json(qualification_path, report)
        _finish_attempt(attempt_path, attempts, status="H2_E3_A02_FULL_PASS")
        print("H2_E3_A02_FULL_PASS", flush=True)
        return 0
    except KeyboardInterrupt:
        failure = "INTERRUPTED"
        if attempt_path is not None and attempts is not None:
            _finish_attempt(attempt_path, attempts, status="FAIL", failure=failure)
        print("H2 E3 INTERRUPTED", file=sys.stderr, flush=True)
        return 130
    except Exception as exc:
        failure = getattr(exc, "code", str(exc))
        if attempt_path is not None and attempts is not None:
            _finish_attempt(attempt_path, attempts, status="FAIL", failure=failure)
        print(f"H2 E3 FAIL: {failure}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
