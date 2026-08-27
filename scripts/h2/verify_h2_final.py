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
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EVIDENCE_ROOT = ROOT / "r6o_evidence"
DEFAULT_OUTPUT = EVIDENCE_ROOT / "H2-F3"
DEFAULT_BASE_RECORD = DEFAULT_OUTPUT / "base.json"
DEFAULT_CODE_FREEZE_RECORD = DEFAULT_OUTPUT / "code-freeze.json"
DEFAULT_CI_RECORD = DEFAULT_OUTPUT / "ci.json"
DEFAULT_QT_RECORD = DEFAULT_OUTPUT / "qt-qualification.json"
DEFAULT_HOST_RECORD = DEFAULT_OUTPUT / "actual-host" / "qualification.json"
DEFAULT_LOCAL_RECORD = DEFAULT_OUTPUT / "local-qualification.json"
DEFAULT_REPAIR_OUTPUT = DEFAULT_OUTPUT / "repair"
DEFAULT_REPAIR_CODE_FREEZE_RECORD = DEFAULT_REPAIR_OUTPUT / "code-freeze.json"
DEFAULT_REPAIR_CI_RECORD = DEFAULT_REPAIR_OUTPUT / "ci.json"
DEFAULT_REPAIR_HOST_RECORD = DEFAULT_REPAIR_OUTPUT / "actual-host" / "qualification.json"

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
E1_LINE_1 = "H2-F3-E1-LINE-1"
E1_LINE_2 = "H2-F3-E1-LINE-2"
E1_EXPECTED_TEXT = f"{E1_LINE_1}\n{E1_LINE_2}"
A02_INITIAL_PROMPT = "COMPARE Kafka and RabbitMQ for event delivery."
A02_REVISED_PROMPT = (
    "COMPARE Kafka and RabbitMQ for event delivery for an audience of data engineers."
)
A02_EXPECTED_PLAN = (
    "IDENTIFY comparison criteria relevant to event delivery and data engineers.\n"
    "COMPARE Kafka and RabbitMQ consistently across those criteria.\n"
    "SUMMARIZE the tradeoffs and the conditions that affect suitability."
)
CURRENT_ACTUAL_HOST_PASS_TOKEN = "H2_F3_CURRENT_ACTUAL_HOST_INTEGRATION_PASS"

CI_REQUIREMENTS = {
    "R6O-1 qualification": {
        "github_windows": "qualify (windows-latest)",
        "github_ubuntu": "qualify (ubuntu-latest)",
    },
    "H2-C Qt Quick qualification": {
        "windows_qt": "windows",
        "linux_x11": "linux-x11",
        "linux_wayland": "linux-wayland",
    },
}


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


def _validate_no_r6o3(documents: Sequence[tuple[str, object]]) -> None:
    for path, document in documents:
        for key_path, value in _walk_keyed(document):
            normalized_key_path = re.sub(r"[^a-z0-9]", "", key_path.lower())
            if "r6o3" not in normalized_key_path:
                continue
            if value is True or (isinstance(value, str) and value.strip().lower() in {"true", "yes", "pass", "implemented", "claimed"}):
                _fail("R6O3_BEHAVIOR_CLAIM", False, {"path": key_path, "value": value}, path)


def _collect_r6o3_documents(
    *, evidence: Path, f3_root: Path
) -> list[tuple[str, object]]:
    """Load every relevant F3 final record plus the final human record."""

    paths = {
        f3_root / "qualification.json",
        f3_root / "actual-host" / "qualification.json",
        f3_root / "local-qualification.json",
        f3_root / "qt-qualification.json",
        f3_root / "ci.json",
    }
    repair = f3_root / "repair"
    paths.update(
        {
            repair / "qualification.json",
            repair / "qualification-summary.json",
            repair / "local-qualification.json",
            repair / "qt-qualification.json",
            repair / "ci.json",
            repair / "authority.json",
            repair / "review-findings.json",
            repair / "actual-host" / "attachment" / "attachment-result.json",
            repair / "actual-host" / "attachment" / "f3-provenance.json",
        }
    )
    if (repair / "actual-host").is_dir():
        paths.update((repair / "actual-host").rglob("qualification.json"))
    human_path = evidence / "H2" / "H2-HUMAN-GATE-RECORD.json"
    paths.add(human_path)
    documents: list[tuple[str, object]] = []
    for path in sorted(
        (item for item in paths if item.is_file()),
        key=lambda item: item.as_posix(),
    ):
        documents.append(
            (
                path.as_posix(),
                _read_json_value(path, gate="H2-F3", dimension="R6O3_SCAN"),
            )
        )
    return documents


def _validate_human_record(*, repo: Path, evidence: Path) -> dict[str, Any]:
    path = evidence / "H2" / "H2-HUMAN-GATE-RECORD.json"
    document = _read_json(path, gate="H2-F3", dimension="HUMAN_GATE_RECORD")
    _require(document.get("gate") == "H2", "HUMAN_GATE_GATE", "H2", document.get("gate"), path.as_posix())
    _require(document.get("human_disposition") is None, "HUMAN_DISPOSITION", None, document.get("human_disposition"), path.as_posix())
    _require(document.get("promotion_authorized") is False, "PROMOTION_AUTHORIZED", False, document.get("promotion_authorized"), path.as_posix())
    _require(document.get("human_pass") in (None, False, "NOT_CLAIMED"), "HUMAN_PASS_CLAIM", "null/false/NOT_CLAIMED", document.get("human_pass"), path.as_posix())
    _require(document.get("state") in (None, "HUMAN_PENDING"), "HUMAN_GATE_STATE", "HUMAN_PENDING", document.get("state"), path.as_posix())
    return {"status": "HUMAN_PENDING", "human_disposition": None, "promotion_authorized": False, "human_pass": "NOT_CLAIMED"}


def _validate_f3_attachment_provenance(
    *,
    repo: Path,
    output: Path,
    qualification: dict[str, Any],
    freeze: dict[str, Any],
    attachment_path: Path,
    attachment_result: dict[str, Any],
) -> dict[str, str]:
    reference = qualification.get("f3_attachment_provenance")
    expected_reference = "actual-host/attachment/f3-provenance.json"
    _require(
        reference == expected_reference,
        "F3_ATTACHMENT_PROVENANCE_REFERENCE",
        expected_reference,
        reference,
        (output / "actual-host" / "qualification.json").as_posix(),
    )
    provenance_path = output / expected_reference
    _require(
        _is_within(provenance_path, output),
        "F3_ATTACHMENT_PROVENANCE_SCOPE",
        "inside F3 repair output",
        provenance_path.as_posix(),
        expected_reference,
    )
    provenance = _read_json(
        provenance_path,
        gate="H2-F3",
        dimension="F3_ATTACHMENT_PROVENANCE_RECORD",
    )
    _require(
        provenance.get("schema_version")
        == "r6o-h2-f3-attachment-provenance-1",
        "F3_ATTACHMENT_PROVENANCE_SCHEMA",
        "r6o-h2-f3-attachment-provenance-1",
        provenance.get("schema_version"),
        provenance_path.as_posix(),
    )
    _require(
        provenance.get("gate") == "H2-F3",
        "F3_ATTACHMENT_PROVENANCE_GATE",
        "H2-F3",
        provenance.get("gate"),
        provenance_path.as_posix(),
    )
    for field in ("head", "tree"):
        _require(
            provenance.get(f"candidate_{field}") == freeze[field],
            f"F3_ATTACHMENT_CANDIDATE_{field.upper()}",
            freeze[field],
            provenance.get(f"candidate_{field}"),
            provenance_path.as_posix(),
        )

    artifact_paths = {
        "attachment_result": attachment_path,
        "event_log": output
        / "actual-host"
        / "attachment"
        / "win32-uia-events.jsonl",
        "host_record": repo
        / "r6o_evidence"
        / "H2-D1"
        / "host-environment.json",
        "selectors": repo
        / "r6o"
        / "host"
        / "codex"
        / "windows"
        / "selectors.json",
        "preflight_reset": output / "actual-host" / "preflight-reset.json",
    }
    artifact_hashes: dict[str, str] = {}
    for name, artifact_path in artifact_paths.items():
        relative_path = _repo_relative(repo, artifact_path)
        _require(
            relative_path is not None,
            f"F3_ATTACHMENT_{name.upper()}_PATH_SCOPE",
            "repository-relative path",
            artifact_path.as_posix(),
            provenance_path.as_posix(),
        )
        assert relative_path is not None
        _require(
            provenance.get(f"{name}_path") == relative_path,
            f"F3_ATTACHMENT_{name.upper()}_PATH",
            relative_path,
            provenance.get(f"{name}_path"),
            provenance_path.as_posix(),
        )
        actual_hash = _sha256_file(artifact_path)
        artifact_hashes[name] = actual_hash
        _require(
            provenance.get(f"{name}_sha256") == actual_hash,
            f"F3_ATTACHMENT_{name.upper()}_HASH",
            actual_hash,
            provenance.get(f"{name}_sha256"),
            provenance_path.as_posix(),
        )

    preflight = _read_json(
        artifact_paths["preflight_reset"],
        gate="H2-F3",
        dimension="F3_ATTACHMENT_PREFLIGHT_RESET",
    )
    _require(
        provenance.get("preflight_status") == "CODEX_TEST_SESSION_READY"
        and preflight.get("status") == "CODEX_TEST_SESSION_READY",
        "F3_ATTACHMENT_PREFLIGHT_STATUS",
        "CODEX_TEST_SESSION_READY",
        {
            "provenance": provenance.get("preflight_status"),
            "record": preflight.get("status"),
        },
        provenance_path.as_posix(),
    )
    expected_state = {
        "attachment_status": "H2_D2_ATTACHMENT_PASS",
        "active_attachment": "PASS",
        "real_codex_host_tested": True,
        "synthetic_owner_used": False,
        "reset_to_attachment_contiguous_machine_flow": True,
        "historical_failures_preserved": True,
    }
    for field, expected in expected_state.items():
        _require(
            provenance.get(field) == expected,
            f"F3_ATTACHMENT_{field.upper()}",
            expected,
            provenance.get(field),
            provenance_path.as_posix(),
        )
    _require(
        provenance.get("attachment_status") == attachment_result.get("status")
        and provenance.get("real_codex_host_tested")
        == attachment_result.get("real_codex_host_tested")
        and provenance.get("synthetic_owner_used")
        == attachment_result.get("synthetic_owner_used"),
        "F3_ATTACHMENT_RESULT_BINDING",
        {
            "status": attachment_result.get("status"),
            "real_codex_host_tested": attachment_result.get(
                "real_codex_host_tested"
            ),
            "synthetic_owner_used": attachment_result.get(
                "synthetic_owner_used"
            ),
        },
        {
            "status": provenance.get("attachment_status"),
            "real_codex_host_tested": provenance.get(
                "real_codex_host_tested"
            ),
            "synthetic_owner_used": provenance.get("synthetic_owner_used"),
        },
        provenance_path.as_posix(),
    )
    result_implementation_hashes = attachment_result.get("implementation_sha256")
    for relative_path in (
        "r6o/host/codex/windows/binding.py",
        "r6o/host/codex/windows/placement.py",
        "scripts/h2/verify_codex_attachment.py",
    ):
        expected_hash = _sha256_file(repo / relative_path)
        result_hash = (
            result_implementation_hashes.get(relative_path)
            if isinstance(result_implementation_hashes, dict)
            else None
        )
        _require(
            result_hash == expected_hash,
            "F3_ATTACHMENT_IMPLEMENTATION_HASH",
            {"path": relative_path, "sha256": expected_hash},
            {"path": relative_path, "sha256": result_hash},
            attachment_path.as_posix(),
        )
    result_event_log = attachment_result.get("event_log")
    expected_result_event_log_path = _repo_relative(
        repo,
        artifact_paths["event_log"],
    )
    result_event_log_path = (
        result_event_log.get("path")
        if isinstance(result_event_log, dict)
        else None
    )
    _require(
        result_event_log_path == expected_result_event_log_path,
        "F3_ATTACHMENT_EVENT_LOG_RESULT_PATH_BINDING",
        expected_result_event_log_path,
        result_event_log_path,
        attachment_path.as_posix(),
    )
    result_event_log_hash = (
        result_event_log.get("sha256")
        if isinstance(result_event_log, dict)
        else None
    )
    _require(
        result_event_log_hash == artifact_hashes["event_log"],
        "F3_ATTACHMENT_EVENT_LOG_RESULT_BINDING",
        artifact_hashes["event_log"],
        result_event_log_hash,
        attachment_path.as_posix(),
    )
    return {"status": "PASS", "path": expected_reference}


def _validate_current_host_evidence(*, repo: Path, output: Path, freeze: dict[str, Any]) -> dict[str, str]:
    path = output / "actual-host" / "qualification.json"
    document = _read_json(path, gate="H2-F3", dimension="ACTUAL_HOST_FINAL_EVIDENCE")
    _require(document.get("schema_version") == "r6o-h2-f3-current-actual-host-1", "ACTUAL_HOST_SCHEMA", "r6o-h2-f3-current-actual-host-1", document.get("schema_version"), path.as_posix())
    _require(document.get("status") == CURRENT_ACTUAL_HOST_PASS_TOKEN, "ACTUAL_HOST_STATUS", CURRENT_ACTUAL_HOST_PASS_TOKEN, document.get("status"), path.as_posix())
    _require(document.get("source", {}).get("head") == freeze["head"] and document.get("source", {}).get("tree") == freeze["tree"], "ACTUAL_HOST_SOURCE", {"head": freeze["head"], "tree": freeze["tree"]}, document.get("source"), path.as_posix())
    _require(document.get("human_gesture_synthesized") is False, "ACTUAL_HOST_HUMAN_GESTURE_POLICY", False, document.get("human_gesture_synthesized"), path.as_posix())

    records = document.get("records")
    expected_records = {
        "e1": "actual-host/e1/qualification.json",
        "g06": "actual-host/g06/qualification.json",
        "a02_full": "actual-host/a02-full/qualification.json",
        "lifecycle": "actual-host/lifecycle/qualification.json",
    }
    _require(records == expected_records, "ACTUAL_HOST_RECORDS", expected_records, records, path.as_posix())
    loaded: dict[str, dict[str, Any]] = {}
    for key, relative_path in expected_records.items():
        record_path = output / relative_path
        _require(_is_within(record_path, output), "ACTUAL_HOST_RECORD_SCOPE", "inside F3 repair output", record_path.as_posix(), path.as_posix())
        loaded[key] = _read_json(record_path, gate="H2-F3", dimension=f"ACTUAL_HOST_{key.upper()}_RECORD")

    e1 = loaded["e1"]
    _require(e1.get("schema_version") == "r6o-h2-f3-current-e1-1" and e1.get("status") == "H2_F3_CURRENT_E1_PASS", "CURRENT_E1_STATUS", "H2_F3_CURRENT_E1_PASS", e1.get("status"), expected_records["e1"])
    _require(e1.get("source", {}).get("head") == freeze["head"] and e1.get("source", {}).get("tree") == freeze["tree"], "CURRENT_E1_SOURCE", freeze, e1.get("source"), expected_records["e1"])
    _validate_host_version(e1, gate="H2-F3", path=expected_records["e1"])
    _require(e1.get("captured_text_normalized") == E1_EXPECTED_TEXT, "CURRENT_E1_TEXT", E1_EXPECTED_TEXT, e1.get("captured_text_normalized"), expected_records["e1"])
    for key in (
        "shift_enter_preserved",
        "unmodified_enter_intercepted",
        "native_enter_keydown_suppressed",
        "native_enter_keyup_suppressed",
        "composer_cleared",
        "sidecar_dismissed",
        "actual_composer_focus_restored",
    ):
        _require(e1.get(key) is True, f"CURRENT_E1_{key.upper()}", True, e1.get(key), expected_records["e1"])
    _require(e1.get("native_codex_submission_observed") is False and e1.get("human_gesture_synthesized") is False, "CURRENT_E1_NO_NATIVE_SUBMISSION", False, {"native": e1.get("native_codex_submission_observed"), "synthetic": e1.get("human_gesture_synthesized")}, expected_records["e1"])

    g06 = loaded["g06"]
    _require(g06.get("status") == "H2_E2_G06_PASS", "CURRENT_G06_STATUS", "H2_E2_G06_PASS", g06.get("status"), expected_records["g06"])
    _require(g06.get("code_freeze_head") == freeze["head"] and g06.get("code_freeze_tree") == freeze["tree"], "CURRENT_G06_SOURCE", freeze, {"head": g06.get("code_freeze_head"), "tree": g06.get("code_freeze_tree")}, expected_records["g06"])
    _validate_host_version(g06, gate="H2-F3", path=expected_records["g06"])
    _validate_operations(g06, G06_OPERATIONS, gate="H2-F3", path=expected_records["g06"])
    _require([item.get("action_id") for item in g06.get("structured_action_envelopes", []) if isinstance(item, dict)] == ["confirm_prompt", "confirm_plan"], "CURRENT_G06_ACTIONS", ["confirm_prompt", "confirm_plan"], g06.get("structured_action_envelopes"), expected_records["g06"])
    _require(g06.get("native_codex_submission_observed") is False and g06.get("sidecar_dismissed") is True and g06.get("actual_composer_focus_restored") is True, "CURRENT_G06_TERMINAL", {"native_submission": False, "dismissed": True, "focus_restored": True}, {"native_submission": g06.get("native_codex_submission_observed"), "dismissed": g06.get("sidecar_dismissed"), "focus_restored": g06.get("actual_composer_focus_restored")}, expected_records["g06"])

    a02 = loaded["a02_full"]
    _require(a02.get("status") == "H2_E3_A02_FULL_PASS", "CURRENT_A02_STATUS", "H2_E3_A02_FULL_PASS", a02.get("status"), expected_records["a02_full"])
    _require(a02.get("code_freeze_head") == freeze["head"] and a02.get("code_freeze_tree") == freeze["tree"], "CURRENT_A02_SOURCE", freeze, {"head": a02.get("code_freeze_head"), "tree": a02.get("code_freeze_tree")}, expected_records["a02_full"])
    _validate_host_version(a02, gate="H2-F3", path=expected_records["a02_full"])
    _validate_operations(a02, A02_OPERATIONS, gate="H2-F3", path=expected_records["a02_full"])
    envelopes = a02.get("input_envelopes", [])
    _require([item.get("source") for item in envelopes if isinstance(item, dict)] == ["STRUCTURED_ACTION", "HOST_COMPOSER_TEXT", "STRUCTURED_ACTION", "STRUCTURED_ACTION"], "CURRENT_A02_ENVELOPES", ["STRUCTURED_ACTION", "HOST_COMPOSER_TEXT", "STRUCTURED_ACTION", "STRUCTURED_ACTION"], envelopes, expected_records["a02_full"])
    _require(isinstance(envelopes, list) and len(envelopes) == 4 and envelopes[1].get("text") == REVISION_TEXT, "CURRENT_A02_REVISION", REVISION_TEXT, envelopes[1].get("text") if isinstance(envelopes, list) and len(envelopes) > 1 and isinstance(envelopes[1], dict) else "MISSING", expected_records["a02_full"])
    expected_hashes = [
        hashlib.sha256(A02_INITIAL_PROMPT.encode("utf-8")).hexdigest(),
        hashlib.sha256(A02_REVISED_PROMPT.encode("utf-8")).hexdigest(),
        hashlib.sha256(A02_EXPECTED_PLAN.encode("utf-8")).hexdigest(),
    ]
    transitions = a02.get("transitions", [])
    actual_hashes = [
        transitions[index].get("artifact_body_sha256")
        if isinstance(transitions, list) and len(transitions) > index and isinstance(transitions[index], dict)
        else None
        for index in (0, 2, 3)
    ]
    _require(actual_hashes == expected_hashes, "CURRENT_A02_ARTIFACT_EQUALITY", expected_hashes, actual_hashes, expected_records["a02_full"])
    for key in ("native_enter_keydown_suppressed", "native_enter_keyup_suppressed", "composer_cleared", "sidecar_dismissed", "actual_composer_focus_restored"):
        _require(a02.get(key) is True, f"CURRENT_A02_{key.upper()}", True, a02.get(key), expected_records["a02_full"])
    _require(a02.get("native_codex_submission_observed") is False, "CURRENT_A02_NATIVE_SUBMISSION", False, a02.get("native_codex_submission_observed"), expected_records["a02_full"])

    lifecycle = loaded["lifecycle"]
    _require(lifecycle.get("schema_version") == "r6o-h2-f3-current-lifecycle-1" and lifecycle.get("status") == "H2_F3_CURRENT_LIFECYCLE_PASS", "CURRENT_LIFECYCLE_STATUS", "H2_F3_CURRENT_LIFECYCLE_PASS", lifecycle.get("status"), expected_records["lifecycle"])
    _require(lifecycle.get("source", {}).get("head") == freeze["head"] and lifecycle.get("source", {}).get("tree") == freeze["tree"], "CURRENT_LIFECYCLE_SOURCE", freeze, lifecycle.get("source"), expected_records["lifecycle"])
    _require(lifecycle.get("actual_host", {}).get("status") == "PASS", "CURRENT_LIFECYCLE_ACTUAL_HOST", "PASS", lifecycle.get("actual_host"), expected_records["lifecycle"])
    _require(lifecycle.get("process_exit", {}).get("status") == "PASS" and lifecycle.get("process_exit", {}).get("cleanup_complete_marker") is True and lifecycle.get("process_exit", {}).get("process_terminated") is True, "CURRENT_LIFECYCLE_PROCESS_EXIT", "PASS/cleanup/terminated", lifecycle.get("process_exit"), expected_records["lifecycle"])
    matrix = lifecycle.get("accepted_f2_repair_matrix")
    _require(isinstance(matrix, dict) and matrix and all(isinstance(item, dict) and item.get("status") == "PASS" for item in matrix.values()), "CURRENT_LIFECYCLE_F2_REPAIRS", "all PASS", matrix, expected_records["lifecycle"])

    attachment = document.get("attachment", {})
    _require(
        isinstance(attachment, dict) and attachment.get("status") == "PASS",
        "ACTUAL_HOST_ATTACHMENT_QUALIFICATION_STATUS",
        "PASS",
        attachment.get("status") if isinstance(attachment, dict) else attachment,
        path.as_posix(),
    )
    attachment_path_value = attachment.get("path")
    _require(isinstance(attachment_path_value, str), "ACTUAL_HOST_ATTACHMENT_PATH", "relative path", attachment_path_value, path.as_posix())
    attachment_path = output / Path(attachment_path_value)
    _require(_is_within(attachment_path, output), "ACTUAL_HOST_ATTACHMENT_PATH_SCOPE", "inside F3 output", attachment_path.as_posix(), path.as_posix())
    attachment_result = _read_json(attachment_path, gate="H2-F3", dimension="ACTUAL_HOST_ATTACHMENT_RESULT")
    _require(attachment_result.get("status") == "H2_D2_ATTACHMENT_PASS", "ACTUAL_HOST_ATTACHMENT_STATUS", "H2_D2_ATTACHMENT_PASS", attachment_result.get("status"), attachment_path.as_posix())
    _require(
        document.get("attachment_status") == attachment_result.get("status"),
        "ACTUAL_HOST_ATTACHMENT_RESULT_STATUS_LINK",
        attachment_result.get("status"),
        document.get("attachment_status"),
        path.as_posix(),
    )
    _require(attachment_result.get("real_codex_host_tested") is True and attachment_result.get("synthetic_owner_used") is False, "ACTUAL_HOST_RUNTIME_IDENTITY", {"real_codex_host_tested": True, "synthetic_owner_used": False}, {"real_codex_host_tested": attachment_result.get("real_codex_host_tested"), "synthetic_owner_used": attachment_result.get("synthetic_owner_used")}, attachment_path.as_posix())
    host = attachment_result.get("host", {})
    for key, expected in CURRENT_HOST.items():
        _require(host.get(key) == expected, f"ACTUAL_HOST_{key.upper()}", expected, host.get(key), attachment_path.as_posix())
    host_record = repo / "r6o_evidence" / "H2-D1" / "host-environment.json"
    selectors = repo / "r6o" / "host" / "codex" / "windows" / "selectors.json"
    _require(attachment_result.get("host_record_sha256") == _sha256_file(host_record), "ACTUAL_HOST_RECORD_HASH", _sha256_file(host_record), attachment_result.get("host_record_sha256"), attachment_path.as_posix())
    _require(attachment_result.get("selectors_sha256") == _sha256_file(selectors), "ACTUAL_HOST_SELECTOR_HASH", _sha256_file(selectors), attachment_result.get("selectors_sha256"), attachment_path.as_posix())
    _validate_f3_attachment_provenance(
        repo=repo,
        output=output,
        qualification=document,
        freeze=freeze,
        attachment_path=attachment_path,
        attachment_result=attachment_result,
    )
    dimensions = document.get("dimensions")
    expected_dimensions = {
        "e1_input_routing": "PASS",
        "actual_host_g06": "PASS",
        "actual_host_a02_full": "PASS",
        "lifecycle_resilience": "PASS",
    }
    _require(dimensions == expected_dimensions, "CURRENT_ACTUAL_HOST_DIMENSIONS", expected_dimensions, dimensions, path.as_posix())
    return {
        "status": "PASS",
        "attachment": "PASS",
        "e1_input_routing": "PASS",
        "actual_host_g06": "PASS",
        "actual_host_a02_full": "PASS",
        "lifecycle_resilience": "PASS",
    }


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
        for key in ("linux_x11", "linux_wayland"):
            ci_job = platforms[key].get("ci_job")
            _require(
                isinstance(ci_job, dict)
                and ci_job.get("status") == "SUCCESS"
                and ci_job == ci.get("jobs", {}).get(key),
                "QT_CI_JOB",
                ci.get("jobs", {}).get(key),
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


def _validate_ci(*, repo: Path, path: Path, freeze: dict[str, Any]) -> dict[str, Any]:
    document = _read_json(path, gate="H2-F3", dimension="FINAL_CI_EVIDENCE")
    _require(document.get("schema_version") == "r6o-h2-f3-ci-1", "CI_EVIDENCE_SCHEMA", "r6o-h2-f3-ci-1", document.get("schema_version"), path.as_posix())
    candidate = document.get("candidate")
    _require(isinstance(candidate, dict), "CI_CANDIDATE_SCHEMA", "object", candidate, path.as_posix())
    assert isinstance(candidate, dict)
    _require(candidate.get("head") == freeze["head"] and candidate.get("tree") == freeze["tree"], "CI_CANDIDATE", {"head": freeze["head"], "tree": freeze["tree"]}, candidate, path.as_posix())
    workflows = document.get("workflows")
    _require(isinstance(workflows, list), "CI_WORKFLOW_SCHEMA", "list", type(workflows).__name__, path.as_posix())
    workflow_names = [item.get("workflow") for item in workflows if isinstance(item, dict)]
    for required_workflow in CI_REQUIREMENTS:
        _require(workflow_names.count(required_workflow) == 1, "CI_REQUIRED_WORKFLOW_COUNT", {required_workflow: 1}, {required_workflow: workflow_names.count(required_workflow)}, path.as_posix())
    by_name = {item.get("workflow"): item for item in workflows if isinstance(item, dict)}
    validated_workflows: dict[str, Any] = {}
    validated_jobs: dict[str, Any] = {}
    platforms: dict[str, str] = {}
    for workflow, jobs in CI_REQUIREMENTS.items():
        item = by_name.get(workflow)
        _require(isinstance(item, dict), "CI_REQUIRED_WORKFLOW", workflow, item, path.as_posix())
        assert isinstance(item, dict)
        _require(item.get("head_sha") == freeze["head"] and item.get("status") == "SUCCESS", "CI_WORKFLOW_HEAD", {"head_sha": freeze["head"], "status": "SUCCESS"}, {"head_sha": item.get("head_sha"), "status": item.get("status")}, {"workflow": workflow, "path": path.as_posix()})
        run_id = item.get("run_id")
        run_url = item.get("run_url")
        _require(isinstance(run_id, int) and run_id > 0, "CI_WORKFLOW_RUN_ID", "positive integer", run_id, {"workflow": workflow, "path": path.as_posix()})
        _require(
            isinstance(run_url, str)
            and run_url == f"https://github.com/paragon-ux/PDL-Standard-R6O/actions/runs/{run_id}",
            "CI_WORKFLOW_RUN_URL",
            f"https://github.com/paragon-ux/PDL-Standard-R6O/actions/runs/{run_id}",
            run_url,
            {"workflow": workflow, "path": path.as_posix()},
        )
        job_records = item.get("jobs")
        _require(isinstance(job_records, dict), "CI_JOB_SCHEMA", "object", job_records, {"workflow": workflow, "path": path.as_posix()})
        validated_workflows[workflow] = {
            "workflow": workflow,
            "run_id": run_id,
            "run_url": run_url,
            "head_sha": freeze["head"],
            "status": "SUCCESS",
        }
        for job, expected_name in jobs.items():
            record = job_records.get(job)
            _require(isinstance(record, dict) and record.get("status") == "SUCCESS", "CI_JOB_STATUS", {"job": job, "status": "SUCCESS"}, record, {"workflow": workflow, "path": path.as_posix()})
            assert isinstance(record, dict)
            job_id = record.get("job_id")
            expected_job_url = (
                f"https://github.com/paragon-ux/PDL-Standard-R6O/actions/runs/"
                f"{run_id}/job/{job_id}"
            )
            _require(
                record.get("head_sha") == freeze["head"]
                and record.get("workflow_run_id") == run_id
                and record.get("workflow") == workflow
                and record.get("name") == expected_name,
                "CI_JOB_PROVENANCE",
                {
                    "head_sha": freeze["head"],
                    "workflow_run_id": run_id,
                    "workflow": workflow,
                    "name": expected_name,
                },
                record,
                {"workflow": workflow, "job": job, "path": path.as_posix()},
            )
            _require(
                isinstance(job_id, int)
                and job_id > 0
                and record.get("job_url") == expected_job_url,
                "CI_JOB_URL",
                expected_job_url,
                record.get("job_url"),
                {"workflow": workflow, "job": job, "path": path.as_posix()},
            )
            validated_jobs[job] = dict(record)
            platforms[job] = "PASS"
    _require(document.get("all_required_jobs_passed") is True, "CI_ALL_REQUIRED", True, document.get("all_required_jobs_passed"), path.as_posix())
    return {
        "candidate": {"head": candidate["head"], "tree": candidate["tree"]},
        "workflows": validated_workflows,
        "jobs": validated_jobs,
        "platforms": platforms,
        **platforms,
    }


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
    _require(document.get("actual_host", {}).get("status") in {"PASS", "HUMAN_PENDING"}, "LOCAL_ACTUAL_HOST", "PASS or HUMAN_PENDING", document.get("actual_host"), path.as_posix())
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
    f3_root = output.parent if output.name == "repair" and output.parent.name == "H2-F3" else output
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
    base = _validate_base(repo=repo, base_record=f3_root / "base.json", current=current)
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
    actual_host = _validate_current_host_evidence(repo=repo, output=output, freeze=freeze) if require_actual_host else {"status": "HUMAN_PENDING"}
    ci = _validate_ci(repo=repo, path=output / "ci.json", freeze=freeze) if require_ci else None
    qt = _validate_qt_evidence(repo=repo, output=output, freeze=freeze, ci=ci) if require_qt else {"status": "NOT_REQUIRED"}
    ci_report = ci if ci is not None else {"status": "NOT_REQUIRED"}
    human = _validate_human_record(repo=repo, evidence=evidence)
    _validate_no_r6o3(_collect_r6o3_documents(evidence=evidence, f3_root=f3_root))
    final_ready = require_local and require_actual_host and require_qt and require_ci
    report_status = (
        "H2_F3_FINAL_INTEGRATION_PASS"
        if final_ready
        else "H2_F3_CURRENT_ACTUAL_HOST_HUMAN_PENDING"
    )
    report = {
        "schema_version": "r6o-h2-f3-final-integration-1",
        "gate": "H2-F3",
        "status": report_status,
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
            "accepted_e1_input_routing": e1,
            "accepted_actual_host_g06": e2,
            "accepted_actual_host_a02_full": e3,
            "e1_input_routing": actual_host.get("e1_input_routing", actual_host.get("status")),
            "actual_host_g06": actual_host.get("actual_host_g06", actual_host.get("status")),
            "actual_host_a02_full": actual_host.get("actual_host_a02_full", actual_host.get("status")),
            "cross_view_parity": f1,
            "accepted_lifecycle_resilience": f2["status"],
            "lifecycle_resilience": actual_host.get("lifecycle_resilience", actual_host.get("status")),
            "f2_second_repair_provenance": "PASS",
            "final_ci": ci_report.get("platforms", ci_report),
        },
        "production_behavior_changed": False,
        "r6o3_behavior_claimed": False,
        "known_findings": [
            "RPC_E_CHANGED_MODE=NONBLOCKING_P2",
            "F3-R3-ATTACHMENT-PROVENANCE-MISMATCH=OPEN_P2_OWNER_GATE",
            "F3-R5-HUMAN-GATE-CANDIDATE-NOT-PINNED=OPEN_P2_F3",
        ],
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
    current = _source_identity(repo)
    _require(not current["dirty_paths"], "LOCAL_COLLECTION_WORKTREE", [], current["dirty_paths"], current)
    output.mkdir(parents=True, exist_ok=True)
    f3_root = output.parent if output.name == "repair" and output.parent.name == "H2-F3" else output
    base_document = _read_json(f3_root / "base.json", gate="H2-F3", dimension="F3_BASE_RECORD")
    base = base_document.get("base")
    _require(isinstance(base, dict), "F3_BASE_IDENTITY", "base object", base, output / "base.json")
    assert isinstance(base, dict)
    freeze = _write_code_freeze(repo=repo, output=output, base={"head": base["head"], "tree": base["tree"]})
    _json_write(
        output / "authority.json",
        {
            "schema_version": "r6o-h2-f3-bounded-repair-authority-1",
            "gate": "H2-F3",
            "agent": "SOL-H2-F3-BOUNDED-REPAIR",
            "trigger": "SOL_F3_REVIEW_REQUEST_CHANGES",
            "repair_base": {
                "head": "ac1a0a465a38a5f86e28cab940c281a53705f052",
                "tree": "7c1f15aca91438695be54d5ea25ba6611e281fb3",
            },
            "repaired_code_freeze": freeze,
            "automatic_repair_budget_remaining": 0,
            "production_behavior_changed": False,
            "r6o3_behavior_claimed": False,
            "next_authority": "HUMAN-H2",
            "human_pass": "NOT_CLAIMED",
        },
    )
    _json_write(
        output / "review-findings.json",
        {
            "schema_version": "r6o-h2-f3-review-findings-1",
            "gate": "H2-F3",
            "initial_review": "REQUEST_CHANGES",
            "blocking_findings": {
                "F3-R1-QT-CI-JOB-PROVENANCE-BYPASS": "FIXED_PENDING_INDEPENDENT_DELTA_REVIEW",
                "F3-R2-CURRENT-ACTUAL-HOST-INTEGRATION-INSUFFICIENT": "HUMAN_ACTION_REQUIRED",
                "F3-R4-R6O3-FINAL-EVIDENCE-SCAN-GAP": "FIXED_PENDING_INDEPENDENT_DELTA_REVIEW",
            },
            "known_nonblocking_findings": {
                "RPC_E_CHANGED_MODE": "NONBLOCKING_P2",
                "F3-R3-ATTACHMENT-PROVENANCE-MISMATCH": "OPEN_P2_OWNER_GATE",
                "F3-R5-HUMAN-GATE-CANDIDATE-NOT-PINNED": "OPEN_P2_F3",
            },
            "automatic_repair_budget_remaining": 0,
            "human_pass": "NOT_CLAIMED",
        },
    )
    python = sys.executable
    baseline_text = str(baseline.resolve())
    output_relative = output.resolve().relative_to(repo.resolve()).as_posix()
    commands: list[dict[str, Any]] = []
    commands.append(_run_command(repo=repo, output=output, identifier="f3_focused_tests", arguments=[python, "-m", "pytest", "r6o/tests/h2/test_h2_final_integration.py", "-q", "-p", "no:cacheprovider"]))
    commands.append(_run_command(repo=repo, output=output, identifier="e1_e2_e3_regression", arguments=[python, "-m", "pytest", "r6o/tests/h2/test_codex_input_binding_contract.py", "r6o/tests/h2/test_codex_h2_e2.py", "r6o/tests/h2/test_codex_h2_e3.py", "-q", "-p", "no:cacheprovider"]))
    commands.append(_run_command(repo=repo, output=output, identifier="qt_focused_tests", arguments=[python, "-m", "pytest", "r6o/tests/h2/test_qt_sidecar_feasibility.py", "r6o/tests/h2/test_qt_sidecar_component.py", "-q", "-p", "no:cacheprovider"], environment={"QT_QUICK_BACKEND": "software", "QT_SCALE_FACTOR": "1", "QT_FONT_DPI": "96"}))
    commands.append(_run_command(repo=repo, output=output, identifier="full_r6o", arguments=[python, "-m", "pytest", "r6o/tests", "-q", "-p", "no:cacheprovider"]))
    commands.append(_run_command(repo=repo, output=output, identifier="r6o1_verification", arguments=[python, "scripts/verify_r6o1.py"], environment={"PDL_R6S_BASELINE_REPO": baseline_text}))
    commands.append(_run_command(repo=repo, output=output, identifier="tui_g06", arguments=[python, "scripts/h2/verify_tui_g06.py", "--baseline-repo", baseline_text, "--evidence-dir", f"{output_relative}/tui-g06"]))
    commands.append(_run_command(repo=repo, output=output, identifier="tui_a02_full", arguments=[python, "scripts/h2/verify_tui_a02_full.py", "--baseline-repo", baseline_text, "--evidence-dir", f"{output_relative}/tui-a02-full"]))
    commands.append(_run_command(repo=repo, output=output, identifier="f1_parity_verifier", arguments=[python, "scripts/h2/verify_cross_view_parity.py", "--baseline-repo", baseline_text, "--output-dir", f"{output_relative}/f1-parity-rerun"]))
    commands.append(_run_command(repo=repo, output=output, identifier="f2_portable_verifier", arguments=[python, "scripts/h2/verify_h2_lifecycle_resilience.py", "--mode", "portable", "--baseline-repo", baseline_text, "--evidence-dir", f"{output_relative}/f2-portable"]))
    commands.append(_run_command(repo=repo, output=output, identifier="qt_windows_qualification", arguments=[python, "scripts/h2/verify_qt_sidecar_component.py", "--platform", "windows", "--evidence-dir", f"{output_relative}/qt"], environment={"QT_QUICK_BACKEND": "software", "QT_SCALE_FACTOR": "1", "QT_FONT_DPI": "96"}))
    if os.name == "nt":
        commands.append(_run_command(repo=repo, output=output, identifier="actual_codex_attachment", arguments=[python, "scripts/h2/verify_codex_attachment.py", "--host-record", "r6o_evidence/H2-D1/host-environment.json", "--selectors", "r6o/host/codex/windows/selectors.json", "--evidence-dir", f"{output_relative}/actual-host/attachment"], environment={"QT_QUICK_BACKEND": "software", "QT_SCALE_FACTOR": "1", "QT_FONT_DPI": "96"}))
    else:
        commands.append({"id": "actual_codex_attachment", "command": "Windows-only actual Codex attachment verifier", "exit_code": 1, "status": "FAIL", "reason": "F3 requires WINDOWS_LOCAL_ACTUAL_CODEX"})

    attachment_path = output / "actual-host" / "attachment" / "attachment-result.json"
    attachment_status = "PASS" if attachment_path.is_file() and _read_json(attachment_path, gate="H2-F3", dimension="ACTUAL_HOST_COLLECTION").get("status") == "H2_D2_ATTACHMENT_PASS" else "FAIL"
    _json_write(output / "actual-host" / "qualification.json", {
        "schema_version": "r6o-h2-f3-current-actual-host-pending-1",
        "gate": "H2-F3",
        "status": "HUMAN_PENDING",
        "source": freeze,
        "attachment": {"status": attachment_status, "path": "actual-host/attachment/attachment-result.json"},
        "current_candidate_dimensions": {
            "e1_input_routing": "HUMAN_PENDING",
            "actual_host_g06": "HUMAN_PENDING",
            "actual_host_a02_full": "HUMAN_PENDING",
            "lifecycle_resilience": "HUMAN_PENDING",
        },
        "human_gesture_synthesized": False,
        "gesture_policy": "The repaired candidate is not qualified until HUMAN-H2 completes the F3 current-host command.",
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
        "actual_host": {"status": "HUMAN_PENDING", "attachment_status": attachment_status, "evidence": "actual-host/qualification.json"},
        "known_findings": [
            "RPC_E_CHANGED_MODE=NONBLOCKING_P2",
            "F3-R3-ATTACHMENT-PROVENANCE-MISMATCH=OPEN_P2_OWNER_GATE",
            "F3-R5-HUMAN-GATE-CANDIDATE-NOT-PINNED=OPEN_P2_F3",
        ],
        "human_gesture_synthesized": False,
    }
    _json_write(output / "local-qualification.json", local)
    _json_write(
        output / "qualification-summary.json",
        {
            "schema_version": "r6o-h2-f3-bounded-repair-summary-1",
            "gate": "H2-F3",
            "status": "HUMAN_ACTION_REQUIRED",
            "source": freeze,
            "r1_qt_ci_job_provenance": "FIXED_PENDING_EXACT_HEAD_CI",
            "r2_current_actual_host_integration": "HUMAN_ACTION_REQUIRED",
            "r4_r6o3_fail_closed": "FIXED",
            "local_qualification": {
                "status": "PASS" if all(item.get("status") == "PASS" for item in commands) else "FAIL",
                "counts": counts,
            },
            "production_behavior_changed": False,
            "r6o3_behavior_claimed": False,
            "implementation_complete": False,
            "ready_for_luna_repair_delta_review": False,
            "next_authority": "HUMAN-H2",
            "human_pass": "NOT_CLAIMED",
        },
    )
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


def _verify_repaired_candidate(
    *, repo: Path, output: Path, expected_head: str, expected_tree: str
) -> dict[str, str]:
    _require(len(expected_head) == 40 and len(expected_tree) == 40, "REPAIRED_FREEZE_ARGUMENTS", "40-character head/tree", {"head": expected_head, "tree": expected_tree}, output.as_posix())
    current = _source_identity(repo)
    _require(current["branch"] == "codex/h2-f3-final-integration", "REPAIRED_FREEZE_BRANCH", "codex/h2-f3-final-integration", current["branch"], current)
    _require(current["head"] == expected_head and current["tree"] == expected_tree, "REPAIRED_FREEZE_CHECKOUT", {"head": expected_head, "tree": expected_tree}, {"head": current["head"], "tree": current["tree"]}, current)
    _require(_git_tree(repo, expected_head) == expected_tree, "REPAIRED_FREEZE_TREE", expected_tree, _git_tree(repo, expected_head), {"head": expected_head})
    output_prefix = output.resolve().relative_to(repo.resolve()).as_posix().rstrip("/") + "/"
    unauthorized = [
        path
        for path in current["dirty_paths"]
        if not path.replace("\\", "/").startswith(output_prefix)
    ]
    _require(not unauthorized, "REPAIRED_FREEZE_WORKTREE_SCOPE", [output_prefix], unauthorized, current)
    freeze_record = _read_json(output / "code-freeze.json", gate="H2-F3", dimension="REPAIRED_CODE_FREEZE_RECORD")
    freeze = freeze_record.get("code_freeze")
    _require(isinstance(freeze, dict) and freeze.get("head") == expected_head and freeze.get("tree") == expected_tree and freeze.get("status") == "FROZEN", "REPAIRED_CODE_FREEZE_RECORD", {"head": expected_head, "tree": expected_tree, "status": "FROZEN"}, freeze, (output / "code-freeze.json").as_posix())
    return {
        "branch": current["branch"],
        "head": expected_head,
        "tree": expected_tree,
        "code_freeze_head": expected_head,
        "code_freeze_tree": expected_tree,
        "status": "FROZEN",
    }


def _collect_current_e1(
    *, host_record: Path, selectors: Path, source: dict[str, str], timeout: float
) -> dict[str, Any]:
    if os.name != "nt":
        _fail("CURRENT_E1_PLATFORM", "Windows", os.name, source)
    from r6o.host.codex.windows.binding import CodexSidecarBinding
    from r6o.host.codex.windows.input_binding import CodexComposerInputBinding
    from scripts.h2.run_codex_h2_e2 import (
        _host_identity,
        _host_session_observation,
        _post_terminal_no_submission_ledger,
        _require_safe_host_session,
    )
    from scripts.h2.verify_h2_lifecycle_resilience import canonical_projection

    host: Any | None = None
    input_binding: Any | None = None
    captured: list[dict[str, Any]] = []
    projection = canonical_projection(
        projection_id="h2-f3-current-e1",
        body="# H2-F3 current E1 input-routing qualification\n",
    )
    try:
        host = CodexSidecarBinding(host_record, selectors)
        preflight = _host_session_observation(host)
        _require_safe_host_session(preflight, phase="F3_CURRENT_E1_INITIAL")
        attachment = host.attach(projection, settle_seconds=0.25)
        _require(attachment.get("visible") is True and attachment.get("global_topmost") is False, "CURRENT_E1_ATTACHMENT", {"visible": True, "global_topmost": False}, attachment, source)

        def on_envelope(envelope: dict[str, Any]) -> None:
            captured.append(dict(envelope))

        input_binding = CodexComposerInputBinding(host, on_envelope)
        input_binding.start()
        input_binding.activate(projection)
        print(
            "HUMAN_ACTION_REQUIRED E1: type H2-F3-E1-LINE-1, press Shift+Enter, "
            "type H2-F3-E1-LINE-2, then press one unmodified Enter. Do not use Send.",
            flush=True,
        )
        delivered = input_binding.wait_for_delivery(timeout=timeout)
        raw_text = delivered.get("text")
        normalized = raw_text.replace("\r\n", "\n").replace("\r", "\n") if isinstance(raw_text, str) else raw_text
        _require(normalized == E1_EXPECTED_TEXT, "CURRENT_E1_CAPTURED_TEXT", E1_EXPECTED_TEXT, normalized, source)
        _require(len(captured) == 1 and input_binding.capture_count == 1 and input_binding.delivery_count == 1, "CURRENT_E1_DELIVERY_COUNT", {"callback": 1, "capture": 1, "delivery": 1}, {"callback": len(captured), "capture": input_binding.capture_count, "delivery": input_binding.delivery_count}, source)
        _require(input_binding.suppressed_keydown_count == 1 and input_binding.suppressed_keyup_count == 1, "CURRENT_E1_ENTER_PAIR", {"keydown": 1, "keyup": 1}, {"keydown": input_binding.suppressed_keydown_count, "keyup": input_binding.suppressed_keyup_count}, source)
        input_binding.deactivate()
        input_binding.stop()
        input_binding = None
        focus_return = host.close_view_and_verify_focus()
        post_ledger = _post_terminal_no_submission_ledger(host)
        postflight = {
            "composer": post_ledger[-1]["composer"],
            "conversation": post_ledger[-1]["conversation"],
        }
        no_native_submission = (
            preflight["conversation"]["visible_turn_group_count"] == 0
            and postflight["conversation"]["visible_turn_group_count"] == 0
            and postflight["composer"]["empty"] is True
        )
        _require(no_native_submission, "CURRENT_E1_NATIVE_SUBMISSION", False, True, source)
        return {
            "schema_version": "r6o-h2-f3-current-e1-1",
            "gate": "H2-F3",
            "status": "H2_F3_CURRENT_E1_PASS",
            "source": {"head": source["head"], "tree": source["tree"], "status": "FROZEN"},
            "actual_codex_host": _host_identity(host),
            "host_preflight": preflight,
            "host_postflight": postflight,
            "post_terminal_no_submission_ledger": post_ledger,
            "captured_text_raw": raw_text,
            "captured_text_normalized": normalized,
            "shift_enter_preserved": "\n" in normalized,
            "unmodified_enter_intercepted": True,
            "native_enter_keydown_suppressed": True,
            "native_enter_keyup_suppressed": True,
            "native_codex_submission_observed": False,
            "composer_cleared": True,
            "sidecar_dismissed": focus_return.get("sidecar_visible") is False,
            "actual_composer_focus_restored": focus_return.get("composer_keyboard_focus") is True,
            "human_gesture_synthesized": False,
        }
    finally:
        if input_binding is not None:
            try:
                input_binding.abort_handoff()
            finally:
                input_binding.stop()
        if host is not None:
            host.close()


def collect_current_actual_host(
    *,
    repo: Path,
    output: Path,
    baseline: Path,
    expected_head: str,
    expected_tree: str,
    timeout: float,
) -> dict[str, Any]:
    source = _verify_repaired_candidate(
        repo=repo,
        output=output,
        expected_head=expected_head,
        expected_tree=expected_tree,
    )
    _validate_oracle(oracle=baseline)
    host_record = repo / "r6o_evidence" / "H2-D1" / "host-environment.json"
    selectors = repo / "r6o" / "host" / "codex" / "windows" / "selectors.json"
    actual_host_root = output / "actual-host"

    e1 = _collect_current_e1(
        host_record=host_record,
        selectors=selectors,
        source=source,
        timeout=timeout,
    )
    _json_write(actual_host_root / "e1" / "qualification.json", e1)

    from scripts.h2 import run_codex_h2_e2 as e2_runner
    from scripts.h2 import run_codex_h2_e3 as e3_runner
    from scripts.h2 import verify_h2_lifecycle_resilience as f2_runner

    checkout = {
        "branch": source["branch"],
        "head": source["head"],
        "tree": source["tree"],
        "code_freeze_head": source["head"],
        "code_freeze_tree": source["tree"],
    }
    print(
        "HUMAN_ACTION_REQUIRED G06: review the displayed G06 Prompt, activate "
        "Confirm this prompt, then review the Plan and activate Confirm this plan.",
        flush=True,
    )
    g06_dir = actual_host_root / "g06"
    g06_args = argparse.Namespace(
        baseline_repo=baseline,
        workspace_root=None,
        host_record=host_record,
        selectors=selectors,
        evidence_dir=g06_dir,
        timeout=timeout,
    )
    g06 = e2_runner.run(g06_args, checkout, 1)
    _json_write(g06_dir / "qualification.json", g06)

    print(
        "HUMAN_ACTION_REQUIRED A02-FULL: on the initial Prompt activate Something else; "
        f"type exactly {REVISION_TEXT!r}; press one unmodified Enter; then activate "
        "Confirm this prompt and Confirm this plan in order.",
        flush=True,
    )
    a02_dir = actual_host_root / "a02-full"
    a02_args = argparse.Namespace(
        baseline_repo=baseline,
        workspace_root=None,
        host_record=host_record,
        selectors=selectors,
        evidence_dir=a02_dir,
        timeout=timeout,
    )
    a02 = e3_runner.run(a02_args, checkout, 1)
    _json_write(a02_dir / "qualification.json", a02)

    print(
        "LIFECYCLE_OBSERVATION: no human gestures are requested while the collector "
        "checks close/deactivate, hook cleanup, reopen, projection restoration, and process exit.",
        flush=True,
    )
    input_boundary = f2_runner.qualify_input_boundary()
    qt_lifecycle = f2_runner.qualify_qt_lifecycle()
    actual_lifecycle = f2_runner.qualify_actual_host(host_record, selectors, 0.25)
    process_exit = f2_runner.qualify_process_exit(
        host_record,
        selectors,
        probe_mode="actual-host",
        settle_seconds=0.25,
    )
    repair_matrix = f2_runner.derive_repair_resilience_matrix(
        input_boundary,
        qt_lifecycle,
        process_exit,
    )
    lifecycle = {
        "schema_version": "r6o-h2-f3-current-lifecycle-1",
        "gate": "H2-F3",
        "status": "H2_F3_CURRENT_LIFECYCLE_PASS",
        "source": {"head": source["head"], "tree": source["tree"], "status": "FROZEN"},
        "actual_host": actual_lifecycle,
        "process_exit": process_exit,
        "accepted_f2_repair_matrix": repair_matrix,
        "d2_regression": f2_runner.qualify_accepted_d2_regression(),
        "warnings": f2_runner.warning_triage(),
        "r6o3_lease_implemented": False,
    }
    _json_write(actual_host_root / "lifecycle" / "qualification.json", lifecycle)

    attachment_path = actual_host_root / "attachment" / "attachment-result.json"
    attachment = _read_json(attachment_path, gate="H2-F3", dimension="ACTUAL_HOST_ATTACHMENT_RESULT")
    event_log_path = actual_host_root / "attachment" / "win32-uia-events.jsonl"
    summary = {
        "schema_version": "r6o-h2-f3-current-actual-host-1",
        "gate": "H2-F3",
        "status": CURRENT_ACTUAL_HOST_PASS_TOKEN,
        "source": {"head": source["head"], "tree": source["tree"], "status": "FROZEN"},
        "actual_codex_host": e1["actual_codex_host"],
        "records": {
            "e1": "actual-host/e1/qualification.json",
            "g06": "actual-host/g06/qualification.json",
            "a02_full": "actual-host/a02-full/qualification.json",
            "lifecycle": "actual-host/lifecycle/qualification.json",
        },
        "dimensions": {
            "e1_input_routing": "PASS",
            "actual_host_g06": "PASS",
            "actual_host_a02_full": "PASS",
            "lifecycle_resilience": "PASS",
        },
        "attachment": {
            "status": "PASS",
            "path": "actual-host/attachment/attachment-result.json",
        },
        "f3_local_event_log": {
            "path": "actual-host/attachment/win32-uia-events.jsonl",
            "sha256": _sha256_file(event_log_path),
        },
        "attachment_status": attachment.get("status"),
        "human_gesture_synthesized": False,
        "r6o3_behavior_claimed": False,
        "known_findings": [
            "F3-R3-ATTACHMENT-PROVENANCE-MISMATCH=OPEN_P2_OWNER_GATE",
            "F3-R5-HUMAN-GATE-CANDIDATE-NOT-PINNED=OPEN_P2_F3",
        ],
    }
    _json_write(actual_host_root / "qualification.json", summary)
    print(CURRENT_ACTUAL_HOST_PASS_TOKEN, flush=True)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-repo", type=Path)
    parser.add_argument("--evidence-root", type=Path, default=EVIDENCE_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--collect-local", action="store_true")
    parser.add_argument("--collect-current-actual-host", action="store_true")
    parser.add_argument("--repair-freeze-head")
    parser.add_argument("--repair-freeze-tree")
    parser.add_argument("--human-action-timeout", type=float, default=300.0)
    parser.add_argument("--finalize-qt", action="store_true")
    parser.add_argument("--allow-pending-ci", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--allow-missing-actual-host", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--allow-pending-qt", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--allow-missing-local", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--probe-repository-import-bootstrap", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.probe_repository_import_bootstrap:
            from r6o.host.codex.windows.binding import CodexSidecarBinding

            assert CodexSidecarBinding is not None
            print("H2_F3_REPOSITORY_IMPORT_BOOTSTRAP_PASS", flush=True)
            return 0
        baseline = args.baseline_repo or (Path(os.environ["PDL_R6S_BASELINE_REPO"]) if os.environ.get("PDL_R6S_BASELINE_REPO") else None)
        if args.collect_local:
            if baseline is None:
                _fail("FROZEN_ORACLE_INPUT", "--baseline-repo or PDL_R6S_BASELINE_REPO", "MISSING", "H2-F3")
            collect_local_qualification(repo=ROOT, output=args.output_dir.resolve(), baseline=baseline.resolve())
        if args.finalize_qt:
            _finalize_qt(output=args.output_dir.resolve(), ci_path=(args.output_dir.resolve() / "ci.json"))
        if args.collect_current_actual_host:
            if baseline is None:
                _fail("FROZEN_ORACLE_INPUT", "--baseline-repo or PDL_R6S_BASELINE_REPO", "MISSING", "H2-F3")
            if args.repair_freeze_head is None or args.repair_freeze_tree is None:
                _fail("REPAIRED_FREEZE_ARGUMENTS", "--repair-freeze-head and --repair-freeze-tree", "MISSING", "H2-F3")
            collect_current_actual_host(
                repo=ROOT,
                output=args.output_dir.resolve(),
                baseline=baseline.resolve(),
                expected_head=args.repair_freeze_head,
                expected_tree=args.repair_freeze_tree,
                timeout=args.human_action_timeout,
            )
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
