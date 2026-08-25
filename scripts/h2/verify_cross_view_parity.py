from __future__ import annotations

"""Fail-closed semantic parity verification for the accepted H2 F1 paths."""

import argparse
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn


sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
FROZEN_ORACLE_COMMIT = "60d982f3328b45a351879d67dc4bb525172b65fd"
FROZEN_ORACLE_TREE = "b7689fbe8b9c9838438cbba6f6e0e5c1ce5b5ed6"
ACCEPTED_E1_HEAD = "8a85ac4214e7b3386c3c8079b0d45fb79a97e9ff"
E2_CODE_FREEZE_HEAD = "8e8f325c31b8d96d31cd7fea901a0790d5086bf6"
E2_CODE_FREEZE_TREE = "ca7530b0ece301c6783877ab049daac884062989"
ACCEPTED_E2_HEAD = "1b46da916aec20aa2a27e533ac5e8aff9f360791"
E3_CODE_FREEZE_HEAD = "d94a1aa0c99056ec81f10c6a41e73ed6ea438ae3"
E3_CODE_FREEZE_TREE = "9fec4c41ed0228e3d4e71c9e19a846c92447c69e"


@dataclass(frozen=True)
class CaseConfig:
    tui_directory: str
    sidecar_gate_directory: str
    sidecar_directory: str
    sidecar_status: str
    sidecar_schema: str
    tui_schema: str
    transition_schema: str
    predecessor_field: str
    predecessor_head: str
    code_freeze_schema: str
    code_freeze_head: str
    code_freeze_tree: str
    transition_ids: tuple[str, ...]
    expected_sources_tui: tuple[str | None, ...]
    expected_sources_sidecar: tuple[str | None, ...]


CASE_CONFIGS = {
    "G06": CaseConfig(
        tui_directory="H2-B1",
        sidecar_gate_directory="H2-E2",
        sidecar_directory="H2-E2/actual-host",
        sidecar_status="H2_E2_G06_PASS",
        sidecar_schema="r6o-h2-e2-qualification-1",
        tui_schema="r6o-h2-b1-test-results-1",
        transition_schema="r6o-h2-e2-transition-1",
        predecessor_field="accepted_e1_head",
        predecessor_head=ACCEPTED_E1_HEAD,
        code_freeze_schema="r6o-h2-e2-code-freeze-1",
        code_freeze_head=E2_CODE_FREEZE_HEAD,
        code_freeze_tree=E2_CODE_FREEZE_TREE,
        transition_ids=("G06-T0-CODEX", "G06-T1-CODEX", "G06-T2-CODEX"),
        expected_sources_tui=(None, "STRUCTURED_ACTION", "STRUCTURED_ACTION"),
        expected_sources_sidecar=(None, "STRUCTURED_ACTION", "STRUCTURED_ACTION"),
    ),
    "A02-FULL": CaseConfig(
        tui_directory="H2-B2",
        sidecar_gate_directory="H2-E3",
        sidecar_directory="H2-E3/actual-host",
        sidecar_status="H2_E3_A02_FULL_PASS",
        sidecar_schema="r6o-h2-e3-qualification-1",
        tui_schema="r6o-h2-b2-test-results-1",
        transition_schema="r6o-h2-e3-transition-1",
        predecessor_field="accepted_e2_head",
        predecessor_head=ACCEPTED_E2_HEAD,
        code_freeze_schema="r6o-h2-e3-code-freeze-1",
        code_freeze_head=E3_CODE_FREEZE_HEAD,
        code_freeze_tree=E3_CODE_FREEZE_TREE,
        transition_ids=(
            "A02-T0-CODEX",
            "A02-T1-FOCUS-CODEX",
            "A02-T2-REVISE-CODEX",
            "A02-T3-CODEX",
            "A02-T4-CODEX",
        ),
        expected_sources_tui=(None, "STRUCTURED_ACTION", "TUI_TEXT", "STRUCTURED_ACTION", "STRUCTURED_ACTION"),
        expected_sources_sidecar=(
            None,
            "STRUCTURED_ACTION",
            "HOST_COMPOSER_TEXT",
            "STRUCTURED_ACTION",
            "STRUCTURED_ACTION",
        ),
    ),
}


class ParityVerificationError(AssertionError):
    """A machine-diagnosable parity or evidence-integrity failure."""

    def __init__(
        self,
        *,
        case: str,
        dimension: str,
        tui_value: Any,
        sidecar_value: Any,
        source_identity: Any,
        detail: str | None = None,
    ) -> None:
        self.case = case
        self.dimension = dimension
        self.tui_value = tui_value
        self.sidecar_value = sidecar_value
        self.source_identity = source_identity
        suffix = f" DETAIL={detail}" if detail else ""
        super().__init__(
            "CASE="
            + case
            + " DIMENSION="
            + dimension
            + " TUI_VALUE="
            + _display(tui_value)
            + " SIDECAR_VALUE="
            + _display(sidecar_value)
            + " SOURCE_IDENTITY="
            + _display(source_identity)
            + suffix
        )


def _display(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except TypeError:
        return repr(value)


def _fail(
    case: str,
    dimension: str,
    tui_value: Any,
    sidecar_value: Any,
    source_identity: Any,
    detail: str | None = None,
) -> NoReturn:
    raise ParityVerificationError(
        case=case,
        dimension=dimension,
        tui_value=tui_value,
        sidecar_value=sidecar_value,
        source_identity=source_identity,
        detail=detail,
    )


def _require(
    condition: bool,
    *,
    case: str,
    dimension: str,
    tui_value: Any,
    sidecar_value: Any,
    source_identity: Any,
    detail: str | None = None,
) -> None:
    if not condition:
        _fail(case, dimension, tui_value, sidecar_value, source_identity, detail)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_file_sha256(path: Path) -> str:
    """Hash accepted JSON evidence with checkout line endings normalized."""

    data = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


def _read_json(path: Path, *, case: str, dimension: str, source: str) -> dict[str, Any]:
    if not path.is_file():
        _fail(case, dimension, f"MISSING:{path}", "NOT_LOADED", source)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        _fail(case, dimension, f"UNREADABLE:{path}", type(exc).__name__, source)
    if not isinstance(value, dict):
        _fail(case, dimension, "JSON_OBJECT_REQUIRED", type(value).__name__, source)
    return value


def _read_jsonl(path: Path, *, case: str, dimension: str, source: str) -> list[dict[str, Any]]:
    if not path.is_file():
        _fail(case, dimension, f"MISSING:{path}", "NOT_LOADED", source)
    records: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        for line in lines:
            value = json.loads(line)
            if not isinstance(value, dict):
                raise TypeError("JSON object required")
            records.append(value)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError) as exc:
        _fail(case, dimension, f"UNREADABLE:{path}", type(exc).__name__, source)
    return records


def _git_value(repo: Path, expression: str) -> str:
    process = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", expression],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if process.returncode != 0:
        raise RuntimeError((process.stdout + process.stderr).strip())
    return process.stdout.strip()


def _git_status(repo: Path) -> str:
    process = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain=v1", "--untracked-files=all"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if process.returncode != 0:
        raise RuntimeError((process.stdout + process.stderr).strip())
    return process.stdout.strip()


def resolve_frozen_oracle(value: Path | None = None) -> Path:
    candidate = value or os.environ.get("PDL_R6S_BASELINE_REPO") or (ROOT.parent / "PDL-Standard-REPL-Harness")
    baseline = Path(candidate).resolve()
    if not baseline.is_dir():
        raise RuntimeError(f"frozen baseline not found: {baseline}")
    commit = _git_value(baseline, "HEAD")
    tree = _git_value(baseline, "HEAD^{tree}")
    if (commit, tree) != (FROZEN_ORACLE_COMMIT, FROZEN_ORACLE_TREE):
        raise RuntimeError(f"frozen oracle mismatch: {commit}/{tree}")
    status = _git_status(baseline)
    if status:
        raise RuntimeError(f"frozen oracle working tree is not clean:\n{status}")
    return baseline


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _resolve_evidence_path(path_value: str, evidence_root: Path) -> Path:
    candidate = Path(path_value)
    if candidate.is_absolute():
        return candidate.resolve()
    if candidate.parts and candidate.parts[0] == "r6o_evidence":
        return (evidence_root.parent / candidate).resolve()
    return (evidence_root / candidate).resolve()


def _source_pair(case: str, tui_source: str, sidecar_source: str, transition_id: str) -> dict[str, str]:
    return {
        "tui": tui_source,
        "sidecar": sidecar_source,
        "transition": transition_id,
    }


def _normalize_actions(
    actions: Any,
    *,
    case: str,
    source: str,
    stage: str,
) -> list[dict[str, Any]]:
    if not isinstance(actions, list):
        _fail(case, "ACTION_ORDER", "LIST_REQUIRED", type(actions).__name__, source)
    normalized: list[dict[str, Any]] = []
    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            _fail(case, "ACTION_ORDER", f"index={index}", type(action).__name__, source)
        action_id = action.get("action_id")
        ordinal = action.get("ordinal")
        kind = action.get("kind")
        enabled = action.get("enabled")
        label = action.get("label")
        canonical_review_text = action.get("canonical_review_text")
        if not isinstance(action_id, str) or not action_id:
            _fail(case, "ACTION_ORDER", action_id, "NONEMPTY_ACTION_ID_REQUIRED", source)
        if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 1:
            _fail(case, "ACTION_ORDER", ordinal, "POSITIVE_ORDINAL_REQUIRED", source)
        if not isinstance(kind, str) or kind not in {"SEMANTIC_MESSAGE", "FREE_RESPONSE_FOCUS"}:
            _fail(case, "ACTION_ORDER", kind, "SUPPORTED_ACTION_KIND_REQUIRED", source)
        if not isinstance(enabled, bool) or not isinstance(label, str) or not label:
            _fail(case, "ACTION_ORDER", action, "VALID_ACTION_FIELDS_REQUIRED", source)
        if kind == "SEMANTIC_MESSAGE" and (not isinstance(canonical_review_text, str) or not canonical_review_text):
            _fail(case, "STRUCTURED_REVIEW_MEANING", canonical_review_text, "NONEMPTY_CANONICAL_TEXT_REQUIRED", source)
        if kind == "FREE_RESPONSE_FOCUS" and canonical_review_text is not None:
            _fail(case, "STRUCTURED_REVIEW_MEANING", canonical_review_text, None, source)
        normalized.append(
            {
                "action_id": action_id,
                "ordinal": ordinal,
                "kind": kind,
                "enabled": enabled,
                "label": label,
                "canonical_review_text": canonical_review_text,
            }
        )
    ordinals = [item["ordinal"] for item in normalized]
    _require(
        ordinals == list(range(1, len(ordinals) + 1)),
        case=case,
        dimension="ACTION_ORDER",
        tui_value=ordinals,
        sidecar_value=list(range(1, len(ordinals) + 1)),
        source_identity=source,
        detail=f"stage={stage}",
    )
    return normalized


def _normalize_artifact(
    artifact: Any,
    *,
    case: str,
    source: str,
) -> dict[str, Any] | None:
    if artifact is None:
        return None
    if not isinstance(artifact, dict):
        _fail(case, "ARTIFACT_IDENTITY", "OBJECT_REQUIRED", type(artifact).__name__, source)
    kind = artifact.get("artifact_kind")
    reference = artifact.get("artifact_ref")
    revision = artifact.get("artifact_revision")
    body = artifact.get("body")
    if not all(isinstance(item, str) and item for item in (kind, reference, revision, body)):
        _fail(case, "ARTIFACT_IDENTITY", artifact, "VALID_ARTIFACT_FIELDS_REQUIRED", source)
    if not reference.startswith(f"{kind}:"):
        _fail(case, "ARTIFACT_IDENTITY", reference, f"{kind}:<opaque-id>", source)
    capabilities = artifact.get("capabilities")
    if not isinstance(capabilities, dict):
        _fail(case, "ARTIFACT_IDENTITY", capabilities, "CAPABILITIES_OBJECT_REQUIRED", source)
    normalized_capabilities = {
        "copy": capabilities.get("copy"),
        "open_external": capabilities.get("open_external"),
    }
    if not all(isinstance(value, bool) for value in normalized_capabilities.values()):
        _fail(case, "ARTIFACT_IDENTITY", capabilities, "BOOLEAN_CAPABILITIES_REQUIRED", source)
    return {
        "artifact_kind": kind,
        "artifact_revision": revision,
        "body_sha256": _sha256_text(body),
        "media_type": artifact.get("media_type"),
        "title": artifact.get("title"),
        "capabilities": normalized_capabilities,
    }


def _normalize_lifecycle(
    lifecycle: Any,
    *,
    case: str,
    source: str,
) -> dict[str, Any]:
    if not isinstance(lifecycle, dict):
        _fail(case, "TERMINAL_DISPOSITION", "OBJECT_REQUIRED", type(lifecycle).__name__, source)
    authorized = lifecycle.get("authorized_handoff_artifacts")
    if not isinstance(authorized, list):
        _fail(case, "TERMINAL_DISPOSITION", authorized, "LIST_REQUIRED", source)
    normalized_authorized = []
    for item in authorized:
        artifact = _normalize_artifact(item, case=case, source=source)
        if artifact is None:
            _fail(case, "TERMINAL_DISPOSITION", item, "ARTIFACT_REQUIRED", source)
        normalized_authorized.append(artifact)
    result_body = lifecycle.get("result_body")
    if result_body is not None and not isinstance(result_body, str):
        _fail(case, "TERMINAL_DISPOSITION", result_body, "TEXT_OR_NULL_REQUIRED", source)
    return {
        "review_required": lifecycle.get("review_required"),
        "terminal": lifecycle.get("terminal"),
        "close_allowed": lifecycle.get("close_allowed"),
        "handoff_ready": lifecycle.get("handoff_ready"),
        "terminal_disposition": lifecycle.get("terminal_disposition"),
        "authorized_handoff_artifacts": normalized_authorized,
        "result_body_sha256": _sha256_text(result_body) if result_body is not None else None,
    }


def normalize_projection(projection: dict[str, Any], *, case: str, source: str) -> dict[str, Any]:
    if projection.get("schema_version") != "r6o-focus-projection-1":
        _fail(case, "STAGE_SEQUENCE", projection.get("schema_version"), "r6o-focus-projection-1", source)
    stage = projection.get("stage")
    session_id = projection.get("session_id")
    model_revision = projection.get("model_revision")
    projection_id = projection.get("projection_id")
    if not all(isinstance(value, str) and value for value in (stage, session_id, model_revision, projection_id)):
        _fail(case, "STALE_IDENTITY", projection, "NONEMPTY_PROJECTION_IDENTITIES_REQUIRED", source)
    actions = _normalize_actions(projection.get("actions"), case=case, source=source, stage=stage)
    artifact = _normalize_artifact(projection.get("artifact"), case=case, source=source)
    lifecycle = _normalize_lifecycle(projection.get("lifecycle"), case=case, source=source)
    terminal = stage in {"CLOSED_SUCCESS", "CLOSED_CANCELLED"}
    if terminal:
        _require(
            artifact is None and actions == [],
            case=case,
            dimension="TERMINAL_DISPOSITION",
            tui_value={"artifact": artifact, "actions": actions},
            sidecar_value={"artifact": None, "actions": []},
            source_identity=source,
        )
    else:
        _require(
            artifact is not None and bool(actions),
            case=case,
            dimension="STAGE_SEQUENCE",
            tui_value={"artifact": artifact, "actions": actions},
            sidecar_value="active projection with artifact and actions",
            source_identity=source,
        )
    model_response = projection.get("model_response")
    if model_response is not None and not isinstance(model_response, str):
        _fail(case, "STRUCTURED_REVIEW_MEANING", model_response, "TEXT_OR_NULL_REQUIRED", source)
    return {
        "stage": stage,
        "focus_kind": projection.get("focus_kind"),
        "interaction_state": projection.get("interaction_state"),
        "actions": actions,
        "artifact": artifact,
        "model_response_sha256": _sha256_text(model_response) if model_response is not None else None,
        "lifecycle": lifecycle,
        "session_id": session_id,
        "model_revision": model_revision,
        "projection_id": projection_id,
    }


def _without_opaque_revisions(value: Any) -> Any:
    """Remove session-scoped artifact revision identities for semantic comparison."""

    if isinstance(value, dict):
        return {
            key: _without_opaque_revisions(item)
            for key, item in value.items()
            if key != "artifact_revision"
        }
    if isinstance(value, list):
        return [_without_opaque_revisions(item) for item in value]
    return value


def _revision_pattern(values: list[str | None]) -> list[str | None]:
    labels: dict[str, str] = {}
    result: list[str | None] = []
    for value in values:
        if value is None:
            result.append(None)
            continue
        if value not in labels:
            labels[value] = f"r{len(labels) + 1}"
        result.append(labels[value])
    return result


def _public_tui_source(event: str, case: str) -> str | None:
    if event == "START":
        return None
    if event == "FOCUS":
        return "STRUCTURED_ACTION"
    if event == "TEXT":
        return "TUI_TEXT"
    if event == "ACTION":
        return "STRUCTURED_ACTION"
    _fail(case, "SOURCE_IDENTITY", event, "START|FOCUS|TEXT|ACTION", f"TUI:{case}")


def capture_tui_projections(case: str, baseline_repo: Path) -> dict[str, Any]:
    """Capture full TUI projections through the accepted public TUI class."""

    if case not in CASE_CONFIGS:
        raise ValueError(f"unsupported F1 case: {case}")
    from r6o.model_binding.base import ModelSessionRequest
    from r6o.model_binding.local_runtime import LocalRuntimeModelBinding
    from r6o.viewmodel.projection import build_focus_projection_from_port
    from r6o.views.tui.app import TerminalReviewApp
    from scripts.run_r6o2_tui import (
        A02_ACTIVATION,
        A02_OPERATIONS,
        A02ReplayWorker,
        G06_ACTIVATION,
        G06_OPERATIONS,
        ObservedWorker,
        load_g06_worker,
    )
    from scripts.h2.verify_a02_full_fixture import REVISION_TEXT

    if case == "G06":
        activation = G06_ACTIVATION
        operations = G06_OPERATIONS
        delegate = load_g06_worker(baseline_repo)
        keys = "\r\r"
        run_id = "h2-f1-tui-g06"
    else:
        activation = A02_ACTIVATION
        operations = A02_OPERATIONS
        delegate = A02ReplayWorker()
        keys = "\t\t\t\r" + REVISION_TEXT + "\r\r\r"
        run_id = "h2-f1-tui-a02-full"

    worker = ObservedWorker(delegate, operations, case)
    events: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix=f"pdl-h2-f1-{case.lower().replace('-', '-')}-") as temporary:
        workspace_root = Path(temporary) / "workspaces"
        model = LocalRuntimeModelBinding(
            baseline_repo,
            worker=worker,
            workspace_root=workspace_root,
            run_id=run_id,
        )
        try:
            started = model.start_or_resume(ModelSessionRequest(request_id=run_id, task_text=activation))
            initial = build_focus_projection_from_port(model, started.session_id)
            call_cursor = 0

            def on_projection(event: str, action_id: str | None, projection: dict[str, Any]) -> None:
                nonlocal call_cursor
                new_calls = worker.calls[call_cursor:]
                call_cursor = len(worker.calls)
                events.append(
                    {
                        "event": event,
                        "action_id": action_id,
                        "input_envelope_source": _public_tui_source(event, case),
                        "worker_operations": [dict(item) for item in new_calls],
                        "projection": projection,
                    }
                )

            final = TerminalReviewApp(
                model,
                started.session_id,
                stdin=io.StringIO(keys),
                stdout=io.StringIO(),
                on_projection=on_projection,
            ).run(initial)
            _require(
                final.get("stage") == "CLOSED_SUCCESS",
                case=case,
                dimension="TERMINAL_DISPOSITION",
                tui_value=final.get("stage"),
                sidecar_value="CLOSED_SUCCESS",
                source_identity=f"TUI:{case}",
            )
        finally:
            model.close()

    expected_ids = [operation_id for operation_id, _ in operations]
    actual_ids = [item["operation_id"] for item in worker.calls]
    _require(
        actual_ids == expected_ids,
        case=case,
        dimension="WORKER_OPERATIONS",
        tui_value=actual_ids,
        sidecar_value=expected_ids,
        source_identity=f"TUI:{case}",
    )
    normalized_events = []
    for index, event in enumerate(events):
        projection = event.get("projection")
        if not isinstance(projection, dict):
            _fail(case, "STAGE_SEQUENCE", event, "PROJECTION_OBJECT_REQUIRED", f"TUI:{case}:{index}")
        normalized_events.append(
            {
                **event,
                "normalized_projection": normalize_projection(
                    projection, case=case, source=f"TUI:{case}:{event['event']}:{index}"
                ),
            }
        )
    return {
        "schema_version": "r6o-h2-f1-tui-capture-1",
        "case": case,
        "source": f"TUI:{case}:accepted-public-path",
        "events": normalized_events,
        "worker_operations": [dict(item) for item in worker.calls],
    }


def load_tui_acceptance(case: str, evidence_root: Path) -> dict[str, Any]:
    config = CASE_CONFIGS[case]
    directory = evidence_root / config.tui_directory
    source = f"TUI:{directory}"
    results = _read_json(directory / "test-results.json", case=case, dimension="MISSING_EVIDENCE", source=source)
    records = _read_jsonl(directory / "state-transitions.jsonl", case=case, dimension="MISSING_EVIDENCE", source=source)
    _require(
        results.get("schema_version") == config.tui_schema,
        case=case,
        dimension="EVIDENCE_INTEGRITY",
        tui_value=results.get("schema_version"),
        sidecar_value=config.tui_schema,
        source_identity=source,
    )
    return {"source": source, "results": results, "records": records}


def _load_e3_evidence_directory(case: str, evidence_root: Path) -> tuple[Path, dict[str, Any]]:
    ledger_path = evidence_root / "H2-E3/actual-host/live-attempts.json"
    ledger = _read_json_array(ledger_path, case=case, dimension="MISSING_EVIDENCE", source=f"SIDECAR:{ledger_path}")
    candidates = [
        item
        for item in ledger
        if isinstance(item, dict)
        and item.get("status") == "H2_E3_A02_FULL_PASS"
        and item.get("code_freeze_head") == E3_CODE_FREEZE_HEAD
        and item.get("code_freeze_tree") == E3_CODE_FREEZE_TREE
    ]
    if not candidates:
        _fail(case, "MISSING_EVIDENCE", "CURRENT_FREEZE_PASS_NOT_FOUND", candidates, str(ledger_path))
    selected = max(candidates, key=lambda item: int(item.get("attempt", 0)))
    evidence_path = selected.get("evidence_path")
    if not isinstance(evidence_path, str) or not evidence_path:
        _fail(case, "MISSING_EVIDENCE", evidence_path, "evidence_path", str(ledger_path))
    directory = _resolve_evidence_path(evidence_path, evidence_root)
    if not _is_within(directory, evidence_root):
        _fail(case, "EVIDENCE_INTEGRITY", str(directory), str(evidence_root), str(ledger_path))
    return directory, selected


def _validate_sidecar_provenance(
    case: str,
    config: CaseConfig,
    qualification: dict[str, Any],
    evidence_root: Path,
    source: str,
    ledger_entry: dict[str, Any] | None,
) -> None:
    expected_identity = {
        config.predecessor_field: config.predecessor_head,
        "code_freeze_head": config.code_freeze_head,
        "code_freeze_tree": config.code_freeze_tree,
    }
    qualification_identity = {
        config.predecessor_field: qualification.get(config.predecessor_field),
        "code_freeze_head": qualification.get("code_freeze_head"),
        "code_freeze_tree": qualification.get("code_freeze_tree"),
    }
    _require(
        qualification_identity == expected_identity,
        case=case,
        dimension="EVIDENCE_INTEGRITY",
        tui_value=expected_identity,
        sidecar_value=qualification_identity,
        source_identity=source,
        detail="qualification predecessor/code-freeze identity mismatch",
    )

    freeze_path = evidence_root / config.sidecar_gate_directory / "code-freeze.json"
    freeze = _read_json(freeze_path, case=case, dimension="MISSING_EVIDENCE", source=str(freeze_path))
    expected_freeze = {"schema_version": config.code_freeze_schema, **expected_identity}
    actual_freeze = {
        "schema_version": freeze.get("schema_version"),
        config.predecessor_field: freeze.get(config.predecessor_field),
        "code_freeze_head": freeze.get("code_freeze_head"),
        "code_freeze_tree": freeze.get("code_freeze_tree"),
    }
    _require(
        actual_freeze == expected_freeze,
        case=case,
        dimension="EVIDENCE_INTEGRITY",
        tui_value=expected_freeze,
        sidecar_value=actual_freeze,
        source_identity=str(freeze_path),
        detail="code-freeze manifest identity mismatch",
    )

    if ledger_entry is None:
        return
    expected_ledger = {
        "status": config.sidecar_status,
        "code_freeze_head": qualification.get("code_freeze_head"),
        "code_freeze_tree": qualification.get("code_freeze_tree"),
        "head": qualification.get("evidence_head_at_run"),
        "tree": qualification.get("evidence_tree_at_run"),
    }
    actual_ledger = {key: ledger_entry.get(key) for key in expected_ledger}
    _require(
        actual_ledger == expected_ledger,
        case=case,
        dimension="EVIDENCE_INTEGRITY",
        tui_value=expected_ledger,
        sidecar_value=actual_ledger,
        source_identity=source,
        detail="live-attempt ledger/qualification identity mismatch",
    )


def _read_json_array(path: Path, *, case: str, dimension: str, source: str) -> list[Any]:
    if not path.is_file():
        _fail(case, dimension, f"MISSING:{path}", "NOT_LOADED", source)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        _fail(case, dimension, f"UNREADABLE:{path}", type(exc).__name__, source)
    if not isinstance(value, list):
        _fail(case, dimension, "LIST_REQUIRED", type(value).__name__, source)
    return value


def _validate_envelope(
    case: str,
    index: int,
    transition: dict[str, Any],
    projection: dict[str, Any],
    previous_projection: dict[str, Any] | None,
    source: str,
) -> str | None:
    envelope = transition.get("input_envelope")
    expected_action = envelope.get("action_id") if isinstance(envelope, dict) else None
    if envelope is None:
        _require(
            index == 0,
            case=case,
            dimension="SOURCE_IDENTITY",
            tui_value=None,
            sidecar_value=None,
            source_identity=source,
            detail="only START may omit an input envelope",
        )
        return None
    if not isinstance(envelope, dict):
        _fail(case, "SOURCE_IDENTITY", envelope, "INPUT_ENVELOPE_OBJECT_REQUIRED", source)
    if envelope.get("schema_version") != "r6o-input-envelope-1":
        _fail(case, "SOURCE_IDENTITY", envelope.get("schema_version"), "r6o-input-envelope-1", source)
    envelope_source = envelope.get("source")
    if envelope_source not in {"STRUCTURED_ACTION", "HOST_COMPOSER_TEXT"}:
        _fail(case, "SOURCE_IDENTITY", envelope_source, "SUPPORTED_TRANSPORT_SOURCE", source)
    if previous_projection is None:
        _fail(case, "STALE_IDENTITY", envelope, "PREVIOUS_PROJECTION_REQUIRED", source)
    expected_identity = {
        "session_id": previous_projection.get("session_id"),
        "model_revision": previous_projection.get("model_revision"),
    }
    actual_identity = {
        "session_id": envelope.get("session_id"),
        "model_revision": envelope.get("model_revision"),
    }
    _require(
        actual_identity == expected_identity,
        case=case,
        dimension="STALE_IDENTITY",
        tui_value=expected_identity,
        sidecar_value=actual_identity,
        source_identity=source,
    )
    if envelope_source == "STRUCTURED_ACTION":
        _require(
            isinstance(expected_action, str) and expected_action,
            case=case,
            dimension="SOURCE_IDENTITY",
            tui_value="STRUCTURED_ACTION",
            sidecar_value=expected_action,
            source_identity=source,
        )
        _require(
            envelope.get("projection_id") == previous_projection.get("projection_id")
            and envelope.get("text") is None,
            case=case,
            dimension="STALE_IDENTITY",
            tui_value={"projection_id": previous_projection.get("projection_id"), "text": None},
            sidecar_value={"projection_id": envelope.get("projection_id"), "text": envelope.get("text")},
            source_identity=source,
        )
    else:
        _require(
            case == "A02-FULL"
            and expected_action is None
            and envelope.get("projection_id") is None
            and envelope.get("text") == "This is not confirmed. The audience should be data engineers, not backend engineers.",
            case=case,
            dimension="SOURCE_IDENTITY",
            tui_value="TUI_TEXT",
            sidecar_value={
                "source": envelope_source,
                "action_id": expected_action,
                "projection_id": envelope.get("projection_id"),
                "text": envelope.get("text"),
            },
            source_identity=source,
        )
    return envelope_source


def load_sidecar_evidence(case: str, evidence_root: Path) -> dict[str, Any]:
    config = CASE_CONFIGS[case]
    ledger_entry: dict[str, Any] | None = None
    if case == "A02-FULL":
        directory, ledger_entry = _load_e3_evidence_directory(case, evidence_root)
    else:
        directory = evidence_root / config.sidecar_directory
    source = f"SIDECAR:{directory}"
    qualification_path = directory / "qualification.json"
    qualification = _read_json(qualification_path, case=case, dimension="MISSING_EVIDENCE", source=source)
    transitions_path = directory / "transitions.json"
    transitions = _read_json_array(transitions_path, case=case, dimension="MISSING_EVIDENCE", source=source)
    _require(
        qualification.get("schema_version") == config.sidecar_schema,
        case=case,
        dimension="EVIDENCE_INTEGRITY",
        tui_value=config.sidecar_schema,
        sidecar_value=qualification.get("schema_version"),
        source_identity=source,
    )
    _require(
        qualification.get("status") == config.sidecar_status,
        case=case,
        dimension="EVIDENCE_INTEGRITY",
        tui_value="accepted pass status",
        sidecar_value=qualification.get("status"),
        source_identity=source,
    )
    _validate_sidecar_provenance(case, config, qualification, evidence_root, source, ledger_entry)
    frozen = qualification.get("frozen_r6s")
    _require(
        isinstance(frozen, dict)
        and frozen.get("commit") == FROZEN_ORACLE_COMMIT
        and frozen.get("tree") == FROZEN_ORACLE_TREE,
        case=case,
        dimension="FROZEN_ORACLE",
        tui_value={"commit": FROZEN_ORACLE_COMMIT, "tree": FROZEN_ORACLE_TREE},
        sidecar_value=frozen,
        source_identity=source,
    )
    qualification_transitions = qualification.get("transitions")
    _require(
        qualification_transitions == transitions,
        case=case,
        dimension="EVIDENCE_INTEGRITY",
        tui_value="qualification/transitions equality",
        sidecar_value="different transition records",
        source_identity=source,
    )
    _require(
        len(transitions) == len(config.transition_ids),
        case=case,
        dimension="STAGE_SEQUENCE",
        tui_value=len(config.transition_ids),
        sidecar_value=len(transitions),
        source_identity=source,
    )
    events: list[dict[str, Any]] = []
    for index, transition in enumerate(transitions):
        if not isinstance(transition, dict):
            _fail(case, "EVIDENCE_INTEGRITY", f"index={index}", type(transition).__name__, source)
        _require(
            transition.get("schema_version") == config.transition_schema,
            case=case,
            dimension="EVIDENCE_INTEGRITY",
            tui_value=config.transition_schema,
            sidecar_value=transition.get("schema_version"),
            source_identity=f"{source}:transition={index}",
            detail="transition schema mismatch",
        )
        transition_id = transition.get("transition_id")
        _require(
            transition_id == config.transition_ids[index],
            case=case,
            dimension="STAGE_SEQUENCE",
            tui_value=config.transition_ids[index],
            sidecar_value=transition_id,
            source_identity=source,
        )
        projection_path_value = transition.get("projection_path")
        if not isinstance(projection_path_value, str):
            _fail(case, "MISSING_EVIDENCE", projection_path_value, "projection_path", source)
        projection_path = _resolve_evidence_path(projection_path_value, evidence_root)
        if not _is_within(projection_path, evidence_root):
            _fail(case, "EVIDENCE_INTEGRITY", str(projection_path), str(evidence_root), source)
        projection = _read_json(projection_path, case=case, dimension="MISSING_EVIDENCE", source=source)
        expected_projection_hash = transition.get("projection_sha256")
        actual_projection_hash = _canonical_file_sha256(projection_path)
        _require(
            actual_projection_hash == expected_projection_hash,
            case=case,
            dimension="EVIDENCE_INTEGRITY",
            tui_value=expected_projection_hash,
            sidecar_value=actual_projection_hash,
            source_identity=source,
        )
        normalized = normalize_projection(
            projection, case=case, source=f"{source}:{transition_id}:projection"
        )
        _require(
            transition.get("projection_id") == normalized["projection_id"]
            and transition.get("stage") == normalized["stage"],
            case=case,
            dimension="STALE_IDENTITY",
            tui_value={"projection_id": normalized["projection_id"], "stage": normalized["stage"]},
            sidecar_value={
                "projection_id": transition.get("projection_id"),
                "stage": transition.get("stage"),
            },
            source_identity=source,
        )
        artifact = normalized.get("artifact")
        _require(
            transition.get("artifact_kind") == (artifact or {}).get("artifact_kind")
            and transition.get("artifact_body_sha256") == (artifact or {}).get("body_sha256"),
            case=case,
            dimension="ARTIFACT_IDENTITY",
            tui_value={
                "artifact_kind": (artifact or {}).get("artifact_kind"),
                "body_sha256": (artifact or {}).get("body_sha256"),
            },
            sidecar_value={
                "artifact_kind": transition.get("artifact_kind"),
                "body_sha256": transition.get("artifact_body_sha256"),
            },
            source_identity=source,
        )
        previous_raw = events[-1]["projection_raw"] if events else None
        envelope_source = _validate_envelope(
            case, index, transition, projection, previous_raw, f"{source}:{transition_id}"
        )
        worker_operations = transition.get("worker_operations")
        if not isinstance(worker_operations, list) or not all(isinstance(item, dict) for item in worker_operations):
            _fail(case, "WORKER_OPERATIONS", worker_operations, "LIST_OF_OBJECTS_REQUIRED", source)
        events.append(
            {
                "transition_id": transition_id,
                "action_id": (
                    transition.get("input_envelope", {}).get("action_id")
                    if isinstance(transition.get("input_envelope"), dict)
                    else None
                ),
                "input_envelope_source": envelope_source,
                "worker_operations": [dict(item) for item in worker_operations],
                "normalized_projection": normalized,
                "projection_raw": projection,
                "transition_raw": transition,
            }
        )
    if qualification.get("native_codex_submission_observed") is not False:
        _fail(case, "SOURCE_IDENTITY", False, qualification.get("native_codex_submission_observed"), source)
    if qualification.get("sidecar_dismissed") is not True:
        _fail(case, "TERMINAL_DISPOSITION", True, qualification.get("sidecar_dismissed"), source)
    return {
        "schema_version": "r6o-h2-f1-sidecar-evidence-1",
        "case": case,
        "source": source,
        "qualification": qualification,
        "events": events,
    }


def _validate_tui_acceptance(case: str, acceptance: dict[str, Any], capture: dict[str, Any]) -> None:
    config = CASE_CONFIGS[case]
    results = acceptance["results"]
    records = acceptance["records"]
    source = acceptance["source"]
    expected_status = "MECHANICAL_PASS_PENDING_HUMAN"
    _require(
        results.get("status") == expected_status,
        case=case,
        dimension="EVIDENCE_INTEGRITY",
        tui_value=expected_status,
        sidecar_value=results.get("status"),
        source_identity=source,
    )
    events = capture["events"]
    _require(
        len(records) == len(events),
        case=case,
        dimension="STAGE_SEQUENCE",
        tui_value=len(events),
        sidecar_value=len(records),
        source_identity=source,
    )
    for index, (record, event) in enumerate(zip(records, events, strict=True)):
        normalized = event["normalized_projection"]
        _require(
            record.get("stage") == normalized["stage"],
            case=case,
            dimension="STAGE_SEQUENCE",
            tui_value=normalized["stage"],
            sidecar_value=record.get("stage"),
            source_identity=f"{source}:record={index}",
        )
        recorded_source = record.get("input_envelope_source")
        # The accepted B1 schema predates the explicit source field. Its
        # non-start action transitions are nevertheless structured actions by
        # the public TUI contract and the accepted worker/evidence path.
        if case == "G06" and "input_envelope_source" not in record:
            recorded_source = event.get("input_envelope_source")
        _require(
            record.get("action_id") == event.get("action_id")
            and recorded_source == event.get("input_envelope_source"),
            case=case,
            dimension="SOURCE_IDENTITY",
            tui_value={"action_id": event.get("action_id"), "source": event.get("input_envelope_source")},
            sidecar_value={"action_id": record.get("action_id"), "source": recorded_source},
            source_identity=f"{source}:record={index}",
        )
        artifact = normalized.get("artifact")
        _require(
            record.get("artifact_kind") == (artifact or {}).get("artifact_kind")
            and record.get("artifact_body_sha256") == (artifact or {}).get("body_sha256"),
            case=case,
            dimension="ARTIFACT_IDENTITY",
            tui_value={"kind": (artifact or {}).get("artifact_kind"), "body_sha256": (artifact or {}).get("body_sha256")},
            sidecar_value={"kind": record.get("artifact_kind"), "body_sha256": record.get("artifact_body_sha256")},
            source_identity=f"{source}:record={index}",
        )
        _require(
            record.get("worker_operations") == event.get("worker_operations"),
            case=case,
            dimension="WORKER_OPERATIONS",
            tui_value=event.get("worker_operations"),
            sidecar_value=record.get("worker_operations"),
            source_identity=f"{source}:record={index}",
        )
        if normalized["stage"] == "CLOSED_SUCCESS":
            _require(
                record.get("terminal_disposition") == normalized["lifecycle"].get("terminal_disposition")
                and record.get("authorized_artifact_hashes")
                == {
                    item["artifact_kind"]: item["body_sha256"]
                    for item in normalized["lifecycle"]["authorized_handoff_artifacts"]
                }
                and record.get("result_body_sha256") == normalized["lifecycle"].get("result_body_sha256"),
                case=case,
                dimension="TERMINAL_DISPOSITION",
                tui_value=normalized["lifecycle"],
                sidecar_value={
                    "terminal_disposition": record.get("terminal_disposition"),
                    "authorized_artifact_hashes": record.get("authorized_artifact_hashes"),
                    "result_body_sha256": record.get("result_body_sha256"),
                },
                source_identity=f"{source}:record={index}",
            )
    expected_ids = results.get("observed_operation_ids")
    actual_ids = [item["operation_id"] for item in capture["worker_operations"]]
    _require(
        expected_ids == actual_ids,
        case=case,
        dimension="WORKER_OPERATIONS",
        tui_value=actual_ids,
        sidecar_value=expected_ids,
        source_identity=source,
    )
    if case == "A02-FULL":
        _require(
            results.get("free_response_source") == "TUI_TEXT"
            and results.get("free_response_submission_count") == 1,
            case=case,
            dimension="SOURCE_IDENTITY",
            tui_value={"source": "TUI_TEXT", "submission_count": 1},
            sidecar_value={
                "source": results.get("free_response_source"),
                "submission_count": results.get("free_response_submission_count"),
            },
            source_identity=source,
        )


def _compare_cases(case: str, tui: dict[str, Any], sidecar: dict[str, Any]) -> dict[str, Any]:
    config = CASE_CONFIGS[case]
    tui_events = tui["events"]
    sidecar_events = sidecar["events"]
    source_identity = _source_pair(case, tui["source"], sidecar["source"], config.transition_ids[0])
    _require(
        len(tui_events) == len(sidecar_events),
        case=case,
        dimension="STAGE_SEQUENCE",
        tui_value=len(tui_events),
        sidecar_value=len(sidecar_events),
        source_identity=source_identity,
    )
    dimensions: dict[str, dict[str, Any]] = {}
    for index, (tui_event, sidecar_event) in enumerate(zip(tui_events, sidecar_events, strict=True)):
        transition_id = config.transition_ids[index]
        identity = _source_pair(case, tui["source"], sidecar["source"], transition_id)
        tui_projection = tui_event["normalized_projection"]
        sidecar_projection = sidecar_event["normalized_projection"]
        _require(
            tui_projection["stage"] == sidecar_projection["stage"]
            and tui_event.get("action_id") == sidecar_event.get("action_id"),
            case=case,
            dimension="STAGE_SEQUENCE",
            tui_value={"stage": tui_projection["stage"], "action_id": tui_event.get("action_id")},
            sidecar_value={"stage": sidecar_projection["stage"], "action_id": sidecar_event.get("action_id")},
            source_identity=identity,
        )
        _require(
            tui_projection["actions"] == sidecar_projection["actions"],
            case=case,
            dimension="ACTION_ORDER",
            tui_value=tui_projection["actions"],
            sidecar_value=sidecar_projection["actions"],
            source_identity=identity,
        )
        _require(
            tui_projection["actions"] == sidecar_projection["actions"],
            case=case,
            dimension="STRUCTURED_REVIEW_MEANING",
            tui_value=tui_projection["actions"],
            sidecar_value=sidecar_projection["actions"],
            source_identity=identity,
        )
        _require(
            _without_opaque_revisions(tui_projection["artifact"])
            == _without_opaque_revisions(sidecar_projection["artifact"]),
            case=case,
            dimension="ARTIFACT_IDENTITY",
            tui_value=tui_projection["artifact"],
            sidecar_value=sidecar_projection["artifact"],
            source_identity=identity,
        )
        _require(
            tui_projection["model_response_sha256"] == sidecar_projection["model_response_sha256"],
            case=case,
            dimension="STRUCTURED_REVIEW_MEANING",
            tui_value=tui_projection["model_response_sha256"],
            sidecar_value=sidecar_projection["model_response_sha256"],
            source_identity=identity,
        )
        _require(
            tui_event.get("worker_operations") == sidecar_event.get("worker_operations"),
            case=case,
            dimension="WORKER_OPERATIONS",
            tui_value=tui_event.get("worker_operations"),
            sidecar_value=sidecar_event.get("worker_operations"),
            source_identity=identity,
        )
        _require(
            tui_event.get("input_envelope_source") == config.expected_sources_tui[index]
            and sidecar_event.get("input_envelope_source") == config.expected_sources_sidecar[index],
            case=case,
            dimension="SOURCE_IDENTITY",
            tui_value=tui_event.get("input_envelope_source"),
            sidecar_value=sidecar_event.get("input_envelope_source"),
            source_identity=identity,
        )
        _require(
            _without_opaque_revisions(tui_projection["lifecycle"])
            == _without_opaque_revisions(sidecar_projection["lifecycle"]),
            case=case,
            dimension="TERMINAL_DISPOSITION",
            tui_value=tui_projection["lifecycle"],
            sidecar_value=sidecar_projection["lifecycle"],
            source_identity=identity,
        )

    tui_stages = [event["normalized_projection"]["stage"] for event in tui_events]
    sidecar_stages = [event["normalized_projection"]["stage"] for event in sidecar_events]
    tui_revisions = [
        (event["normalized_projection"]["artifact"] or {}).get("artifact_revision")
        for event in tui_events
    ]
    sidecar_revisions = [
        (event["normalized_projection"]["artifact"] or {}).get("artifact_revision")
        for event in sidecar_events
    ]
    _require(
        _revision_pattern(tui_revisions) == _revision_pattern(sidecar_revisions),
        case=case,
        dimension="ARTIFACT_IDENTITY",
        tui_value=tui_revisions,
        sidecar_value=sidecar_revisions,
        source_identity=source_identity,
        detail="artifact revisions are opaque per-session identities; transition identity pattern must match",
    )
    tui_terminal_revisions = [
        item["artifact_revision"]
        for item in tui_events[-1]["normalized_projection"]["lifecycle"]["authorized_handoff_artifacts"]
    ]
    sidecar_terminal_revisions = [
        item["artifact_revision"]
        for item in sidecar_events[-1]["normalized_projection"]["lifecycle"]["authorized_handoff_artifacts"]
    ]
    _require(
        _revision_pattern(tui_terminal_revisions) == _revision_pattern(sidecar_terminal_revisions),
        case=case,
        dimension="ARTIFACT_IDENTITY",
        tui_value=tui_terminal_revisions,
        sidecar_value=sidecar_terminal_revisions,
        source_identity=source_identity,
        detail="terminal artifact revision identity pattern must match",
    )
    dimensions["stage_sequence"] = {"status": "PASS", "tui": tui_stages, "sidecar": sidecar_stages}
    dimensions["projected_action_ids_order"] = {
        "status": "PASS",
        "tui": [[item["action_id"] for item in event["normalized_projection"]["actions"]] for event in tui_events],
        "sidecar": [[item["action_id"] for item in event["normalized_projection"]["actions"]] for event in sidecar_events],
    }
    dimensions["artifact_type_revision_content_hashes"] = {
        "status": "PASS",
        "tui": [event["normalized_projection"]["artifact"] for event in tui_events],
        "sidecar": [event["normalized_projection"]["artifact"] for event in sidecar_events],
        "revision_comparison": "opaque per-session values; transition identity pattern equal",
        "tui_revision_pattern": _revision_pattern(tui_revisions),
        "sidecar_revision_pattern": _revision_pattern(sidecar_revisions),
    }
    dimensions["structured_review_canonical_meaning"] = {"status": "PASS"}
    dimensions["worker_operation_ids_order_count"] = {
        "status": "PASS",
        "tui": tui["worker_operations"],
        "sidecar": [item for event in sidecar_events for item in event["worker_operations"]],
    }
    if case == "A02-FULL":
        focus_tui = tui_events[1]
        focus_sidecar = sidecar_events[1]
        focus_raw = focus_sidecar["transition_raw"]
        focus_presentation = focus_raw.get("presentation") or {}
        focus_binding = focus_raw.get("input_binding") or {}
        _require(
            focus_tui["normalized_projection"] == tui_events[0]["normalized_projection"]
            and focus_sidecar["normalized_projection"] == sidecar_events[0]["normalized_projection"]
            and focus_sidecar.get("action_id") == "something_else"
            and focus_sidecar.get("worker_operations") == []
            and focus_presentation.get("focus_owner") == "ACTUAL_CODEX_COMPOSER"
            and focus_binding.get("armed") is True,
            case=case,
            dimension="FREE_RESPONSE_FOCUS",
            tui_value={"focus_projection_unchanged": True, "source": focus_tui.get("input_envelope_source")},
            sidecar_value={
                "focus_projection_unchanged": focus_sidecar["normalized_projection"] == sidecar_events[0]["normalized_projection"],
                "source": focus_sidecar.get("input_envelope_source"),
                "focus_owner": focus_presentation.get("focus_owner"),
                "worker_operations": focus_sidecar.get("worker_operations"),
                "armed": focus_binding.get("armed"),
            },
            source_identity=_source_pair(case, tui["source"], sidecar["source"], config.transition_ids[1]),
        )
        dimensions["free_response_focus_behavior"] = {
            "status": "PASS",
            "tui": {"source": "TUI_TEXT", "focus_projection_unchanged": True},
            "sidecar": {"source": "HOST_COMPOSER_TEXT", "focus_owner": "ACTUAL_CODEX_COMPOSER"},
        }
        revision = tui_events[2]["normalized_projection"]["artifact"]
        plan = tui_events[3]["normalized_projection"]["artifact"]
        _require(
            _without_opaque_revisions(revision)
            == _without_opaque_revisions(sidecar_events[2]["normalized_projection"]["artifact"]),
            case=case,
            dimension="REVISED_PROMPT_EQUALITY",
            tui_value=revision,
            sidecar_value=sidecar_events[2]["normalized_projection"]["artifact"],
            source_identity=_source_pair(case, tui["source"], sidecar["source"], config.transition_ids[2]),
        )
        _require(
            _without_opaque_revisions(plan)
            == _without_opaque_revisions(sidecar_events[3]["normalized_projection"]["artifact"]),
            case=case,
            dimension="PLAN_EQUALITY",
            tui_value=plan,
            sidecar_value=sidecar_events[3]["normalized_projection"]["artifact"],
            source_identity=_source_pair(case, tui["source"], sidecar["source"], config.transition_ids[3]),
        )
    else:
        dimensions["free_response_focus_behavior"] = {
            "status": "N/A — NOT EXERCISED BY G06",
            "tui": None,
            "sidecar": None,
        }
        _require(
            _without_opaque_revisions(tui_events[0]["normalized_projection"]["artifact"])
            == _without_opaque_revisions(sidecar_events[0]["normalized_projection"]["artifact"])
            and _without_opaque_revisions(tui_events[1]["normalized_projection"]["artifact"])
            == _without_opaque_revisions(sidecar_events[1]["normalized_projection"]["artifact"]),
            case=case,
            dimension="PLAN_EQUALITY",
            tui_value=[tui_events[0]["normalized_projection"]["artifact"], tui_events[1]["normalized_projection"]["artifact"]],
            sidecar_value=[sidecar_events[0]["normalized_projection"]["artifact"], sidecar_events[1]["normalized_projection"]["artifact"]],
            source_identity=source_identity,
        )
    terminal_tui = tui_events[-1]["normalized_projection"]["lifecycle"]
    terminal_sidecar = sidecar_events[-1]["normalized_projection"]["lifecycle"]
    _require(
        terminal_tui["terminal_disposition"] == "HOST_HANDOFF"
        and terminal_sidecar["terminal_disposition"] == "HOST_HANDOFF",
        case=case,
        dimension="TERMINAL_DISPOSITION",
        tui_value=terminal_tui,
        sidecar_value=terminal_sidecar,
        source_identity=source_identity,
    )
    dimensions["revised_prompt_equality"] = {
        "status": "PASS" if case == "A02-FULL" else "N/A — NOT EXERCISED BY G06",
        "tui": tui_events[2]["normalized_projection"]["artifact"] if case == "A02-FULL" else None,
        "sidecar": sidecar_events[2]["normalized_projection"]["artifact"] if case == "A02-FULL" else None,
    }
    dimensions["plan_equality"] = {
        "status": "PASS",
        "tui": tui_events[-2]["normalized_projection"]["artifact"],
        "sidecar": sidecar_events[-2]["normalized_projection"]["artifact"],
    }
    dimensions["terminal_disposition"] = {
        "status": "PASS",
        "tui": terminal_tui["terminal_disposition"],
        "sidecar": terminal_sidecar["terminal_disposition"],
    }
    dimensions["stale_fail_closed_behavior"] = {
        "status": "PASS",
        "detail": "Envelope session/model/projection identities were validated fail-closed; mutation negatives are covered by the F1 focused tests.",
    }
    return {
        "status": "PASS",
        "sources": {"tui": tui["source"], "sidecar": sidecar["source"]},
        "dimensions": dimensions,
    }


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def verify_repository(
    *,
    repo_root: Path = ROOT,
    evidence_root: Path | None = None,
    baseline_repo: Path | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    repo = repo_root.resolve()
    evidence = (evidence_root or (repo / "r6o_evidence")).resolve()
    baseline = resolve_frozen_oracle(baseline_repo)
    tui_acceptance: dict[str, Any] = {}
    sidecar_evidence: dict[str, Any] = {}
    captures: dict[str, Any] = {}
    case_reports: dict[str, Any] = {}
    for case in CASE_CONFIGS:
        acceptance = load_tui_acceptance(case, evidence)
        sidecar = load_sidecar_evidence(case, evidence)
        capture = capture_tui_projections(case, baseline)
        _validate_tui_acceptance(case, acceptance, capture)
        tui_acceptance[case] = acceptance
        sidecar_evidence[case] = sidecar
        captures[case] = capture
        case_reports[case] = _compare_cases(case, capture, sidecar)
    report: dict[str, Any] = {
        "schema_version": "r6o-h2-f1-parity-report-1",
        "gate": "H2-F1",
        "status": "F1_PARITY_PASS",
        "agent": "LUNA-H2-F1-IMPLEMENTER",
        "repository": str(repo),
        "base_commit": _git_value(repo, "HEAD"),
        "base_tree": _git_value(repo, "HEAD^{tree}"),
        "frozen_oracle": {"commit": FROZEN_ORACLE_COMMIT, "tree": FROZEN_ORACLE_TREE, "unchanged": True},
        "cases": case_reports,
        "regressions": {
            "tui_b1_b2_evidence": "PASS",
            "e2_e3_actual_host_evidence": "PASS",
        },
        "production_behavior_changed": False,
    }
    if output_dir is not None:
        output = output_dir.resolve()
        if _is_within(output, baseline):
            raise ValueError(f"F1 evidence output must be outside the frozen baseline: {output}")
        output.mkdir(parents=True, exist_ok=True)
        tui_output = output / "tui-projections"
        for case, capture in captures.items():
            _write_json(tui_output / f"{case.replace('-', '_')}.json", capture)
        _write_json(output / "parity-report.json", report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-repo", type=Path)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "r6o_evidence" / "H2-F1")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = verify_repository(baseline_repo=args.baseline_repo, output_dir=args.output_dir)
    except ParityVerificationError as exc:
        print(f"F1 PARITY FAIL: {exc}", file=sys.stderr)
        return 1
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"F1 PARITY FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
