from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.h2.verify_tui_g06 import PLAN_SHA256, PROMPT_SHA256, RESULT_SHA256, run_qualification


def test_public_tui_g06_process_reaches_closed_success(
    tmp_path: Path,
    baseline_repo: Path,
) -> None:
    evidence = tmp_path / "evidence"
    report = run_qualification(baseline_repo, evidence_dir=evidence)
    assert report["status"] == "MECHANICAL_PASS_PENDING_HUMAN"
    assert report["driver"] == "PUBLIC_PROCESS_STDIN_KEYBOARD_BOUNDARY"
    assert report["observed_screens"] == ["PROMPT REVIEW", "PLAN REVIEW", "REVIEW COMPLETE"]
    assert report["observed_operation_ids"] == [f"G06:000{index}" for index in range(1, 6)]
    assert report["final_stage"] == "CLOSED_SUCCESS"
    assert report["prompt_body_sha256"] == PROMPT_SHA256
    assert report["plan_body_sha256"] == PLAN_SHA256
    assert report["result_body_sha256"] == RESULT_SHA256
    assert report["oracle_inventory_unchanged"] is True

    transitions = [
        json.loads(line)
        for line in (evidence / "state-transitions.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [item["transition_id"] for item in transitions] == [
        "G06-T0-TUI",
        "G06-T1-TUI",
        "G06-T2-TUI",
    ]
    assert [item["stage"] for item in transitions] == [
        "PROMPT_REVIEW",
        "PLAN_REVIEW",
        "CLOSED_SUCCESS",
    ]


def test_terminal_recording_contains_real_input_and_ordered_screens(
    tmp_path: Path,
    baseline_repo: Path,
) -> None:
    evidence = tmp_path / "evidence"
    run_qualification(baseline_repo, evidence_dir=evidence)
    lines = (evidence / "tui-g06.cast").read_text(encoding="utf-8").splitlines()
    header = json.loads(lines[0])
    events = [json.loads(line) for line in lines[1:]]
    assert header["version"] == 2
    assert [event[2] for event in events if event[1] == "i"] == ["\r", "\r"]
    rendered = "".join(event[2] for event in events if event[1] == "o")
    positions = [rendered.index(marker) for marker in ("PROMPT REVIEW", "PLAN REVIEW", "REVIEW COMPLETE")]
    assert positions == sorted(positions)


def test_tui_view_does_not_import_protected_runtime_or_controller_authority() -> None:
    view_source = (Path(__file__).resolve().parents[2] / "views" / "tui" / "app.py").read_text(
        encoding="utf-8"
    ).lower()
    for forbidden in (
        "mechanicalcontroller",
        "mechanical_controller",
        "sessionengine",
        "session_engine",
        "workeradapter",
        "worker_adapter",
        "reviewdecision",
        "review_decision",
        "localruntimemodelbinding",
        "workspace_root",
    ):
        assert forbidden not in view_source


def test_qualification_rejects_evidence_directory_inside_frozen_oracle(
    baseline_repo: Path,
) -> None:
    forbidden = baseline_repo / "h2-b1-evidence-forbidden"
    with pytest.raises(ValueError, match="outside the frozen R6S baseline"):
        run_qualification(baseline_repo, evidence_dir=forbidden)
    assert not forbidden.exists()
