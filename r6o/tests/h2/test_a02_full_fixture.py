from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

import pytest

from scripts.h2.verify_a02_full_fixture import (
    EXPECTED_OPERATIONS,
    MANIFEST_PATH,
    RECORDED_CASE_PATH,
    ReplayMissError,
    StrictReplayWorker,
    record_fixture,
    sha256_text,
    validate_fixture_documents,
    verify_fixture,
)


@dataclass(frozen=True)
class Request:
    operation: str
    prompt: str


def test_a02_full_human_equivalent_replay_reaches_terminal(
    tmp_path: Path,
    baseline_repo: Path,
) -> None:
    report = verify_fixture(baseline_repo, workspace_root=tmp_path / "workspaces")
    assert report["final_stage"] == "CLOSED_SUCCESS"
    assert report["consumed_operation_ids"] == [operation_id for operation_id, _ in EXPECTED_OPERATIONS]
    assert report["oracle_inventory_unchanged"] is True
    assert report["focus_transition"] == {
        "action_id": "something_else",
        "result_type": "FOCUS_REQUIRED",
        "focus_role": "FREE_RESPONSE",
        "worker_call_delta": 0,
        "artifact_unchanged": True,
    }
    assert set(report["artifact_hashes"]) == {
        "initial_prompt_body_sha256",
        "revised_prompt_body_sha256",
        "plan_body_sha256",
        "final_result_body_sha256",
    }


def test_a02_full_manifest_freezes_every_prompt_and_response_hash() -> None:
    recorded = json.loads(RECORDED_CASE_PATH.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert len(recorded["entries"]) == len(manifest["worker_operations"]) == 7
    for entry, frozen in zip(recorded["entries"], manifest["worker_operations"], strict=True):
        assert entry["operation_id"] == frozen["operation_id"]
        assert entry["operation"] == frozen["operation"]
        assert entry["prompt_sha256"] == frozen["prompt_sha256"]
        assert entry["response_sha256"] == frozen["response_sha256"] == sha256_text(entry["response"])


def test_a02_full_replay_fails_closed_on_prompt_miss() -> None:
    recorded = json.loads(RECORDED_CASE_PATH.read_text(encoding="utf-8"))
    worker = StrictReplayWorker(recorded["entries"])
    first = recorded["entries"][0]
    with pytest.raises(ReplayMissError, match="replay mismatch"):
        worker.call(Request(operation=first["operation"], prompt="not the frozen prompt"))


def test_a02_full_replay_fails_closed_on_unconsumed_operation() -> None:
    recorded = json.loads(RECORDED_CASE_PATH.read_text(encoding="utf-8"))
    worker = StrictReplayWorker(recorded["entries"])
    with pytest.raises(ReplayMissError, match="unconsumed fixture operations"):
        worker.assert_fully_consumed()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("model", "manual", "recording metadata A02F:0001.model"),
        ("sandbox_mode", "workspace-write", "recording metadata A02F:0001.sandbox_mode"),
        ("approval_mode", "on-request", "recording metadata A02F:0001.approval_mode"),
    ],
)
def test_a02_full_documents_reject_unapproved_per_operation_provenance(
    field: str,
    value: str,
    message: str,
) -> None:
    recorded_bytes = RECORDED_CASE_PATH.read_bytes()
    recorded = json.loads(recorded_bytes)
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    mutated = deepcopy(recorded)
    mutated["entries"][0]["recording_metadata"][field] = value
    with pytest.raises(AssertionError, match=message):
        validate_fixture_documents(mutated, manifest, recorded_case_bytes=recorded_bytes)


def test_a02_full_documents_reject_non_utc_recording_timestamp() -> None:
    recorded_bytes = RECORDED_CASE_PATH.read_bytes()
    recorded = json.loads(recorded_bytes)
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest["recording_process"]["recorded_at_utc"] = "2026-08-22T23:12:42+01:00"
    with pytest.raises(AssertionError, match="must be UTC"):
        validate_fixture_documents(recorded, manifest, recorded_case_bytes=recorded_bytes)


def test_a02_full_recording_rejects_unapproved_model_before_worker_invocation() -> None:
    with pytest.raises(ValueError, match="recording model must be"):
        record_fixture(None, model="deepseek-v4-flash")
