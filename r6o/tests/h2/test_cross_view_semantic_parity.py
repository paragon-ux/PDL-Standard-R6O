from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path
from typing import Any, Callable

import pytest

from scripts.h2 import verify_cross_view_parity as verifier


ROOT = Path(__file__).resolve().parents[3]
EVIDENCE_ROOT = ROOT / "r6o_evidence"


@pytest.fixture(scope="module")
def accepted_cases(baseline_repo: Path) -> dict[str, dict[str, Any]]:
    cases: dict[str, dict[str, Any]] = {}
    for case in verifier.CASE_CONFIGS:
        cases[case] = {
            "tui": verifier.capture_tui_projections(case, baseline_repo),
            "sidecar": verifier.load_sidecar_evidence(case, EVIDENCE_ROOT),
            "acceptance": verifier.load_tui_acceptance(case, EVIDENCE_ROOT),
        }
        verifier._validate_tui_acceptance(
            case,
            cases[case]["acceptance"],
            cases[case]["tui"],
        )
    return cases


def test_g06_and_a02_full_positive_parity(accepted_cases: dict[str, dict[str, Any]]) -> None:
    for case, inputs in accepted_cases.items():
        report = verifier._compare_cases(case, inputs["tui"], inputs["sidecar"])
        assert report["status"] == "PASS"
    assert (
        verifier._compare_cases("G06", accepted_cases["G06"]["tui"], accepted_cases["G06"]["sidecar"])
        ["dimensions"]["free_response_focus_behavior"]["status"]
        == "N/A — NOT EXERCISED BY G06"
    )


def test_cli_verifier_writes_machine_readable_pass_report(
    baseline_repo: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "H2-F1"
    report = verifier.verify_repository(baseline_repo=baseline_repo, output_dir=output)
    assert report["status"] == "F1_PARITY_PASS"
    assert report["cases"]["G06"]["status"] == "PASS"
    assert report["cases"]["A02-FULL"]["status"] == "PASS"
    assert (output / "parity-report.json").is_file()
    assert (output / "tui-projections" / "G06.json").is_file()
    assert (output / "tui-projections" / "A02_FULL.json").is_file()


def _assert_diagnostic(exc_info: pytest.ExceptionInfo[verifier.ParityVerificationError], case: str) -> None:
    error = exc_info.value
    assert error.case == case
    message = str(error)
    for field in ("CASE=", "DIMENSION=", "TUI_VALUE=", "SIDECAR_VALUE=", "SOURCE_IDENTITY="):
        assert field in message


Mutation = Callable[[dict[str, Any]], None]


@pytest.mark.parametrize(
    ("case", "name", "mutate", "dimension"),
    [
        (
            "G06",
            "stage",
            lambda sidecar: sidecar["events"][1]["normalized_projection"].__setitem__(
                "stage", "PROMPT_REVIEW"
            ),
            "STAGE_SEQUENCE",
        ),
        (
            "G06",
            "action",
            lambda sidecar: sidecar["events"][0]["normalized_projection"]["actions"][0].__setitem__(
                "action_id", "wrong_action"
            ),
            "ACTION_ORDER",
        ),
        (
            "G06",
            "artifact",
            lambda sidecar: sidecar["events"][0]["normalized_projection"]["artifact"].__setitem__(
                "body_sha256", "mutated-artifact"
            ),
            "ARTIFACT_IDENTITY",
        ),
        (
            "G06",
            "worker",
            lambda sidecar: sidecar["events"][1]["worker_operations"][0].__setitem__(
                "operation_id", "G06:9999"
            ),
            "WORKER_OPERATIONS",
        ),
        (
            "A02-FULL",
            "revised Prompt",
            lambda sidecar: sidecar["events"][2]["normalized_projection"]["artifact"].__setitem__(
                "body_sha256", "mutated-revised-prompt"
            ),
            "ARTIFACT_IDENTITY",
        ),
        (
            "A02-FULL",
            "Plan",
            lambda sidecar: sidecar["events"][3]["normalized_projection"]["artifact"].__setitem__(
                "body_sha256", "mutated-plan"
            ),
            "ARTIFACT_IDENTITY",
        ),
        (
            "A02-FULL",
            "terminal",
            lambda sidecar: sidecar["events"][-1]["normalized_projection"]["lifecycle"].__setitem__(
                "terminal_disposition", "CANCELLED"
            ),
            "TERMINAL_DISPOSITION",
        ),
        (
            "A02-FULL",
            "wrong source",
            lambda sidecar: sidecar["events"][2].__setitem__("input_envelope_source", "TUI_TEXT"),
            "SOURCE_IDENTITY",
        ),
    ],
)
def test_semantic_mutations_fail_closed(
    accepted_cases: dict[str, dict[str, Any]],
    case: str,
    name: str,
    mutate: Mutation,
    dimension: str,
) -> None:
    tui = copy.deepcopy(accepted_cases[case]["tui"])
    sidecar = copy.deepcopy(accepted_cases[case]["sidecar"])
    mutate(sidecar)

    with pytest.raises(verifier.ParityVerificationError) as exc_info:
        verifier._compare_cases(case, tui, sidecar)

    _assert_diagnostic(exc_info, case)
    assert exc_info.value.dimension == dimension, name


def _copy_actual_host_evidence(tmp_path: Path, case: str) -> Path:
    evidence_root = tmp_path / "r6o_evidence"
    if case == "G06":
        shutil.copytree(EVIDENCE_ROOT / "H2-E2", evidence_root / "H2-E2")
    else:
        shutil.copytree(EVIDENCE_ROOT / "H2-E3", evidence_root / "H2-E3")
    return evidence_root


def _qualification_path(evidence_root: Path, case: str) -> Path:
    if case == "G06":
        return evidence_root / "H2-E2/actual-host/qualification.json"
    return evidence_root / "H2-E3/actual-host/attempt-0012/qualification.json"


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def test_missing_sidecar_projection_fails_closed_in_temporary_input(tmp_path: Path) -> None:
    evidence_root = _copy_actual_host_evidence(tmp_path, "A02-FULL")
    projection = evidence_root / "H2-E3/actual-host/attempt-0012/projections/A02-T3-CODEX.json"
    projection.unlink()

    with pytest.raises(verifier.ParityVerificationError) as exc_info:
        verifier.load_sidecar_evidence("A02-FULL", evidence_root)

    _assert_diagnostic(exc_info, "A02-FULL")
    assert exc_info.value.dimension == "MISSING_EVIDENCE"


def test_stale_identity_fails_closed_in_temporary_input(tmp_path: Path) -> None:
    evidence_root = _copy_actual_host_evidence(tmp_path, "A02-FULL")
    transition_paths = [
        evidence_root / "H2-E3/actual-host/attempt-0012/transitions.json",
        evidence_root / "H2-E3/actual-host/attempt-0012/qualification.json",
    ]
    for path in transition_paths:
        records = json.loads(path.read_text(encoding="utf-8"))
        transitions = records["transitions"] if isinstance(records, dict) else records
        transitions[1]["input_envelope"]["model_revision"] = "stale-model-revision"
        path.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(verifier.ParityVerificationError) as exc_info:
        verifier.load_sidecar_evidence("A02-FULL", evidence_root)

    _assert_diagnostic(exc_info, "A02-FULL")
    assert exc_info.value.dimension == "STALE_IDENTITY"


@pytest.mark.parametrize("case", ["G06", "A02-FULL"])
def test_transition_schema_fails_closed_in_temporary_input(tmp_path: Path, case: str) -> None:
    evidence_root = _copy_actual_host_evidence(tmp_path, case)
    qualification_path = _qualification_path(evidence_root, case)
    transitions_path = qualification_path.with_name("transitions.json")
    for path in (qualification_path, transitions_path):
        records = json.loads(path.read_text(encoding="utf-8"))
        transitions = records["transitions"] if isinstance(records, dict) else records
        transitions[0]["schema_version"] = "incompatible-transition-schema"
        _write_json(path, records)

    with pytest.raises(verifier.ParityVerificationError) as exc_info:
        verifier.load_sidecar_evidence(case, evidence_root)

    _assert_diagnostic(exc_info, case)
    assert exc_info.value.dimension == "EVIDENCE_INTEGRITY"


@pytest.mark.parametrize(
    ("case", "field"),
    [
        ("G06", "accepted_e1_head"),
        ("G06", "code_freeze_head"),
        ("G06", "code_freeze_tree"),
        ("A02-FULL", "accepted_e2_head"),
        ("A02-FULL", "code_freeze_head"),
        ("A02-FULL", "code_freeze_tree"),
    ],
)
def test_qualification_provenance_fails_closed_in_temporary_input(
    tmp_path: Path,
    case: str,
    field: str,
) -> None:
    evidence_root = _copy_actual_host_evidence(tmp_path, case)
    qualification_path = _qualification_path(evidence_root, case)
    qualification = json.loads(qualification_path.read_text(encoding="utf-8"))
    qualification[field] = f"stale-{field}"
    _write_json(qualification_path, qualification)

    with pytest.raises(verifier.ParityVerificationError) as exc_info:
        verifier.load_sidecar_evidence(case, evidence_root)

    _assert_diagnostic(exc_info, case)
    assert exc_info.value.dimension == "EVIDENCE_INTEGRITY"


@pytest.mark.parametrize(
    ("case", "gate_directory", "field"),
    [
        ("G06", "H2-E2", "accepted_e1_head"),
        ("G06", "H2-E2", "code_freeze_tree"),
        ("A02-FULL", "H2-E3", "accepted_e2_head"),
        ("A02-FULL", "H2-E3", "code_freeze_tree"),
    ],
)
def test_code_freeze_manifest_provenance_fails_closed_in_temporary_input(
    tmp_path: Path,
    case: str,
    gate_directory: str,
    field: str,
) -> None:
    evidence_root = _copy_actual_host_evidence(tmp_path, case)
    freeze_path = evidence_root / gate_directory / "code-freeze.json"
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    freeze[field] = f"stale-{field}"
    _write_json(freeze_path, freeze)

    with pytest.raises(verifier.ParityVerificationError) as exc_info:
        verifier.load_sidecar_evidence(case, evidence_root)

    _assert_diagnostic(exc_info, case)
    assert exc_info.value.dimension == "EVIDENCE_INTEGRITY"


def test_e3_ledger_qualification_mismatch_fails_closed_in_temporary_input(tmp_path: Path) -> None:
    evidence_root = _copy_actual_host_evidence(tmp_path, "A02-FULL")
    ledger_path = evidence_root / "H2-E3/actual-host/live-attempts.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger[-1]["head"] = "stale-evidence-head"
    _write_json(ledger_path, ledger)

    with pytest.raises(verifier.ParityVerificationError) as exc_info:
        verifier.load_sidecar_evidence("A02-FULL", evidence_root)

    _assert_diagnostic(exc_info, "A02-FULL")
    assert exc_info.value.dimension == "EVIDENCE_INTEGRITY"


def test_e2_ledger_qualification_mismatch_fails_closed_in_temporary_input(tmp_path: Path) -> None:
    evidence_root = _copy_actual_host_evidence(tmp_path, "G06")
    ledger_path = evidence_root / "H2-E2/actual-host/live-attempts.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger[-1]["head"] = "stale-evidence-head"
    _write_json(ledger_path, ledger)

    with pytest.raises(verifier.ParityVerificationError) as exc_info:
        verifier.load_sidecar_evidence("G06", evidence_root)

    _assert_diagnostic(exc_info, "G06")
    assert exc_info.value.dimension == "EVIDENCE_INTEGRITY"
