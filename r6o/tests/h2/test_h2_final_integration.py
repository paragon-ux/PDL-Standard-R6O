from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Callable

import pytest

from scripts.h2 import verify_h2_final as verifier


ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "r6o_evidence"


def _stage(tmp_path: Path, *relative_paths: str) -> Path:
    staged = tmp_path / "evidence"
    for relative in relative_paths:
        source = EVIDENCE / relative
        target = staged / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return staged


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _assert_diagnostic(exc_info: pytest.ExceptionInfo[verifier.FinalIntegrationError]) -> None:
    message = str(exc_info.value)
    for field in ("GATE=", "DIMENSION=", "EXPECTED=", "ACTUAL=", "SOURCE_IDENTITY="):
        assert field in message


def test_accepted_e2_single_attempt_ledger_is_valid(tmp_path: Path) -> None:
    staged = _stage(
        tmp_path,
        "H2-E2/code-freeze.json",
        "H2-E2/actual-host/qualification.json",
        "H2-E2/actual-host/live-attempts.json",
    )
    assert verifier._validate_e2(repo=ROOT, evidence=staged) == "PASS"


def test_root_oracle_fields_are_validated() -> None:
    verifier._validate_oracle_fields(
        {
            "oracle_commit": verifier.FROZEN_ORACLE_COMMIT,
            "oracle_tree": verifier.FROZEN_ORACLE_TREE,
        },
        gate="H2-B1",
        path="fixture.json",
    )


def test_accepted_tui_records_are_valid(tmp_path: Path) -> None:
    staged = _stage(
        tmp_path,
        "H2-B1/test-results.json",
        "H2-B2/test-results.json",
    )
    assert verifier._validate_tui(repo=ROOT, evidence=staged) == {
        "G06": "PASS",
        "A02-FULL": "PASS",
    }


def test_accepted_e3_revision_envelope_is_valid(tmp_path: Path) -> None:
    staged = _stage(
        tmp_path,
        "H2-E3/code-freeze.json",
        "H2-E3/actual-host/attempt-0012/qualification.json",
        "H2-E3/actual-host/live-attempts.json",
    )
    assert verifier._validate_e3(repo=ROOT, evidence=staged) == "PASS"


@pytest.mark.parametrize("stale_gate", ["H2-E1", "H2-F2"])
def test_stale_predecessor_accepted_head_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    stale_gate: str,
) -> None:
    stale = verifier.ACCEPTED_HEADS[stale_gate]
    monkeypatch.setattr(
        verifier,
        "_is_ancestor",
        lambda _repo, ancestor, _descendant: ancestor != stale,
    )
    monkeypatch.setattr(verifier, "_git_tree", lambda _repo, _revision: "tree")
    with pytest.raises(verifier.FinalIntegrationError) as exc_info:
        verifier._validate_ancestry(repo=ROOT, current_head="current")
    _assert_diagnostic(exc_info)
    assert exc_info.value.gate == stale_gate
    assert exc_info.value.dimension == "PREDECESSOR_ANCESTRY"


def test_stale_f2_second_repair_freeze_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_trees = {
        head: tree
        for head, tree in verifier.ACCEPTED_CODE_FREEZES.values()
    }

    def fake_tree(_repo: Path, revision: str) -> str:
        if revision == verifier.EXPECTED_F2_FREEZE_HEAD:
            return "0" * 40
        return expected_trees.get(revision, "tree")

    monkeypatch.setattr(verifier, "_is_ancestor", lambda *_args: True)
    monkeypatch.setattr(verifier, "_git_tree", fake_tree)
    with pytest.raises(verifier.FinalIntegrationError) as exc_info:
        verifier._validate_ancestry(repo=ROOT, current_head="current")
    _assert_diagnostic(exc_info)
    assert exc_info.value.gate == "H2-F2"
    assert exc_info.value.dimension == "ACCEPTED_FREEZE_TREE"


def test_missing_f1_parity_evidence_fails_closed(tmp_path: Path) -> None:
    staged = tmp_path / "evidence"
    with pytest.raises(verifier.FinalIntegrationError) as exc_info:
        verifier._validate_f1(repo=ROOT, evidence=staged)
    _assert_diagnostic(exc_info)
    assert exc_info.value.dimension == "MISSING_ACCEPTED_EVIDENCE"


def test_missing_f2_resilience_evidence_fails_closed(tmp_path: Path) -> None:
    staged = tmp_path / "evidence"
    with pytest.raises(verifier.FinalIntegrationError) as exc_info:
        verifier._validate_f2(repo=ROOT, evidence=staged)
    _assert_diagnostic(exc_info)
    assert exc_info.value.dimension == "MISSING_ACCEPTED_EVIDENCE"


def test_protected_path_mutation_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = {"head": "base", "tree": "tree"}
    monkeypatch.setattr(
        verifier,
        "_changed_paths_from",
        lambda _repo, _revision: ["r6o/model_binding/unauthorized.py"],
    )
    with pytest.raises(verifier.FinalIntegrationError) as exc_info:
        verifier._validate_protected_boundary(repo=ROOT, base=base)
    _assert_diagnostic(exc_info)
    assert exc_info.value.dimension == "PROTECTED_PATH_DIFF"


def test_frozen_oracle_mismatch_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    oracle = tmp_path / "oracle"
    (oracle / "scripts").mkdir(parents=True)
    (oracle / "scripts" / "verify_repl_baseline.py").write_text("# frozen\n", encoding="utf-8")

    def fake_git(
        _repo: Path,
        *arguments: str,
        gate: str = "H2-F3",
    ) -> str:
        if arguments == ("rev-parse", "HEAD"):
            return "1" * 40
        if arguments == ("status", "--porcelain", "--untracked-files=all"):
            return ""
        return ""

    monkeypatch.setattr(verifier, "_git", fake_git)
    monkeypatch.setattr(verifier, "_git_tree", lambda _repo, _revision: verifier.FROZEN_ORACLE_TREE)
    with pytest.raises(verifier.FinalIntegrationError) as exc_info:
        verifier._validate_oracle(oracle=oracle)
    _assert_diagnostic(exc_info)
    assert exc_info.value.gate == "R6S"
    assert exc_info.value.dimension == "FROZEN_ORACLE_COMMIT"


def test_missing_final_host_evidence_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(verifier.FinalIntegrationError) as exc_info:
        verifier._validate_current_host_evidence(
            repo=ROOT,
            output=tmp_path / "H2-F3",
            freeze={"head": "1" * 40, "tree": "2" * 40},
        )
    _assert_diagnostic(exc_info)
    assert exc_info.value.dimension == "ACTUAL_HOST_FINAL_EVIDENCE"


def test_wrong_human_gate_identity_fails_closed(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    _write_json(
        evidence / "H2" / "H2-HUMAN-GATE-RECORD.json",
        {
            "schema_version": "r6o-h2-human-gate-record-1",
            "gate": "H3",
            "human_disposition": None,
            "promotion_authorized": False,
            "human_pass": None,
        },
    )
    with pytest.raises(verifier.FinalIntegrationError) as exc_info:
        verifier._validate_human_record(repo=ROOT, evidence=evidence)
    _assert_diagnostic(exc_info)
    assert exc_info.value.dimension == "HUMAN_GATE_GATE"


def test_false_r6o3_claim_fails_closed() -> None:
    with pytest.raises(verifier.FinalIntegrationError) as exc_info:
        verifier._validate_no_r6o3(
            [("fixture.json", {"r6o3_behavior_claimed": True})]
        )
    _assert_diagnostic(exc_info)
    assert exc_info.value.dimension == "R6O3_BEHAVIOR_CLAIM"


def test_prefilled_human_disposition_fails_closed(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    _write_json(
        evidence / "H2" / "H2-HUMAN-GATE-RECORD.json",
        {
            "schema_version": "r6o-h2-human-gate-record-1",
            "gate": "H2",
            "human_disposition": "HUMAN_PASS",
            "promotion_authorized": True,
            "human_pass": "HUMAN_PASS",
        },
    )
    with pytest.raises(verifier.FinalIntegrationError) as exc_info:
        verifier._validate_human_record(repo=ROOT, evidence=evidence)
    _assert_diagnostic(exc_info)
    assert exc_info.value.dimension == "HUMAN_DISPOSITION"


def test_stale_ci_candidate_fails_closed(tmp_path: Path) -> None:
    ci_path = tmp_path / "ci.json"
    _write_json(
        ci_path,
        {
            "schema_version": "r6o-h2-f3-ci-1",
            "candidate": {"head": "0" * 40, "tree": "0" * 40},
            "workflows": [],
            "all_required_jobs_passed": False,
        },
    )
    with pytest.raises(verifier.FinalIntegrationError) as exc_info:
        verifier._validate_ci(
            repo=ROOT,
            path=ci_path,
            freeze={"head": "1" * 40, "tree": "2" * 40},
        )
    _assert_diagnostic(exc_info)
    assert exc_info.value.dimension == "CI_CANDIDATE"


def _valid_ci_document(freeze: dict[str, str]) -> dict[str, Any]:
    workflows = []
    next_run = 100
    next_job = 1000
    for workflow, jobs in verifier.CI_REQUIREMENTS.items():
        run_id = next_run
        next_run += 1
        records = {}
        for job, name in jobs.items():
            job_id = next_job
            next_job += 1
            records[job] = {
                "job_id": job_id,
                "name": name,
                "status": "SUCCESS",
                "head_sha": freeze["head"],
                "workflow_run_id": run_id,
                "workflow": workflow,
                "job_url": (
                    "https://github.com/paragon-ux/PDL-Standard-R6O/actions/"
                    f"runs/{run_id}/job/{job_id}"
                ),
            }
        workflows.append(
            {
                "workflow": workflow,
                "run_id": run_id,
                "run_url": (
                    "https://github.com/paragon-ux/PDL-Standard-R6O/actions/"
                    f"runs/{run_id}"
                ),
                "head_sha": freeze["head"],
                "status": "SUCCESS",
                "jobs": records,
            }
        )
    return {
        "schema_version": "r6o-h2-f3-ci-1",
        "candidate": dict(freeze),
        "workflows": workflows,
        "all_required_jobs_passed": True,
    }


def _write_valid_qt(output: Path, freeze: dict[str, str], ci: dict[str, Any]) -> None:
    jobs = {
        key: value
        for workflow in ci["workflows"]
        for key, value in workflow["jobs"].items()
    }
    _write_json(
        output / "qt-qualification.json",
        {
            "schema_version": "r6o-h2-f3-qt-qualification-1",
            "source": dict(freeze),
            "human_visual_approval": "PENDING_HUMAN_H2",
            "platforms": {
                "windows": {
                    "status": "PASS",
                    "result_path": "qt/windows/component-result.json",
                },
                "linux_x11": {"status": "PASS", "ci_job": jobs["linux_x11"]},
                "linux_wayland": {
                    "status": "PASS",
                    "ci_job": jobs["linux_wayland"],
                },
            },
        },
    )
    _write_json(
        output / "qt" / "windows" / "component-result.json",
        {
            "status": "MECHANICAL_PASS_PENDING_FINAL_REVIEW",
            "source": dict(freeze),
            "proof": {
                "q01_q24": {f"Q{number:02d}": True for number in range(1, 25)},
                "q25_standard_human_comparison": "PENDING_HUMAN_H2",
                "q26_expanded_human_comparison": "PENDING_HUMAN_H2",
            },
        },
    )


def _stub_repository_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    *,
    freeze: dict[str, str],
) -> None:
    monkeypatch.setattr(
        verifier,
        "_source_identity",
        lambda _repo: {
            "branch": "codex/h2-f3-final-integration",
            "head": freeze["head"],
            "tree": freeze["tree"],
            "dirty_paths": [],
        },
    )
    monkeypatch.setattr(verifier, "_validate_base", lambda **_kwargs: {"head": "b" * 40, "tree": "c" * 40})
    monkeypatch.setattr(verifier, "_validate_code_freeze", lambda **_kwargs: dict(freeze))
    monkeypatch.setattr(verifier, "_validate_ancestry", lambda **_kwargs: {})
    monkeypatch.setattr(verifier, "_validate_protected_boundary", lambda **_kwargs: {"status": "EMPTY"})
    monkeypatch.setattr(verifier, "_validate_oracle", lambda **_kwargs: {"status": "UNCHANGED"})
    monkeypatch.setattr(verifier, "_validate_tui", lambda **_kwargs: {"G06": "PASS", "A02-FULL": "PASS"})
    monkeypatch.setattr(verifier, "_validate_e1", lambda **_kwargs: "PASS")
    monkeypatch.setattr(verifier, "_validate_e2", lambda **_kwargs: "PASS")
    monkeypatch.setattr(verifier, "_validate_e3", lambda **_kwargs: "PASS")
    monkeypatch.setattr(verifier, "_validate_f1", lambda **_kwargs: "PASS")
    monkeypatch.setattr(verifier, "_validate_f2", lambda **_kwargs: {"status": "PASS"})
    monkeypatch.setattr(verifier, "_validate_local_qualification", lambda **_kwargs: {"status": "PASS"})
    monkeypatch.setattr(verifier, "_validate_current_host_evidence", lambda **_kwargs: {"status": "PASS", "attachment": "PASS"})
    monkeypatch.setattr(verifier, "_validate_human_record", lambda **_kwargs: {"status": "HUMAN_PENDING"})


@pytest.mark.parametrize(
    ("case", "dimension"),
    [
        ("missing_candidate_head", "CI_CANDIDATE"),
        ("wrong_candidate_head", "CI_CANDIDATE"),
        ("missing_workflow_head", "CI_WORKFLOW_HEAD"),
        ("wrong_workflow_head", "CI_WORKFLOW_HEAD"),
        ("missing_linux_job_provenance", "CI_JOB_PROVENANCE"),
        ("wrong_linux_job_provenance", "CI_JOB_PROVENANCE"),
        ("successful_job_from_different_run", "CI_JOB_PROVENANCE"),
    ],
)
def test_repository_verifier_rejects_inexact_ci_provenance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    case: str,
    dimension: str,
) -> None:
    freeze = {"head": "1" * 40, "tree": "2" * 40}
    _stub_repository_dependencies(monkeypatch, freeze=freeze)
    evidence = tmp_path / "evidence"
    output = evidence / "H2-F3" / "repair"
    ci = _valid_ci_document(freeze)
    qt_workflow = ci["workflows"][1]
    if case == "missing_candidate_head":
        del ci["candidate"]["head"]
    elif case == "wrong_candidate_head":
        ci["candidate"]["head"] = "0" * 40
    elif case == "missing_workflow_head":
        del qt_workflow["head_sha"]
    elif case == "wrong_workflow_head":
        qt_workflow["head_sha"] = "0" * 40
    elif case == "missing_linux_job_provenance":
        del qt_workflow["jobs"]["linux_x11"]["head_sha"]
    elif case == "wrong_linux_job_provenance":
        qt_workflow["jobs"]["linux_x11"]["head_sha"] = "0" * 40
    else:
        qt_workflow["jobs"]["linux_x11"]["workflow_run_id"] += 1
    _write_json(output / "ci.json", ci)
    _write_valid_qt(output, freeze, _valid_ci_document(freeze))
    _write_json(evidence / "H2" / "H2-HUMAN-GATE-RECORD.json", {"r6o3_behavior_claimed": False})
    with pytest.raises(verifier.FinalIntegrationError) as exc_info:
        verifier.verify_repository(
            repo_root=ROOT,
            evidence_root=evidence,
            baseline_repo=tmp_path,
            output_dir=output,
            require_local=False,
            require_actual_host=False,
            write_report=False,
        )
    _assert_diagnostic(exc_info)
    assert exc_info.value.dimension == dimension


def test_repository_verifier_accepts_exact_ci_job_run_candidate_provenance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    freeze = {"head": "1" * 40, "tree": "2" * 40}
    _stub_repository_dependencies(monkeypatch, freeze=freeze)
    evidence = tmp_path / "evidence"
    output = evidence / "H2-F3" / "repair"
    ci = _valid_ci_document(freeze)
    _write_json(output / "ci.json", ci)
    _write_valid_qt(output, freeze, ci)
    _write_json(evidence / "H2" / "H2-HUMAN-GATE-RECORD.json", {"r6o3_behavior_claimed": False})
    report = verifier.verify_repository(
        repo_root=ROOT,
        evidence_root=evidence,
        baseline_repo=tmp_path,
        output_dir=output,
        require_local=False,
        require_actual_host=False,
        write_report=False,
    )
    assert report["dimensions"]["final_ci"] == {
        "github_windows": "PASS",
        "github_ubuntu": "PASS",
        "windows_qt": "PASS",
        "linux_x11": "PASS",
        "linux_wayland": "PASS",
    }


@pytest.mark.parametrize(
    ("relative_path", "key", "value"),
    [
        ("H2-F3/qualification.json", "r6o3_behavior_claimed", True),
        ("H2-F3/actual-host/qualification.json", "r6o3_lease_implemented", True),
        ("H2/H2-HUMAN-GATE-RECORD.json", "r6o3_behavior_claimed", "YES"),
    ],
)
def test_repository_verifier_rejects_r6o3_claim_in_final_f3_records(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    relative_path: str,
    key: str,
    value: object,
) -> None:
    freeze = {"head": "1" * 40, "tree": "2" * 40}
    _stub_repository_dependencies(monkeypatch, freeze=freeze)
    evidence = tmp_path / "evidence"
    output = evidence / "H2-F3" / "repair"
    _write_json(evidence / relative_path, {key: value})
    human = evidence / "H2" / "H2-HUMAN-GATE-RECORD.json"
    if not human.is_file():
        _write_json(human, {"r6o3_behavior_claimed": False})
    with pytest.raises(verifier.FinalIntegrationError) as exc_info:
        verifier.verify_repository(
            repo_root=ROOT,
            evidence_root=evidence,
            baseline_repo=tmp_path,
            output_dir=output,
            require_local=False,
            require_actual_host=False,
            require_qt=False,
            require_ci=False,
            write_report=False,
        )
    _assert_diagnostic(exc_info)
    assert exc_info.value.dimension == "R6O3_BEHAVIOR_CLAIM"


def test_repository_verifier_accepts_safe_negative_r6o3_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    freeze = {"head": "1" * 40, "tree": "2" * 40}
    _stub_repository_dependencies(monkeypatch, freeze=freeze)
    evidence = tmp_path / "evidence"
    output = evidence / "H2-F3" / "repair"
    values = [False, "NO", "NOT_IMPLEMENTED", "NOT_CLAIMED"]
    paths = [
        "H2-F3/qualification.json",
        "H2-F3/actual-host/qualification.json",
        "H2-F3/local-qualification.json",
        "H2-F3/qt-qualification.json",
        "H2-F3/ci.json",
        "H2-F3/repair/actual-host/qualification.json",
        "H2/H2-HUMAN-GATE-RECORD.json",
    ]
    for index, relative_path in enumerate(paths):
        _write_json(
            evidence / relative_path,
            {"r6o3_behavior_claimed": values[index % len(values)]},
        )
    report = verifier.verify_repository(
        repo_root=ROOT,
        evidence_root=evidence,
        baseline_repo=tmp_path,
        output_dir=output,
        require_local=False,
        require_actual_host=False,
        require_qt=False,
        require_ci=False,
        write_report=False,
    )
    assert report["r6o3_behavior_claimed"] is False


def _write_current_host_fixture(
    output: Path,
    freeze: dict[str, str],
) -> None:
    host = dict(verifier.CURRENT_HOST)
    e1 = {
        "schema_version": "r6o-h2-f3-current-e1-1",
        "status": "H2_F3_CURRENT_E1_PASS",
        "source": dict(freeze),
        "actual_codex_host": host,
        "captured_text_normalized": verifier.E1_EXPECTED_TEXT,
        "shift_enter_preserved": True,
        "unmodified_enter_intercepted": True,
        "native_enter_keydown_suppressed": True,
        "native_enter_keyup_suppressed": True,
        "native_codex_submission_observed": False,
        "composer_cleared": True,
        "sidecar_dismissed": True,
        "actual_composer_focus_restored": True,
        "human_gesture_synthesized": False,
    }
    g06 = {
        "status": "H2_E2_G06_PASS",
        "code_freeze_head": freeze["head"],
        "code_freeze_tree": freeze["tree"],
        "actual_codex_host": host,
        "worker_operations": [
            {"operation_id": operation_id, "operation": operation}
            for operation_id, operation in verifier.G06_OPERATIONS
        ],
        "structured_action_envelopes": [
            {"action_id": "confirm_prompt"},
            {"action_id": "confirm_plan"},
        ],
        "native_codex_submission_observed": False,
        "sidecar_dismissed": True,
        "actual_composer_focus_restored": True,
    }
    a02 = {
        "status": "H2_E3_A02_FULL_PASS",
        "code_freeze_head": freeze["head"],
        "code_freeze_tree": freeze["tree"],
        "actual_codex_host": host,
        "worker_operations": [
            {"operation_id": operation_id, "operation": operation}
            for operation_id, operation in verifier.A02_OPERATIONS
        ],
        "input_envelopes": [
            {"source": "STRUCTURED_ACTION", "action_id": "something_else"},
            {"source": "HOST_COMPOSER_TEXT", "text": verifier.REVISION_TEXT},
            {"source": "STRUCTURED_ACTION", "action_id": "confirm_prompt"},
            {"source": "STRUCTURED_ACTION", "action_id": "confirm_plan"},
        ],
        "transitions": [
            {"artifact_body_sha256": hashlib.sha256(verifier.A02_INITIAL_PROMPT.encode()).hexdigest()},
            {},
            {"artifact_body_sha256": hashlib.sha256(verifier.A02_REVISED_PROMPT.encode()).hexdigest()},
            {"artifact_body_sha256": hashlib.sha256(verifier.A02_EXPECTED_PLAN.encode()).hexdigest()},
        ],
        "native_enter_keydown_suppressed": True,
        "native_enter_keyup_suppressed": True,
        "native_codex_submission_observed": False,
        "composer_cleared": True,
        "sidecar_dismissed": True,
        "actual_composer_focus_restored": True,
    }
    lifecycle = {
        "schema_version": "r6o-h2-f3-current-lifecycle-1",
        "status": "H2_F3_CURRENT_LIFECYCLE_PASS",
        "source": dict(freeze),
        "actual_host": {"status": "PASS"},
        "process_exit": {
            "status": "PASS",
            "cleanup_complete_marker": True,
            "process_terminated": True,
        },
        "accepted_f2_repair_matrix": {"R1": {"status": "PASS"}},
        "r6o3_lease_implemented": False,
    }
    records = {
        "e1": e1,
        "g06": g06,
        "a02-full": a02,
        "lifecycle": lifecycle,
    }
    for name, value in records.items():
        _write_json(output / "actual-host" / name / "qualification.json", value)
    attachment_source = EVIDENCE / "H2-F3" / "actual-host" / "attachment" / "attachment-result.json"
    attachment_target = output / "actual-host" / "attachment" / "attachment-result.json"
    attachment_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(attachment_source, attachment_target)
    _write_json(
        output / "actual-host" / "qualification.json",
        {
            "schema_version": "r6o-h2-f3-current-actual-host-1",
            "status": verifier.CURRENT_ACTUAL_HOST_PASS_TOKEN,
            "source": dict(freeze),
            "human_gesture_synthesized": False,
            "records": {
                "e1": "actual-host/e1/qualification.json",
                "g06": "actual-host/g06/qualification.json",
                "a02_full": "actual-host/a02-full/qualification.json",
                "lifecycle": "actual-host/lifecycle/qualification.json",
            },
            "attachment": {
                "status": "PASS",
                "path": "actual-host/attachment/attachment-result.json",
            },
            "dimensions": {
                "e1_input_routing": "PASS",
                "actual_host_g06": "PASS",
                "actual_host_a02_full": "PASS",
                "lifecycle_resilience": "PASS",
            },
        },
    )


def test_current_actual_host_evidence_is_pinned_and_complete(tmp_path: Path) -> None:
    freeze = {"head": "1" * 40, "tree": "2" * 40}
    output = tmp_path / "repair"
    _write_current_host_fixture(output, freeze)
    assert verifier._validate_current_host_evidence(
        repo=ROOT,
        output=output,
        freeze=freeze,
    )["status"] == "PASS"


def test_current_actual_host_wrong_revision_fails_closed(tmp_path: Path) -> None:
    freeze = {"head": "1" * 40, "tree": "2" * 40}
    output = tmp_path / "repair"
    _write_current_host_fixture(output, freeze)
    path = output / "actual-host" / "a02-full" / "qualification.json"
    a02 = json.loads(path.read_text(encoding="utf-8"))
    a02["input_envelopes"][1]["text"] = "wrong revision"
    _write_json(path, a02)
    with pytest.raises(verifier.FinalIntegrationError) as exc_info:
        verifier._validate_current_host_evidence(
            repo=ROOT,
            output=output,
            freeze=freeze,
        )
    _assert_diagnostic(exc_info)
    assert exc_info.value.dimension == "CURRENT_A02_REVISION"
