from __future__ import annotations

"""Canonical machine-only H2-F3 reset/attachment provenance transaction."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[2]
ATTACHMENT_RESULT_SCHEMA = "r6o-h2-d2-attachment-result-1"
ATTACHMENT_RESULT_GATE = "H2-D2"
ATTACHMENT_RESULT_PASS = "H2_D2_ATTACHMENT_PASS"
PROVENANCE_SCHEMA = "r6o-h2-f3-attachment-provenance-1"
PROVENANCE_GATE = "H2-F3"
PROVENANCE_REFERENCE = "actual-host/attachment/f3-provenance.json"
ATTACHMENT_REFERENCE = "actual-host/attachment/attachment-result.json"
EVENT_LOG_REFERENCE = "actual-host/attachment/win32-uia-events.jsonl"
PREFLIGHT_REFERENCE = "actual-host/preflight-reset.json"
HOST_RECORD_REFERENCE = "r6o_evidence/H2-D1/host-environment.json"
SELECTORS_REFERENCE = "r6o/host/codex/windows/selectors.json"
PRODUCER_IMPLEMENTATION_PATHS = (
    "r6o/host/codex/windows/binding.py",
    "r6o/host/codex/windows/placement.py",
    "scripts/h2/verify_codex_attachment.py",
)


class F3AttachmentTransactionError(RuntimeError):
    """Stable fail-closed canonical transaction diagnostic."""

    def __init__(self, dimension: str, expected: object, actual: object) -> None:
        self.dimension = dimension
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"DIMENSION={dimension} EXPECTED={expected!r} ACTUAL={actual!r}"
        )


def _require(condition: bool, dimension: str, expected: object, actual: object) -> None:
    if not condition:
        raise F3AttachmentTransactionError(dimension, expected, actual)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path, *, dimension: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise F3AttachmentTransactionError(dimension, "readable JSON object", repr(exc)) from exc
    _require(isinstance(value, dict), dimension, "JSON object", type(value).__name__)
    return value


def _write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def _repo_relative(repo: Path, path: Path, *, dimension: str) -> str:
    try:
        return path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError as exc:
        raise F3AttachmentTransactionError(
            dimension,
            "repository-relative path",
            path.resolve().as_posix(),
        ) from exc


def _git(repo: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise F3AttachmentTransactionError(
            "CANDIDATE_GIT_IDENTITY",
            {"exit_code": 0, "command": ["git", *arguments]},
            {"exit_code": result.returncode, "stderr": result.stderr.strip()},
        )
    return result.stdout.strip()


def _candidate_identity(repo: Path) -> dict[str, str]:
    head = _git(repo, "rev-parse", "HEAD")
    tree = _git(repo, "rev-parse", "HEAD^{tree}")
    _require(len(head) == 40 and len(tree) == 40, "CANDIDATE_IDENTITY", "40-character head/tree", {"head": head, "tree": tree})
    return {"head": head, "tree": tree}


def _run_command(
    arguments: Sequence[str],
    *,
    repo: Path,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if environment:
        env.update(environment)
    return subprocess.run(
        list(arguments),
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _validate_reset(*, reset_path: Path, selectors_path: Path) -> dict[str, Any]:
    reset = _read_json(reset_path, dimension="RESET_RESULT")
    _require(
        reset.get("schema_version") == "r6o-h2-d1-reset-log-1",
        "RESET_SCHEMA",
        "r6o-h2-d1-reset-log-1",
        reset.get("schema_version"),
    )
    _require(
        reset.get("status") == "CODEX_TEST_SESSION_READY",
        "RESET_STATUS",
        "CODEX_TEST_SESSION_READY",
        reset.get("status"),
    )
    _require(
        reset.get("selectors_sha256") == _sha256_file(selectors_path),
        "RESET_SELECTORS_HASH",
        _sha256_file(selectors_path),
        reset.get("selectors_sha256"),
    )
    return reset


def validate_attachment_result(
    *,
    repo: Path,
    attachment_path: Path,
    event_log_path: Path,
    host_record_path: Path,
    selectors_path: Path,
) -> dict[str, Any]:
    """Validate the complete producer contract before any PASS provenance write."""

    attachment = _read_json(attachment_path, dimension="ATTACHMENT_RESULT")
    exact_fields = {
        "schema_version": ATTACHMENT_RESULT_SCHEMA,
        "gate": ATTACHMENT_RESULT_GATE,
        "status": ATTACHMENT_RESULT_PASS,
        "real_codex_host_tested": True,
        "synthetic_owner_used": False,
    }
    for field, expected in exact_fields.items():
        _require(
            attachment.get(field) == expected,
            f"ATTACHMENT_RESULT_{field.upper()}",
            expected,
            attachment.get(field),
        )

    event_log = attachment.get("event_log")
    _require(isinstance(event_log, dict), "ATTACHMENT_RESULT_EVENT_LOG", "object", event_log)
    expected_event_path = _repo_relative(
        repo,
        event_log_path,
        dimension="ATTACHMENT_RESULT_EVENT_LOG_PATH_SCOPE",
    )
    _require(
        event_log.get("path") == expected_event_path,
        "ATTACHMENT_RESULT_EVENT_LOG_PATH",
        expected_event_path,
        event_log.get("path"),
    )
    expected_event_hash = _sha256_file(event_log_path)
    _require(
        event_log.get("sha256") == expected_event_hash,
        "ATTACHMENT_RESULT_EVENT_LOG_HASH",
        expected_event_hash,
        event_log.get("sha256"),
    )

    expected_host_hash = _sha256_file(host_record_path)
    _require(
        attachment.get("host_record_sha256") == expected_host_hash,
        "ATTACHMENT_RESULT_HOST_RECORD_HASH",
        expected_host_hash,
        attachment.get("host_record_sha256"),
    )
    expected_selectors_hash = _sha256_file(selectors_path)
    _require(
        attachment.get("selectors_sha256") == expected_selectors_hash,
        "ATTACHMENT_RESULT_SELECTORS_HASH",
        expected_selectors_hash,
        attachment.get("selectors_sha256"),
    )

    expected_implementation = {
        relative_path: _sha256_file(repo / relative_path)
        for relative_path in PRODUCER_IMPLEMENTATION_PATHS
    }
    _require(
        attachment.get("implementation_sha256") == expected_implementation,
        "ATTACHMENT_RESULT_PRODUCER_IDENTITY",
        expected_implementation,
        attachment.get("implementation_sha256"),
    )
    return attachment


def _expected_provenance(
    *,
    repo: Path,
    output: Path,
    candidate: dict[str, str],
    attachment: dict[str, Any],
) -> dict[str, Any]:
    actual_host = output / "actual-host"
    attachment_path = actual_host / "attachment" / "attachment-result.json"
    event_log_path = actual_host / "attachment" / "win32-uia-events.jsonl"
    preflight_path = actual_host / "preflight-reset.json"
    host_record_path = repo / HOST_RECORD_REFERENCE
    selectors_path = repo / SELECTORS_REFERENCE
    producer_identity = {
        relative_path: _sha256_file(repo / relative_path)
        for relative_path in PRODUCER_IMPLEMENTATION_PATHS
    }
    return {
        "schema_version": PROVENANCE_SCHEMA,
        "gate": PROVENANCE_GATE,
        "candidate_head": candidate["head"],
        "candidate_tree": candidate["tree"],
        "attachment_result_path": _repo_relative(repo, attachment_path, dimension="ATTACHMENT_RESULT_PATH_SCOPE"),
        "attachment_result_sha256": _sha256_file(attachment_path),
        "event_log_path": _repo_relative(repo, event_log_path, dimension="EVENT_LOG_PATH_SCOPE"),
        "event_log_sha256": _sha256_file(event_log_path),
        "preflight_reset_path": _repo_relative(repo, preflight_path, dimension="PREFLIGHT_PATH_SCOPE"),
        "preflight_reset_sha256": _sha256_file(preflight_path),
        "preflight_status": "CODEX_TEST_SESSION_READY",
        "host_record_path": _repo_relative(repo, host_record_path, dimension="HOST_RECORD_PATH_SCOPE"),
        "host_record_sha256": _sha256_file(host_record_path),
        "selectors_path": _repo_relative(repo, selectors_path, dimension="SELECTORS_PATH_SCOPE"),
        "selectors_sha256": _sha256_file(selectors_path),
        "producer_implementation_sha256": producer_identity,
        "attachment_status": attachment["status"],
        "active_attachment": "PASS",
        "real_codex_host_tested": attachment["real_codex_host_tested"],
        "synthetic_owner_used": attachment["synthetic_owner_used"],
        "reset_to_attachment_contiguous_machine_flow": True,
        "historical_failures_preserved": True,
    }


def _write_provenance_and_link(
    *,
    repo: Path,
    output: Path,
    candidate: dict[str, str],
    attachment: dict[str, Any],
) -> dict[str, Any]:
    actual_host = output / "actual-host"
    provenance_path = output / PROVENANCE_REFERENCE
    aggregate_path = actual_host / "qualification.json"
    aggregate = _read_json(aggregate_path, dimension="AGGREGATE_QUALIFICATION")
    provenance = _expected_provenance(
        repo=repo,
        output=output,
        candidate=candidate,
        attachment=attachment,
    )

    # Provenance is committed before the aggregate link. Until the final atomic
    # aggregate write succeeds, no newly produced chain is advertised as active.
    _write_json_atomic(provenance_path, provenance)
    aggregate["attachment"] = {
        "status": "PASS",
        "path": ATTACHMENT_REFERENCE,
    }
    aggregate["attachment_status"] = ATTACHMENT_RESULT_PASS
    aggregate["f3_attachment_provenance"] = PROVENANCE_REFERENCE
    aggregate["f3_local_event_log"] = {
        "path": EVENT_LOG_REFERENCE,
        "sha256": provenance["event_log_sha256"],
    }
    _write_json_atomic(aggregate_path, aggregate)
    return provenance


def link_existing_provenance(
    *,
    repo: Path = ROOT,
    output: Path,
) -> dict[str, Any]:
    """Restore the canonical link after a semantic collector replaces its summary."""

    repo = repo.resolve()
    output = output.resolve()
    candidate = _candidate_identity(repo)
    actual_host = output / "actual-host"
    attachment_path = output / ATTACHMENT_REFERENCE
    event_log_path = output / EVENT_LOG_REFERENCE
    preflight_path = output / PREFLIGHT_REFERENCE
    host_record_path = repo / HOST_RECORD_REFERENCE
    selectors_path = repo / SELECTORS_REFERENCE
    provenance_path = output / PROVENANCE_REFERENCE
    provenance = _read_json(provenance_path, dimension="EXISTING_PROVENANCE")
    attachment = validate_attachment_result(
        repo=repo,
        attachment_path=attachment_path,
        event_log_path=event_log_path,
        host_record_path=host_record_path,
        selectors_path=selectors_path,
    )
    _validate_reset(reset_path=preflight_path, selectors_path=selectors_path)
    expected_provenance = _expected_provenance(
        repo=repo,
        output=output,
        candidate=candidate,
        attachment=attachment,
    )
    _require(
        provenance == expected_provenance,
        "EXISTING_PROVENANCE_COMPLETE_CHAIN",
        expected_provenance,
        provenance,
    )

    aggregate_path = actual_host / "qualification.json"
    aggregate = _read_json(aggregate_path, dimension="AGGREGATE_QUALIFICATION")
    aggregate["attachment"] = {"status": "PASS", "path": ATTACHMENT_REFERENCE}
    aggregate["attachment_status"] = attachment["status"]
    aggregate["f3_attachment_provenance"] = PROVENANCE_REFERENCE
    aggregate["f3_local_event_log"] = {
        "path": EVENT_LOG_REFERENCE,
        "sha256": expected_provenance["event_log_sha256"],
    }
    _write_json_atomic(aggregate_path, aggregate)
    return aggregate


def run_canonical_transaction(
    *,
    repo: Path = ROOT,
    output: Path,
    host_record_path: Path | None = None,
    selectors_path: Path | None = None,
) -> dict[str, Any]:
    """Own reset -> attachment -> validation -> provenance -> aggregate link."""

    repo = repo.resolve()
    output = output.resolve()
    host_record = (host_record_path or (repo / HOST_RECORD_REFERENCE)).resolve()
    selectors = (selectors_path or (repo / SELECTORS_REFERENCE)).resolve()
    _repo_relative(repo, output, dimension="OUTPUT_PATH_SCOPE")
    _repo_relative(repo, host_record, dimension="HOST_RECORD_PATH_SCOPE")
    _repo_relative(repo, selectors, dimension="SELECTORS_PATH_SCOPE")
    candidate = _candidate_identity(repo)

    actual_host = output / "actual-host"
    preflight_path = actual_host / "preflight-reset.json"
    attachment_dir = actual_host / "attachment"
    attachment_path = attachment_dir / "attachment-result.json"
    event_log_path = attachment_dir / "win32-uia-events.jsonl"
    environment = {
        "QT_QUICK_BACKEND": "software",
        "QT_SCALE_FACTOR": "1",
        "QT_FONT_DPI": "96",
    }

    reset_result = _run_command(
        [
            sys.executable,
            "scripts/h2/reset_codex_test_session.py",
            "--selectors",
            _repo_relative(repo, selectors, dimension="SELECTORS_PATH_SCOPE"),
            "--output",
            _repo_relative(repo, preflight_path, dimension="PREFLIGHT_PATH_SCOPE"),
        ],
        repo=repo,
        environment=environment,
    )
    _require(
        reset_result.returncode == 0,
        "RESET_EXECUTION",
        0,
        {"exit_code": reset_result.returncode, "stderr": reset_result.stderr},
    )
    _validate_reset(reset_path=preflight_path, selectors_path=selectors)

    attachment_result = _run_command(
        [
            sys.executable,
            "scripts/h2/verify_codex_attachment.py",
            "--host-record",
            _repo_relative(repo, host_record, dimension="HOST_RECORD_PATH_SCOPE"),
            "--selectors",
            _repo_relative(repo, selectors, dimension="SELECTORS_PATH_SCOPE"),
            "--evidence-dir",
            _repo_relative(repo, attachment_dir, dimension="ATTACHMENT_DIRECTORY_SCOPE"),
        ],
        repo=repo,
        environment=environment,
    )
    _require(
        attachment_result.returncode == 0,
        "ATTACHMENT_EXECUTION",
        0,
        {"exit_code": attachment_result.returncode, "stderr": attachment_result.stderr},
    )
    attachment = validate_attachment_result(
        repo=repo,
        attachment_path=attachment_path,
        event_log_path=event_log_path,
        host_record_path=host_record,
        selectors_path=selectors,
    )
    return _write_provenance_and_link(
        repo=repo,
        output=output,
        candidate=candidate,
        attachment=attachment,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--host-record", type=Path)
    parser.add_argument("--selectors", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        provenance = run_canonical_transaction(
            output=args.output_dir,
            host_record_path=args.host_record,
            selectors_path=args.selectors,
        )
    except F3AttachmentTransactionError as exc:
        print(f"H2 F3 CANONICAL ATTACHMENT FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(provenance, indent=2, ensure_ascii=False, sort_keys=True))
    print("H2_F3_CANONICAL_ATTACHMENT_PROVENANCE_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
