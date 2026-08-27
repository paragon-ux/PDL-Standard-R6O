from __future__ import annotations

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
