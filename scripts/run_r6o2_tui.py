from __future__ import annotations

"""Public R6O terminal runner."""

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from r6o.model_binding.base import ModelSessionRequest
from r6o.model_binding.local_runtime import LocalRuntimeModelBinding
from r6o.viewmodel.projection import build_focus_projection_from_port
from r6o.views.tui import TerminalReviewApp


G06_ACTIVATION = (
    "Use $confirm-with-pseudocode to explain the difference between optimistic and "
    "pessimistic locking for senior developers."
)
G06_OPERATIONS = (
    ("G06:0001", "DRAFT_PROMPT"),
    ("G06:0002", "INTERPRET_PROMPT_REVIEW"),
    ("G06:0003", "DRAFT_PLAN"),
    ("G06:0004", "INTERPRET_PLAN_REVIEW"),
    ("G06:0005", "EXECUTE"),
)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def resolve_baseline(value: Path | None) -> Path:
    candidate = value or os.environ.get("PDL_R6S_BASELINE_REPO") or (ROOT.parent / "PDL-Standard-REPL-Harness")
    baseline = Path(candidate).resolve()
    if not (baseline / "fixtures" / "r4-recorded-worker" / "recorded-cases.json").is_file():
        raise RuntimeError(f"frozen R6S baseline not found at {baseline}")
    return baseline


def load_recorded_worker(baseline: Path, case_id: str) -> Any:
    fixture_path = baseline / "fixtures" / "r4-recorded-worker" / "recorded-cases.json"
    entries = json.loads(fixture_path.read_text(encoding="utf-8"))["entries"]
    old_path = list(sys.path)
    sys.path.insert(0, str(baseline))
    try:
        from providers.recorded import RecordedFixtureBuilder
    finally:
        sys.path[:] = old_path
    builder = RecordedFixtureBuilder()
    selected = 0
    for entry in entries:
        if (entry.get("source") or "").split(":", 1)[0] != case_id:
            continue
        builder.add(
            entry["operation"],
            entry["prompt_sha256"],
            entry["response"],
            metadata={"source": entry.get("source", "frozen-r6s")},
            prompt_text=entry.get("prompt_text"),
        )
        selected += 1
    if selected != len(G06_OPERATIONS):
        raise RuntimeError(f"frozen G06 fixture has {selected} entries, expected {len(G06_OPERATIONS)}")
    return builder.build()


class ObservedWorker:
    """Record successful calls while preserving the frozen worker's matching."""

    def __init__(self, delegate: Any) -> None:
        self.delegate = delegate
        self.calls: list[dict[str, str]] = []

    def call(self, request: Any) -> Any:
        index = len(self.calls)
        if index >= len(G06_OPERATIONS):
            raise RuntimeError(f"unexpected extra G06 operation: {request.operation}")
        operation_id, expected = G06_OPERATIONS[index]
        if request.operation != expected:
            raise RuntimeError(f"expected {operation_id} {expected}, got {request.operation}")
        result = self.delegate.call(request)
        self.calls.append({"operation_id": operation_id, "operation": request.operation})
        return result


class StateTransitionRecorder:
    def __init__(self, path: Path | None, worker: ObservedWorker) -> None:
        self.path = path.resolve() if path else None
        self.worker = worker
        self.call_cursor = 0
        self.records: list[dict[str, Any]] = []
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text("", encoding="utf-8")

    def __call__(self, event: str, action_id: str | None, projection: dict[str, Any]) -> None:
        new_calls = self.worker.calls[self.call_cursor :]
        self.call_cursor = len(self.worker.calls)
        transition = {
            ("START", None): ("G06-T0-TUI", "G06-S1", "TUI_ACTION_CONFIRM_PROMPT"),
            ("ACTION", "confirm_prompt"): ("G06-T1-TUI", "G06-S2", "TUI_ACTION_CONFIRM_PLAN"),
            ("ACTION", "confirm_plan"): ("G06-T2-TUI", "G06-S3", "INVOKING_SHELL"),
        }.get((event, action_id))
        if transition is None:
            raise RuntimeError(f"unexpected G06 TUI transition: {event}/{action_id}")
        transition_id, state_id, focus_owner = transition
        artifact = projection.get("artifact")
        lifecycle = projection["lifecycle"]
        record: dict[str, Any] = {
            "schema_version": "r6o-h2-b1-state-transition-1",
            "transition_id": transition_id,
            "state_id": state_id,
            "stage": projection["stage"],
            "action_id": action_id,
            "worker_operations": new_calls,
            "artifact_kind": artifact["artifact_kind"] if artifact else None,
            "artifact_body_sha256": sha256_text(artifact["body"]) if artifact else None,
            "focus_owner": focus_owner,
            "terminal_disposition": lifecycle["terminal_disposition"],
        }
        if projection["stage"] == "CLOSED_SUCCESS":
            record["authorized_artifact_hashes"] = {
                item["artifact_kind"]: sha256_text(item["body"])
                for item in lifecycle["authorized_handoff_artifacts"]
            }
            record["result_body_sha256"] = sha256_text(lifecycle["result_body"])
        self.records.append(record)
        if self.path:
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recorded", action="store_true", help="use the frozen R6S recorded worker")
    parser.add_argument("--case", choices=("G06",), required=True)
    parser.add_argument("--baseline-repo", type=Path)
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--state-log", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.recorded:
        print("R6O TUI FAIL: H2-B1 requires --recorded", file=sys.stderr)
        return 2
    binding: LocalRuntimeModelBinding | None = None
    temporary: tempfile.TemporaryDirectory[str] | None = None
    try:
        baseline = resolve_baseline(args.baseline_repo)
        if args.state_log is not None and is_within(args.state_log, baseline):
            raise RuntimeError("state-log must be outside the frozen R6S baseline")
        workspace_root = args.workspace_root
        if workspace_root is None:
            temporary = tempfile.TemporaryDirectory(prefix="pdl-r6o2-tui-")
            workspace_root = Path(temporary.name) / "workspaces"
        worker = ObservedWorker(load_recorded_worker(baseline, args.case))
        binding = LocalRuntimeModelBinding(
            baseline,
            worker=worker,
            workspace_root=workspace_root,
            run_id="h2-b1-tui-g06",
        )
        started = binding.start_or_resume(
            ModelSessionRequest(request_id="h2-b1-tui-g06", task_text=G06_ACTIVATION)
        )
        projection = build_focus_projection_from_port(binding, started.session_id)
        recorder = StateTransitionRecorder(args.state_log, worker)
        final_projection = TerminalReviewApp(
            binding,
            started.session_id,
            on_projection=recorder,
        ).run(projection)
        if final_projection["stage"] != "CLOSED_SUCCESS":
            raise RuntimeError(f"TUI ended at {final_projection['stage']}, expected CLOSED_SUCCESS")
        expected_ids = [operation_id for operation_id, _ in G06_OPERATIONS]
        if [item["operation_id"] for item in worker.calls] != expected_ids:
            raise RuntimeError("G06 worker operations were not consumed exactly once in order")
        print("R6O TUI PASS: CLOSED_SUCCESS", flush=True)
        return 0
    except KeyboardInterrupt:
        print("R6O TUI INTERRUPTED", file=sys.stderr, flush=True)
        return 130
    except Exception as exc:
        print(f"R6O TUI FAIL: {exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        if binding is not None:
            binding.close()
        if temporary is not None:
            temporary.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
