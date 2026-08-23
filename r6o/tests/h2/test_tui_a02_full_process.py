from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.h2.verify_a02_full_fixture import REVISION_TEXT
from scripts.h2.verify_tui_a02_full import (
    EXPECTED_TRANSITIONS,
    INITIAL_PROMPT_SHA256,
    PLAN_SHA256,
    RESULT_SHA256,
    REVISED_PROMPT_SHA256,
    run_qualification,
    verify_state_log,
)


def test_public_tui_a02_full_process_completes_without_restart(
    tmp_path: Path,
    baseline_repo: Path,
) -> None:
    evidence = tmp_path / "evidence"
    report = run_qualification(baseline_repo, evidence_dir=evidence)

    assert report["status"] == "MECHANICAL_PASS_PENDING_HUMAN"
    assert report["driver"] == "PUBLIC_PROCESS_STDIN_KEYBOARD_BOUNDARY"
    assert report["free_response_source"] == "TUI_TEXT"
    assert report["free_response_submission_count"] == 1
    assert report["observed_screens"] == [
        "PROMPT REVIEW INITIAL",
        "PROMPT REVIEW REVISED",
        "PLAN REVIEW",
    ]
    assert report["terminal_behavior"] == "RESTORE_AND_RETURN_WITHOUT_RELAUNCH"
    assert report["observed_operation_ids"] == [f"A02F:000{index}" for index in range(1, 8)]
    assert report["final_stage"] == "CLOSED_SUCCESS"
    assert report["artifact_body_sha256"] == {
        "initial_prompt": INITIAL_PROMPT_SHA256,
        "revised_prompt": REVISED_PROMPT_SHA256,
        "plan": PLAN_SHA256,
        "result": RESULT_SHA256,
    }
    assert report["oracle_inventory_unchanged"] is True

    records = [
        json.loads(line)
        for line in (evidence / "state-transitions.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [record["transition_id"] for record in records] == [item[0] for item in EXPECTED_TRANSITIONS]
    assert records[1]["worker_operations"] == []
    assert records[1]["artifact_body_sha256"] == records[0]["artifact_body_sha256"]


def test_terminal_recording_contains_exact_human_keyboard_flow(
    tmp_path: Path,
    baseline_repo: Path,
) -> None:
    evidence = tmp_path / "evidence"
    run_qualification(baseline_repo, evidence_dir=evidence)
    lines = (evidence / "tui-a02-full.cast").read_text(encoding="utf-8").splitlines()
    events = [json.loads(line) for line in lines[1:]]
    inputs = [event[2] for event in events if event[1] == "i"]

    assert inputs == ["\t\t\t", "\r", REVISION_TEXT, "\r", "\r", "\r"]
    rendered = "".join(event[2] for event in events if event[1] == "o")
    assert rendered.count("PDLt · PROMPT REVIEW") > 1
    assert "event delivery for an audience of data" in rendered
    assert "PDLt · PLAN REVIEW" in rendered
    assert "ReplayMissError" not in rendered
    assert "R6O TUI PASS: CLOSED_SUCCESS" in rendered


def test_public_runner_has_no_hidden_a02_review_submission() -> None:
    runner = (Path(__file__).resolve().parents[3] / "scripts" / "run_r6o2_tui.py").read_text(
        encoding="utf-8"
    )
    assert REVISION_TEXT not in runner
    assert "--case" in runner
    assert "A02-FULL" in runner


def test_b2_state_log_verifier_rejects_focus_worker_call() -> None:
    records = []
    for expected in EXPECTED_TRANSITIONS:
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
        records.append(
            {
                "schema_version": "r6o-h2-b2-state-transition-1",
                "transition_id": transition_id,
                "state_id": state_id,
                "stage": stage,
                "action_id": action_id,
                "input_envelope_source": envelope_source,
                "worker_operations": [
                    {"operation_id": operation_id, "operation": "DRAFT_PROMPT"}
                    for operation_id in operation_ids
                ],
                "artifact_kind": artifact_kind,
                "artifact_body_sha256": artifact_hash,
                "focus_owner": focus_owner,
                "terminal_disposition": "HOST_HANDOFF" if stage == "CLOSED_SUCCESS" else None,
            }
        )
    records[1]["worker_operations"] = [{"operation_id": "A02F:0002", "operation": "DRAFT_PROMPT"}]
    with pytest.raises(AssertionError, match="worker operation IDs differ"):
        verify_state_log(records)


def test_qualification_rejects_evidence_inside_frozen_oracle(baseline_repo: Path) -> None:
    forbidden = baseline_repo / "h2-b2-evidence-forbidden"
    with pytest.raises(ValueError, match="outside the frozen R6S baseline"):
        run_qualification(baseline_repo, evidence_dir=forbidden)
    assert not forbidden.exists()
