from __future__ import annotations

"""R6O-2 Sidecar dev-run entry point.

Examples:
    python scripts/run_r6o2_sidecar.py --harness --mode STANDARD
    python scripts/run_r6o2_sidecar.py --standalone --mode EXPANDED
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from r6o.model_binding.base import ArtifactSnapshot, LifecycleSnapshot, ModelStateSnapshot, ReviewSubject
from r6o.model_binding.memory_model import StaticModelPort
from r6o.presentation_transport import PresentationAdapter
from r6o.views.sidecar.app import HarnessShell, TkSidecarView
from r6o.views.sidecar.model import SidecarModel


def _demo_snapshot(mode: str) -> ModelStateSnapshot:
    body = (
        "COMPARE Kafka and RabbitMQ for event delivery.\n"
        "- delivery guarantees\n- throughput\n- consumer model\n"
        "- operations burden\n- ecosystem maturity\n- operational complexity"
    )
    artifact = ArtifactSnapshot(
        artifact_ref="prompt:P1",
        artifact_revision="P1",
        artifact_kind="prompt",
        title="Authoritative Prompt (PDL.md)",
        body=body,
        capabilities={"copy": True, "open_external": False},
    )
    subject = ReviewSubject(
        artifact_ref="prompt:P1",
        artifact_revision="P1",
        artifact_kind="prompt",
        title="Authoritative Prompt (PDL.md)",
    )
    return ModelStateSnapshot(
        session_id="demo-1",
        workspace_id="W-demo",
        model_revision="demo-rev-1",
        stage="PROMPT_REVIEW",
        interaction_state="REVIEW_REQUIRED",
        review_subject=subject,
        lifecycle=LifecycleSnapshot(
            review_required=True,
            terminal=False,
            close_allowed=True,
            handoff_ready=False,
            terminal_disposition=None,
            result_body=None,
            authorized_handoff_artifacts=(),
        ),
        model_response=None,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="R6O-2 Sidecar dev run")
    parser.add_argument("--mode", choices=["STANDARD", "EXPANDED"], default="STANDARD")
    parser.add_argument("--harness", action="store_true", help="show inside the qualification harness shell")
    parser.add_argument("--standalone", action="store_true", help="show as a standalone sidecar window")
    args = parser.parse_args()
    if args.harness == args.standalone:
        args.harness = True
    snapshot = _demo_snapshot(args.mode)
    artifact = ArtifactSnapshot(
        "prompt:P1", "P1", "prompt", "Authoritative Prompt (PDL.md)",
        "COMPARE Kafka and RabbitMQ for event delivery.\n- delivery guarantees\n- throughput\n- consumer model\n- operations burden\n- ecosystem maturity\n- operational complexity",
    )
    port = StaticModelPort(snapshot, {"prompt:P1": artifact})
    model = SidecarModel(PresentationAdapter(port), "demo-1")
    model.mode = args.mode
    if args.harness:
        HarnessShell(model).run()
    else:
        TkSidecarView(model).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

