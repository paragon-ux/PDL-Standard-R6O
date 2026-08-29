from __future__ import annotations

"""Structural and deterministic cross-field validation for current runs."""

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from .record import R6O_COMMIT, R6O_TREE, R6S_COMMIT, R6S_TREE, sha256_bytes, sha256_file, sha256_json, sha256_text, required_subsequence
    from .inspect_live_modules import validate_external_artifacts
except ImportError:  # Direct execution: python scripts/live_parity/validate.py
    from record import R6O_COMMIT, R6O_TREE, R6S_COMMIT, R6S_TREE, sha256_bytes, sha256_file, sha256_json, sha256_text, required_subsequence
    from inspect_live_modules import validate_external_artifacts


SCHEMA_PATH = Path(__file__).resolve().parent / "schema" / "live-functional-parity-record.schema.json"
CAPABILITY_NAMES = (
    "fresh_session_created",
    "fresh_workspace_created",
    "live_worker_observed",
    "prompt_review_reached",
    "prompt_task_change_classified",
    "prompt_revision_route_observed",
    "prompt_correction_persisted",
    "prompt_confirmation_progressed",
    "plan_review_reached",
    "plan_approach_change_classified",
    "plan_revision_route_observed",
    "plan_correction_persisted",
    "resume_checkpoint_preserved",
    "plan_confirmation_progressed",
    "execute_reached",
    "execution_continuation_supported_if_requested",
    "result_persisted",
    "terminal_success",
    "historical_case_dependency_absent",
    "historical_evidence_dependency_absent",
    "recorded_worker_dependency_absent",
    "source_repo_unchanged",
    "host_crash_absent",
)


def structural_findings(record: dict[str, Any], schema_path: str | Path = SCHEMA_PATH) -> list[str]:
    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:
        return [f"environment dependency missing: jsonschema ({exc})"]
    try:
        schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(record), key=lambda item: list(item.absolute_path))
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        return [f"schema load/validation error: {exc}"]
    findings: list[str] = []
    for error in errors:
        location = "/".join(str(part) for part in error.absolute_path) or "$"
        findings.append(f"{location}: {error.message}")
    return findings


def _same(left: Any, right: Any) -> bool:
    return left == right


def _workspace_output(run_root: Path, label: str) -> Path | None:
    workspace_root = run_root / label / "workspace"
    candidates = sorted(
        path for path in workspace_root.glob("W-*") if path.is_dir() and (path / "stages").is_dir()
    )
    if len(candidates) != 1:
        return None
    return candidates[0] / "stages" / "50_execution" / "output"


def _result_facts(run_root: Path, label: str, result: dict[str, Any], findings: list[str]) -> bool:
    output = _workspace_output(run_root, label)
    current_json = output / "current.json" if output else None
    current_md = output / "current.md" if output else None
    json_exists = bool(current_json and current_json.is_file())
    md_exists = bool(current_md and current_md.is_file())
    metadata: dict[str, Any] = {}
    body = ""
    if json_exists:
        try:
            loaded = json.loads(current_json.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                metadata = loaded
        except (OSError, json.JSONDecodeError):
            findings.append(f"{label}.result: current.json is not valid JSON")
    if md_exists:
        try:
            body = current_md.read_text(encoding="utf-8").rstrip("\n")
        except (OSError, UnicodeError):
            findings.append(f"{label}.result: current.md is unreadable")
    body_hash = sha256_text(body) if body else None
    expected = {
        "current_json_exists": json_exists,
        "current_md_exists": md_exists,
        "body_nonempty": bool(body),
        "body_sha256": body_hash,
    }
    for field, actual in expected.items():
        if result.get(field) != actual:
            findings.append(f"{label}.result.{field}: record={result.get(field)!r}, observed={actual!r}")
    recorded_kind = result.get("execution_kind")
    observed_kind = metadata.get("kind") if metadata else None
    if json_exists and recorded_kind != observed_kind:
        findings.append(f"{label}.result.execution_kind: record={recorded_kind!r}, persisted={observed_kind!r}")
    return bool(json_exists and md_exists and observed_kind == "RESULT" and body)


def _input_findings(record: dict[str, Any], run_root: Path, findings: list[str]) -> bool:
    attestation = record.get("input_attestation")
    if not isinstance(attestation, dict):
        findings.append("input_attestation: missing object")
        return False
    valid = True
    expected_paths = {
        "task_evidence_path": "private-inputs/task.txt",
        "prompt_correction_evidence_path": "private-inputs/prompt-correction.txt",
        "plan_correction_evidence_path": "private-inputs/plan-correction.txt",
    }
    for hash_field, path_field in (
        ("task_sha256", "task_evidence_path"),
        ("prompt_correction_sha256", "prompt_correction_evidence_path"),
        ("plan_correction_sha256", "plan_correction_evidence_path"),
    ):
        relative = attestation.get(path_field)
        if relative != expected_paths[path_field]:
            findings.append(f"{path_field}: must equal canonical {expected_paths[path_field]!r}")
            valid = False
            continue
        candidate = (run_root / relative).resolve()
        private_root = (run_root / "private-inputs").resolve()
        if candidate == private_root or not candidate.is_relative_to(private_root) or not candidate.is_file():
            findings.append(f"{path_field}: retained input is missing or escapes private-inputs")
            valid = False
            continue
        actual = sha256_file(candidate)
        if actual != attestation.get(hash_field):
            findings.append(f"{path_field}: retained bytes do not match {hash_field}")
            valid = False
    if attestation.get("runtime_supplied") is not True:
        findings.append("input_attestation.runtime_supplied must be true for a live run")
        valid = False
    if attestation.get("same_inputs_both_sides") is not True:
        findings.append("input_attestation.same_inputs_both_sides must be true")
        valid = False
    for field in (
        "historical_case_id_supplied",
        "historical_evidence_supplied",
        "expected_output_supplied",
        "recorded_worker_supplied",
    ):
        if attestation.get(field) is not False:
            findings.append(f"input_attestation.{field} must be false")
            valid = False
    if attestation.get("private_input_evidence_retained") is not True:
        findings.append("input_attestation.private_input_evidence_retained must be true")
        valid = False
    return valid


def _worker_findings(record: dict[str, Any], run_root: Path, findings: list[str]) -> bool:
    config = record.get("worker_configuration")
    if not isinstance(config, dict):
        findings.append("worker_configuration: missing object")
        return False
    config_path = run_root / "private-inputs" / "worker-config.json"
    valid = config_path.is_file()
    if not valid:
        findings.append("worker_configuration: private-inputs/worker-config.json is missing")
    else:
        raw = config_path.read_bytes()
        digest = config.get("configuration_sha256")
        if sha256_bytes(raw) != digest:
            findings.append("worker_configuration.configuration_sha256 does not match retained preimage bytes")
            valid = False
        try:
            preimage = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            findings.append(f"worker_configuration preimage is invalid: {exc}")
            preimage = None
        if isinstance(preimage, dict) and sha256_json(preimage) != digest:
            findings.append("worker_configuration.configuration_sha256 does not recompute from preimage")
            valid = False
        if isinstance(preimage, dict):
            for field in ("implementation", "requested_model"):
                if preimage.get(field) != config.get(field):
                    findings.append(f"worker_configuration.{field} does not match preimage")
                    valid = False
    r6s = record.get("r6s", {})
    r6o = record.get("r6o", {})
    r6s_meta = r6s.get("worker_metadata", {}) if isinstance(r6s, dict) else {}
    r6o_meta = r6o.get("worker_metadata", {}) if isinstance(r6o, dict) else {}
    matching = all(
        r6s_meta.get(field) == r6o_meta.get(field) == config.get(field)
        for field in ("implementation", "requested_model", "configuration_sha256")
    )
    if config.get("same_configuration_both_sides") != matching:
        findings.append("worker configuration parity flag contradicts side metadata")
        valid = False
    for field in ("same_configuration_both_sides", "real_live_worker"):
        if config.get(field) is not True:
            findings.append(f"worker_configuration.{field} must be true")
            valid = False
    if config.get("recorded_or_stub_worker") is not False:
        findings.append("worker_configuration.recorded_or_stub_worker must be false")
        valid = False
    if config.get("bypass_state") == "disabled" and config.get("bypass_exception_rationale") is not None:
        findings.append("disabled bypass must not carry an exception rationale")
        valid = False
    for label, side in (("r6s", r6s), ("r6o", r6o)):
        meta = side.get("worker_metadata", {}) if isinstance(side, dict) else {}
        if meta.get("configuration_sha256") != config.get("configuration_sha256"):
            findings.append(f"{label}.worker_metadata.configuration_sha256 does not match top-level configuration")
            valid = False
        if meta.get("live_worker") is not True or meta.get("recorded_or_stub") is not False:
            findings.append(f"{label}.worker_metadata is not a real live worker")
            valid = False
    return valid and matching


def _correction_findings(
    label: str,
    name: str,
    correction: dict[str, Any],
    intent: str,
    action: str,
    findings: list[str],
    strict: bool,
) -> bool:
    before_hash = correction.get("body_sha256_before")
    after_hash = correction.get("body_sha256_after")
    body_changed = before_hash != after_hash
    if correction.get("body_changed") != body_changed:
        findings.append(f"{label}.{name}.body_changed contradicts body hashes")
    route = correction.get("observed_intent") == intent and correction.get("observed_next_action") == action
    if correction.get("route_valid") != route:
        findings.append(f"{label}.{name}.route_valid contradicts observed route")
    if strict and not route:
        findings.append(f"{label}.{name}: required route {intent} -> {action} was not observed")
    if strict and not body_changed:
        findings.append(f"{label}.{name}: correction body did not change")
    if strict and correction.get("artifact_id_before") == correction.get("artifact_id_after"):
        findings.append(f"{label}.{name}: artifact identity did not change")
    if strict and correction.get("persisted") is not True:
        findings.append(f"{label}.{name}: corrected artifact was not persisted")
    return bool(route and body_changed and correction.get("persisted") is True and correction.get("artifact_id_before") != correction.get("artifact_id_after"))


def _resume_findings(label: str, side: dict[str, Any], findings: list[str], strict: bool) -> bool:
    resume = side.get("resume", {})
    before = resume.get("before", {})
    after = resume.get("after", {})
    comparisons = {
        "same_workspace_path": _same(before.get("workspace_path_sha256"), after.get("workspace_path_sha256")),
        "same_workspace_id": _same(before.get("workspace_id"), after.get("workspace_id")),
        "same_session_or_instance": _same(before.get("session_or_instance_id"), after.get("session_or_instance_id")),
        "controller_state_equal": _same(before.get("controller_state_sha256"), after.get("controller_state_sha256")),
        "prompt_equal": _same(before.get("prompt"), after.get("prompt")),
        "plan_equal": _same(before.get("plan"), after.get("plan")),
        "pending_state_equal": all(
            _same(before.get(field), after.get(field))
            for field in ("pending_change_sha256", "pending_input_sha256", "in_flight_action_sha256")
        ),
    }
    valid = True
    for field, expected in comparisons.items():
        if resume.get(field) != expected:
            findings.append(f"{label}.resume.{field} contradicts before/after evidence")
            valid = False
        if strict and not expected:
            findings.append(f"{label}.resume.{field} is not preserved")
    if resume.get("replacement_workspace_created") is not False:
        findings.append(f"{label}.resume.replacement_workspace_created must be false")
        valid = False
    prompt = before.get("prompt", {})
    plan = before.get("plan", {})
    if plan.get("source_prompt_id") != prompt.get("artifact_id"):
        findings.append(f"{label}.resume.before.plan.source_prompt_id is not bound to its current Prompt")
        valid = False
    prompt_after = after.get("prompt", {})
    plan_after = after.get("plan", {})
    if plan_after.get("source_prompt_id") != prompt_after.get("artifact_id"):
        findings.append(f"{label}.resume.after.plan.source_prompt_id is not bound to its current Prompt")
        valid = False
    for point, artifact in (("before", before), ("after", after)):
        if artifact.get("workspace_id") != side.get("workspace_id"):
            findings.append(f"{label}.resume.{point}.workspace_id differs from side workspace_id")
            valid = False
        if artifact.get("session_or_instance_id") != side.get("session_id"):
            findings.append(f"{label}.resume.{point}.session identity differs from side session_id")
            valid = False
    expected_public = None if label == "r6s" else True
    if resume.get("public_semantic_state_equivalent") != expected_public:
        findings.append(f"{label}.resume.public_semantic_state_equivalent is inconsistent")
        valid = False
    return valid and all(comparisons.values()) and resume.get("replacement_workspace_created") is False


def _continuation_findings(label: str, side: dict[str, Any], operations: list[str], findings: list[str], strict: bool) -> bool:
    continuation = side.get("execution_continuation", {})
    disposition = continuation.get("disposition")
    request_index = next((index for index, value in enumerate(operations) if value == "REQUEST_INPUT"), None)
    interpret_index = next((index for index, value in enumerate(operations) if value == "INTERPRET_EXECUTION_INPUT"), None)
    has_later_execute = interpret_index is not None and any(
        value == "EXECUTE" for value in operations[interpret_index + 1 :]
    )
    if disposition == "NOT_REQUESTED":
        expected = {
            "request_input_observed": False,
            "input_supplied": False,
            "interpret_execution_input_observed": False,
            "subsequent_execute_observed": False,
            "result_reached": True,
        }
        valid = request_index is None and interpret_index is None
    elif disposition == "REQUESTED_COMPLETED":
        expected = {
            "request_input_observed": True,
            "input_supplied": True,
            "interpret_execution_input_observed": True,
            "subsequent_execute_observed": True,
            "result_reached": True,
        }
        valid = request_index is not None and interpret_index is not None and request_index < interpret_index and has_later_execute
        if request_index is not None and interpret_index is not None and request_index >= interpret_index:
            findings.append(f"{label}.execution_continuation requires REQUEST_INPUT before INTERPRET_EXECUTION_INPUT")
    else:
        expected = {}
        valid = False
        findings.append(f"{label}.execution_continuation has an incomplete/unknown disposition")
    for field, expected_value in expected.items():
        if continuation.get(field) != expected_value:
            findings.append(f"{label}.execution_continuation.{field} contradicts operation evidence")
            valid = False
    if strict and not valid:
        findings.append(f"{label}.execution_continuation is incomplete")
    return valid


def _side_findings(label: str, side: dict[str, Any], run_root: Path, findings: list[str], strict: bool, attestation: dict[str, Any]) -> bool:
    if not isinstance(side, dict):
        findings.append(f"{label}: missing side object")
        return False
    operations = side.get("operations") if isinstance(side.get("operations"), list) else []
    observed_subsequence = required_subsequence(operations)
    if side.get("required_operation_subsequence_observed") != observed_subsequence:
        findings.append(f"{label}.required_operation_subsequence_observed contradicts operations")
    if strict and not observed_subsequence:
        findings.append(f"{label}: required operation subsequence is incomplete")
    prompt_ok = _correction_findings(label, "prompt_correction", side.get("prompt_correction", {}), "REVISE_TASK", "REVISE_PROMPT", findings, strict)
    plan_ok = _correction_findings(label, "plan_correction", side.get("plan_correction", {}), "REVISE_APPROACH", "REVISE_PLAN", findings, strict)
    resume_ok = _resume_findings(label, side, findings, strict)
    continuation_ok = _continuation_findings(label, side, operations, findings, strict)
    result_ok = _result_facts(run_root, label, side.get("result", {}), findings)
    metadata = side.get("worker_metadata", {})
    cap = side.get("capabilities", {})
    expected_capabilities = {
        "fresh_session_created": bool(side.get("session_id")),
        "fresh_workspace_created": bool(side.get("workspace_id")),
        "live_worker_observed": metadata.get("live_worker") is True and metadata.get("recorded_or_stub") is False,
        "prompt_review_reached": "INTERPRET_PROMPT_REVIEW" in operations,
        "prompt_task_change_classified": side.get("prompt_correction", {}).get("observed_intent") == "REVISE_TASK",
        "prompt_revision_route_observed": "REVISE_PROMPT" in operations,
        "prompt_correction_persisted": prompt_ok,
        "prompt_confirmation_progressed": "DRAFT_PLAN" in operations,
        "plan_review_reached": "INTERPRET_PLAN_REVIEW" in operations,
        "plan_approach_change_classified": side.get("plan_correction", {}).get("observed_intent") == "REVISE_APPROACH",
        "plan_revision_route_observed": "REVISE_PLAN" in operations,
        "plan_correction_persisted": plan_ok,
        "resume_checkpoint_preserved": resume_ok,
        "plan_confirmation_progressed": "EXECUTE" in operations,
        "execute_reached": "EXECUTE" in operations,
        "execution_continuation_supported_if_requested": continuation_ok,
        "result_persisted": result_ok,
        "terminal_success": result_ok and side.get("execution_continuation", {}).get("result_reached") is True,
        "historical_case_dependency_absent": attestation.get("historical_case_id_supplied") is False,
        "historical_evidence_dependency_absent": attestation.get("historical_evidence_supplied") is False,
        "recorded_worker_dependency_absent": attestation.get("recorded_worker_supplied") is False,
        "source_repo_unchanged": side.get("source_git_clean_after") is True and side.get("source_physical_inventory_equal") is True,
        "host_crash_absent": bool(operations),
    }
    valid = observed_subsequence and prompt_ok and plan_ok and resume_ok and continuation_ok and result_ok
    for name in CAPABILITY_NAMES:
        if name in expected_capabilities and cap.get(name) != expected_capabilities[name]:
            findings.append(f"{label}.capabilities.{name} contradicts underlying evidence")
            valid = False
        if strict and cap.get(name) is not True:
            findings.append(f"{label}.capabilities.{name} must be true for PASS")
            valid = False
    return valid


def semantic_findings(record: dict[str, Any], run_root: str | Path) -> list[str]:
    findings: list[str] = []
    root = Path(run_root).resolve()
    strict = record.get("status") == "PASS"
    attestation = record.get("input_attestation", {})
    expected_baselines = {
        "r6s": ("paragon-ux/PDL-Standard-REPL-Harness", R6S_COMMIT, R6S_TREE),
        "r6o": ("paragon-ux/PDL-Standard-R6O", R6O_COMMIT, R6O_TREE),
    }
    source_ok = True
    baselines = record.get("baselines", {})
    for label, (repository, commit, tree) in expected_baselines.items():
        baseline = baselines.get(label, {}) if isinstance(baselines, dict) else {}
        for field, expected in (("repository", repository), ("commit", commit), ("tree", tree)):
            if baseline.get(field) != expected:
                findings.append(f"baselines.{label}.{field} does not match the pinned baseline")
                source_ok = False
        equal = baseline.get("physical_inventory_before_sha256") == baseline.get("physical_inventory_after_sha256")
        if baseline.get("physical_inventory_equal") != equal:
            findings.append(f"baselines.{label}.physical_inventory_equal contradicts inventory hashes")
            source_ok = False
        if strict and (baseline.get("git_clean_before") is not True or baseline.get("git_clean_after") is not True or not equal):
            findings.append(f"baselines.{label}: PASS requires clean unchanged source")
            source_ok = False
    input_ok = _input_findings(record, root, findings)
    worker_ok = _worker_findings(record, root, findings)
    r6s = record.get("r6s", {})
    r6o = record.get("r6o", {})
    r6s_ok = _side_findings("r6s", r6s, root, findings, strict, attestation if isinstance(attestation, dict) else {})
    r6o_ok = _side_findings("r6o", r6o, root, findings, strict, attestation if isinstance(attestation, dict) else {})
    anti = record.get("anti_hardcode", {})
    anti_ok = True
    for label in ("r6s", "r6o"):
        side = anti.get(label, {}) if isinstance(anti, dict) else {}
        count = side.get("scanned_module_count", 0)
        paths = side.get("scanned_paths", [])
        zero = all(side.get(name) == 0 for name in (
            "g06_matches", "a02_matches", "rdx_case_matches", "recorded_fixture_path_matches",
            "historical_evidence_path_matches", "expected_output_routing_matches", "recorded_provider_live_import_matches",
        )) and side.get("matched_locations") == []
        if count != len(paths) or count < 1 or len(paths) != len(set(paths)):
            findings.append(f"anti_hardcode.{label}: scanned path/count evidence is inconsistent")
            anti_ok = False
        if not zero:
            findings.append(f"anti_hardcode.{label}: forbidden live-routing matches are present")
            anti_ok = False
    parity = record.get("parity", {})
    expected_parity = {
        "required_capabilities_pass_both": r6s_ok and r6o_ok,
        "same_input_hashes": input_ok,
        "same_worker_configuration": worker_ok,
        "anti_hardcode_pass_both": anti_ok,
        "source_read_only_pass_both": source_ok and r6s.get("source_git_clean_after") is True and r6o.get("source_git_clean_after") is True,
    }
    parity_ok = True
    for field, expected in expected_parity.items():
        if parity.get(field) != expected:
            findings.append(f"parity.{field} contradicts underlying evidence")
            parity_ok = False
        if strict and expected is not True:
            findings.append(f"parity.{field} is not proven")
            parity_ok = False
    complete = source_ok and input_ok and worker_ok and r6s_ok and r6o_ok and anti_ok and parity_ok
    if strict and not complete:
        findings.append("status PASS is not authorized by complete current evidence")
    if not strict and complete:
        findings.append("status is not PASS despite complete current evidence")
    return findings


def validate_record(
    record: dict[str, Any],
    run_root: str | Path,
    schema_path: str | Path = SCHEMA_PATH,
    *,
    execution_metadata: dict[str, Any] | None = None,
    r6o_control: str | Path | None = None,
    r6s_source: str | Path | None = None,
    gate_root: str | Path | None = None,
    code_freeze_head: str | None = None,
    code_freeze_tree: str | None = None,
) -> tuple[list[str], list[str]]:
    structural = structural_findings(record, schema_path)
    semantic = semantic_findings(record, run_root)
    context = (execution_metadata, r6o_control, r6s_source, gate_root, code_freeze_head, code_freeze_tree)
    if any(value is not None for value in context):
        if not all(value is not None for value in context):
            semantic.append("INTEGRITY: external validation context is incomplete")
        else:
            semantic.extend(validate_external_artifacts(
                record, run_root, execution_metadata,
                r6o_control=r6o_control, r6s_source=r6s_source, gate_root=gate_root,
                code_freeze_head=code_freeze_head, code_freeze_tree=code_freeze_tree,
            ))
    return structural, semantic


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate one frozen live-parity run record")
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--execution-metadata", type=Path, required=True)
    parser.add_argument("--r6o-control", type=Path, required=True)
    parser.add_argument("--r6s", type=Path, required=True)
    parser.add_argument("--gate-root", type=Path, required=True)
    parser.add_argument("--code-freeze-head", required=True)
    parser.add_argument("--code-freeze-tree", required=True)
    parser.add_argument("--schema", type=Path, required=True)
    args = parser.parse_args()
    try:
        record = json.loads(args.record.read_bytes().decode("utf-8"))
        metadata = json.loads(args.execution_metadata.read_bytes().decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"STRUCTURAL: external artifact load failed: {exc}")
        return 1
    structural, semantic = validate_record(
        record, args.run_root, args.schema, execution_metadata=metadata,
        r6o_control=args.r6o_control, r6s_source=args.r6s, gate_root=args.gate_root,
        code_freeze_head=args.code_freeze_head, code_freeze_tree=args.code_freeze_tree,
    )
    for finding in structural:
        print(f"STRUCTURAL: {finding}")
    for finding in semantic:
        print(f"SEMANTIC: {finding}")
    if not structural and not semantic:
        print("LIVE_PARITY_RECORD_VALID")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
