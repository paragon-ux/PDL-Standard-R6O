from __future__ import annotations

"""R6O-2 TUI dev-run entry point.

Examples:
    python scripts/run_r6o2_tui.py --demo
    python scripts/run_r6o2_tui.py --recorded
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from r6o.model_binding.base import ModelSessionRequest
from r6o.model_binding.local_runtime import LocalRuntimeModelBinding
from r6o.model_binding.memory_model import StaticModelPort
from r6o.presentation_transport import PresentationAdapter
from r6o.views.tui.app import run as run_tui
from r6o.views.tui.controller import TuiController


def _demo_port():
    from r6o.model_binding.base import ArtifactSnapshot, LifecycleSnapshot, ModelStateSnapshot, ReviewSubject

    body = "COMPARE Kafka and RabbitMQ for event delivery.\n- delivery guarantees\n- throughput\n- consumer model\n- operations burden\n- ecosystem maturity"
    artifact = ArtifactSnapshot("prompt:P1", "P1", "prompt", "Authoritative Prompt (PDL.md)", body)
    snapshot = ModelStateSnapshot(
        session_id="demo-1", workspace_id="W-demo", model_revision="demo-rev-1", stage="PROMPT_REVIEW",
        interaction_state="REVIEW_REQUIRED",
        review_subject=ReviewSubject("prompt:P1", "P1", "prompt", "Authoritative Prompt (PDL.md)"),
        lifecycle=LifecycleSnapshot(True, False, True, False, None, None, ()),
        model_response=None,
    )
    return StaticModelPort(snapshot, {"prompt:P1": artifact})


def _recorded_port():
    baseline = Path(__file__).resolve().parents[1].parent / "PDL-Standard-REPL-Harness"
    fixture = baseline / "fixtures" / "r4-recorded-worker" / "recorded-cases.json"
    from providers.fixtures import build_recorded_fixture_from_vendored

    worker = build_recorded_fixture_from_vendored(baseline, fixture, case_ids=["G06"])
    binding = LocalRuntimeModelBinding(baseline, worker=worker, workspace_root=Path(tempfile.mkdtemp(prefix="r6o2-tui-")), run_id="tui")
    binding.start_or_resume(ModelSessionRequest(request_id="tui", task_text="Use $confirm-with-pseudocode to explain the difference between optimistic and pessimistic locking for senior developers."))
    return binding, binding.read_state(binding._session_id).session_id


def main() -> int:
    parser = argparse.ArgumentParser(description="R6O-2 TUI dev run")
    parser.add_argument("--demo", action="store_true", help="static demo session")
    parser.add_argument("--recorded", action="store_true", help="deterministic recorded G06 session")
    args = parser.parse_args()
    if not (args.demo or args.recorded):
        args.demo = True
    if args.recorded:
        port, session = _recorded_port()
    else:
        port, session = _demo_port(), "demo-1"
    controller = TuiController(PresentationAdapter(port), session)
    run_tui(controller)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
