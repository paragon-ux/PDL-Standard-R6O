from __future__ import annotations

"""Public R6O-2 Sidecar qualification-harness entry point."""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from r6o.views.sidecar import SidecarHarness, SidecarModel
from scripts._r6o2_recorded import start_recorded_session


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch the public R6O-2 Sidecar")
    parser.add_argument("--recorded", action="store_true", help="use the qualified G06 recorded binding")
    parser.add_argument("--harness", action="store_true", help="embed in the H2 qualification host")
    parser.add_argument("--mode", choices=("STANDARD", "EXPANDED"), default="STANDARD")
    parser.add_argument("--capture", type=Path, help="capture the initial public window and exit")
    parser.add_argument(
        "--capture-stage",
        choices=("PROMPT_REVIEW", "PLAN_REVIEW"),
        default="PROMPT_REVIEW",
        help="projection stage to capture when --capture is used",
    )
    parser.add_argument("--smoke", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not args.recorded:
        parser.error("--recorded is required for the H2 public surface")
    if not args.harness:
        parser.error("--harness is required for the H2 public surface")

    session = start_recorded_session("G06", surface=f"r6o2-sidecar-{args.mode.lower()}")
    try:
        model = SidecarModel(session.adapter, session.session_id, args.mode)
        headless = args.smoke or os.environ.get("R6O2_SMOKE_MODE") == "1"
        display_smoke = os.environ.get("R6O2_DISPLAY_SMOKE") == "1"
        if headless and not display_smoke and not args.capture:
            print(
                "R6O2_SIDECAR_READY "
                f"session={model.projection['session_id']} "
                f"stage={model.projection['stage']} mode={model.mode} "
                "display=LOCAL_DISPLAY_GATE_REQUIRED"
            )
            return 0
        harness = SidecarHarness(model)
        if args.capture or display_smoke:
            harness.root.update()
            if args.capture and args.capture_stage == "PLAN_REVIEW":
                harness.invoke_action("confirm_prompt")
                harness.root.update()
            geometry = harness.geometry_snapshot()
            if args.capture:
                harness.capture(args.capture)
            print("R6O2_SIDECAR_WINDOW_READY " + json.dumps(geometry, sort_keys=True))
            harness.close()
            return 0
        harness.run()
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
