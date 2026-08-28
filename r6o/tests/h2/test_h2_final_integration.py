from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import pytest

from scripts.h2 import f3_attachment_provenance as transaction
from scripts.h2 import verify_h2_final as verifier


ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "r6o_evidence"


def test_f3_hashed_text_evidence_uses_lf_checkout_identity() -> None:
    paths = [
        "r6o_evidence/H2-F3/qualification.json",
        "r6o_evidence/H2-F3/repair/actual-host/attachment/win32-uia-events.jsonl",
        "r6o_evidence/H2-F3/repair/logs/final_verifier.stdout.txt",
        "r6o_evidence/H2-F3/tui-e1/session.cast",
        "r6o_evidence/H2-F3/future/failure.log",
    ]
    completed = subprocess.run(
        ["git", "check-attr", "text", "eol", "--", *paths],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    for path in paths:
        assert f"{path}: text: set" in completed.stdout
        assert f"{path}: eol: lf" in completed.stdout


def test_direct_script_bootstraps_repository_imports_without_pythonpath() -> None:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "scripts/h2/verify_h2_final.py",
            "--probe-repository-import-bootstrap",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "H2_F3_REPOSITORY_IMPORT_BOOTSTRAP_PASS"


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


@pytest.mark.parametrize(
    ("relative_path", "document"),
    [
        (
            "H2-F3/repair/actual-host/attachment/attachment-result.json",
            {"scope": {"r6o3_lease_implemented": True}},
        ),
        (
            "H2-F3/repair/actual-host/attachment/f3-provenance.json",
            {"r6o3_behavior_claimed": True},
        ),
    ],
)
def test_repository_verifier_rejects_r6o3_claim_in_current_attachment_records(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    relative_path: str,
    document: dict[str, Any],
) -> None:
    freeze = {"head": "1" * 40, "tree": "2" * 40}
    _stub_repository_dependencies(monkeypatch, freeze=freeze)
    evidence = tmp_path / "evidence"
    output = evidence / "H2-F3" / "repair"
    _write_json(evidence / relative_path, document)

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


def test_repository_verifier_accepts_safe_negative_current_attachment_records(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    freeze = {"head": "1" * 40, "tree": "2" * 40}
    _stub_repository_dependencies(monkeypatch, freeze=freeze)
    evidence = tmp_path / "evidence"
    output = evidence / "H2-F3" / "repair"
    _write_json(
        output / "actual-host" / "attachment" / "attachment-result.json",
        {"scope": {"r6o3_lease_implemented": False}},
    )
    _write_json(
        output / "actual-host" / "attachment" / "f3-provenance.json",
        {"r6o3_behavior_claimed": False},
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
    repo: Path,
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
    attachment_source = EVIDENCE / "H2-F3" / "repair" / "actual-host" / "attachment" / "attachment-result.json"
    attachment_target = output / "actual-host" / "attachment" / "attachment-result.json"
    attachment_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(attachment_source, attachment_target)
    event_log_target = output / "actual-host" / "attachment" / "win32-uia-events.jsonl"
    shutil.copyfile(
        EVIDENCE
        / "H2-F3"
        / "repair"
        / "actual-host"
        / "attachment"
        / "win32-uia-events.jsonl",
        event_log_target,
    )
    attachment_document = json.loads(
        attachment_target.read_text(encoding="utf-8")
    )
    attachment_document["event_log"]["path"] = event_log_target.relative_to(repo).as_posix()
    attachment_document["event_log"]["sha256"] = hashlib.sha256(
        event_log_target.read_bytes()
    ).hexdigest()
    implementation_paths = (
        "r6o/host/codex/windows/binding.py",
        "r6o/host/codex/windows/placement.py",
        "scripts/h2/verify_codex_attachment.py",
    )
    attachment_document["implementation_sha256"] = {}
    for relative_path in implementation_paths:
        implementation_target = repo / relative_path
        implementation_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative_path, implementation_target)
        attachment_document["implementation_sha256"][relative_path] = hashlib.sha256(
            implementation_target.read_bytes()
        ).hexdigest()
    _write_json(attachment_target, attachment_document)
    preflight_target = output / "actual-host" / "preflight-reset.json"
    shutil.copyfile(
        EVIDENCE / "H2-F3" / "repair" / "actual-host" / "preflight-reset.json",
        preflight_target,
    )
    host_record_target = repo / "r6o_evidence" / "H2-D1" / "host-environment.json"
    host_record_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(
        EVIDENCE / "H2-D1" / "host-environment.json",
        host_record_target,
    )
    selectors_target = repo / "r6o" / "host" / "codex" / "windows" / "selectors.json"
    selectors_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(
        ROOT / "r6o" / "host" / "codex" / "windows" / "selectors.json",
        selectors_target,
    )
    provenance_target = output / "actual-host" / "attachment" / "f3-provenance.json"
    _write_json(
        provenance_target,
        {
            "schema_version": "r6o-h2-f3-attachment-provenance-1",
            "gate": "H2-F3",
            "candidate_head": freeze["head"],
            "candidate_tree": freeze["tree"],
            "attachment_result_path": attachment_target.relative_to(repo).as_posix(),
            "attachment_result_sha256": hashlib.sha256(attachment_target.read_bytes()).hexdigest(),
            "event_log_path": event_log_target.relative_to(repo).as_posix(),
            "event_log_sha256": hashlib.sha256(event_log_target.read_bytes()).hexdigest(),
            "host_record_path": host_record_target.relative_to(repo).as_posix(),
            "host_record_sha256": hashlib.sha256(host_record_target.read_bytes()).hexdigest(),
            "selectors_path": selectors_target.relative_to(repo).as_posix(),
            "selectors_sha256": hashlib.sha256(selectors_target.read_bytes()).hexdigest(),
            "producer_implementation_sha256": {
                relative_path: hashlib.sha256((repo / relative_path).read_bytes()).hexdigest()
                for relative_path in implementation_paths
            },
            "preflight_reset_path": preflight_target.relative_to(repo).as_posix(),
            "preflight_reset_sha256": hashlib.sha256(preflight_target.read_bytes()).hexdigest(),
            "preflight_status": "CODEX_TEST_SESSION_READY",
            "attachment_status": "H2_D2_ATTACHMENT_PASS",
            "active_attachment": "PASS",
            "real_codex_host_tested": True,
            "synthetic_owner_used": False,
            "reset_to_attachment_contiguous_machine_flow": True,
            "historical_failures_preserved": True,
        },
    )
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
            "attachment_status": "H2_D2_ATTACHMENT_PASS",
            "f3_attachment_provenance": "actual-host/attachment/f3-provenance.json",
            "dimensions": {
                "e1_input_routing": "PASS",
                "actual_host_g06": "PASS",
                "actual_host_a02_full": "PASS",
                "lifecycle_resilience": "PASS",
            },
        },
    )


def _write_transaction_inputs(repo: Path, output: Path) -> None:
    for relative_path in transaction.PRODUCER_IMPLEMENTATION_PATHS:
        path = repo / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative_path + "\n", encoding="utf-8")
    _write_json(repo / transaction.HOST_RECORD_REFERENCE, {"codex": {"product_name": "Codex"}})
    _write_json(repo / transaction.SELECTORS_REFERENCE, {"host_compatibility": {}})
    _write_json(
        output / "actual-host" / "qualification.json",
        {
            "schema_version": "r6o-h2-f3-current-actual-host-pending-1",
            "gate": "H2-F3",
            "status": "HUMAN_PENDING",
        },
    )


def _fake_transaction_command(
    repo: Path,
    calls: list[str],
    *,
    attachment_schema: str = transaction.ATTACHMENT_RESULT_SCHEMA,
) -> Callable[..., subprocess.CompletedProcess[str]]:
    def run(
        arguments: list[str],
        *,
        repo: Path,
        environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del environment
        script = Path(arguments[1]).name
        calls.append(script)
        if script == "reset_codex_test_session.py":
            output_path = repo / arguments[arguments.index("--output") + 1]
            selectors_path = repo / transaction.SELECTORS_REFERENCE
            _write_json(
                output_path,
                {
                    "schema_version": "r6o-h2-d1-reset-log-1",
                    "status": "CODEX_TEST_SESSION_READY",
                    "selectors_sha256": hashlib.sha256(selectors_path.read_bytes()).hexdigest(),
                },
            )
        else:
            evidence_dir = repo / arguments[arguments.index("--evidence-dir") + 1]
            event_log = evidence_dir / "win32-uia-events.jsonl"
            event_log.parent.mkdir(parents=True, exist_ok=True)
            event_log.write_bytes(b'{"sequence":1}\n')
            _write_json(
                evidence_dir / "attachment-result.json",
                {
                    "schema_version": attachment_schema,
                    "gate": transaction.ATTACHMENT_RESULT_GATE,
                    "status": transaction.ATTACHMENT_RESULT_PASS,
                    "real_codex_host_tested": True,
                    "synthetic_owner_used": False,
                    "event_log": {
                        "path": event_log.relative_to(repo).as_posix(),
                        "sha256": hashlib.sha256(event_log.read_bytes()).hexdigest(),
                    },
                    "host_record_sha256": hashlib.sha256(
                        (repo / transaction.HOST_RECORD_REFERENCE).read_bytes()
                    ).hexdigest(),
                    "selectors_sha256": hashlib.sha256(
                        (repo / transaction.SELECTORS_REFERENCE).read_bytes()
                    ).hexdigest(),
                    "implementation_sha256": {
                        relative_path: hashlib.sha256((repo / relative_path).read_bytes()).hexdigest()
                        for relative_path in transaction.PRODUCER_IMPLEMENTATION_PATHS
                    },
                },
            )
        return subprocess.CompletedProcess(arguments, 0, stdout="PASS", stderr="")

    return run


def test_canonical_transaction_produces_only_a_complete_active_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    freeze = {"head": "1" * 40, "tree": "2" * 40}
    repo = tmp_path / "pass" / "repo"
    output = repo / "r6o_evidence" / "H2-F3" / "repair"
    _write_transaction_inputs(repo, output)
    calls: list[str] = []
    monkeypatch.setattr(transaction, "_candidate_identity", lambda _: dict(freeze))
    monkeypatch.setattr(transaction, "_run_command", _fake_transaction_command(repo, calls))

    provenance = transaction.run_canonical_transaction(repo=repo, output=output)
    assert calls == ["reset_codex_test_session.py", "verify_codex_attachment.py"]
    assert provenance["candidate_head"] == freeze["head"]
    assert provenance["candidate_tree"] == freeze["tree"]
    assert provenance["reset_to_attachment_contiguous_machine_flow"] is True
    assert provenance["producer_implementation_sha256"] == {
        path: hashlib.sha256((repo / path).read_bytes()).hexdigest()
        for path in transaction.PRODUCER_IMPLEMENTATION_PATHS
    }
    aggregate = json.loads(
        (output / "actual-host" / "qualification.json").read_text(encoding="utf-8")
    )
    attachment_path = output / transaction.ATTACHMENT_REFERENCE
    attachment = json.loads(attachment_path.read_text(encoding="utf-8"))
    assert aggregate["f3_attachment_provenance"] == transaction.PROVENANCE_REFERENCE
    assert verifier._validate_f3_attachment_provenance(
        repo=repo,
        output=output,
        qualification=aggregate,
        freeze=freeze,
        attachment_path=attachment_path,
        attachment_result=attachment,
    ) == {"status": "PASS", "path": transaction.PROVENANCE_REFERENCE}
    _write_json(
        output / "actual-host" / "qualification.json",
        {"schema_version": "semantic-summary", "status": "HUMAN_COLLECTION_COMPLETE"},
    )
    relinked = transaction.link_existing_provenance(repo=repo, output=output)
    assert relinked["status"] == "HUMAN_COLLECTION_COMPLETE"
    assert relinked["f3_attachment_provenance"] == transaction.PROVENANCE_REFERENCE
    relinked.pop("f3_attachment_provenance")
    _write_json(output / "actual-host" / "qualification.json", relinked)
    provenance["event_log_sha256"] = "0" * 64
    _write_json(output / transaction.PROVENANCE_REFERENCE, provenance)
    with pytest.raises(transaction.F3AttachmentTransactionError) as exc_info:
        transaction.link_existing_provenance(repo=repo, output=output)
    assert exc_info.value.dimension == "EXISTING_PROVENANCE_COMPLETE_CHAIN"
    unlinked = json.loads(
        (output / "actual-host" / "qualification.json").read_text(encoding="utf-8")
    )
    assert "f3_attachment_provenance" not in unlinked
    assert unlinked["status"] == "HUMAN_COLLECTION_COMPLETE"

    failed_repo = tmp_path / "fail" / "repo"
    failed_output = failed_repo / "r6o_evidence" / "H2-F3" / "repair"
    _write_transaction_inputs(failed_repo, failed_output)
    monkeypatch.setattr(
        transaction,
        "_run_command",
        _fake_transaction_command(failed_repo, [], attachment_schema="wrong-schema"),
    )
    with pytest.raises(transaction.F3AttachmentTransactionError):
        transaction.run_canonical_transaction(repo=failed_repo, output=failed_output)
    assert not (failed_output / transaction.PROVENANCE_REFERENCE).exists()
    failed_aggregate = json.loads(
        (failed_output / "actual-host" / "qualification.json").read_text(encoding="utf-8")
    )
    assert "f3_attachment_provenance" not in failed_aggregate


def test_current_actual_host_wrong_revision_fails_closed(tmp_path: Path) -> None:
    freeze = {"head": "1" * 40, "tree": "2" * 40}
    repo = tmp_path / "repo"
    output = repo / "r6o_evidence" / "H2-F3" / "repair"
    _write_current_host_fixture(repo, output, freeze)
    path = output / "actual-host" / "a02-full" / "qualification.json"
    a02 = json.loads(path.read_text(encoding="utf-8"))
    a02["input_envelopes"][1]["text"] = "wrong revision"
    _write_json(path, a02)
    with pytest.raises(verifier.FinalIntegrationError) as exc_info:
        verifier._validate_current_host_evidence(
            repo=repo,
            output=output,
            freeze=freeze,
        )
    _assert_diagnostic(exc_info)
    assert exc_info.value.dimension == "CURRENT_A02_REVISION"


def _load_attachment_chain(
    output: Path,
) -> tuple[Path, dict[str, Any], Path, dict[str, Any]]:
    attachment_path = output / "actual-host" / "attachment" / "attachment-result.json"
    provenance_path = output / "actual-host" / "attachment" / "f3-provenance.json"
    return (
        attachment_path,
        json.loads(attachment_path.read_text(encoding="utf-8")),
        provenance_path,
        json.loads(provenance_path.read_text(encoding="utf-8")),
    )


def _assert_current_chain_fails(
    *,
    repo: Path,
    output: Path,
    freeze: dict[str, str],
    dimension: str,
) -> None:
    with pytest.raises(verifier.FinalIntegrationError) as exc_info:
        verifier._validate_current_host_evidence(
            repo=repo,
            output=output,
            freeze=freeze,
        )
    _assert_diagnostic(exc_info)
    assert exc_info.value.dimension == dimension


def _assert_preflight_contract_tamper_fails(
    *,
    root: Path,
    freeze: dict[str, str],
    scenario: str,
    dimension: str,
) -> None:
    repo = root / "repo"
    output = repo / "r6o_evidence" / "H2-F3" / "repair"
    _write_current_host_fixture(repo, output, freeze)
    reset_path = output / "actual-host" / "preflight-reset.json"
    reset = json.loads(reset_path.read_text(encoding="utf-8"))
    provenance_path = output / transaction.PROVENANCE_REFERENCE
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))

    if scenario == "path":
        provenance["preflight_reset_path"] = "r6o_evidence/H2-D1/reset-session.log"
    elif scenario == "hash":
        provenance["preflight_reset_sha256"] = "0" * 64
    elif scenario == "schema":
        reset["schema_version"] = "wrong-reset-schema"
    elif scenario == "selectors":
        reset["selectors_sha256"] = "0" * 64
    elif scenario == "status":
        reset["status"] = "FAIL"
    else:  # pragma: no cover - the explicit contract cases are exhaustive
        raise AssertionError(scenario)

    if scenario in {"schema", "selectors", "status"}:
        _write_json(reset_path, reset)
        provenance["preflight_reset_sha256"] = hashlib.sha256(
            reset_path.read_bytes()
        ).hexdigest()
    _write_json(provenance_path, provenance)
    _assert_current_chain_fails(
        repo=repo,
        output=output,
        freeze=freeze,
        dimension=dimension,
    )


@pytest.mark.parametrize(
    ("scenario", "dimension"),
    [
        ("attachment_schema", "F3_ATTACHMENT_RESULT_SCHEMA_VERSION"),
        ("attachment_gate", "F3_ATTACHMENT_RESULT_GATE"),
        ("candidate_identity", "F3_ATTACHMENT_CANDIDATE_HEAD"),
        ("attachment_artifact_binding", "F3_ATTACHMENT_ATTACHMENT_RESULT_PATH"),
        ("nested_event_log_binding", "F3_ATTACHMENT_EVENT_LOG_RESULT_PATH_BINDING"),
        ("preflight_contract", "F3_ATTACHMENT_PREFLIGHT_SCHEMA"),
        ("producer_input_binding", "F3_ATTACHMENT_HOST_RECORD_PATH"),
        ("attachment_status", "ACTUAL_HOST_ATTACHMENT_STATUS"),
        ("real_host_flag", "ACTUAL_HOST_RUNTIME_IDENTITY"),
        ("synthetic_owner_flag", "ACTUAL_HOST_RUNTIME_IDENTITY"),
        ("contiguous_flow", "F3_ATTACHMENT_RESET_TO_ATTACHMENT_CONTIGUOUS_MACHINE_FLOW"),
        ("producer_identity", "F3_ATTACHMENT_IMPLEMENTATION_HASH"),
    ],
)
def test_contract_tampering_matrix_fails_closed(
    tmp_path: Path,
    scenario: str,
    dimension: str,
) -> None:
    freeze = {"head": "1" * 40, "tree": "2" * 40}
    if scenario == "preflight_contract":
        _assert_preflight_contract_tamper_fails(
            root=tmp_path / "path",
            freeze=freeze,
            scenario="path",
            dimension="F3_ATTACHMENT_PREFLIGHT_RESET_PATH",
        )
        _assert_preflight_contract_tamper_fails(
            root=tmp_path / "hash",
            freeze=freeze,
            scenario="hash",
            dimension="F3_ATTACHMENT_PREFLIGHT_RESET_HASH",
        )
        _assert_preflight_contract_tamper_fails(
            root=tmp_path / "schema",
            freeze=freeze,
            scenario="schema",
            dimension="F3_ATTACHMENT_PREFLIGHT_SCHEMA",
        )
        _assert_preflight_contract_tamper_fails(
            root=tmp_path / "selectors",
            freeze=freeze,
            scenario="selectors",
            dimension="F3_ATTACHMENT_PREFLIGHT_SELECTORS_HASH",
        )
        _assert_preflight_contract_tamper_fails(
            root=tmp_path / "status",
            freeze=freeze,
            scenario="status",
            dimension="F3_ATTACHMENT_PREFLIGHT_STATUS",
        )
        return

    repo = tmp_path / "repo"
    output = repo / "r6o_evidence" / "H2-F3" / "repair"
    _write_current_host_fixture(repo, output, freeze)
    attachment_path, attachment, provenance_path, provenance = _load_attachment_chain(output)

    if scenario == "attachment_schema":
        attachment["schema_version"] = "wrong-schema"
    elif scenario == "attachment_gate":
        attachment["gate"] = "WRONG-GATE"
    elif scenario == "candidate_identity":
        provenance["candidate_head"] = "0" * 40
        provenance["candidate_tree"] = "0" * 40
    elif scenario == "attachment_artifact_binding":
        provenance["attachment_result_path"] = "r6o_evidence/H2-D2/attachment-result.json"
        provenance["attachment_result_sha256"] = "0" * 64
    elif scenario == "nested_event_log_binding":
        attachment["event_log"] = {
            "path": "r6o_evidence/H2-D2/win32-uia-events.jsonl",
            "sha256": "0" * 64,
        }
    elif scenario == "producer_input_binding":
        provenance["host_record_path"] = "r6o_evidence/H2-D1/wrong-host.json"
        provenance["host_record_sha256"] = "0" * 64
        provenance["selectors_path"] = "r6o/host/codex/windows/wrong-selectors.json"
        provenance["selectors_sha256"] = "0" * 64
    elif scenario == "attachment_status":
        attachment["status"] = "FAIL"
    elif scenario == "real_host_flag":
        attachment["real_codex_host_tested"] = False
    elif scenario == "synthetic_owner_flag":
        attachment["synthetic_owner_used"] = True
    elif scenario == "contiguous_flow":
        provenance["reset_to_attachment_contiguous_machine_flow"] = False
    elif scenario == "producer_identity":
        attachment["implementation_sha256"]["scripts/h2/verify_codex_attachment.py"] = "0" * 64
        provenance["producer_implementation_sha256"]["scripts/h2/verify_codex_attachment.py"] = "0" * 64
    else:  # pragma: no cover - the parameter table is exhaustive
        raise AssertionError(scenario)

    if scenario in {
        "attachment_schema",
        "attachment_gate",
        "nested_event_log_binding",
        "attachment_status",
        "real_host_flag",
        "synthetic_owner_flag",
        "producer_identity",
    }:
        _write_json(attachment_path, attachment)
        provenance["attachment_result_sha256"] = hashlib.sha256(
            attachment_path.read_bytes()
        ).hexdigest()
    _write_json(provenance_path, provenance)
    _assert_current_chain_fails(
        repo=repo,
        output=output,
        freeze=freeze,
        dimension=dimension,
    )


def test_chain_topology_matrix_fails_closed(tmp_path: Path) -> None:
    freeze = {"head": "1" * 40, "tree": "2" * 40}

    missing_repo = tmp_path / "missing" / "repo"
    missing_output = missing_repo / "r6o_evidence" / "H2-F3" / "repair"
    _write_current_host_fixture(missing_repo, missing_output, freeze)
    (missing_output / transaction.PROVENANCE_REFERENCE).unlink()
    _assert_current_chain_fails(
        repo=missing_repo,
        output=missing_output,
        freeze=freeze,
        dimension="F3_ATTACHMENT_PROVENANCE_RECORD",
    )

    unlinked_repo = tmp_path / "unlinked" / "repo"
    unlinked_output = unlinked_repo / "r6o_evidence" / "H2-F3" / "repair"
    _write_current_host_fixture(unlinked_repo, unlinked_output, freeze)
    unlinked_path = unlinked_output / "actual-host" / "qualification.json"
    unlinked = json.loads(unlinked_path.read_text(encoding="utf-8"))
    unlinked.pop("f3_attachment_provenance")
    _write_json(unlinked_path, unlinked)
    _assert_current_chain_fails(
        repo=unlinked_repo,
        output=unlinked_output,
        freeze=freeze,
        dimension="F3_ATTACHMENT_PROVENANCE_REFERENCE",
    )

    wrong_repo = tmp_path / "wrong" / "repo"
    wrong_output = wrong_repo / "r6o_evidence" / "H2-F3" / "repair"
    _write_current_host_fixture(wrong_repo, wrong_output, freeze)
    wrong_path = wrong_output / "actual-host" / "qualification.json"
    wrong = json.loads(wrong_path.read_text(encoding="utf-8"))
    wrong["f3_attachment_provenance"] = "actual-host/attachment/not-current.json"
    _write_json(wrong_path, wrong)
    _assert_current_chain_fails(
        repo=wrong_repo,
        output=wrong_output,
        freeze=freeze,
        dimension="F3_ATTACHMENT_PROVENANCE_REFERENCE",
    )


def test_current_history_isolation_matrix(tmp_path: Path) -> None:
    freeze = {"head": "1" * 40, "tree": "2" * 40}

    current_pass_repo = tmp_path / "current-pass" / "repo"
    current_pass_output = current_pass_repo / "r6o_evidence" / "H2-F3" / "repair"
    _write_current_host_fixture(current_pass_repo, current_pass_output, freeze)
    _write_json(
        current_pass_output / "actual-host" / "attachment" / "history" / "failed.json",
        {"attachment_status": "FAIL"},
    )
    assert verifier._validate_current_host_evidence(
        repo=current_pass_repo,
        output=current_pass_output,
        freeze=freeze,
    )["status"] == "PASS"

    current_fail_repo = tmp_path / "current-fail" / "repo"
    current_fail_output = current_fail_repo / "r6o_evidence" / "H2-F3" / "repair"
    _write_current_host_fixture(current_fail_repo, current_fail_output, freeze)
    _write_json(
        current_fail_output / "actual-host" / "attachment" / "history" / "passed.json",
        {"attachment_status": "H2_D2_ATTACHMENT_PASS"},
    )
    provenance_path = current_fail_output / transaction.PROVENANCE_REFERENCE
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["attachment_status"] = "FAIL"
    _write_json(provenance_path, provenance)
    _assert_current_chain_fails(
        repo=current_fail_repo,
        output=current_fail_output,
        freeze=freeze,
        dimension="F3_ATTACHMENT_ATTACHMENT_STATUS",
    )
