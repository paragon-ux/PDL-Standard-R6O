from __future__ import annotations

"""Pure FocusProjection construction from normalized Model Port snapshots."""

import hashlib
import json
from typing import Any

from r6o.viewmodel.actions import ACTION_MAPPING_VERSION, project_actions
from r6o.viewmodel.model_port import ArtifactSnapshot, ModelPort, ModelStateSnapshot

_FOCUS_KIND = {
    "PROMPT_REVIEW": "PROMPT_REVIEW",
    "PLAN_REVIEW": "PLAN_REVIEW",
    "WAITING_INPUT": "WAITING_INPUT",
    "EXECUTION_READY": "HANDOFF_READY",
    "CLOSED_SUCCESS": "CLOSED",
    "CLOSED_CANCELLED": "CANCELLED",
}


def _artifact_dict(snapshot: ArtifactSnapshot | None) -> dict[str, Any] | None:
    return snapshot.to_dict() if snapshot else None


def _fingerprint(state: ModelStateSnapshot, artifact: ArtifactSnapshot | None, actions: list[dict[str, Any]]) -> str:
    material = {
        "schema_version": "r6o-focus-projection-1",
        "action_mapping_version": ACTION_MAPPING_VERSION,
        "model_revision": state.model_revision,
        "artifact_ref": artifact.artifact_ref if artifact else None,
        "artifact_revision": artifact.artifact_revision if artifact else None,
        "actions": actions,
    }
    canonical = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "projection-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_focus_projection(
    state: ModelStateSnapshot,
    artifact: ArtifactSnapshot | None,
) -> dict[str, Any]:
    actions = project_actions(state.stage)
    return {
        "schema_version": "r6o-focus-projection-1",
        "session_id": state.session_id,
        "workspace_id": state.workspace_id,
        "model_revision": state.model_revision,
        "projection_id": _fingerprint(state, artifact, actions),
        "interaction_state": state.interaction_state,
        "stage": state.stage,
        "focus_kind": _FOCUS_KIND.get(state.stage),
        "artifact": _artifact_dict(artifact),
        "actions": actions,
        "lifecycle": state.lifecycle.to_dict(),
    }


def build_focus_projection_from_port(port: ModelPort, session_id: str) -> dict[str, Any]:
    state = port.read_state(session_id)
    subject = state.review_subject
    artifact = (
        port.read_artifact(session_id, subject.artifact_ref, subject.artifact_revision)
        if subject
        else None
    )
    return build_focus_projection(state, artifact)
