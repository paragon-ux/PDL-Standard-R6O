from __future__ import annotations

"""Mechanical lifecycle projections: CloseResult and HandoffEnvelope.

Deterministic compilers over authoritative controller state. No LLM call.
"""

import json
import tempfile
import uuid
from pathlib import Path
from typing import Any

from r6o.model_binding.base import ArtifactSnapshot


def _disposition(stage: str) -> str:
    if stage in {"EXECUTION_READY", "CLOSED_SUCCESS"}:
        return "HOST_HANDOFF"
    if stage == "CLOSED_CANCELLED":
        return "CANCELLED"
    return "PDLT_RESUME"


def build_close_result(terminal_state: dict[str, Any], *, result_id: str | None = None, handoff_ref: str | None = None) -> dict[str, Any]:
    stage = str(terminal_state.get("stage", "UNKNOWN"))
    return {
        "schema_version": "r6o-close-result-1",
        "session_id": terminal_state.get("instance_id") or "session",
        "result_id": result_id or f"close-{uuid.uuid4().hex[:12]}",
        "disposition": _disposition(stage),
        "model_revision": terminal_state.get("revision") or "authoritative",
        "handoff_ref": handoff_ref,
        "reason_code": None,
    }


def build_handoff_envelope(terminal_state: dict[str, Any], artifacts: list[ArtifactSnapshot], *, handoff_id: str | None = None) -> dict[str, Any]:
    disposition = _disposition(str(terminal_state.get("stage", "UNKNOWN")))
    if disposition != "HOST_HANDOFF":
        raise ValueError(f"handoff requires HOST_HANDOFF disposition, got {disposition}")
    execution_request: dict[str, Any] | None = None
    result_body = terminal_state.get("result") or terminal_state.get("execution_result")
    if result_body is not None:
        execution_request = {"result_body": result_body}
    elif terminal_state.get("stage") == "EXECUTION_READY":
        execution_request = {"state": "EXECUTION_READY"}
    return {
        "schema_version": "r6o-handoff-envelope-1",
        "handoff_id": handoff_id or f"handoff-{uuid.uuid4().hex[:12]}",
        "session_id": terminal_state.get("instance_id") or "session",
        "workspace_id": terminal_state.get("workspace_id"),
        "source_model_revision": terminal_state.get("revision") or "authoritative",
        "disposition": "HOST_HANDOFF",
        "artifacts": [
            {
                "artifact_ref": a.artifact_ref,
                "artifact_revision": a.artifact_revision,
                "artifact_kind": a.artifact_kind,
                "body": a.body,
            }
            for a in artifacts
        ],
        "execution_request": execution_request,
        "created_at": None,
    }


def write_handoff(path: Path, envelope: dict[str, Any]) -> str:
    """Persist a handoff durably before CloseResult(HOST_HANDOFF) is emitted."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with open(fd, "w", encoding="utf-8") as handle:
            json.dump(envelope, handle, ensure_ascii=False, indent=2)
        Path(tmp).replace(path)
    finally:
        if Path(tmp).exists():
            Path(tmp).unlink(missing_ok=True)
    return str(path)
