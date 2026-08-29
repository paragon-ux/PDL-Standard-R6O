from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from scripts.live_parity.inspect_live_modules import import_containment, should_scan
from scripts.live_parity.record import (
    R6O_COMMIT,
    R6O_TREE,
    R6S_COMMIT,
    R6S_TREE,
    canonical_json_bytes,
    physical_inventory,
    required_subsequence,
    sha256_bytes,
    sha256_json,
    sha256_text,
)
from scripts.live_parity.validate import validate_record


def _resume_point(label: str, prompt_id: str, plan_id: str) -> dict[str, Any]:
    return {
        "workspace_path_sha256": sha256_text(f"C:/external/{label}/workspace/{label}"),
        "workspace_id": f"W-{label}",
        "session_or_instance_id": f"I-{label}",
        "controller_state_sha256": sha256_text(f"state-{label}"),
        "prompt": {
            "artifact_id": prompt_id,
            "body_sha256": sha256_text(f"prompt-{label}"),
            "confirmed": False,
        },
        "plan": {
            "artifact_id": plan_id,
            "body_sha256": sha256_text(f"plan-{label}"),
            "confirmed": False,
            "source_prompt_id": prompt_id,
        },
        "pending_change_sha256": None,
        "pending_input_sha256": None,
        "in_flight_action_sha256": None,
    }


def _side(label: str, config_hash: str, lifecycle_matches: bool | None) -> dict[str, Any]:
    operations = [
        "DRAFT_PROMPT",
        "INTERPRET_PROMPT_REVIEW",
        "REVISE_PROMPT",
        "DRAFT_PLAN",
        "INTERPRET_PLAN_REVIEW",
        "REVISE_PLAN",
        "EXECUTE",
    ]
    prompt_before = _resume_point(label, f"P-{label}-old", f"R-{label}-before")
    prompt_after = deepcopy(prompt_before)
    prompt_after["prompt"].update({
        "artifact_id": f"P-{label}-new",
        "body_sha256": sha256_text(f"prompt-{label}-corrected"),
    })
    prompt_after["plan"]["source_prompt_id"] = f"P-{label}-new"
    plan_before = _resume_point(label, f"P-{label}-new", f"R-{label}-old")
    plan_after = deepcopy(plan_before)
    plan_after["plan"].update({
        "artifact_id": f"R-{label}-new",
        "body_sha256": sha256_text(f"plan-{label}-corrected"),
    })
    resume_before = deepcopy(plan_after)
    resume_after = deepcopy(plan_after)
    return {
        "session_id": f"I-{label}",
        "workspace_id": f"W-{label}",
        "worker_metadata": {
            "implementation": "providers.codex_worker.CodexWorker",
            "requested_model": "deepseek-v4-flash",
            "observed_model": "deepseek-v4-flash",
            "provider": "codex",
            "runtime_version": "codex 1",
            "configuration_sha256": config_hash,
            "live_worker": True,
            "recorded_or_stub": False,
        },
        "operations": operations,
        "required_operation_subsequence_observed": True,
        "prompt_correction": {
            "observed_intent": "REVISE_TASK",
            "observed_next_action": "REVISE_PROMPT",
            "artifact_id_before": prompt_before["prompt"]["artifact_id"],
            "artifact_id_after": prompt_after["prompt"]["artifact_id"],
            "body_sha256_before": prompt_before["prompt"]["body_sha256"],
            "body_sha256_after": prompt_after["prompt"]["body_sha256"],
            "body_changed": True,
            "persisted": True,
            "route_valid": True,
        },
        "plan_correction": {
            "observed_intent": "REVISE_APPROACH",
            "observed_next_action": "REVISE_PLAN",
            "artifact_id_before": plan_before["plan"]["artifact_id"],
            "artifact_id_after": plan_after["plan"]["artifact_id"],
            "body_sha256_before": plan_before["plan"]["body_sha256"],
            "body_sha256_after": plan_after["plan"]["body_sha256"],
            "body_changed": True,
            "persisted": True,
            "route_valid": True,
        },
        "resume": {
            "before": resume_before,
            "after": resume_after,
            "same_workspace_path": True,
            "same_workspace_id": True,
            "same_session_or_instance": True,
            "controller_state_equal": True,
            "prompt_equal": True,
            "plan_equal": True,
            "pending_state_equal": True,
            "replacement_workspace_created": False,
            "public_semantic_state_equivalent": None if label == "r6s" else True,
        },
        "execution_continuation": {
            "disposition": "NOT_REQUESTED",
            "request_input_observed": False,
            "input_supplied": False,
            "interpret_execution_input_observed": False,
            "subsequent_execute_observed": False,
            "result_reached": True,
        },
        "result": {
            "execution_kind": "RESULT",
            "current_json_exists": True,
            "current_md_exists": True,
            "body_nonempty": True,
            "body_sha256": sha256_text(f"result-{label}"),
            "lifecycle_result_matches_persisted": lifecycle_matches,
        },
        "capabilities": {name: True for name in (
            "fresh_session_created", "fresh_workspace_created", "live_worker_observed",
            "prompt_review_reached", "prompt_task_change_classified", "prompt_revision_route_observed",
            "prompt_correction_persisted", "prompt_confirmation_progressed", "plan_review_reached",
            "plan_approach_change_classified", "plan_revision_route_observed", "plan_correction_persisted",
            "resume_checkpoint_preserved", "plan_confirmation_progressed", "execute_reached",
            "execution_continuation_supported_if_requested", "result_persisted", "terminal_success",
            "historical_case_dependency_absent", "historical_evidence_dependency_absent",
            "recorded_worker_dependency_absent", "source_repo_unchanged", "host_crash_absent",
        )},
        "source_git_clean_after": True,
        "source_physical_inventory_equal": True,
    }


def _valid_record(run_root: Path) -> dict[str, Any]:
    private = run_root / "private-inputs"
    private.mkdir(parents=True)
    inputs = {
        "task.txt": b"An arbitrary qualification task.\n",
        "prompt-correction.txt": b"Change the task audience.\n",
        "plan-correction.txt": b"Use a decision matrix first.\n",
    }
    for name, data in inputs.items():
        (private / name).write_bytes(data)
    preimage = {
        "implementation": "providers.codex_worker.CodexWorker",
        "requested_model": "deepseek-v4-flash",
        "sandbox_mode": "read-only",
        "approval_policy": "never",
        "dangerous_bypass": False,
        "timeout_seconds": 30.0,
        "capture_tokens": True,
        "json_mode": True,
        "worker_workdir_policy": "separate external per-side workdir",
    }
    (private / "worker-config.json").write_bytes(canonical_json_bytes(preimage))
    config_hash = sha256_json(preimage)
    for label in ("r6s", "r6o"):
        output = run_root / label / "workspace" / f"W-{label}" / "stages" / "50_execution" / "output"
        output.mkdir(parents=True)
        (output / "current.json").write_text(json.dumps({"kind": "RESULT"}), encoding="utf-8")
        (output / "current.md").write_text(f"result-{label}", encoding="utf-8")
    baseline_hashes = {label: sha256_text(f"{label}-inventory") for label in ("r6s", "r6o")}
    return {
        "schema_version": "pdl-live-functional-parity-record-2",
        "run_id": "test-run",
        "baselines": {
            "r6s": {
                "repository": "paragon-ux/PDL-Standard-REPL-Harness", "commit": R6S_COMMIT, "tree": R6S_TREE,
                "git_clean_before": True, "git_clean_after": True,
                "physical_inventory_before_sha256": baseline_hashes["r6s"],
                "physical_inventory_after_sha256": baseline_hashes["r6s"], "physical_inventory_equal": True,
            },
            "r6o": {
                "repository": "paragon-ux/PDL-Standard-R6O", "commit": R6O_COMMIT, "tree": R6O_TREE,
                "git_clean_before": True, "git_clean_after": True,
                "physical_inventory_before_sha256": baseline_hashes["r6o"],
                "physical_inventory_after_sha256": baseline_hashes["r6o"], "physical_inventory_equal": True,
            },
        },
        "input_attestation": {
            "task_sha256": sha256_bytes(inputs["task.txt"]),
            "prompt_correction_sha256": sha256_bytes(inputs["prompt-correction.txt"]),
            "plan_correction_sha256": sha256_bytes(inputs["plan-correction.txt"]),
            "task_evidence_path": "private-inputs/task.txt",
            "prompt_correction_evidence_path": "private-inputs/prompt-correction.txt",
            "plan_correction_evidence_path": "private-inputs/plan-correction.txt",
            "private_input_evidence_retained": True, "prompt_correction_class": "TASK_CHANGE",
            "plan_correction_class": "APPROACH_ONLY", "runtime_supplied": True,
            "same_inputs_both_sides": True, "historical_case_id_supplied": False,
            "historical_evidence_supplied": False, "expected_output_supplied": False,
            "recorded_worker_supplied": False,
        },
        "worker_configuration": {
            "implementation": preimage["implementation"], "requested_model": preimage["requested_model"],
            "configuration_sha256": config_hash, "same_configuration_both_sides": True,
            "real_live_worker": True, "recorded_or_stub_worker": False, "bypass_state": "disabled",
            "bypass_exception_rationale": None,
        },
        "anti_hardcode": {
            "r6s": {"scanned_module_count": 1, "scanned_paths": ["r6s/host/app.py"],
                    "g06_matches": 0, "a02_matches": 0, "rdx_case_matches": 0,
                    "recorded_fixture_path_matches": 0, "historical_evidence_path_matches": 0,
                    "expected_output_routing_matches": 0, "recorded_provider_live_import_matches": 0,
                    "matched_locations": []},
            "r6o": {"scanned_module_count": 1, "scanned_paths": ["r6o/r6o/model_binding/local_runtime.py"],
                    "g06_matches": 0, "a02_matches": 0, "rdx_case_matches": 0,
                    "recorded_fixture_path_matches": 0, "historical_evidence_path_matches": 0,
                    "expected_output_routing_matches": 0, "recorded_provider_live_import_matches": 0,
                    "matched_locations": []},
        },
        "r6s": _side("r6s", config_hash, None),
        "r6o": _side("r6o", config_hash, True),
        "parity": {
            "required_capabilities_pass_both": True, "same_input_hashes": True,
            "same_worker_configuration": True, "anti_hardcode_pass_both": True,
            "source_read_only_pass_both": True, "generated_text_equality_required": False,
        },
        "status": "PASS",
    }


def test_valid_record_passes_structural_and_semantic_validation(tmp_path: Path) -> None:
    record = _valid_record(tmp_path)
    structural, semantic = validate_record(record, tmp_path)
    assert structural == []
    assert semantic == []


@pytest.mark.parametrize("mutate", [
    lambda record: record["baselines"]["r6s"].update({
        "physical_inventory_after_sha256": sha256_text("different")}),
    lambda record: record["r6s"]["prompt_correction"].update({
        "body_sha256_after": record["r6s"]["prompt_correction"]["body_sha256_before"]}),
    lambda record: record["r6s"]["prompt_correction"].update({"observed_next_action": "REVISE_PLAN"}),
    lambda record: record["r6s"].update({"operations": ["DRAFT_PROMPT" ]}),
    lambda record: record["r6s"]["resume"]["after"].update({
        "controller_state_sha256": sha256_text("different-state")}),
    lambda record: record["r6o"]["resume"]["after"]["plan"].update({"source_prompt_id": "P-other"}),
    lambda record: record["r6o"]["worker_metadata"].update({"configuration_sha256": sha256_text("other")}),
    lambda record: record["parity"].update({"same_input_hashes": False}),
    lambda record: record["r6o"]["capabilities"].update({"result_persisted": False}),
])
def test_semantic_validator_rejects_contradictory_pass_records(
    tmp_path: Path, mutate: Callable[[dict[str, Any]], None]
) -> None:
    record = _valid_record(tmp_path)
    mutate(record)
    structural, semantic = validate_record(record, tmp_path)
    assert structural or semantic


def test_input_alias_is_rejected_by_schema_and_semantic_validator(tmp_path: Path) -> None:
    record = _valid_record(tmp_path)
    record["input_attestation"]["task_evidence_path"] = "private/task.txt"
    structural, semantic = validate_record(record, tmp_path)
    assert any("task_evidence_path" in finding for finding in structural + semantic)


def test_requested_continuation_cannot_claim_incomplete_pass(tmp_path: Path) -> None:
    record = _valid_record(tmp_path)
    record["r6s"]["execution_continuation"] = {
        "disposition": "REQUESTED_INCOMPLETE", "request_input_observed": True,
        "input_supplied": False, "interpret_execution_input_observed": False,
        "subsequent_execute_observed": False, "result_reached": False,
    }
    structural, semantic = validate_record(record, tmp_path)
    assert structural or semantic


def test_containment_rejects_production_module_from_gate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    gate = tmp_path / "gate"
    module_path = gate / "r6o" / "model_binding" / "fake.py"
    monkeypatch.setitem(sys.modules, "r6o.fake_gate", SimpleNamespace(__file__=str(module_path)))
    violations = import_containment(
        "r6o", r6o_root=tmp_path / "control", r6s_root=tmp_path / "r6s", gate_root=gate
    )
    assert any("r6o.fake_gate" in violation and "not-r6o-control" in violation for violation in violations)


@pytest.mark.parametrize("relative", ["tests/test_x.py", "docs/readme.md", "fixtures/recorded.json", "evidence/run.json"])
def test_bounded_scanner_excludes_nonproduction_paths(relative: str) -> None:
    assert should_scan(relative) is False


def test_inventory_digest_changes_with_file_content(tmp_path: Path) -> None:
    target = tmp_path / "source.txt"
    target.write_text("before", encoding="utf-8")
    first, _ = physical_inventory(tmp_path)
    target.write_text("after", encoding="utf-8")
    second, _ = physical_inventory(tmp_path)
    assert first != second


def test_required_subsequence_is_ordered() -> None:
    assert required_subsequence(["DRAFT_PROMPT", "INTERPRET_PROMPT_REVIEW", "REVISE_PROMPT",
                                 "DRAFT_PLAN", "INTERPRET_PLAN_REVIEW", "REVISE_PLAN", "EXECUTE"])
    assert not required_subsequence(["DRAFT_PROMPT", "REVISE_PROMPT", "INTERPRET_PROMPT_REVIEW"])
