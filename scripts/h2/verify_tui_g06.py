from __future__ import annotations

"""Process-level H2-B1 qualification for the public G06 TUI."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any


sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "run_r6o2_tui.py"
DEFAULT_EVIDENCE_DIR = ROOT / "r6o_evidence" / "H2-B1"
REFERENCE_PATH = ROOT / "docs" / "h2" / "TUI-REFERENCE-v4-2026-08-22.md"
REFERENCE_SHA256 = "af74ce9fa9b09b8f7e4e555e9213c9e6a0574897718749c872f015da51c331b5"
FROZEN_ORACLE_COMMIT = "60d982f3328b45a351879d67dc4bb525172b65fd"
FROZEN_ORACLE_TREE = "b7689fbe8b9c9838438cbba6f6e0e5c1ce5b5ed6"
PROMPT_SHA256 = "3b981f581b4f8ab151852f9214493c65accc72153f2f57c68dbc3c4c244911f2"
PLAN_SHA256 = "4763d12d6203ca03c4e8936f2dfb58a3d0d0e782d8990f7a5d12dbf8425bf7ce"
RESULT_SHA256 = "47106d2d4689ef07820e0537511d0cbabdb50701ca0bef83d52dc1b617ea279b"
EXPECTED_TRANSITIONS = (
    ("G06-T0-TUI", "G06-S1", "PROMPT_REVIEW", None, ("G06:0001",), "prompt", PROMPT_SHA256, "TUI_ACTION_CONFIRM_PROMPT"),
    ("G06-T1-TUI", "G06-S2", "PLAN_REVIEW", "confirm_prompt", ("G06:0002", "G06:0003"), "plan", PLAN_SHA256, "TUI_ACTION_CONFIRM_PLAN"),
    ("G06-T2-TUI", "G06-S3", "CLOSED_SUCCESS", "confirm_plan", ("G06:0004", "G06:0005"), None, None, "CALLING_SHELL"),
)


def git_value(repo: Path, expression: str) -> str:
    process = subprocess.run(
        ["git", "rev-parse", expression],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if process.returncode != 0:
        raise RuntimeError((process.stdout + process.stderr).strip())
    return process.stdout.strip()


def git_status(repo: Path) -> str:
    process = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if process.returncode != 0:
        raise RuntimeError((process.stdout + process.stderr).strip())
    return process.stdout.strip()


def require_clean_oracle(repo: Path) -> None:
    status = git_status(repo)
    if status:
        raise RuntimeError(f"frozen oracle working tree is not clean:\n{status}")


def resolve_baseline(value: Path | None) -> Path:
    candidate = value or os.environ.get("PDL_R6S_BASELINE_REPO") or (ROOT.parent / "PDL-Standard-REPL-Harness")
    baseline = Path(candidate).resolve()
    if not baseline.is_dir():
        raise RuntimeError(f"frozen baseline not found: {baseline}")
    commit = git_value(baseline, "HEAD")
    tree = git_value(baseline, "HEAD^{tree}")
    if (commit, tree) != (FROZEN_ORACLE_COMMIT, FROZEN_ORACLE_TREE):
        raise RuntimeError(f"frozen oracle mismatch: {commit}/{tree}")
    require_clean_oracle(baseline)
    return baseline


def physical_inventory(root: Path) -> dict[str, tuple[int, int, str]]:
    result: dict[str, tuple[int, int, str]] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root)
        if ".git" in relative.parts:
            continue
        stat = path.stat()
        result[relative.as_posix()] = (
            stat.st_size,
            stat.st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
    return result


def is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def normalized_text_sha256(path: Path) -> str:
    """Hash UTF-8 text after universal-newline normalization."""

    return hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()


class ProcessKeyboardDriver:
    """Drive the public process through its stdin keyboard boundary."""

    def __init__(self, command: list[str], *, cwd: Path, environment: dict[str, str]) -> None:
        self.started = time.monotonic()
        self.output = bytearray()
        self.events: list[tuple[float, str, bytes]] = []
        self.condition = threading.Condition()
        self.process = subprocess.Popen(
            command,
            cwd=cwd,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.reader = threading.Thread(target=self._read_output, name="h2-b1-tui-output", daemon=True)
        self.reader.start()

    def _read_output(self) -> None:
        assert self.process.stdout is not None
        while True:
            chunk = self.process.stdout.read(1)
            if not chunk:
                break
            with self.condition:
                self.output.extend(chunk)
                self.events.append((time.monotonic() - self.started, "o", chunk))
                self.condition.notify_all()
        with self.condition:
            self.condition.notify_all()

    def wait_for(self, marker: str, *, after: int = 0, timeout: float = 30.0) -> int:
        encoded = marker.encode("utf-8")
        deadline = time.monotonic() + timeout
        with self.condition:
            while True:
                position = bytes(self.output).find(encoded, after)
                if position >= 0:
                    return position
                if self.process.poll() is not None:
                    transcript = bytes(self.output).decode("utf-8", errors="replace")
                    raise AssertionError(f"process exited before {marker!r}:\n{transcript}")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    transcript = bytes(self.output).decode("utf-8", errors="replace")
                    raise AssertionError(f"timed out waiting for {marker!r}:\n{transcript}")
                self.condition.wait(min(remaining, 0.1))

    def press_enter(self) -> None:
        if self.process.stdin is None:
            raise AssertionError("public process stdin is unavailable")
        payload = b"\r"
        self.process.stdin.write(payload)
        self.process.stdin.flush()
        self.events.append((time.monotonic() - self.started, "i", payload))

    def finish(self, timeout: float = 30.0) -> tuple[int, str]:
        if self.process.stdin is not None:
            self.process.stdin.close()
        returncode = self.process.wait(timeout=timeout)
        self.reader.join(timeout=5.0)
        transcript = bytes(self.output).decode("utf-8", errors="replace")
        return returncode, transcript

    def stop(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5.0)

    def cast_events(self) -> list[list[Any]]:
        coalesced: list[list[Any]] = []
        for elapsed, event_type, payload in self.events:
            if coalesced and coalesced[-1][1] == event_type:
                coalesced[-1][2].extend(payload)
            else:
                coalesced.append([round(elapsed, 6), event_type, bytearray(payload)])
        return [
            [elapsed, event_type, bytes(payload).decode("utf-8", errors="strict")]
            for elapsed, event_type, payload in coalesced
        ]


def load_state_log(path: Path) -> list[dict[str, Any]]:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = json.loads(line)
        if not isinstance(value, dict):
            raise AssertionError("state transition line must be an object")
        records.append(value)
    return records


def verify_state_log(records: list[dict[str, Any]]) -> None:
    if len(records) != len(EXPECTED_TRANSITIONS):
        raise AssertionError(f"expected three state transitions, got {len(records)}")
    operation_ids: list[str] = []
    for record, expected in zip(records, EXPECTED_TRANSITIONS, strict=True):
        transition_id, state_id, stage, action_id, operations, artifact_kind, artifact_hash, focus = expected
        if record.get("schema_version") != "r6o-h2-b1-state-transition-1":
            raise AssertionError(f"wrong state-log schema at {transition_id}")
        actual = (
            record.get("transition_id"),
            record.get("state_id"),
            record.get("stage"),
            record.get("action_id"),
            record.get("artifact_kind"),
            record.get("artifact_body_sha256"),
            record.get("focus_owner"),
        )
        if actual != (transition_id, state_id, stage, action_id, artifact_kind, artifact_hash, focus):
            raise AssertionError(f"state transition differs at {transition_id}: {actual}")
        observed_operations = record.get("worker_operations")
        if not isinstance(observed_operations, list):
            raise AssertionError(f"worker_operations must be a list at {transition_id}")
        expected_operation_names = {
            "G06:0001": "DRAFT_PROMPT",
            "G06:0002": "INTERPRET_PROMPT_REVIEW",
            "G06:0003": "DRAFT_PLAN",
            "G06:0004": "INTERPRET_PLAN_REVIEW",
            "G06:0005": "EXECUTE",
        }
        observed_ids = tuple(item.get("operation_id") for item in observed_operations)
        if observed_ids != operations:
            raise AssertionError(f"worker operation IDs differ at {transition_id}: {observed_ids}")
        for item in observed_operations:
            if set(item) != {"operation_id", "operation"}:
                raise AssertionError(f"worker operation fields differ at {transition_id}")
            if item["operation"] != expected_operation_names[item["operation_id"]]:
                raise AssertionError(f"worker operation name differs at {item['operation_id']}")
        operation_ids.extend(observed_ids)
    if operation_ids != [f"G06:000{index}" for index in range(1, 6)]:
        raise AssertionError("G06 operations were not observed exactly once in order")
    terminal = records[-1]
    if terminal.get("terminal_disposition") != "HOST_HANDOFF":
        raise AssertionError("terminal disposition is not HOST_HANDOFF")
    if terminal.get("authorized_artifact_hashes") != {"prompt": PROMPT_SHA256, "plan": PLAN_SHA256}:
        raise AssertionError("terminal Prompt/Plan hashes differ")
    if terminal.get("result_body_sha256") != RESULT_SHA256:
        raise AssertionError("terminal result hash differs")


def write_cast(path: Path, events: list[list[Any]]) -> None:
    header = {
        "version": 2,
        "width": 80,
        "height": 30,
        "timestamp": int(time.time()),
        "env": {"TERM": "xterm-256color", "SHELL": "public-process-keyboard-driver"},
    }
    content = [json.dumps(header, sort_keys=True)]
    content.extend(json.dumps(event, ensure_ascii=False) for event in events)
    path.write_text("\n".join(content) + "\n", encoding="utf-8", newline="\n")


def run_qualification(
    baseline_repo: Path | None = None,
    *,
    evidence_dir: Path = DEFAULT_EVIDENCE_DIR,
) -> dict[str, Any]:
    baseline = resolve_baseline(baseline_repo)
    if not REFERENCE_PATH.is_file() or normalized_text_sha256(REFERENCE_PATH) != REFERENCE_SHA256:
        raise AssertionError("H2-B1 TUI reference v4 identity differs")
    oracle_before = physical_inventory(baseline)
    evidence = evidence_dir.resolve()
    if is_within(evidence, baseline):
        raise ValueError("evidence directory must be outside the frozen R6S baseline")
    evidence.mkdir(parents=True, exist_ok=True)
    state_log = evidence / "state-transitions.jsonl"
    cast_path = evidence / "tui-g06.cast"
    results_path = evidence / "test-results.json"
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    with tempfile.TemporaryDirectory(prefix="pdl-h2-b1-") as temporary:
        workspace_root = Path(temporary) / "workspaces"
        command = [
            sys.executable,
            str(RUNNER),
            "--recorded",
            "--case",
            "G06",
            "--baseline-repo",
            str(baseline),
            "--workspace-root",
            str(workspace_root),
            "--state-log",
            str(state_log),
        ]
        driver = ProcessKeyboardDriver(command, cwd=ROOT, environment=environment)
        try:
            prompt_position = driver.wait_for("PDLt · PROMPT REVIEW")
            driver.wait_for("ACTIVE", after=prompt_position)
            driver.wait_for(
                "Explain the difference between optimistic locking and pessimistic locking",
                after=prompt_position,
            )
            driver.wait_for("Review Options", after=prompt_position)
            driver.wait_for("> 1  Confirm prompt", after=prompt_position)
            driver.wait_for("Enter  Select", after=prompt_position)
            driver.press_enter()
            plan_position = driver.wait_for("PDLt · PLAN REVIEW", after=prompt_position + 1)
            driver.wait_for("IDENTIFY the target audience as senior developers", after=plan_position)
            driver.wait_for("Review Options", after=plan_position)
            driver.wait_for("> 1  Confirm plan", after=plan_position)
            driver.press_enter()
            returncode, transcript = driver.finish()
        finally:
            driver.stop()
    if returncode != 0:
        raise AssertionError(f"public TUI exited {returncode}:\n{transcript}")
    if "R6O TUI PASS: CLOSED_SUCCESS" not in transcript:
        raise AssertionError("public runner did not report CLOSED_SUCCESS")
    for forbidden in ("PDLt REVIEW", "\nACTIONS\n", "[Enter]", "PDLt · REVIEW COMPLETE"):
        if forbidden in transcript:
            raise AssertionError(f"superseded TUI presentation marker rendered: {forbidden!r}")
    records = load_state_log(state_log)
    verify_state_log(records)
    oracle_after = physical_inventory(baseline)
    if oracle_after != oracle_before:
        raise AssertionError("frozen R6S oracle physical inventory changed")
    write_cast(cast_path, driver.cast_events())
    report = {
        "schema_version": "r6o-h2-b1-test-results-1",
        "gate": "H2-B1",
        "status": "MECHANICAL_PASS_PENDING_HUMAN",
        "driver": "PUBLIC_PROCESS_STDIN_KEYBOARD_BOUNDARY",
        "public_command": "python scripts\\run_r6o2_tui.py --recorded --case G06",
        "exit_code": returncode,
        "observed_screens": ["PROMPT REVIEW", "PLAN REVIEW"],
        "terminal_behavior": "RESTORE_AND_RETURN_WITHOUT_TERMINAL_REVIEW_SCREEN",
        "presentation_reference": {
            "path": "docs/h2/TUI-REFERENCE-v4-2026-08-22.md",
            "normalized_text_sha256": REFERENCE_SHA256,
        },
        "observed_operation_ids": [f"G06:000{index}" for index in range(1, 6)],
        "final_stage": "CLOSED_SUCCESS",
        "prompt_body_sha256": PROMPT_SHA256,
        "plan_body_sha256": PLAN_SHA256,
        "result_body_sha256": RESULT_SHA256,
        "oracle_commit": FROZEN_ORACLE_COMMIT,
        "oracle_tree": FROZEN_ORACLE_TREE,
        "oracle_inventory_unchanged": True,
        "terminal_recording": cast_path.name,
        "state_transitions": state_log.name,
    }
    results_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-repo", type=Path)
    parser.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_qualification(args.baseline_repo, evidence_dir=args.evidence_dir)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
