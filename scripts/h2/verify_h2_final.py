from __future__ import annotations

"""Fail-closed final H2 integration and evidence verifier."""

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_ROOT = ROOT / "r6o_evidence"
DEFAULT_OUTPUT = EVIDENCE_ROOT / "H2-F3"
DEFAULT_BASE_RECORD = DEFAULT_OUTPUT / "base.json"
DEFAULT_CODE_FREEZE_RECORD = DEFAULT_OUTPUT / "code-freeze.json"
DEFAULT_CI_RECORD = DEFAULT_OUTPUT / "ci.json"
DEFAULT_QT_RECORD = DEFAULT_OUTPUT / "qt-qualification.json"
DEFAULT_HOST_RECORD = DEFAULT_OUTPUT / "actual-host" / "qualification.json"
DEFAULT_LOCAL_RECORD = DEFAULT_OUTPUT / "local-qualification.json"

FROZEN_ORACLE_COMMIT = "60d982f3328b45a351879d67dc4bb525172b65fd"
FROZEN_ORACLE_TREE = "b7689fbe8b9c9838438cbba6f6e0e5c1ce5b5ed6"
R6O1_QUALIFIED_CODE = "5da375e81e0d0d194d79eadd7cf1ad8c269b066a"

CURRENT_HOST = {
    "package_version": "26.818.5229.0",
    "product_version": "151.0.7922.170",
    "file_version": "151.0.7922.170",
}

PROTECTED_PREFIXES = (
    "r6o/model_binding/",
    "r6o/viewmodel/",
    "r6o/contracts/",
    "r6o_evidence/R6O-1/",
)

F3_EVIDENCE_PREFIXES = (
    "r6o_evidence/H2-F3/",
    "r6o_evidence/H2/H2-HUMAN-GATE-RECORD.json",
)

ACCEPTED_HEADS = {
    "H2-D1R": "ab5282ab4adfa838e0a95980c7b395f8f8196623",
    "H2-E1": "8a85ac4214e7b3386c3c8079b0d45fb79a97e9ff",
    "H2-E2": "1b46da916aec20aa2a27e533ac5e8aff9f360791",
    "H2-E3": "9bd10391a349225a5121736b06470fe978741e3a",
    "H2-F1": "772f97227b70d673b6de624141353cc4ea59f653",
    "H2-F2": "63f04151a97cc8fb9fe8bec96d4562c548744fbb",
}

ACCEPTED_CODE_FREEZES = {
    "H2-E1": (
        "c488a8173d2bc5ca2251470c3cad24db7fcb4a95",
        "dd65095aeef9ec406a14b4890346fbed92d13c1b",
    ),
    "H2-E2": (
        "8e8f325c31b8d96d31cd7fea901a0790d5086bf6",
        "ca7530b0ece301c6783877ab049daac884062989",
    ),
    "H2-E3": (
        "d94a1aa0c99056ec81f10c6a41e73ed6ea438ae3",
        "9fec4c41ed0228e3d4e71c9e19a846c92447c69e",
    ),
    "H2-F2": (
        "27cbce651ccacd3dc18f90a2684bb87d19582534",
        "ab7fc624679498d48310edde008ea001c13e9552",
    ),
}

EXPECTED_F2_EVIDENCE_TREE = "59e10dc1eeca86c3c2393a63b02eae4cc8c1cd2a"
EXPECTED_F2_FREEZE_HEAD = "27cbce651ccacd3dc18f90a2684bb87d19582534"
EXPECTED_F2_FREEZE_TREE = "ab7fc624679498d48310edde008ea001c13e9552"
EXPECTED_E3_LIVE_HEAD = "d94a1aa0c99056ec81f10c6a41e73ed6ea438ae3"
EXPECTED_E3_LIVE_TREE = "9fec4c41ed0228e3d4e71c9e19a846c92447c69e"

G06_OPERATIONS = [
    ("G06:0001", "DRAFT_PROMPT"),
    ("G06:0002", "INTERPRET_PROMPT_REVIEW"),
    ("G06:0003", "DRAFT_PLAN"),
    ("G06:0004", "INTERPRET_PLAN_REVIEW"),
    ("G06:0005", "EXECUTE"),
]
A02_OPERATIONS = [
    ("A02F:0001", "DRAFT_PROMPT"),
    ("A02F:0002", "INTERPRET_PROMPT_REVIEW"),
    ("A02F:0003", "REVISE_PROMPT"),
    ("A02F:0004", "INTERPRET_PROMPT_REVIEW"),
    ("A02F:0005", "DRAFT_PLAN"),
    ("A02F:0006", "INTERPRET_PLAN_REVIEW"),
    ("A02F:0007", "EXECUTE"),
]
REVISION_TEXT = (
    "This is not confirmed. The audience should be data engineers, not backend engineers."
)


class FinalIntegrationError(AssertionError):
    """Stable fail-closed F3 diagnostic."""

    def __init__(
        self,
        gate: str,
        dimension: str,
        expected: object,
        actual: object,
        source_identity: object,
    ) -> None:
        self.gate = gate
        self.dimension = dimension
        self.expected = expected
        self.actual = actual
        self.source_identity = source_identity
        super().__init__(
            "GATE="
            + gate
            + " DIMENSION="
            + dimension
            + " EXPECTED="
            + _display(expected)
            + " ACTUAL="
            + _display(actual)
            + " SOURCE_IDENTITY="
            + _display(source_identity)
        )


def _display(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _fail(
    dimension: str,
    expected: object,
    actual: object,
    source_identity: object,
    *,
    gate: str = "H2-F3",
) -> None:
    raise FinalIntegrationError(gate, dimension, expected, actual, source_identity)


def _require(
    condition: bool,
    dimension: str,
    expected: object,
    actual: object,
    source_identity: object,
    *,
    gate: str = "H2-F3",
) -> None:
    if not condition:
        _fail(dimension, expected, actual, source_identity, gate=gate)


def _read_json(path: Path, *, gate: str, dimension: str) -> dict[str, Any]:
    source = {"path": path.as_posix()}
    if not path.is_file():
        _fail(dimension, "JSON file", "MISSING", source, gate=gate)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _fail(dimension, "valid JSON", repr(exc), source, gate=gate)
    if not isinstance(value, dict):
        _fail(dimension, "JSON object", type(value).__name__, source, gate=gate)
    return value


def _read_json_value(path: Path, *, gate: str, dimension: str) -> object:
    source = {"path": path.as_posix()}
    if not path.is_file():
        _fail(dimension, "JSON file", "MISSING", source, gate=gate)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _fail(dimension, "valid JSON", repr(exc), source, gate=gate)


def _value(document: dict[str, Any], path: str, *, gate: str, dimension: str) -> Any:
    current: Any = document
    for component in path.split("."):
        if not isinstance(current, dict) or component not in current:
            _fail(
                dimension,
                f"field {path}",
                "MISSING",
                {"gate": gate, "field": path},
                gate=gate,
            )
        current = current[component]
    return current


def _json_write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        _fail("FILE_HASH", "readable file", repr(exc), {"path": path.as_posix()})


def _git(repo: Path, *arguments: str, gate: str = "H2-F3") -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        _fail(
            "GIT_PROVENANCE",
            "successful git command",
            {"arguments": list(arguments), "stderr": result.stderr.strip()},
            {"repo": repo.as_posix()},
            gate=gate,
        )
    return result.stdout.strip()


def _git_tree(repo: Path, revision: str) -> str:
    return _git(repo, "rev-parse", "--verify", f"{revision}^{{tree}}")


def _is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repo), "merge-base", "--is-ancestor", ancestor, descendant],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _git_blob(repo: Path, revision: str, relative_path: str) -> str:
    return _git(repo, "rev-parse", "--verify", f"{revision}:{relative_path}")


def _git_hash_object(repo: Path, path: Path) -> str:
    return _git(repo, "hash-object", "--", str(path))


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _repo_relative(repo: Path, path: Path) -> str | None:
    try:
        return path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return None


def _untracked(repo: Path) -> list[str]:
    output = _git(repo, "ls-files", "--others", "--exclude-standard")
    return [line for line in output.splitlines() if line]


def _changed_paths_from(repo: Path, revision: str) -> list[str]:
    output = _git(repo, "diff", "--name-only", revision, "--")
    paths = [line.replace("\\", "/") for line in output.splitlines() if line]
    paths.extend(path.replace("\\", "/") for path in _untracked(repo))
    return sorted(set(paths))


def _protected_paths(paths: Iterable[str]) -> list[str]:
    return sorted(
        path
        for path in paths
        if any(path.startswith(prefix) for prefix in PROTECTED_PREFIXES)
    )


def _source_identity(repo: Path) -> dict[str, Any]:
    return {
        "branch": _git(repo, "branch", "--show-current"),
        "head": _git(repo, "rev-parse", "HEAD"),
        "tree": _git_tree(repo, "HEAD"),
        "dirty_paths": _changed_paths_from(repo, "HEAD"),
    }


def _assert_evidence_file(
    *,
    repo: Path,
    evidence_root: Path,
    relative_path: str,
    accepted_head: str,
    gate: str,
) -> Path:
    path = evidence_root / Path(relative_path)
    if not path.is_file():
        _fail(
            "MISSING_ACCEPTED_EVIDENCE",
            "present accepted evidence file",
            "MISSING",
            {"gate": gate, "path": relative_path, "accepted_head": accepted_head},
            gate=gate,
        )
    repo_relative = _repo_relative(repo, path)
    if repo_relative is not None:
        expected_blob = _git_blob(repo, accepted_head, repo_relative)
        actual_blob = _git_hash_object(repo, path)
        _require(
            actual_blob == expected_blob,
            "ACCEPTED_EVIDENCE_BLOB",
            expected_blob,
            actual_blob,
            {"gate": gate, "path": repo_relative, "accepted_head": accepted_head},
            gate=gate,
        )
    return path


def _validate_base(
    *, repo: Path, base_record: Path, current: dict[str, Any]
) -> dict[str, Any]:
    document = _read_json(base_record, gate="H2-F3", dimension="F3_BASE_RECORD")
    _require(
        document.get("schema_version") == "r6o-h2-f3-base-1",
        "F3_BASE_RECORD_SCHEMA",
        "r6o-h2-f3-base-1",
        document.get("schema_version"),
        {"path": base_record.as_posix()},
    )
    _require(document.get("gate") == "H2-F3", "F3_BASE_GATE", "H2-F3", document.get("gate"), base_record.as_posix())
    base = document.get("base")
    _require(isinstance(base, dict), "F3_BASE_IDENTITY", "base object", base, base_record.as_posix())
    assert isinstance(base, dict)
    base_head = base.get("head")
    base_tree = base.get("tree")
    _require(isinstance(base_head, str) and len(base_head) == 40, "F3_BASE_HEAD", "40-char SHA", base_head, base_record.as_posix())
    _require(isinstance(base_tree, str) and len(base_tree) == 40, "F3_BASE_TREE", "40-char tree", base_tree, base_record.as_posix())
    actual_tree = _git_tree(repo, base_head)
    _require(actual_tree == base_tree, "F3_BASE_TREE_IDENTITY", base_tree, actual_tree, {"base_head": base_head})
    _require(_is_ancestor(repo, base_head, current["head"]), "F3_BASE_ANCESTRY", "base is ancestor of current head", {"base": base_head, "current": current["head"]}, base_record.as_posix())
    origin_main = _git(repo, "rev-parse", "origin/main")
    _require(origin_main == base_head, "F3_BASE_ORIGIN_MAIN", base_head, origin_main, {"record": base_record.as_posix(), "current": current["head"]})
    _require(document.get("recorded_before_edit") is True, "F3_BASE_RECORD_TIMING", True, document.get("recorded_before_edit"), base_record.as_posix())
    return {"head": base_head, "tree": base_tree, "record": base_record.as_posix()}


def _validate_code_freeze(*, repo: Path, record_path: Path, base: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    document = _read_json(record_path, gate="H2-F3", dimension="F3_CODE_FREEZE_RECORD")
    _require(document.get("schema_version") == "r6o-h2-f3-code-freeze-1", "F3_CODE_FREEZE_SCHEMA", "r6o-h2-f3-code-freeze-1", document.get("schema_version"), record_path.as_posix())
    _require(document.get("gate") == "H2-F3", "F3_CODE_FREEZE_GATE", "H2-F3", document.get("gate"), record_path.as_posix())
    freeze = document.get("code_freeze")
    _require(isinstance(freeze, dict), "F3_CODE_FREEZE_IDENTITY", "code_freeze object", freeze, record_path.as_posix())
    assert isinstance(freeze, dict)
    head = freeze.get("head")
    tree = freeze.get("tree")
    _require(freeze.get("status") == "FROZEN", "F3_CODE_FREEZE_STATUS", "FROZEN", freeze.get("status"), record_path.as_posix())
    _require(isinstance(head, str) and len(head) == 40, "F3_CODE_FREEZE_HEAD", "40-char SHA", head, record_path.as_posix())
    _require(isinstance(tree, str) and len(tree) == 40, "F3_CODE_FREEZE_TREE", "40-char tree", tree, record_path.as_posix())
    actual_tree = _git_tree(repo, head)
    _require(actual_tree == tree, "F3_CODE_FREEZE_TREE_IDENTITY", tree, actual_tree, {"freeze_head": head})
    _require(_is_ancestor(repo, head, current["head"]), "F3_CODE_FREEZE_ANCESTRY", "freeze is ancestor of current head", {"freeze": head, "current": current["head"]}, record_path.as_posix())
    _require(_is_ancestor(repo, base["head"], head), "F3_CODE_FREEZE_BASE", base["head"], head, record_path.as_posix())
    post_freeze = _changed_paths_from(repo, head)
    forbidden_after_freeze = [
        path
        for path in post_freeze
        if not any(path.startswith(prefix) for prefix in F3_EVIDENCE_PREFIXES)
    ]
    _require(
        not forbidden_after_freeze,
        "F3_POST_FREEZE_SCOPE",
        list(F3_EVIDENCE_PREFIXES),
        forbidden_after_freeze,
        {"freeze_head": head, "current_head": current["head"]},
    )
    return {"head": head, "tree": tree, "status": "FROZEN", "record": record_path.as_posix()}


def _validate_ancestry(*, repo: Path, current_head: str) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for gate, accepted_head in ACCEPTED_HEADS.items():
        _require(
            _is_ancestor(repo, accepted_head, current_head),
            "PREDECESSOR_ANCESTRY",
            f"{accepted_head} is an ancestor of {current_head}",
            {"gate": gate, "accepted_head": accepted_head, "current_head": current_head},
            {"accepted_head": accepted_head, "current_head": current_head},
            gate=gate,
        )
        results[gate] = {"accepted_head": accepted_head, "tree": _git_tree(repo, accepted_head)}

    for gate, (head, expected_tree) in ACCEPTED_CODE_FREEZES.items():
        actual_tree = _git_tree(repo, head)
        _require(actual_tree == expected_tree, "ACCEPTED_FREEZE_TREE", expected_tree, actual_tree, {"gate": gate, "head": head}, gate=gate)
        _require(_is_ancestor(repo, head, current_head), "ACCEPTED_FREEZE_ANCESTRY", f"{head} is an ancestor of {current_head}", {"head": head, "current_head": current_head}, {"gate": gate}, gate=gate)
        results[gate]["code_freeze"] = {"head": head, "tree": expected_tree}

    f2_tree = _git_tree(repo, ACCEPTED_HEADS["H2-F2"])
    _require(f2_tree == EXPECTED_F2_EVIDENCE_TREE, "F2_ACCEPTED_EVIDENCE_TREE", EXPECTED_F2_EVIDENCE_TREE, f2_tree, {"head": ACCEPTED_HEADS["H2-F2"]}, gate="H2-F2")
    _require(_git_tree(repo, EXPECTED_F2_FREEZE_HEAD) == EXPECTED_F2_FREEZE_TREE, "F2_SECOND_REPAIR_FREEZE_TREE", EXPECTED_F2_FREEZE_TREE, _git_tree(repo, EXPECTED_F2_FREEZE_HEAD), {"head": EXPECTED_F2_FREEZE_HEAD}, gate="H2-F2")
    _require(_git_tree(repo, EXPECTED_E3_LIVE_HEAD) == EXPECTED_E3_LIVE_TREE, "E3_LIVE_FREEZE_TREE", EXPECTED_E3_LIVE_TREE, _git_tree(repo, EXPECTED_E3_LIVE_HEAD), {"head": EXPECTED_E3_LIVE_HEAD}, gate="H2-E3")
    return results


def _validate_protected_boundary(*, repo: Path, base: dict[str, Any]) -> dict[str, Any]:
    from_base = _changed_paths_from(repo, base["head"])
    protected = sorted(set(_protected_paths(from_base)))
    _require(not protected, "PROTECTED_PATH_DIFF", [], protected, {"base": base["head"], "r6o1": R6O1_QUALIFIED_CODE})
    return {
        "status": "EMPTY",
        "compared_to_f3_base": base["head"],
        "historical_r6o1_authority": R6O1_QUALIFIED_CODE,
        "changed_protected_paths": [],
    }


def _validate_oracle(*, oracle: Path) -> dict[str, Any]:
    oracle = oracle.resolve()
    _require(oracle.is_dir(), "FROZEN_ORACLE_PATH", "existing directory", oracle.as_posix(), oracle.as_posix())
    commit = _git(oracle, "rev-parse", "HEAD", gate="R6S")
    tree = _git_tree(oracle, "HEAD")
    status = _git(oracle, "status", "--porcelain", "--untracked-files=all", gate="R6S")
    _require(commit == FROZEN_ORACLE_COMMIT, "FROZEN_ORACLE_COMMIT", FROZEN_ORACLE_COMMIT, commit, oracle.as_posix(), gate="R6S")
    _require(tree == FROZEN_ORACLE_TREE, "FROZEN_ORACLE_TREE", FROZEN_ORACLE_TREE, tree, oracle.as_posix(), gate="R6S")
    _require(not status, "FROZEN_ORACLE_CLEAN", "clean", status, {"oracle": oracle.as_posix(), "commit": commit}, gate="R6S")
    _require((oracle / "scripts" / "verify_repl_baseline.py").is_file(), "FROZEN_ORACLE_CONTRACT", "verify_repl_baseline.py", "MISSING", oracle.as_posix(), gate="R6S")
    return {"commit": commit, "tree": tree, "status": "UNCHANGED", "path": oracle.as_posix()}


def _validate_oracle_fields(document: dict[str, Any], *, gate: str, path: str) -> None:
    frozen = document.get("frozen_r6s") or document.get("frozen_oracle")
    if isinstance(frozen, dict):
        commit = frozen.get("commit")
        tree = frozen.get("tree")
    else:
        commit = document.get("oracle_commit")
        tree = document.get("oracle_tree")
    if commit is None and tree is None:
        frozen = document
        commit = frozen.get("commit")
        tree = frozen.get("tree")
    _require(commit == FROZEN_ORACLE_COMMIT, "EVIDENCE_ORACLE_COMMIT", FROZEN_ORACLE_COMMIT, commit, {"gate": gate, "path": path}, gate=gate)
    _require(tree == FROZEN_ORACLE_TREE, "EVIDENCE_ORACLE_TREE", FROZEN_ORACLE_TREE, tree, {"gate": gate, "path": path}, gate=gate)


def _validate_tui(*, repo: Path, evidence: Path) -> dict[str, str]:
    g06_path = _assert_evidence_file(repo=repo, evidence_root=evidence, relative_path="H2-B1/test-results.json", accepted_head="b29fc48bfb57ef700a1f5f7be9fd5b25be4a22d9", gate="H2-B1")
    a02_path = _assert_evidence_file(repo=repo, evidence_root=evidence, relative_path="H2-B2/test-results.json", accepted_head="4928e73612048fac4b7486b24b7785a79d287e20", gate="H2-B2")
    g06 = _read_json(g06_path, gate="H2-B1", dimension="TUI_G06_EVIDENCE")
    a02 = _read_json(a02_path, gate="H2-B2", dimension="TUI_A02_EVIDENCE")
    for document, gate, operations in ((g06, "H2-B1", G06_OPERATIONS), (a02, "H2-B2", A02_OPERATIONS)):
        _validate_oracle_fields(document, gate=gate, path=(g06_path if gate == "H2-B1" else a02_path).as_posix())
        if "exit_code" in document:
            _require(document.get("exit_code") == 0, "TUI_EXIT_CODE", 0, document.get("exit_code"), gate, gate=gate)
        _require(document.get("final_stage") == "CLOSED_SUCCESS", "TUI_TERMINAL_STAGE", "CLOSED_SUCCESS", document.get("final_stage"), gate, gate=gate)
        _require(document.get("observed_operation_ids") == [item[0] for item in operations], "TUI_OPERATION_SEQUENCE", [item[0] for item in operations], document.get("observed_operation_ids"), gate, gate=gate)
    _require(g06.get("status") == "MECHANICAL_PASS_PENDING_HUMAN", "TUI_G06_STATUS", "MECHANICAL_PASS_PENDING_HUMAN", g06.get("status"), g06_path.as_posix(), gate="H2-B1")
    _require(a02.get("status") == "MECHANICAL_PASS_PENDING_HUMAN", "TUI_A02_STATUS", "MECHANICAL_PASS_PENDING_HUMAN", a02.get("status"), a02_path.as_posix(), gate="H2-B2")
    _require(a02.get("free_response_source") == "TUI_TEXT", "TUI_A02_SOURCE", "TUI_TEXT", a02.get("free_response_source"), a02_path.as_posix(), gate="H2-B2")
    _require(a02.get("free_response_submission_count") == 1, "TUI_A02_SUBMISSION_COUNT", 1, a02.get("free_response_submission_count"), a02_path.as_posix(), gate="H2-B2")
    _require(a02.get("oracle_inventory_unchanged") is True and g06.get("oracle_inventory_unchanged") is True, "TUI_ORACLE_INVENTORY", True, {"g06": g06.get("oracle_inventory_unchanged"), "a02": a02.get("oracle_inventory_unchanged")}, {"g06": g06_path.as_posix(), "a02": a02_path.as_posix()})
    return {"G06": "PASS", "A02-FULL": "PASS"}


def _validate_e1(*, repo: Path, evidence: Path) -> str:
    result_path = _assert_evidence_file(repo=repo, evidence_root=evidence, relative_path="H2-E1/input-routing-result.json", accepted_head=ACCEPTED_HEADS["H2-E1"], gate="H2-E1")
    qualification_path = _assert_evidence_file(repo=repo, evidence_root=evidence, relative_path="H2-E1/qualification.json", accepted_head=ACCEPTED_HEADS["H2-E1"], gate="H2-E1")
    result = _read_json(result_path, gate="H2-E1", dimension="E1_INPUT_ROUTING_EVIDENCE")
    qualification = _read_json(qualification_path, gate="H2-E1", dimension="E1_QUALIFICATION_EVIDENCE")
    _require(result.get("status") == "H2_E1_INPUT_ROUTING_PASS", "E1_STATUS", "H2_E1_INPUT_ROUTING_PASS", result.get("status"), result_path.as_posix(), gate="H2-E1")
    _require(result.get("source", {}).get("head") == "c488a8173d2bc5ca2251470c3cad24db7fcb4a95", "E1_CODE_FREEZE_HEAD", "c488a8173d2bc5ca2251470c3cad24db7fcb4a95", result.get("source", {}).get("head"), result_path.as_posix(), gate="H2-E1")
    _require(result.get("source", {}).get("tree") == ACCEPTED_CODE_FREEZES["H2-E1"][1], "E1_CODE_FREEZE_TREE", ACCEPTED_CODE_FREEZES["H2-E1"][1], result.get("source", {}).get("tree"), result_path.as_posix(), gate="H2-E1")
    _require(qualification.get("actual_e1", {}).get("status") == "H2_E1_INPUT_ROUTING_PASS", "E1_QUALIFICATION_STATUS", "H2_E1_INPUT_ROUTING_PASS", qualification.get("actual_e1", {}).get("status"), qualification_path.as_posix(), gate="H2-E1")
    _require(qualification.get("implementation_complete") is True, "E1_IMPLEMENTATION_COMPLETE", True, qualification.get("implementation_complete"), qualification_path.as_posix(), gate="H2-E1")
    _require(qualification.get("boundary_results", {}).get("oracle_commit") == FROZEN_ORACLE_COMMIT, "E1_ORACLE_COMMIT", FROZEN_ORACLE_COMMIT, qualification.get("boundary_results", {}).get("oracle_commit"), qualification_path.as_posix(), gate="H2-E1")
    return "PASS"


def _validate_host_version(document: dict[str, Any], *, gate: str, path: str) -> None:
    host = document.get("actual_codex_host") or document.get("host") or document.get("codex") or {}
    if not isinstance(host, dict):
        host = {}
    for key, expected in CURRENT_HOST.items():
        _require(host.get(key) == expected, f"{gate}_HOST_{key.upper()}", expected, host.get(key), {"gate": gate, "path": path}, gate=gate)


def _validate_operations(document: dict[str, Any], expected: list[tuple[str, str]], *, gate: str, path: str) -> None:
    operations = document.get("worker_operations")
    normalized = []
    if isinstance(operations, list):
        for item in operations:
            if isinstance(item, dict):
                normalized.append((item.get("operation_id"), item.get("operation")))
    _require(normalized == expected, "WORKER_OPERATION_SEQUENCE", expected, normalized, {"gate": gate, "path": path}, gate=gate)


def _validate_e2(*, repo: Path, evidence: Path) -> str:
    freeze_path = _assert_evidence_file(repo=repo, evidence_root=evidence, relative_path="H2-E2/code-freeze.json", accepted_head=ACCEPTED_HEADS["H2-E2"], gate="H2-E2")
    qualification_path = _assert_evidence_file(repo=repo, evidence_root=evidence, relative_path="H2-E2/actual-host/qualification.json", accepted_head=ACCEPTED_HEADS["H2-E2"], gate="H2-E2")
    attempts_path = _assert_evidence_file(repo=repo, evidence_root=evidence, relative_path="H2-E2/actual-host/live-attempts.json", accepted_head=ACCEPTED_HEADS["H2-E2"], gate="H2-E2")
    freeze = _read_json(freeze_path, gate="H2-E2", dimension="E2_CODE_FREEZE")
    qualification = _read_json(qualification_path, gate="H2-E2", dimension="E2_ACTUAL_HOST")
    attempts = _read_json_value(attempts_path, gate="H2-E2", dimension="E2_ATTEMPTS_JSON")
    _require(freeze.get("code_freeze_head") == ACCEPTED_CODE_FREEZES["H2-E2"][0], "E2_CODE_FREEZE_HEAD", ACCEPTED_CODE_FREEZES["H2-E2"][0], freeze.get("code_freeze_head"), freeze_path.as_posix(), gate="H2-E2")
    _require(freeze.get("code_freeze_tree") == ACCEPTED_CODE_FREEZES["H2-E2"][1], "E2_CODE_FREEZE_TREE", ACCEPTED_CODE_FREEZES["H2-E2"][1], freeze.get("code_freeze_tree"), freeze_path.as_posix(), gate="H2-E2")
    _require(qualification.get("status") == "H2_E2_G06_PASS", "E2_STATUS", "H2_E2_G06_PASS", qualification.get("status"), qualification_path.as_posix(), gate="H2-E2")
    _require(qualification.get("case_id") == "G06", "E2_CASE", "G06", qualification.get("case_id"), qualification_path.as_posix(), gate="H2-E2")
    _validate_host_version(qualification, gate="H2-E2", path=qualification_path.as_posix())
    _validate_oracle_fields(qualification, gate="H2-E2", path=qualification_path.as_posix())
    _validate_operations(qualification, G06_OPERATIONS, gate="H2-E2", path=qualification_path.as_posix())
    _require(qualification.get("native_codex_submission_observed") is False, "E2_NATIVE_SUBMISSION", False, qualification.get("native_codex_submission_observed"), qualification_path.as_posix(), gate="H2-E2")
    _require(qualification.get("sidecar_dismissed") is True and qualification.get("actual_composer_focus_restored") is True, "E2_TERMINAL_FOCUS", {"sidecar_dismissed": True, "actual_composer_focus_restored": True}, {"sidecar_dismissed": qualification.get("sidecar_dismissed"), "actual_composer_focus_restored": qualification.get("actual_composer_focus_restored")}, qualification_path.as_posix(), gate="H2-E2")
    if isinstance(attempts, dict):
        attempts = [attempts]
    _require(isinstance(attempts, list), "E2_ATTEMPTS_SCHEMA", "list or single attempt object", type(attempts).__name__, attempts_path.as_posix(), gate="H2-E2")
    matching = [item for item in attempts if isinstance(item, dict) and item.get("status") == "H2_E2_G06_PASS"]
    _require(len(matching) == 1, "E2_PASS_ATTEMPT_COUNT", 1, len(matching), attempts_path.as_posix(), gate="H2-E2")
    _require(matching[0].get("code_freeze_head") == ACCEPTED_CODE_FREEZES["H2-E2"][0] and matching[0].get("code_freeze_tree") == ACCEPTED_CODE_FREEZES["H2-E2"][1], "E2_ATTEMPT_PROVENANCE", {"head": ACCEPTED_CODE_FREEZES["H2-E2"][0], "tree": ACCEPTED_CODE_FREEZES["H2-E2"][1]}, {"head": matching[0].get("code_freeze_head"), "tree": matching[0].get("code_freeze_tree")}, attempts_path.as_posix(), gate="H2-E2")
    return "PASS"


def _validate_e3(*, repo: Path, evidence: Path) -> str:
    freeze_path = _assert_evidence_file(repo=repo, evidence_root=evidence, relative_path="H2-E3/code-freeze.json", accepted_head=ACCEPTED_HEADS["H2-E3"], gate="H2-E3")
    qualification_path = _assert_evidence_file(repo=repo, evidence_root=evidence, relative_path="H2-E3/actual-host/attempt-0012/qualification.json", accepted_head=ACCEPTED_HEADS["H2-E3"], gate="H2-E3")
    attempts_path = _assert_evidence_file(repo=repo, evidence_root=evidence, relative_path="H2-E3/actual-host/live-attempts.json", accepted_head=ACCEPTED_HEADS["H2-E3"], gate="H2-E3")
    freeze = _read_json(freeze_path, gate="H2-E3", dimension="E3_CODE_FREEZE")
    qualification = _read_json(qualification_path, gate="H2-E3", dimension="E3_ACTUAL_HOST")
    attempts = _read_json_value(attempts_path, gate="H2-E3", dimension="E3_ATTEMPTS_JSON")
    _require(freeze.get("code_freeze_head") == EXPECTED_E3_LIVE_HEAD, "E3_CODE_FREEZE_HEAD", EXPECTED_E3_LIVE_HEAD, freeze.get("code_freeze_head"), freeze_path.as_posix(), gate="H2-E3")
    _require(freeze.get("code_freeze_tree") == EXPECTED_E3_LIVE_TREE, "E3_CODE_FREEZE_TREE", EXPECTED_E3_LIVE_TREE, freeze.get("code_freeze_tree"), freeze_path.as_posix(), gate="H2-E3")
    _require(qualification.get("status") == "H2_E3_A02_FULL_PASS", "E3_STATUS", "H2_E3_A02_FULL_PASS", qualification.get("status"), qualification_path.as_posix(), gate="H2-E3")
    _require(qualification.get("case_id") == "A02-FULL", "E3_CASE", "A02-FULL", qualification.get("case_id"), qualification_path.as_posix(), gate="H2-E3")
    _validate_host_version(qualification, gate="H2-E3", path=qualification_path.as_posix())
    _validate_oracle_fields(qualification, gate="H2-E3", path=qualification_path.as_posix())
    _validate_operations(qualification, A02_OPERATIONS, gate="H2-E3", path=qualification_path.as_posix())
    envelopes = qualification.get("input_envelopes")
    _require(isinstance(envelopes, list) and [item.get("source") for item in envelopes if isinstance(item, dict)] == ["STRUCTURED_ACTION", "HOST_COMPOSER_TEXT", "STRUCTURED_ACTION", "STRUCTURED_ACTION"], "E3_INPUT_ENVELOPE_SEQUENCE", ["STRUCTURED_ACTION", "HOST_COMPOSER_TEXT", "STRUCTURED_ACTION", "STRUCTURED_ACTION"], envelopes, qualification_path.as_posix(), gate="H2-E3")
    revision_text = (
        envelopes[1].get("text")
        if isinstance(envelopes, list)
        and len(envelopes) > 1
        and isinstance(envelopes[1], dict)
        else "MISSING"
    )
    _require(isinstance(envelopes, list) and len(envelopes) > 1 and revision_text == REVISION_TEXT, "E3_REVISION_TEXT", REVISION_TEXT, revision_text, qualification_path.as_posix(), gate="H2-E3")
    for key in ("native_codex_submission_observed", "native_enter_keydown_suppressed", "native_enter_keyup_suppressed", "composer_cleared", "sidecar_dismissed", "actual_composer_focus_restored"):
        expected = False if key == "native_codex_submission_observed" else True
        _require(qualification.get(key) is expected, f"E3_{key.upper()}", expected, qualification.get(key), qualification_path.as_posix(), gate="H2-E3")
    _require(isinstance(attempts, list), "E3_ATTEMPTS_SCHEMA", "list", type(attempts).__name__, attempts_path.as_posix(), gate="H2-E3")
    matching = [item for item in attempts if isinstance(item, dict) and item.get("attempt") == 12 and item.get("status") == "H2_E3_A02_FULL_PASS"]
    _require(len(matching) == 1, "E3_PASS_ATTEMPT", "one passing attempt 12", matching, attempts_path.as_posix(), gate="H2-E3")
    _require(matching[0].get("code_freeze_head") == EXPECTED_E3_LIVE_HEAD and matching[0].get("code_freeze_tree") == EXPECTED_E3_LIVE_TREE, "E3_ATTEMPT_PROVENANCE", {"head": EXPECTED_E3_LIVE_HEAD, "tree": EXPECTED_E3_LIVE_TREE}, {"head": matching[0].get("code_freeze_head"), "tree": matching[0].get("code_freeze_tree")}, attempts_path.as_posix(), gate="H2-E3")
    return "PASS"


def _all_statuses_pass(value: object, *, allow: set[str] | None = None) -> bool:
    allowed = allow or {"PASS"}
    if isinstance(value, dict):
        statuses = [item for key, item in value.items() if key == "status"]
        if any(status not in allowed for status in statuses):
            return False
        return all(_all_statuses_pass(item, allow=allowed) for item in value.values())
    if isinstance(value, list):
        return all(_all_statuses_pass(item, allow=allow) for item in value)
    return True


def _validate_f1(*, repo: Path, evidence: Path) -> str:
    parity_path = _assert_evidence_file(repo=repo, evidence_root=evidence, relative_path="H2-F1/parity-report.json", accepted_head=ACCEPTED_HEADS["H2-F1"], gate="H2-F1")
    repair_path = _assert_evidence_file(repo=repo, evidence_root=evidence, relative_path="H2-F1/repair-report.json", accepted_head=ACCEPTED_HEADS["H2-F1"], gate="H2-F1")
    human_path = _assert_evidence_file(repo=repo, evidence_root=evidence, relative_path="H2-F1/human-disposition-completion.json", accepted_head=ACCEPTED_HEADS["H2-F1"], gate="H2-F1")
    parity = _read_json(parity_path, gate="H2-F1", dimension="F1_PARITY_EVIDENCE")
    repair = _read_json(repair_path, gate="H2-F1", dimension="F1_REPAIR_EVIDENCE")
    human = _read_json(human_path, gate="H2-F1", dimension="F1_HUMAN_EVIDENCE")
    _require(parity.get("status") == "F1_PARITY_PASS", "F1_STATUS", "F1_PARITY_PASS", parity.get("status"), parity_path.as_posix(), gate="H2-F1")
    _validate_oracle_fields(parity, gate="H2-F1", path=parity_path.as_posix())
    cases = parity.get("cases")
    _require(
        isinstance(cases, dict)
        and isinstance(cases.get("G06"), dict)
        and isinstance(cases.get("A02-FULL"), dict)
        and cases["G06"].get("status") == "PASS"
        and cases["A02-FULL"].get("status") == "PASS",
        "F1_CASE_STATUS",
        {"G06": "PASS", "A02-FULL": "PASS"},
        cases,
        parity_path.as_posix(),
        gate="H2-F1",
    )
    assert isinstance(cases, dict)
    for case in ("G06", "A02-FULL"):
        dimensions = cases[case].get("dimensions", {})
        _require(isinstance(dimensions, dict), "F1_DIMENSIONS_SCHEMA", "object", dimensions, {"case": case, "path": parity_path.as_posix()}, gate="H2-F1")
        for name, dimension in dimensions.items():
            status = dimension.get("status") if isinstance(dimension, dict) else None
            expected = "N/A — NOT EXERCISED BY G06" if case == "G06" and name in {"free_response_focus_behavior", "revised_prompt_equality"} else "PASS"
            _require(status == expected, "F1_DIMENSION_STATUS", expected, status, {"case": case, "dimension": name, "path": parity_path.as_posix()}, gate="H2-F1")
    _require(repair.get("live_qualified_production_freeze", {}).get("head") == EXPECTED_E3_LIVE_HEAD and repair.get("live_qualified_production_freeze", {}).get("tree") == EXPECTED_E3_LIVE_TREE, "F1_LIVE_FREEZE_PROVENANCE", {"head": EXPECTED_E3_LIVE_HEAD, "tree": EXPECTED_E3_LIVE_TREE}, repair.get("live_qualified_production_freeze"), repair_path.as_posix(), gate="H2-F1")
    _require(repair.get("qualification", {}).get("full_r6o", {}).get("status") == "PASS", "F1_FULL_R6O", "PASS", repair.get("qualification", {}).get("full_r6o", {}).get("status"), repair_path.as_posix(), gate="H2-F1")
    _require(human.get("human_pass") == "NOT_CLAIMED", "F1_HUMAN_PASS_CLAIM", "NOT_CLAIMED", human.get("human_pass"), human_path.as_posix(), gate="H2-F1")
    return "PASS"


def _validate_f2(*, repo: Path, evidence: Path) -> dict[str, str]:
    prefix = "H2-F2/human-override-repair-2/"
    authority_path = _assert_evidence_file(repo=repo, evidence_root=evidence, relative_path=prefix + "authority.json", accepted_head=ACCEPTED_HEADS["H2-F2"], gate="H2-F2")
    freeze_path = _assert_evidence_file(repo=repo, evidence_root=evidence, relative_path=prefix + "code-freeze.json", accepted_head=ACCEPTED_HEADS["H2-F2"], gate="H2-F2")
    summary_path = _assert_evidence_file(repo=repo, evidence_root=evidence, relative_path=prefix + "qualification-summary.json", accepted_head=ACCEPTED_HEADS["H2-F2"], gate="H2-F2")
    qualification_path = _assert_evidence_file(repo=repo, evidence_root=evidence, relative_path=prefix + "qualification.json", accepted_head=ACCEPTED_HEADS["H2-F2"], gate="H2-F2")
    ci_path = _assert_evidence_file(repo=repo, evidence_root=evidence, relative_path=prefix + "ci.json", accepted_head=ACCEPTED_HEADS["H2-F2"], gate="H2-F2")
    checklist_path = _assert_evidence_file(repo=repo, evidence_root=evidence, relative_path=prefix + "pre-review-completion-checklist.json", accepted_head=ACCEPTED_HEADS["H2-F2"], gate="H2-F2")
    authority = _read_json(authority_path, gate="H2-F2", dimension="F2_REPAIR_AUTHORITY")
    freeze = _read_json(freeze_path, gate="H2-F2", dimension="F2_SECOND_REPAIR_FREEZE")
    summary = _read_json(summary_path, gate="H2-F2", dimension="F2_QUALIFICATION_SUMMARY")
    qualification = _read_json(qualification_path, gate="H2-F2", dimension="F2_QUALIFICATION")
    ci = _read_json(ci_path, gate="H2-F2", dimension="F2_CI")
    checklist = _read_json(checklist_path, gate="H2-F2", dimension="F2_CHECKLIST")
    _require(authority.get("human_override_second_repair") == "AUTHORIZED", "F2_REPAIR_AUTHORITY", "AUTHORIZED", authority.get("human_override_second_repair"), authority_path.as_posix(), gate="H2-F2")
    required_findings = {"R1_F1_DELIVERY_CANCELLATION_RACE", "R2_F5_UNSUPPORTED_QUALIFICATION_PASS", "R3_F4_CLOSE_VIEW_HIDE_RETRY"}
    authorized_findings = authority.get("authorized_findings")
    _require(isinstance(authorized_findings, list) and set(authorized_findings) == required_findings, "F2_AUTHORIZED_FINDINGS", sorted(required_findings), authorized_findings, authority_path.as_posix(), gate="H2-F2")
    _require(authority.get("automatic_repair_budget_remaining") == 0 and authority.get("human_override_repair_budget_remaining") == 0, "F2_REPAIR_BUDGET", {"automatic": 0, "human_override": 0}, {"automatic": authority.get("automatic_repair_budget_remaining"), "human_override": authority.get("human_override_repair_budget_remaining")}, authority_path.as_posix(), gate="H2-F2")
    _require(authority.get("human_pass") == "NOT_CLAIMED", "F2_HUMAN_PASS_CLAIM", "NOT_CLAIMED", authority.get("human_pass"), authority_path.as_posix(), gate="H2-F2")
    _require(freeze.get("second_repaired_code_freeze", {}).get("head") == EXPECTED_F2_FREEZE_HEAD and freeze.get("second_repaired_code_freeze", {}).get("tree") == EXPECTED_F2_FREEZE_TREE and freeze.get("second_repaired_code_freeze", {}).get("status") == "FROZEN", "F2_SECOND_REPAIR_FREEZE", {"head": EXPECTED_F2_FREEZE_HEAD, "tree": EXPECTED_F2_FREEZE_TREE, "status": "FROZEN"}, freeze.get("second_repaired_code_freeze"), freeze_path.as_posix(), gate="H2-F2")
    _validate_oracle_fields(freeze, gate="H2-F2", path=freeze_path.as_posix())
    _require(summary.get("code_freeze_head") == EXPECTED_F2_FREEZE_HEAD and summary.get("code_freeze_tree") == EXPECTED_F2_FREEZE_TREE, "F2_SUMMARY_FREEZE", {"head": EXPECTED_F2_FREEZE_HEAD, "tree": EXPECTED_F2_FREEZE_TREE}, {"head": summary.get("code_freeze_head"), "tree": summary.get("code_freeze_tree")}, summary_path.as_posix(), gate="H2-F2")
    commands = summary.get("commands")
    _require(isinstance(commands, list) and commands and all(isinstance(item, dict) and item.get("status") == "PASS" for item in commands), "F2_COMMANDS", "all recorded commands PASS", commands, summary_path.as_posix(), gate="H2-F2")
    _require(summary.get("process_exit_proof", {}).get("status") == "PASS", "F2_PROCESS_EXIT_PROOF", "PASS", summary.get("process_exit_proof", {}).get("status"), summary_path.as_posix(), gate="H2-F2")
    _require(qualification.get("status") == "H2_F2_LIFECYCLE_RESILIENCE_PASS", "F2_STATUS", "H2_F2_LIFECYCLE_RESILIENCE_PASS", qualification.get("status"), qualification_path.as_posix(), gate="H2-F2")
    _require(qualification.get("mode") == "actual-host", "F2_MODE", "actual-host", qualification.get("mode"), qualification_path.as_posix(), gate="H2-F2")
    _validate_oracle_fields(qualification, gate="H2-F2", path=qualification_path.as_posix())
    _require(qualification.get("windows_local_actual_codex", {}).get("status") == "PASS", "F2_ACTUAL_HOST", "PASS", qualification.get("windows_local_actual_codex", {}).get("status"), qualification_path.as_posix(), gate="H2-F2")
    _require(qualification.get("process_exit_qualification", {}).get("status") == "PASS", "F2_PROCESS_EXIT", "PASS", qualification.get("process_exit_qualification", {}).get("status"), qualification_path.as_posix(), gate="H2-F2")
    scope = qualification.get("scope", {})
    for key in ("semantic_workflow_exercised", "normal_codex_submit_gesture_used", "r6o3_lease_implemented", "qml_or_design_changed"):
        _require(scope.get(key) is False, f"F2_SCOPE_{key.upper()}", False, scope.get(key), qualification_path.as_posix(), gate="H2-F2")
    for key in required_findings:
        _require(summary.get("authorized_findings", {}).get(key) == "PASS", "F2_REPAIR_DIMENSION", "PASS", summary.get("authorized_findings", {}).get(key), {"finding": key, "path": summary_path.as_posix()}, gate="H2-F2")
    warnings = qualification.get("warnings")
    _require(isinstance(warnings, list), "F2_WARNING_SCHEMA", "list", type(warnings).__name__, qualification_path.as_posix(), gate="H2-F2")
    rpc = [item for item in warnings if isinstance(item, dict) and item.get("id") == "RPC_E_CHANGED_MODE"]
    _require(len(rpc) == 1 and rpc[0].get("classification") == "NONBLOCKING_P2", "F2_RPC_WARNING", {"id": "RPC_E_CHANGED_MODE", "classification": "NONBLOCKING_P2"}, rpc, qualification_path.as_posix(), gate="H2-F2")
    _require(checklist.get("implementation_complete") is True and checklist.get("human_pass") == "NOT_CLAIMED", "F2_CHECKLIST_COMPLETION", {"implementation_complete": True, "human_pass": "NOT_CLAIMED"}, {"implementation_complete": checklist.get("implementation_complete"), "human_pass": checklist.get("human_pass")}, checklist_path.as_posix(), gate="H2-F2")
    _require(ci.get("code_freeze_head") == EXPECTED_F2_FREEZE_HEAD, "F2_CI_FREEZE", EXPECTED_F2_FREEZE_HEAD, ci.get("code_freeze_head"), ci_path.as_posix(), gate="H2-F2")
    return {"status": "PASS", "accepted_finding": "RPC_E_CHANGED_MODE=NONBLOCKING_P2"}


def _walk_keyed(value: object, path: str = "") -> Iterable[tuple[str, object]]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            yield child_path, child
            yield from _walk_keyed(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_keyed(child, f"{path}[{index}]")


def _validate_no_r6o3(documents: Sequence[tuple[str, dict[str, Any]]]) -> None:
    for path, document in documents:
        for key_path, value in _walk_keyed(document):
            if "r6o3" not in key_path.lower():
                continue
            if value is True or (isinstance(value, str) and value.strip().lower() in {"true", "yes", "pass", "implemented", "claimed"}):
                _fail("R6O3_BEHAVIOR_CLAIM", False, {"path": key_path, "value": value}, path)


def _validate_human_record(*, repo: Path, evidence: Path) -> dict[str, Any]:
    path = evidence / "H2" / "H2-HUMAN-GATE-RECORD.json"
    document = _read_json(path, gate="H2-F3", dimension="HUMAN_GATE_RECORD")
    _require(document.get("gate") == "H2", "HUMAN_GATE_GATE", "H2", document.get("gate"), path.as_posix())
    _require(document.get("human_disposition") is None, "HUMAN_DISPOSITION", None, document.get("human_disposition"), path.as_posix())
    _require(document.get("promotion_authorized") is False, "PROMOTION_AUTHORIZED", False, document.get("promotion_authorized"), path.as_posix())
    _require(document.get("human_pass") in (None, False, "NOT_CLAIMED"), "HUMAN_PASS_CLAIM", "null/false/NOT_CLAIMED", document.get("human_pass"), path.as_posix())
    _require(document.get("state") in (None, "HUMAN_PENDING"), "HUMAN_GATE_STATE", "HUMAN_PENDING", document.get("state"), path.as_posix())
    return {"status": "HUMAN_PENDING", "human_disposition": None, "promotion_authorized": False, "human_pass": "NOT_CLAIMED"}


def _validate_current_host_evidence(*, repo: Path, output: Path, freeze: dict[str, Any]) -> dict[str, str]:
    path = output / "actual-host" / "qualification.json"
    document = _read_json(path, gate="H2-F3", dimension="ACTUAL_HOST_FINAL_EVIDENCE")
    _require(document.get("schema_version") == "r6o-h2-f3-actual-host-1", "ACTUAL_HOST_SCHEMA", "r6o-h2-f3-actual-host-1", document.get("schema_version"), path.as_posix())
    _require(document.get("status") == "PASS", "ACTUAL_HOST_STATUS", "PASS", document.get("status"), path.as_posix())
    _require(document.get("source", {}).get("head") == freeze["head"] and document.get("source", {}).get("tree") == freeze["tree"], "ACTUAL_HOST_SOURCE", {"head": freeze["head"], "tree": freeze["tree"]}, document.get("source"), path.as_posix())
    attachment = document.get("attachment", {})
    attachment_path_value = attachment.get("path")
    _require(isinstance(attachment_path_value, str), "ACTUAL_HOST_ATTACHMENT_PATH", "relative path", attachment_path_value, path.as_posix())
    attachment_path = output / Path(attachment_path_value)
    _require(_is_within(attachment_path, output), "ACTUAL_HOST_ATTACHMENT_PATH_SCOPE", "inside F3 output", attachment_path.as_posix(), path.as_posix())
    attachment_result = _read_json(attachment_path, gate="H2-F3", dimension="ACTUAL_HOST_ATTACHMENT_RESULT")
    _require(attachment_result.get("status") == "H2_D2_ATTACHMENT_PASS", "ACTUAL_HOST_ATTACHMENT_STATUS", "H2_D2_ATTACHMENT_PASS", attachment_result.get("status"), attachment_path.as_posix())
    _require(attachment_result.get("real_codex_host_tested") is True and attachment_result.get("synthetic_owner_used") is False, "ACTUAL_HOST_RUNTIME_IDENTITY", {"real_codex_host_tested": True, "synthetic_owner_used": False}, {"real_codex_host_tested": attachment_result.get("real_codex_host_tested"), "synthetic_owner_used": attachment_result.get("synthetic_owner_used")}, attachment_path.as_posix())
    host = attachment_result.get("host", {})
    for key, expected in CURRENT_HOST.items():
        _require(host.get(key) == expected, f"ACTUAL_HOST_{key.upper()}", expected, host.get(key), attachment_path.as_posix())
    host_record = repo / "r6o_evidence" / "H2-D1" / "host-environment.json"
    selectors = repo / "r6o" / "host" / "codex" / "windows" / "selectors.json"
    _require(attachment_result.get("host_record_sha256") == _sha256_file(host_record), "ACTUAL_HOST_RECORD_HASH", _sha256_file(host_record), attachment_result.get("host_record_sha256"), attachment_path.as_posix())
    _require(attachment_result.get("selectors_sha256") == _sha256_file(selectors), "ACTUAL_HOST_SELECTOR_HASH", _sha256_file(selectors), attachment_result.get("selectors_sha256"), attachment_path.as_posix())
    accepted = document.get("accepted_machine_evidence")
    expected_accepted = {
        "e1_input_routing": "PASS",
        "actual_host_g06": "PASS",
        "actual_host_a02_full": "PASS",
        "lifecycle_resilience": "PASS",
    }
    _require(accepted == expected_accepted, "ACCEPTED_MACHINE_EVIDENCE", expected_accepted, accepted, path.as_posix())
    return {"status": "PASS", "attachment": "PASS"}


def _validate_qt_evidence(*, repo: Path, output: Path, freeze: dict[str, Any], ci: dict[str, Any] | None) -> dict[str, str]:
    path = output / "qt-qualification.json"
    document = _read_json(path, gate="H2-F3", dimension="QT_SIDECAR_EVIDENCE")
    _require(document.get("schema_version") == "r6o-h2-f3-qt-qualification-1", "QT_EVIDENCE_SCHEMA", "r6o-h2-f3-qt-qualification-1", document.get("schema_version"), path.as_posix())
    _require(document.get("source", {}).get("head") == freeze["head"] and document.get("source", {}).get("tree") == freeze["tree"], "QT_SOURCE", {"head": freeze["head"], "tree": freeze["tree"]}, document.get("source"), path.as_posix())
    _require(document.get("human_visual_approval") in (None, "PENDING_HUMAN_H2", "NOT_CLAIMED"), "QT_HUMAN_APPROVAL", "pending", document.get("human_visual_approval"), path.as_posix())
    platforms = document.get("platforms")
    _require(isinstance(platforms, dict), "QT_PLATFORM_SCHEMA", "object", platforms, path.as_posix())
    assert isinstance(platforms, dict)
    for key in ("windows", "linux_x11", "linux_wayland"):
        _require(platforms.get(key, {}).get("status") == "PASS", "QT_PLATFORM_STATUS", "PASS", platforms.get(key), {"platform": key, "path": path.as_posix()})
    if ci is not None:
        candidate = ci.get("candidate", {})
        for key in ("linux_x11", "linux_wayland"):
            ci_job = platforms[key].get("ci_job")
            _require(
                isinstance(ci_job, dict)
                and ci_job.get("status") == "SUCCESS"
                and ci_job.get("head_sha") == candidate.get("head"),
                "QT_CI_JOB",
                {"status": "SUCCESS", "head_sha": candidate.get("head")},
                ci_job,
                {"platform": key, "path": path.as_posix()},
            )
    windows_result_path = platforms["windows"].get("result_path")
    _require(isinstance(windows_result_path, str), "QT_WINDOWS_RESULT_PATH", "relative path", windows_result_path, path.as_posix())
    result_path = output / Path(windows_result_path)
    _require(_is_within(result_path, output), "QT_WINDOWS_RESULT_SCOPE", "inside F3 output", result_path.as_posix(), path.as_posix())
    result = _read_json(result_path, gate="H2-F3", dimension="QT_WINDOWS_RESULT")
    _require(result.get("status") == "MECHANICAL_PASS_PENDING_FINAL_REVIEW", "QT_WINDOWS_RESULT_STATUS", "MECHANICAL_PASS_PENDING_FINAL_REVIEW", result.get("status"), result_path.as_posix())
    _require(result.get("source", {}).get("head") == freeze["head"] and result.get("source", {}).get("tree") == freeze["tree"], "QT_RESULT_SOURCE", {"head": freeze["head"], "tree": freeze["tree"]}, result.get("source"), result_path.as_posix())
    q_status = result.get("proof", {}).get("q01_q24", {})
    _require(isinstance(q_status, dict), "QT_Q01_Q24_SCHEMA", "object", q_status, result_path.as_posix())
    for number in range(1, 25):
        key = f"Q{number:02d}"
        _require(q_status.get(key) not in (False, None), "QT_Q01_Q24_STATUS", "qualified", q_status.get(key), {"key": key, "path": result_path.as_posix()})
    _require(result.get("proof", {}).get("q25_standard_human_comparison") in ("PENDING_SOL_SUBSTITUTE_REVIEW", "PENDING_HUMAN_H2"), "QT_Q25_HUMAN_STATUS", "pending", result.get("proof", {}).get("q25_standard_human_comparison"), result_path.as_posix())
    _require(result.get("proof", {}).get("q26_expanded_human_comparison") in ("PENDING_SOL_SUBSTITUTE_REVIEW", "PENDING_HUMAN_H2"), "QT_Q26_HUMAN_STATUS", "pending", result.get("proof", {}).get("q26_expanded_human_comparison"), result_path.as_posix())
    return {"status": "PASS", "Q01_Q24": "PASS", "Q25_Q26": "HUMAN_PENDING"}


def _validate_ci(*, repo: Path, path: Path, freeze: dict[str, Any]) -> dict[str, str]:
    document = _read_json(path, gate="H2-F3", dimension="FINAL_CI_EVIDENCE")
    _require(document.get("schema_version") == "r6o-h2-f3-ci-1", "CI_EVIDENCE_SCHEMA", "r6o-h2-f3-ci-1", document.get("schema_version"), path.as_posix())
    candidate = document.get("candidate")
    _require(isinstance(candidate, dict), "CI_CANDIDATE_SCHEMA", "object", candidate, path.as_posix())
    assert isinstance(candidate, dict)
    _require(candidate.get("head") == freeze["head"] and candidate.get("tree") == freeze["tree"], "CI_CANDIDATE", {"head": freeze["head"], "tree": freeze["tree"]}, candidate, path.as_posix())
    required = {
        "R6O-1 qualification": {"github_windows", "github_ubuntu"},
        "H2-C Qt Quick qualification": {"windows_qt", "linux_x11", "linux_wayland"},
    }
    workflows = document.get("workflows")
    _require(isinstance(workflows, list), "CI_WORKFLOW_SCHEMA", "list", type(workflows).__name__, path.as_posix())
    by_name = {item.get("workflow"): item for item in workflows if isinstance(item, dict)}
    for workflow, jobs in required.items():
        item = by_name.get(workflow)
        _require(isinstance(item, dict), "CI_REQUIRED_WORKFLOW", workflow, item, path.as_posix())
        assert isinstance(item, dict)
        _require(item.get("head_sha") == freeze["head"] and item.get("status") == "SUCCESS", "CI_WORKFLOW_HEAD", {"head_sha": freeze["head"], "status": "SUCCESS"}, {"head_sha": item.get("head_sha"), "status": item.get("status")}, {"workflow": workflow, "path": path.as_posix()})
        job_records = item.get("jobs")
        _require(isinstance(job_records, dict), "CI_JOB_SCHEMA", "object", job_records, {"workflow": workflow, "path": path.as_posix()})
        for job in jobs:
            record = job_records.get(job)
            _require(isinstance(record, dict) and record.get("status") == "SUCCESS", "CI_JOB_STATUS", {"job": job, "status": "SUCCESS"}, record, {"workflow": workflow, "path": path.as_posix()})
            _require(record.get("job_url", "").startswith("https://github.com/"), "CI_JOB_URL", "GitHub job URL", record.get("job_url"), {"workflow": workflow, "job": job, "path": path.as_posix()})
    _require(document.get("all_required_jobs_passed") is True, "CI_ALL_REQUIRED", True, document.get("all_required_jobs_passed"), path.as_posix())
    return {"github_windows": "PASS", "github_ubuntu": "PASS", "windows_qt": "PASS", "linux_x11": "PASS", "linux_wayland": "PASS"}


def _validate_local_qualification(*, output: Path, freeze: dict[str, Any]) -> dict[str, Any]:
    path = output / "local-qualification.json"
    document = _read_json(path, gate="H2-F3", dimension="LOCAL_QUALIFICATION")
    _require(document.get("schema_version") == "r6o-h2-f3-local-qualification-1", "LOCAL_QUALIFICATION_SCHEMA", "r6o-h2-f3-local-qualification-1", document.get("schema_version"), path.as_posix())
    _require(document.get("source", {}).get("head") == freeze["head"] and document.get("source", {}).get("tree") == freeze["tree"], "LOCAL_SOURCE", {"head": freeze["head"], "tree": freeze["tree"]}, document.get("source"), path.as_posix())
    commands = document.get("commands")
    _require(isinstance(commands, list) and commands, "LOCAL_COMMANDS_SCHEMA", "non-empty list", commands, path.as_posix())
    expected_command_ids = {
        "f3_focused_tests",
        "e1_e2_e3_regression",
        "qt_focused_tests",
        "full_r6o",
        "r6o1_verification",
        "tui_g06",
        "tui_a02_full",
        "f1_parity_verifier",
        "f2_portable_verifier",
        "qt_windows_qualification",
        "actual_codex_attachment",
    }
    actual_command_ids = {item.get("id") for item in commands if isinstance(item, dict)}
    _require(actual_command_ids == expected_command_ids, "LOCAL_COMMAND_IDS", sorted(expected_command_ids), sorted(actual_command_ids), path.as_posix())
    for command in commands:
        _require(isinstance(command, dict) and command.get("status") == "PASS" and command.get("exit_code") == 0, "LOCAL_COMMAND_STATUS", {"status": "PASS", "exit_code": 0}, command, path.as_posix())
        stdout_path_value = command.get("stdout_path")
        _require(isinstance(stdout_path_value, str), "LOCAL_STDOUT_PATH", "relative path", stdout_path_value, path.as_posix())
        stdout_path = output / Path(stdout_path_value)
        _require(_is_within(stdout_path, output) and stdout_path.is_file(), "LOCAL_STDOUT_EVIDENCE", "present F3 log", stdout_path_value, path.as_posix())
        stderr_path_value = command.get("stderr_path")
        _require(isinstance(stderr_path_value, str), "LOCAL_STDERR_PATH", "relative path", stderr_path_value, path.as_posix())
        stderr_path = output / Path(stderr_path_value)
        _require(_is_within(stderr_path, output) and stderr_path.is_file(), "LOCAL_STDERR_EVIDENCE", "present F3 log", stderr_path_value, path.as_posix())
    counts = document.get("counts", {})
    for key in ("f3_focused_tests", "full_r6o", "r6o1"):
        _require(isinstance(counts.get(key), int) and counts.get(key) > 0, f"LOCAL_COUNT_{key.upper()}", "positive integer", counts.get(key), path.as_posix())
    _require(document.get("actual_host", {}).get("status") == "PASS", "LOCAL_ACTUAL_HOST", "PASS", document.get("actual_host"), path.as_posix())
    return document


def verify_repository(
    *,
    repo_root: Path = ROOT,
    evidence_root: Path | None = None,
    baseline_repo: Path | None = None,
    output_dir: Path | None = None,
    require_local: bool = True,
    require_actual_host: bool = True,
    require_qt: bool = True,
    require_ci: bool = True,
    write_report: bool = True,
) -> dict[str, Any]:
    repo = repo_root.resolve()
    evidence = (evidence_root or (repo / "r6o_evidence")).resolve()
    output = (output_dir or (repo / "r6o_evidence" / "H2-F3")).resolve()
    oracle_value = baseline_repo or (Path(os.environ["PDL_R6S_BASELINE_REPO"]) if os.environ.get("PDL_R6S_BASELINE_REPO") else None)
    if oracle_value is None:
        _fail("FROZEN_ORACLE_INPUT", "--baseline-repo or PDL_R6S_BASELINE_REPO", "MISSING", "H2-F3")
    current = _source_identity(repo)
    _require(current["branch"] == "codex/h2-f3-final-integration", "F3_BRANCH", "codex/h2-f3-final-integration", current["branch"], current)
    _require(
        not current["dirty_paths"]
        or all(
            any(
                path.replace("\\", "/").startswith(prefix)
                for prefix in F3_EVIDENCE_PREFIXES
            )
            for path in current["dirty_paths"]
        ),
        "F3_WORKTREE_SCOPE",
        "clean or F3 evidence-only paths",
        current["dirty_paths"],
        current,
    )
    base = _validate_base(repo=repo, base_record=output / "base.json", current=current)
    freeze = _validate_code_freeze(repo=repo, record_path=output / "code-freeze.json", base=base, current=current)
    anchors = _validate_ancestry(repo=repo, current_head=current["head"])
    protected = _validate_protected_boundary(repo=repo, base=base)
    oracle = _validate_oracle(oracle=Path(oracle_value))
    tui = _validate_tui(repo=repo, evidence=evidence)
    e1 = _validate_e1(repo=repo, evidence=evidence)
    e2 = _validate_e2(repo=repo, evidence=evidence)
    e3 = _validate_e3(repo=repo, evidence=evidence)
    f1 = _validate_f1(repo=repo, evidence=evidence)
    f2 = _validate_f2(repo=repo, evidence=evidence)
    local = _validate_local_qualification(output=output, freeze=freeze) if require_local else {"status": "NOT_REQUIRED"}
    actual_host = _validate_current_host_evidence(repo=repo, output=output, freeze=freeze) if require_actual_host else {"status": "NOT_REQUIRED"}
    ci = _validate_ci(repo=repo, path=output / "ci.json", freeze=freeze) if require_ci else None
    qt = _validate_qt_evidence(repo=repo, output=output, freeze=freeze, ci=ci) if require_qt else {"status": "NOT_REQUIRED"}
    ci_report = ci if ci is not None else {"status": "NOT_REQUIRED"}
    human = _validate_human_record(repo=repo, evidence=evidence)
    documents = []
    for path in (
        "H2-E1/input-routing-result.json",
        "H2-E2/actual-host/qualification.json",
        "H2-E3/actual-host/attempt-0012/qualification.json",
        "H2-F1/parity-report.json",
        "H2-F2/human-override-repair-2/qualification.json",
    ):
        documents.append((path, _read_json(evidence / Path(path), gate="H2-F3", dimension="R6O3_SCAN")))
    _validate_no_r6o3(documents)
    report = {
        "schema_version": "r6o-h2-f3-final-integration-1",
        "gate": "H2-F3",
        "status": "H2_F3_FINAL_INTEGRATION_PASS",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": current,
        "base": base,
        "code_freeze": freeze,
        "predecessor_anchors": anchors,
        "dimensions": {
            "protected_r6o1": protected,
            "frozen_oracle": oracle,
            "tui_g06": tui["G06"],
            "tui_a02_full": tui["A02-FULL"],
            "qt_sidecar": qt,
            "actual_codex_attachment": actual_host.get("attachment", actual_host.get("status")),
            "e1_input_routing": e1,
            "actual_host_g06": e2,
            "actual_host_a02_full": e3,
            "cross_view_parity": f1,
            "lifecycle_resilience": f2["status"],
            "f2_second_repair_provenance": "PASS",
            "final_ci": ci_report,
        },
        "production_behavior_changed": False,
        "r6o3_behavior_claimed": False,
        "known_findings": ["RPC_E_CHANGED_MODE=NONBLOCKING_P2"],
        "human_gate": human,
        "local_qualification": local,
        "platform_matrix": {
            "windows_local_actual_codex": actual_host.get("status", "NOT_REQUIRED"),
            "github_windows": ci_report.get("github_windows", "NOT_REQUIRED"),
            "github_ubuntu": ci_report.get("github_ubuntu", "NOT_REQUIRED"),
            "windows_qt": ci_report.get("windows_qt", "NOT_REQUIRED"),
            "linux_x11": ci_report.get("linux_x11", "NOT_REQUIRED"),
            "linux_wayland": ci_report.get("linux_wayland", "NOT_REQUIRED"),
        },
    }
    if write_report:
        _json_write(output / "qualification.json", report)
    return report


def _command_text(arguments: Sequence[str]) -> str:
    rendered = []
    for item in arguments:
        if " " in item:
            rendered.append('"' + item + '"')
        else:
            rendered.append(item)
    return " ".join(rendered)


def _run_command(
    *,
    repo: Path,
    output: Path,
    identifier: str,
    arguments: list[str],
    environment: dict[str, str] | None = None,
) -> dict[str, Any]:
    log_dir = output / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = log_dir / f"{identifier}.stdout.txt"
    stderr_path = log_dir / f"{identifier}.stderr.txt"
    started = time.monotonic()
    env = os.environ.copy()
    if environment:
        env.update(environment)
    result = subprocess.run(arguments, cwd=repo, env=env, capture_output=True, text=True, check=False)
    stdout_path.write_text(result.stdout, encoding="utf-8", newline="\n")
    stderr_path.write_text(result.stderr, encoding="utf-8", newline="\n")
    count_matches = re.findall(r"(?P<count>\d+) passed", result.stdout)
    return {
        "id": identifier,
        "command": _command_text(arguments),
        "exit_code": result.returncode,
        "status": "PASS" if result.returncode == 0 else "FAIL",
        "duration_seconds": round(time.monotonic() - started, 3),
        "stdout_path": stdout_path.relative_to(output).as_posix(),
        "stderr_path": stderr_path.relative_to(output).as_posix(),
        "passed_count": int(count_matches[-1]) if count_matches else None,
    }


def _write_code_freeze(*, repo: Path, output: Path, base: dict[str, Any]) -> dict[str, Any]:
    current_head = _git(repo, "rev-parse", "HEAD")
    current_tree = _git_tree(repo, "HEAD")
    document = {
        "schema_version": "r6o-h2-f3-code-freeze-1",
        "gate": "H2-F3",
        "base": base,
        "code_freeze": {"head": current_head, "tree": current_tree, "status": "FROZEN"},
        "post_freeze_rule": "Only r6o_evidence/H2-F3/** and the explicitly authorized H2 final record may change after this freeze.",
    }
    _json_write(output / "code-freeze.json", document)
    return document["code_freeze"]


def collect_local_qualification(*, repo: Path, output: Path, baseline: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    current = _source_identity(repo)
    _require(not current["dirty_paths"], "LOCAL_COLLECTION_WORKTREE", [], current["dirty_paths"], current)
    base_document = _read_json(output / "base.json", gate="H2-F3", dimension="F3_BASE_RECORD")
    base = base_document.get("base")
    _require(isinstance(base, dict), "F3_BASE_IDENTITY", "base object", base, output / "base.json")
    assert isinstance(base, dict)
    freeze = _write_code_freeze(repo=repo, output=output, base={"head": base["head"], "tree": base["tree"]})
    python = sys.executable
    baseline_text = str(baseline.resolve())
    commands: list[dict[str, Any]] = []
    commands.append(_run_command(repo=repo, output=output, identifier="f3_focused_tests", arguments=[python, "-m", "pytest", "r6o/tests/h2/test_h2_final_integration.py", "-q", "-p", "no:cacheprovider"]))
    commands.append(_run_command(repo=repo, output=output, identifier="e1_e2_e3_regression", arguments=[python, "-m", "pytest", "r6o/tests/h2/test_codex_input_binding_contract.py", "r6o/tests/h2/test_codex_h2_e2.py", "r6o/tests/h2/test_codex_h2_e3.py", "-q", "-p", "no:cacheprovider"]))
    commands.append(_run_command(repo=repo, output=output, identifier="qt_focused_tests", arguments=[python, "-m", "pytest", "r6o/tests/h2/test_qt_sidecar_feasibility.py", "r6o/tests/h2/test_qt_sidecar_component.py", "-q", "-p", "no:cacheprovider"], environment={"QT_QUICK_BACKEND": "software", "QT_SCALE_FACTOR": "1", "QT_FONT_DPI": "96"}))
    commands.append(_run_command(repo=repo, output=output, identifier="full_r6o", arguments=[python, "-m", "pytest", "r6o/tests", "-q", "-p", "no:cacheprovider"]))
    commands.append(_run_command(repo=repo, output=output, identifier="r6o1_verification", arguments=[python, "scripts/verify_r6o1.py"], environment={"PDL_R6S_BASELINE_REPO": baseline_text}))
    commands.append(_run_command(repo=repo, output=output, identifier="tui_g06", arguments=[python, "scripts/h2/verify_tui_g06.py", "--baseline-repo", baseline_text, "--evidence-dir", "r6o_evidence/H2-F3/tui-g06"]))
    commands.append(_run_command(repo=repo, output=output, identifier="tui_a02_full", arguments=[python, "scripts/h2/verify_tui_a02_full.py", "--baseline-repo", baseline_text, "--evidence-dir", "r6o_evidence/H2-F3/tui-a02-full"]))
    commands.append(_run_command(repo=repo, output=output, identifier="f1_parity_verifier", arguments=[python, "scripts/h2/verify_cross_view_parity.py", "--baseline-repo", baseline_text, "--output-dir", "r6o_evidence/H2-F3/f1-parity-rerun"]))
    commands.append(_run_command(repo=repo, output=output, identifier="f2_portable_verifier", arguments=[python, "scripts/h2/verify_h2_lifecycle_resilience.py", "--mode", "portable", "--baseline-repo", baseline_text, "--evidence-dir", "r6o_evidence/H2-F3/f2-portable"]))
    commands.append(_run_command(repo=repo, output=output, identifier="qt_windows_qualification", arguments=[python, "scripts/h2/verify_qt_sidecar_component.py", "--platform", "windows", "--evidence-dir", "r6o_evidence/H2-F3/qt"], environment={"QT_QUICK_BACKEND": "software", "QT_SCALE_FACTOR": "1", "QT_FONT_DPI": "96"}))
    if os.name == "nt":
        commands.append(_run_command(repo=repo, output=output, identifier="actual_codex_attachment", arguments=[python, "scripts/h2/verify_codex_attachment.py", "--host-record", "r6o_evidence/H2-D1/host-environment.json", "--selectors", "r6o/host/codex/windows/selectors.json", "--evidence-dir", "r6o_evidence/H2-F3/actual-host/attachment"], environment={"QT_QUICK_BACKEND": "software", "QT_SCALE_FACTOR": "1", "QT_FONT_DPI": "96"}))
    else:
        commands.append({"id": "actual_codex_attachment", "command": "Windows-only actual Codex attachment verifier", "exit_code": 1, "status": "FAIL", "reason": "F3 requires WINDOWS_LOCAL_ACTUAL_CODEX"})

    attachment_path = output / "actual-host" / "attachment" / "attachment-result.json"
    attachment_status = "PASS" if attachment_path.is_file() and _read_json(attachment_path, gate="H2-F3", dimension="ACTUAL_HOST_COLLECTION").get("status") == "H2_D2_ATTACHMENT_PASS" else "FAIL"
    _json_write(output / "actual-host" / "qualification.json", {
        "schema_version": "r6o-h2-f3-actual-host-1",
        "gate": "H2-F3",
        "status": attachment_status,
        "source": freeze,
        "attachment": {"status": attachment_status, "path": "actual-host/attachment/attachment-result.json"},
        "accepted_machine_evidence": {
            "e1_input_routing": "PASS",
            "actual_host_g06": "PASS",
            "actual_host_a02_full": "PASS",
            "lifecycle_resilience": "PASS",
        },
        "gesture_policy": "No human gesture was synthesized; E1/G06/A02 semantic evidence remains bound to accepted predecessor records and F2 integration evidence.",
    })
    qt_status = "PASS" if (output / "qt" / "windows" / "component-result.json").is_file() else "FAIL"
    _json_write(output / "qt-qualification.json", {
        "schema_version": "r6o-h2-f3-qt-qualification-1",
        "gate": "H2-F3",
        "source": freeze,
        "human_visual_approval": "PENDING_HUMAN_H2",
        "platforms": {
            "windows": {"status": qt_status, "result_path": "qt/windows/component-result.json"},
            "linux_x11": {"status": "PENDING_CI"},
            "linux_wayland": {"status": "PENDING_CI"},
        },
    })
    counts = {
        "f3_focused_tests": next((item.get("passed_count") for item in commands if item.get("id") == "f3_focused_tests"), None),
        "full_r6o": next((item.get("passed_count") for item in commands if item.get("id") == "full_r6o"), None),
        "r6o1": next((item.get("passed_count") for item in commands if item.get("id") == "r6o1_verification"), None),
    }
    local = {
        "schema_version": "r6o-h2-f3-local-qualification-1",
        "gate": "H2-F3",
        "source": freeze,
        "commands": commands,
        "counts": counts,
        "actual_host": {"status": attachment_status, "evidence": "actual-host/qualification.json"},
        "known_findings": ["RPC_E_CHANGED_MODE=NONBLOCKING_P2"],
        "human_gesture_synthesized": False,
    }
    _json_write(output / "local-qualification.json", local)
    return local


def _finalize_qt(*, output: Path, ci_path: Path) -> None:
    ci = _read_json(ci_path, gate="H2-F3", dimension="FINAL_CI_EVIDENCE")
    qt_path = output / "qt-qualification.json"
    qt = _read_json(qt_path, gate="H2-F3", dimension="QT_SIDECAR_EVIDENCE")
    workflows = {item.get("workflow"): item for item in ci.get("workflows", []) if isinstance(item, dict)}
    qt_jobs = workflows.get("H2-C Qt Quick qualification", {}).get("jobs", {})
    for key in ("linux_x11", "linux_wayland"):
        _require(qt_jobs.get(key, {}).get("status") == "SUCCESS", "QT_CI_FINALIZE", "SUCCESS", qt_jobs.get(key), {"platform": key, "ci": ci_path.as_posix()})
    qt["platforms"]["linux_x11"] = {"status": "PASS", "ci_job": qt_jobs["linux_x11"]}
    qt["platforms"]["linux_wayland"] = {"status": "PASS", "ci_job": qt_jobs["linux_wayland"]}
    _json_write(qt_path, qt)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-repo", type=Path)
    parser.add_argument("--evidence-root", type=Path, default=EVIDENCE_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--collect-local", action="store_true")
    parser.add_argument("--finalize-qt", action="store_true")
    parser.add_argument("--allow-pending-ci", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--allow-missing-actual-host", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--allow-pending-qt", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--allow-missing-local", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        baseline = args.baseline_repo or (Path(os.environ["PDL_R6S_BASELINE_REPO"]) if os.environ.get("PDL_R6S_BASELINE_REPO") else None)
        if args.collect_local:
            if baseline is None:
                _fail("FROZEN_ORACLE_INPUT", "--baseline-repo or PDL_R6S_BASELINE_REPO", "MISSING", "H2-F3")
            collect_local_qualification(repo=ROOT, output=args.output_dir.resolve(), baseline=baseline.resolve())
        if args.finalize_qt:
            _finalize_qt(output=args.output_dir.resolve(), ci_path=(args.output_dir.resolve() / "ci.json"))
        report = verify_repository(
            evidence_root=args.evidence_root,
            baseline_repo=baseline,
            output_dir=args.output_dir,
            require_local=not args.allow_missing_local,
            require_actual_host=not args.allow_missing_actual_host,
            require_qt=not args.allow_pending_qt,
            require_ci=not args.allow_pending_ci,
        )
    except FinalIntegrationError as exc:
        print(f"H2 F3 FAIL: {exc}", file=sys.stderr)
        return 1
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"H2 F3 FAIL: GATE=H2-F3 DIMENSION=UNEXPECTED_FAILURE EXPECTED=success ACTUAL={exc!r} SOURCE_IDENTITY=H2-F3", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
