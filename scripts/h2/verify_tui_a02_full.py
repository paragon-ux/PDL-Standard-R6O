from __future__ import annotations

"""Process-level H2-B2 qualification for the public A02-FULL TUI."""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.h2.verify_a02_full_fixture import REVISION_TEXT
from scripts.h2.verify_tui_g06 import (
    FROZEN_ORACLE_COMMIT,
    FROZEN_ORACLE_TREE,
    ProcessKeyboardDriver,
    is_within,
    physical_inventory,
    resolve_baseline,
    write_cast,
)


RUNNER = ROOT / "scripts" / "run_r6o2_tui.py"
DEFAULT_EVIDENCE_DIR = ROOT / "r6o_evidence" / "H2-B2"
INITIAL_PROMPT_SHA256 = "dba4f08e0a47d995ac2a76439c1f4a7d2da61a50a8f3147f08b558944446af9c"
REVISED_PROMPT_SHA256 = "03a174f24f155f0b171b7cb922db60342b040022c329a0693f65bfd97da62e4a"
PLAN_SHA256 = "0598f12fb2ac853b161f0690913dd90ae1ce041803e71f4133661fb276443a68"
RESULT_SHA256 = "79cd3ac621e54343d4cbef28229766f2c8ae4b5e694dc46b7d69b9375f7e35c4"
EXPECTED_OPERATIONS = {
    f"A02F:000{index}": operation
    for index, operation in enumerate(
        (
            "DRAFT_PROMPT",
            "INTERPRET_PROMPT_REVIEW",
            "REVISE_PROMPT",
            "INTERPRET_PROMPT_REVIEW",
            "DRAFT_PLAN",
            "INTERPRET_PLAN_REVIEW",
            "EXECUTE",
        ),
        start=1,
    )
}
EXPECTED_TRANSITIONS = (
    (
        "A02-T0-TUI", "A02-S1", "PROMPT_REVIEW", None, None,
        ("A02F:0001",), "prompt", INITIAL_PROMPT_SHA256, "TUI_ACTION_CONFIRM_PROMPT",
    ),
    (
        "A02-T1-FOCUS-TUI", "A02-S1", "PROMPT_REVIEW", "something_else", "STRUCTURED_ACTION",
        (), "prompt", INITIAL_PROMPT_SHA256, "TUI_FREE_RESPONSE_INPUT",
    ),
    (
        "A02-T2-REVISE-TUI", "A02-S2", "PROMPT_REVIEW", None, "TUI_TEXT",
        ("A02F:0002", "A02F:0003"), "prompt", REVISED_PROMPT_SHA256, "TUI_ACTION_CONFIRM_PROMPT",
    ),
    (
        "A02-T3-TUI", "A02-S3", "PLAN_REVIEW", "confirm_prompt", "STRUCTURED_ACTION",
        ("A02F:0004", "A02F:0005"), "plan", PLAN_SHA256, "TUI_ACTION_CONFIRM_PLAN",
    ),
    (
        "A02-T4-TUI", "A02-S4", "CLOSED_SUCCESS", "confirm_plan", "STRUCTURED_ACTION",
        ("A02F:0006", "A02F:0007"), None, None, "CALLING_SHELL",
    ),
)


def load_state_log(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = json.loads(line)
        if not isinstance(value, dict):
            raise AssertionError("state transition line must be a JSON object")
        records.append(value)
    return records


def verify_state_log(records: list[dict[str, Any]]) -> None:
    if len(records) != len(EXPECTED_TRANSITIONS):
        raise AssertionError(f"expected five A02-FULL transitions, got {len(records)}")
    observed_ids: list[str] = []
    for record, expected in zip(records, EXPECTED_TRANSITIONS, strict=True):
        (
            transition_id,
            state_id,
            stage,
            action_id,
            envelope_source,
            operation_ids,
            artifact_kind,
            artifact_hash,
            focus_owner,
        ) = expected
        actual = (
            record.get("transition_id"),
            record.get("state_id"),
            record.get("stage"),
            record.get("action_id"),
            record.get("input_envelope_source"),
            record.get("artifact_kind"),
            record.get("artifact_body_sha256"),
            record.get("focus_owner"),
        )
        wanted = (
            transition_id,
            state_id,
            stage,
            action_id,
            envelope_source,
            artifact_kind,
            artifact_hash,
            focus_owner,
        )
        if record.get("schema_version") != "r6o-h2-b2-state-transition-1" or actual != wanted:
            raise AssertionError(f"A02-FULL state transition differs at {transition_id}: {actual}")
        operations = record.get("worker_operations")
        if not isinstance(operations, list):
            raise AssertionError(f"worker_operations must be a list at {transition_id}")
        actual_operation_ids = tuple(item.get("operation_id") for item in operations)
        if actual_operation_ids != operation_ids:
            raise AssertionError(
                f"worker operation IDs differ at {transition_id}: {actual_operation_ids}"
            )
        for item in operations:
            if set(item) != {"operation_id", "operation"}:
                raise AssertionError(f"worker operation fields differ at {transition_id}")
            if item["operation"] != EXPECTED_OPERATIONS[item["operation_id"]]:
                raise AssertionError(f"worker operation name differs at {item['operation_id']}")
        observed_ids.extend(actual_operation_ids)
    if observed_ids != list(EXPECTED_OPERATIONS):
        raise AssertionError("A02-FULL operations were not observed exactly once in order")
    focus = records[1]
    if focus["worker_operations"] or focus["artifact_body_sha256"] != INITIAL_PROMPT_SHA256:
        raise AssertionError("FREE_RESPONSE_FOCUS changed semantics or the Prompt artifact")
    terminal = records[-1]
    if terminal.get("terminal_disposition") != "HOST_HANDOFF":
        raise AssertionError("terminal disposition is not HOST_HANDOFF")
    if terminal.get("authorized_artifact_hashes") != {
        "prompt": REVISED_PROMPT_SHA256,
        "plan": PLAN_SHA256,
    }:
        raise AssertionError("terminal revised Prompt/Plan hashes differ")
    if terminal.get("result_body_sha256") != RESULT_SHA256:
        raise AssertionError("terminal result hash differs")


def run_qualification(
    baseline_repo: Path | None = None,
    *,
    evidence_dir: Path = DEFAULT_EVIDENCE_DIR,
) -> dict[str, Any]:
    baseline = resolve_baseline(baseline_repo)
    oracle_before = physical_inventory(baseline)
    evidence = evidence_dir.resolve()
    if is_within(evidence, baseline):
        raise ValueError("evidence directory must be outside the frozen R6S baseline")
    evidence.mkdir(parents=True, exist_ok=True)
    state_log = evidence / "state-transitions.jsonl"
    cast_path = evidence / "tui-a02-full.cast"
    results_path = evidence / "test-results.json"
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    with tempfile.TemporaryDirectory(prefix="pdl-h2-b2-") as temporary:
        command = [
            sys.executable,
            str(RUNNER),
            "--recorded",
            "--case",
            "A02-FULL",
            "--baseline-repo",
            str(baseline),
            "--workspace-root",
            str(Path(temporary) / "workspaces"),
            "--state-log",
            str(state_log),
        ]
        driver = ProcessKeyboardDriver(command, cwd=ROOT, environment=environment)
        try:
            initial = driver.wait_for("PDLt · PROMPT REVIEW")
            driver.wait_for("COMPARE Kafka and RabbitMQ for event delivery.", after=initial)
            driver.wait_for("> 1  Confirm prompt", after=initial)
            driver.send_keys("\t\t\t")
            focused_action = driver.wait_for("> 4  Something else...", after=initial + 1)
            driver.press_enter()
            editor = driver.wait_for("Review > ", after=focused_action)
            driver.send_keys(REVISION_TEXT)
            driver.press_enter()
            revised = driver.wait_for(
                "event delivery for an audience of data",
                after=editor,
                timeout=10.0,
            )
            driver.wait_for("> 1  Confirm prompt", after=revised)
            driver.press_enter()
            plan = driver.wait_for("PDLt · PLAN REVIEW", after=revised)
            driver.wait_for("IDENTIFY comparison criteria relevant to event delivery", after=plan)
            driver.wait_for("> 1  Confirm plan", after=plan)
            driver.press_enter()
            returncode, transcript = driver.finish()
        finally:
            driver.stop()
    if returncode != 0:
        raise AssertionError(f"public A02-FULL TUI exited {returncode}:\n{transcript}")
    if "R6O TUI PASS: CLOSED_SUCCESS" not in transcript:
        raise AssertionError("public runner did not report CLOSED_SUCCESS")
    if "ReplayMissError" in transcript:
        raise AssertionError("public A02-FULL TUI encountered ReplayMissError")
    records = load_state_log(state_log)
    verify_state_log(records)
    if physical_inventory(baseline) != oracle_before:
        raise AssertionError("frozen R6S oracle physical inventory changed")
    write_cast(cast_path, driver.cast_events())
    report = {
        "schema_version": "r6o-h2-b2-test-results-1",
        "gate": "H2-B2",
        "status": "MECHANICAL_PASS_PENDING_HUMAN",
        "driver": "PUBLIC_PROCESS_STDIN_KEYBOARD_BOUNDARY",
        "public_command": "python scripts\\run_r6o2_tui.py --recorded --case A02-FULL",
        "free_response_source": "TUI_TEXT",
        "free_response_submission_count": 1,
        "observed_screens": ["PROMPT REVIEW INITIAL", "PROMPT REVIEW REVISED", "PLAN REVIEW"],
        "terminal_behavior": "RESTORE_AND_RETURN_WITHOUT_RELAUNCH",
        "observed_operation_ids": list(EXPECTED_OPERATIONS),
        "final_stage": "CLOSED_SUCCESS",
        "artifact_body_sha256": {
            "initial_prompt": INITIAL_PROMPT_SHA256,
            "revised_prompt": REVISED_PROMPT_SHA256,
            "plan": PLAN_SHA256,
            "result": RESULT_SHA256,
        },
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
    print(json.dumps(run_qualification(args.baseline_repo, evidence_dir=args.evidence_dir), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
