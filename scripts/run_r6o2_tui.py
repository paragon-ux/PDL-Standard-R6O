from __future__ import annotations

"""Public R6O terminal runner."""

import argparse
import hashlib
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from r6o.model_binding.base import ModelSessionRequest
from r6o.model_binding.local_runtime import LocalRuntimeModelBinding
from r6o.viewmodel.projection import build_focus_projection_from_port
from r6o.views.tui import TerminalReviewApp, TerminalViewClosed


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
A02_ACTIVATION = "Use $confirm-with-pseudocode to compare Kafka and RabbitMQ for event delivery."
A02_OPERATIONS = (
    ("A02F:0001", "DRAFT_PROMPT"),
    ("A02F:0002", "INTERPRET_PROMPT_REVIEW"),
    ("A02F:0003", "REVISE_PROMPT"),
    ("A02F:0004", "INTERPRET_PROMPT_REVIEW"),
    ("A02F:0005", "DRAFT_PLAN"),
    ("A02F:0006", "INTERPRET_PLAN_REVIEW"),
    ("A02F:0007", "EXECUTE"),
)
A02_FIXTURE = ROOT / "fixtures" / "r6o2" / "a02-full" / "recorded-case.json"


@dataclass(frozen=True)
class WorkerResult:
    text: str
    metadata: dict[str, Any]


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


def load_g06_worker(baseline: Path) -> Any:
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
        if (entry.get("source") or "").split(":", 1)[0] != "G06":
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


class A02ReplayWorker:
    """Fail closed unless every request matches the next frozen A02-FULL entry."""

    def __init__(self) -> None:
        value = json.loads(A02_FIXTURE.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("case_id") != "A02-FULL":
            raise RuntimeError("A02-FULL fixture identity differs")
        entries = value.get("entries")
        if not isinstance(entries, list) or len(entries) != len(A02_OPERATIONS):
            raise RuntimeError("A02-FULL fixture must contain exactly seven entries")
        self.entries = entries
        self.index = 0

    def call(self, request: Any) -> WorkerResult:
        if self.index >= len(self.entries):
            raise RuntimeError(f"ReplayMissError: replay exhausted at {request.operation}")
        entry = self.entries[self.index]
        operation_id, expected_operation = A02_OPERATIONS[self.index]
        actual_hash = sha256_text(request.prompt)
        if (
            entry.get("operation_id") != operation_id
            or entry.get("operation") != expected_operation
            or request.operation != expected_operation
            or actual_hash != entry.get("prompt_sha256")
        ):
            raise RuntimeError(
                "ReplayMissError: replay mismatch at "
                f"{operation_id}; expected {expected_operation} prompt={entry.get('prompt_sha256')}, "
                f"got {request.operation} prompt={actual_hash}"
            )
        self.index += 1
        return WorkerResult(
            text=entry["response"],
            metadata={"source": operation_id, "fixture": "A02-FULL"},
        )


class ObservedWorker:
    """Record successful calls while preserving the frozen worker's matching."""

    def __init__(self, delegate: Any, operations: tuple[tuple[str, str], ...], case_id: str) -> None:
        self.delegate = delegate
        self.operations = operations
        self.case_id = case_id
        self.calls: list[dict[str, str]] = []

    def call(self, request: Any) -> Any:
        index = len(self.calls)
        if index >= len(self.operations):
            raise RuntimeError(f"unexpected extra {self.case_id} operation: {request.operation}")
        operation_id, expected = self.operations[index]
        if request.operation != expected:
            raise RuntimeError(f"expected {operation_id} {expected}, got {request.operation}")
        result = self.delegate.call(request)
        self.calls.append({"operation_id": operation_id, "operation": request.operation})
        return result


class StateTransitionRecorder:
    def __init__(self, path: Path | None, worker: ObservedWorker, case_id: str) -> None:
        self.path = path.resolve() if path else None
        self.worker = worker
        self.case_id = case_id
        self.call_cursor = 0
        self.records: list[dict[str, Any]] = []
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text("", encoding="utf-8")

    def __call__(self, event: str, action_id: str | None, projection: dict[str, Any]) -> None:
        new_calls = self.worker.calls[self.call_cursor :]
        self.call_cursor = len(self.worker.calls)
        transitions = {
            "G06": {
                ("START", None): ("G06-T0-TUI", "G06-S1", "TUI_ACTION_CONFIRM_PROMPT", None),
                ("ACTION", "confirm_prompt"): (
                    "G06-T1-TUI", "G06-S2", "TUI_ACTION_CONFIRM_PLAN", "STRUCTURED_ACTION"
                ),
                ("ACTION", "confirm_plan"): (
                    "G06-T2-TUI", "G06-S3", "CALLING_SHELL", "STRUCTURED_ACTION"
                ),
            },
            "A02-FULL": {
                ("START", None): ("A02-T0-TUI", "A02-S1", "TUI_ACTION_CONFIRM_PROMPT", None),
                ("FOCUS", "something_else"): (
                    "A02-T1-FOCUS-TUI", "A02-S1", "TUI_FREE_RESPONSE_INPUT", "STRUCTURED_ACTION"
                ),
                ("TEXT", None): (
                    "A02-T2-REVISE-TUI", "A02-S2", "TUI_ACTION_CONFIRM_PROMPT", "TUI_TEXT"
                ),
                ("ACTION", "confirm_prompt"): (
                    "A02-T3-TUI", "A02-S3", "TUI_ACTION_CONFIRM_PLAN", "STRUCTURED_ACTION"
                ),
                ("ACTION", "confirm_plan"): (
                    "A02-T4-TUI", "A02-S4", "CALLING_SHELL", "STRUCTURED_ACTION"
                ),
            },
        }
        transition = transitions[self.case_id].get((event, action_id))
        if transition is None:
            raise RuntimeError(f"unexpected {self.case_id} TUI transition: {event}/{action_id}")
        transition_id, state_id, focus_owner, envelope_source = transition
        artifact = projection.get("artifact")
        lifecycle = projection["lifecycle"]
        record: dict[str, Any] = {
            "schema_version": (
                "r6o-h2-b1-state-transition-1"
                if self.case_id == "G06"
                else "r6o-h2-b2-state-transition-1"
            ),
            "transition_id": transition_id,
            "state_id": state_id,
            "stage": projection["stage"],
            "action_id": action_id,
            "input_envelope_source": envelope_source,
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
    parser.add_argument("--recorded", action="store_true", help="use the gate-approved recorded fixture")
    parser.add_argument("--case", choices=("G06", "A02-FULL"), required=True)
    parser.add_argument("--baseline-repo", type=Path)
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--state-log", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.recorded:
        print("R6O TUI FAIL: H2 TUI qualification requires --recorded", file=sys.stderr)
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
        operations = G06_OPERATIONS if args.case == "G06" else A02_OPERATIONS
        activation = G06_ACTIVATION if args.case == "G06" else A02_ACTIVATION
        delegate = load_g06_worker(baseline) if args.case == "G06" else A02ReplayWorker()
        worker = ObservedWorker(delegate, operations, args.case)
        run_token = f"h2-{'b1-tui-g06' if args.case == 'G06' else 'b2-tui-a02-full'}"
        binding = LocalRuntimeModelBinding(
            baseline,
            worker=worker,
            workspace_root=workspace_root,
            run_id=run_token,
        )
        started = binding.start_or_resume(
            ModelSessionRequest(request_id=run_token, task_text=activation)
        )
        projection = build_focus_projection_from_port(binding, started.session_id)
        recorder = StateTransitionRecorder(args.state_log, worker, args.case)
        final_projection = TerminalReviewApp(
            binding,
            started.session_id,
            on_projection=recorder,
        ).run(projection)
        if final_projection["stage"] != "CLOSED_SUCCESS":
            raise RuntimeError(f"TUI ended at {final_projection['stage']}, expected CLOSED_SUCCESS")
        expected_ids = [operation_id for operation_id, _ in operations]
        if [item["operation_id"] for item in worker.calls] != expected_ids:
            raise RuntimeError(f"{args.case} worker operations were not consumed exactly once in order")
        print("R6O TUI PASS: CLOSED_SUCCESS", flush=True)
        return 0
    except KeyboardInterrupt:
        print("R6O TUI INTERRUPTED", file=sys.stderr, flush=True)
        return 130
    except TerminalViewClosed:
        print("R6O TUI CLOSED", flush=True)
        return 0
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
